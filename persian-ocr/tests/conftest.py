import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    return ROOT / "samples"


@pytest.fixture(scope="session")
def sample_image(samples_dir) -> Path:
    return samples_dir / "images" / "page-01.jpg"
