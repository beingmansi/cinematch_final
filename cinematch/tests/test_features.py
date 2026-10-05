"""Tests for: watchlist, multi-genre browsing, account settings, TMDB-powered endpoints."""


def new_user(client, name):
    return client.post("/users", json={"username": name}).json()["user_id"]


def test_watchlist_flow(client):
    uid = new_user(client, "wl_user")
    assert client.get(f"/users/{uid}/watchlist/ids").json() == []
    assert client.post("/watchlist", json={"user_id": uid, "movie_id": 1}).status_code == 200
    assert client.post("/watchlist", json={"user_id": uid, "movie_id": 1}).status_code == 200    # idempotent
    client.post("/watchlist", json={"user_id": uid, "movie_id": 296})
    ids = client.get(f"/users/{uid}/watchlist/ids").json()
    assert sorted(ids) == [1, 296]
    wl = client.get(f"/users/{uid}/watchlist").json()
    assert wl["total"] == 2 and all(m["in_watchlist"] for m in wl["items"])
    assert client.get("/movies/1", params={"user_id": uid}).json()["in_watchlist"] is True
    assert client.get("/movies/2", params={"user_id": uid}).json()["in_watchlist"] is False
    client.delete(f"/watchlist/{uid}/1")
    assert client.get(f"/users/{uid}/watchlist/ids").json() == [296]
    assert client.post("/watchlist", json={"user_id": uid, "movie_id": 99999999}).status_code == 404
    assert client.post("/watchlist", json={"user_id": 99999999, "movie_id": 1}).status_code == 404


def test_multi_genre_browsing_shows_50_plus(client):
    r = client.get("/movies", params={"genres": "Animation,Children", "match": "all", "limit": 60}).json()
    assert r["total"] > 60 and len(r["items"]) == 60
    assert all({"Animation", "Children"} <= set(m["genres"]) for m in r["items"])
    any_ = client.get("/movies", params={"genres": "Western,Film-Noir", "match": "any", "limit": 100}).json()
    assert any_["total"] > 100 and all({"Western", "Film-Noir"} & set(m["genres"]) for m in any_["items"])
    assert any_["total"] > client.get("/movies", params={"genres": "Western", "limit": 1}).json()["total"]
    assert client.get("/movies", params={"genres": "Nonexistent"}).json()["total"] == 0
    # paging with offset gives different movies
    p1 = client.get("/movies", params={"genres": "Drama", "limit": 60}).json()["items"]
    p2 = client.get("/movies", params={"genres": "Drama", "limit": 60, "offset": 60}).json()["items"]
    assert not {m["movie_id"] for m in p1} & {m["movie_id"] for m in p2}
    assert client.get("/movies", params={"match": "some"}).status_code == 422


def test_recommend_with_multiple_genres(client):
    items = client.get("/recommend/1", params={"genres": "Sci-Fi,Thriller", "match": "all", "n": 20}).json()["items"]
    assert items and all({"Sci-Fi", "Thriller"} <= set(m["genres"]) for m in items)
    items = client.get("/popular", params={"genres": "Horror,Comedy", "match": "any", "n": 50}).json()
    assert len(items) == 50


def test_account_settings_and_protection(client):
    uid = new_user(client, "settings_user")
    client.post("/ratings", json={"user_id": uid, "movie_id": 1, "rating": 4})
    client.post("/watchlist", json={"user_id": uid, "movie_id": 2})
    client.post("/reviews", json={"user_id": uid, "movie_id": 1, "text": "hello"})
    info = client.get(f"/users/{uid}").json()
    assert (info["n_ratings"], info["n_watchlist"], info["n_reviews"], info["is_sample"]) == (1, 1, 1, False)
    assert client.delete(f"/users/{uid}/ratings").json()["ratings_removed"] == 1
    assert client.delete(f"/users/{uid}/watchlist").json()["removed"] == 1
    assert client.delete(f"/users/{uid}").status_code == 200
    assert client.get(f"/users/{uid}").status_code == 404
    assert client.get("/movies/1/reviews").json() == [] or all(r["username"] != "settings_user" for r in client.get("/movies/1/reviews").json())
    # MovieLens sample accounts cannot be wiped by anybody who types their name
    for path in ("/users/1/ratings", "/users/1/watchlist", "/users/1"):
        assert client.delete(path).status_code == 403
    assert client.get("/users/1").json()["is_sample"] is True


