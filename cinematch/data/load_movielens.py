"""Load MovieLens (ml-latest-small) into SQLite. Recreates the database from scratch.

Run from the project root:   python -m data.load_movielens
If data/ml-latest-small is missing the script tries to download it.
An alternative folder can be passed:   python -m data.load_movielens path/to/folder
"""
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

from config import DATA_DIR, MOVIELENS_DIR, MOVIELENS_URL
from backend.database import get_conn, reset_db


def download():
    print("Downloading MovieLens ml-latest-small ...")
    r = requests.get(MOVIELENS_URL, timeout=60)
    r.raise_for_status()
    zipfile.ZipFile(io.BytesIO(r.content)).extractall(DATA_DIR)


def load(folder: Path):
    folder = Path(folder)
    movies = pd.read_csv(folder / "movies.csv")
    ratings = pd.read_csv(folder / "ratings.csv")

    # "Toy Story (1995)" -> title "Toy Story", year 1995
    ext = movies["title"].str.extract(r"^(.*?)\s*\((\d{4})\)\s*$")
    movies["year"] = pd.to_numeric(ext[1], errors="coerce").astype("Int64")
    movies["title"] = ext[0].fillna(movies["title"])
    movies["genres"] = movies["genres"].replace("(no genres listed)", "")
    movies = movies.rename(columns={"movieId": "movie_id"})[["movie_id", "title", "year", "genres"]]
    movies = movies.drop_duplicates("movie_id")

    ratings = ratings.rename(columns={"userId": "user_id", "movieId": "movie_id", "timestamp": "ts"})
    ratings = ratings.drop_duplicates(["user_id", "movie_id"])
    ratings = ratings[ratings["rating"].between(0.5, 5.0) & ratings["movie_id"].isin(movies["movie_id"])]

    users = pd.DataFrame({"user_id": sorted(ratings["user_id"].unique())})
    users["username"] = "ml_user_" + users["user_id"].astype(str)

    reset_db()
    with get_conn() as conn:
        movies.to_sql("movies", conn, if_exists="append", index=False)
        users.to_sql("users", conn, if_exists="append", index=False)
        ratings.to_sql("ratings", conn, if_exists="append", index=False)
        if (folder / "links.csv").exists():
            links = pd.read_csv(folder / "links.csv", dtype={"imdbId": str})
            links = links.rename(columns={"movieId": "movie_id", "imdbId": "imdb_id", "tmdbId": "tmdb_id"})
            links["tmdb_id"] = links["tmdb_id"].astype("Int64")
            links.to_sql("links", conn, if_exists="append", index=False)
        if (folder / "tags.csv").exists():
            tags = pd.read_csv(folder / "tags.csv").rename(columns={"userId": "user_id", "movieId": "movie_id"})
            tags[["user_id", "movie_id", "tag"]].dropna().to_sql("tags", conn, if_exists="append", index=False)
    print(f"Loaded {len(movies)} movies, {len(users)} users and {len(ratings)} ratings.")
    return len(movies), len(users), len(ratings)


def main(folder=None):
    folder = Path(folder) if folder else MOVIELENS_DIR
    if not (folder / "movies.csv").exists():
        download()
    return load(folder)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
