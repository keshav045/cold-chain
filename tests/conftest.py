import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from coldchain.config import make_config  # noqa: E402
from coldchain.export import export_all  # noqa: E402
from coldchain.generate import generate  # noqa: E402


@pytest.fixture(scope="session")
def result():
    return generate(make_config("starter"))


@pytest.fixture(scope="session")
def starter_dir(tmp_path_factory, result):
    d = tmp_path_factory.mktemp("starter")
    export_all(result, str(d), ("csv", "json", "sql"))
    return str(d)


@pytest.fixture()
def tables(result):
    """Deep copies of the generated tables AND ground-truth that tests may freely corrupt."""
    return {k: v.copy(deep=True) for k, v in result.tables.items()}, result.ground_truth.copy(deep=True)
