"""
Context Providers for Queen Honey Context Builder.

Each provider renders ONE section of the intelligence context prompt.
The dispatcher iterates all providers in order, collecting lines.

Original: Queen._build_honey_context (CC=135, 430 lines, synth.py:412)
Refactored: 16 small providers (CC ~5-12 each) + dispatcher (CC ~5)
"""

from .base import ContextProvider, HoneyContext
from .dispatcher import build_honey_context, PROVIDERS

__all__ = ["ContextProvider", "HoneyContext", "build_honey_context", "PROVIDERS"]
