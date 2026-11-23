import os
import json
import subprocess
import webbrowser
import re


class Tools:
    def __init__(self):
        self.index_file = r"C:\projects\jarvis2.0\tools\app_index.json"
        self.commands_file = r"C:\projects\jarvis2.0\tools\app_launcher_commands.json"

        self.index = self._load_json(self.index_file, default={})
        self.commands = self._load_json(self.commands_file, default={})

    # --------------------------
    # FILE SYSTEM
    # --------------------------

    def _load_json(self, path, default):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()

                    if content:
                        return json.loads(content)

        except Exception:
            pass

        return default

    def _save_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _expand(self, path):
        return os.path.expandvars(path)

    # --------------------------
    # APP LAUNCHER
    # --------------------------

    def _launch_app(self, name):
        if name not in self.index:
            return f"{name} not found"

        app = self.index[name]

        path = self._expand(app.get("path", ""))

        if not os.path.exists(path):
            return f"{name} path invalid"

        args = app.get("args", [])

        try:
            if args:
                subprocess.Popen([path] + args)
            else:
                subprocess.Popen(path)

            return f"{name} launched"

        except Exception as e:
            return f"{name} failed: {e}"

    # --------------------------
    # URL LAUNCHER
    # --------------------------

    def _launch_url(self, url):
        try:
            url = url.strip()

            # force proper URL format
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url

            webbrowser.open(url)

            return f"Opened {url}"

        except Exception as e:
            return f"Failed to open {url}: {e}"

    # --------------------------
    # FOLDER LAUNCHER
    # --------------------------

    def _launch_folder(self, path):
        try:
            path = self._expand(path)

            if not os.path.exists(path):
                return f"Folder not found: {path}"

            subprocess.Popen(f'explorer "{path}"')

            return f"Opened folder {path}"

        except Exception as e:
            return f"Failed to open folder {path}: {e}"

    # --------------------------
    # COMMAND SAVE
    # --------------------------

    def _save_current_setup(self, setup_name):
        setup_name = setup_name.lower().replace(" ", "")

        launched_items = []

        # save all apps currently in command
        for app_name in self.index:
            launched_items.append(app_name)

        self.commands[setup_name] = {
            "items": launched_items
        }

        self._save_json(self.commands_file, self.commands)

        return f"Saved setup '{setup_name}'"

    # --------------------------
    # MAIN LAUNCHER
    # --------------------------

    def launcher(self, target: str) -> str:
        """
        Launches apps, websites, folders, or saved setups.

        IMPORTANT:
        Input must ONLY contain:
        - app names
        - website URLs
        - folder paths
        - setup names

        NEVER provide:
        - terminal commands
        - shell syntax
        - cmd commands
        - powershell commands
        - bash commands
        - wsl commands
        - quotes
        - operators like && or ;

        VALID examples:
        discord
        valorant and discord
        youtube.com
        C:\projects
        gaming setup

        INVALID examples:
        start discord
        cmd /c discord
        wsl.exe ...
        """

        cmd = target.strip()
        cmd_lower = cmd.lower()

        # --------------------------
        # SAVE APP PATH
        # --------------------------

        save_app_match = re.search(
            r"save (.*?) as (c:\\.*)",
            cmd,
            re.IGNORECASE
        )

        if save_app_match:
            app_name = (
                save_app_match.group(1)
                .strip()
                .lower()
                .replace(" ", "")
            )

            app_path = save_app_match.group(2).strip()

            self.index[app_name] = {
                "path": app_path,
                "args": [],
                "aliases": [app_name]
            }

            self._save_json(self.index_file, self.index)

            return f"Saved app '{app_name}'"

        # --------------------------
        # SAVE SETUP
        # --------------------------

        save_setup_match = re.search(
            r"save this as (.*)",
            cmd_lower
        )

        if save_setup_match:
            setup_name = save_setup_match.group(1).strip()

            return self._save_current_setup(setup_name)

        # --------------------------
        # LAUNCH SAVED SETUP
        # --------------------------

        normalized_full = (
            cmd_lower
            .replace("launch ", "")
            .replace("open ", "")
            .replace(" ", "")
            .strip()
        )

        if normalized_full in self.commands:
            results = []

            items = self.commands[normalized_full].get("items", [])

            for item in items:
                if item in self.index:
                    results.append(self._launch_app(item))

            return "\n".join(results)

        # --------------------------
        # MULTI ITEM SPLIT
        # --------------------------

        cleaned_command = cmd_lower

        cleaned_command = re.sub(
            r"^(launch|open)\s+",
            "",
            cleaned_command
        )

        parts = re.split(r"\s+and\s+|,", cleaned_command)

        results = []

        # --------------------------
        # HANDLE EACH PART
        # --------------------------

        for part in parts:
            part = part.strip()

            if not part:
                continue

            normalized_part = (
                part
                .replace(" ", "")
                .replace('"', "")
                .replace("'", "")
            )

            # --------------------------
            # WEBSITE
            # --------------------------

            if re.search(r"(https?://|\.com|\.net|\.org)", part):
                results.append(self._launch_url(part))
                continue

            # --------------------------
            # FOLDER
            # --------------------------

            folder_match = re.search(
                r"([a-zA-Z]:\\[^\s'\"]+)",
                part
            )

            if folder_match:
                folder_path = folder_match.group(1)

                results.append(
                    self._launch_folder(folder_path)
                )

                continue

            # --------------------------
            # APP MATCHING
            # --------------------------

            matched_app = None

            for app_name, data in self.index.items():

                aliases = data.get("aliases", [])

                # include app name itself automatically
                aliases.append(app_name)

                for alias in aliases:

                    alias_normalized = (
                        alias
                        .lower()
                        .replace(" ", "")
                    )

                    if alias_normalized in normalized_part:
                        matched_app = app_name
                        break

                if matched_app:
                    break

            if matched_app:
                results.append(
                    self._launch_app(matched_app)
                )
            else:
                results.append(
                    f"No match for '{part}'"
                )

        # --------------------------
        # FINAL RESULT
        # --------------------------

        if not results:
            return "Nothing detected"

        return "\n".join(results)