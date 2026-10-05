"""Offline evaluation: RMSE, Precision@K, Recall@K for each model vs. baselines.

Protocol: for every user hold out 20% of ratings (seed 42) as a test set and fit on the rest.
 * RMSE is computed on the held-out ratings.
 * Ranking metrics: a held-out movie rated >= 4.0 is "relevant". Each model ranks the movies the user
   has not rated in training (only movies with >= min_ratings training ratings can be recommended, and
   relevance is counted within that same candidate set). Precision@K = hits/K, Recall@K = hits/#relevant.
Run:  python -m recommender.evaluate          (writes data/eval_results.json)
"""
import json
import sys
import time

import numpy as np
import pandas as pd

from config import EVAL_PATH, MODEL_PARAMS
from recommender.data_prep import clean, load_tables
from recommender.hybrid import Recommender

K = 10
THRESHOLD = 4.0


def split_ratings(ratings: pd.DataFrame, frac=0.2, seed=42):
    test = ratings.groupby("user_id", group_keys=False).sample(frac=frac, random_state=seed)
    return ratings.drop(test.index), test


def evaluate(rec: Recommender, train: pd.DataFrame, test: pd.DataFrame, alpha=None, beta=None, gamma=None, k=K, thr=THRESHOLD):
    a = rec.p["alpha"] if alpha is None else alpha
    train_by_user = {u: g.set_index("movie_id")["rating"].to_dict() for u, g in train.groupby("user_id")}
    test_by_user = {u: g for u, g in test.groupby("user_id")}
    methods = ["popularity", "content", "cf", "hybrid"]
    errs = {m: [] for m in ["global_mean", "user_mean", "bias_baseline", "content", "cf", "hybrid"]}
    prec = {m: [] for m in methods}; rcl = {m: [] for m in methods}
    recommended = {m: set() for m in methods}

    for u, tr in train_by_user.items():
        te = test_by_user.get(u)
        if te is None:
            continue
        ridx, vals, mu = rec.user_profile(tr)
        cf, cb = rec.deviations(ridx, vals, mu)
        ti = te["movie_id"].map(rec.idx).to_numpy()
        y = te["rating"].to_numpy()
        base = mu + rec.item_bias[ti]
        clip = lambda p: np.clip(p, 0.5, 5.0)
        errs["global_mean"] += list(rec.global_mean - y)
        errs["user_mean"] += list(clip(mu) - y)
        errs["bias_baseline"] += list(clip(base) - y)
        errs["content"] += list(clip(base + cb[ti]) - y)
        errs["cf"] += list(clip(base + cf[ti]) - y)
        errs["hybrid"] += list(clip(base + a * cf[ti] + (1 - a) * cb[ti]) - y)

        mask = rec._candidate_mask(ridx)
        rel = {int(i) for i, r_ in zip(ti, y) if r_ >= thr and mask[i]}
        if not rel:
            continue
        scores = {
            "popularity": rec.bayes_avg,
            "content": rec.blend(cf, cb, "content"),
            "cf": rec.blend(cf, cb, "cf"),
            "hybrid": rec.blend(cf, cb, "hybrid", alpha=alpha, beta=beta, gamma=gamma),
        }
        for m, s in scores.items():
            top = rec._top(s, mask, k)
            hits = len(rel.intersection(int(i) for i in top))
            prec[m].append(hits / k); rcl[m].append(hits / len(rel))
            recommended[m].update(int(i) for i in top)

    rmse = {m: float(np.sqrt(np.mean(np.square(e)))) for m, e in errs.items()}
    n_cand = int((rec.item_count >= rec.p["min_ratings"]).sum())
    return {
        "rmse": rmse,
        "precision_at_k": {m: float(np.mean(v)) for m, v in prec.items()},
        "recall_at_k": {m: float(np.mean(v)) for m, v in rcl.items()},
        "catalog_coverage": {m: len(s) / n_cand for m, s in recommended.items()},
        "users_evaluated": len(prec["hybrid"]),
        "k": k, "relevance_threshold": thr,
    }


def tune(train, movies, tags, grid, seed=7, min_coverage=0.05):
    """Pick hybrid alpha/beta/gamma on a validation split carved out of the TRAINING data only.
    alpha is limited to 0.4-0.8 so the hybrid always blends both the collaborative and the content signal.
    Objective: highest Precision@K among settings whose catalog coverage is at least `min_coverage`
    (so the winner cannot simply recommend the same few blockbusters to everybody)."""
    tr2, val = split_ratings(train, frac=0.15, seed=seed)
    rec = Recommender(movies, tr2, tags)
    best, rows = None, []
    for alpha, beta, gamma in grid:
        res = evaluate(rec, tr2, val, alpha=alpha, beta=beta, gamma=gamma)
        p, cov = res["precision_at_k"]["hybrid"], res["catalog_coverage"]["hybrid"]
        rows.append({"alpha": alpha, "beta": beta, "gamma": gamma, "p_at_k": round(p, 4),
                     "coverage": round(cov, 3), "rmse": round(res["rmse"]["hybrid"], 4)})
        if cov >= min_coverage and (best is None or p > best[0]):
            best = (p, alpha, beta, gamma)
    return best[1], best[2], best[3], rows


def run(do_tune=True, out=EVAL_PATH):
    t0 = time.time()
    movies, ratings, tags = load_tables()
    movies, ratings = clean(movies, ratings)
    train, test = split_ratings(ratings)
    alpha, beta, gamma, tuning = MODEL_PARAMS["alpha"], MODEL_PARAMS["beta"], MODEL_PARAMS["gamma"], []
    if do_tune:
        grid = [(a, b, g) for a in (0.4, 0.6, 0.8) for b in (0.0, 0.5) for g in (0.05, 0.1, 0.2, 0.4)]
        alpha, beta, gamma, tuning = tune(train, movies, tags, grid)
        print(f"Validation-selected alpha={alpha}, beta={beta}, gamma={gamma}")
    rec = Recommender(movies, train, tags)
    res = evaluate(rec, train, test, alpha=alpha, beta=beta, gamma=gamma)
    res.update({"alpha": alpha, "beta": beta, "gamma": gamma, "tuning": tuning,
                "train_ratings": len(train), "test_ratings": len(test),
                "seconds": round(time.time() - t0, 1)})
    out.write_text(json.dumps(res, indent=2))
    return res


def print_report(res):
    print(f"\nUsers evaluated: {res['users_evaluated']}   K={res['k']}   relevant = rating >= {res['relevance_threshold']}")
    print("\nRMSE (lower is better)")
    for m, v in res["rmse"].items():
        print(f"  {m:14s} {v:.4f}")
    print("\nRanking metrics")
    print(f"  {'model':12s} {'P@K':>8s} {'R@K':>8s} {'coverage':>9s}")
    for m in res["precision_at_k"]:
        print(f"  {m:12s} {res['precision_at_k'][m]:8.4f} {res['recall_at_k'][m]:8.4f} {res['catalog_coverage'][m]:9.3f}")


if __name__ == "__main__":
    print_report(run(do_tune="--no-tune" not in sys.argv))
