"""Tool functions exposed to the local Ollama model.

Add tool names to ENABLED_TOOL_NAMES to make them available to the model.
The dispatcher only executes functions registered in TOOL_FUNCTIONS.
"""

from __future__ import annotations

import sys
import threading
import uuid
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


ENABLED_TOOL_NAMES = {
    "launch_app",
    "manage_files_and_folders",
    "tavily_web_search",
    "spotify_control",
}

_pending_approvals: dict[str, dict] = {}
_approval_lock = threading.Lock()


def create_path_approval(path: str, mode: str) -> str:
    approval_id = uuid.uuid4().hex
    with _approval_lock:
        _pending_approvals[approval_id] = {
            "event": threading.Event(),
            "approved": False,
            "path": path,
            "mode": mode,
        }
    return approval_id


def resolve_path_approval(approval_id: str, approved: bool) -> bool:
    with _approval_lock:
        approval = _pending_approvals.get(approval_id)
        if approval is None:
            return False
        approval["approved"] = approved
        approval["event"].set()
        return True


def wait_for_path_approval(approval_id: str, timeout: float = 120) -> bool:
    with _approval_lock:
        approval = _pending_approvals.get(approval_id)
    if approval is None:
        return False
    approval["event"].wait(timeout)
    with _approval_lock:
        approval = _pending_approvals.pop(approval_id, None)
    return bool(approval and approval["event"].is_set() and approval["approved"])


def launch_app(target: str) -> str:
    """Launch a configured app, website, folder, or saved setup.

    Args:
        target: The app name, website, folder path, or setup to open.
    """
    from tools.app_launcher import Tools as AppLauncher

    return AppLauncher().launcher(target)


def manage_files_and_folders(path: str, content: str = "", mode: str = "create") -> str:
    """Create, edit, append to, or permanently delete files and folders.

    Args:
        path: Absolute path of the exact file or folder to change. C:\\Windows is forbidden. C:\\Program Files, C:\\Program Files (x86), C:\\Users, C:\\Lessons, and C:\\Projects require explicit user approval.
        content: Text to write for create, overwrite, or append; leave empty for folders or deletion.
        mode: create makes a file or folder; overwrite replaces file text; append adds file text and creates the file if needed; delete permanently removes a file or folder and all its contents, after user approval. Use the exact mode matching the user's request.
    """
    from tools.folder_and_file_creator import Tools as FileCreator

    return FileCreator().create(path=path, content=content, mode=mode)


def list_important_emails(account: str = "work", query: str = "is:unread", max_results: int = 10) -> str:
    """List recent matching email subjects from a connected account.

    Args:
        account: The account name, work or school.
        query: A Gmail search query.
        max_results: Maximum number of emails to return.
    """
    from tools.email_calendar_and_classroom_manager import Tools as GoogleTools

    return GoogleTools().list_important_emails(account=account, query=query, max_results=max_results)


def manage_calendar_event(
    action: str,
    title: str | None = None,
    start: str | None = None,
    end: str | None = None,
    event_id: str | None = None,
) -> str:
    """List, create, or delete a calendar event.

    Args:
        action: One of list, create, or delete.
        title: Event title when creating an event.
        start: Event start time in ISO 8601 format.
        end: Event end time in ISO 8601 format.
        event_id: Calendar event ID when deleting an event.
    """
    from tools.email_calendar_and_classroom_manager import Tools as GoogleTools

    return GoogleTools().manage_calendar_event(
        action=action, title=title, start=start, end=end, event_id=event_id
    )


def get_classroom_assignments() -> str:
    """List courses and assignments from the connected school account."""
    from tools.email_calendar_and_classroom_manager import Tools as GoogleTools

    return GoogleTools().get_classroom_assignments()


def tavily_web_search(query: str) -> str:
    """Search the live web for current, recent, or explicitly requested information.

    Args:
        query: A focused web search query. Return findings with source titles and URLs.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return "Web search is not configured. Set the TAVILY_API_KEY Windows user environment variable and restart Jarvis."
    if not query or not query.strip():
        return "Please provide a search query."

    payload = json.dumps({
        "query": query.strip(),
        "topic": "general",
        "search_depth": "basic",
        "max_results": 5,
        "include_answer": False,
        "include_raw_content": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return "Tavily rejected the API key. Check TAVILY_API_KEY and restart Jarvis."
        if error.code == 429:
            return "Tavily refused the search because the rate or monthly credit limit was reached. Check your Tavily dashboard."
        return f"Tavily search failed with HTTP {error.code}."
    except (urllib.error.URLError, TimeoutError) as error:
        return f"Tavily search could not connect: {error}."
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "Tavily returned an unreadable response."

    results = data.get("results", [])
    if not results:
        return "Tavily found no results for that query."
    formatted = [f"Web search results for: {query.strip()}"]
    for index, result in enumerate(results, 1):
        title = result.get("title") or "Untitled source"
        url = result.get("url") or ""
        content = result.get("content") or ""
        formatted.append(f"{index}. {title}\nURL: {url}\nSummary: {content}")
    return "\n\n".join(formatted)


def spotify_control(action: str, query: str = "") -> str:
    """Control the Spotify desktop app. Actions: play, pause, next, previous, liked, search_play."""
    from tools.spotify_desktop import control

    return control(action, query)


TOOL_FUNCTIONS: dict[str, Callable] = {
    "launch_app": launch_app,
    "manage_files_and_folders": manage_files_and_folders,
    "list_important_emails": list_important_emails,
    "manage_calendar_event": manage_calendar_event,
    "get_classroom_assignments": get_classroom_assignments,
    "tavily_web_search": tavily_web_search,
    "spotify_control": spotify_control,
}


def get_enabled_tools() -> list[Callable]:
    unknown = ENABLED_TOOL_NAMES.difference(TOOL_FUNCTIONS)
    if unknown:
        raise ValueError(f"Unknown enabled tool(s): {', '.join(sorted(unknown))}")
    return [TOOL_FUNCTIONS[name] for name in TOOL_FUNCTIONS if name in ENABLED_TOOL_NAMES]


def execute_tool(name: str, arguments: dict, path_confirmed: bool = False) -> str:
    """Execute one allowlisted function, returning a string for Ollama."""
    if name not in ENABLED_TOOL_NAMES:
        raise ValueError(f"Tool is not enabled: {name}")
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        raise ValueError(f"Unknown tool: {name}")
    if name == "manage_files_and_folders":
        from tools.folder_and_file_creator import Tools as FileCreator

        result = FileCreator().create(**arguments, confirmed=path_confirmed)
    else:
        result = function(**arguments)
    return result if isinstance(result, str) else str(result)
