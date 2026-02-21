"""Actionable error catalog for OdooUpgrader."""

from typing import Dict

_ERROR_MESSAGES: Dict[str, Dict[str, str]] = {
    "invalid_source_format": {
        "what": "Invalid source format. Supported formats are `.zip` and `.dump`.",
        "next": "Use a local or remote source ending with `.zip` or `.dump`.",
    },
    "invalid_addons_format": {
        "what": "Invalid addons format. Remote or file addons must be a `.zip` file.",
        "next": "Provide a directory or `.zip` package containing valid Odoo modules.",
    },
    "insecure_http": {
        "what": "{label} uses insecure HTTP.",
        "next": "Switch to HTTPS or use `--allow-insecure-http` only for trusted endpoints.",
    },
    "source_not_found": {
        "what": "Source file not found: {path}",
        "next": "Check the path or download the source file before retrying.",
    },
    "extra_addons_not_found": {
        "what": "Extra addons path not found: {path}",
        "next": "Provide an existing directory, zip file, or reachable URL for addons.",
    },
    "upgrade_step_failed": {
        "what": "Upgrade step to {target_version} failed.",
        "next": "Inspect `output/odoo.log` and container logs, then resume with `--resume`.",
    },
}


def actionable_error(code: str, **kwargs: str) -> str:
    if code not in _ERROR_MESSAGES:
        raise KeyError(f"Unknown error catalog key: {code}")

    template = _ERROR_MESSAGES[code]
    what = template["what"].format(**kwargs)
    next_step = template["next"].format(**kwargs)
    return f"{what} Suggested action: {next_step}"
