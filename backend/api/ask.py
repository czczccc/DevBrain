import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.ai_provider_service import AIProviderError, get_active_runtime_provider
from backend.services.llm_client import (
    DEFAULT_SYSTEM_PROMPT,
    LLMClientError,
    chat_completion,
)
from backend.services.repo_analysis_service import (
    FileAnalysisRecord,
    ProjectAnalysisContext,
    load_project_analysis_context,
)
from backend.settings import settings
from core.indexing import search_index

ASK_SYSTEM_PROMPT = (
    "You are DevBrain, a codebase analysis assistant. "
    "Use only the provided repository summary, file analyses, and code windows. "
    "Separate direct observations from inference when there is uncertainty. "
    "Cite concrete files and line ranges whenever possible."
)

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
    analysis_ready: bool
    repo_summary: str | None = None


@router.post("/ask", response_model=AskResponse)
def ask_question(payload: AskRequest) -> AskResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty")

    _read_project_metadata(payload.project_id)
    _ensure_index_files(payload.project_id)
    matches = _search_matches(payload.project_id, question, payload.top_k)
    if not matches:
        raise HTTPException(status_code=400, detail="No relevant context found for this question")
    try:
        provider = get_active_runtime_provider()
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    analysis_context = load_project_analysis_context(
        project_id=payload.project_id,
        file_paths=_matched_file_paths(matches),
    )
    prompt = _build_prompt(question=question, matches=matches, analysis_context=analysis_context)
    try:
        answer = chat_completion(
            prompt=prompt,
            config=provider,
            system_prompt=_system_prompt_for_context(analysis_context),
        )
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AskResponse(
        answer=answer,
        sources=_build_sources(matches),
        analysis_ready=analysis_context.analysis_ready,
        repo_summary=analysis_context.repo_summary,
    )


def _search_matches(project_id: str, question: str, top_k: int):
    try:
        return search_index(
            project_id=project_id,
            query=question,
            top_k=top_k,
            model_name=settings.embedding_model,
            index_dir="data/index",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Index not found. Build index first.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _matched_file_paths(matches) -> list[str]:
    seen: set[str] = set()
    file_paths: list[str] = []
    for match in matches:
        if match.relative_path in seen:
            continue
        seen.add(match.relative_path)
        file_paths.append(match.relative_path)
    return file_paths


def _build_prompt(question: str, matches, analysis_context: ProjectAnalysisContext) -> str:
    sections = [
        "Answer the user question only with the provided repository context.",
        "If some detail is not supported by the provided context, say that clearly.",
        f"Question: {question}",
        _repo_summary_section(analysis_context),
        _file_analysis_section(analysis_context.file_analyses),
        _code_context_section(matches),
    ]
    return "\n\n".join(section for section in sections if section)


def _repo_summary_section(analysis_context: ProjectAnalysisContext) -> str:
    if not analysis_context.repo_summary:
        return "Repository Summary:\nNot available yet. Repository analysis has not completed."
    return f"Repository Summary:\n{analysis_context.repo_summary}"


def _file_analysis_section(file_analyses: list[FileAnalysisRecord]) -> str:
    if not file_analyses:
        return "File Analyses:\nNot available for the matched files yet."
    lines = ["File Analyses:"]
    for analysis in file_analyses:
        lines.extend(
            [
                f"- file: {analysis.file_path}",
                f"  summary: {analysis.file_summary}",
                f"  key_symbols: {', '.join(analysis.key_symbols) if analysis.key_symbols else 'none'}",
                (
                    "  dependencies_or_calls: "
                    f"{', '.join(analysis.dependencies_or_calls) if analysis.dependencies_or_calls else 'none'}"
                ),
            ]
        )
    return "\n".join(lines)


def _code_context_section(matches) -> str:
    context_parts: list[str] = []
    for idx, match in enumerate(matches, start=1):
        context_parts.append(
            "\n".join(
                [
                    f"[Code Context {idx}]",
                    f"file: {match.relative_path}",
                    f"line_range: {match.start_line}-{match.end_line}",
                    f"window_index: {match.window_index}",
                    f"key_symbols: {', '.join(match.key_symbols) if match.key_symbols else 'none'}",
                    "code:",
                    match.content,
                ]
            )
        )
    return "Code Windows:\n\n" + "\n\n".join(context_parts)


def _system_prompt_for_context(analysis_context: ProjectAnalysisContext) -> str:
    if analysis_context.analysis_ready:
        return ASK_SYSTEM_PROMPT
    return DEFAULT_SYSTEM_PROMPT


def _build_sources(matches) -> list[SourceItem]:
    return [
        SourceItem(
            file_path=item.relative_path,
            line_range=f"{item.start_line}-{item.end_line}",
            start_line=item.start_line,
            end_line=item.end_line,
            score=item.score,
        )
        for item in matches
    ]


def _read_project_metadata(project_id: str) -> dict[str, str | int | list[str] | bool | None]:
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
