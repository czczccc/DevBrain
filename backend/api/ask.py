import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.deepseek_client import DeepSeekAPIError, DeepSeekConfig, chat_completion
from backend.settings import settings
from core.indexing import search_index

router = APIRouter(tags=["ask"])


class AskRequest(BaseModel):
    project_id: str
    question: str
    top_k: int = Field(default=5, ge=1, le=20)


class SourceItem(BaseModel):
    file_path: str
    line_range: str
    start_line: int
    end_line: int
    score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceItem]


@router.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest) -> AskResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")

    _read_project_metadata(payload.project_id)
    _ensure_index_files(payload.project_id)
    try:
        matches = search_index(
            project_id=payload.project_id,
            query=question,
            top_k=payload.top_k,
            model_name=settings.embedding_model,
            index_dir="data/index",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Index not found. Build index first.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not matches:
        raise HTTPException(status_code=400, detail="No relevant context found for this question")

    if not settings.deepseek_api_key.strip():
        raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY is not configured")

    prompt = _build_prompt(question=question, matches=matches)
    try:
        answer = chat_completion(
            prompt=prompt,
            config=DeepSeekConfig(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
            ),
        )
    except DeepSeekAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    sources = [
        SourceItem(
            file_path=item.relative_path,
            line_range=f"{item.start_line}-{item.end_line}",
            start_line=item.start_line,
            end_line=item.end_line,
            score=item.score,
        )
        for item in matches
    ]
    return AskResponse(answer=answer, sources=sources)


def _build_prompt(question: str, matches) -> str:
    context_parts: list[str] = []
    for idx, match in enumerate(matches, start=1):
        context_parts.append(
            "\n".join(
                [
                    f"[Context {idx}]",
                    f"file: {match.relative_path}",
                    f"line_range: {match.start_line}-{match.end_line}",
                    "code:",
                    match.content,
                ]
            )
        )

    context = "\n\n".join(context_parts)
    return "\n\n".join(
        [
            "Answer the user question only with the provided code context.",
            "If context is insufficient, say it clearly.",
            f"Question: {question}",
            "Context:",
            context,
        ]
    )


def _read_project_metadata(project_id: str) -> dict[str, str | int | list[str]]:
    metadata_path = Path("data/projects") / f"{project_id}.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Project metadata not found")
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _ensure_index_files(project_id: str) -> None:
    index_dir = Path("data/index")
    faiss_file = index_dir / f"{project_id}.faiss"
    chunks_file = index_dir / f"{project_id}.chunks.json"
    if not faiss_file.exists() or not chunks_file.exists():
        raise HTTPException(status_code=404, detail="Index not found. Build index first.")
