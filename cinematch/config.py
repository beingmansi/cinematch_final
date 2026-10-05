"""Central settings for CineMatch. Secrets (TMDB key) come from environment variables / .env only."""
import os
from pathlib import Path

try:  # optional: load variables from a .env file in the project root
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def _default_db() -> Path:
    """data/cinematch.db, or the system temp folder if the project folder is read-only (some hosts)."""
    try:
        DATA_DIR.mkdir(exist_ok=True)
        probe = DATA_DIR / ".write_test"
        probe.touch(); probe.unlink()
        return DATA_DIR / "cinematch.db"
    except OSError:
        import tempfile
        return Path(tempfile.gettempdir()) / "cinematch.db"


DB_PATH = Path(os.getenv("CINEMATCH_DB") or _default_db())
MOVIELENS_DIR = DATA_DIR / "ml-latest-small"
MOVIELENS_URL = "https://files.grouplens.org/datasets/movielens/ml-latest-small.zip"
EVAL_PATH = DATA_DIR / "eval_results.json"

API_HOST = os.getenv("CINEMATCH_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("CINEMATCH_API_PORT", "8000"))
API_URL = os.getenv("CINEMATCH_API_URL", f"http://{API_HOST}:{API_PORT}")


def add_movie_enabled() -> bool:
    """The 'Add movie from TMDB' feature is built but switched off by default.
    Turn it on with CINEMATCH_ENABLE_ADD=1 (in .env or the host's secrets) - it also needs a TMDB key."""
    return os.getenv("CINEMATCH_ENABLE_ADD", "0").strip() in ("1", "true", "True", "yes")


def get_tmdb_key() -> str:
    """Read at call time so the key can be set after import (optional feature)."""
    return os.getenv("TMDB_API_KEY", "").strip()


# Recommender hyper-parameters (tuned on a validation split, see recommender/evaluate.py)
MODEL_PARAMS = {
    "k_neighbors": 100,   # neighbours kept per movie in the collaborative model
    "shrink": 10.0,       # shrinks similarities that rest on few co-raters
    "lam_cf": 2.0,        # damping for the collaborative deviation
    "lam_cb": 2.0,        # damping for the content deviation
    "lam_item": 5.0,      # damping for the item bias
    "user_prior": 3.0,    # pseudo-ratings pulling a user's mean toward the global mean
    "alpha": 0.8,         # hybrid weight on collaborative (1 - alpha on content)
    "beta": 0.0,          # hybrid weight on the item quality bias
    "gamma": 0.1,         # hybrid weight on item popularity (standardised log rating count)
    "min_ratings": 5,     # movies with fewer ratings are not recommended
}
