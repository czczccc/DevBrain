"""Repository ingestion utilities for codebase indexing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_IGNORED_DIRS = {".git", "node_modules", "build", "dist"}
DEFAULT_ALLOWED_EXTENSIONS = {".py", ".ts", ".js", ".md", ".json"}


@dataclass(frozen=True)
class RepoDocument:
    """A single ingested source document from the repository."""

    relative_path: str
    language: str
    content: str


@dataclass(frozen=True)
class IngestionError:
    """Captures file-level ingestion failures without stopping the pipeline."""

    relative_path: str
    message: str


@dataclass(frozen=True)
class IngestionResult:
    """The full output of repository ingestion."""

    root_path: str
    documents: list[RepoDocument]
    errors: list[IngestionError]


class RepoIngestor:
    """Ingest repository files while applying ignore and extension rules."""

    def __init__(
        self,
        ignored_dirs: Iterable[str] | None = None,
        allowed_extensions: Iterable[str] | None = None,
    ) -> None:
        self.ignored_dirs = set(ignored_dirs or DEFAULT_IGNORED_DIRS)
        self.allowed_extensions = {
            extension.lower() for extension in (allowed_extensions or DEFAULT_ALLOWED_EXTENSIONS)
        }

    def ingest(self, root_path: str | Path) -> IngestionResult:
        root = Path(root_path).resolve()
        documents: list[RepoDocument] = []
        errors: list[IngestionError] = []

        for file_path in self._iter_candidate_files(root):
            relative_path = file_path.relative_to(root).as_posix()
            try:
                content = file_path.read_text(encoding="utf-8-sig")
            except (UnicodeDecodeError, OSError) as exc:
                errors.append(IngestionError(relative_path=relative_path, message=str(exc)))
                continue

            documents.append(
                RepoDocument(
                    relative_path=relative_path,
                    language=self._detect_language(file_path),
                    content=content,
                )
            )

        documents.sort(key=lambda document: document.relative_path)
        errors.sort(key=lambda error: error.relative_path)
        return IngestionResult(root_path=root.as_posix(), documents=documents, errors=errors)

    def _iter_candidate_files(self, root: Path) -> Iterable[Path]:
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            if self._is_ignored(file_path, root):
                continue
            if file_path.suffix.lower() not in self.allowed_extensions:
                continue
            yield file_path

    def _is_ignored(self, file_path: Path, root: Path) -> bool:
        relative_parts = file_path.relative_to(root).parts
        return any(part in self.ignored_dirs for part in relative_parts[:-1])

    @staticmethod
    def _detect_language(file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".py":
            return "python"
        if suffix in {".ts", ".js"}:
            return "javascript"
        if suffix == ".md":
            return "markdown"
        if suffix == ".json":
            return "json"
        return "text"
