# Cathedra Faculty 0.3.7 — simpler office updates

Save your work, choose Exit Cathedra, then download and open
**[Cathedra-Faculty-Setup.exe](https://github.com/sebas011/Cathedra-Faculty/releases/latest/download/Cathedra-Faculty-Setup.exe)**.
Choose **Update Cathedra**. The updated application opens when setup finishes.

The single-file setup includes the full Windows application. It extracts and
checks its package automatically, then uses Cathedra's existing installer to lock
the data folder, make and verify a complete private recovery copy, replace the
application and check the preserved data. It does not download or run scripts
from a changing website. No Python, Node.js or administrator account is required.

The original 0.3.2 manifest and the seven known legacy sidecar files are supported.
These reference files stay in the private recovery copy instead of being mixed
into the new application. Do not manually remove files or edit manifests.

Setup shows progress and readable errors. If Cathedra is still open, save your
work, choose Exit Cathedra, return to setup and choose **Try again**. Setup never
force-closes an editing session. Keep the recovery folder shown after an update.

New installations start empty. Existing accounts and records are retained during
updates; moving records to another PC still uses Backup & Export privately. The
public download contains no office records or credentials. Database schema stays
at 24, and workload/compensation rules remain unchanged.

The full ZIP and checksum files remain available as an optional alternative.
See the [simple office guide](SIMPLE_OFFICE_UPDATE.md) and
[original 0.3.2 migration guide](UPGRADE_FROM_032.md).
