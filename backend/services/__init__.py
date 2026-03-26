"""Service-layer modules for backend integrations."""

from .deepseek_client import (
    DEFAULT_SYSTEM_PROMPT,
    DeepSeekAPIError,
    DeepSeekConfig,
    chat_completion,
    chat_completion_from_messages,
)
from .repo_analysis_service import (
    AnalysisJobStatus,
    FileAnalysisRecord,
    ProjectAnalysisContext,
    create_analysis_job,
    get_analysis_job_status,
    load_project_analysis_context,
    reset_project_analysis,
    run_analysis_job,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "DeepSeekAPIError",
    "DeepSeekConfig",
    "chat_completion",
    "chat_completion_from_messages",
    "AnalysisJobStatus",
    "FileAnalysisRecord",
    "ProjectAnalysisContext",
    "create_analysis_job",
    "get_analysis_job_status",
    "load_project_analysis_context",
    "reset_project_analysis",
    "run_analysis_job",
]
