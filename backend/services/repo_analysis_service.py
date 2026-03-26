"""Background repository analysis built on indexed code windows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
from threading import Lock
import uuid

from backend.models import RuntimeAIProvider
from backend.services.llm_client import (
    LLMClientError,
    chat_completion,
)
from core.chunking import CodeChunk
from core.code_intelligence import FileIntelligence, extract_file_intelligence
from core.indexing import load_chunks
from core.repo_ingestion import RepoDocument, RepoIngestor

ANALYSIS_ROOT = Path("data/analysis")
JOBS_DIR = ANALYSIS_ROOT / "jobs"
PROJECTS_DIR = ANALYSIS_ROOT / "projects"
ACTIVE_ANALYSIS_JOBS: set[str] = set()
ACTIVE_ANALYSIS_JOBS_LOCK = Lock()
STALE_JOB_THRESHOLD = timedelta(seconds=90)
WINDOW_BATCH_SIZE = 4
REPO_SUMMARY_BATCH_SIZE = 25
SMALL_FILE_MAX_WINDOWS = 3
SMALL_FILE_MAX_CHARS = 12000
FIRST_PASS_FILE_LIMIT = 24
PRIMARY_CODE_EXTENSIONS = {".py", ".ts", ".js"}
LOW_PRIORITY_PATH_PARTS = {
    "docs",
    "examples",
    "samples",
    "tests",
    "test",
    "fixtures",
    "mocks",
    "__tests__",
}
WINDOW_SUMMARY_SYSTEM_PROMPT = (
    "You analyze source code windows for one file. "
    "Return valid JSON only."
)
FILE_SUMMARY_SYSTEM_PROMPT = (
    "You synthesize a file-level understanding from code window analyses. "
    "Return valid JSON only."
)
REPO_SUMMARY_SYSTEM_PROMPT = (
    "你负责为代码仓库生成中文总结。"
    "总结正文必须使用简体中文。"
    "文件名、类名、函数名、变量名、命令、库名、框架名，以及常见 IT / 编程术语保持原文。"
    "输出精炼 Markdown，不要使用 JSON。"
)


@dataclass(frozen=True)
class LineWindowAnalysis:
    """LLM interpretation for a line window."""

    window_index: int
    start_line: int
    end_line: int
    summary: str


@dataclass(frozen=True)
class FileAnalysisRecord:
    """Persisted understanding for a single file."""

    file_path: str
    file_summary: str
    line_windows: list[LineWindowAnalysis]
    key_symbols: list[str] = field(default_factory=list)
    dependencies_or_calls: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectAnalysisContext:
    """Loaded analysis context for `/ask` prompt construction."""

    analysis_ready: bool
    repo_summary: str | None
    file_analyses: list[FileAnalysisRecord]


@dataclass(frozen=True)
class AnalysisJobStatus:
    """Persistent status for background analysis work."""

    job_id: str
    project_id: str
    status: str
    total_files: int
    completed_files: int
    failed_files: int
    current_file: str | None
    repo_summary_ready: bool
    started_at: str | None
    finished_at: str | None
    updated_at: str
    error: str | None = None


def create_analysis_job(project_id: str) -> AnalysisJobStatus:
    """Create a fresh job record for a project analysis run."""

    reset_project_analysis(project_id)
    _ensure_analysis_dirs()
    status = AnalysisJobStatus(
        job_id=uuid.uuid4().hex,
        project_id=project_id,
        status="pending",
        total_files=0,
        completed_files=0,
        failed_files=0,
        current_file=None,
        repo_summary_ready=False,
        started_at=None,
        finished_at=None,
        updated_at=_utc_now(),
    )
    _save_job_status(status)
    return status


def run_analysis_job(project_id: str, root_path: str, job_id: str, config: RuntimeAIProvider) -> None:
    """Analyze repository files and persist per-file summaries in the background."""

    status = get_analysis_job_status(job_id)
    _mark_job_active(job_id)
    try:
        status = _start_job(status)
        documents, windows_by_file = _load_analysis_inputs(project_id=project_id, root_path=root_path)
        ordered_documents = _prioritize_documents(documents)
        first_pass_docs, remaining_docs = _split_analysis_phases(ordered_documents)
        status = _save_job_status(replace(status, total_files=len(ordered_documents)))
        analyses, status = _analyze_documents(
            project_id,
            first_pass_docs,
            windows_by_file,
            config,
            status,
        )
        if remaining_docs and analyses:
            status = _publish_repo_summary_snapshot(project_id, analyses, config, status)
        remaining_analyses, status = _analyze_documents(
            project_id,
            remaining_docs,
            windows_by_file,
            config,
            status,
        )
        analyses.extend(remaining_analyses)
        repo_summary = _safely_build_repo_summary(project_id, analyses, config)
        final_status = _finish_job(status.job_id, bool(repo_summary))
        if final_status.failed_files or (analyses and not final_status.repo_summary_ready):
            _save_job_status(replace(final_status, status="completed_with_errors"))
        else:
            _save_job_status(replace(final_status, status="completed"))
    except Exception as exc:
        _save_job_status(_failed_job(status.job_id, str(exc)))
    finally:
        _mark_job_inactive(job_id)


def get_analysis_job_status(job_id: str) -> AnalysisJobStatus:
    """Read a job status, marking stale runs as interrupted."""

    status = _load_job_status(job_id)
    if _is_stale_running_job(status):
        status = replace(
            status,
            status="interrupted",
            current_file=None,
            finished_at=_utc_now(),
            updated_at=_utc_now(),
            error="Analysis job was interrupted before completion.",
        )
        _save_job_status(status)
    return status


def load_project_analysis_context(
    project_id: str,
    file_paths: list[str],
) -> ProjectAnalysisContext:
    """Return repo and file-level understanding for `/ask`."""

    repo_summary = _read_repo_summary(project_id)
    file_analyses = [analysis for path in file_paths if (analysis := _read_file_analysis(project_id, path))]
    return ProjectAnalysisContext(
        analysis_ready=repo_summary is not None,
        repo_summary=repo_summary,
        file_analyses=file_analyses,
    )


def reset_project_analysis(project_id: str) -> None:
    """Delete prior analysis artifacts for a project."""

    project_dir = _project_dir(project_id)
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=True)


def _analyze_documents(
    project_id: str,
    documents: list[RepoDocument],
    windows_by_file: dict[str, list[CodeChunk]],
    config: RuntimeAIProvider,
    job_status: AnalysisJobStatus,
) -> tuple[list[FileAnalysisRecord], AnalysisJobStatus]:
    analyses: list[FileAnalysisRecord] = []
    status = job_status
    for document in documents:
        status = _save_job_status(replace(status, current_file=document.relative_path))
        try:
            analysis = _analyze_document(document, windows_by_file[document.relative_path], config)
        except Exception as exc:
            status = _advance_failed_file(status, str(exc))
            continue
        _write_file_analysis(project_id, analysis)
        analyses.append(analysis)
        status = _advance_completed_file(status)
    return analyses, status


def _prioritize_documents(documents: list[RepoDocument]) -> list[RepoDocument]:
    return sorted(
        documents,
        key=lambda document: (
            _document_priority(document),
            document.relative_path.count("/"),
            document.relative_path.lower(),
        ),
    )


def _document_priority(document: RepoDocument) -> int:
    path = Path(document.relative_path)
    suffix = path.suffix.lower()
    lower_parts = {part.lower() for part in path.parts[:-1]}
    lower_name = path.name.lower()
    in_low_priority_path = bool(lower_parts & LOW_PRIORITY_PATH_PARTS)
    looks_like_test_file = ".test." in lower_name or ".spec." in lower_name

    if suffix in PRIMARY_CODE_EXTENSIONS and not in_low_priority_path and not looks_like_test_file:
        return 0
    if len(path.parts) == 1 and (lower_name == "readme.md" or suffix == ".json"):
        return 1
    return 2


def _split_analysis_phases(
    documents: list[RepoDocument],
) -> tuple[list[RepoDocument], list[RepoDocument]]:
    if len(documents) <= FIRST_PASS_FILE_LIMIT:
        return documents, []
    return documents[:FIRST_PASS_FILE_LIMIT], documents[FIRST_PASS_FILE_LIMIT:]


def _publish_repo_summary_snapshot(
    project_id: str,
    analyses: list[FileAnalysisRecord],
    config: RuntimeAIProvider,
    status: AnalysisJobStatus,
) -> AnalysisJobStatus:
    repo_summary = _safely_build_repo_summary(project_id, analyses, config)
    if not repo_summary:
        return status
    return _save_job_status(
        replace(
            status,
            repo_summary_ready=True,
            updated_at=_utc_now(),
        )
    )


def _analyze_document(
    document: RepoDocument,
    windows: list[CodeChunk],
    config: RuntimeAIProvider,
) -> FileAnalysisRecord:
    intelligence = extract_file_intelligence(document)
    if _is_small_file(document, windows):
        return _analyze_small_file(document, windows, intelligence, config)

    line_windows = _analyze_large_file_windows(document, windows, intelligence, config)
    file_summary, dependencies = _synthesize_file_summary(
        file_path=document.relative_path,
        line_windows=line_windows,
        intelligence=intelligence,
        config=config,
    )
    return FileAnalysisRecord(
        file_path=document.relative_path,
        file_summary=file_summary,
        line_windows=line_windows,
        key_symbols=intelligence.key_symbols,
        dependencies_or_calls=dependencies or intelligence.dependencies_or_calls,
    )

def _load_analysis_inputs(
    project_id: str,
    root_path: str,
) -> tuple[list[RepoDocument], dict[str, list[CodeChunk]]]:
    ingestor = RepoIngestor()
    ingestion = ingestor.ingest(root_path)
    chunks = load_chunks(Path("data/index") / f"{project_id}.chunks.json")
    windows_by_file = _group_chunks_by_file(chunks)
    documents: list[RepoDocument] = []
    for document in ingestion.documents:
        if document.relative_path not in windows_by_file:
            continue
        documents.append(document)
    return documents, windows_by_file


def _group_chunks_by_file(chunks: list[CodeChunk]) -> dict[str, list[CodeChunk]]:
    grouped: dict[str, list[CodeChunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.relative_path, []).append(chunk)
    for file_path in grouped:
        grouped[file_path] = sorted(grouped[file_path], key=lambda item: item.window_index)
    return grouped


def _is_small_file(document: RepoDocument, windows: list[CodeChunk]) -> bool:
    return len(windows) <= SMALL_FILE_MAX_WINDOWS and len(document.content) <= SMALL_FILE_MAX_CHARS


def _analyze_small_file(
    document: RepoDocument,
    windows: list[CodeChunk],
    intelligence: FileIntelligence,
    config: RuntimeAIProvider,
) -> FileAnalysisRecord:
    prompt = _build_small_file_prompt(document, windows, intelligence)
    raw_response = chat_completion(
        prompt=prompt,
        config=config,
        system_prompt=WINDOW_SUMMARY_SYSTEM_PROMPT,
    )
    parsed = _parse_json_response(raw_response)
    line_windows = _parse_line_window_items(parsed.get("line_windows", []), windows)
    file_summary = _safe_text(parsed.get("file_summary"))
    dependencies = _parse_string_list(parsed.get("dependencies_or_calls"))
    return FileAnalysisRecord(
        file_path=document.relative_path,
        file_summary=file_summary,
        line_windows=line_windows,
        key_symbols=_merge_lists(intelligence.key_symbols, _parse_string_list(parsed.get("key_symbols"))),
        dependencies_or_calls=_merge_lists(intelligence.dependencies_or_calls, dependencies),
    )


def _analyze_large_file_windows(
    document: RepoDocument,
    windows: list[CodeChunk],
    intelligence: FileIntelligence,
    config: RuntimeAIProvider,
) -> list[LineWindowAnalysis]:
    analyses: list[LineWindowAnalysis] = []
    for window_batch in _batched(windows, WINDOW_BATCH_SIZE):
        prompt = _build_window_batch_prompt(document.relative_path, window_batch, intelligence)
        raw_response = chat_completion(
            prompt=prompt,
            config=config,
            system_prompt=WINDOW_SUMMARY_SYSTEM_PROMPT,
        )
        parsed = _parse_json_response(raw_response)
        analyses.extend(_parse_line_window_items(parsed.get("line_windows", []), window_batch))
    return sorted(analyses, key=lambda item: item.window_index)


def _synthesize_file_summary(
    file_path: str,
    line_windows: list[LineWindowAnalysis],
    intelligence: FileIntelligence,
    config: RuntimeAIProvider,
) -> tuple[str, list[str]]:
    prompt = _build_file_summary_prompt(file_path, line_windows, intelligence)
    raw_response = chat_completion(
        prompt=prompt,
        config=config,
        system_prompt=FILE_SUMMARY_SYSTEM_PROMPT,
    )
    parsed = _parse_json_response(raw_response)
    file_summary = _safe_text(parsed.get("file_summary"))
    dependencies = _merge_lists(
        intelligence.dependencies_or_calls,
        _parse_string_list(parsed.get("dependencies_or_calls")),
    )
    return file_summary, dependencies


def _synthesize_repo_summary(
    analyses: list[FileAnalysisRecord],
    config: RuntimeAIProvider,
) -> str | None:
    if not analyses:
        return None

    batch_summaries = [
        _summarize_repo_batch(batch, config) for batch in _batched(analyses, REPO_SUMMARY_BATCH_SIZE)
    ]
    if len(batch_summaries) == 1:
        return batch_summaries[0]

    prompt = "\n\n".join(
        [
            (
                "请基于下面的分组文件总结，输出这个仓库的中文总结。"
                "至少覆盖：项目用途、核心模块、入口/启动点、关键补充观察。"
                "说明文字用中文，代码元素和专业术语保持原文。"
            ),
            "\n\n".join(
                f"[Group {index}]\n{summary}" for index, summary in enumerate(batch_summaries, start=1)
            ),
        ]
    )
    return chat_completion(prompt=prompt, config=config, system_prompt=REPO_SUMMARY_SYSTEM_PROMPT)


def _safely_build_repo_summary(
    project_id: str,
    analyses: list[FileAnalysisRecord],
    config: RuntimeAIProvider,
) -> str | None:
    try:
        repo_summary = _synthesize_repo_summary(analyses, config)
    except Exception:
        return None
    if repo_summary:
        _write_repo_summary(project_id, repo_summary)
    return repo_summary


def _summarize_repo_batch(analyses: list[FileAnalysisRecord], config: RuntimeAIProvider) -> str:
    prompt = "\n\n".join(
        [
            (
                "请用中文总结这批文件对应的仓库信息，至少覆盖：项目用途、核心模块、"
                "入口/启动点、关键补充观察。说明文字用中文，代码元素和专业术语保持原文。"
            ),
            "\n\n".join(
                f"file: {analysis.file_path}\nsummary: {analysis.file_summary}"
                for analysis in analyses
            ),
        ]
    )
    return chat_completion(prompt=prompt, config=config, system_prompt=REPO_SUMMARY_SYSTEM_PROMPT)


def _build_small_file_prompt(
    document: RepoDocument,
    windows: list[CodeChunk],
    intelligence: FileIntelligence,
) -> str:
    instructions = [
        "Return strict JSON with keys: file_summary, key_symbols, dependencies_or_calls, line_windows.",
        "line_windows must be an array of objects with window_index, start_line, end_line, summary.",
        "Explain each requested window so that every included line range is understandable.",
        f"file_path: {document.relative_path}",
        f"language: {document.language}",
        f"known_symbols: {', '.join(intelligence.key_symbols) if intelligence.key_symbols else 'none'}",
        "code:",
        document.content,
        "windows:",
        "\n".join(_window_label(chunk) for chunk in windows),
    ]
    return "\n\n".join(instructions)


def _build_window_batch_prompt(
    file_path: str,
    windows: list[CodeChunk],
    intelligence: FileIntelligence,
) -> str:
    instructions = [
        "Return strict JSON with one key: line_windows.",
        "line_windows must be an array of objects with window_index, start_line, end_line, summary.",
        f"file_path: {file_path}",
        f"known_symbols: {', '.join(intelligence.key_symbols) if intelligence.key_symbols else 'none'}",
        "\n\n".join(_window_block(chunk) for chunk in windows),
    ]
    return "\n\n".join(instructions)


def _build_file_summary_prompt(
    file_path: str,
    line_windows: list[LineWindowAnalysis],
    intelligence: FileIntelligence,
) -> str:
    instructions = [
        "Return strict JSON with keys: file_summary, dependencies_or_calls.",
        f"file_path: {file_path}",
        f"known_symbols: {', '.join(intelligence.key_symbols) if intelligence.key_symbols else 'none'}",
        "window_summaries:",
        "\n".join(_window_analysis_line(item) for item in line_windows),
    ]
    return "\n\n".join(instructions)


def _window_label(chunk: CodeChunk) -> str:
    return (
        f"- window_index={chunk.window_index}, start_line={chunk.start_line}, "
        f"end_line={chunk.end_line}"
    )


def _window_block(chunk: CodeChunk) -> str:
    return "\n".join(
        [
            f"[Window {chunk.window_index}]",
            f"start_line: {chunk.start_line}",
            f"end_line: {chunk.end_line}",
            "code:",
            chunk.content,
        ]
    )


def _window_analysis_line(window: LineWindowAnalysis) -> str:
    return (
        f"- window_index={window.window_index}, lines={window.start_line}-{window.end_line}, "
        f"summary={window.summary}"
    )


def _parse_line_window_items(raw_items, windows: list[CodeChunk]) -> list[LineWindowAnalysis]:
    items_by_index = {item.window_index: item for item in _coerce_line_windows(raw_items)}
    analyses: list[LineWindowAnalysis] = []
    for window in windows:
        analysis = items_by_index.get(window.window_index)
        if analysis is None:
            raise LLMClientError(
                f"Missing analysis for window {window.window_index} in {window.relative_path}"
            )
        analyses.append(analysis)
    return analyses


def _coerce_line_windows(raw_items) -> list[LineWindowAnalysis]:
    if not isinstance(raw_items, list):
        raise LLMClientError("AI analysis response missing line_windows array")

    analyses: list[LineWindowAnalysis] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        analyses.append(
            LineWindowAnalysis(
                window_index=int(item.get("window_index", 0)),
                start_line=int(item.get("start_line", 1)),
                end_line=int(item.get("end_line", item.get("start_line", 1))),
                summary=_safe_text(item.get("summary")),
            )
        )
    return analyses


def _parse_json_response(raw_text: str) -> dict:
    try:
        return json.loads(raw_text)
    except ValueError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start < 0 or end <= start:
            raise LLMClientError("AI analysis response is not valid JSON")
        return json.loads(raw_text[start : end + 1])


def _parse_string_list(raw_value) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    cleaned = [str(item).strip() for item in raw_value if str(item).strip()]
    return cleaned[:20]


def _safe_text(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LLMClientError("AI analysis response missing required text field")
    return value.strip()


def _write_file_analysis(project_id: str, analysis: FileAnalysisRecord) -> None:
    path = _analysis_file_path(project_id, analysis.file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(analysis), ensure_ascii=False, indent=2), encoding="utf-8")


def _read_file_analysis(project_id: str, file_path: str) -> FileAnalysisRecord | None:
    path = _analysis_file_path(project_id, file_path)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["line_windows"] = [LineWindowAnalysis(**item) for item in payload["line_windows"]]
    return FileAnalysisRecord(**payload)


def _write_repo_summary(project_id: str, repo_summary: str) -> None:
    path = _project_dir(project_id) / "repo_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"repo_summary": repo_summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_repo_summary(project_id: str) -> str | None:
    path = _project_dir(project_id) / "repo_summary.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("repo_summary")
    return summary if isinstance(summary, str) and summary.strip() else None


def _save_job_status(status: AnalysisJobStatus) -> AnalysisJobStatus:
    _ensure_analysis_dirs()
    path = _job_status_path(status.job_id)
    path.write_text(json.dumps(asdict(status), ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def _load_job_status(job_id: str) -> AnalysisJobStatus:
    path = _job_status_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"Analysis job {job_id} not found")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AnalysisJobStatus(**payload)


def _start_job(status: AnalysisJobStatus) -> AnalysisJobStatus:
    started_at = _utc_now()
    return _save_job_status(
        replace(
            status,
            status="running",
            started_at=started_at,
            updated_at=started_at,
        )
    )


def _advance_completed_file(status: AnalysisJobStatus) -> AnalysisJobStatus:
    return _save_job_status(
        replace(
            status,
            completed_files=status.completed_files + 1,
            updated_at=_utc_now(),
        )
    )


def _advance_failed_file(status: AnalysisJobStatus, error: str) -> AnalysisJobStatus:
    return _save_job_status(
        replace(
            status,
            failed_files=status.failed_files + 1,
            updated_at=_utc_now(),
            error=error,
        )
    )


def _finish_job(job_id: str, repo_summary_ready: bool) -> AnalysisJobStatus:
    status = _load_job_status(job_id)
    finished_at = _utc_now()
    return _save_job_status(
        replace(
            status,
            current_file=None,
            repo_summary_ready=status.repo_summary_ready or repo_summary_ready,
            finished_at=finished_at,
            updated_at=finished_at,
        )
    )


def _failed_job(job_id: str, error: str) -> AnalysisJobStatus:
    status = _load_job_status(job_id)
    finished_at = _utc_now()
    return replace(
        status,
        status="failed",
        current_file=None,
        finished_at=finished_at,
        updated_at=finished_at,
        error=error,
    )


def _analysis_file_path(project_id: str, file_path: str) -> Path:
    digest = hashlib.sha1(file_path.encode("utf-8")).hexdigest()
    return _project_dir(project_id) / "files" / f"{digest}.json"


def _project_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id


def _job_status_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _ensure_analysis_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _mark_job_active(job_id: str) -> None:
    with ACTIVE_ANALYSIS_JOBS_LOCK:
        ACTIVE_ANALYSIS_JOBS.add(job_id)


def _mark_job_inactive(job_id: str) -> None:
    with ACTIVE_ANALYSIS_JOBS_LOCK:
        ACTIVE_ANALYSIS_JOBS.discard(job_id)


def _is_stale_running_job(status: AnalysisJobStatus) -> bool:
    if status.status not in {"pending", "running"}:
        return False
    with ACTIVE_ANALYSIS_JOBS_LOCK:
        if status.job_id in ACTIVE_ANALYSIS_JOBS:
            return False
    updated_at = datetime.fromisoformat(status.updated_at)
    return datetime.now(UTC) - updated_at > STALE_JOB_THRESHOLD


def _batched(items: list, batch_size: int) -> list[list]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _merge_lists(primary: list[str], secondary: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in primary + secondary:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        merged.append(cleaned)
    return merged[:20]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
