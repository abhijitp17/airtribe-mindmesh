"""The test run can never touch a developer's database or uploads (see conftest.py)."""
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.config import get_settings
from tests.conftest import _refuse_unless_throwaway


def test_settings_point_at_throwaway_locations():
    s = get_settings()
    temp = Path(tempfile.gettempdir()).resolve()
    assert s.database_url.startswith("sqlite:///")
    assert Path(s.database_url.removeprefix("sqlite:///")).resolve().is_relative_to(temp), s.database_url
    assert Path(s.storage_dir).resolve().is_relative_to(temp), s.storage_dir


@pytest.mark.parametrize("url", [
    "sqlite:///./mindmesh.db",
    "sqlite:////Users/someone/Desktop/Mindmesh/backend/mindmesh.db",
    "postgresql+psycopg://mindmesh:mindmesh@localhost:5432/mindmesh",
])
def test_reset_guard_refuses_real_databases(url):
    with pytest.raises(RuntimeError, match="Refusing to reset"):
        _refuse_unless_throwaway(create_engine(url))


def test_reset_guard_allows_temp_sqlite():
    _refuse_unless_throwaway(create_engine(f"sqlite:///{tempfile.gettempdir()}/x/tests.db"))
