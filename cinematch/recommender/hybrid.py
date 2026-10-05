"""Hybrid recommender = baseline (user mean + item bias) + collaborative and content deviations.

predicted rating = mu_u + b_i + alpha * dev_cf + (1 - alpha) * dev_cb
ranking score    = beta * b_i + gamma * z(log popularity) + alpha * dev_cf + (1 - alpha) * dev_cb
Works for brand-new users because it only needs the user's own list of ratings at request time.
"""
import numpy as np
import pandas as pd

from config import MODEL_PARAMS
from recommender.content_based import ContentModel
from recommender.knn import build_item_knn


class Recommender:
    def __init__(self, movies: pd.DataFrame, ratings: pd.DataFrame, tags: pd.DataFrame | None = None,
                 params: dict | None = None, content_kwargs: dict | None = None):
        self.p = {**MODEL_PARAMS, **(params or {})}
        self.movies = movies.reset_index(drop=True)
        self.ids = self.movies["movie_id"].to_numpy()
        self.idx = {int(m): i for i, m in enumerate(self.ids)}
        n = len(self.ids)

        r = ratings[ratings["movie_id"].isin(self.idx)].copy()
        self.global_mean = float(r["rating"].mean())
        r["i"] = r["movie_id"].map(self.idx)
        K = self.p["user_prior"]
        g = r.groupby("user_id")["rating"].agg(["sum", "count"])
        self.user_mean = ((g["sum"] + K * self.global_mean) / (g["count"] + K)).to_dict()
        r["mu"] = r["user_id"].map(self.user_mean)

        # item statistics and damped item bias
        self.item_count = np.bincount(r["i"], minlength=n).astype(np.int32)
        resid_u = r["rating"] - r["mu"]
        sums = np.bincount(r["i"], weights=resid_u, minlength=n)
        self.item_bias = (sums / (self.item_count + self.p["lam_item"])).astype(np.float32)
        item_sum = np.bincount(r["i"], weights=r["rating"], minlength=n)
        C = 10.0   # Bayesian average used for the "popular" list
        self.bayes_avg = ((item_sum + C * self.global_mean) / (self.item_count + C)).astype(np.float32)
        lp = np.log1p(self.item_count)
        rated = self.item_count >= self.p["min_ratings"]
        self.pop_z = ((lp - lp[rated].mean()) / lp[rated].std()).astype(np.float32)   # standardised log-popularity

        # residual user x item matrix -> item-item neighbours
        uids = {u: j for j, u in enumerate(sorted(self.user_mean))}
        R = np.zeros((len(uids), n), np.float32)
        B = np.zeros((len(uids), n), np.float32)
        ui = r["user_id"].map(uids).to_numpy()
        ii = r["i"].to_numpy()
        R[ui, ii] = (r["rating"] - r["mu"]).to_numpy() - self.item_bias[ii]
        B[ui, ii] = 1.0
        self.S = build_item_knn(R, B, self.p["k_neighbors"], self.p["shrink"])
        del R, B

        self.content = ContentModel(self.movies, tags, **(content_kwargs or {}))
        self.genre_sets = [set(gl) for gl in self.movies["genre_list"]]
        self.genre_names = sorted({g for gs in self.genre_sets for g in gs})
        self.genre_mask = {g: np.array([g in gs for gs in self.genre_sets]) for g in self.genre_names}

    # ---------- user helpers ----------
    def user_profile(self, user_ratings: dict):
        pairs = [(self.idx[int(m)], float(v)) for m, v in user_ratings.items() if int(m) in self.idx]
        if not pairs:
            return np.array([], int), np.array([], np.float32), self.global_mean
        ridx = np.array([p[0] for p in pairs]); vals = np.array([p[1] for p in pairs], np.float32)
        K = self.p["user_prior"]
        mu = (vals.sum() + K * self.global_mean) / (len(vals) + K)
        return ridx, vals, float(mu)

    def deviations(self, ridx, vals, mu):
        """Return (dev_cf, dev_cb) arrays over all movies."""
        n = len(self.ids)
        if len(ridx) == 0:
            z = np.zeros(n, np.float32)
            return z, z
        resid = vals - mu - self.item_bias[ridx]
        c = np.zeros(n, np.float32); c[ridx] = resid
        m = np.zeros(n, np.float32); m[ridx] = 1.0
        dev_cf = (self.S @ c) / ((self.S @ m) + self.p["lam_cf"])
        dev_cb = self.content.deviation(ridx, resid, self.p["lam_cb"])
        return dev_cf.astype(np.float32), dev_cb.astype(np.float32)

    def blend(self, dev_cf, dev_cb, mode="hybrid", alpha=None, beta=None, gamma=None):
        a = self.p["alpha"] if alpha is None else alpha
        b = self.p["beta"] if beta is None else beta
        g = self.p["gamma"] if gamma is None else gamma
        if mode == "content":
            return dev_cb
        if mode == "cf":
            return dev_cf
        return b * self.item_bias + g * self.pop_z + a * dev_cf + (1 - a) * dev_cb

    # ---------- public API ----------
    def predict_rating(self, user_ratings: dict, movie_id: int, alpha=None) -> float:
        ridx, vals, mu = self.user_profile(user_ratings)
        i = self.idx[int(movie_id)]
        cf, cb = self.deviations(ridx, vals, mu)
        a = self.p["alpha"] if alpha is None else alpha
        return float(np.clip(mu + self.item_bias[i] + a * cf[i] + (1 - a) * cb[i], 0.5, 5.0))

    def genre_filter(self, genre=None, genres=None, match="any"):
        """Boolean mask over all movies for one or several genres ('any' = at least one, 'all' = every one)."""
        wanted = [g for g in ([genre] if genre else []) + list(genres or []) if g]
        if not wanted:
            return None
        masks = [self.genre_mask.get(g, np.zeros(len(self.ids), bool)) for g in wanted]
        return np.logical_and.reduce(masks) if match == "all" else np.logical_or.reduce(masks)

    def _candidate_mask(self, exclude_idx, genre=None, genres=None, match="any"):
        mask = self.item_count >= self.p["min_ratings"]
        if len(exclude_idx):
            mask = mask.copy(); mask[exclude_idx] = False
        gm = self.genre_filter(genre, genres, match)
        if gm is not None:
            mask = mask & gm
        return mask

    def _top(self, score, mask, n):
        s = np.where(mask, score, -np.inf)
        n = min(n, int(mask.sum()))
        if n <= 0:
            return np.array([], int)
        top = np.argpartition(-s, n - 1)[:n]
        return top[np.argsort(-s[top])]

    def popular(self, n=10, genre=None, exclude=(), genres=None, match="any"):
        ex = np.array([self.idx[int(m)] for m in exclude if int(m) in self.idx], int)
        mask = self._candidate_mask(ex, genre, genres, match)
        return [{"movie_id": int(self.ids[i]), "score": float(self.bayes_avg[i]),
                 "predicted_rating": float(self.bayes_avg[i])} for i in self._top(self.bayes_avg, mask, n)]

    def recommend(self, user_ratings: dict, n=10, mode="hybrid", genre=None, alpha=None, genres=None, match="any"):
        if mode == "popular" or not user_ratings:
            return self.popular(n, genre, exclude=user_ratings.keys(), genres=genres, match=match)
        ridx, vals, mu = self.user_profile(user_ratings)
        if len(ridx) == 0:
            return self.popular(n, genre, genres=genres, match=match)
        cf, cb = self.deviations(ridx, vals, mu)
        score = self.blend(cf, cb, mode, alpha)
        a = self.p["alpha"] if alpha is None else alpha
        pred = np.clip(mu + self.item_bias + a * cf + (1 - a) * cb, 0.5, 5.0)
        out = []
        for i in self._top(score, self._candidate_mask(ridx, genre, genres, match), n):
            out.append({"movie_id": int(self.ids[i]), "score": float(score[i]), "predicted_rating": float(pred[i])})
        return out

    def explain(self, user_ratings: dict, movie_id: int, k=2):
        """Titles of the user's liked movies that are most similar (in content) to the recommendation."""
        ridx, vals, mu = self.user_profile(user_ratings)
        if len(ridx) == 0:
            return []
        liked = vals >= max(mu, 3.5)
        if not liked.any():
            return []
        li, lv = ridx[liked], vals[liked]
        sims = (self.content.X[li] @ self.content.X[self.idx[int(movie_id)]].T).toarray().ravel()
        order = np.argsort(-(sims + 0.01 * lv))[:k]
        return [self.movies.at[int(li[o]), "title"] for o in order if sims[o] > 0]

    def similar(self, movie_id: int, n=10):
        i = self.idx[int(movie_id)]
        cb = self.content.similar_scores(i)
        cf = np.asarray(self.S[i].todense()).ravel()
        cf_t = np.asarray(self.S[:, i].todense()).ravel()
        score = 0.5 * cb + 0.5 * np.maximum(cf, cf_t)
        # movies nobody has rated yet (e.g. ones added from TMDB) may appear here, judged by content alone
        mask = ((self.item_count >= self.p["min_ratings"]) | (self.item_count == 0)).copy()
        mask[i] = False
        return [{"movie_id": int(self.ids[j]), "score": float(score[j])} for j in self._top(score, mask, n)]
