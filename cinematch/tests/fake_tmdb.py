"""A tiny fake TMDB server so the real HTTP code path can be tested without internet or a key."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

GOOD_KEY = "k" * 32
REQUESTS: list[str] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        auth_ok = q.get("api_key", [""])[0] == GOOD_KEY or self.headers.get("Authorization", "") == "Bearer " + "t" * 60
        if not auth_ok:
            return self._send(401, {"status_code": 7})
        REQUESTS.append(u.path)
        m = re.fullmatch(r"/3/movie/(\d+)/reviews", u.path)
        if m:
            tid = int(m.group(1))
            if tid == 862:   # Toy Story has reviews
                return self._send(200, {"results": [
                    {"author": "film_fan", "content": "A delight from start to finish.", "created_at": "2020-01-02T10:00:00Z",
                     "author_details": {"rating": 9}},
                    {"author": "grumpy", "content": "Fine, but overrated.", "created_at": "2021-03-04T10:00:00Z",
                     "author_details": {"rating": None}}]})
            return self._send(200, {"results": []})
        m = re.fullmatch(r"/3/movie/(\d+)", u.path)
        if m:
            tid = int(m.group(1))
            if tid == 404404:
                return self._send(404, {"status_code": 34})
            return self._send(200, {
                "id": tid, "title": f"Fake Movie {tid}", "poster_path": f"/poster{tid}.jpg", "overview": f"Overview of {tid}.",
                "release_date": "2024-05-01", "imdb_id": "tt7654321",
                "genres": [{"name": "Science Fiction"}, {"name": "History"}, {"name": "Thriller"}, {"name": "Family"}]})
        if u.path == "/3/search/movie":
            return self._send(200, {"results": [
                {"id": 900001, "title": "Brand New Film", "release_date": "2025-01-01", "overview": "Fresh.", "poster_path": "/new.jpg"},
                {"id": 862, "title": "Toy Story", "release_date": "1995-10-30", "overview": "Toys.", "poster_path": "/ts.jpg"}]})
        self._send(404, {})


def start():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/3"
