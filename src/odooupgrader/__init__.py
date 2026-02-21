"""
OdooUpgrader - Professional Odoo database upgrade tool
"""

__version__ = "0.7.0"
__author__ = "Fasil"
__email__ = "fasilwdr@hotmail.com"

from .core import OdooUpgrader, UpgraderError

__all__ = ["OdooUpgrader", "UpgraderError"]
