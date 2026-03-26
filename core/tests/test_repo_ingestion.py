from pathlib import Path

from core.repo_ingestion import RepoIngestor


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_ingest_filters_extensions_and_ignored_dirs(tmp_path: Path) -> None:
    _write(tmp_path / "backend" / "app.py", "print('ok')")
    _write(tmp_path / "frontend" / "index.ts", "const app = 1;")
    _write(tmp_path / "docs" / "readme.md", "# hello")
    _write(tmp_path / "data" / "seed.csv", "id,name")
    _write(tmp_path / "node_modules" / "pkg" / "index.js", "ignored")
    _write(tmp_path / ".git" / "config", "ignored")

    result = RepoIngestor().ingest(tmp_path)

    paths = [document.relative_path for document in result.documents]
    assert "backend/app.py" in paths
    assert "frontend/index.ts" in paths
    assert "docs/readme.md" in paths
    assert "data/seed.csv" not in paths
    assert all(not path.startswith("node_modules/") for path in paths)
    assert all(not path.startswith(".git/") for path in paths)
    assert result.errors == []


def test_ingest_collects_decode_errors(tmp_path: Path) -> None:
    file_path = tmp_path / "backend" / "broken.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"\xff\xfe\x00\x00")

    result = RepoIngestor().ingest(tmp_path)

    assert result.documents == []
    assert len(result.errors) == 1
    assert result.errors[0].relative_path == "backend/broken.py"
