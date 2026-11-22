import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_DIR.parents[1]

# The project package (src/sales) and job entrypoint are importable as in the workspace.
for path in (PROJECT_DIR / "src", PROJECT_DIR / "src" / "jobs", REPO_ROOT / "shared" / "python"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


@pytest.fixture
def project_dir() -> Path:
    return PROJECT_DIR


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
