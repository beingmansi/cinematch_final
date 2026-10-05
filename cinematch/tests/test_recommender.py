import numpy as np


def titles(rec, items):
    return [rec.movies.set_index("movie_id").at[i["movie_id"], "title"] for i in items]


def test_similar_movies_are_sensible(rec):
    t = titles(rec, rec.similar(1, 5))          # Toy Story
    assert "Toy Story 2" in t and "Toy Story 3" in t
    t = titles(rec, rec.similar(2571, 5))       # The Matrix
    assert "Matrix Reloaded, The" in t


def test_recommend_excludes_rated_and_is_sorted(rec, tables):
    _, r, _ = tables
    ur = r[r.user_id == 5].set_index("movie_id")["rating"].to_dict()
    for mode in ["hybrid", "content", "cf", "popular"]:
        items = rec.recommend(ur, 10, mode)
        ids = [i["movie_id"] for i in items]
        assert len(ids) == 10 and len(set(ids)) == 10
        assert not set(ids) & set(ur)
        assert all(0.5 <= i["predicted_rating"] <= 5.0 for i in items)
        scores = [i["score"] for i in items]
        assert scores == sorted(scores, reverse=True)


def test_cold_start_returns_popular(rec):
    items = rec.recommend({}, 5)
    assert len(items) == 5
    assert "Shawshank Redemption, The" in titles(rec, items)


def test_new_user_with_few_ratings_gets_personal_recs(rec):
    kids = rec.recommend({1: 5.0, 3114: 5.0, 4886: 4.5}, 10)           # Toy Story, Toy Story 2, Monsters Inc
    assert any("Animation" in rec.movies.set_index("movie_id").at[i["movie_id"], "genres"] for i in kids)
    assert kids != rec.recommend({}, 10)


def test_genre_filter(rec):
    items = rec.recommend({1: 5.0}, 8, genre="Horror")
    assert items and all("Horror" in rec.movies.set_index("movie_id").at[i["movie_id"], "genres"] for i in items)


def test_min_ratings_filter(rec):
    for i in rec.recommend({1: 5.0}, 30):
        assert rec.item_count[rec.idx[i["movie_id"]]] >= rec.p["min_ratings"]


def test_predict_rating_in_range(rec):
    p = rec.predict_rating({1: 5.0, 2: 3.0}, 296)
    assert 0.5 <= p <= 5.0


def test_explanations(rec):
    why = rec.explain({1: 5.0, 3114: 5.0}, 4886)
    assert why and all(isinstance(w, str) for w in why)


def test_neighbour_matrix_properties(rec):
    S = rec.S
    assert S.shape == (len(rec.ids), len(rec.ids))
    assert S.diagonal().sum() == 0 and S.min() >= 0 and S.max() <= 1.0 + 1e-6
    assert np.diff(S.indptr).max() <= rec.p["k_neighbors"]


def test_multi_genre_filters(rec):
    items = rec.recommend({1: 5.0}, 15, genres=["Sci-Fi", "Thriller"], match="all")
    assert items and all({"Sci-Fi", "Thriller"} <= rec.genre_sets[rec.idx[i["movie_id"]]] for i in items)
    items = rec.recommend({1: 5.0}, 15, genres=["Western", "Horror"], match="any")
    assert all({"Western", "Horror"} & rec.genre_sets[rec.idx[i["movie_id"]]] for i in items)
    assert rec.recommend({1: 5.0}, 5, genres=["NoSuchGenre"]) == []
