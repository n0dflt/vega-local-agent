"""Built-in research domain metadata."""

from __future__ import annotations

from domains.models import DomainDefinition


def create_research_domain() -> DomainDefinition:
    return DomainDefinition(
        name="research",
        description="Safe local document discovery, reading, and analysis.",
        intents=("document_analysis",),
        capabilities=("document.read", "document.analyze", "project.search"),
        tool_names=(
            "list_dir",
            "read_file",
            "find_file",
            "search_in_files",
            "summarize_file",
        ),
    )


__all__ = ["create_research_domain"]
