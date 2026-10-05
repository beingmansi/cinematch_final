"""TMDB integration (posters, descriptions, reviews, adding movies). Everything is optional:
nothing here talks to the internet unless TMDB_API_KEY is set. Results are cached in SQLite and
re-fetched after 150 days (TMDB's terms do not allow keeping their data longer than 6 months)."""
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from backend.database import get_conn
from config import get_tmdb_key

def api_base() -> str:     # overridable for tests (a fake TMDB server)
    return os.getenv("TMDB_API_BASE", "https://api.themoviedb.org/3")


def img_base() -> str:
    return os.getenv("TMDB_IMAGE_BASE", "https://image.tmdb.org/t/p/w342")


STALE_DAYS = 150
NEW_MOVIE_ID_OFFSET = 1_000_000          # movies added from TMDB get id = offset + tmdb_id (no clash with MovieLens)
_cooldown_until = 0.0                     # after a network failure skip TMDB for a minute so the app stays fast

# TMDB genre names -> MovieLens genre names (so added movies work with the same genre filters)
GENRE_MAP = {"Science Fiction": "Sci-Fi", "Family": "Children", "Music": "Musical"}
KNOWN_GENRES = {"Action", "Adventure", "Animation", "Children", "Comedy", "Crime", "Documentary", "Drama",
                "Fantasy", "Horror", "Musical", "Mystery", "Romance", "Sci-Fi", "Thriller", "War", "Western"}


class TMDBError(Exception):
    pass


def enabled() -> bool:
    return bool(get_tmdb_key())


def _request(path: str, params: dict | None = None):
    """Return (status_code, json) or None if TMDB could not be reached."""
    global _cooldown_until
    key = get_tmdb_key()
    headers, params = {}, dict(params or {})
    if len(key) > 40:                 # v4 "Read Access Token"
        headers["Authorization"] = f"Bearer {key}"
    else:                             # v3 API key
        params["api_key"] = key
    try:
        r = requests.get(f"{api_base()}{path}", headers=headers, params=params, timeout=4)
    except requests.RequestException:
        _cooldown_until = time.time() + 60
        return None
    try:
        return r.status_code, (r.json() if r.content else {})
    except ValueError:
        return r.status_code, {}


def _need_key():
    if not enabled():
        raise TMDBError("TMDB is not set up. Add TMDB_API_KEY to the .env file and restart the app.")


def _call(path, params=None):
    _need_key()
    res = _request(path, params)
    if res is None:
        raise TMDBError("Could not reach TMDB. Check your internet connection and try again.")
    status, data = res
    if status == 401:
        raise TMDBError("TMDB rejected the API key. Check TMDB_API_KEY in your .env file.")
    if status == 404:
        raise TMDBError("TMDB has no such movie.")
    if status != 200:
        raise TMDBError(f"TMDB returned an error (HTTP {status}).")
    return data


def _poster(path):
    return (img_base() + path) if path else None


# ---------------- posters & overviews (cached) ----------------
def _fetch_info(tmdb_id: int):
    res = _request(f"/movie/{tmdb_id}")
    if res is None:
        return None
    status, data = res
    if status == 404:
        return (None, None)
    if status != 200:
        return None
    return (_poster(data.get("poster_path")), data.get("overview") or None)


def info_for(movie_ids: list[int]) -> dict[int, dict]:
    """{movie_id: {"poster_url", "overview"}} from the cache, fetching missing/stale ones if TMDB is enabled."""
    if not movie_ids:
        return {}
    ph = ",".join("?" * len(movie_ids))
    with get_conn() as conn:
        cached = {r["movie_id"]: {"poster_url": r["poster_url"], "overview": r["overview"]} for r in conn.execute(
            f"SELECT * FROM poster_cache WHERE movie_id IN ({ph}) AND fetched_at >= datetime('now', '-{STALE_DAYS} days')",
            movie_ids)}
        missing = [m for m in movie_ids if m not in cached]
        if missing and enabled() and time.time() >= _cooldown_until:
            links = {r["movie_id"]: r["tmdb_id"] for r in conn.execute(
                f"SELECT movie_id, tmdb_id FROM links WHERE movie_id IN ({','.join('?' * len(missing))})", missing)}
            todo = [(m, links[m]) for m in missing if links.get(m)]
            with ThreadPoolExecutor(max_workers=16) as ex:
                results = list(ex.map(lambda t: _fetch_info(t[1]), todo))
            for (m, _), res in zip(todo, results):
                if res is None:
                    continue
                conn.execute("INSERT OR REPLACE INTO poster_cache(movie_id, poster_url, overview, fetched_at) "
                             "VALUES (?,?,?,datetime('now'))", (m, res[0], res[1]))
                cached[m] = {"poster_url": res[0], "overview": res[1]}
    return cached


