import asyncio

from neuraworkbench.src.code_processing import (
    build_directory_tree,
    collect_text_files,
    export_codebase_markdown,
    summarize_codebase,
)


def test_code_processing():
    # Insert the root folder of the codebase you want to summarize.
    code_base_root = r"C:\INSERT\YOUR\CODEBASE\ROOT"

    # Insert a folder where intermediate summaries should be written.
    summary_root = r"C:\INSERT\YOUR\SUMMARY\OUTPUT\FOLDER"

    # Insert the final Markdown export path.
    output_root = r"C:\INSERT\YOUR\OUTPUT\overview.md"

    # Replace the placeholder paths above before running this example.
    if "INSERT\\YOUR" in code_base_root or "INSERT\\YOUR" in summary_root or "INSERT\\YOUR" in output_root:
        return

    # Extensions only matter for the file collection.
    exts = []  # Add project-specific file extensions here if needed.
    exclude = []  # Add project-specific folders or files to exclude here.

    comments = {
        # "src": "# Main code",
        # "src/main.py": "# Entry point",
    }

    exclude_default = [
        ".git", ".gitignore", ".github", ".gitkeep", ".gitmodules",
        "__pycache__",
    ]
    exts_default = [
        ".txt", ".md",
        ".sv", ".v", ".vhd",
        ".jl", ".sh", ".tcl", ".do", ".py",
        ".c", ".h", ".cpp", ".hpp",
    ]
    exts = exts + exts_default
    exclude = exclude + exclude_default

    cb_tree = "\n".join(build_directory_tree(code_base_root, exclude_list=exclude, comments=comments))
    print(cb_tree)

    asyncio.run(
        summarize_codebase(
            code_base_root,
            summary_root,
            cb_tree,
            exclude_list=exclude,
            extensions=None,
            summary_model="gpt-5.2",
        )
    )

    export_codebase_markdown(
        code_base_root,
        summary_root,
        output_markdown_path=output_root,
        dir_tree=cb_tree,
        include_folder_summaries=True,
        include_file_summaries=True,
    )


if __name__ == "__main__":
    test_code_processing()
