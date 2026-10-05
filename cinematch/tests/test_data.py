import sqlite3
import pytest
from recommender.data_prep import summary
import config


def test_counts(tables):
    m, r, _ = tables
    s = summary(m, r)
    assert (s["movies"], s["ratings"], s["users"]) == (9742, 100836, 610)
    assert round(s["sparsity_pct"], 1) == 98.3


def test_cleaning(tables):
    m, r, _ = tables
    assert r["rating"].between(0.5, 5).all()
    assert not r.duplicated(["user_id", "movie_id"]).any()
    assert (m["genres"] != "(no genres listed)").all()
    assert r["movie_id"].isin(m["movie_id"]).all()


def test_title_and_year_split(tables):
    m, _, _ = tables
    row = m[m.movie_id == 1].iloc[0]
    assert row["title"] == "Toy Story" and row["year"] == 1995


def test_schema_rejects_bad_rating():
    conn = sqlite3.connect(config.DB_PATH)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO ratings(user_id, movie_id, rating) VALUES (1, 1, 9.0)")
    conn.close()
