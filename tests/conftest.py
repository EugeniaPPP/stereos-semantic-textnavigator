from pathlib import Path

import pytest

DOCUMENTS_DIR = Path(__file__).resolve().parent.parent / "documents"


@pytest.fixture(scope="session")
def source_files() -> list[tuple[str, bytes]]:
    """Raw (filename, bytes) pairs of the sample documents."""
    files = [(path.name, path.read_bytes()) for path in sorted(DOCUMENTS_DIR.glob("*.txt"))]
    assert files, "documents/ must contain sample TXT files"
    return files
