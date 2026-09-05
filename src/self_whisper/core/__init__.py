"""Core: configuration, logging, versioning."""

from self_whisper.core.config import ConfigManager, config
from self_whisper.core.version import __version__

__all__ = ["ConfigManager", "config", "__version__"]
