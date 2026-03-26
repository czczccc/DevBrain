import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field

from backend.services.ai_provider_service import AIProviderError, get_active_runtime_provider
from backend.services.repo_analysis_service import (
    AnalysisJobStatus,
    create_analysis_job,
    get_analysis_job_status,
    load_project_analysis_context,
    reset_project_analysis,
    run_analysis_job,
)
from backend.settings import settings
from core.chunking import chunk_documents
from core.indexing import build_and_save_index, search_index
from core.repo_import import (
    DEFAULT_SCAN_IGNORED_DIRS,
    save_project_metadata,
    scan_repository_files,
)
from core.repo_ingestion import RepoIngestor
from core.repo_source import RepoCloneResult, RepoSourceError, clone_github_repository

router = APIRouter(prefix="/repo", tags=["repo"])


class RepoLoadRequest(BaseModel):
    local_path: str | None = Field(default=None, description="Absolute or relative local repository path")
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
    source_type: str
    source_url: str | None = None
    cache_reused: bool = False


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


class RepoAnalyzeRequest(BaseModel):
    project_id: str


class RepoAnalyzeResponse(BaseModel):
    job_id: str
    project_id: str
    status: str
    total_files: int
    completed_files: int
    failed_files: int
    current_file: str | None
    repo_summary_ready: bool
    repo_summary: str | None = None


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


class ResolvedRepoSource(BaseModel):
    root_path: Path
    source_type: str
    source_url: str | None = None
    cache_reused: bool = False


@router.post("/load", response_model=RepoLoadResponse)
def load_repo(
    payload: RepoLoadRequest,
    x_github_token: str | None = Header(default=None, alias="X-GitHub-Token"),
) -> RepoLoadResponse:
    source = _resolve_repo_root(payload=payload, github_token=x_github_token)
    scanned_files = scan_repository_files(source.root_path, ignored_dirs=DEFAULT_SCAN_IGNORED_DIRS)
    metadata = save_project_metadata(
        source.root_path,
        scanned_files,
        output_dir="data/projects",
        ignored_dirs=DEFAULT_SCAN_IGNORED_DIRS,
        source_type=source.source_type,
        source_url=source.source_url,
        cache_reused=source.cache_reused,
    )
    return RepoLoadResponse(
        metadata=RepoMetadataItem(**metadata.__dict__),
        files=[RepoFileItem(path=item.path, size=item.size) for item in scanned_files],
    )


@router.post("/index", response_model=RepoIndexResponse)
def index_repo(payload: RepoIndexRequest) -> RepoIndexResponse:
    metadata = _read_project_metadata(payload.project_id)
    ingestion = RepoIngestor().ingest(Path(metadata["root_path"]))
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

    reset_project_analysis(payload.project_id)
    return RepoIndexResponse(
        project_id=payload.project_id,
        root_path=metadata["root_path"],
        document_count=len(ingestion.documents),
        chunk_count=index_info["chunk_count"],
        model_name=index_info["model_name"],
    )


@router.post("/analyze", response_model=RepoAnalyzeResponse)
def analyze_repo(
    payload: RepoAnalyzeRequest,
    background_tasks: BackgroundTasks,
) -> RepoAnalyzeResponse:
    metadata = _read_project_metadata(payload.project_id)
    _ensure_index_files(payload.project_id)
    try:
        provider = get_active_runtime_provider()
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    job = create_analysis_job(payload.project_id)
    background_tasks.add_task(
        run_analysis_job,
        payload.project_id,
        str(metadata["root_path"]),
        job.job_id,
        provider,
    )
    return _to_analyze_response(job)


@router.get("/analyze/{job_id}", response_model=RepoAnalyzeResponse)
def get_analyze_status(job_id: str) -> RepoAnalyzeResponse:
    try:
        job = get_analysis_job_status(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Analysis job not found") from exc
    return _to_analyze_response(job)


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


def _resolve_repo_root(payload: RepoLoadRequest, github_token: str | None) -> ResolvedRepoSource:
    local_path = (payload.local_path or "").strip()
    github_url = (payload.github_url or "").strip()
    target_dir = (payload.target_dir or "").strip()
    has_local = bool(local_path)
    has_github = bool(github_url)

    if has_local == has_github:
        raise HTTPException(status_code=400, detail="Provide exactly one source: local_path or github_url")

    if has_local:
        root = Path(local_path).expanduser().resolve()
        if not root.exists():
            raise HTTPException(status_code=400, detail="Local path does not exist")
        if not root.is_dir():
            raise HTTPException(status_code=400, detail="Local path must be a directory")
        return ResolvedRepoSource(root_path=root, source_type="local")

    if not target_dir:
        raise HTTPException(status_code=400, detail="target_dir is required when github_url is provided")

    try:
        result = clone_github_repository(
            github_url=github_url,
            target_dir=target_dir,
            github_token=github_token,
        )
    except RepoSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return _to_resolved_repo_source(result)


def _to_resolved_repo_source(result: RepoCloneResult) -> ResolvedRepoSource:
    return ResolvedRepoSource(
        root_path=result.path,
        source_type="github",
        source_url=result.normalized_url,
        cache_reused=result.cache_reused,
    )


def _read_project_metadata(project_id: str) -> dict[str, str | int | bool | list[str] | None]:
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


def _to_analyze_response(job: AnalysisJobStatus) -> RepoAnalyzeResponse:
    repo_summary = None
    if job.repo_summary_ready:
        repo_summary = load_project_analysis_context(job.project_id, []).repo_summary
    return RepoAnalyzeResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        status=job.status,
        total_files=job.total_files,
        completed_files=job.completed_files,
        failed_files=job.failed_files,
        current_file=job.current_file,
        repo_summary_ready=job.repo_summary_ready,
        repo_summary=repo_summary,
    )
