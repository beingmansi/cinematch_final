"""Smoke-test the Streamlit pages with Streamlit's headless AppTest against a real running backend."""
import os
import threading
import time

import pytest
import requests

PORT = 8765
APP = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.py")


@pytest.fixture(scope="module")
def backend(loaded_db):
    import uvicorn
    os.environ["CINEMATCH_API_URL"] = f"http://127.0.0.1:{PORT}"
    from backend.main import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    server.install_signal_handlers = lambda: None
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    s = requests.Session(); s.trust_env = False
    for _ in range(60):
        try:
            if s.get(f"http://127.0.0.1:{PORT}/health", timeout=1).status_code == 200:
                break
        except requests.RequestException:
            time.sleep(0.5)
    yield
    server.should_exit = True
    t.join(timeout=5)


@pytest.fixture
def app_test(backend, monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    return at


def cards(at, prefix):
    return [b for b in at.button if b.key and b.key.startswith(prefix)]


def test_layout_bottom_nav_and_slim_sidebar(app_test):
    at = app_test
    assert [b.label for b in at.button if b.key and b.key.startswith("nav_")] == [
        "🏠 Home", "🎯 For You", "🔖 Watchlist", "⭐ Ratings", "➕ Add"]
    assert [b.label for b in at.sidebar.button] == ["📊 Model Evaluation", "⚙️ User settings"]
    assert at.text_input(key="home_q").placeholder.startswith("🔍")
    assert len(cards(at, "open_home")) >= 50                 # at least 50 movies visible at once


def test_multi_genre_and_show_more(app_test):
    at = app_test
    at.multiselect(key="home_genres").set_value(["Animation", "Children"]).run()
    at.radio(key="home_match").set_value("All selected").run()
    assert not at.exception and len(cards(at, "open_home")) == 60
    at.button(key="more_home_limit").click().run()
    assert len(cards(at, "open_home")) == 120


def test_full_user_journey(app_test):
    at = app_test
    nav = lambda k: at.button(key=f"nav_{k}").click().run()
    at.text_input(key="login_name").set_value("ui_journey").run()
    at.button(key="btn_login").click().run()
    assert at.session_state["user"]["username"] == "ui_journey"
    # open a movie, rate it, review it, save to watchlist
    cards(at, "open_home")[0].click().run()
    assert not at.exception and at.session_state["page"] == "movie"
    next(b for b in at.button if b.label == "Save rating").click().run()
    at.text_area[0].set_value("Nice one.").run()
    next(b for b in at.button if b.label == "Post review").click().run()
    next(b for b in at.button if b.key == "wl_detail").click().run()
    assert not at.exception and len(at.session_state["wl"]) == 1
    for page in ("watchlist", "ratings", "foryou", "add", "home"):
        nav(page)
        assert not at.exception, page
    nav("ratings")
    assert [m.value for m in at.metric][0] == "1"
    nav("watchlist")
    assert len(cards(at, "open_wl")) == 1
    nav("add")
    assert any("TMDB" in w.value for w in at.warning)          # no key -> friendly instructions
    # sidebar pages, then delete account
    at.sidebar.button[0].click().run()
    assert not at.exception and "recommendations" in at.title[0].value
    at.sidebar.button[1].click().run()
    at.checkbox(key="del_sure").check().run()
    next(b for b in at.button if b.label == "Delete my account").click().run()
    assert at.session_state["user"] is None
