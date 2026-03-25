import os
import io
import re
import json
import time
import asyncio
from tqdm import tqdm
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from neuraworkbench.src.prompt_templates import load_prompt_template
from neuraworkbench.src.llm_interface import (single_prompt_sync_v2, chat_with_backoff_and_fallback,
                                              completion_with_backoff)

#####################################################
#                  Global Variables                 #
#####################################################
pass


#####################################################
#                 Code Base Tree                    #
#####################################################
def print_directory_tree(startpath, prefix="", relpath="", exclude_list=None, comments=None, tree=""):
    if exclude_list is None:
        exclude_list = []
    if comments is None:
        comments = {}

    items = sorted(os.listdir(startpath))
    # Exclude items by name
    items = [item for item in items if item not in exclude_list]
    files = [f for f in items if os.path.isfile(os.path.join(startpath, f))]
    dirs = [d for d in items if os.path.isdir(os.path.join(startpath, d))]
    entries = dirs + files

    for idx, entry in enumerate(entries):
        path = os.path.join(startpath, entry)
        rel = os.path.join(relpath, entry) if relpath else entry
        is_last = idx == len(entries) - 1
        branch = "└── " if is_last else "├── "
        spacer = "    " if is_last else "│   "
        comment = " " + comments.get(rel, "")
        print(prefix + branch + entry + comment)
        if os.path.isdir(path):
            print_directory_tree(path, prefix + spacer, rel, exclude_list, comments, tree)


def build_directory_tree(startpath, prefix="", relpath="", exclude_list=None, comments=None):
    if exclude_list is None:
        exclude_list = []
    if comments is None:
        comments = {}

    tree_lines = []
    items = sorted(os.listdir(startpath))

    # Exclude items by name
    items = [item for item in items if item not in exclude_list]
    files = [f for f in items if os.path.isfile(os.path.join(startpath, f))]
    dirs = [d for d in items if os.path.isdir(os.path.join(startpath, d))]
    entries = dirs + files

    for idx, entry in enumerate(entries):
        path = os.path.join(startpath, entry)
        rel = os.path.join(relpath, entry) if relpath else entry
        is_last = idx == len(entries) - 1
        branch = "└── " if is_last else "├── "
        spacer = "    " if is_last else "│   "
        comment = " " + comments.get(rel, "")

        # instead of print(), append to list
        tree_lines.append(prefix + branch + entry + comment)

        if os.path.isdir(path):
            tree_lines.extend(
                build_directory_tree(path, prefix + spacer, rel, exclude_list, comments)
            )

    return tree_lines


#####################################################
#                 Code Base Summary                 #
#####################################################
def collect_text_files(startpath, exclude_list=None, extensions=None):
    """
    Recursively collect all text files with specified extensions from a directory, excluding specified files/folders.

    Args:
        startpath (str): Root directory to scan.
        exclude_list (list): List of folder or file names to exclude (anywhere in the tree).
        extensions (list): List of allowed file extensions (e.g., ['.py', '.md']). If None, all files are included.

    Returns:
        dict: {relative_path: file_content, ...}
    """
    if exclude_list is None:
        exclude_list = []
    if extensions is not None:
        # Normalize extensions (force lower case, start with ".")
        extensions = [ext if ext.startswith('.') else f".{ext}" for ext in extensions]
        extensions = set([ext.lower() for ext in extensions])

    collected = {}

    def _collect(curr_path, rel_path=""):
        items = sorted(os.listdir(curr_path))
        items = [item for item in items if item not in exclude_list]
        for item in items:
            abs_item = os.path.join(curr_path, item)
            rel_item = os.path.join(rel_path, item) if rel_path else item
            if os.path.isdir(abs_item):
                _collect(abs_item, rel_item)
            else:
                # Only include files with the desired extensions
                if (extensions is None) or (os.path.splitext(item)[1].lower() in extensions):
                    try:
                        with open(abs_item, "r", encoding="utf-8") as f:
                            collected[rel_item] = f.read()
                    except Exception as e:
                        print(f"Could not read {rel_item}: {e}")

    _collect(startpath)
    return collected