# ---------------- reviews ----------------
def reviews_for(movie_id: int, limit: int = 10) -> list[dict]:
    """TMDB user reviews for a movie (cached). Returns [] if the movie has none or TMDB is not enabled."""
    with get_conn() as conn:
        fresh = conn.execute("SELECT 1 FROM review_fetch WHERE movie_id=? AND fetched_at >= datetime('now', ?)",
                             (movie_id, f"-{STALE_DAYS} days")).fetchone()
        if not fresh:
            if not enabled():
                return []
            row = conn.execute("SELECT tmdb_id FROM links WHERE movie_id=?", (movie_id,)).fetchone()
            if not row or not row["tmdb_id"]:
                return []
            res = _request(f"/movie/{row['tmdb_id']}/reviews", {"language": "en-US", "page": 1})
            if res is None or res[0] != 200:
                return []
            conn.execute("DELETE FROM tmdb_reviews WHERE movie_id=?", (movie_id,))
            for r in res[1].get("results", [])[:20]:
                rating = (r.get("author_details") or {}).get("rating")
                conn.execute("INSERT INTO tmdb_reviews(movie_id, author, content, rating, created, fetched_at) "
                             "VALUES (?,?,?,?,?,datetime('now'))",
                             (movie_id, r.get("author") or "TMDB user", (r.get("content") or "").strip()[:1500],
                              None if rating is None else float(rating) / 2.0,    # TMDB rates out of 10
                              (r.get("created_at") or "")[:10]))
            conn.execute("INSERT OR REPLACE INTO review_fetch(movie_id, fetched_at) VALUES (?, datetime('now'))",
                         (movie_id,))
        rows = conn.execute("SELECT author, content, rating, created FROM tmdb_reviews WHERE movie_id=? "
                            "AND content != '' LIMIT ?", (movie_id, limit)).fetchall()
    return [dict(r) for r in rows]


# ---------------- search & add ----------------
def search_movies(query: str) -> list[dict]:
    data = _call("/search/movie", {"query": query, "include_adult": "false", "language": "en-US", "page": 1})
    out = []
    for r in data.get("results", [])[:12]:
        out.append({"tmdb_id": r["id"], "title": r.get("title") or "?", "year": (r.get("release_date") or "")[:4] or None,
                    "overview": (r.get("overview") or "")[:300], "poster_url": _poster(r.get("poster_path"))})
    return out


def add_movie(tmdb_id: int) -> dict:
    """Add a TMDB movie to the local catalogue. Returns {"movie_id", "title", "already_existed"}."""
    with get_conn() as conn:
        row = conn.execute("SELECT l.movie_id, m.title FROM links l JOIN movies m USING(movie_id) WHERE l.tmdb_id=?",
                           (tmdb_id,)).fetchone()
        if row:
            return {"movie_id": row["movie_id"], "title": row["title"], "already_existed": True}
    d = _call(f"/movie/{tmdb_id}")
    title = d.get("title") or d.get("original_title")
    if not title:
        raise TMDBError("TMDB returned a movie without a title.")
    genres = []
    for g in d.get("genres", []):
        name = GENRE_MAP.get(g["name"], g["name"])
        if name in KNOWN_GENRES and name not in genres:
            genres.append(name)
    year = int((d.get("release_date") or "0000")[:4]) or None
    movie_id = NEW_MOVIE_ID_OFFSET + int(tmdb_id)
    imdb = (d.get("imdb_id") or "").replace("tt", "") or None
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO movies(movie_id, title, year, genres) VALUES (?,?,?,?)",
                     (movie_id, title, year, "|".join(genres)))
        conn.execute("INSERT OR REPLACE INTO links(movie_id, imdb_id, tmdb_id) VALUES (?,?,?)", (movie_id, imdb, tmdb_id))
        conn.execute("INSERT OR REPLACE INTO poster_cache(movie_id, poster_url, overview, fetched_at) "
                     "VALUES (?,?,?,datetime('now'))", (movie_id, _poster(d.get("poster_path")), d.get("overview") or None))
    return {"movie_id": movie_id, "title": title, "already_existed": False}
