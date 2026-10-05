# 🎬 CineMatch – Intelligent Movie Recommendation and Review System

AIML project: a hybrid movie recommender (content-based + collaborative filtering) with a FastAPI backend,
a Streamlit frontend and a SQLite database, built on the MovieLens `ml-latest-small` dataset.

## Quick start

```bash
# 1. (recommended) create a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows        |   source venv/bin/activate   (Mac/Linux)

# 2. install
pip install -r requirements.txt

# 3. run everything (loads the data on first start, then opens the app in your browser)
python run.py
```

* App: http://localhost:8501  * API docs: http://127.0.0.1:8000/docs
* The dataset is already in `data/ml-latest-small/`. If you delete it, `run.py` downloads it again.
* Run manually instead of `run.py`:
  `python -m data.load_movielens` → `uvicorn backend.main:app` → (second terminal) `streamlit run frontend/app.py`

**Try it:** click *Demo user* (a real MovieLens user with 232 ratings) or sign in with any new username, open a
movie, rate it, save it with **🔖 Save**, and watch **🎯 For You** change. Compare the four methods in *For You → Method*.

## What you can do in the app

| Where | What |
|---|---|
| **Bottom bar** | 🏠 Home · 🎯 For You · 🔖 Watchlist · ⭐ Ratings (· ➕ Add, see below) |
| **Sidebar** | 📊 Model Evaluation · ⚙️ User settings (only these two) |
| **Home** | Search bar, pick **several genres at once** (match *any* or *all*), sort, 60 movies at a time + "Show more" |
| **Movie page** | Poster, description, your rating, write a review, add to watchlist, reviews from CineMatch users **and TMDB**, "More like this" |
| **For You** | Personal picks (hybrid / collaborative / content / popular), genre filter, "Because you liked …" |
| **Add** (off by default) | Search TMDB and add any movie to CineMatch – built, but hidden until you set `CINEMATCH_ENABLE_ADD=1` |
| **Settings** | Your stats, sign out, clear ratings/watchlist, delete account |

Without a TMDB key you get coloured title cards instead of posters; everything else works.

## TMDB: posters, descriptions, TMDB reviews, adding movies (free, optional)
1. Create a free account at themoviedb.org, **verify your email**, then Settings → API → request a key
   (choose the personal / non-commercial option; no student proof is asked).
2. Copy `.env.example` to a new file called `.env` and paste the key after `TMDB_API_KEY=`
   (the long **API Read Access Token** or the 32-character **API Key** both work). No quotes, no spaces.
