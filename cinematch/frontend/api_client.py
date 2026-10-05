"""Thin wrapper around the FastAPI backend."""
import os

import requests

API_URL = os.getenv("CINEMATCH_API_URL",
                    f"http://{os.getenv('CINEMATCH_API_HOST', '127.0.0.1')}:{os.getenv('CINEMATCH_API_PORT', '8000')}")


# The backend runs on this machine, so never route these calls through an HTTP(S) proxy.
_session = requests.Session()
_session.trust_env = False


class APIError(Exception):
    pass


def call(method: str, path: str, **kwargs):
    try:
        r = _session.request(method, API_URL + path, timeout=60, **kwargs)
    except requests.RequestException:
        raise APIError("Cannot reach the CineMatch backend. Start it with: uvicorn backend.main:app")
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text
        if isinstance(detail, list):   # pydantic validation errors
            detail = "; ".join(d.get("msg", "invalid input") for d in detail)
        raise APIError(str(detail))
    return r.json()


def get(path, **params):
    return call("GET", path, params={k: v for k, v in params.items() if v not in (None, "")})


def post(path, payload):
    return call("POST", path, json=payload)


def delete(path):
    return call("DELETE", path)
