"""Dynamic Jira Project Discovery (ADR-014) — public exports.

Imports are lazy to avoid pulling in heavy ORM models at module level,
which enables import on Python < 3.12 for testing individual modules.
"""

__all__ = [
    "DiscoveryRepository",
    "Guardrails",
    "ModeResolver",
    "ProjectDiscoveryService",
    "SmartPrioritizer",
]


def __getattr__(name: str):
    if name == "DiscoveryRepository":
        from src.contexts.integrations.jira.discovery.repository import DiscoveryRepository
        return DiscoveryRepository
    if name == "Guardrails":
        from src.contexts.integrations.jira.discovery.guardrails import Guardrails
        return Guardrails
    if name == "ModeResolver":
        from src.contexts.integrations.jira.discovery.mode_resolver import ModeResolver
        return ModeResolver
    if name == "ProjectDiscoveryService":
        from src.contexts.integrations.jira.discovery.project_discovery_service import ProjectDiscoveryService
        return ProjectDiscoveryService
    if name == "SmartPrioritizer":
        from src.contexts.integrations.jira.discovery.smart_prioritizer import SmartPrioritizer
        return SmartPrioritizer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