3. Restart the app (`python run.py`). Posters and the **From TMDB** review tab switch on.
4. *Optional:* to also switch on the **➕ Add** page, put `CINEMATCH_ENABLE_ADD=1` in `.env` (or the host's secrets). It is off by default.

Rules to follow: keep the key secret (`.env` is git-ignored – never upload it), keep the TMDB credit line
(it is in the app footer), and don't use the key commercially. TMDB data cached in the database is re-fetched after
150 days (TMDB's terms don't allow keeping it longer than 6 months).
The first time you open a screen of 60 movies with a key, loading the posters takes a few seconds; afterwards they are cached.

**Movies added from TMDB** get id `1,000,000 + tmdb_id`, have no ratings yet, and appear in search, genre lists and
"More like this". They join the personalised recommendations once at least 5 people have rated them.

**Optional sample reviews** (so review pages aren't empty in a demo): `python -m data.seed_demo`
(remove with `--remove`). They are clearly tagged "sample review" and are placeholder text, not real opinions.

## Deploying online (free: Streamlit Community Cloud)

CineMatch has two parts (API + website), but Streamlit Community Cloud runs one program. `streamlit_app.py` handles this:
it starts the API inside the same process and then shows the site. You do not change any code.

1. **Put the project on GitHub** (see "Safe GitHub upload" below). Do **not** upload `.env` or the database.
2. Go to **share.streamlit.io**, sign in with GitHub, click **Create app** / **New app**.
3. Choose your repository and branch (usually `main`) and set **Main file path** to `streamlit_app.py`.
4. Open **Advanced settings**: pick **Python 3.11 or 3.12**, and paste your TMDB key into **Secrets** (format: `.streamlit/secrets.toml.example`). No key? Skip this – the app still works.
5. Click **Deploy**. The first start takes a minute or two (it installs packages, builds the database and trains the models).
   You get a link like `https://your-name-cineMatch.streamlit.app` to share.

What to expect on the free plan (measured on this project: ~290 MB normal, ~400 MB briefly at start-up; the limit is ~1 GB):
* The app **sleeps after ~12 hours without visitors** and wakes on the next visit (a short "waking up" wait).
* **User data is not permanent.** New users, ratings, reviews and watchlists are kept in a file inside the app's
  container, which can be reset whenever the app restarts or you redeploy. The MovieLens data and the models are rebuilt
  automatically, so the app always works – but visitors' own data may disappear. For permanent storage you would
  move the database to an external service (e.g. a hosted Postgres) – ask if you want that.
* **Sign-in is username-only**, so on a public site anyone can type another visitor's username and become them
  (they could also delete that profile). Fine for a college demo; add passwords/PINs before real use.
* Keep the TMDB credit line in the footer, and keep the repo/app non-commercial (MovieLens and TMDB terms).

**Safe GitHub upload:** run `git status` before the first commit – `.env`, `venv/` and `data/cinematch.db` must **not**
appear (they are in `.gitignore`). If a key ever reaches GitHub, delete that TMDB key on TMDB's site and create a new one.

## Architecture

```
Streamlit (frontend/app.py) ──HTTP──▶ FastAPI (backend/main.py) ──▶ Recommender (recommender/)  [in memory]
                                              │
                                              └──▶ SQLite (data/cinematch.db): movies, users, ratings, reviews, watchlist, links, tags, TMDB caches
```

| Folder | What is inside |
|---|---|
| `frontend/` | `app.py` (all pages + bottom navigation bar), `api_client.py` |
| `backend/` | `main.py` (endpoints), `database.py` (schema), `schemas.py` (validation), `service.py` (model holder), `tmdb.py` (posters, reviews, add movie) |
| `recommender/` | `content_based.py`, `knn.py`, `hybrid.py`, `evaluate.py`, `data_prep.py` |
| (root) | `run.py` (local launcher), `streamlit_app.py` (deployment entry), `requirements.txt`, `requirements-dev.txt` (tests) |
| `data/` | `load_movielens.py`, `seed_demo.py`, `ml-latest-small/`, `eval_results.json` |
| `tests/` | 51 automated tests (`pytest`), incl. a fake TMDB server and headless UI tests |

## How the recommender works

1. **Baseline** – predicted rating = user average (pulled toward the global mean for users with few ratings) + a damped
   *movie bias* (is this movie generally rated above or below average?).
2. **Content-based** – every movie becomes a TF-IDF vector from its genres, decade, title words and user tags.
   A movie is scored by how similar it is (cosine) to the movies the user rated above/below their baseline.
3. **Collaborative (item-based kNN)** – movies are similar when the same users rate them above/below their baselines
   (cosine on residual ratings, shrunk when few users rated both, top-100 neighbours kept per movie).
4. **Hybrid** – `score = α·collaborative + (1−α)·content + β·movie bias + γ·popularity`. α, β, γ were chosen on a
   validation split cut from the training data (not the test data): **α = 0.8, β = 0, γ = 0.1**.
5. **Cold start** – a user with no ratings gets popular movies; one rating already starts personalising (content
   model works immediately, and the collaborative model uses the user's own list so no retraining is needed).

## Results (20% of each user's ratings held out; 594 users with ≥1 relevant held-out movie)

Relevant = held-out rating ≥ 4.0; lists of 10; only movies with ≥ 5 training ratings can be recommended.

| Model | Precision@10 | Recall@10 | Catalog coverage |
|---|---|---|---|
| Popularity (baseline) | 0.077 | 0.056 | 1.2 % |
| Content-based | 0.025 | 0.029 | 53 % |
| Collaborative (item-kNN) | 0.059 | 0.060 | 48 % |
| **Hybrid** | **0.127** | **0.113** | 10.7 % |

| RMSE (lower is better) | |
|---|---|
| Global mean | 1.050 |
| User mean | 0.951 |
| User + movie bias | 0.892 |
| Content-based | 0.863 |
| Collaborative | 0.865 |
| **Hybrid** | **0.863** |

Reproduce: `python -m recommender.evaluate` (≈2 min; add `--no-tune` to skip the weight search).

**Honest reading of the numbers:** the hybrid doubles the precision of the popularity baseline and has lower
rating error than all baselines. Pure content-based and pure collaborative lists have low precision here because
users mostly rate popular films, but they are far more diverse (coverage). With only 610 users and 98.3 % sparsity,
absolute precision values are small – that is normal for this dataset size. The hybrid trades some diversity
(10.7 % coverage) for accuracy; raise `gamma`→0 in `config.py` for more varied (but less accurate) lists.

## API (all JSON, interactive docs at `/docs`)

`GET /health` · `POST /users` · `GET/DELETE /users/{id}` · `GET/DELETE /users/{id}/ratings` ·
`GET /genres` · `GET /movies` (search, `genres=A,B&match=any|all`, sort, paging) · `GET /movies/{id}` ·
`GET /movies/{id}/similar` · `GET /popular` · `POST /ratings` · `POST /reviews` · `GET /movies/{id}/reviews` ·
`GET /movies/{id}/tmdb-reviews` · `POST /watchlist` · `DELETE /watchlist/{user}/{movie}` ·
`GET/DELETE /users/{id}/watchlist` · `GET /users/{id}/watchlist/ids` · `GET /tmdb/search` · `POST /tmdb/add` ·
`GET /recommend/{user_id}?mode=hybrid|content|cf|popular&genres=A,B` · `GET /evaluation` · `POST /admin/retrain`

Ratings you add are used immediately for your own recommendations; the backend retrains when it starts, when a
TMDB movie is added, or on `POST /admin/retrain` – that is when new ratings also join the movie-to-movie model.
The sample MovieLens accounts (`ml_user_*`) cannot be deleted or wiped through the API.

## Tests
Install the test tools with `pip install -r requirements-dev.txt`, then `pytest` runs 51 tests: data cleaning, recommenders, no train/test leakage, evaluation sanity, every API endpoint
(validation, SQL/HTML-injection attempts), the TMDB code against a fake local TMDB server, and the Streamlit pages
clicked through headlessly. They use a temporary database and never need internet or a key.

## Notes & limits
* Sign-in is username-only (no password) – fine for a demo, not for production.
* Data: MovieLens ml-latest-small (610 users, 9,742 movies, 100,836 ratings). F. Maxwell Harper and Joseph A. Konstan (2015),
  *The MovieLens Datasets: History and Context*, ACM TiiS 5(4). Dataset © GroupLens – for research/education; cite it if you submit this work.
* This product uses the TMDB API but is not endorsed or certified by TMDB. (TMDB logo: if your TMDB agreement asks for it, add the official logo from TMDB's website next to the footer text.)
* Sign-in is username-only; anyone who types your username becomes you. Fine for a demo; add real authentication before publishing it.

## Troubleshooting
| Problem | Fix |
|---|---|
| "Cannot reach the CineMatch backend" | The API is not running – use `python run.py`, or start `uvicorn backend.main:app` first |
| `ModuleNotFoundError: config` / `backend` | Run commands from the project root folder (the one containing `run.py`) |
| "No data loaded" | `python -m data.load_movielens` then restart the API |
| Port already in use | Close the old run, or set `CINEMATCH_API_PORT` / use `streamlit run ... --server.port 8502` |
| Model Evaluation page empty | `python -m recommender.evaluate` |
| No posters, "TMDB is not set up" | Check `.env` (see TMDB section), verify your TMDB email, restart the app |
| Updated from an older CineMatch version | Delete `data/cinematch.db` and run `python run.py` (rebuilds the database) |
