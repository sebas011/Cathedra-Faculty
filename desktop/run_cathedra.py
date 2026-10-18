"""Cathedra's Windows desktop launcher entry point for PyInstaller."""

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

_product_file = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "APP_PRODUCT"
PRODUCT = "faculty"
if _product_file.exists() and _product_file.read_text(encoding="utf-8").strip() != PRODUCT:
    raise RuntimeError("Invalid Cathedra Faculty product configuration.")
APP_NAME = "Cathedra Faculty"
DEFAULT_PORT = 8102


def resource_path(*parts: str) -> Path:
    """Find a file from either a PyInstaller bundle or the source checkout."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root.joinpath(*parts)


def writable_data_directory(override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    root = (
        Path(sys.executable).parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    return root / "data"


def prepare_data_directory(data_directory: Path) -> None:
    data_directory.mkdir(parents=True, exist_ok=True)
    active_database = data_directory / "cathedra.db"
    if active_database.exists():
        return
    bundled_database = resource_path("backend", "cathedra-seed.db")
    if not bundled_database.exists():
        raise RuntimeError("The bundled Cathedra database could not be found.")
    shutil.copy2(bundled_database, active_database)


def lock_data_directory(data_directory: Path):
    data_directory.mkdir(parents=True, exist_ok=True)
    lock_file = (data_directory / ".cathedra.lock").open("a+b")
    try:
        if lock_file.seek(0, os.SEEK_END) == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as caught:
        lock_file.close()
        raise RuntimeError(
            "This Cathedra data folder is already open in another app process."
        ) from caught
    return lock_file


def bundled_release_version() -> str:
    try:
        return resource_path("VERSION").read_text(encoding="utf-8").strip() or "development"
    except OSError:
        return "development"


def bundled_build_identity() -> str:
    path = resource_path("BUILD_ID")
    return path.read_text(encoding="utf-8").strip() if path.exists() else "development"


def service_is_ready(port: int, expected_version: str, data_directory: Path) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/health", timeout=1
        ) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            directory_identity = hashlib.sha256(
                str(data_directory.resolve()).casefold().encode("utf-8")
            ).hexdigest()[:16]
            return (
                payload.get("status") == "ok"
                and payload.get("release_version") == expected_version
                and payload.get("build_identity", "development") == bundled_build_identity()
                and payload.get("data_directory_identity") == directory_identity
                and payload.get("product") == PRODUCT
            )
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def wait_for_service(
    port: int, expected_version: str, data_directory: Path, timeout_seconds: int = 20
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if service_is_ready(port, expected_version, data_directory):
            return True
        time.sleep(0.25)
    return False


def port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def show_error(message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    else:
        print(message, file=sys.stderr)


def write_startup_error(message: str) -> None:
    data_directory = Path(os.environ.get("CATHEDRA_DATA_DIR", writable_data_directory(None)))
    try:
        data_directory.mkdir(parents=True, exist_ok=True)
        (data_directory / "launcher-error.log").write_text(message, encoding="utf-8")
    except OSError:
        pass


def open_app_window(url: str, data_directory: Path | None = None) -> subprocess.Popen | None:
    edge_locations = [
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
    ]
    edge = next((candidate for candidate in edge_locations if candidate.exists()), None)
    if edge:
        arguments = [str(edge), f"--app={url}", "--new-window"]
        if data_directory is not None:
            arguments.extend(
                [
                    f"--user-data-dir={data_directory / 'edge-profile'}",
                    "--disable-background-mode",
                    "--no-first-run",
                ]
            )
        return subprocess.Popen(arguments)
    else:
        webbrowser.open_new(url)
        return None


def setup_entry_url(data_directory: Path, default_url: str) -> str:
    entries = list(data_directory.glob(".setup-*/start.html"))
    if not entries:
        return default_url
    # Only the private file's URI is passed to the browser process, never its key.
    return max(entries, key=lambda entry: entry.stat().st_mtime_ns).resolve().as_uri()


def watch_app_window(window: subprocess.Popen, shutdown_signal: threading.Event) -> None:
    started = time.monotonic()
    window.wait()
    if time.monotonic() - started >= 5:
        shutdown_signal.set()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch Cathedra as a local desktop application.")
    parser.add_argument("--data-dir", help="Override the writable Cathedra data folder.")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="Local-only port for the Cathedra service."
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start the local service without opening a window.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    data_directory = writable_data_directory(arguments.data_dir)
    if getattr(sys, "frozen", False) and os.name == "nt":
        security_script = Path(sys.executable).parent / "desktop" / "protect-local-folder.ps1"
        if not security_script.is_file():
            raise RuntimeError(
                "The Windows folder-protection tool is missing. Recopy the complete Faculty release."
            )
        data_directory.mkdir(parents=True, exist_ok=True)
        application_directory = Path(sys.executable).parent.resolve()
        targets = [application_directory]
        if application_directory not in data_directory.resolve().parents:
            targets.append(data_directory.resolve())
        for target in targets:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
            try:
                result = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(security_script),
                        "-Folder",
                        str(target),
                    ],
                    capture_output=True,
                    stdin=subprocess.DEVNULL,
                    env={
                        **os.environ,
                        "PSModulePath": str(
                            Path(os.environ.get("SystemRoot", "C:/Windows"))
                            / "System32"
                            / "WindowsPowerShell"
                            / "v1.0"
                            / "Modules"
                        ),
                    },
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=120,
                    check=False,
                )
            finally:
                ctypes.windll.kernel32.SetDllDirectoryW(str(sys._MEIPASS))
            if result.returncode != 0:
                raise RuntimeError(
                    f"Windows folder protection failed (helper exit {result.returncode}). Run desktop/Prepare-Office-Copy.cmd as the Windows account that will use Faculty."
                )
    version = bundled_release_version()
    identity = bundled_build_identity()
    frontend_identity = resource_path("frontend", "dist", "build-id.txt")
    if identity != "development" and (
        not frontend_identity.exists()
        or frontend_identity.read_text(encoding="utf-8").strip() != identity
    ):
        raise RuntimeError(
            "The application and screen assets belong to different builds. Restore a complete verified release folder."
        )
    os.environ["CATHEDRA_DATA_DIR"] = str(data_directory)
    os.environ["CATHEDRA_PRODUCT"] = PRODUCT
    os.environ["CATHEDRA_FRONTEND_DIST"] = str(resource_path("frontend", "dist"))
    os.environ["CATHEDRA_RELEASE_VERSION"] = version
    os.environ["CATHEDRA_BUILD_ID"] = identity
    backend_root = resource_path("backend")
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    url = f"http://127.0.0.1:{arguments.port}"
    os.environ["CATHEDRA_SETUP_ORIGIN"] = url
    if service_is_ready(arguments.port, version, data_directory):
        if not arguments.no_browser:
            open_app_window(setup_entry_url(data_directory, url), data_directory)
        return
    if not port_is_available(arguments.port):
        show_error(
            f"Port {arguments.port} is being used by a different Cathedra version or data folder. "
            "Close that service or choose a different port."
        )
        raise SystemExit(1)

    data_lock = lock_data_directory(data_directory)
    prepare_data_directory(data_directory)
    from app.local_logging import configure_local_logging

    configure_local_logging(data_directory)

    import uvicorn
    from app.main import app

    shutdown_signal = threading.Event()
    app.state.shutdown_signal = shutdown_signal
    configuration = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=arguments.port,
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(configuration)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    if not wait_for_service(arguments.port, version, data_directory):
        show_error("Cathedra could not start its local service.")
        raise SystemExit(1)

    if not arguments.no_browser:
        capability = app.state.setup_capability
        entry_url = capability.entry_path.as_uri() if capability is not None else url
        window = open_app_window(entry_url, data_directory)
        if window is not None:
            threading.Thread(
                target=watch_app_window, args=(window, shutdown_signal), daemon=True
            ).start()
    try:
        shutdown_signal.wait()
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
        data_lock.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as caught:
        message = f"Cathedra could not start.\n\n{caught}"
        write_startup_error(message)
        show_error(message)
        raise
