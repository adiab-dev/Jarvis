import os
import shutil
from pathlib import Path


HARD_BLOCKED_PATHS = (r"C:\Windows",)
CONFIRMATION_PATHS = (
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\Users",
    r"C:\Lessons",
    r"C:\projects",
)


def _is_within(path: str, root: str) -> bool:
    path_key = os.path.normcase(os.path.normpath(path))
    root_key = os.path.normcase(os.path.normpath(root))
    try:
        return os.path.commonpath((path_key, root_key)) == root_key
    except ValueError:
        return False


def check_path_access(path: str) -> str:
    """Return allowed, confirmation_required, or blocked for a target path."""
    if not isinstance(path, str) or not path.strip():
        return "blocked"

    expanded = os.path.expandvars(os.path.expanduser(path.strip()))
    if not os.path.isabs(expanded):
        return "blocked"

    resolved = str(Path(expanded).resolve(strict=False))
    if Path(resolved).anchor and os.path.normcase(resolved) == os.path.normcase(Path(resolved).anchor):
        return "blocked"
    if any(_is_within(resolved, root) for root in HARD_BLOCKED_PATHS):
        return "blocked"
    if any(_is_within(resolved, root) for root in CONFIRMATION_PATHS):
        return "confirmation_required"
    return "allowed"


class Tools:
    def create(self, path: str, content: str = "", mode: str = "create", confirmed: bool = False):
        """
        Create, edit, or delete files and folders at an absolute path.

        Modes:
        - create: create a new file or folder; an existing file is left unchanged.
        - overwrite: replace all text in a file, creating the file if needed.
        - append: add text to the end of a file.
        - delete: permanently delete a file or a folder and all its contents.
          Deletion always requires approval from the user.

        C:\\Windows is always blocked. Other protected locations require the
        user's approval. Never claim success unless this tool confirms it.

        Examples:

        create(
            path="C:\\projects\\MyProject"
        )

        create(
            path="C:\\projects\\MyProject\\index.html",
            content="<h1>Hello</h1>",
            mode="create"
        )

        create(
            path="C:\\projects\\MyProject\\index.html",
            content="<h1>Updated</h1>",
            mode="overwrite"
        )

        create(
            path="C:\\projects\\log.txt",
            content="New line\\n",
            mode="append"
        )
        """

        if not isinstance(path, str) or not path.strip():
            return "Path must be a non-empty string"

        path = os.path.expandvars(path.strip())
        access = check_path_access(path)
        if access == "blocked":
            return "This path is blocked or invalid. Use an absolute path outside protected locations."
        mode = mode.lower().strip() if isinstance(mode, str) else ""
        if mode not in {"create", "overwrite", "append", "delete"}:
            return "Invalid mode. Use: create, overwrite, append, or delete"
        if (access == "confirmation_required" or mode == "delete") and not confirmed:
            return f"User approval is required before this operation can change: '{path}'"

        try:
            if mode == "delete":
                if not os.path.exists(path):
                    return f"Nothing was deleted; the path does not exist: '{path}'"
                if os.path.isdir(path):
                    shutil.rmtree(path)
                    return f"Folder and its contents deleted: '{path}'"
                os.remove(path)
                return f"File deleted: '{path}'"

            # ----------------------------------
            # DIRECTORY
            # ----------------------------------
            if not os.path.splitext(path)[1]:
                if mode != "create":
                    return "Overwrite and append modes apply to files. Use create for folders."
                os.makedirs(path, exist_ok=True)
                return f"Directory created or already exists: '{path}'"

            # ----------------------------------
            # FILE
            # ----------------------------------
            directory = os.path.dirname(path)

            if directory:
                os.makedirs(directory, exist_ok=True)

            # CREATE
            if mode == "create":
                if os.path.exists(path):
                    return f"File already exists: '{path}'"

                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

                return f"File created: '{path}'"

            # OVERWRITE
            elif mode == "overwrite":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

                return f"File written: '{path}'"

            # APPEND
            elif mode == "append":
                with open(path, "a", encoding="utf-8") as f:
                    f.write(content)

                return f"Content appended: '{path}'"

            else:
                return "Invalid mode. Use: create, overwrite, append, or delete"

        except PermissionError:
            return f"Permission denied: '{path}'"

        except Exception as e:
            return f"Error creating '{path}': {e}"
