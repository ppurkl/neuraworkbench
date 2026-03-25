import os

from neuraworkbench.src.presentation_processing import (
    analyze_presentation_pdf,
    export_slide_summaries,
)


def test_presentation_processing():
    # Insert the absolute path to the presentation PDF you want to process.
    slides_path = r"C:\INSERT\YOUR\PRESENTATION.pdf"

    # Replace the placeholder path above before running this example.
    if "INSERT\\YOUR" in slides_path:
        return

    base_dir = os.path.dirname(slides_path)
    pdf_filename = os.path.basename(slides_path)
    pdf_stem, _ = os.path.splitext(pdf_filename)
    presentation_dir = os.path.join(base_dir, pdf_stem)
    summaries_dir = os.path.join(presentation_dir, "summaries")

    analyze_presentation_pdf(slides_path)

    export_slide_summaries(summaries_dir, os.path.join(presentation_dir, pdf_stem + ".md"))


if __name__ == "__main__":
    test_presentation_processing()
