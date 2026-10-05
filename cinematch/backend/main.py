"""CineMatch FastAPI backend."""
import json
import sqlite3
from contextlib import asynccontextmanager

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query

import config
from backend import tmdb
from backend.database import get_conn, init_db
from backend.schemas import RatingIn, ReviewIn, TmdbAddIn, UserIn, WatchIn
from backend.service import service


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    service.train()
    yield


app = FastAPI(title="CineMatch API", version="2.0", lifespan=lifespan)


# ---------------- helpers ----------------
def need_model():
    if service.rec is None:
        raise HTTPException(503, "No data loaded. Run: python -m data.load_movielens, then restart the API.")
    return service.rec


def user_exists(conn, user_id: int):
    row = conn.execute("SELECT user_id, username FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"User {user_id} not found")
    return row


def not_sample_account(row):
    if row["username"].startswith("ml_user_"):
        raise HTTPException(403, "Sample MovieLens accounts are read-only. Create your own username to use this.")


def movie_row(movie_id: int):
    rec = need_model()
    i = rec.idx.get(movie_id)
    if i is None:
        raise HTTPException(404, f"Movie {movie_id} not found")
    return rec.movies.iloc[i]


def user_ratings(conn, user_id: int) -> dict:
    return {r["movie_id"]: r["rating"] for r in
            conn.execute("SELECT movie_id, rating FROM ratings WHERE user_id=?", (user_id,))}


def split_genres(genres: str | None) -> list[str]:
    return [g.strip() for g in (genres or "").split(",") if g.strip()]


def movie_cards(conn, ids: list[int], user_id: int | None = None, with_posters=True) -> dict[int, dict]:
    """JSON for a list of movies: title/year/genres + live rating stats (+ user's rating, watchlist flag, poster)."""
    rec = need_model()
    ids = [int(i) for i in ids]
    if not ids:
        return {}
    ph = ",".join("?" * len(ids))
    stats = {r["movie_id"]: (r["a"], r["c"]) for r in conn.execute(
        f"SELECT movie_id, AVG(rating) a, COUNT(*) c FROM ratings WHERE movie_id IN ({ph}) GROUP BY movie_id", ids)}
    mine, watch = {}, set()
    if user_id is not None:
        mine = {r["movie_id"]: r["rating"] for r in conn.execute(
            f"SELECT movie_id, rating FROM ratings WHERE user_id=? AND movie_id IN ({ph})", [user_id, *ids])}
        watch = {r["movie_id"] for r in conn.execute(
            f"SELECT movie_id FROM watchlist WHERE user_id=? AND movie_id IN ({ph})", [user_id, *ids])}
    extra = tmdb.info_for(ids) if with_posters else {}
    out = {}
    for m in ids:
        row = rec.movies.iloc[rec.idx[m]]
        avg, cnt = stats.get(m, (None, 0))
        out[m] = {
            "movie_id": m, "title": row["title"],
            "year": None if pd.isna(row["year"]) else int(row["year"]),
            "genres": row["genre_list"],
            "avg_rating": None if avg is None else round(avg, 2), "n_ratings": cnt,
            "user_rating": mine.get(m), "in_watchlist": m in watch,
            "poster_url": extra.get(m, {}).get("poster_url"),
            "overview": extra.get(m, {}).get("overview"),
        }
    return out


# ---------------- system ----------------
@app.get("/health")
def health():
    with get_conn() as conn:
        n_movies = conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        n_ratings = conn.execute("SELECT COUNT(*) FROM ratings").fetchone()[0]
        n_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {"status": "ok" if service.rec is not None else "no_data", "movies": n_movies, "ratings": n_ratings,
            "users": n_users, "model_trained_at": service.trained_at, "tmdb_enabled": tmdb.enabled(),
            "add_movie_enabled": config.add_movie_enabled()}


@app.post("/admin/retrain")
def retrain():
    """Rebuild the recommender so ratings/movies added through the app are included in the models."""
    if not service.train():
        raise HTTPException(503, "No data loaded")
    return {"status": "retrained", "at": service.trained_at}


@app.get("/evaluation")
def evaluation():
    if not config.EVAL_PATH.exists():
        raise HTTPException(404, "No evaluation results yet. Run: python -m recommender.evaluate")
    return json.loads(config.EVAL_PATH.read_text())


# ---------------- users ----------------
@app.post("/users")
def login_or_register(body: UserIn):
    """Simple username sign-in (no password - this is a demo app). Creates the user if new."""
    with get_conn() as conn:
        row = conn.execute("SELECT user_id, username FROM users WHERE username=?", (body.username,)).fetchone()
        created = False
        if not row:
            try:
                cur = conn.execute("INSERT INTO users(username) VALUES (?)", (body.username,))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Username already taken")
            row = {"user_id": cur.lastrowid, "username": body.username}
            created = True
        n = conn.execute("SELECT COUNT(*) FROM ratings WHERE user_id=?", (row["user_id"],)).fetchone()[0]
        w = conn.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=?", (row["user_id"],)).fetchone()[0]
    return {"user_id": row["user_id"], "username": row["username"], "n_ratings": n, "n_watchlist": w, "created": created}


@app.get("/users/{user_id}")
def get_user(user_id: int):
    with get_conn() as conn:
        row = user_exists(conn, user_id)
        n = conn.execute("SELECT COUNT(*) FROM ratings WHERE user_id=?", (user_id,)).fetchone()[0]
        w = conn.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=?", (user_id,)).fetchone()[0]
        r = conn.execute("SELECT COUNT(*) FROM reviews WHERE user_id=?", (user_id,)).fetchone()[0]
    return {"user_id": row["user_id"], "username": row["username"], "n_ratings": n, "n_watchlist": w,
            "n_reviews": r, "is_sample": row["username"].startswith("ml_user_")}


@app.get("/users/{user_id}/ratings")
def get_user_ratings(user_id: int, limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0)):
    need_model()
    with get_conn() as conn:
        user_exists(conn, user_id)
        total = conn.execute("SELECT COUNT(*) FROM ratings WHERE user_id=?", (user_id,)).fetchone()[0]
        rows = conn.execute("SELECT movie_id, rating, ts FROM ratings WHERE user_id=? ORDER BY ts DESC, movie_id "
                            "LIMIT ? OFFSET ?", (user_id, limit, offset)).fetchall()
        dist = {r["rating"]: r["c"] for r in conn.execute(
            "SELECT rating, COUNT(*) c FROM ratings WHERE user_id=? GROUP BY rating", (user_id,))}
        avg = conn.execute("SELECT AVG(rating) FROM ratings WHERE user_id=?", (user_id,)).fetchone()[0]
        cards = movie_cards(conn, [r["movie_id"] for r in rows], user_id)
    return {"total": total, "average": None if avg is None else round(avg, 2), "distribution": dist,
            "items": [{**cards[r["movie_id"]], "rating": r["rating"], "ts": r["ts"]} for r in rows]}


