"""Versioned personal-client API. No provider is instantiated at import time."""
from .app import create_app

__all__ = ["create_app"]