def test_posters_in_listings_with_tmdb(client, tmdb_on):
    items = client.get("/movies", params={"genres": "Comedy", "limit": 20}).json()["items"]
    assert all(m["poster_url"] and m["poster_url"].startswith("http://img.test/w342/poster") for m in items)
    assert all(m["overview"] for m in items)


def test_tmdb_reviews_endpoint(client, tmdb_on):
    r = client.get("/movies/1/tmdb-reviews").json()
    assert [x["author"] for x in r] == ["film_fan", "grumpy"]


def test_tmdb_endpoints_without_key_are_polite(client, monkeypatch):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    r = client.get("/tmdb/search", params={"q": "inception"})
    assert r.status_code == 503 and "TMDB_API_KEY" in r.json()["detail"]
    assert client.post("/tmdb/add", json={"tmdb_id": 7000000}).status_code == 503
    assert client.get("/movies/3/tmdb-reviews").json() == []


def test_add_movie_from_tmdb_end_to_end(client, tmdb_on):
    hits = client.get("/tmdb/search", params={"q": "brand new"}).json()
    assert hits[0]["title"] == "Brand New Film" and hits[0]["tmdb_id"] == 900001
    res = client.post("/tmdb/add", json={"tmdb_id": 900001}).json()
    mid = res["movie_id"]
    assert res["already_existed"] is False and mid == 1_900_001
    # the new movie is now a normal citizen of the catalogue
    d = client.get(f"/movies/{mid}").json()
    assert d["title"] == "Fake Movie 900001" and d["year"] == 2024 and d["n_ratings"] == 0
    assert "Sci-Fi" in d["genres"] and d["poster_url"].endswith("poster900001.jpg")
    found = client.get("/movies", params={"q": "Fake Movie 900001"}).json()
    assert found["total"] == 1
    assert any(m["movie_id"] == mid for m in client.get("/movies", params={"genres": "Sci-Fi", "sort": "year", "limit": 100}).json()["items"])
    uid = new_user(client, "adder")
    assert client.post("/ratings", json={"user_id": uid, "movie_id": mid, "rating": 4.5}).status_code == 200
    assert client.get(f"/movies/{mid}/similar").status_code == 200
    # adding it again is harmless
    assert client.post("/tmdb/add", json={"tmdb_id": 900001}).json()["already_existed"] is True
    # an already-known MovieLens film is recognised instead of duplicated
    assert client.post("/tmdb/add", json={"tmdb_id": 862}).json() == {"movie_id": 1, "title": "Toy Story", "already_existed": True}


def test_demo_review_seeding(client):
    from data import seed_demo
    assert seed_demo.seed() > 0
    assert seed_demo.seed() == 0                                   # idempotent
    top = client.get("/movies", params={"limit": 1}).json()["items"][0]["movie_id"]
    revs = client.get(f"/movies/{top}/reviews").json()
    assert revs and all(r["username"].startswith("sample_") and r["text"].startswith("Sample review") for r in revs)
    assert client.get("/health").json()["ratings"] >= 100836        # no ratings were created
    seed_demo.remove()
    assert all(not r["username"].startswith("sample_") for r in client.get(f"/movies/{top}/reviews").json())


def test_add_movie_feature_can_be_switched_off(client, tmdb_on, monkeypatch):
    monkeypatch.setenv("CINEMATCH_ENABLE_ADD", "0")
    assert client.get("/health").json()["add_movie_enabled"] is False
    assert client.get("/tmdb/search", params={"q": "toy"}).status_code == 403
    assert client.post("/tmdb/add", json={"tmdb_id": 900001}).status_code == 403
    monkeypatch.setenv("CINEMATCH_ENABLE_ADD", "1")
    assert client.get("/tmdb/search", params={"q": "toy"}).status_code == 200