@app.delete("/users/{user_id}/ratings")
def clear_ratings(user_id: int):
    with get_conn() as conn:
        not_sample_account(user_exists(conn, user_id))
        n = conn.execute("DELETE FROM ratings WHERE user_id=?", (user_id,)).rowcount
    return {"status": "deleted", "ratings_removed": n}


@app.delete("/users/{user_id}")
def delete_account(user_id: int):
    """Delete a user and everything they created (ratings, reviews, watchlist)."""
    with get_conn() as conn:
        not_sample_account(user_exists(conn, user_id))
        for t in ("ratings", "reviews", "watchlist"):
            conn.execute(f"DELETE FROM {t} WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    return {"status": "deleted"}


# ---------------- watchlist ----------------
@app.post("/watchlist")
def add_to_watchlist(body: WatchIn):
    movie_row(body.movie_id)
    with get_conn() as conn:
        user_exists(conn, body.user_id)
        conn.execute("INSERT OR IGNORE INTO watchlist(user_id, movie_id) VALUES (?,?)", (body.user_id, body.movie_id))
    return {"status": "added"}


@app.delete("/watchlist/{user_id}/{movie_id}")
def remove_from_watchlist(user_id: int, movie_id: int):
    with get_conn() as conn:
        user_exists(conn, user_id)
        conn.execute("DELETE FROM watchlist WHERE user_id=? AND movie_id=?", (user_id, movie_id))
    return {"status": "removed"}


@app.get("/users/{user_id}/watchlist")
def get_watchlist(user_id: int, limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0)):
    need_model()
    with get_conn() as conn:
        user_exists(conn, user_id)
        total = conn.execute("SELECT COUNT(*) FROM watchlist WHERE user_id=?", (user_id,)).fetchone()[0]
        ids = [r["movie_id"] for r in conn.execute(
            "SELECT movie_id FROM watchlist WHERE user_id=? ORDER BY added DESC, movie_id LIMIT ? OFFSET ?",
            (user_id, limit, offset))]
        cards = movie_cards(conn, ids, user_id)
    return {"total": total, "items": [cards[i] for i in ids]}


