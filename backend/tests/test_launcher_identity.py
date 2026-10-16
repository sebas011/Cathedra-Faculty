import hashlib
import importlib.util
import json
import threading
from pathlib import Path

import pytest


def launcher_module():
    path = Path(__file__).resolve().parents[2] / "desktop" / "run_cathedra.py"
    spec = importlib.util.spec_from_file_location("cathedra_launcher_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_reuses_only_matching_version_and_data_folder(monkeypatch, tmp_path: Path) -> None:
    launcher = launcher_module()
    office_directory = tmp_path / "office"
    office_directory.mkdir()
    other_directory = tmp_path / "other"
    other_directory.mkdir()
    identity = hashlib.sha256(
        str(office_directory.resolve()).casefold().encode("utf-8")
    ).hexdigest()[:16]

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps(
                {
                    "status": "ok",
                    "product": "faculty",
                    "release_version": "test",
                    "build_identity": "test-build",
                    "data_directory_identity": identity,
                }
            ).encode("utf-8")

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    monkeypatch.setattr(launcher, "bundled_build_identity", lambda: "test-build")
    assert launcher.service_is_ready(8100, "test", office_directory)
    assert not launcher.service_is_ready(8100, "other", office_directory)
    assert not launcher.service_is_ready(8100, "test", other_directory)
    monkeypatch.setattr(launcher, "bundled_build_identity", lambda: "different-build")
    assert not launcher.service_is_ready(8100, "test", office_directory)


def test_launcher_rejects_second_process_on_same_data_folder(tmp_path: Path) -> None:
    launcher = launcher_module()
    data_directory = tmp_path / "office"
    first_lock = launcher.lock_data_directory(data_directory)
    try:
        with pytest.raises(RuntimeError, match="already open"):
            launcher.lock_data_directory(data_directory)
    finally:
        first_lock.close()
    second_lock = launcher.lock_data_directory(data_directory)
    second_lock.close()


def test_setup_reuses_private_file_uri_and_returns_to_normal_url(tmp_path: Path) -> None:
    launcher = launcher_module()
    from app.bootstrap import SetupCapability

    capability = SetupCapability(tmp_path, "http://127.0.0.1:18181")
    try:
        url = launcher.setup_entry_url(tmp_path, "http://127.0.0.1:18181")
        assert url == capability.entry_path.as_uri()
        assert "setup-key" not in url and "#" not in url
    finally:
        capability.consume()
    assert launcher.setup_entry_url(tmp_path, "http://127.0.0.1:18181") == "http://127.0.0.1:18181"


def test_exit_requires_packaged_shutdown_signal(client) -> None:
    from app.main import app

    assert client.post("/api/v1/desktop/exit").status_code == 409
    shutdown_signal = threading.Event()
    app.state.shutdown_signal = shutdown_signal
    try:
        assert client.post("/api/v1/desktop/exit").json() == {"status": "closing"}
        assert shutdown_signal.is_set()
    finally:
        del app.state.shutdown_signal


def test_window_close_stops_service_after_established_session(monkeypatch) -> None:
    launcher = launcher_module()
    shutdown_signal = threading.Event()

    class Window:
        def wait(self):
            return 0

    times = iter((0.0, 20.0))
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(times))
    launcher.watch_app_window(Window(), shutdown_signal)
    assert shutdown_signal.is_set()


def test_immediate_window_handoff_does_not_stop_service(monkeypatch) -> None:
    launcher = launcher_module()
    shutdown_signal = threading.Event()

    class Window:
        def wait(self):
            return 0

    times = iter((0.0, 0.1))
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(times))
    launcher.watch_app_window(Window(), shutdown_signal)
    assert not shutdown_signal.is_set()
