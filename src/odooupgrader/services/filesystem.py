"""Filesystem helpers for OdooUpgrader."""

import logging
import os
import shutil
import sys

from rich.console import Console


class FileSystemService:
    """Encapsulates file and directory side effects."""

    def __init__(self, logger: logging.Logger, console: Console):
        self.logger = logger
        self.console = console

    def set_permissions(self, path: str, mode: int):
        if sys.platform == "win32":
            return

        try:
            os.chmod(path, mode)
        except Exception as exc:
            self.logger.warning("Could not set permissions on %s: %s", path, exc)

    def set_tree_permissions(self, root: str, dir_mode: int, file_mode: int, script_mode: int):
        if sys.platform == "win32" or not os.path.exists(root):
            return

        for current_root, dirs, files in os.walk(root):
            for directory in dirs:
                self.set_permissions(os.path.join(current_root, directory), dir_mode)
            for file_name in files:
                mode = script_mode if file_name.endswith(".sh") else file_mode
                self.set_permissions(os.path.join(current_root, file_name), mode)

    def cleanup_dir(self, path: str):
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
                self.logger.debug("Removed directory: %s", path)
            except Exception as exc:
                message = f"Warning: Could not remove {path}: {exc}"
                self.console.print(f"[yellow]{message}[/yellow]")
                self.logger.warning(message)
