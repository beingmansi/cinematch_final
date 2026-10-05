"""OPTIONAL: fill the app with clearly-labelled SAMPLE reviews so the review pages are not empty in a demo.

    python -m data.seed_demo            add sample reviews to the 40 most-rated movies
    python -m data.seed_demo --remove   remove them again

The reviews are generic placeholder text written by users whose names start with "sample_"
(the app shows a "sample review" tag next to them). They are NOT real opinions - do not present them as such.
No ratings are created, so the recommender is unaffected.
"""
import random
import sys

from backend.database import get_conn, init_db

AUTHORS = ["sample_alex", "sample_riya", "sample_sam", "sample_maya", "sample_dev", "sample_zoe"]
TEXTS = [
    "Sample review: great pacing and a cast that clearly cared. Would watch again.",
    "Sample review: a few slow moments, but the ending makes up for it.",
    "Sample review: looks fantastic and the music fits perfectly.",
    "Sample review: not my favourite, but I can see why people love it.",
    "Sample review: easy to recommend to friends - fun from start to finish.",
    "Sample review: the story stayed with me for days after watching.",
    "Sample review: solid movie night pick, nothing more and nothing less.",
    "Sample review: the characters are the best part - really well written.",
]


def seed(n_movies=40, seed_value=7):
    init_db()
    rng = random.Random(seed_value)
    with get_conn() as conn:
        if conn.execute("SELECT COUNT(*) FROM users WHERE username LIKE 'sample\\_%' ESCAPE '\\'").fetchone()[0]:
            print("Sample reviews already present. Use --remove first to recreate them.")
            return 0
        ids = {}
        for a in AUTHORS:
            cur = conn.execute("INSERT INTO users(username) VALUES (?)", (a,))
            ids[a] = cur.lastrowid
        top = [r[0] for r in conn.execute(
            "SELECT movie_id FROM ratings GROUP BY movie_id ORDER BY COUNT(*) DESC LIMIT ?", (n_movies,))]
        count = 0
        for mid in top:
            for a in rng.sample(AUTHORS, rng.randint(1, 3)):
                conn.execute("INSERT INTO reviews(user_id, movie_id, text) VALUES (?,?,?)",
                             (ids[a], mid, rng.choice(TEXTS)))
                count += 1
    print(f"Added {count} sample reviews on {len(top)} movies.")
    return count


def remove():
    with get_conn() as conn:
        ids = [r[0] for r in conn.execute("SELECT user_id FROM users WHERE username LIKE 'sample\\_%' ESCAPE '\\'")]
        for i in ids:
            conn.execute("DELETE FROM reviews WHERE user_id=?", (i,))
            conn.execute("DELETE FROM users WHERE user_id=?", (i,))
    print(f"Removed sample accounts and their reviews ({len(ids)} accounts).")


if __name__ == "__main__":
    remove() if "--remove" in sys.argv else seed()
