"""Collect installed dependency metadata and bundled license texts for a release."""
import importlib.metadata
import json
import sys
from pathlib import Path


def write(folder):
    root=Path(__file__).resolve().parents[1]
    sections=["Cathedra Faculty third-party dependency notices\nIncludes runtime, build, and test inputs. This does not assign a license to Cathedra's own source.\n"]
    for distribution in sorted(importlib.metadata.distributions(),key=lambda item:item.metadata["Name"].lower()):
        name=distribution.metadata["Name"]
        sections.append(f"\n=== Python: {name} {distribution.version} ===\nLicense metadata: {distribution.metadata.get('License-Expression') or distribution.metadata.get('License') or 'See dependency license'}\n")
        for file in distribution.files or []:
            if ".dist-info/" in str(file) and any(part.lower().startswith(("license","licence","copying","notice")) for part in file.parts):
                path=distribution.locate_file(file)
                if path.is_file():sections.append(path.read_text(encoding="utf-8",errors="replace"))
    packages=json.loads((root/"frontend/package-lock.json").read_text())["packages"]
    for relative,metadata in sorted(packages.items()):
        if not relative:continue
        path=root/"frontend"/relative
        sections.append(f"\n=== npm: {relative.removeprefix('node_modules/')} {metadata.get('version','')} ===\nLicense metadata: {metadata.get('license','See dependency license')}\n")
        for file in sorted(path.glob("*")):
            if file.is_file() and file.name.lower().startswith(("license","licence","copying","notice")):
                sections.append(file.read_text(encoding="utf-8",errors="replace"))
    (folder/"THIRD_PARTY_NOTICES.txt").write_text("\n".join(sections),encoding="utf-8")


if __name__=="__main__":write(Path(sys.argv[1]).resolve())
