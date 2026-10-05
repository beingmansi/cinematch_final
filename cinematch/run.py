"""One-command launcher:  python run.py

1. loads MovieLens into SQLite on first run (data/ml-latest-small, or downloads it)
2. starts the FastAPI backend (http://127.0.0.1:8000, docs at /docs)
3. starts the Streamlit frontend (http://localhost:8501)
Press Ctrl+C to stop both.   Use `python run.py --headless` to skip opening a browser.
"""
import subprocess
import sys
import time

import requests

import config
from backend.database import db_is_loaded, init_db


def wait_for_api(timeout=90):
    s = requests.Session(); s.trust_env = False
    for _ in range(timeout):
        try:
            if s.get(f"{config.API_URL}/health", timeout=2).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def main():
    headless = "--headless" in sys.argv
    init_db()
    if not db_is_loaded():
        print("First run: loading MovieLens into the database ...")
        from data.load_movielens import main as load_data
        try:
            load_data()
        except Exception as e:   # noqa: BLE001
            sys.exit(f"Could not load data: {e}\nPut the unzipped 'ml-latest-small' folder inside the data/ folder and retry.")
    if not config.EVAL_PATH.exists():
        print("Tip: run `python -m recommender.evaluate` once to fill the 'Model Evaluation' page.")

    print("Starting backend ...")
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app",
                            "--host", config.API_HOST, "--port", str(config.API_PORT)])
    ui = None
    try:
        if not wait_for_api():
            sys.exit("Backend did not start. Check the messages above.")
        print(f"Backend ready: {config.API_URL}/docs\nStarting Streamlit ...")
        cmd = [sys.executable, "-m", "streamlit", "run", "frontend/app.py", "--server.port", "8501"]
        if headless:
            cmd += ["--server.headless", "true"]
        ui = subprocess.Popen(cmd)
        ui.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in (ui, api):
            if p and p.poll() is None:
                p.terminate()
        print("Stopped.")


if __name__ == "__main__":
    main()
