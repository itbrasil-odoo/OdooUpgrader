"""Installed module audit helpers for OdooUpgrader."""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from odooupgrader.errors import UpgraderError


class ModuleAuditService:
    """Collects installed modules and validates OCA module availability."""

    MANIFEST_FILES = ("__manifest__.py", "__openerp__.py")
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        logger,
        console,
        requests_module=requests,
        github_token: Optional[str] = None,
        timeout_seconds: float = 20.0,
        retry_count: int = 1,
        retry_backoff_seconds: float = 2.0,
    ):
        self.logger = logger
        self.console = console
        self.requests = requests_module
        self.github_token = github_token or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        self.timeout_seconds = timeout_seconds
        self.retry_count = max(0, retry_count)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    def collect_installed_modules(self, run_context, run_cmd) -> List[Dict[str, str]]:
        query = (
            "SELECT name, latest_version, state "
            "FROM ir_module_module "
            "WHERE state = 'installed' "
            "ORDER BY name;"
        )
        result = run_cmd(
            [
                "docker",
                "exec",
                "-i",
                run_context.db_container_name,
                "psql",
                "-U",
                run_context.postgres_user,
                "-d",
                run_context.target_database,
                "-t",
                "-A",
                "-F",
                "|",
                "-c",
                query,
            ],
            check=False,
            capture_output=True,
        )

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise UpgraderError(
                "Could not query installed modules from database. "
                f"psql returned code {result.returncode}. Details: {stderr or 'no stderr output'}"
            )

        modules: List[Dict[str, str]] = []
        for line in result.stdout.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue

            parts = cleaned.split("|")
            name = parts[0].strip() if len(parts) > 0 else ""
            latest_version = parts[1].strip() if len(parts) > 1 else ""
            state = parts[2].strip() if len(parts) > 2 else "installed"
            if not name:
                continue
            modules.append(
                {
                    "name": name,
                    "latest_version": latest_version,
                    "state": state,
                }
            )

        return modules

    def discover_local_modules(
        self,
        addons_locations: List[str],
        recursive: bool = True,
    ) -> Dict[str, Dict[str, object]]:
        discovered: Dict[str, Dict[str, object]] = {}
        for location in addons_locations:
            if not location:
                continue

            root = Path(location)
            if not root.exists() or not root.is_dir():
                self.logger.debug("Skipping non-directory addons location: %s", root)
                continue

            manifest_paths = self._find_manifest_paths(root, recursive=recursive)
            for manifest_path in manifest_paths:
                module_dir = manifest_path.parent
                module_name = module_dir.name
                oca_repo = self._detect_oca_repository(module_dir, root)

                entry = discovered.setdefault(
                    module_name,
                    {
                        "name": module_name,
                        "paths": [],
                        "is_oca": False,
                        "oca_repositories": [],
                    },
                )

                entry_paths = entry["paths"]
                if isinstance(entry_paths, list):
                    module_path = str(module_dir)
                    if module_path not in entry_paths:
                        entry_paths.append(module_path)

                if oca_repo:
                    entry["is_oca"] = True
                    repos = entry["oca_repositories"]
                    if isinstance(repos, list) and oca_repo not in repos:
                        repos.append(oca_repo)

        for entry in discovered.values():
            paths = entry["paths"]
            repos = entry["oca_repositories"]
            if isinstance(paths, list):
                paths.sort()
            if isinstance(repos, list):
                repos.sort()

        return discovered

    def check_oca_modules_target(
        self, module_repository_pairs: List[Dict[str, str]], target_version: str
    ) -> List[Dict[str, object]]:
        checks: List[Dict[str, object]] = []
        for pair in module_repository_pairs:
            module_name = pair["module"]
            repository = pair["repository"]
            exists, error = self._check_single_oca_module(repository, module_name, target_version)
            checks.append(
                {
                    "module": module_name,
                    "repository": repository,
                    "target_version": target_version,
                    "exists": exists,
                    "error": error,
                }
            )
        return checks

    def run_audit(
        self,
        run_context,
        run_cmd,
        target_version: str,
        addons_locations: List[str],
        recursive: bool = True,
        output_file: Optional[str] = None,
    ) -> Dict[str, object]:
        installed_modules = self.collect_installed_modules(run_context, run_cmd)
        discovered_local = self.discover_local_modules(addons_locations, recursive=recursive)

        installed_by_name = {module["name"]: module for module in installed_modules}
        installed_names = set(installed_by_name.keys())
        local_names = set(discovered_local.keys())
        installed_in_local = sorted(installed_names.intersection(local_names))

        oca_pairs: List[Dict[str, str]] = []
        for module_name in installed_in_local:
            entry = discovered_local[module_name]
            repos = entry.get("oca_repositories", [])
            if not isinstance(repos, list):
                continue
            for repository in repos:
                oca_pairs.append({"module": module_name, "repository": repository})

        oca_checks = self.check_oca_modules_target(oca_pairs, target_version)
        oca_missing = [
            item
            for item in oca_checks
            if item["exists"] is False and not item["error"]
        ]
        oca_errors = [item for item in oca_checks if item["error"]]

        report: Dict[str, object] = {
            "target_version": target_version,
            "installed_modules_count": len(installed_modules),
            "installed_modules": installed_modules,
            "addons_locations": addons_locations,
            "recursive_scan": recursive,
            "detected_local_modules_count": len(discovered_local),
            "detected_local_modules": discovered_local,
            "installed_modules_in_local_addons": installed_in_local,
            "oca": {
                "checked_modules_count": len(oca_checks),
                "checks": oca_checks,
                "missing_in_target_count": len(oca_missing),
                "missing_in_target": oca_missing,
                "check_error_count": len(oca_errors),
                "check_errors": oca_errors,
            },
        }

        if output_file:
            self.write_report(report, output_file)

        return report

    def write_report(self, report: Dict[str, object], output_file: str):
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as file_obj:
            json.dump(report, file_obj, indent=2, sort_keys=True)
            file_obj.write("\n")

    def _find_manifest_paths(self, root: Path, recursive: bool) -> List[Path]:
        manifests: List[Path] = []
        if self._is_module_dir(root):
            manifests.extend(self._manifest_files_in_dir(root))

        if not recursive:
            for child in root.iterdir():
                if not child.is_dir() or child.name.startswith("."):
                    continue
                if self._is_module_dir(child):
                    manifests.extend(self._manifest_files_in_dir(child))
            return manifests

        for manifest_name in self.MANIFEST_FILES:
            for manifest_path in root.rglob(manifest_name):
                if not manifest_path.is_file():
                    continue
                if self._is_hidden_or_cache_path(manifest_path):
                    continue
                manifests.append(manifest_path)

        unique = sorted({path.resolve() for path in manifests})
        return unique

    def _check_single_oca_module(
        self,
        repository: str,
        module_name: str,
        target_version: str,
    ) -> Tuple[bool, Optional[str]]:
        url = f"https://api.github.com/repos/OCA/{repository}/contents/{module_name}"
        headers = {"Accept": "application/vnd.github+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        max_attempts = max(1, self.retry_count + 1)
        request_exception = getattr(self.requests, "RequestException", Exception)
        for attempt in range(1, max_attempts + 1):
            try:
                response = self.requests.get(
                    url,
                    headers=headers,
                    params={"ref": target_version},
                    timeout=self.timeout_seconds,
                )
            except request_exception as exc:
                if attempt < max_attempts:
                    time.sleep(self.retry_backoff_seconds)
                    continue
                return False, f"GitHub request failed: {exc}"

            status_code = response.status_code
            if status_code == 200:
                return True, None
            if status_code == 404:
                return False, None

            if status_code in self.RETRYABLE_STATUS_CODES and attempt < max_attempts:
                time.sleep(self.retry_backoff_seconds)
                continue

            message = self._response_message(response)
            return False, f"GitHub API returned {status_code}: {message}"

        return False, "GitHub check failed after retries."

    def _response_message(self, response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = payload.get("message")
                if isinstance(message, str) and message:
                    return message
        except ValueError:
            pass
        return (response.text or "").strip() or "no details"

    def _detect_oca_repository(self, module_dir: Path, scan_root: Path) -> Optional[str]:
        parts = module_dir.parts
        if "OCA" in parts:
            index = parts.index("OCA")
            if index + 1 < len(parts):
                return parts[index + 1]

        resolved_root = scan_root.resolve()
        current = module_dir.resolve()
        while True:
            if (current / ".oca").exists():
                return current.name
            if current == resolved_root or current.parent == current:
                return None
            current = current.parent

    def _is_hidden_or_cache_path(self, manifest_path: Path) -> bool:
        for part in manifest_path.parts:
            if part.startswith("."):
                return True
            if part == "__pycache__":
                return True
        return False

    def _is_module_dir(self, module_dir: Path) -> bool:
        return any((module_dir / manifest_name).is_file() for manifest_name in self.MANIFEST_FILES)

    def _manifest_files_in_dir(self, module_dir: Path) -> List[Path]:
        paths: List[Path] = []
        for manifest_name in self.MANIFEST_FILES:
            manifest_path = module_dir / manifest_name
            if manifest_path.is_file():
                paths.append(manifest_path)
        return paths
