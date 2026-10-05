"""Item-item neighbourhood builder (collaborative filtering core)."""
import numpy as np
import scipy.sparse as sp


def build_item_knn(R: np.ndarray, B: np.ndarray, k: int, shrink: float, chunk: int = 300) -> sp.csr_matrix:
    """Return a sparse (items x items) similarity matrix keeping the top-k positive neighbours per item.

    R: dense (users x items) matrix of residual ratings (0 where unrated)
    B: dense (users x items) 0/1 matrix, 1 where the user rated the item
    Similarity = cosine of the residual columns, shrunk by co-rater count: sim * n/(n+shrink).
    """
    n_items = R.shape[1]
    norms = np.linalg.norm(R, axis=0)
    norms[norms == 0] = 1.0
    Rn = (R / norms).astype(np.float32)
    B = B.astype(np.float32)
    rows, cols, vals = [], [], []
    kk = min(k, n_items - 1)
    for start in range(0, n_items, chunk):
        stop = min(start + chunk, n_items)
        sim = Rn[:, start:stop].T @ Rn                 # (chunk, items)
        co = B[:, start:stop].T @ B                    # co-rater counts
        sim *= co / (co + shrink)
        idx = np.arange(stop - start)
        sim[idx, start + idx] = 0.0                    # no self-similarity
        sim[sim < 0] = 0.0                             # keep positive neighbours only
        top = np.argpartition(-sim, kk - 1, axis=1)[:, :kk]
        topv = np.take_along_axis(sim, top, axis=1)
        keep = topv > 0
        r = np.repeat(np.arange(start, stop), kk).reshape(-1, kk)
        rows.append(r[keep]); cols.append(top[keep]); vals.append(topv[keep])
    return sp.csr_matrix(
        (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
        shape=(n_items, n_items), dtype=np.float32,
    )
