"""SQLite setup: schema creation and a small connection helper."""
import sqlite3
from contextlib import contextmanager
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    movie_id INTEGER PRIMARY KEY,
    title    TEXT NOT NULL,
    year     INTEGER,
    genres   TEXT
);
CREATE TABLE IF NOT EXISTS users (
    user_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    created  TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS ratings (
    user_id  INTEGER NOT NULL,
    movie_id INTEGER NOT NULL,
    rating   REAL NOT NULL CHECK (rating >= 0.5 AND rating <= 5.0),
    ts       INTEGER,
    PRIMARY KEY (user_id, movie_id)
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    movie_id  INTEGER NOT NULL,
    text      TEXT NOT NULL,
    created   TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS links (
    movie_id INTEGER PRIMARY KEY,
    imdb_id  TEXT,
    tmdb_id  INTEGER
);
CREATE TABLE IF NOT EXISTS tags (
    user_id  INTEGER,
    movie_id INTEGER,
    tag      TEXT
);
CREATE TABLE IF NOT EXISTS poster_cache (
    movie_id   INTEGER PRIMARY KEY,
    poster_url TEXT,
    overview   TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS tmdb_reviews (
    movie_id   INTEGER NOT NULL,
    author     TEXT,
    content    TEXT NOT NULL,
    rating     REAL,
    created    TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS review_fetch (
    movie_id   INTEGER PRIMARY KEY,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS watchlist (
    user_id  INTEGER NOT NULL,
    movie_id INTEGER NOT NULL,
    added    TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, movie_id)
);
CREATE INDEX IF NOT EXISTS idx_ratings_movie ON ratings(movie_id);
CREATE INDEX IF NOT EXISTS idx_reviews_movie ON reviews(movie_id);
CREATE INDEX IF NOT EXISTS idx_tmdb_reviews_movie ON tmdb_reviews(movie_id);
"""

TABLES = ["movies", "users", "ratings", "reviews", "links", "tags", "poster_cache", "tmdb_reviews", "review_fetch", "watchlist"]


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        # older versions had a poster_cache without fetched_at; it is only a cache, so rebuild it
        cols = [r[1] for r in conn.execute("PRAGMA table_info(poster_cache)")]
        if cols and "fetched_at" not in cols:
            conn.execute("DROP TABLE poster_cache")
        conn.executescript(SCHEMA)


def reset_db():
    """Drop everything and recreate empty tables."""
    with get_conn() as conn:
        for t in TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
    init_db()


def db_is_loaded() -> bool:
    try:
        with get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0] > 0
    except sqlite3.Error:
        return False
