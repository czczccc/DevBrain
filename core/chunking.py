"""Code chunking helpers for repository indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from core.code_intelligence import extract_file_intelligence
from core.repo_ingestion import RepoDocument

DEFAULT_WINDOW_SIZE = 80
DEFAULT_WINDOW_OVERLAP = 20


@dataclass(frozen=True)
class CodeChunk:
    """A searchable unit produced from source documents."""

    chunk_id: str
    relative_path: str
    content: str
    start_line: int
    end_line: int
    chunk_type: str = "line_window"
    window_index: int = 0
    key_symbols: list[str] = field(default_factory=list)


def chunk_documents(
    documents: Iterable[RepoDocument],
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_WINDOW_OVERLAP,
) -> list[CodeChunk]:
    """Chunk repository documents into overlapping line windows."""

    chunks: list[CodeChunk] = []
    for document in documents:
        chunks.extend(_chunk_document(document, window_size=window_size, overlap=overlap))
    return chunks


def _chunk_document(document: RepoDocument, window_size: int, overlap: int) -> list[CodeChunk]:
    lines = document.content.splitlines()
    if not lines:
        return []

    intelligence = extract_file_intelligence(document)
    windows: list[CodeChunk] = []
    for window_index, (start_line, end_line) in enumerate(
        _iter_line_windows(line_count=len(lines), window_size=window_size, overlap=overlap)
    ):
        content = "\n".join(lines[start_line - 1 : end_line]).strip()
        if not content:
            continue
        windows.append(
            CodeChunk(
                chunk_id=f"{document.relative_path}:{start_line}-{end_line}",
                relative_path=document.relative_path,
                content=content,
                start_line=start_line,
                end_line=end_line,
                chunk_type="line_window",
                window_index=window_index,
                key_symbols=intelligence.key_symbols,
            )
        )
    return windows


def _iter_line_windows(line_count: int, window_size: int, overlap: int) -> Iterable[tuple[int, int]]:
    if line_count <= 0:
        return []

    if window_size <= 0:
        raise ValueError("window_size must be positive")
    if overlap < 0:
        raise ValueError("overlap must not be negative")
    if overlap >= window_size:
        raise ValueError("overlap must be smaller than window_size")

    if line_count <= window_size:
        return [(1, line_count)]

    windows: list[tuple[int, int]] = []
    step = window_size - overlap
    start_line = 1

    while start_line <= line_count:
        end_line = min(start_line + window_size - 1, line_count)
        windows.append((start_line, end_line))
        if end_line >= line_count:
            break
        start_line += step

    return windows
