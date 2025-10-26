import json
import os
import re
from typing import List

INTENDED_ADDR = "allo1cxvw0pu9nmpxku9acj5h2q3daq3m0jac5q6vma"
WALLET_REGEX = re.compile(r"allo1[a-z0-9]{20,}")


def replace_addresses_in_text(text: str) -> str:
    return WALLET_REGEX.sub(INTENDED_ADDR, text)


def scrub_text_file(path: str) -> bool:
    """Scrub a text-like file, being tolerant of common encodings (UTF-8/UTF-16)."""
    encodings_to_try = [
        "utf-8",
        "utf-8-sig",  # UTF-8 with BOM
        "utf-16",
        "utf-16-le",
        "utf-16-be",
    ]
    content = None
    used_encoding = None
    for enc in encodings_to_try:
        try:
            with open(path, "r", encoding=enc) as f:
                content = f.read()
            used_encoding = enc
            break
        except (UnicodeDecodeError, OSError, IOError):
            continue
    if content is None:
        return False

    new_content = replace_addresses_in_text(content)
    if new_content != content:
        try:
            with open(path, "w", encoding=used_encoding or "utf-8") as f:
                f.write(new_content)
            return True
        except (OSError, IOError):
            return False
    return False


def scrub_notebook(path: str) -> bool:
    changed = False
    try:
        with open(path, "r", encoding="utf-8") as f:
            nb = json.load(f)
        cells: List[dict] = nb.get("cells", [])
        for cell in cells:
            # Clear execution counts and outputs
            if cell.get("cell_type") == "code":
                if cell.get("outputs"):
                    cell["outputs"] = []
                    changed = True
                if cell.get("execution_count") is not None:
                    cell["execution_count"] = None
                    changed = True
            # Replace occurrences in source
            if isinstance(cell.get("source"), list):
                new_source = []
                modified = False
                for line in cell["source"]:
                    new_line = replace_addresses_in_text(line)
                    if new_line != line:
                        modified = True
                    new_source.append(new_line)
                if modified:
                    cell["source"] = new_source
                    changed = True
        if changed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(nb, f, ensure_ascii=False)
    except (OSError, IOError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return changed


def main() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    exts_text = {".py", ".ps1", ".md", ".toml", ".txt", ".json", ".yml", ".yaml", ".log", ".csv"}
    changed_files = []
    for root, _, files in os.walk(repo_root):
        # Skip venvs and caches
        if any(skip in root for skip in (".venv", "venv", "__pycache__", ".git")):
            continue
        for name in files:
            path = os.path.join(root, name)
            _, ext = os.path.splitext(name.lower())
            if ext in exts_text:
                if scrub_text_file(path):
                    changed_files.append(path)
            elif ext == ".ipynb":
                if scrub_notebook(path):
                    changed_files.append(path)
    if changed_files:
        print("Scrubbed files:")
        for p in changed_files:
            print(f" - {os.path.relpath(p, repo_root)}")
    else:
        print("No changes needed. Repo is clean.")


if __name__ == "__main__":
    main()