@app.get("/users/{user_id}/watchlist/ids")
def get_watchlist_ids(user_id: int):
    with get_conn() as conn:
        user_exists(conn, user_id)
        return [r["movie_id"] for r in conn.execute("SELECT movie_id FROM watchlist WHERE user_id=?", (user_id,))]


@app.delete("/users/{user_id}/watchlist")
def clear_watchlist(user_id: int):
    with get_conn() as conn:
        not_sample_account(user_exists(conn, user_id))
        n = conn.execute("DELETE FROM watchlist WHERE user_id=?", (user_id,)).rowcount
    return {"status": "deleted", "removed": n}


# ---------------- movies ----------------
@app.get("/genres")
def genres():
    return need_model().genre_names


@app.get("/movies")
def search_movies(q: str = "", genre: str | None = None, genres: str | None = Query(None, description="comma separated"),
                  match: str = Query("any", pattern="^(any|all)$"),
                  year_min: int | None = None, year_max: int | None = None,
                  sort: str = Query("popular", pattern="^(popular|rating|title|year)$"),
                  limit: int = Query(12, ge=1, le=120), offset: int = Query(0, ge=0), user_id: int | None = None):
    rec = need_model()
    df = rec.movies.copy()
    df["n"] = rec.item_count
    df["bayes"] = rec.bayes_avg
    if q.strip():
        df = df[df["title"].str.contains(q.strip(), case=False, regex=False)]
    gm = rec.genre_filter(genre, split_genres(genres), match)
    if gm is not None:
        df = df[gm[df.index.to_numpy()]]
    if year_min is not None:
        df = df[df["year"] >= year_min]
    if year_max is not None:
        df = df[df["year"] <= year_max]
    if sort == "popular":
        df = df.sort_values(["n", "title"], ascending=[False, True])
    elif sort == "rating":
        df = df[df["n"] >= rec.p["min_ratings"]].sort_values("bayes", ascending=False)
    elif sort == "year":
        df = df.sort_values("year", ascending=False)
    else:
        df = df.sort_values("title")
    total = len(df)
    ids = df["movie_id"].iloc[offset: offset + limit].tolist()
    with get_conn() as conn:
        cards = movie_cards(conn, ids, user_id)
    return {"total": total, "items": [cards[i] for i in ids]}


@app.get("/movies/{movie_id}")
def movie_detail(movie_id: int, user_id: int | None = None):
    movie_row(movie_id)
    with get_conn() as conn:
        card = movie_cards(conn, [movie_id], user_id)[movie_id]
        card["n_reviews"] = conn.execute("SELECT COUNT(*) FROM reviews WHERE movie_id=?", (movie_id,)).fetchone()[0]
    return card


@app.get("/movies/{movie_id}/similar")
def similar_movies(movie_id: int, n: int = Query(8, ge=1, le=30), user_id: int | None = None):
    movie_row(movie_id)
    sims = service.rec.similar(movie_id, n)
    with get_conn() as conn:
        cards = movie_cards(conn, [s["movie_id"] for s in sims], user_id)
    return [{**cards[s["movie_id"]], "similarity": round(s["score"], 3)} for s in sims]


@app.get("/popular")
def popular(n: int = Query(12, ge=1, le=100), genre: str | None = None, genres: str | None = None,
            match: str = Query("any", pattern="^(any|all)$"), user_id: int | None = None):
    rec = need_model()
    items = rec.popular(n, genre, genres=split_genres(genres), match=match)
    with get_conn() as conn:
        cards = movie_cards(conn, [i["movie_id"] for i in items], user_id)
    return [cards[i["movie_id"]] for i in items]


