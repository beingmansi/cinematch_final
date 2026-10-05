"""CineMatch - Streamlit frontend. Run:  streamlit run frontend/app.py"""
import html
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # lets `import api_client` work from any folder

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from api_client import APIError, delete, get, post

try:   # streamlit_app.py (deployment entry) may already have set this
    st.set_page_config(page_title="CineMatch", page_icon="🎬", layout="wide")
except st.errors.StreamlitAPIException:
    pass

# ------------------------------------------------------------------ styling (bottom navigation bar etc.)
st.markdown("""
<style>
/* leave room for the floating bottom bar */
[data-testid="stMainBlockContainer"], .block-container { padding-bottom: 7.5rem !important; }
/* bottom navigation bar: a floating pill fixed to the bottom of the screen */
.st-key-bottom_nav {
    position: fixed; bottom: 14px; left: 50%; transform: translateX(-50%);
    width: min(780px, 94vw); z-index: 1000; padding: 6px 10px;
    background: rgba(128,128,128,0.20); backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
    border: 1px solid rgba(128,128,128,0.35); border-radius: 20px; box-shadow: 0 8px 28px rgba(0,0,0,0.28);
}
.st-key-bottom_nav button { border: none; padding: 0.35rem 0.2rem; font-size: 0.85rem; }
/* keep the 5 buttons in ONE row, even on phones (Streamlit normally stacks columns there) */
.st-key-bottom_nav [data-testid="stHorizontalBlock"] { gap: 0.25rem !important; flex-wrap: nowrap !important; }
.st-key-bottom_nav [data-testid="stColumn"] { min-width: 0 !important; width: auto !important; flex: 1 1 0 !important; }
.st-key-bottom_nav button p { white-space: nowrap; }
@media (max-width: 640px) {
    .st-key-bottom_nav { width: 97vw; padding: 4px 4px; bottom: 8px; }
    .st-key-bottom_nav button { padding: 0.3rem 0; }
    .st-key-bottom_nav button p { font-size: 0.64rem; }
    /* movie grid: two cards per row on phones instead of one long single column */
    [class*="st-key-grid_"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.5rem !important; }
    [class*="st-key-grid_"] [data-testid="stColumn"] { min-width: calc(50% - 0.5rem) !important; flex: 1 1 calc(50% - 0.5rem) !important; width: auto !important; }
    /* ...and inside a card, stack the Open / Save buttons so their labels fit */
    [class*="st-key-grid_"] [data-testid="stColumn"] [data-testid="stColumn"] { min-width: 100% !important; flex: 1 1 100% !important; }
}
</style>
""", unsafe_allow_html=True)

NAV_ALL = [("home", "🏠", "Home"), ("foryou", "🎯", "For You"), ("watchlist", "🔖", "Watchlist"),
       ("ratings", "⭐", "Ratings"), ("add", "➕", "Add")]
CARD_COLS = 5
PAGE_SIZE = 60

ss = st.session_state
ss.setdefault("user", None)
ss.setdefault("page", "home")
ss.setdefault("movie_id", None)
ss.setdefault("wl", set())
ss.setdefault("flash", None)
ss.setdefault("prev_page", "home")
for k in ("home_limit", "rec_limit", "rate_limit", "wl_limit"):
    ss.setdefault(k, PAGE_SIZE if k != "rec_limit" else 30)


# ------------------------------------------------------------------ helpers
def uid():
    return ss.user["user_id"] if ss.user else None


def goto(page: str):
    if page != "movie":
        ss.prev_page = page
    ss.page = page
    ss.scroll_top = True


def open_movie(movie_id: int):
    ss.prev_page = ss.page if ss.page != "movie" else ss.prev_page
    ss.movie_id = movie_id
    ss.page = "movie"
    ss.scroll_top = True


