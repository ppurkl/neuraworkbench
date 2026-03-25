import os
import re
import fitz
from PyPDF2 import PdfReader

from neuraworkbench.src.llm_interface import image_prompt_sync
from neuraworkbench.src.prompt_templates import load_prompt_template


def pdf_to_images(pdf_path: str, images_dir: str):
    """
    Render all pages of a PDF file to PNG images inside `images_dir`.
    Filenames: page1.png, page2.png, ...
    """
    os.makedirs(images_dir, exist_ok=True)
    pdf_file = fitz.open(pdf_path)

    # remove the last element (the PDF file name)
    # pdf_folder_path = pdf_path.split("\\")[:-1]
    # pdf_folder_path = "\\".join(pdf_folder_path)
    # os.makedirs(f"{pdf_folder_path}\\images", exist_ok=True)

    # iterate over PDF pages
    for page_index in range(len(pdf_file)):
        page = pdf_file.load_page(page_index)  # load the page
        print(f"[+] Generating image of page {page_index+1} ...")

        pix = page.get_pixmap()
        page_png_name = f"page{page_index + 1}.png"
        page_png_path = os.path.join(images_dir, page_png_name)
        pix.save(page_png_path)


# regex to extract numbers from filename
def extract_number(filename):
    match = re.search(r'\d+', filename)
    return int(match.group()) if match else float('inf')


def analyze_presentation_pdf(pdf_path: str) -> None:
    """
    For a given PDF presentation:
      - Create a folder named after the PDF (without extension).
      - Inside that folder, create:
          - images/     -> PNG images of each slide
          - summaries/  -> one Markdown file per slide with the summary
      - For each slide:
          - Extract the page text from the PDF
          - Send image + text to `image_prompt_sync`
          - Store the returned summary in summaries/slide_XX.md
    """

    # --- Prepare folders -----------------------------------------------------
    base_dir = os.path.dirname(pdf_path)
    pdf_filename = os.path.basename(pdf_path)
    pdf_stem, _ = os.path.splitext(pdf_filename)

    # Folder named after PDF file
    presentation_dir = os.path.join(base_dir, pdf_stem)
    images_dir = os.path.join(presentation_dir, "images")
    summaries_dir = os.path.join(presentation_dir, "summaries")

    os.makedirs(presentation_dir, exist_ok=True)
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(summaries_dir, exist_ok=True)

    print(f"[+] Working directory for this PDF: {presentation_dir}")

    # --- Step 1: render slides to images ------------------------------------
    pdf_to_images(pdf_path, images_dir)

    # --- Step 2: load PDF text ----------------------------------------------
    pdf_reader = PdfReader(pdf_path)
    num_pages = len(pdf_reader.pages)
    print(f"[+] Loaded PDF with {num_pages} pages")

    # --- Step 3: collect & sort slide images --------------------------------
    slide_imgs = [f for f in os.listdir(images_dir) if f.lower().endswith(".png")]
    slide_imgs = sorted(slide_imgs, key=extract_number)

    # --- Step 4: run over images + text -------------------------------------
    for slide_idx, img_name in enumerate(slide_imgs):
        if slide_idx >= num_pages:
            # Safety check: more images than pages (shouldn't normally happen)
            print(f"[!] More images than PDF pages, stopping at page {num_pages}")
            break

        # Text for this page
        page = pdf_reader.pages[slide_idx]
        page_text = page.extract_text() or ""  # avoid None

        # Image path
        image_path = os.path.join(images_dir, img_name)

        print(f"\n[+] Generating summary of slide {slide_idx + 1} ...")

        # Variant A: single combined prompt (works with your current signature)
        content_prompt = f"Full text of this slide:\n{page_text}"

        slide_system_prompt = load_prompt_template("slide_summary", "system_prompt")

        slide_summary = image_prompt_sync(
            image_path=image_path,
            system_prompt=slide_system_prompt,
            user_prompt=content_prompt,
            model="gpt-5.1"
        )

        # --- Step 5: store summary per slide --------------------------------
        summary_filename = f"slide_{slide_idx + 1}.md"
        summary_path = os.path.join(summaries_dir, summary_filename)

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(slide_summary)

        print(f"[+] Saved summary to: {summary_path}")


def get_clean_summary(text: str) -> str:
    """
    Remove surrounding ```markdown / ```md / ```...``` fences
    and return the inner content as plain markdown.
    """
    if text is None:
        return ""

    # Strip outer whitespace first
    text = text.strip()

    # Case 1: whole text is a single fenced block: ```lang\n ... \n```
    fenced_pattern = r'^```[a-zA-Z0-9_-]*\s*\n(.*?)\n```$'
    m = re.match(fenced_pattern, text, flags=re.DOTALL)
    if m:
        return m.group(1).strip()

    # Case 2: more “loose” fences at beginning / end
    text = re.sub(r'^```[a-zA-Z0-9_-]*\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)

    return text.strip()


def _extract_slide_number(filename: str) -> int:
    """
    Try to extract the first integer from the filename as slide number.
    If none is found, return a large number so these go to the end.
    """
    m = re.search(r'(\d+)', filename)
    if m:
        return int(m.group(1))
    return 10**9  # "infinite" so they sort last


def export_slide_summaries(summary_dir: str, output_path: str) -> None:
    """
    Reads all *.md / *.txt files from `summary_dir`, sorts them by slide number,
    cleans each summary (removing ```markdown fences, etc.), and writes them
    into one consolidated Markdown file.

    Output format:

    # Slide 1
    <summary for slide 1>

    # Slide 2
    <summary for slide 2>
    ...
    """
    # Collect all candidate summary files
    files = [
        f for f in os.listdir(summary_dir)
        if os.path.isfile(os.path.join(summary_dir, f))
        and f.lower().endswith((".md", ".txt"))
    ]

    # Sort by extracted slide number (e.g., slide_1.md, slide_2.md, ...)
    files.sort(key=_extract_slide_number)

    with open(output_path, "w", encoding="utf-8") as out_f:
        for idx, filename in enumerate(files, start=1):
            file_path = os.path.join(summary_dir, filename)

            with open(file_path, "r", encoding="utf-8") as in_f:
                raw = in_f.read()

            summary = get_clean_summary(raw)

            # Decide which slide number to show:
            slide_no = _extract_slide_number(filename)
            if slide_no == 10**9:
                slide_no = idx  # fallback if no number in filename

            out_f.write(f"# Slide {slide_no}\n")
            out_f.write(summary.rstrip() + "\n\n")