# ---------------- ratings & reviews ----------------
@app.post("/ratings")
def rate_movie(body: RatingIn):
    movie_row(body.movie_id)
    with get_conn() as conn:
        user_exists(conn, body.user_id)
        conn.execute("INSERT INTO ratings(user_id, movie_id, rating, ts) VALUES (?,?,?,strftime('%s','now')) "
                     "ON CONFLICT(user_id, movie_id) DO UPDATE SET rating=excluded.rating, ts=excluded.ts",
                     (body.user_id, body.movie_id, body.rating))
        n = conn.execute("SELECT COUNT(*) FROM ratings WHERE user_id=?", (body.user_id,)).fetchone()[0]
    return {"status": "saved", "n_ratings": n}


@app.post("/reviews")
def post_review(body: ReviewIn):
    movie_row(body.movie_id)
    with get_conn() as conn:
        user_exists(conn, body.user_id)
        cur = conn.execute("INSERT INTO reviews(user_id, movie_id, text) VALUES (?,?,?)",
                           (body.user_id, body.movie_id, body.text))
    return {"status": "saved", "review_id": cur.lastrowid}


@app.get("/movies/{movie_id}/reviews")
def movie_reviews(movie_id: int, limit: int = Query(20, ge=1, le=100)):
    """Reviews written by CineMatch users."""
    movie_row(movie_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT r.review_id, r.text, r.created, u.username, "
            "(SELECT rating FROM ratings x WHERE x.user_id=r.user_id AND x.movie_id=r.movie_id) AS rating "
            "FROM reviews r JOIN users u ON u.user_id=r.user_id WHERE r.movie_id=? "
            "ORDER BY r.review_id DESC LIMIT ?", (movie_id, limit)).fetchall()
    return [dict(r) for r in rows]


@app.get("/movies/{movie_id}/tmdb-reviews")
def movie_tmdb_reviews(movie_id: int, limit: int = Query(10, ge=1, le=20)):
    """Reviews written on TMDB (empty list if TMDB is not set up or the movie has none)."""
    movie_row(movie_id)
    return tmdb.reviews_for(movie_id, limit)


# ---------------- TMDB: add movies ----------------
def need_add_feature():
    if not config.add_movie_enabled():
        raise HTTPException(403, "Adding movies is switched off. Set CINEMATCH_ENABLE_ADD=1 to enable it.")


@app.get("/tmdb/search")
def tmdb_search(q: str = Query(min_length=2, max_length=100)):
    need_add_feature()
    try:
        return tmdb.search_movies(q)
    except tmdb.TMDBError as e:
        raise HTTPException(503, str(e))


@app.post("/tmdb/add")
def tmdb_add(body: TmdbAddIn):
    need_add_feature()
    try:
        res = tmdb.add_movie(body.tmdb_id)
    except tmdb.TMDBError as e:
        raise HTTPException(503, str(e))
    if not res["already_existed"]:
        service.train()          # make the new movie visible to search / similar-movies
    return res


# ---------------- recommendations ----------------
@app.get("/recommend/{user_id}")
def recommend(user_id: int, n: int = Query(10, ge=1, le=100),
              mode: str = Query("hybrid", pattern="^(hybrid|content|cf|popular)$"),
              genre: str | None = None, genres: str | None = None,
              match: str = Query("any", pattern="^(any|all)$"),
              alpha: float | None = Query(None, ge=0.0, le=1.0)):
    rec = need_model()
    with get_conn() as conn:
        user_exists(conn, user_id)
        ur = user_ratings(conn, user_id)
        items = rec.recommend(ur, n=n, mode=mode, genre=genre, alpha=alpha, genres=split_genres(genres), match=match)
        cards = movie_cards(conn, [i["movie_id"] for i in items], user_id)
    out = []
    for it in items:
        reason = rec.explain(ur, it["movie_id"]) if ur and mode != "popular" else []
        out.append({**cards[it["movie_id"]], "predicted_rating": round(it["predicted_rating"], 2),
                    "score": round(it["score"], 3), "because_you_liked": reason})
    return {"user_id": user_id, "mode": "popular" if not ur else mode, "n_user_ratings": len(ur),
            "cold_start": not ur, "items": out}
