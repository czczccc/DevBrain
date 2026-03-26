"""Repository import helpers for phase-2 local path onboarding."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
import json
import uuid

DEFAULT_SCAN_IGNORED_DIRS = {".git", "node_modules"}


@dataclass(frozen=True)
class ScannedFile:
    """A file discovered during recursive repository scanning."""

    path: str
    size: int


@dataclass(frozen=True)
class ProjectMetadata:
    """Project-level metadata persisted after import."""

    project_id: str
    root_path: str
    imported_at: str
    file_count: int
    ignored_dirs: list[str]
    source_type: str = "local"
    source_url: str | None = None
    cache_reused: bool = False


def scan_repository_files(
    root_path: str | Path, ignored_dirs: set[str] | None = None
) -> list[ScannedFile]:
    """Recursively scan files while skipping ignored directories."""

    root = Path(root_path).resolve()
    skip_dirs = ignored_dirs or DEFAULT_SCAN_IGNORED_DIRS
    files: list[ScannedFile] = []

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(root).as_posix()
        parent_parts = Path(relative).parts[:-1]
        if any(part in skip_dirs for part in parent_parts):
            continue

        files.append(ScannedFile(path=relative, size=file_path.stat().st_size))

    files.sort(key=lambda item: item.path)
    return files


def save_project_metadata(
    root_path: str | Path,
    files: list[ScannedFile],
    output_dir: str | Path = "data/projects",
    ignored_dirs: set[str] | None = None,
    source_type: str = "local",
    source_url: str | None = None,
    cache_reused: bool = False,
) -> ProjectMetadata:
    """Save metadata for an imported project and return the persisted model."""

    root = Path(root_path).resolve()
    skip_dirs = sorted(list(ignored_dirs or DEFAULT_SCAN_IGNORED_DIRS))
    metadata = ProjectMetadata(
        project_id=uuid.uuid4().hex,
        root_path=root.as_posix(),
        imported_at=datetime.now(UTC).isoformat(),
        file_count=len(files),
        ignored_dirs=skip_dirs,
        source_type=source_type,
        source_url=source_url,
        cache_reused=cache_reused,
    )

    target_dir = Path(output_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / f"{metadata.project_id}.json"
    target_file.write_text(
        json.dumps(asdict(metadata), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return metadata
