"""Content-based model: TF-IDF over genres, decade, title words and user tags."""
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

STOP = {"the", "and", "of", "a", "an", "in", "to", "for", "on", "at", "la", "le", "de", "part", "movie", "film"}


def movie_tokens(row, tags: list[str], use_title=True, use_tags=True) -> list[str]:
    toks = ["g_" + g.lower() for g in row["genres"].split("|") if g]
    if row["year"] == row["year"] and row["year"] is not None:  # not NaN
        toks.append(f"dec_{int(row['year']) // 10 * 10}")
    if use_title:
        toks += ["t_" + w for w in re.findall(r"[a-z0-9]+", row["title"].lower()) if len(w) > 2 and w not in STOP]
    if use_tags and tags:
        toks += ["tag_" + t for t in tags]
    return toks


class ContentModel:
    def __init__(self, movies, tags_df=None, use_title=True, use_tags=True):
        tag_map = {}
        if tags_df is not None and len(tags_df):
            for mid, grp in tags_df.groupby("movie_id"):
                words = set()
                for t in grp["tag"].astype(str):
                    words.update(w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2 and w not in STOP)
                tag_map[mid] = sorted(words)
        docs = [movie_tokens(r, tag_map.get(r["movie_id"], []), use_title, use_tags) for _, r in movies.iterrows()]
        self.vectorizer = TfidfVectorizer(analyzer=lambda d: d, sublinear_tf=True)
        self.X = self.vectorizer.fit_transform(docs).tocsr().astype(np.float32)   # rows are L2-normalised

    def similar_scores(self, item_idx: int) -> np.ndarray:
        """Cosine similarity of one movie to all movies."""
        return np.asarray((self.X @ self.X[item_idx].T).todense()).ravel()

    def deviation(self, rated_idx, residuals, lam: float) -> np.ndarray:
        """Similarity-weighted average residual of the user's rated movies, for every movie."""
        n = self.X.shape[0]
        c = np.zeros(n, np.float32); c[rated_idx] = residuals
        m = np.zeros(n, np.float32); m[rated_idx] = 1.0
        num = self.X @ (self.X.T @ c)
        den = self.X @ (self.X.T @ m)
        return num / (den + lam)
