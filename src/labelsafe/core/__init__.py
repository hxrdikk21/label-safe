"""
LabelSafe Core Module.
Contains system configuration and canonical Pydantic contracts shared across all workstreams.
"""

from .config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
