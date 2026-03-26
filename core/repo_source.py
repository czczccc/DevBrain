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


@dataclass(frozen=True)
class RepoCloneResult:
    """Resolved repository path and whether a local cache was reused."""

    path: Path
    normalized_url: str
    cache_reused: bool


def clone_github_repository(
    github_url: str,
    target_dir: str | Path,
    github_token: str | None = None,
) -> RepoCloneResult:
    """Clone a GitHub repository to target_dir and return normalized path."""

    normalized_url = normalize_github_url(github_url)
    if not GITHUB_URL_PATTERN.match(github_url.strip()):
        raise RepoSourceError(
            status_code=400,
            message="github_url must match https://github.com/<owner>/<repo>(.git)",
        )

    root = Path(target_dir).expanduser().resolve()
    if root.exists():
        if not root.is_dir():
            raise RepoSourceError(status_code=400, message="target_dir must be a directory path")
        if any(root.iterdir()):
            if is_cached_github_repository(root, normalized_url):
                return RepoCloneResult(
                    path=root,
                    normalized_url=normalized_url,
                    cache_reused=True,
                )
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
        return RepoCloneResult(
            path=root,
            normalized_url=normalized_url,
            cache_reused=False,
        )

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


def normalize_github_url(github_url: str) -> str:
    """Normalize a GitHub HTTPS URL for cache matching."""

    normalized = github_url.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def is_cached_github_repository(target_dir: str | Path, github_url: str) -> bool:
    """Return True when target_dir is a git repo whose origin matches github_url."""

    root = Path(target_dir).expanduser().resolve()
    if not root.is_dir() or not (root / ".git").exists():
        return False

    origin_url = _read_origin_url(root)
    if not origin_url:
        return False

    return normalize_github_url(origin_url) == normalize_github_url(github_url)


def _read_origin_url(root: Path) -> str | None:
    """Read the remote origin URL for a local git repository."""

    command = ["git", "-C", root.as_posix(), "config", "--get", "remote.origin.url"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env={"GIT_TERMINAL_PROMPT": "0", **os.environ},
        )
    except FileNotFoundError:
        return None

    if completed.returncode != 0:
        return None

    origin = (completed.stdout or "").strip()
    return origin or None
