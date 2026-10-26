"""A small offline setup window around the verified Windows office installer.

The frozen executable embeds office-package.zip and setup-metadata.json. It never
downloads code and never replaces application files itself: Install-Office.ps1
owns verification of an existing installation, recovery backup and rollback.
"""

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path

APPLICATION = "Cathedra Faculty"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_FILES = 4096
MAX_JSON_BYTES = 2 * 1024 * 1024
IDENTITY_FIELDS = (
    "product",
    "version",
    "source_commit",
    "release_tag",
    "build_identity",
    "source_snapshot_sha256",
)
COMPANIONS = {"Install-Office.ps1", "Install-or-Update.cmd", "OFFICE-READ-ME.txt"}
REQUIRED_APP_FILES = {
    "Cathedra Faculty.exe",
    "_internal/VERSION",
    "_internal/APP_PRODUCT",
    "_internal/BUILD_ID",
    "_internal/frontend/dist/release-version.txt",
    "_internal/frontend/dist/build-id.txt",
    "_internal/backend/cathedra-seed.db",
    "desktop/protect-local-folder.ps1",
    "THIRD_PARTY_NOTICES.txt",
}


class SetupError(RuntimeError):
    """Setup stopped before success was established."""


class InstallerError(SetupError):
    def __init__(self, output, log_path):
        super().__init__("The office installer could not finish the update.")
        self.output = output
        self.log_path = log_path


class VerifiedBundle:
    def __init__(self, archive, metadata, records):
        self.archive = archive
        self.metadata = metadata
        self.records = records
        self.file_count = len(records)


def resource_directory():
    return Path(
        getattr(
            sys,
            "_MEIPASS",
            Path(__file__).resolve().parent / "build/office-setup-resources",
        )
    )


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unique_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SetupError("The package contains duplicate manifest fields.")
        result[key] = value
    return result


def read_json_bytes(content):
    if len(content) > MAX_JSON_BYTES:
        raise SetupError("The package manifest is too large.")
    try:
        value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_json_pairs)
    except (UnicodeError, ValueError) as error:
        raise SetupError("The package manifest could not be read.") from error
    if not isinstance(value, dict):
        raise SetupError("The package manifest is invalid.")
    return value


def safe_relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise SetupError("The package contains an unsafe Windows path.")
    parts = value.split("/")
    for part in parts:
        if (
            part in {"", ".", ".."}
            or re.search(r'[<>:"|?*\x00-\x1f]', part)
            or part.endswith((".", " "))
            or re.match(r"(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part)
        ):
            raise SetupError("The package contains an unsafe Windows path.")
    return parts


def _plain_path(path):
    current = path.absolute()
    for item in (current, *current.parents):
        if item.is_symlink() or item.is_junction():
            raise SetupError("Linked folders cannot be used for this setup.")
    return current


def load_metadata(resources):
    path = _plain_path(resources / "setup-metadata.json")
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise SetupError("This setup file is incomplete. Download the complete setup again.")
    metadata = read_json_bytes(path.read_bytes())
    if metadata.get("product") != "faculty":
        raise SetupError("This setup does not contain Cathedra Faculty.")
    version = metadata.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SetupError("The setup version is invalid.")
    patterns = {
        "source_commit": r"[0-9a-f]{40}",
        "release_tag": rf"v{re.escape(version)}-office\.[1-9]\d*",
        "build_identity": rf"{re.escape(version)}-[0-9a-f]{{32}}",
        "source_snapshot_sha256": r"[0-9a-f]{64}",
        "zip_sha256": r"[0-9a-f]{64}",
    }
    if any(
        not isinstance(metadata.get(key), str) or not re.fullmatch(pattern, metadata[key])
        for key, pattern in patterns.items()
    ):
        raise SetupError("The setup identity is invalid. Download the complete setup again.")
    return metadata


def _manifest_records(manifest):
    values = manifest.get("files")
    if not isinstance(values, list) or not values or len(values) > MAX_FILES:
        raise SetupError("The package file inventory is invalid.")
    records = {}
    folded = set()
    for record in values:
        if not isinstance(record, dict):
            raise SetupError("The package file inventory is invalid.")
        name = record.get("path")
        safe_relative_path(name)
        size = record.get("bytes")
        digest = record.get("sha256")
        if (
            name.casefold() in folded
            or type(size) is not int
            or size < 0
            or size > MAX_FILE_BYTES
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)
        ):
            raise SetupError("The package file inventory is invalid or duplicated.")
        folded.add(name.casefold())
        records[name] = {"bytes": size, "sha256": digest.lower()}
    return records


