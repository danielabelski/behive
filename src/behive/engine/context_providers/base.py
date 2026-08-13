"""
Base class for context providers.
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("singularity")


@dataclass
class HoneyContext:
    """Shared context passed to all providers."""
    honey: dict
    mission: dict = field(init=False)
    mission_id: str = ""
    lines: list = field(default_factory=list)

    def __post_init__(self):
        self.mission = self.honey.get("mission", {})


class ContextProvider(ABC):
    """Base class for a context section renderer."""

    section_name: str = ""  # Override in subclass

    @abstractmethod
    def render(self, ctx: HoneyContext) -> list[str]:
        """Return lines for this section. Empty list = skip section."""
        ...

    def applies(self, ctx: HoneyContext) -> bool:
        """Override to conditionally skip this provider."""
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED UTILITIES (used by multiple providers)
# ═══════════════════════════════════════════════════════════════════════════════

NUM_PATTERN = re.compile(
    r'\b(\d[\d\s]*[\d](?:[.,]\d+)?)\s*'
    r'(%|PLN|EUR|USD|GBP|zł|mln|tys|k|M|B|GB|TB|ms|s|min|h|'
    r'dni|miesięcy|lat|gwiazdek|users|klientów|pracowników|firm|'
    r'projektów|calls|req|rps|stars|downloads|installs|seats|licenses)\b',
    re.IGNORECASE
)


def parse_domains_json(domains_json: Any) -> list[str]:
    """Safely parse domains from JSON or list."""
    if isinstance(domains_json, list):
        return domains_json
    if isinstance(domains_json, str) and domains_json:
        try:
            return json.loads(domains_json)
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def extract_domain(url: str) -> str:
    """Extract clean domain from URL."""
    if not url:
        return ""
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def safe_conf(conf: Any) -> str:
    """Safely format confidence value."""
    try:
        return f"{float(conf):.2f}"
    except Exception:
        return str(conf)
