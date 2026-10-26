"""The setup wrapper validates packages and delegates writes to the existing installer."""

import hashlib
import importlib.util
import io
import json
import stat
import uuid
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def setup():
    path = Path(__file__).resolve().parents[2] / "desktop/office_setup.py"
    spec = importlib.util.spec_from_file_location("cathedra_office_setup_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(name, content):
    return {"path": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def make_bundle(
    folder, *, app_extra=None, app_transform=None, wrapper_transform=None, zip_extra=()
):
    folder.mkdir(exist_ok=True)
    metadata = {
        "product": "faculty",
        "version": "0.3.7",
        "source_commit": "a" * 40,
        "release_tag": "v0.3.7-office.1",
        "build_identity": "0.3.7-" + "b" * 32,
        "source_snapshot_sha256": "c" * 64,
    }
    app = {
        "Cathedra Faculty.exe": b"MZ synthetic application; never executable",
        "_internal/VERSION": b"0.3.7\n",
        "_internal/APP_PRODUCT": b"faculty\n",
        "_internal/BUILD_ID": metadata["build_identity"].encode(),
        "_internal/frontend/dist/release-version.txt": b"0.3.7",
        "_internal/frontend/dist/build-id.txt": metadata["build_identity"].encode(),
        "_internal/backend/cathedra-seed.db": b"synthetic seed marker",
        "desktop/protect-local-folder.ps1": b"synthetic protector; never executed",
        "THIRD_PARTY_NOTICES.txt": b"Synthetic test notices",
    }
    app.update(app_extra or {})
    app_manifest = {
        key: metadata[key]
        for key in ("product", "version", "build_identity", "source_snapshot_sha256")
    }
    app_manifest["files"] = [record(name, value) for name, value in sorted(app.items())]
    if app_transform:
        app_transform(app_manifest)
    app["release-manifest.json"] = json.dumps(app_manifest).encode()
    files = {"Cathedra Faculty/" + name: content for name, content in app.items()}
    files.update(
        {
            "Install-Office.ps1": b"synthetic installer; never executed",
            "Install-or-Update.cmd": b"synthetic wrapper",
            "OFFICE-READ-ME.txt": b"synthetic readme",
        }
    )
    wrapper = {
        **metadata,
        "platform": "Windows-x64",
        "asset": "Cathedra-Faculty-0.3.7-Windows-x64.zip",
        "files": [record(name, content) for name, content in sorted(files.items())],
    }
    if wrapper_transform:
        wrapper_transform(wrapper)
    files["office-release-manifest.json"] = json.dumps(wrapper).encode()
    archive = folder / "office-package.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for name, content in files.items():
            package.writestr(name, content)
        for name, content, mode in zip_extra:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode
            package.writestr(info, content)
    for name, _content, _mode in zip_extra:
        if "\\" in name:
            archive.write_bytes(
                archive.read_bytes().replace(name.replace("\\", "/").encode(), name.encode())
            )
    metadata["zip_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    (folder / "setup-metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return metadata


def test_complete_bundle_verifies_without_extracting_or_executing(setup, tmp_path, monkeypatch):
    metadata = make_bundle(tmp_path)
    monkeypatch.setattr(
        setup.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("No process expected")
    )
    bundle = setup.verify_bundle(tmp_path)
    assert bundle.metadata == metadata
    assert bundle.file_count == 14
    assert set(tmp_path.iterdir()) == {
        tmp_path / "office-package.zip",
        tmp_path / "setup-metadata.json",
    }


def test_archive_checksum_mismatch_is_rejected(setup, tmp_path):
    make_bundle(tmp_path)
    with (tmp_path / "office-package.zip").open("ab") as output:
        output.write(b"changed")
    with pytest.raises(setup.SetupError, match="integrity"):
        setup.verify_bundle(tmp_path)


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "C:/escape",
        "Cathedra Faculty/CON.txt",
        "Cathedra Faculty/a\\b",
        "Cathedra Faculty/trailing. ",
    ],
)
def test_unsafe_archive_paths_rejected_before_extraction(setup, tmp_path, path):
    make_bundle(tmp_path, zip_extra=[(path, b"not trusted", 0)])
    with pytest.raises(setup.SetupError, match="unsafe Windows path"):
        setup.verify_bundle(tmp_path)
    assert not (tmp_path.parent / "escape").exists()


def test_case_collisions_and_symbolic_links_rejected(setup, tmp_path):
    first = tmp_path / "collision"
    make_bundle(first, zip_extra=[("CATHEDRA FACULTY/_internal/version", b"collision", 0)])
    with pytest.raises(setup.SetupError, match="duplicate"):
        setup.verify_bundle(first)
    second = tmp_path / "link"
    make_bundle(
        second, zip_extra=[("Cathedra Faculty/link", b"../escape", (stat.S_IFLNK | 0o777) << 16)]
    )
    with pytest.raises(setup.SetupError, match="unsafe"):
        setup.verify_bundle(second)


def test_explicit_directory_cannot_have_a_file_ancestor(setup, tmp_path):
    make_bundle(
        tmp_path,
        zip_extra=[
            ("Cathedra Faculty/plain", b"file", 0),
            ("Cathedra Faculty/plain/nested/", b"", (stat.S_IFDIR | 0o755) << 16),
        ],
    )
    with pytest.raises(setup.SetupError, match="conflicting file and folder"):
        setup.verify_bundle(tmp_path)


def test_package_identity_cannot_be_changed_independently(setup, tmp_path):
    make_bundle(tmp_path, wrapper_transform=lambda wrapper: wrapper.update(source_commit="d" * 40))
    with pytest.raises(setup.SetupError, match="identity"):
        setup.verify_bundle(tmp_path)


def test_outer_inventory_must_cover_exact_files(setup, tmp_path):
    make_bundle(tmp_path, wrapper_transform=lambda wrapper: wrapper["files"].pop())
    with pytest.raises(setup.SetupError, match="inventory"):
        setup.verify_bundle(tmp_path)


def test_nested_application_inventory_must_match_office_wrapper(setup, tmp_path):
    make_bundle(
        tmp_path, app_transform=lambda manifest: manifest["files"][0].update(sha256="0" * 64)
    )
    with pytest.raises(setup.SetupError, match="inventories disagree"):
        setup.verify_bundle(tmp_path)


def test_identity_resources_and_runtime_databases_are_checked(setup, tmp_path):
    first = tmp_path / "wrong-version"
    make_bundle(first, app_extra={"_internal/VERSION": b"0.3.2"})
    with pytest.raises(setup.SetupError, match="resource identity"):
        setup.verify_bundle(first)
    second = tmp_path / "private-records"
    make_bundle(second, app_extra={"data/cathedra.db": b"private records must never ship"})
    with pytest.raises(setup.SetupError, match="Runtime records"):
        setup.verify_bundle(second)


def test_archive_limits_apply_even_when_outer_digest_matches(setup, tmp_path, monkeypatch):
    make_bundle(tmp_path)
    monkeypatch.setattr(setup, "MAX_TOTAL_BYTES", 10)
    with pytest.raises(setup.SetupError, match="too large"):
        setup.verify_bundle(tmp_path)


def test_manifest_sizes_cannot_be_booleans(setup, tmp_path):
    make_bundle(tmp_path, wrapper_transform=lambda wrapper: wrapper["files"][0].update(bytes=True))
    with pytest.raises(setup.SetupError, match="inventory"):
        setup.verify_bundle(tmp_path)


def test_smoke_target_guard_requires_disposable_account_temp_folder(setup, tmp_path):
    profile = tmp_path / "profile"
    temporary = profile / "AppData/Local/Temp"
    temporary.mkdir(parents=True)
    valid = temporary / ("cathedra-installer-test-" + uuid.uuid4().hex) / "synthetic office"
    assert setup.smoke_install_target(valid, profile, temporary) == valid
    for invalid in (
        profile / "Cathedra-Faculty",
        temporary / "ordinary-folder/office",
        tmp_path / valid.parent.name / "office",
    ):
        with pytest.raises(setup.SetupError, match="disposable"):
            setup.smoke_install_target(invalid, profile, temporary)


def test_normal_and_smoke_commands_delegate_without_force_stopping_app(setup, tmp_path):
    normal = setup.installer_command(tmp_path / "package", tmp_path / "office")
    assert normal[-2:] == ["-InstallFolder", str(tmp_path / "office")]
    assert "-TestMode" not in normal and "-NoLaunch" not in normal
    smoke = setup.installer_command(
        tmp_path / "package", tmp_path / "office", smoke=True, no_launch=True
    )
    assert smoke[-2:] == ["-NoLaunch", "-TestMode"]
    assert all(
        "taskkill" not in item.lower() and "stop-process" not in item.lower() for item in normal
    )
    with pytest.raises(setup.SetupError, match="must not launch"):
        setup.installer_command(tmp_path, tmp_path, smoke=True)


def test_verification_cli_writes_receipt_and_never_installs(setup, tmp_path, monkeypatch):
    resources = tmp_path / "resources"
    metadata = make_bundle(resources)
    monkeypatch.setattr(setup, "resource_directory", lambda: resources)
    monkeypatch.setattr(
        setup, "install_bundle", lambda *args, **kwargs: pytest.fail("No install expected")
    )
    receipt = tmp_path / "result.json"
    assert setup.main(["--verify-bundle", "--receipt", str(receipt)]) == 0
    result = json.loads(receipt.read_text())
    assert result["status"] == "ok" and result["build_identity"] == metadata["build_identity"]
    assert result["zip_sha256"] == metadata["zip_sha256"]
    assert result["private_backup"] is None


def test_gui_verification_dispatches_read_only_and_records_identity(setup, tmp_path, monkeypatch):
    resources = tmp_path / "resources"
    metadata = make_bundle(resources)
    monkeypatch.setattr(setup, "resource_directory", lambda: resources)
    monkeypatch.setattr(
        setup, "install_bundle", lambda *args, **kwargs: pytest.fail("No install expected")
    )
    calls = []

    def gui(*, verify=False):
        calls.append(verify)
        return {"gui_constructed": True, "gui_controls_fit": True, "install_attempted": False}

    monkeypatch.setattr(setup, "show_gui", gui)
    receipt = tmp_path / "gui.json"
    assert setup.main(["--verify-gui", "--receipt", str(receipt)]) == 0
    result = json.loads(receipt.read_text())
    assert calls == [True]
    assert result["status"] == "ok" and result["gui_constructed"]
    assert result["install_attempted"] is False and result["gui_controls_fit"]
    assert result["build_identity"] == metadata["build_identity"]
    assert result["zip_sha256"] == metadata["zip_sha256"]


@pytest.mark.parametrize("extra", [["--no-launch"], ["--install-folder", "C:/live-office"]])
def test_gui_verification_rejects_install_options_before_bundle_read(
    setup, tmp_path, monkeypatch, extra
):
    monkeypatch.setattr(setup, "verify_bundle", lambda: pytest.fail("Guard must run first"))
    monkeypatch.setattr(setup, "show_gui", lambda **kwargs: pytest.fail("No GUI expected"))
    receipt = tmp_path / "gui-error.json"
    assert setup.main(["--verify-gui", "--receipt", str(receipt), *extra]) == 1
    assert json.loads(receipt.read_text())["status"] == "error"


def test_gui_runtime_failure_cannot_produce_a_success_receipt(setup, tmp_path, monkeypatch):
    resources = tmp_path / "resources"
    make_bundle(resources)
    monkeypatch.setattr(setup, "resource_directory", lambda: resources)

    def unavailable_gui(**kwargs):
        raise RuntimeError("Tk runtime unavailable")

    monkeypatch.setattr(setup, "show_gui", unavailable_gui)
    receipt = tmp_path / "gui-unavailable.json"
    assert setup.main(["--verify-gui", "--receipt", str(receipt)]) == 1
    result = json.loads(receipt.read_text())
    assert result["status"] == "error" and "Tk runtime unavailable" in result["error"]


def test_smoke_cli_refuses_live_install_target_before_bundle_read(setup, tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    temporary = profile / "AppData/Local/Temp"
    temporary.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("LOCALAPPDATA", str(profile / "AppData/Local"))
    monkeypatch.setattr(setup, "verify_bundle", lambda: pytest.fail("Guard must run first"))
    receipt = tmp_path / "error.json"
    assert (
        setup.main(
            [
                "--smoke-install",
                "--install-folder",
                str(profile / "Cathedra-Faculty"),
                "--no-launch",
                "--receipt",
                str(receipt),
            ]
        )
        == 1
    )
    assert json.loads(receipt.read_text())["status"] == "error"
    assert not (profile / "Cathedra-Faculty").exists()


def test_cli_receipt_never_overwrites_existing_file(setup, tmp_path):
    receipt = tmp_path / "existing.db"
    receipt.write_bytes(b"existing records")
    assert setup.main(["--verify-bundle", "--receipt", str(receipt)]) == 1
    assert receipt.read_bytes() == b"existing records"


def test_installer_failure_preserves_log_and_existing_data(setup, tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    temporary = profile / "AppData/Local/Temp"
    temporary.mkdir(parents=True)
    target = profile / "Cathedra-Faculty/data"
    target.mkdir(parents=True)
    (target / "cathedra.db").write_bytes(b"saved office records")
    resources = tmp_path / "resources"
    make_bundle(resources)
    bundle = setup.verify_bundle(resources)
    work = temporary / ("cathedra-setup-" + uuid.uuid4().hex)
    package = work / "package"
    package.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("LOCALAPPDATA", str(profile / "AppData/Local"))
    monkeypatch.setattr(setup, "_private_work_folder", lambda *args: (work, package))

    class Process:
        stdout = io.StringIO(
            "Installation stopped: Cathedra Faculty is running. Save and close it.\n"
        )
        returncode = 1

        def wait(self):
            return self.returncode

    monkeypatch.setattr(setup, "_start_process", lambda *args, **kwargs: Process())
    with pytest.raises(setup.InstallerError) as error:
        setup.install_bundle(bundle)
    assert error.value.log_path.is_file() and "running" in error.value.output
    assert (target / "cathedra.db").read_bytes() == b"saved office records"