def _archive_entries(package):
    infos = package.infolist()
    if not infos or len(infos) > MAX_FILES:
        raise SetupError("The setup contains too many package entries.")
    folded = set()
    files = {}
    total = 0
    for info in infos:
        # ZipInfo normalizes Windows separators and truncates NULs in filename;
        # inspect the original central-directory spelling before that normalization.
        if info.orig_filename != info.filename:
            raise SetupError("The package contains an unsafe Windows path.")
        name = info.filename[:-1] if info.is_dir() else info.filename
        safe_relative_path(name)
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (
            name.casefold() in folded
            or stat.S_ISLNK(mode)
            or kind not in {0, stat.S_IFREG, stat.S_IFDIR}
            or info.external_attr & 0x400
            or info.flag_bits & 1
            or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            or info.file_size < 0
            or info.file_size > MAX_FILE_BYTES
        ):
            raise SetupError("The setup contains an unsafe or duplicate package entry.")
        folded.add(name.casefold())
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise SetupError("The expanded package is too large.")
        if not info.is_dir():
            files[name] = info
    file_keys = {name.casefold() for name in files}
    for name in folded:
        parts = name.split("/")
        if any("/".join(parts[:end]).casefold() in file_keys for end in range(1, len(parts))):
            raise SetupError("The package contains conflicting file and folder paths.")
    return files


def _zip_json(package, infos, name):
    if name not in infos or infos[name].file_size > MAX_JSON_BYTES:
        raise SetupError("The setup is missing a required package manifest.")
    return read_json_bytes(package.read(name))


def verify_bundle(resources=None):
    resources = Path(resources) if resources is not None else resource_directory()
    metadata = load_metadata(resources)
    archive = _plain_path(resources / "office-package.zip")
    if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise SetupError("This setup file is incomplete. Download the complete setup again.")
    if sha256_file(archive) != metadata["zip_sha256"]:
        raise SetupError("This setup file did not pass its integrity check. Download it again.")
    try:
        with zipfile.ZipFile(archive) as package:
            infos = _archive_entries(package)
            wrapper = _zip_json(package, infos, "office-release-manifest.json")
            if any(wrapper.get(key) != metadata[key] for key in IDENTITY_FIELDS):
                raise SetupError("The package identity does not match this setup.")
            if wrapper.get("platform") != "Windows-x64" or wrapper.get("asset") != (
                f"Cathedra-Faculty-{metadata['version']}-Windows-x64.zip"
            ):
                raise SetupError("The package platform or version is invalid.")
            records = _manifest_records(wrapper)
            if set(infos) != set(records) | {"office-release-manifest.json"}:
                raise SetupError("The package files differ from the verified inventory.")
            app_prefix = APPLICATION + "/"
            if not COMPANIONS.issubset(records) or any(
                name not in COMPANIONS and not name.startswith(app_prefix) for name in records
            ):
                raise SetupError("The package contains an unexpected companion file.")
            for name, record in records.items():
                if infos[name].file_size != record["bytes"]:
                    raise SetupError("A package file size does not match its inventory.")
                digest = hashlib.sha256()
                with package.open(infos[name]) as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != record["sha256"]:
                    raise SetupError("A package file did not pass its integrity check.")
            app_manifest = _zip_json(package, infos, app_prefix + "release-manifest.json")
            if any(
                app_manifest.get(key) != metadata[key]
                for key in (
                    "product",
                    "version",
                    "build_identity",
                    "source_snapshot_sha256",
                )
            ):
                raise SetupError("The application identity does not match this setup.")
            app_records = _manifest_records(app_manifest)
            if not REQUIRED_APP_FILES.issubset(app_records):
                raise SetupError("The package is missing required application files.")
            actual_app = {name[len(app_prefix) :] for name in infos if name.startswith(app_prefix)}
            if actual_app != set(app_records) | {"release-manifest.json"}:
                raise SetupError("The application files differ from the verified inventory.")
            for name, record in app_records.items():
                if name == "release-manifest.json" or name.split("/")[0].casefold() == "data":
                    raise SetupError("Runtime records must not be included in setup.")
                if re.search(r"(?i)(\.db($|-)|\.sqlite[0-9]*($|-))", name) and name != (
                    "_internal/backend/cathedra-seed.db"
                ):
                    raise SetupError("The package contains an unexpected database.")
                if record != records.get(app_prefix + name):
                    raise SetupError("The application and office inventories disagree.")
            text_identities = {
                "_internal/VERSION": metadata["version"],
                "_internal/APP_PRODUCT": "faculty",
                "_internal/BUILD_ID": metadata["build_identity"],
                "_internal/frontend/dist/release-version.txt": metadata["version"],
                "_internal/frontend/dist/build-id.txt": metadata["build_identity"],
            }
            for name, expected in text_identities.items():
                if package.read(app_prefix + name).decode("utf-8-sig").strip() != expected:
                    raise SetupError("The application resource identity is inconsistent.")
            records["office-release-manifest.json"] = {
                "bytes": infos["office-release-manifest.json"].file_size,
                "sha256": hashlib.sha256(package.read("office-release-manifest.json")).hexdigest(),
            }
    except (OSError, zipfile.BadZipFile, UnicodeError, RuntimeError) as error:
        if isinstance(error, SetupError):
            raise
        raise SetupError("The setup package could not be verified. Download it again.") from error
    return VerifiedBundle(archive, metadata, records)


