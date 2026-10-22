import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path


def source_snapshot(root: Path) -> str:
    paths = set()
    for folder in ("backend/app", "backend/tests", "frontend/src", "frontend/tests"):
        paths.update(
            path
            for path in (root / folder).rglob("*")
            if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".css"}
        )
    for folder, patterns in (
        ("backend", ("*.py", "*.txt", "*.toml")),
        ("frontend", ("*.ts", "*.json", "*.js", "*.html")),
        ("desktop", ("*.py", "*.ps1", "*.cmd", "*.txt")),
    ):
        for pattern in patterns:
            paths.update((root / folder).glob(pattern))
    paths.update(root / name for name in ("VERSION", "APP_PRODUCT"))
    guide = root / "docs" / "GOOGLE_SHEETS_SETUP.md"
    if guide.is_file():
        paths.add(guide)
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def verify_constraints(root: Path):
    for line in (root / "backend" / "constraints-win-py314.txt").read_text().splitlines():
        if "==" not in line:
            continue
        name, expected = line.split("==", 1)
        actual = importlib.metadata.version(name)
        if actual != expected:
            raise RuntimeError(f"Unpinned dependency: {name}: {actual} != {expected}")


def inventory(root: Path, folder: Path):
    files = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.name != "release-manifest.json":
            relative = path.relative_to(folder).as_posix()
            if relative.startswith("data/"):
                raise RuntimeError("Office data must not enter the clean release.")
            files.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
            )
    packages = sorted(
        (
            {"name": distribution.metadata["Name"], "version": distribution.version}
            for distribution in importlib.metadata.distributions()
        ),
        key=lambda item: item["name"].lower(),
    )
    manifest = {
        "product": "faculty",
        "version": (root / "VERSION").read_text().strip(),
        "build_identity": (root / "BUILD_ID").read_text().strip(),
        "source_snapshot_sha256": source_snapshot(root),
        "python": sys.version.split()[0],
        "backend_packages": packages,
        "frontend_lock_sha256": hashlib.sha256(
            (root / "frontend" / "package-lock.json").read_bytes()
        ).hexdigest(),
        "files": files,
        "signing": "Unsigned; certificate signing is an external release decision.",
    }
    (folder / "release-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    verify_constraints(root)
    if len(sys.argv) > 1 and sys.argv[1] == "--source-hash":
        print(source_snapshot(root))
    elif len(sys.argv) > 1:
        inventory(root, Path(sys.argv[1]).resolve())
