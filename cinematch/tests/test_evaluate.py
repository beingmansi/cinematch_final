import numpy as np
from recommender.evaluate import evaluate, split_ratings
from recommender.hybrid import Recommender


def test_split_has_no_leakage(tables):
    _, r, _ = tables
    train, test = split_ratings(r)
    assert len(train) + len(test) == len(r)
    key = lambda d: set(zip(d.user_id, d.movie_id))
    assert not key(train) & key(test)
    assert train.user_id.nunique() == test.user_id.nunique() == 610


def test_models_beat_baselines(tables):
    m, r, t = tables
    sub = r[r.user_id <= 150]                      # smaller sample keeps the test fast
    train, test = split_ratings(sub)
    res = evaluate(Recommender(m, train, t), train, test)
    rm = res["rmse"]
    assert rm["hybrid"] < rm["user_mean"] < rm["global_mean"]
    assert rm["hybrid"] < rm["bias_baseline"]
    assert res["precision_at_k"]["hybrid"] > res["precision_at_k"]["content"]
    assert all(0 <= v <= 1 for d in (res["precision_at_k"], res["recall_at_k"], res["catalog_coverage"]) for v in d.values())
