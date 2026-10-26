"""Exercise the actual one-file setup on synthetic folders with no developer PATH."""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import closing
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in folder.rglob("*") if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-folder", required=True, type=Path)
    args = parser.parse_args()
    folder = args.download_folder.resolve(strict=True)
    setup = folder / "Cathedra-Faculty-Setup.exe"
    assert (folder / (setup.name + ".sha256")).read_text().strip() == f"{sha(setup)}  {setup.name}"
    wrapper = json.loads((folder / "office-release-manifest.json").read_text(encoding="utf-8-sig"))
    zip_hash = sha(folder / wrapper["asset"])
    profile = Path(os.environ["USERPROFILE"]).resolve(strict=True)
    temporary = (Path(os.environ["LOCALAPPDATA"]) / "Temp").resolve(strict=True)
    assert temporary.is_relative_to(profile)
    fixture = temporary / ("cathedra-installer-test-" + uuid.uuid4().hex)
    fixture.mkdir()
    install = fixture / "office application with spaces-é"
    environment = {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(("CATHEDRA_", "PYTHON", "VIRTUAL_ENV"))
    }
    windows = Path(os.environ["SystemRoot"])
    environment["PATH"] = ";".join(
        str(windows / part) for part in ("System32", ".", "System32/WindowsPowerShell/v1.0")
    )
    environment["PSModulePath"] = str(windows / "System32/WindowsPowerShell/v1.0/Modules")

    def run(mode, target):
        receipt = fixture / (mode.lstrip("-") + "-" + uuid.uuid4().hex + ".json")
        command = [str(setup), mode, "--receipt", str(receipt)]
        if target:
            command += ["--install-folder", str(target), "--no-launch"]
        outcome = subprocess.run(
            command,
            check=False,
            cwd=fixture,
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=360,
        )
        if outcome.returncode or not receipt.is_file():
            detail = (
                receipt.read_text(encoding="utf-8-sig")
                if receipt.is_file()
                else "No receipt was written."
            )
            raise AssertionError(f"Setup CLI failed: {mode} ({outcome.returncode}) {detail}")
        result = json.loads(receipt.read_text(encoding="utf-8-sig"))
        assert result["status"] == "ok"
        assert result["version"] == wrapper["version"]
        assert result["build_identity"] == wrapper["build_identity"]
        assert result["source_commit"] == wrapper["source_commit"]
        assert result["zip_sha256"] == zip_hash
        return result

    try:
        run("--verify-bundle", None)
        gui = run("--verify-gui", None)
        assert gui["gui_constructed"] is True
        assert gui["gui_controls_fit"] is True
        assert gui["install_attempted"] is False
        first = run("--smoke-install", install)
        assert first.get("private_backup") is None
        assert (install / "Cathedra Faculty.exe").is_file()
        assert not (install / "data").exists()
        data = install / "data"
        data.mkdir()
        with closing(sqlite3.connect(data / "cathedra.db")) as database:
            database.execute(
                "CREATE TABLE setup_test_records (id INTEGER PRIMARY KEY, note TEXT NOT NULL)"
            )
            database.execute(
                "INSERT INTO setup_test_records VALUES (1, ?)",
                ("Synthetic update record",),
            )
            database.commit()
        (data / "attachments").mkdir()
        (data / "attachments/fixture.txt").write_text("Synthetic attachment", encoding="utf-8")
        (data / "empty-folder").mkdir()
        before = tree(data)
        # A second run exercises update + complete private backup, not only extraction.
        second = run("--smoke-install", install)
        assert tree(data) == before
        assert (data / "empty-folder").is_dir()
        backup = Path(second["private_backup"]).resolve(strict=True)
        assert backup.is_relative_to(fixture) and backup != install
        backup_data = tree(backup / "data")
        # The installer creates a zero-byte guard before taking its complete
        # recovery copy, then removes only that newly created guard from live data.
        assert set(backup_data) == set(before) | {".cathedra.lock"}
        assert backup_data[".cathedra.lock"] == hashlib.sha256(b"").hexdigest()
        assert {name: value for name, value in backup_data.items() if name in before} == before
        assert (backup / "data/empty-folder").is_dir()
        assert (backup / "release-manifest.json").is_file()
        assert (
            json.loads((install / "release-manifest.json").read_text(encoding="utf-8-sig"))[
                "build_identity"
            ]
            == wrapper["build_identity"]
        )
        print(
            json.dumps(
                {
                    "single_file_bundle_verified": True,
                    "setup_window_verified": True,
                    "fresh_install": True,
                    "update_and_private_backup": True,
                    "data_hashes_preserved": True,
                    "developer_tools_not_on_path": True,
                    "version": wrapper["version"],
                    "build_identity": wrapper["build_identity"],
                },
                indent=2,
            )
        )
    finally:
        resolved = fixture.resolve()
        assert resolved.parent == temporary and re.fullmatch(
            r"cathedra-installer-test-[a-f0-9]{32}", resolved.name
        )
        assert not any(p.is_symlink() or p.is_junction() for p in resolved.rglob("*"))
        shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
