from pathlib import Path
from contextlib import contextmanager
import shutil
import uuid

TEST_TMP_ROOT = Path(__file__).resolve().parents[1] / ".tmp_test"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


@contextmanager
def temporary_directory():
    """Create an isolated temporary directory under repository writable root."""
    path = TEST_TMP_ROOT / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)
