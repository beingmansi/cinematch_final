import requests
from unittest.mock import patch

from backend import tmdb
from backend.database import get_conn


def test_disabled_without_key_makes_no_network_calls(monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    with get_conn() as c:
        c.execute("DELETE FROM poster_cache"); c.execute("DELETE FROM review_fetch")
    with patch("backend.tmdb.requests.get") as g:
        assert tmdb.info_for([1, 2]) == {}
        assert tmdb.reviews_for(1) == []
        g.assert_not_called()


def test_posters_fetched_once_then_cached(tmdb_on):
    out = tmdb.info_for([1, 2])
    assert out[1]["poster_url"] == "http://img.test/w342/poster862.jpg" and out[1]["overview"] == "Overview of 862."
    n = len(tmdb_on.REQUESTS)
    assert n == 2
    tmdb.info_for([1, 2])
    assert len(tmdb_on.REQUESTS) == n          # cache hit, no new requests


def test_stale_cache_is_refetched(tmdb_on):
    tmdb.info_for([1])
    with get_conn() as c:                       # pretend the cached row is 200 days old (TMDB: max 6 months)
        c.execute("UPDATE poster_cache SET fetched_at = datetime('now', '-200 days') WHERE movie_id=1")
    before = len(tmdb_on.REQUESTS)
    tmdb.info_for([1])
    assert len(tmdb_on.REQUESTS) == before + 1


def test_bearer_token_accepted(monkeypatch, fake_tmdb_server, tmdb_on):
    monkeypatch.setenv("TMDB_API_KEY", "t" * 60)
    with get_conn() as c:
        c.execute("DELETE FROM poster_cache")
    assert tmdb.info_for([1])[1]["poster_url"].endswith("poster862.jpg")


def test_bad_key_gives_clear_error(monkeypatch, tmdb_on):
    monkeypatch.setenv("TMDB_API_KEY", "x" * 32)
    try:
        tmdb.search_movies("toy")
        assert False, "expected TMDBError"
    except tmdb.TMDBError as e:
        assert "rejected" in str(e)


def test_network_failure_does_not_crash_and_is_not_cached(monkeypatch, tmdb_on):
    with patch("backend.tmdb.requests.get", side_effect=requests.ConnectionError()):
        assert tmdb.info_for([1]) == {}
        assert tmdb._cooldown_until > 0
    tmdb._cooldown_until = 0
    with get_conn() as c:
        assert c.execute("SELECT COUNT(*) FROM poster_cache").fetchone()[0] == 0


def test_reviews_fetched_and_cached(tmdb_on):
    r = tmdb.reviews_for(1)                    # Toy Story -> tmdb 862 on the fake server
    assert [x["author"] for x in r] == ["film_fan", "grumpy"] and r[0]["rating"] == 4.5 and r[1]["rating"] is None
    n = len(tmdb_on.REQUESTS)
    tmdb.reviews_for(1)
    assert len(tmdb_on.REQUESTS) == n
    assert tmdb.reviews_for(2) == []           # a movie with no reviews


def test_add_movie_maps_genres_and_is_idempotent(tmdb_on):
    res = tmdb.add_movie(5000001)
    assert res == {"movie_id": 6_000_001, "title": "Fake Movie 5000001", "already_existed": False}
    with get_conn() as c:
        row = c.execute("SELECT title, year, genres FROM movies WHERE movie_id=6000001").fetchone()
    assert (row["title"], row["year"]) == ("Fake Movie 5000001", 2024)
    assert row["genres"] == "Sci-Fi|Thriller|Children"          # History dropped, others mapped to MovieLens names
    assert tmdb.add_movie(5000001)["already_existed"] is True
    assert tmdb.add_movie(862)["already_existed"] is True       # Toy Story already in MovieLens (tmdb 862)
