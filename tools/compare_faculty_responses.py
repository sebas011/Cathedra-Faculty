import argparse
import json
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.auth import password_hash


def request(base, path, token="", payload=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    with urllib.request.urlopen(
        urllib.request.Request(base + path, data=data, headers=headers), timeout=30
    ) as response:
        return json.load(response)


def capture(application: Path, source: Path, directory: Path):
    directory.mkdir(parents=True)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(directory / "cathedra.db")) as copy:
            original.backup(copy)
            password = secrets.token_urlsafe(32)
            copy.execute(
                "INSERT INTO local_users (username, password_hash, role, is_active, must_change_password, created_at) "
                "VALUES (?, ?, 'admin', 1, 0, CURRENT_TIMESTAMP)",
                ("isolated-comparison", password_hash(password)),
            )
            copy.commit()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}/api/v1"
    process = subprocess.Popen(
        [str(application), "--no-browser", "--port", str(port), "--data-dir", str(directory)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    token = ""
    try:
        for _attempt in range(120):
            try:
                request(base, "/health")
                break
            except (OSError, ValueError) as caught:
                if process.poll() is not None:
                    raise RuntimeError("Isolated application exited before readiness.") from caught
                time.sleep(0.25)
        else:
            raise TimeoutError("Isolated application did not become ready.")
        token = request(
            base,
            "/auth/login",
            payload={
                "username": "isolated-comparison",
                "password": password,
            },
        )["token"]
        paths = (
            "/faculty-profiles/page",
            "/workloads/page",
            "/workloads/summary",
            "/expenses/active-period",
            "/expenses/overload-budgets",
        )
        responses = {path: request(base, path, token) for path in paths}
        period = responses["/expenses/active-period"]
        projection_path = (
            "/expenses/monthly-projection?period=semester&academic_year="
            + urllib.parse.quote(period["academic_year"])
            + "&term="
            + urllib.parse.quote(period["term"])
        )
        responses["projection"] = request(base, projection_path, token)
        return responses
    finally:
        if token:
            try:
                request(base, "/desktop/exit", token, {})
            except OSError:
                pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)


def normalize(value):
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, str):
        return value.replace(", FSDP grants", "")
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-app", type=Path, required=True)
    parser.add_argument("--new-app", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--rehearsal-root", type=Path, required=True)
    args = parser.parse_args()
    previous = capture(args.old_app, args.source, args.rehearsal_root / "previous")
    current = capture(args.new_app, args.source, args.rehearsal_root / "current")
    if normalize(previous) != normalize(current):
        differences = [
            key for key in previous if normalize(previous[key]) != normalize(current[key])
        ]
        raise RuntimeError("Faculty responses changed: " + ", ".join(differences))
    print(json.dumps({"matched_responses": list(current), "calculations_unchanged": True}))
