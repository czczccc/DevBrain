"""Repository source helpers for remote GitHub imports."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess

GITHUB_URL_PATTERN = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?/?$"
)


@dataclass(frozen=True)
class RepoSourceError(Exception):
    """Structured error for source acquisition failures."""

    status_code: int
    message: str


def clone_github_repository(
    github_url: str,
    target_dir: str | Path,
    github_token: str | None = None,
) -> Path:
    """Clone a GitHub repository to target_dir and return normalized path."""

    normalized_url = github_url.strip()
    if not GITHUB_URL_PATTERN.match(normalized_url):
        raise RepoSourceError(
            status_code=400,
            message="github_url must match https://github.com/<owner>/<repo>(.git)",
        )

    root = Path(target_dir).expanduser().resolve()
    if root.exists():
        if not root.is_dir():
            raise RepoSourceError(status_code=400, message="target_dir must be a directory path")
        if any(root.iterdir()):
            raise RepoSourceError(status_code=409, message="target_dir already exists and is not empty")

    root.parent.mkdir(parents=True, exist_ok=True)
    existed_before = root.exists()

    command: list[str] = ["git", "clone", "--depth", "1", normalized_url, root.as_posix()]

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = github_token.strip() if github_token else ""
    if token:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {token}"

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RepoSourceError(status_code=500, message="git is not installed or not available in PATH") from exc

    if completed.returncode == 0:
        return root

    if not existed_before and root.exists():
        shutil.rmtree(root, ignore_errors=True)

    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    detail = stderr or stdout or "git clone failed"
    lowered = detail.lower()

    if _is_auth_error(lowered):
        raise RepoSourceError(status_code=401, message=_truncate(detail))
    if _is_not_found_error(lowered):
        raise RepoSourceError(status_code=404, message=_truncate(detail))
    raise RepoSourceError(status_code=502, message=_truncate(detail))


def _is_auth_error(message: str) -> bool:
    markers = (
        "authentication failed",
        "access denied",
        "http basic: access denied",
        "invalid username or password",
        "could not read username",
        "could not read password",
        "fatal: authentication",
    )
    return any(marker in message for marker in markers)


def _is_not_found_error(message: str) -> bool:
    markers = (
        "repository not found",
        "not found",
        "does not exist",
    )
    return any(marker in message for marker in markers)


def _truncate(value: str, limit: int = 300) -> str:
    cleaned = value.replace("\n", " ").strip()
    return cleaned[:limit] if len(cleaned) > limit else cleaned
