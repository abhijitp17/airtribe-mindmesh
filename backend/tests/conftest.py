import io
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Safety first: pytest imports this before any test module, so whatever a test file imports
# (and whatever DATABASE_URL is exported in the shell), settings can never resolve to the
# developer's database or uploads. Without this, a module that cached settings at import
# time made the API tests drop the tables in ./mindmesh.db (docs/DECISIONS.md #30).
TEST_ROOT = Path(tempfile.mkdtemp(prefix="mindmesh-tests-")).resolve()
os.environ.update({
    "APP_ENV": "test",
    "AI_PROVIDER": "mock",
    "DATABASE_URL": f"sqlite:///{TEST_ROOT}/tests.db",
    "STORAGE_DIR": str(TEST_ROOT / "uploads"),
})

SAMPLE_PAGES = [
    [
        "CHAPTER 1 FLOW BASICS",
        "",
        "1.1 Little's Law",
        "",
        "Little's Law states that work in process equals throughput multiplied by cycle time.",
        "Written as a formula, WIP = TH x CT. It holds for any stable production line",
        "regardless of the arrival or service distributions.",
        "",
        "Managers use Little's Law to estimate cycle time when WIP and throughput are known.",
        "For example, a line with 120 jobs in process and a throughput of 40 jobs per day",
        "has an average cycle time of three days.",
    ],
    [
        "1.2 Variability",
        "",
        "Variability degrades the performance of a production system. Higher variability in",
        "arrivals or processing times increases queue time, which in turn increases cycle time.",
        "The coefficient of variation is the standard deviation divided by the mean.",
        "",
        "Buffers against variability take three forms: inventory, capacity, and time.",
    ],
]


def make_pdf(pages: list[list[str]]) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle("Factory Physics Sample")
    for lines in pages:
        y = 740
        for line in lines:
            c.drawString(72, y, line)
            y -= 16
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def sample_pdf() -> bytes:
    return make_pdf(SAMPLE_PAGES)


@pytest.fixture(autouse=True)
def _fresh_db(request):
    """Start every API test (anything using `client`) from empty tables.

    Each tests/test_api*.py sets its own DATABASE_URL, but app.db builds a single
    engine per process, so in a full run every file shares the first file's
    database and reused emails collide. Pure tests don't touch the DB and skip this.
    """
    if "client" in request.fixturenames:
        from app.db import Base, engine, load_all_models

        _refuse_unless_throwaway(engine)
        load_all_models()
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    yield


def _refuse_unless_throwaway(engine) -> None:
    """Never drop tables in a database that isn't a SQLite file under the system temp dir."""
    db = engine.url.database or ""
    temp = Path(tempfile.gettempdir()).resolve()
    if engine.url.get_backend_name() != "sqlite" or not db or not Path(db).resolve().is_relative_to(temp):
        raise RuntimeError(
            f"Refusing to reset {engine.url!r}: tests only reset throwaway SQLite files under {temp}. "
            "Something bound the app to a real database before the tests' settings applied."
        )


# ---------------------------------------------------------------- shared API fixtures

@pytest.fixture
def client():
    """A TestClient for API tests; test modules may define their own."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_clerk(monkeypatch):
    """AUTH_PROVIDER=clerk with a test signing key and a fake Backend API (see tests/test_auth_clerk.py)."""
    import dataclasses

    import httpx

    from app import clerk as clerk_mod
    from app import deps
    from app.clerk import ClerkAPI, ClerkVerifier
    from app.config import get_settings
    from app.routers import auth as auth_router
    from tests.test_auth_clerk import FakeClerk
    from tests.test_clerk_verify import ISS, PUBLIC_PEM, WEB

    settings = dataclasses.replace(get_settings(), auth_provider="clerk", clerk_frontend_api_url=ISS,
                                   clerk_authorized_parties=[WEB], clerk_secret_key="sk_test_fake")
    for mod in (deps, auth_router):
        monkeypatch.setattr(mod, "get_settings", lambda: settings)
    monkeypatch.setattr(clerk_mod, "get_verifier", lambda: ClerkVerifier(ISS, [WEB], pem=PUBLIC_PEM))
    fake = FakeClerk()
    clerk_mod.set_api(ClerkAPI("sk_test_fake", "https://api.clerk.test/v1", transport=httpx.MockTransport(fake.handler)))
    yield fake
    clerk_mod.set_api(None)
