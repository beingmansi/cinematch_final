import os
import tempfile
from pathlib import Path

# Use a throw-away database so tests never touch the real data/cinematch.db
_tmp = tempfile.mkdtemp()
os.environ["CINEMATCH_DB"] = str(Path(_tmp) / "test.db")
os.environ.pop("TMDB_API_KEY", None)
os.environ["CINEMATCH_ENABLE_ADD"] = "1"      # the add-movie feature is off by default; tests exercise it

import pytest  # noqa: E402

from data.load_movielens import main as load_data  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def loaded_db():
    return load_data()


@pytest.fixture(scope="session", autouse=True)
def tables(loaded_db):   # autouse: snapshot the pristine data before API tests add users/ratings
    from recommender.data_prep import clean, load_tables
    m, r, t = load_tables()
    m, r = clean(m, r)
    return m, r, t


@pytest.fixture(scope="session", autouse=True)
def rec(tables):
    from recommender.hybrid import Recommender
    m, r, t = tables
    return Recommender(m, r, t)


@pytest.fixture(scope="session")
def client(loaded_db):
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def fake_tmdb_server():
    from tests import fake_tmdb
    server, base = fake_tmdb.start()
    yield base
    server.shutdown()


@pytest.fixture
def tmdb_on(monkeypatch, fake_tmdb_server):
    """Point the app at the fake TMDB server with a valid key."""
    from tests import fake_tmdb
    monkeypatch.setenv("TMDB_API_BASE", fake_tmdb_server)
    monkeypatch.setenv("TMDB_IMAGE_BASE", "http://img.test/w342")
    monkeypatch.setenv("TMDB_API_KEY", fake_tmdb.GOOD_KEY)
    from backend import tmdb
    tmdb._cooldown_until = 0
    from backend.database import get_conn
    with get_conn() as c:
        c.execute("DELETE FROM poster_cache"); c.execute("DELETE FROM tmdb_reviews"); c.execute("DELETE FROM review_fetch")
    fake_tmdb.REQUESTS.clear()
    return fake_tmdb
