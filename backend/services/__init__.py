"""Service-layer modules for backend integrations."""

from .ai_provider_service import (
    AIProviderError,
    activate_provider,
    delete_provider,
    get_active_runtime_provider,
    get_ai_config_snapshot,
    save_provider,
)
from .llm_client import (
    DEFAULT_SYSTEM_PROMPT,
    LLMClientError,
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
    "AIProviderError",
    "activate_provider",
    "delete_provider",
    "get_active_runtime_provider",
    "get_ai_config_snapshot",
    "save_provider",
    "DEFAULT_SYSTEM_PROMPT",
    "LLMClientError",
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
