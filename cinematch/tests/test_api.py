import pytest


def test_health(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["movies"] == 9742 and h["ratings"] >= 100836


def test_user_signup_and_login(client):
    a = client.post("/users", json={"username": "alice_01"}).json()
    b = client.post("/users", json={"username": "alice_01"}).json()
    assert a["created"] is True and b["created"] is False and a["user_id"] == b["user_id"] > 610
    assert client.post("/users", json={"username": "x"}).status_code == 422
    assert client.post("/users", json={"username": "bad name!"}).status_code == 422
    assert client.get("/users/999999").status_code == 404


def test_rating_flow_updates_recommendations(client):
    uid = client.post("/users", json={"username": "bob_flow"}).json()["user_id"]
    cold = client.get(f"/recommend/{uid}").json()
    assert cold["cold_start"] and len(cold["items"]) == 10
    for mid, rt in [(1, 5), (3114, 5), (4886, 4.5), (78499, 5)]:
        assert client.post("/ratings", json={"user_id": uid, "movie_id": mid, "rating": rt}).status_code == 200
    warm = client.get(f"/recommend/{uid}").json()
    assert not warm["cold_start"] and warm["n_user_ratings"] == 4
    ids = {i["movie_id"] for i in warm["items"]}
    assert not ids & {1, 3114, 4886, 78499}
    assert ids != {i["movie_id"] for i in cold["items"]}
    # upsert: re-rating changes the value, not the count
    client.post("/ratings", json={"user_id": uid, "movie_id": 1, "rating": 2.0})
    body = client.get(f"/users/{uid}/ratings").json()
    assert body["total"] == 4 and {r["movie_id"]: r["rating"] for r in body["items"]}[1] == 2.0


@pytest.mark.parametrize("bad", [0, 0.3, 5.5, -1, "abc"])
def test_rating_validation(client, bad):
    uid = client.post("/users", json={"username": "carol_val"}).json()["user_id"]
    assert client.post("/ratings", json={"user_id": uid, "movie_id": 1, "rating": bad}).status_code == 422


def test_rating_unknown_movie_or_user(client):
    uid = client.post("/users", json={"username": "dave_404"}).json()["user_id"]
    assert client.post("/ratings", json={"user_id": uid, "movie_id": 99999999, "rating": 3}).status_code == 404
    assert client.post("/ratings", json={"user_id": 99999999, "movie_id": 1, "rating": 3}).status_code == 404


def test_reviews(client):
    uid = client.post("/users", json={"username": "erin_rev"}).json()["user_id"]
    txt = "<script>alert(1)</script> Great movie'; DROP TABLE reviews;--"
    assert client.post("/reviews", json={"user_id": uid, "movie_id": 1, "text": txt}).status_code == 200
    got = client.get("/movies/1/reviews").json()
    assert got[0]["text"] == txt and got[0]["username"] == "erin_rev"     # stored verbatim, table still alive
    assert client.post("/reviews", json={"user_id": uid, "movie_id": 1, "text": "   "}).status_code == 422
    assert client.post("/reviews", json={"user_id": uid, "movie_id": 1, "text": "x" * 2001}).status_code == 422


def test_search_and_filters(client):
    r = client.get("/movies", params={"q": "matrix", "limit": 5}).json()
    assert r["total"] >= 3 and any(m["title"] == "Matrix, The" for m in r["items"])
    r = client.get("/movies", params={"genre": "Horror", "year_min": 1990, "year_max": 1999, "sort": "year"}).json()
    assert r["total"] > 0 and all(1990 <= m["year"] <= 1999 and "Horror" in m["genres"] for m in r["items"])
    assert client.get("/movies", params={"q": "'; DROP TABLE movies;--"}).json()["total"] == 0
    assert client.get("/movies", params={"sort": "bogus"}).status_code == 422
    assert client.get("/movies", params={"limit": 1000}).status_code == 422


def test_movie_detail_similar_popular_genres(client):
    d = client.get("/movies/1").json()
    assert d["title"] == "Toy Story" and d["n_ratings"] >= 215 and 3.8 < d["avg_rating"] < 4.1
    assert client.get("/movies/99999999").status_code == 404
    sims = client.get("/movies/1/similar", params={"n": 5}).json()
    assert len(sims) == 5 and "movie_id" in sims[0] and sims[0]["movie_id"] != 1
    assert len(client.get("/popular", params={"n": 6, "genre": "Comedy"}).json()) == 6
    assert "Drama" in client.get("/genres").json()


def test_recommend_modes_and_params(client):
    for mode in ["hybrid", "content", "cf", "popular"]:
        r = client.get("/recommend/1", params={"mode": mode, "n": 5}).json()
        assert len(r["items"]) == 5
    assert client.get("/recommend/1", params={"mode": "nope"}).status_code == 422
    assert client.get("/recommend/1", params={"alpha": 2}).status_code == 422
    assert client.get("/recommend/999999").status_code == 404
    first = client.get("/recommend/1").json()["items"][0]
    assert first["because_you_liked"] and first["predicted_rating"] >= 0.5


def test_retrain_and_evaluation_endpoint(client):
    assert client.post("/admin/retrain").json()["status"] == "retrained"
    ev = client.get("/evaluation")
    assert ev.status_code in (200, 404)
