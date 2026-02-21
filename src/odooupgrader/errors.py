"""Domain errors for OdooUpgrader."""


class UpgraderError(RuntimeError):
    """Raised when the upgrade cannot continue safely."""
