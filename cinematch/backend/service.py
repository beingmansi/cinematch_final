"""Holds the trained recommender in memory (built from the SQLite data at start-up)."""
import threading
import time

from backend.database import db_is_loaded
from recommender.data_prep import clean, load_tables
from recommender.hybrid import Recommender


class RecService:
    def __init__(self):
        self.rec: Recommender | None = None
        self.movies = None
        self.trained_at = None
        self.lock = threading.Lock()

    def train(self):
        with self.lock:
            if not db_is_loaded():
                self.rec = None
                return False
            movies, ratings, tags = load_tables()
            movies, ratings = clean(movies, ratings)
            self.movies = movies
            self.rec = Recommender(movies, ratings, tags)
            self.trained_at = time.strftime("%Y-%m-%d %H:%M:%S")
            return True


service = RecService()