def _should_include_file(filename, extensions):
    if extensions is None:
        return True
    ext = os.path.splitext(filename)[1].lower()
    return ext in extensions


def get_folder_prompt(dir_tree, folder_relpath, files_info, folders_info):
    """Default Markdown content for generation of folder summaries."""
    title = folder_relpath or "."
    lines = [f"# Directory Tree", f"{dir_tree}\n", f"# Content of `{title}`", ""]
    if files_info:
        lines.append("## Files")
        for f in files_info:
            lines.append(f"- **{f['name']}**\n{f['summary']}")
        lines.append("")
    if folders_info:
        lines.append("## Sub-folders")
        for d in folders_info:
            lines.append(f"- **{d['name']}/**\n{d['summary']}")
        lines.append("")

    return "\n".join(lines)


async def summarize_codebase(
        source_root,
        output_root,
        dir_tree,
        exclude_list=None,
        extensions=None,
        naming="append",  # "append" -> foo.py.md, "replace" -> foo.md
        encoding="utf-8",
        summary_model="gpt-4o"
):
    """
    Mirror the source_root and generate:
      - one Markdown summary per included file; and
      - one README.md per folder that summarizes its files and sub-folders.

    Folder summaries are computed bottom-up so each folder can incorporate
    sub-folder summaries.

    Args:
        source_root (str)
        output_root (str)
        dir_tree (str): Directory tree of the code base
        exclude_list (list[str])
        extensions (list[str]|None)
        naming (str): "append" or "replace" for file summary filenames
        encoding (str)
        summary_model (str): OpenAI model used to summarize
    """
    if exclude_list is None:
        exclude_list = []

    # Normalize extensions
    if extensions is not None:
        extensions = [ext if ext.startswith('.') else f".{ext}" for ext in extensions]
        extensions = set([ext.lower() for ext in extensions])

    # Map to hold computed folder summaries keyed by relative folder path ('' for root)
    folder_summary_cache = {}
    # Ensure output root exists
    os.makedirs(output_root, exist_ok=True)

    # --- Cache setup ---
    cache_path = os.path.join(output_root, ".summary_cache.json")
    try:
        with open(cache_path, "r", encoding="utf-8") as _cf:
            cache = json.load(_cf)
    except Exception:
        cache = {}
    # cache schema:
    #   cache[rel_path] = {"type": "file"|"folder", "mtime": float, "md_rel": "relative/path/to/summary.md"}
    changed_paths = set()  # paths (files/folders) whose summaries changed this run
    seen_files = set()  # rel file paths that currently exist and are included
    seen_folders = set()  # rel folder paths that currently exist ('' for root)

    # Walk bottom-up so subfolders are processed before their parents
    for curr_dir, subdirs, files in os.walk(source_root, topdown=False):
        # relative folder path like "src/foo" or "" for root
        folder_rel = os.path.relpath(curr_dir, start=source_root)
        if folder_rel == ".":
            folder_rel = ""
        seen_folders.add(folder_rel)

        # Skip any folder that is or is inside an excluded directory
        parts = folder_rel.split(os.sep) if folder_rel else []
        if any(part in exclude_list for part in parts):
            continue
        # Filter subdirs and files by exclude_list
        subdirs[:] = [d for d in subdirs if d not in exclude_list]
        files = [f for f in files if f not in exclude_list and _should_include_file(f, extensions)]

        print(f"\nEntering folder: {curr_dir}")

        # --- 1) File summaries for files directly in this folder ---
        files_info = []
        for filename in tqdm(sorted(files)):
            abs_path = os.path.join(curr_dir, filename)
            rel_path = os.path.join(folder_rel, filename) if folder_rel else filename
            seen_files.add(rel_path)

            base, ext = os.path.splitext(rel_path)
            if naming == "replace":
                md_rel = f"{base}.md"  # src/foo/bar.md
            else:
                md_rel = f"{rel_path}.md"  # src/foo/bar.py.md

            out_abs = os.path.join(output_root, md_rel)
            os.makedirs(os.path.dirname(out_abs), exist_ok=True)

            # Incremental check via mtime + presence of existing md
            try:
                src_mtime = os.path.getmtime(abs_path)
            except Exception:
                src_mtime = 0.0
            cached = cache.get(rel_path)
            has_current_summary = os.path.exists(out_abs)
            must_regen = not (cached and cached.get("type") == "file" and has_current_summary and abs(
                cached.get("mtime", -1) - src_mtime) < 1e-6)

            if not must_regen:
                # Reuse existing summary to feed folder summarization
                try:
                    with open(out_abs, "r", encoding=encoding) as f:
                        summary_md = f.read()
                except Exception:
                    # If reuse fails, fall back to regeneration
                    must_regen = True

            if must_regen:
                # Read + summarize file
                try:
                    with open(abs_path, "r", encoding=encoding) as f:
                        content = f.read()
                except Exception as e:
                    print(f"[WARN] Could not read {rel_path}: {e}")
                    continue

                try:
                    file_system_prompt = load_prompt_template("code_file_summary", "system_prompt")
                    file_user_prompt = (f"# Directory Tree:\n"
                                        f"{dir_tree}\n\n"
                                        f"File Path:\n"
                                        f"{rel_path}\n\n"
                                        f"File Content:\n"
                                        f"{content}")
                    summary_md = await completion_with_backoff(file_system_prompt, file_user_prompt, summary_model)
                    if not isinstance(summary_md, str):
                        summary_md = str(summary_md)
                except Exception as e:
                    print(f"[WARN] Summarizer failed for {rel_path}: {e}")
                    continue

                # Write file summary
                try:
                    with open(out_abs, "w", encoding=encoding, newline="\n") as f:
                        f.write(summary_md)
                except Exception as e:
                    print(f"[WARN] Could not write summary {md_rel}: {e}")
                    continue

                # Update cache + changed set
                cache[rel_path] = {"type": "file", "mtime": src_mtime, "md_rel": md_rel}
                changed_paths.add(rel_path)

            files_info.append({"name": filename, "summary": summary_md, "rel": rel_path})

        # --- 2) Gather immediate sub-folder summaries (already computed) ---
        folders_info = []
        for d in sorted(subdirs):
            child_rel = os.path.join(folder_rel, d) if folder_rel else d
            child_summary = folder_summary_cache.get(child_rel, "")
            # If the child summary wasn't created (empty folder?), still include name
            folders_info.append({"name": d, "summary": child_summary, "rel": child_rel})

        # --- 3) Build this folder's README from file + subfolder summaries ---
        folder_name = os.path.basename(curr_dir.rstrip(os.sep)) or "root"
        out_folder_abs = os.path.join(output_root, folder_rel) if folder_rel else output_root
        os.makedirs(out_folder_abs, exist_ok=True)
        folder_summary_filename = f"{folder_name}.md"
        readme_abs = os.path.join(out_folder_abs, folder_summary_filename)
        folder_cached = cache.get(folder_rel)
        has_folder_summary = os.path.exists(readme_abs)

        # Decide whether folder summary must be (re)generated
        # A folder needs regeneration if:
        #  - it has no cached entry or file is missing, OR
        #  - any immediate child file/child folder changed, OR
        #  - we want to force-refresh because inputs changed
        immediate_children_changed = any(
            (os.path.join(folder_rel, f) if folder_rel else f) in changed_paths for f in files
        ) or any(
            (os.path.join(folder_rel, d) if folder_rel else d) in changed_paths for d in subdirs
        )
        must_regen_folder = not (folder_cached and folder_cached.get("type") == "folder" and has_folder_summary)
        must_regen_folder = must_regen_folder or immediate_children_changed

        if must_regen_folder:
            print(f"\t- Generate folder summary")
            try:
                folder_system_prompt = load_prompt_template("code_folder_summary", "system_prompt")
                folder_user_prompt = get_folder_prompt(dir_tree, folder_rel, files_info, folders_info)
                folder_md = await completion_with_backoff(folder_system_prompt, folder_user_prompt, summary_model)
                if not isinstance(folder_md, str):
                    folder_md = str(folder_md)
            except Exception as e:
                print(f"[WARN] Folder summarizer failed for '{folder_rel or '.'}': {e}")
                folder_md = f"# Summary of `{folder_rel or '.'}`\n\n(Generation failed.)\n"

            # Write folder README
            try:
                with open(readme_abs, "w", encoding=encoding, newline="\n") as f:
                    f.write(folder_md)
            except Exception as e:
                print(f"[WARN] Could not write folder README {os.path.join(folder_rel, folder_summary_filename)}: {e}")

            # Cache for parent folders to consume
            folder_summary_cache[folder_rel] = folder_md

            # Update folder cache + changed set
            cache[folder_rel] = {
                "type": "folder",
                "mtime": time.time(),  # we track "built at" for folder
                "md_rel": os.path.relpath(readme_abs, start=output_root)
            }
            changed_paths.add(folder_rel)
        else:
            # Reuse existing folder summary for parent aggregation
            try:
                with open(readme_abs, "r", encoding=encoding) as f:
                    folder_md = f.read()
            except Exception as e:
                print(f"[WARN] Could not read existing folder README for '{folder_rel or '.'}': {e}")
                folder_md = f"# Summary of `{folder_rel or '.'}`\n\n(Existing summary could not be read.)\n"
            folder_summary_cache[folder_rel] = folder_md
            # keep existing cache entry intact

    # --- Deletions: remove summaries for files/folders that no longer exist ---
    # Build helpers to compute expected md path from rel path/type
    def _file_md_rel_from_rel_path(rel_path):
        base, ext = os.path.splitext(rel_path)
        return f"{base}.md" if naming == "replace" else f"{rel_path}.md"

    stale_keys = []
    for rel_path, meta in list(cache.items()):
        if meta.get("type") == "file":
            if rel_path not in seen_files:
                # delete summary file if exists
                md_rel = meta.get("md_rel") or _file_md_rel_from_rel_path(rel_path)
                out_abs = os.path.join(output_root, md_rel)
                try:
                    if os.path.exists(out_abs):
                        os.remove(out_abs)
                except Exception as e:
                    print(f"[WARN] Could not remove stale file summary {md_rel}: {e}")
                stale_keys.append(rel_path)
        elif meta.get("type") == "folder":
            if rel_path not in seen_folders:
                md_rel = meta.get("md_rel") or os.path.join(rel_path,
                                                            (os.path.basename(rel_path) or "root") + ".md")
                out_abs = os.path.join(output_root, md_rel)
                try:
                    if os.path.exists(out_abs):
                        os.remove(out_abs)
                except Exception as e:
                    print(f"[WARN] Could not remove stale folder summary {md_rel}: {e}")
                stale_keys.append(rel_path)
    for k in stale_keys:
        cache.pop(k, None)

    # --- Persist cache ---
    try:
        with open(cache_path, "w", encoding="utf-8") as _cf:
            json.dump(cache, _cf, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Could not write cache file {cache_path}: {e}")

    print(f"✅ File and folder summaries written under: {output_root}")


#####################################################
#              Summary and Code Export              #
#####################################################
def remove_top_level_heading(text: str) -> str:
    """
    Removes a leading '# ...' Markdown headline if present.
    Only removes the *first* line if it is a level-1 heading.
    """
    lines = text.lstrip().splitlines()

    if lines and re.match(r"^#\s+.+", lines[0]):
        return "\n".join(lines[1:]).lstrip("\n")
    return text


def export_codebase_markdown(
        source_root: str,
        summaries_root: str,
        output_markdown_path: str,
        dir_tree: str | None = None,
        include_folder_summaries: bool = True,
        include_file_summaries: bool = False,
        include_code: bool = False,
        subpaths: Optional[List[str]] = None,  # limit to these folders/files (relative)
        files: Optional[List[str]] = None,  # explicit files (relative) to include
        title: Optional[str] = None,  # doc title
        encoding: str = "utf-8",
):
    src = Path(source_root).resolve()
    sums = Path(summaries_root).resolve()
    out = Path(output_markdown_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if dir_tree is not None:
        include_tree = True
    else:
        include_tree = False

    # Assemble document
    buf = io.StringIO()
    repo_name = src.name
    doc_title = title or f"{repo_name} · Export Bundle"

    buf.write(f"# {doc_title}\n\n")
    buf.write("> Generated for interactive code comprehension & editing sessions.\n\n")

    # Optional index
    toc = []
    if include_tree:
        toc.append("- [Directory Tree](#directory-tree)")
    if include_folder_summaries:
        toc.append("- [Folder Summaries](#folder-summaries)")
    if include_file_summaries:
        toc.append("- [File Summaries](#file-summaries)")
    if include_code:
        toc.append("- [Source Code](#source-code)")
    if toc:
        buf.write("## Table of Contents\n")
        buf.write("\n".join(toc) + "\n\n")

    # Directory Tree
    if include_tree:
        buf.write("## Directory Tree\n\n")
        tree_md = dir_tree
        buf.write("```text\n")
        buf.write(tree_md)
        buf.write("\n```\n\n")

    # Folder Summaries
    if include_folder_summaries:
        buf.write("## Folder Summaries\n\n")
        for dirpath, dirnames, _ in os.walk(summaries_root):
            rel_dir = os.path.relpath(dirpath, summaries_root)
            is_root = (rel_dir == ".")
            folder_name = str(sums).split("\\")[-1] if is_root else os.path.basename(dirpath)
            folder_display = "." if is_root else rel_dir.replace(os.sep, "/")

            buf.write(f"### {folder_display}/\n\n")

            # Try to find folder summary file: <foldername>.md
            folder_summary_filename = f"{folder_name}.md"
            folder_summary_path = os.path.join(dirpath, folder_summary_filename)
            if os.path.exists(folder_summary_path):
                with open(folder_summary_path, encoding=encoding) as f:
                    folder_summary = f.read().strip()
                if folder_summary:
                    buf.write(folder_summary.strip() + "\n\n")

    # File Summaries
    if include_file_summaries:
        buf.write("## File Summaries\n\n")
        for dirpath, dirnames, filenames in os.walk(summaries_root):
            rel_dir = os.path.relpath(dirpath, summaries_root)
            is_root = (rel_dir == ".")
            folder_name = str(sums).split("\\")[-1] if is_root else os.path.basename(dirpath)
            folder_display = "." if is_root else rel_dir.replace(os.sep, "/")

            # Try to find folder summary file: <foldername>.md
            folder_summary_filename = f"{folder_name}.md"

            # --- File summaries in this folder -----------------------------------
            # Any *.md that is NOT the folder summary is treated as a file summary.
            file_summary_filenames = sorted(
                fn for fn in filenames
                if fn.endswith(".md") and fn != folder_summary_filename
            )

            if file_summary_filenames:
                for fname in file_summary_filenames:
                    # Strip only the '.md' for display, keep original basename
                    display_name = fname[:-3]
                    file_summary_path = os.path.join(dirpath, fname)
                    with open(file_summary_path, encoding=encoding) as f:
                        file_summary = f.read().strip()

                    buf.write(f"### {display_name}\n\n")
                    if file_summary:
                        buf.write(remove_top_level_heading(file_summary) + "\n\n")

    # Write
    out.write_text(buf.getvalue(), encoding=encoding)
