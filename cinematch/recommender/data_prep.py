"""Stage 2: load, inspect and clean MovieLens data from SQLite."""
import pandas as pd
from backend.database import get_conn


def load_tables():
    with get_conn() as conn:
        movies = pd.read_sql("SELECT * FROM movies", conn)
        ratings = pd.read_sql("SELECT * FROM ratings", conn)
        tags = pd.read_sql("SELECT * FROM tags", conn)
    return movies, ratings, tags


def clean(movies: pd.DataFrame, ratings: pd.DataFrame):
    movies = movies.drop_duplicates("movie_id").copy()
    ratings = ratings.drop_duplicates(["user_id", "movie_id"]).dropna(subset=["rating"])
    ratings = ratings[ratings["rating"].between(0.5, 5.0)]
    movies["genres"] = movies["genres"].replace("(no genres listed)", "").fillna("")
    movies["genre_list"] = movies["genres"].apply(lambda g: g.split("|") if g else [])
    ratings = ratings[ratings["movie_id"].isin(movies["movie_id"])]
    return movies.reset_index(drop=True), ratings.reset_index(drop=True)


def summary(movies: pd.DataFrame, ratings: pd.DataFrame) -> dict:
    n_u, n_m = ratings["user_id"].nunique(), ratings["movie_id"].nunique()
    per_user = ratings.groupby("user_id").size()
    per_movie = ratings.groupby("movie_id").size()
    return {
        "movies": len(movies), "ratings": len(ratings), "users": n_u, "rated_movies": n_m,
        "sparsity_pct": round(100 * (1 - len(ratings) / (n_u * n_m)), 2),
        "mean_rating": round(ratings["rating"].mean(), 3),
        "min_ratings_per_user": int(per_user.min()),
        "median_ratings_per_movie": float(per_movie.median()),
        "movies_with_one_rating": int((per_movie == 1).sum()),
        "movies_no_genre": int((movies["genres"] == "").sum()),
        "movies_no_year": int(movies["year"].isna().sum()),
    }


if __name__ == "__main__":
    m, r, _ = load_tables()
    m, r = clean(m, r)
    for k, v in summary(m, r).items():
        print(f"{k:28s} {v}")
