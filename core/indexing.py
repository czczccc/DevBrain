"""Embedding and FAISS indexing utilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from core.chunking import CodeChunk


@dataclass(frozen=True)
class SearchResult:
    """A semantic search match from indexed chunks."""

    chunk_id: str
    relative_path: str
    score: float
    start_line: int
    end_line: int
    content: str


def build_and_save_index(
    project_id: str,
    chunks: list[CodeChunk],
    model_name: str,
    output_dir: str | Path = "data/index",
) -> dict[str, str | int]:
    """Build embeddings and persist FAISS index + chunk metadata."""

    _ensure_dependencies()
    from sentence_transformers import SentenceTransformer
    import faiss

    model = SentenceTransformer(model_name)
    vectors = model.encode([chunk.content for chunk in chunks], normalize_embeddings=True)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)

    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(target / f"{project_id}.faiss"))
    (target / f"{project_id}.chunks.json").write_text(
        json.dumps([asdict(chunk) for chunk in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target / f"{project_id}.index.json").write_text(
        json.dumps(
            {"project_id": project_id, "model_name": model_name, "chunk_count": len(chunks)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"project_id": project_id, "chunk_count": len(chunks), "model_name": model_name}


def search_index(
    project_id: str,
    query: str,
    top_k: int,
    model_name: str,
    index_dir: str | Path = "data/index",
) -> list[SearchResult]:
    """Search persisted FAISS index using semantic similarity."""

    _ensure_dependencies()
    from sentence_transformers import SentenceTransformer
    import faiss

    source = Path(index_dir).resolve()
    index = faiss.read_index(str(source / f"{project_id}.faiss"))
    chunks = _load_chunks(source / f"{project_id}.chunks.json")
    model = SentenceTransformer(model_name)
    query_vector = model.encode([query], normalize_embeddings=True)
    scores, indices = index.search(query_vector, top_k)
    return _map_results(scores[0], indices[0], chunks)


def _load_chunks(path: Path) -> list[CodeChunk]:
    raw_items = json.loads(path.read_text(encoding="utf-8"))
    return [CodeChunk(**item) for item in raw_items]


def _map_results(scores, indices, chunks: list[CodeChunk]) -> list[SearchResult]:
    results: list[SearchResult] = []
    for score, idx in zip(scores, indices):
        if idx < 0 or idx >= len(chunks):
            continue
        chunk = chunks[idx]
        results.append(
            SearchResult(
                chunk_id=chunk.chunk_id,
                relative_path=chunk.relative_path,
                score=float(score),
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=chunk.content,
            )
        )
    return results


def _ensure_dependencies() -> None:
    try:
        import faiss  # noqa: F401
        import sentence_transformers  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "Missing indexing dependencies. Install sentence-transformers and faiss-cpu."
        ) from exc
