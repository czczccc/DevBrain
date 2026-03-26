"""Optional syntax intelligence powered by tree-sitter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.repo_ingestion import RepoDocument


@dataclass(frozen=True)
class FileIntelligence:
    """Extracted symbol and dependency hints for a source file."""

    key_symbols: list[str] = field(default_factory=list)
    dependencies_or_calls: list[str] = field(default_factory=list)


def extract_file_intelligence(document: RepoDocument) -> FileIntelligence:
    """Return best-effort symbol metadata for a document."""

    language = _map_language(document.language)
    if not language:
        return FileIntelligence()

    try:
        from tree_sitter_language_pack import ProcessConfig, process
    except Exception:
        return FileIntelligence()

    try:
        result = process(document.content, ProcessConfig(language=language))
    except Exception:
        return FileIntelligence()

    return FileIntelligence(
        key_symbols=_unique_values(_collect_names(result.get("structure", []))),
        dependencies_or_calls=_unique_values(_collect_names(result.get("imports", []))),
    )


def _map_language(language: str) -> str | None:
    if language == "python":
        return "python"
    if language == "javascript":
        return "javascript"
    return None


def _collect_names(value: Any) -> list[str]:
    if isinstance(value, dict):
        names = _collect_names(value.get("name"))
        for item in value.values():
            if item is value.get("name"):
                continue
            names.extend(_collect_names(item))
        return names

    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            names.extend(_collect_names(item))
        return names

    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []

    return []


def _unique_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique[:20]
