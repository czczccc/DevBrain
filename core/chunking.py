"""Code chunking helpers for repository indexing."""

from __future__ import annotations

from dataclasses import dataclass
import ast
from typing import Iterable

from core.repo_ingestion import RepoDocument


@dataclass(frozen=True)
class CodeChunk:
    """A searchable unit produced from source documents."""

    chunk_id: str
    relative_path: str
    content: str
    start_line: int
    end_line: int


def chunk_documents(documents: Iterable[RepoDocument]) -> list[CodeChunk]:
    """Chunk repository documents by function blocks when possible."""

    chunks: list[CodeChunk] = []
    for document in documents:
        produced = _chunk_python_document(document) if document.language == "python" else []
        if not produced:
            produced = [_chunk_whole_document(document)]
        chunks.extend(produced)
    return chunks


def _chunk_python_document(document: RepoDocument) -> list[CodeChunk]:
    try:
        tree = ast.parse(document.content)
    except SyntaxError:
        return []

    chunks: list[CodeChunk] = []
    lines = document.content.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start_line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", start_line)
        content = "\n".join(lines[start_line - 1 : end_line]).strip()
        if not content:
            continue
        chunk_id = f"{document.relative_path}:{start_line}-{end_line}"
        chunks.append(
            CodeChunk(
                chunk_id=chunk_id,
                relative_path=document.relative_path,
                content=content,
                start_line=start_line,
                end_line=end_line,
            )
        )
    return sorted(chunks, key=lambda item: (item.relative_path, item.start_line))


def _chunk_whole_document(document: RepoDocument) -> CodeChunk:
    lines = document.content.splitlines()
    end_line = max(len(lines), 1)
    return CodeChunk(
        chunk_id=f"{document.relative_path}:1-{end_line}",
        relative_path=document.relative_path,
        content=document.content,
        start_line=1,
        end_line=end_line,
    )