def safe(fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except APIError as e:
        st.error(str(e))
        return default


def sign_in(name: str):
    res = safe(post, "/users", {"username": name})
    if res:
        ss.user = res
        ss.wl = set(safe(get, f"/users/{res['user_id']}/watchlist/ids", default=[]))
        ss.flash = ("success", f"Welcome, {res['username']}!" if res["created"] else f"Welcome back, {res['username']}!")


def sign_out():
    ss.user = None
    ss.wl = set()
    ss.page = "home"


def toggle_watch(movie_id: int):
    if not uid():
        ss.flash = ("warning", "Sign in first to use your watchlist (open ⚙️ User settings in the sidebar, or use the box on Home).")
        return
    try:
        if movie_id in ss.wl:
            delete(f"/watchlist/{uid()}/{movie_id}")
            ss.wl.discard(movie_id)
        else:
            post("/watchlist", {"user_id": uid(), "movie_id": movie_id})
            ss.wl.add(movie_id)
    except APIError as e:
        ss.flash = ("error", str(e))


def more(key: str, step: int):
    ss[key] += step


@st.cache_data(ttl=600, show_spinner=False)
def genres_list():
    return get("/genres")


def stars_text(avg, n):
    return f"⭐ {avg:.2f} · {n:,} ratings" if avg is not None else "No ratings yet"


def poster(m: dict):
    """Real poster if TMDB gave us one, otherwise a coloured title card."""
    if m.get("poster_url"):
        st.image(m["poster_url"], width="stretch")
        return
    seed = (m["genres"][0] if m.get("genres") else m["title"]).encode()
    hue = zlib.crc32(seed) % 360
    st.markdown(
        f'<div style="aspect-ratio:2/3;border-radius:10px;display:flex;align-items:center;justify-content:center;'
        f'padding:12px;text-align:center;color:#fff;font-weight:700;line-height:1.25;'
        f'background:linear-gradient(160deg,hsl({hue},55%,34%),hsl({(hue + 45) % 360},60%,16%))">'
        f'{html.escape(m["title"])}</div>', unsafe_allow_html=True)


def movie_card(m: dict, key: str, extra: str | None = None):
    with st.container(border=True):
        poster(m)
        year = f" ({m['year']})" if m.get("year") else ""
        st.markdown(f"**{m['title']}**{year}")
        st.caption(" · ".join(m["genres"]) if m["genres"] else "No genres listed")
        st.caption(stars_text(m.get("avg_rating"), m.get("n_ratings", 0)))
        if m.get("user_rating"):
            st.caption(f"Your rating: {m['user_rating']} ★")
        if extra:
            st.caption(extra)
        c1, c2 = st.columns(2)
        c1.button("Open", key=f"open_{key}_{m['movie_id']}", on_click=open_movie, args=(m["movie_id"],), width="stretch")
        saved = m["movie_id"] in ss.wl
        c2.button("✅ Saved" if saved else "🔖 Save", key=f"wl_{key}_{m['movie_id']}", on_click=toggle_watch,
                  args=(m["movie_id"],), help="Remove from watchlist" if saved else "Add to watchlist", width="stretch")


def grid(movies: list[dict], key: str, extras: dict | None = None):
    if not movies:
        st.info("Nothing to show here yet.")
        return
    for start in range(0, len(movies), CARD_COLS):
        with st.container(key=f"grid_{key}_{start}"):
            row = st.columns(CARD_COLS)
            for col, m in zip(row, movies[start:start + CARD_COLS]):
                with col:
                    movie_card(m, key, (extras or {}).get(m["movie_id"]))


def show_more_button(shown: int, total: int, state_key: str, step: int = PAGE_SIZE):
    st.caption(f"Showing {shown:,} of {total:,}")
    if shown < total:
        st.button(f"Show {min(step, total - shown)} more", key=f"more_{state_key}", on_click=more,
                  args=(state_key, step))


def flash():
    if ss.flash:
        kind, text = ss.flash
        getattr(st, kind, st.info)(text)
        ss.flash = None


def login_box(title="Sign in to rate, review and save movies"):
    with st.container(border=True):
        st.markdown(f"**{title}**")
        c1, c2, c3 = st.columns([3, 1, 1])
        name = c1.text_input("Username", placeholder="pick any username, e.g. mansi_01", key="login_name",
                             label_visibility="collapsed")
        c2.button("Continue", width="stretch", on_click=lambda: sign_in(ss.login_name), key="btn_login")
        c3.button("Demo user", width="stretch", on_click=lambda: sign_in("ml_user_1"), key="btn_demo",
                  help="Sample account with 232 ratings (read-only for account deletion)")
        st.caption("No password needed. A new username creates a new profile.")


def footer():
    st.divider()
    st.caption("Movie ratings: MovieLens (GroupLens Research). Posters, descriptions and TMDB reviews: "
               "This product uses the TMDB API but is not endorsed or certified by TMDB.")


# ------------------------------------------------------------------ backend check
health = safe(get, "/health")
if health is None:
    st.stop()
if health["status"] != "ok":
    st.error("The backend has no data. Run `python -m data.load_movielens` and restart the API.")
    st.stop()
TMDB_ON = health.get("tmdb_enabled", False)
NAV = [n for n in NAV_ALL if n[0] != "add" or health.get("add_movie_enabled")]
if ss.page == "add" and not health.get("add_movie_enabled"):
    ss.page = "home"

# ------------------------------------------------------------------ sidebar (only 2 entries)
with st.sidebar:
    st.title("🎬 CineMatch")
    st.caption(f"{health['movies']:,} movies · {health['ratings']:,} ratings")
    st.button("📊 Model Evaluation", width="stretch", on_click=goto, args=("eval",),
              type="primary" if ss.page == "eval" else "secondary")
    st.button("⚙️ User settings", width="stretch", on_click=goto, args=("settings",),
              type="primary" if ss.page == "settings" else "secondary")
    st.divider()
    if ss.user:
        st.success(f"Signed in as **{ss.user['username']}**")
    else:
        st.info("Not signed in")


# ------------------------------------------------------------------ pages
def page_home():
    st.title("🎬 CineMatch")
    flash()
    if not ss.user:
        login_box()
    elif ss.user.get("n_ratings", 0) == 0 and not st.session_state.get("welcome_seen"):
        with st.container(border=True):
            st.markdown("**👋 Getting started** — 1️⃣ Open a few movies you know and rate them · "
                        "2️⃣ Go to **🎯 For You** to see picks made for you · 3️⃣ Tap **🔖 Save** on anything you want to watch later.")

    q = st.text_input("Search", placeholder="🔍 Search movies by title…", key="home_q", label_visibility="collapsed")
    c1, c2, c3 = st.columns([5, 2, 2])
    sel = c1.multiselect("Genres", genres_list(), key="home_genres", placeholder="Pick one or more genres")
    match = c2.radio("Match", ["Any selected", "All selected"], key="home_match", horizontal=True,
                     disabled=len(sel) < 2, help="Any = movies with at least one of the genres. All = movies that have every genre.")
    sort = c3.selectbox("Sort by", ["Most popular", "Highest rated", "Newest", "A–Z"], key="home_sort")
    sig = (q, tuple(sel), match, sort)
    if ss.get("home_sig") != sig:
        ss.home_sig = sig
        ss.home_limit = PAGE_SIZE

    with st.expander("ℹ️ How do the recommendations work?"):
        st.markdown(
            "- **Content-based** – *you liked Toy Story, so here are other animated family films* (compares genres, years, titles, tags).\n"
            "- **Collaborative** – *people whose taste matches yours loved these* (compares rating patterns).\n"
            "- **Hybrid** – blends both, plus a little popularity. This is the default on **🎯 For You**.")

    res = safe(get, "/movies", q=q, genres=",".join(sel), match="all" if match == "All selected" else "any",
               sort={"Most popular": "popular", "Highest rated": "rating", "Newest": "year", "A–Z": "title"}[sort],
               limit=ss.home_limit, user_id=uid())
    if not res:
        return
    if not q and not sel:
        st.subheader("Popular right now")
    elif sel:
        st.subheader(f"{', '.join(sel)} movies")
    grid(res["items"], "home")
    show_more_button(len(res["items"]), res["total"], "home_limit")
    footer()


def page_for_you():
    st.title("🎯 Recommended for you")
    flash()
    if not uid():
        login_box("Sign in to get recommendations made for you")
        return
    labels = {"hybrid": "Hybrid (best)", "cf": "Collaborative", "content": "Content-based", "popular": "Just popular"}
    c1, c2 = st.columns([2, 5])
    mode = c1.selectbox("Method", list(labels), format_func=labels.get)
    sel = c2.multiselect("Genres", genres_list(), key="rec_genres", placeholder="Any genre — or pick several")
    match = "any"
    if len(sel) > 1:
        match = "all" if st.radio("Match", ["Any selected", "All selected"], horizontal=True, key="rec_match") == "All selected" else "any"
    alpha = None
    if mode == "hybrid":
        with st.expander("Advanced: hybrid mix"):
            alpha = st.slider("Content ←→ Collaborative", 0.0, 1.0, 0.8, 0.05,
                              help="0 = only movie content (genres, tags, title), 1 = only what similar users liked")
    sig = (mode, tuple(sel), match, alpha)
    if ss.get("rec_sig") != sig:
        ss.rec_sig = sig
        ss.rec_limit = 30
    res = safe(get, f"/recommend/{uid()}", n=ss.rec_limit, mode=mode, genres=",".join(sel), match=match, alpha=alpha)
    if not res:
        return
    if res["cold_start"]:
        st.info("You haven't rated anything yet, so these are popular picks. Rate a few movies you know and these become personal.")
    elif res["n_user_ratings"] < 5:
        st.info(f"You've rated {res['n_user_ratings']} movies. A few more ratings will make the picks better.")
    extras = {}
    for it in res["items"]:
        bits = [f"We guess you'd give it {it['predicted_rating']:.1f} ★"]
        if it["because_you_liked"]:
            bits.append("Because you liked " + ", ".join(it["because_you_liked"]))
        extras[it["movie_id"]] = " · ".join(bits)
    grid(res["items"], "rec", extras=extras)
    if len(res["items"]) >= ss.rec_limit:
        st.button("Show 30 more", key="more_rec", on_click=more, args=("rec_limit", 30))
    footer()


def page_watchlist():
    st.title("🔖 My watchlist")
    flash()
    if not uid():
        login_box("Sign in to save movies for later")
        return
    res = safe(get, f"/users/{uid()}/watchlist", limit=ss.wl_limit)
    if not res:
        return
    if not res["items"]:
        st.info("Your watchlist is empty. Tap **🔖 Save** on any movie to save it here.")
    grid(res["items"], "wl")
    if res["items"]:
        show_more_button(len(res["items"]), res["total"], "wl_limit")
    footer()


def page_my_ratings():
    st.title("⭐ My ratings")
    flash()
    if not uid():
        login_box("Sign in to see your ratings")
        return
    res = safe(get, f"/users/{uid()}/ratings", limit=ss.rate_limit)
    if not res:
        return
    if not res["total"]:
        st.info("You haven't rated any movies yet. Open a movie on Home and give it stars.")
        return
    m1, m2 = st.columns(2)
    m1.metric("Movies rated", f"{res['total']:,}")
    m2.metric("Your average rating", f"{res['average']:.2f} ★")
    dist = pd.DataFrame({"Stars": [str(k) for k in sorted(res["distribution"])],
                         "Movies": [res["distribution"][k] for k in sorted(res["distribution"])]})
    st.caption("How you rate")
    st.bar_chart(dist.set_index("Stars"), height=180)
    grid(res["items"], "rate")
    show_more_button(len(res["items"]), res["total"], "rate_limit")
    footer()


def page_add():
    st.title("➕ Add a movie")
    flash()
    st.caption("Can't find a movie? Look it up on TMDB and add it to CineMatch.")
    if not TMDB_ON:
        st.warning("This needs a free TMDB key. Put it in the `.env` file as `TMDB_API_KEY=...` and restart the app. "
                   "See the README for the steps.")
        return
    q = st.text_input("Movie title", placeholder="e.g. Oppenheimer", key="add_q")
    if len(q.strip()) < 2:
        return
    hits = safe(get, "/tmdb/search", q=q.strip(), default=[])
    if not hits:
        st.info("No results.")
    for h in hits:
        with st.container(border=True):
            a, b = st.columns([1, 5])
            with a:
                if h.get("poster_url"):
                    st.image(h["poster_url"], width="stretch")
            with b:
                st.markdown(f"**{h['title']}** ({h['year'] or '?'})")
                st.caption(h["overview"] or "No description.")
                if st.button("Add to CineMatch", key=f"add_{h['tmdb_id']}"):
                    res = safe(post, "/tmdb/add", {"tmdb_id": h["tmdb_id"]})
                    if res:
                        if res["already_existed"]:
                            st.info(f"“{res['title']}” is already in CineMatch.")
                        else:
                            st.success(f"Added “{res['title']}”. It has no ratings yet — be the first to rate it!")
                        st.button("Open it", key=f"openadd_{h['tmdb_id']}", on_click=open_movie, args=(res["movie_id"],))
    footer()


def page_movie():
    mid = ss.movie_id
    if mid is None:
        st.info("Pick a movie from Home, For You or Watchlist (click **Open**).")
        return
    st.button("← Back", on_click=goto, args=(ss.prev_page,))
    flash()
    m = safe(get, f"/movies/{mid}", user_id=uid())
    if not m:
        return
    left, right = st.columns([1, 3])
    with left:
        poster(m)
    with right:
        st.header(f"{m['title']} ({m['year']})" if m.get("year") else m["title"])
        st.write(" · ".join(m["genres"]) or "No genres listed")
        st.write(stars_text(m.get("avg_rating"), m.get("n_ratings", 0)))
        if m.get("overview"):
            st.write(m["overview"])
        saved = mid in ss.wl
        st.button("✅ In your watchlist (click to remove)" if saved else "🔖 Add to watchlist", key="wl_detail",
                  on_click=toggle_watch, args=(mid,))

    st.subheader("Rate & review")
    if not uid():
        login_box("Sign in to rate and review this movie")
    else:
        opts = [x / 2 for x in range(1, 11)]
        c1, c2 = st.columns([4, 1])
        val = c1.select_slider("Your rating", options=opts, value=m["user_rating"] or 3.5, key=f"rate_{mid}")
        if c2.button("Save rating", width="stretch", key=f"saverate_{mid}"):
            if safe(post, "/ratings", {"user_id": uid(), "movie_id": mid, "rating": val}):
                ss.user["n_ratings"] = max(1, ss.user.get("n_ratings", 0))
                ss.flash = ("success", "Rating saved!")
                st.rerun()
        text = st.text_area("Write a review (optional)", max_chars=2000, key=f"rev_{mid}")
        if st.button("Post review", key=f"postrev_{mid}"):
            if not text.strip():
                st.warning("Write something first.")
            elif safe(post, "/reviews", {"user_id": uid(), "movie_id": mid, "text": text}):
                ss.flash = ("success", "Review posted!")
                st.rerun()

    st.subheader("Reviews")
    mine = safe(get, f"/movies/{mid}/reviews", default=[])
    theirs = safe(get, f"/movies/{mid}/tmdb-reviews", default=[])
    tab1, tab2 = st.tabs([f"CineMatch users ({len(mine)})", f"From TMDB ({len(theirs)})"])
    with tab1:
        if not mine:
            st.caption("No reviews from CineMatch users yet — be the first!")
        for r in mine:
            with st.container(border=True):
                tag = " · *sample review*" if r["username"].startswith("sample_") else ""
                st.markdown(f"**{r['username']}**" + (f" · ★ {r['rating']}" if r.get("rating") else "") + tag)
                st.text(r["text"])      # st.text shows what users typed verbatim (no markdown/HTML)
                st.caption(r["created"])
    with tab2:
        if not TMDB_ON:
            st.caption("Add a TMDB key to see reviews from TMDB here.")
        elif not theirs:
            st.caption("TMDB has no reviews for this movie.")
        for r in theirs:
            with st.container(border=True):
                st.markdown(f"**{r['author']}**" + (f" · ★ {r['rating']}" if r.get("rating") else ""))
                st.text(r["content"][:900] + ("…" if len(r["content"]) > 900 else ""))

    st.subheader("More like this")
    sims = safe(get, f"/movies/{mid}/similar", n=10, user_id=uid(), default=[])
    grid(sims, "sim", extras={s["movie_id"]: f"{round(s['similarity'] * 100)}% similar" for s in sims})
    footer()


def page_settings():
    st.title("⚙️ User settings")
    flash()
    if not ss.user:
        login_box("Sign in or create a profile")
        st.caption("Your username is the only thing that identifies you here (no password), so don't use it for anything sensitive.")
        return
    info = safe(get, f"/users/{uid()}")
    if not info:
        return
    st.subheader(f"Hello, {info['username']}")
    a, b, c = st.columns(3)
    a.metric("Movies rated", info["n_ratings"])
    b.metric("In watchlist", info["n_watchlist"])
    c.metric("Reviews written", info["n_reviews"])
    st.button("Sign out", on_click=sign_out)
    st.divider()
    st.subheader("Your data")
    if info["is_sample"]:
        st.info("This is a read-only sample account from the MovieLens dataset. Create your own username to manage your data.")
    else:
        cc1, cc2 = st.columns(2)
        if cc1.button("Clear all my ratings"):
            if safe(delete, f"/users/{uid()}/ratings"):
                st.success("Ratings cleared.")
        if cc2.button("Clear my watchlist"):
            if safe(delete, f"/users/{uid()}/watchlist"):
                ss.wl = set()
                st.success("Watchlist cleared.")
        with st.expander("Delete my account"):
            st.warning("This permanently deletes your profile, ratings, reviews and watchlist.")
            sure = st.checkbox("I understand, delete everything", key="del_sure")
            if st.button("Delete my account", disabled=not sure):
                if safe(delete, f"/users/{uid()}"):
                    sign_out()
                    ss.flash = ("success", "Account deleted.")
                    st.rerun()
    st.divider()
    st.subheader("About")
    st.caption(f"Model last trained: {health.get('model_trained_at')} · TMDB posters/reviews: {'on' if TMDB_ON else 'off (no key)'}")
    st.caption("Ratings you add change your own picks immediately. They join the movie-to-movie model when the backend retrains "
               "(on restart, or `POST /admin/retrain`).")
    footer()


def page_eval():
    st.title("📊 How good are the recommendations?")
    res = safe(get, "/evaluation")
    if not res:
        return
    k, hy = res["k"], "hybrid"
    p, rm, cov = res["precision_at_k"], res["rmse"], res["catalog_coverage"]
    st.markdown(f"**In short:** the Hybrid method finds about **{p[hy] / p['popularity']:.1f}×** as many movies you'd like as "
                f"simply recommending the most popular ones, and its star-rating guesses are off by about **{rm[hy]:.2f}** stars.")

    c1, c2, c3 = st.columns(3)
    c1.metric(f"Good picks in a list of {k}", f"{p[hy] * k:.1f}", help=f"Precision@{k} = {p[hy]:.3f}. Average number of movies "
              f"(out of {k} suggested) that the person really did rate 4★ or higher.")
    c2.metric("Rating guess is off by", f"{rm[hy]:.2f} ★", help="RMSE: the typical gap between the predicted and the real rating.")
    c3.metric("Share of movies ever suggested", f"{cov[hy] * 100:.0f}%", help="Catalog coverage: low = the same famous movies go to everyone.")

    with st.expander("🧪 How was this tested?", expanded=True):
        st.markdown(
            f"1. For each of {res['users_evaluated']} users we **hid 20% of their ratings**.\n"
            "2. Each method looked only at the other 80% and made its picks and guesses.\n"
            f"3. We then checked the hidden ratings: did the top-{k} picks contain movies the user rated **4★ or higher**? "
            "How close were the star guesses?\n\n"
            "It's like a student answering exam questions whose answers were hidden during studying.")

    names = {"popularity": "Popular movies only", "content": "Content-based", "cf": "Collaborative", "hybrid": "Hybrid (CineMatch)"}

    def bars(labels: dict, values: dict, higher_better: bool, fmt: str):
        df = pd.DataFrame({"Method": list(labels.values()), "Value": [values[k] for k in labels]})
        best = df["Value"].max() if higher_better else df["Value"].min()
        df["Best"] = df["Value"] == best
        base = alt.Chart(df).encode(y=alt.Y("Method:N", sort=None, title=None, axis=alt.Axis(labelLimit=320, labelPadding=8)))
        bar = base.mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("Value:Q", title=None, axis=None),
            color=alt.condition("datum.Best", alt.value("#2ecc71"), alt.value("#8a8f98")),
            tooltip=["Method", alt.Tooltip("Value:Q", format=fmt)])
        text = base.mark_text(align="left", dx=6, fontSize=13, fontWeight="bold").encode(
            x="Value:Q", text=alt.Text("Value:Q", format=fmt))
        st.altair_chart((bar + text).properties(height=36 * len(df)).configure_view(stroke=None)
                        .configure_axis(labelFontSize=13), width="stretch")

    st.subheader("Do the picks match what people like?")
    st.caption(f"Good picks per list of {k} (higher is better; green = best)")
    bars(names, {m: p[m] * k for m in names}, True, ".2f")

    st.subheader("How well are star ratings guessed?")
    st.caption("Average mistake in stars (lower is better; green = best).")
    rm_names = {"global_mean": "Guess 3.5 for everyone", "user_mean": "Guess each user's average",
                "bias_baseline": "Average + movie quality", "content": "Content-based", "cf": "Collaborative",
                "hybrid": "Hybrid (CineMatch)"}
    bars(rm_names, rm, False, ".2f")

    with st.expander("The numbers in detail"):
        detail = pd.DataFrame({
            "Method": [names[m] for m in names],
            f"Precision@{k}": [p[m] for m in names], f"Recall@{k}": [res["recall_at_k"][m] for m in names],
            "Coverage": [cov[m] for m in names]})
        st.dataframe(detail.style.format({c: "{:.3f}" for c in detail.columns[1:]}), hide_index=True, width="stretch")
        st.caption(f"**Recall@{k}**: of all the movies a user liked and we hid, the share that showed up in the top {k}. "
                   f"Hybrid settings picked on a separate validation split: collaborative weight {res['alpha']}, "
                   f"movie-quality weight {res['beta']}, popularity weight {res['gamma']}.")
    footer()


# ------------------------------------------------------------------ router + bottom navigation bar
PAGES = {"home": page_home, "foryou": page_for_you, "watchlist": page_watchlist, "ratings": page_my_ratings,
         "add": page_add, "movie": page_movie, "eval": page_eval, "settings": page_settings}
if ss.pop("scroll_top", False):      # Streamlit keeps the old scroll position; jump back to the top on a new page
    components.html("<script>const m=window.parent.document.querySelector('[data-testid=\"stMain\"]');"
                    "if(m){m.scrollTo(0,0);}</script>", height=0)
PAGES[ss.page]()

with st.container(key="bottom_nav"):
    cols = st.columns(len(NAV))
    for col, (key, icon, label) in zip(cols, NAV):
        col.button(f"{icon} {label}", key=f"nav_{key}", width="stretch", on_click=goto, args=(key,),
                   type="primary" if ss.page == key else "secondary")