def _profile_and_temp(profile=None, temporary=None):
    profile = _plain_path(Path(profile) if profile is not None else Path(os.environ["USERPROFILE"]))
    temporary = _plain_path(
        Path(temporary) if temporary is not None else Path(os.environ["LOCALAPPDATA"]) / "Temp"
    )
    if (
        not profile.is_dir()
        or not temporary.is_dir()
        or not temporary.resolve().is_relative_to(profile.resolve())
    ):
        raise SetupError("Setup needs the temporary folder for your current Windows account.")
    return profile, temporary


def smoke_install_target(value, profile=None, temporary=None):
    profile, temporary = _profile_and_temp(profile, temporary)
    target = _plain_path(Path(value))
    fixture = target.parent
    if (
        not Path(value).is_absolute()
        or not re.fullmatch(r"cathedra-installer-test-[0-9a-f]{32}", fixture.name)
        or fixture.parent.resolve() != temporary.resolve()
        or not target.resolve().is_relative_to(profile.resolve())
    ):
        raise SetupError("Automated setup tests require a disposable GUID-named test folder.")
    safe_relative_path(target.name)
    return target


@contextlib.contextmanager
def _clean_dll_search_path():
    restore = getattr(sys, "_MEIPASS", None)
    kernel = None
    if sys.platform == "win32" and restore:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.restype = ctypes.c_int
        if not kernel.SetDllDirectoryW(None):
            raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        if kernel is not None:
            # Do not lose a running installer process if restoration fails.
            # A cleared process DLL search path is safe for the external child.
            kernel.SetDllDirectoryW(str(restore))


def child_environment():
    environment = dict(os.environ)
    for name in list(environment):
        if name.upper().startswith(("_PYI_", "PYTHON")) or name.upper() == "_MEIPASS2":
            environment.pop(name)
    windows = Path(environment.get("SystemRoot", r"C:\Windows"))
    environment["PSModulePath"] = str(windows / "System32/WindowsPowerShell/v1.0/Modules")
    frozen_root = str(getattr(sys, "_MEIPASS", "")).casefold()
    if frozen_root:
        environment["PATH"] = os.pathsep.join(
            item
            for item in environment.get("PATH", "").split(os.pathsep)
            if item and not item.casefold().startswith(frozen_root)
        )
    return environment


