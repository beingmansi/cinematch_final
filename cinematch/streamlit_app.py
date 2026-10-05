"""Single entry point for deployment (e.g. Streamlit Community Cloud) and for `streamlit run streamlit_app.py`.

Hosts like Streamlit Community Cloud run ONE program, but CineMatch is a FastAPI backend + a Streamlit frontend.
This file starts the backend inside the same process (in a background thread, once), makes sure the database
exists, and then runs the normal Streamlit app in frontend/app.py.
Locally you can still use `python run.py` (two separate processes) – both work.
"""
import os
import runpy
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st

st.set_page_config(page_title="CineMatch", page_icon="🎬", layout="wide")


@st.cache_resource(show_spinner="Starting CineMatch… the very first start takes about 30 seconds.")
def start_backend():
    import requests
    import uvicorn

    import config
    from backend.database import db_is_loaded, init_db

    init_db()
    if not db_is_loaded():
        from data.load_movielens import main as load_data
        load_data()
    os.environ.setdefault("CINEMATCH_API_URL", config.API_URL)

    from backend.main import app
    server = uvicorn.Server(uvicorn.Config(app, host=config.API_HOST, port=config.API_PORT, log_level="warning"))
    server.install_signal_handlers = lambda: None      # not allowed outside the main thread
    threading.Thread(target=server.run, daemon=True).start()

    session = requests.Session()
    session.trust_env = False
    for _ in range(120):
        try:
            if session.get(f"{config.API_URL}/health", timeout=2).json().get("status") == "ok":
                return server
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("The CineMatch backend did not start in time.")


start_backend()
runpy.run_path(str(ROOT / "frontend" / "app.py"), run_name="__main__")
