import json
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from backend.settings import settings
from core.chunking import chunk_documents
from core.indexing import build_and_save_index, search_index
from core.repo_import import (
    DEFAULT_SCAN_IGNORED_DIRS,
    save_project_metadata,
    scan_repository_files,
)
from core.repo_ingestion import RepoIngestor
from core.repo_source import RepoSourceError, clone_github_repository

router = APIRouter(prefix="/repo", tags=["repo"])


class RepoLoadRequest(BaseModel):
    local_path: str | None = Field(
        default=None,
        description="Absolute or relative local repository path",
    )
    github_url: str | None = Field(
        default=None,
        description="GitHub HTTPS URL (https://github.com/<owner>/<repo>(.git))",
    )
    target_dir: str | None = Field(
        default=None,
        description="Required for github_url mode; destination clone directory",
    )


class RepoFileItem(BaseModel):
    path: str
    size: int


class RepoMetadataItem(BaseModel):
    project_id: str
    root_path: str
    imported_at: str
    file_count: int
    ignored_dirs: list[str]


class RepoLoadResponse(BaseModel):
    metadata: RepoMetadataItem
    files: list[RepoFileItem]


class RepoIndexRequest(BaseModel):
    project_id: str


class RepoIndexResponse(BaseModel):
    project_id: str
    root_path: str
    document_count: int
    chunk_count: int
    model_name: str


class RepoSearchRequest(BaseModel):
    project_id: str
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class SearchItem(BaseModel):
    chunk_id: str
    path: str
    score: float
    start_line: int
    end_line: int
    content: str


class RepoSearchResponse(BaseModel):
    project_id: str
    query: str
    results: list[SearchItem]


@router.post("/load", response_model=RepoLoadResponse)
def load_repo(
    payload: RepoLoadRequest,
    x_github_token: str | None = Header(default=None, alias="X-GitHub-Token"),
) -> RepoLoadResponse:
    root = _resolve_repo_root(payload=payload, github_token=x_github_token)

    scanned_files = scan_repository_files(root, ignored_dirs=DEFAULT_SCAN_IGNORED_DIRS)
    metadata = save_project_metadata(
        root,
        scanned_files,
        output_dir="data/projects",
        ignored_dirs=DEFAULT_SCAN_IGNORED_DIRS,
    )

    return RepoLoadResponse(
        metadata=RepoMetadataItem(**metadata.__dict__),
        files=[RepoFileItem(path=item.path, size=item.size) for item in scanned_files],
    )


@router.post("/index", response_model=RepoIndexResponse)
def index_repo(payload: RepoIndexRequest) -> RepoIndexResponse:
    metadata = _read_project_metadata(payload.project_id)
    root_path = Path(metadata["root_path"])
    ingestion = RepoIngestor().ingest(root_path)
    chunks = chunk_documents(ingestion.documents)

    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks available to index")

    try:
        index_info = build_and_save_index(
            project_id=payload.project_id,
            chunks=chunks,
            model_name=settings.embedding_model,
            output_dir="data/index",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RepoIndexResponse(
        project_id=payload.project_id,
        root_path=metadata["root_path"],
        document_count=len(ingestion.documents),
        chunk_count=index_info["chunk_count"],
        model_name=index_info["model_name"],
    )


@router.post("/search", response_model=RepoSearchResponse)
def semantic_search(payload: RepoSearchRequest) -> RepoSearchResponse:
    _read_project_metadata(payload.project_id)

    try:
        results = search_index(
            project_id=payload.project_id,
            query=payload.query,
            top_k=payload.top_k,
            model_name=settings.embedding_model,
            index_dir="data/index",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Index not found. Build index first.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RepoSearchResponse(
        project_id=payload.project_id,
        query=payload.query,
        results=[
            SearchItem(
                chunk_id=item.chunk_id,
                path=item.relative_path,
                score=item.score,
                start_line=item.start_line,
                end_line=item.end_line,
                content=item.content,
            )
            for item in results
        ],
    )


def _resolve_repo_root(payload: RepoLoadRequest, github_token: str | None) -> Path:
    local_path = (payload.local_path or "").strip()
    github_url = (payload.github_url or "").strip()
    target_dir = (payload.target_dir or "").strip()

    has_local = bool(local_path)
    has_github = bool(github_url)

    if has_local == has_github:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one source: local_path or github_url",
        )

    if has_local:
        root = Path(local_path).expanduser().resolve()
        if not root.exists():
            raise HTTPException(status_code=400, detail="Local path does not exist")
        if not root.is_dir():
            raise HTTPException(status_code=400, detail="Local path must be a directory")
        return root

    if not target_dir:
        raise HTTPException(status_code=400, detail="target_dir is required when github_url is provided")

    try:
        return clone_github_repository(
            github_url=github_url,
            target_dir=target_dir,
            github_token=github_token,
        )
    except RepoSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _read_project_metadata(project_id: str) -> dict[str, str | int | list[str]]:
    metadata_path = Path("data/projects") / f"{project_id}.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Project metadata not found")
    return json.loads(metadata_path.read_text(encoding="utf-8"))