def powershell_command():
    return str(
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )


def _start_process(command, **kwargs):
    with _clean_dll_search_path():
        return subprocess.Popen(
            command,
            env=child_environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            **kwargs,
        )


def _private_work_folder(bundle, temporary):
    work = temporary / ("cathedra-setup-" + uuid.uuid4().hex)
    work.mkdir()
    package_folder = work / "package"
    package_folder.mkdir()
    # Verify again immediately before extraction; the archive is never obtained
    # from the network or chosen from an arbitrary user-supplied path.
    if sha256_file(bundle.archive) != bundle.metadata["zip_sha256"]:
        raise SetupError("The setup package changed before it could be prepared.")
    with zipfile.ZipFile(bundle.archive) as package:
        entries = _archive_entries(package)
        if set(entries) != set(bundle.records):
            raise SetupError("The package inventory changed before extraction.")
        for name, info in entries.items():
            target = package_folder.joinpath(*safe_relative_path(name))
            if not target.resolve().is_relative_to(package_folder.resolve()):
                raise SetupError("The setup contains an unsafe extraction path.")
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            count = 0
            with package.open(info) as source, target.open("xb") as destination:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    count += len(block)
                    digest.update(block)
                    destination.write(block)
            if (
                count != bundle.records[name]["bytes"]
                or digest.hexdigest() != bundle.records[name]["sha256"]
            ):
                raise SetupError("A package file changed during extraction.")
    if sha256_file(bundle.archive) != bundle.metadata["zip_sha256"]:
        raise SetupError("The package changed during extraction. No installation was attempted.")
    protector = package_folder / APPLICATION / "desktop/protect-local-folder.ps1"
    command = [
        powershell_command(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(protector),
        "-Folder",
        str(work),
    ]
    process = _start_process(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output, _ = process.communicate()
    if process.returncode or b"Private Windows permissions verified" not in output:
        raise SetupError(
            "Setup could not create a private working folder. Your installation was not changed."
        )
    return work, package_folder


def installer_command(package_folder, target, *, smoke=False, no_launch=False):
    if smoke and not no_launch:
        raise SetupError("Automated setup tests must not launch the office application.")
    command = [
        powershell_command(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(package_folder / "Install-Office.ps1"),
        "-PackageFolder",
        str(package_folder),
        "-InstallFolder",
        str(target),
    ]
    if no_launch:
        command.append("-NoLaunch")
    if smoke:
        command.append("-TestMode")
    return command


def _stage_for_line(line):
    stages = (
        (
            "Saving a private recovery copy",
            "Backing up your current application and records…",
        ),
        ("Verifying the recovery copy", "Checking your recovery copy…"),
        ("Verifying your recovery copy", "Checking your recovery copy…"),
        ("Installing the verified application", "Installing the update…"),
        ("Checking saved records", "Checking your saved records…"),
        ("Checking your saved records", "Checking your saved records…"),
        ("Preparing the new application", "Preparing the new application…"),
        ("Checking the complete", "Checking the complete update…"),
    )
    return next((label for prefix, label in stages if prefix in line), None)


def _remove_work_folder(work, temporary):
    work = _plain_path(work)
    if work.parent.resolve() != temporary.resolve() or not re.fullmatch(
        r"cathedra-setup-[0-9a-f]{32}", work.name
    ):
        raise SetupError("The setup working folder could not be safely removed.")
    if any(item.is_symlink() or item.is_junction() for item in work.rglob("*")):
        raise SetupError("A linked setup working file was found; the folder was retained.")
    shutil.rmtree(work)


def install_bundle(bundle, *, target=None, smoke=False, no_launch=False, progress=None):
    profile, temporary = _profile_and_temp()
    if smoke:
        if not no_launch or target is None:
            raise SetupError("Automated setup tests require a target and --no-launch.")
        target = smoke_install_target(target, profile, temporary)
    elif target is not None or no_launch:
        raise SetupError("Normal setup uses the current account's Faculty installation.")
    else:
        target = profile / "Cathedra-Faculty"
    notify = progress or (lambda text: None)
    notify("Preparing the verified update…")
    work, package_folder = _private_work_folder(bundle, temporary)
    log_path = work / "setup.log"
    output = []
    with log_path.open("x", encoding="utf-8") as log:
        process = _start_process(
            installer_command(package_folder, target, smoke=smoke, no_launch=no_launch),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
        )
        for line in process.stdout:
            log.write(line)
            log.flush()
            output.append(line)
            label = _stage_for_line(line)
            if label:
                notify(label)
        process.wait()
    rendered = "".join(output)
    if process.returncode:
        raise InstallerError(rendered, log_path)
    installed = target / "release-manifest.json"
    if not installed.is_file():
        raise InstallerError(
            "The installer finished without a verifiable application manifest.",
            log_path,
        )
    manifest = read_json_bytes(installed.read_bytes())
    if any(
        manifest.get(key) != bundle.metadata[key]
        for key in ("product", "version", "build_identity", "source_snapshot_sha256")
    ):
        raise InstallerError("The installed application identity could not be confirmed.", log_path)
    backups = [
        line.partition(": ")[2].strip()
        for line in rendered.splitlines()
        if line.startswith("Recovery copy (keep this private): ")
    ]
    result = {
        "status": "ok",
        **{key: bundle.metadata[key] for key in IDENTITY_FIELDS},
        "zip_sha256": bundle.metadata["zip_sha256"],
        "install_folder": str(target),
        "private_backup": backups[-1] if backups else None,
    }
    try:
        _remove_work_folder(work, temporary)
    except (OSError, SetupError):
        # A verified installation is still successful if a public package cache
        # is momentarily held by antivirus. It contains no office records.
        result["temporary_package_retained"] = True
    return result


def _write_receipt(path, result):
    if path is not None:
        path = _plain_path(Path(path))
        with path.open("x", encoding="utf-8") as destination:
            json.dump(result, destination, indent=2)
    if sys.stdout is not None:
        print(json.dumps(result, indent=2), flush=True)


def show_gui(*, verify=False):
    # Import only for interactive setup or the explicit read-only GUI check.
    # Other verification helpers remain usable without starting a Tk window.
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Cathedra Faculty setup")
    root.geometry("660x560")
    root.minsize(660, 560)
    root.configure(background="#f6f7f4")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background="#f6f7f4")
    style.configure("TLabel", background="#f6f7f4", foreground="#182231", font=("Segoe UI", 11))
    style.configure(
        "Primary.TButton",
        background="#3154d9",
        foreground="white",
        padding=(18, 12),
        font=("Segoe UI", 10, "bold"),
    )
    style.map("Primary.TButton", background=[("active", "#253ead"), ("disabled", "#a8b4e9")])
    style.configure("TButton", padding=(14, 12), font=("Segoe UI", 10))
    frame = ttk.Frame(root, padding=32)
    frame.pack(fill="both", expand=True)
    title = ttk.Label(frame, text="Cathedra Faculty", font=("Segoe UI", 22, "bold"))
    title.pack(anchor="w")
    status = tk.StringVar(value="Ready to prepare your update.")
    events = queue.Queue()
    state = {
        "busy": False,
        "finished": False,
        "details": "",
        "log": None,
        "install_attempted": False,
    }
    verification_result = {}
    try:
        metadata = load_metadata(resource_directory())
        installed = Path(os.environ["USERPROFILE"]) / "Cathedra-Faculty"
        updating = installed.exists()
        heading = f"{'Update to' if updating else 'Install'} version {metadata['version']}"
    except (OSError, SetupError, KeyError) as error:
        metadata = None
        updating = False
        heading = "This setup file could not be opened"
        status.set(str(error))
    ttk.Label(frame, text=heading, font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(18, 8))
    explanation = (
        "Your existing records and accounts stay on this computer. Setup creates a private recovery copy before replacing the application."
        if updating
        else "Install the Faculty workspace for your Windows account. A new installation starts with an empty database."
    )
    ttk.Label(frame, text=explanation, wraplength=580, justify="left").pack(anchor="w")
    ttk.Label(
        frame,
        text="Save any open work and use Exit Cathedra before continuing.",
        wraplength=580,
    ).pack(anchor="w", pady=(12, 0))
    indicator = ttk.Progressbar(frame, mode="indeterminate")
    indicator.pack(fill="x", pady=(24, 12))
    status_label = ttk.Label(frame, textvariable=status, wraplength=580, justify="left")
    status_label.pack(anchor="w")
    helper = ttk.Label(
        frame,
        text="Large offices can take a few minutes. Keep this window open until setup finishes.",
        wraplength=580,
        foreground="#5d6a7b",
        font=("Segoe UI", 10),
    )
    helper.pack(anchor="w", pady=(8, 16))
    actions = ttk.Frame(frame)
    actions.pack(side="bottom", fill="x")

    def close():
        if state["busy"]:
            status.set("Please keep this window open while setup protects and checks your records.")
            return
        root.destroy()

    def details():
        window = tk.Toplevel(root)
        window.title("Setup details")
        window.geometry("720x360")
        text = tk.Text(window, wrap="word", font=("Segoe UI", 10))
        text.pack(fill="both", expand=True, padx=16, pady=16)
        detail = state["details"]
        if state["log"]:
            detail += f"\n\nPrivate setup log: {state['log']}"
        text.insert("1.0", detail)
        text.configure(state="disabled")

    def worker():
        try:
            events.put(("progress", "Checking the complete setup file…"))
            bundle = verify_bundle()
            result = install_bundle(bundle, progress=lambda text: events.put(("progress", text)))
            events.put(("success", result))
        except Exception as error:
            events.put(("error", error))

    def start():
        if verify or state["busy"] or metadata is None:
            return
        state["install_attempted"] = True
        state["busy"] = True
        state["details"] = ""
        state["log"] = None
        primary.configure(state="disabled")
        cancel.configure(state="disabled")
        detail_button.pack_forget()
        indicator.start(12)
        threading.Thread(target=worker, daemon=False).start()

    def poll():
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == "progress":
                    status.set(value)
                else:
                    state["busy"] = False
                    indicator.stop()
                    cancel.configure(state="normal", text="Close setup")
                    if kind == "success":
                        state["finished"] = True
                        status.set(f"Cathedra is ready. Version {value['version']} is installed.")
                        helper.configure(
                            text=(
                                "Your recovery copy is saved. Choose Show details for its location. Use the desktop shortcut next time."
                                if value["private_backup"]
                                else "Use the Cathedra Faculty desktop shortcut next time. Your new workspace is ready."
                            )
                        )
                        primary.pack_forget()
                        if value["private_backup"]:
                            state["details"] = "Private recovery copy: " + value["private_backup"]
                            detail_button.pack(side="left")
                    else:
                        output = value.output if isinstance(value, InstallerError) else str(value)
                        state["details"] = output
                        state["log"] = value.log_path if isinstance(value, InstallerError) else None
                        busy = any(
                            text in output
                            for text in (
                                "Cathedra Faculty is running",
                                "Close all Cathedra Faculty",
                                "data folder is in use",
                            )
                        )
                        status.set(
                            "Close Cathedra to continue."
                            if busy
                            else "Setup could not finish. Review the details before trying again."
                        )
                        helper.configure(
                            text="Save your open work and choose Exit Cathedra in the app. Then return here and choose Try again."
                            if busy
                            else "Keep any recovery copy. The details include the reason and the private setup log, when available."
                        )
                        primary.configure(state="normal", text="Try again")
                        detail_button.pack(side="left")
        except queue.Empty:
            pass
        root.after(100, poll)

    cancel = ttk.Button(actions, text="Cancel", command=close)
    cancel.pack(side="right")
    primary = ttk.Button(
        actions,
        text="Update Cathedra" if updating else "Install Cathedra",
        style="Primary.TButton",
        command=start,
    )
    primary.pack(side="right", padx=(0, 10))
    detail_button = ttk.Button(actions, text="Show details", command=details)
    if metadata is None or verify:
        primary.configure(state="disabled")
    root.protocol("WM_DELETE_WINDOW", close)
    root.bind("<Escape>", lambda event: close())
    root.after(100, poll)

    def finish_verification():
        try:
            root.update_idletasks()
            if metadata is None:
                raise SetupError("The setup window could not load its verified identity.")
            width, height = root.winfo_width(), root.winfo_height()
            for name, widget in (
                ("primary action", primary),
                ("cancel action", cancel),
                ("status", status_label),
            ):
                left = widget.winfo_rootx() - root.winfo_rootx()
                top = widget.winfo_rooty() - root.winfo_rooty()
                if (
                    not widget.winfo_ismapped()
                    or widget.winfo_width() < widget.winfo_reqwidth()
                    or widget.winfo_height() < widget.winfo_reqheight()
                    or left < 0
                    or top < 0
                    or left + widget.winfo_width() > width
                    or top + widget.winfo_height() > height
                ):
                    raise SetupError(f"The setup window does not fully display its {name}.")
            if state["install_attempted"] or not primary.instate(["disabled"]):
                raise SetupError("The read-only setup check did not keep installation disabled.")
            verification_result.update(
                {
                    "gui_constructed": True,
                    "gui_controls_fit": True,
                    "gui_width": width,
                    "gui_height": height,
                    "install_attempted": False,
                }
            )
        except Exception as error:
            verification_result["error"] = error
        finally:
            root.destroy()

    if verify:
        root.after(300, finish_verification)
    root.mainloop()
    if verify:
        if "error" in verification_result:
            raise SetupError(str(verification_result["error"])) from verification_result["error"]
        if not verification_result.get("gui_constructed"):
            raise SetupError("The setup window closed before its read-only check finished.")
        return verification_result
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cathedra Faculty setup")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-bundle", action="store_true")
    mode.add_argument("--verify-gui", action="store_true")
    mode.add_argument("--smoke-install", action="store_true")
    parser.add_argument("--install-folder")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--receipt")
    args = parser.parse_args(argv)
    if not args.verify_bundle and not args.verify_gui and not args.smoke_install:
        if args.install_folder or args.no_launch or args.receipt:
            parser.error("Automated options require a verification or smoke-install mode.")
        show_gui()
        return 0
    result = {
        "status": "error",
        "private_backup": None,
        **dict.fromkeys((*IDENTITY_FIELDS, "zip_sha256")),
    }
    try:
        if not args.receipt:
            raise SetupError("Automated verification requires a new receipt file.")
        receipt = _plain_path(Path(args.receipt))
        if receipt.exists() or not receipt.parent.is_dir():
            raise SetupError("Choose a new receipt file in an existing folder.")
        if (args.verify_bundle or args.verify_gui) and (args.install_folder or args.no_launch):
            raise SetupError("Read-only verification does not install or launch the application.")
        if args.smoke_install:
            if not args.install_folder or not args.no_launch:
                raise SetupError(
                    "Automated installation requires --install-folder and --no-launch."
                )
            smoke_install_target(args.install_folder)
        metadata = load_metadata(resource_directory())
        result.update({key: metadata[key] for key in IDENTITY_FIELDS})
        result["zip_sha256"] = metadata["zip_sha256"]
        bundle = verify_bundle()
        if args.verify_bundle or args.verify_gui:
            result.update(
                {
                    "status": "ok",
                    "archive_files": bundle.file_count,
                    "private_backup": None,
                }
            )
            if args.verify_gui:
                result.update(show_gui(verify=True))
        else:
            result = install_bundle(bundle, target=args.install_folder, smoke=True, no_launch=True)
        _write_receipt(args.receipt, result)
        return 0
    except Exception as error:
        result["status"] = "error"
        result["error"] = str(error)
        if isinstance(error, InstallerError):
            result["private_log"] = str(error.log_path)
        try:
            _write_receipt(args.receipt, result)
        except (OSError, SetupError):
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
