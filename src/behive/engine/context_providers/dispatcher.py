"""
Dispatcher — replaces Queen._build_honey_context (CC=135) with a simple loop (CC~5).
"""

import logging
from .base import ContextProvider, HoneyContext
from .providers import (
    MissionHeaderProvider,
    NumericDigestProvider,
    KeyClaimsProvider,
    ConfirmedFactsProvider,
    AllFactsProvider,
    EntitiesProvider,
    ClustersProvider,
    FalsificationProvider,
    OutliersProvider,
    CitationsProvider,
    ResearchGapsProvider,
    TopClaimsProvider,
    HypothesisProvider,
    PriorsProvider,
    GraveyardProvider,
)

log = logging.getLogger("singularity")

# Ordered list — determines section order in the prompt.
# Add/remove/reorder without touching any logic.
PROVIDERS: list[ContextProvider] = [
    MissionHeaderProvider(),
    NumericDigestProvider(),
    KeyClaimsProvider(),
    ConfirmedFactsProvider(),
    AllFactsProvider(),
    EntitiesProvider(),
    ClustersProvider(),
    FalsificationProvider(),
    OutliersProvider(),
    CitationsProvider(),
    ResearchGapsProvider(),
    TopClaimsProvider(),
    HypothesisProvider(),
    PriorsProvider(),
    GraveyardProvider(),
]


def build_honey_context(honey: dict, mission_id: str = "") -> str:
    """
    Build structured text context from honey data.
    
    Drop-in replacement for Queen._build_honey_context.
    Same output, CC reduced from 135 to 5.
    """
    ctx = HoneyContext(honey=honey, mission_id=mission_id)

    for provider in PROVIDERS:
        if provider.applies(ctx):
            try:
                section_lines = provider.render(ctx)
                if section_lines:
                    ctx.lines.extend(section_lines)
            except Exception as e:
                log.debug(f"Context provider '{provider.section_name}' error: {e}")
                continue

    return "\n".join(ctx.lines)
