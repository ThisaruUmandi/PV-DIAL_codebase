import sys

import pytest


@pytest.fixture(autouse=True)
def _restore_main_module():
    """Streamlit's AppTest runs the app script as __main__ and leaves it that way;
    a later test that spawns a worker process (provenance replay, re-execution)
    would then try to re-run the app in the child. Put __main__ back."""
    saved = sys.modules.get("__main__")
    yield
    if saved is not None:
        sys.modules["__main__"] = saved
