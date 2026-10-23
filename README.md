# Cathedra Faculty

Windows desktop application for faculty profiles, teaching workloads, approvals,
reports and expense projections. The interface retains the established green palette.
The backend uses FastAPI, SQLAlchemy and SQLite; the frontend uses React and TypeScript.
FSDP is maintained separately and is not registered in this application's UI or API.

## Download and use on your office PC

**[Download the latest Windows app](https://github.com/sebas011/Cathedra-Faculty/releases/latest)**

1. Open the release above and download the `Cathedra-Faculty-…-Windows-x64.zip` asset.
2. Right-click the ZIP and choose **Extract All**. Open the extracted folder.
3. Double-click **Install-or-Update.cmd**. Then use the **Cathedra Faculty** desktop shortcut.

Use Windows 10 or 11 (64-bit), with Microsoft Edge installed. Python, Node.js,
development tools and administrator rights are not required. Download the release
ZIP under **Assets**; GitHub's **Code > Download ZIP** contains development source.

The installer places the complete app in `%USERPROFILE%\Cathedra-Faculty`.
Close Cathedra before installing an update. Existing records and sign-in accounts
in that location are preserved, with a private backup made before replacement.
The installer checks the packaged file hashes and refuses an incomplete package.

On a new PC, the app starts with an empty database and guides you through creating
your administrator account. This public download contains no faculty records or
existing passwords. To bring records from another PC, use **Backup & Export** in
the existing app and transfer that backup privately; restore it in the office app.
Restoring replaces the destination records and accounts, so preserve a backup of
that destination first. Computers do not synchronize automatically.

## Updating from the original 0.3.2 installation

Use **v0.3.5-office.2** or a later corrected release. The original 0.3.2 manifest
legitimately lacks build identities and BUILD_ID; the first office.1 installer
incorrectly rejects it. The corrected installer verifies its old checksums,
backs up the complete application and data privately, and preserves the original
manifest in the recovery copy. Download/extract the whole corrected ZIP; do not
edit old manifests or replace one script inside an earlier ZIP.

Read the [step-by-step 0.3.2 migration guide](docs/UPGRADE_FROM_032.md), including
first-start database migration, existing-account sign-in and complete recovery.

## Update three separate Google Sheets

Administrators can connect three different spreadsheets under **Backup & Export**:
**Faculty Workload**, **Overload Projection** and **Faculty Profile**. Each has its
own connection, update button, read-only test and last successful update.

Workload exports contain workload records, assignments and frozen approved hours
without payment columns. Overload exports contain Regular Faculty overload
estimates, budgets and relevant cost settings; part-time teaching and base salary
projections are excluded. Profiles include the faculty fields recorded in the app,
including salary fields. Accounts, sessions, keys and activity logs are excluded.

Use three distinct spreadsheet IDs. You can share them all with one approved
Google service account as Editor and select its JSON key for each connection.
Read the [detailed setup guide](docs/GOOGLE_SHEETS_SETUP.md), also downloadable
from each connection form. Existing tabs are preserved; Cathedra updates only
its marked category tabs. Old combined connections are preserved separately.
Connections stay on the current PC; no Google credentials ship in the download.

## Repository scope

This is a clean publication of the current application source (version 0.3.5,
schema 24). It includes backend and frontend runtime code, synthetic application
tests, dependency locks, the desktop launcher, packaging and Windows CI workflows.

Office databases, account credentials, personnel source documents, screenshots,
deployment receipts, and historical correction scripts/fixtures containing real
office decisions are kept outside this public repository. The local private Git
history is intentionally not published. No production accounts or default passwords
are provided. Historical import utilities are not required to run the application;
schema migration and backup/restore support remain in the runtime source.

## Development on Windows

Use Python 3.14 and Node.js 24. From the repository root:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt -r desktop/requirements-build.txt -c backend/constraints-win-py314.txt
npm ci --prefix frontend
```

In a backend terminal:

```powershell
cd backend
$env:CATHEDRA_SETUP_ORIGIN = 'http://127.0.0.1:5175'
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8102
```

In a second terminal:

```powershell
cd frontend
npm run dev
```

For first administrator setup, open the newest `data/.setup-*/start.html` from
the selected data folder as the same Windows user. That private entry supplies
the one-time setup key; opening the login route directly cannot create the first
administrator. The key is removed from the address immediately and consumed after
setup. Windows private-entry creation requires Python 3.13 or newer.

Development uses the repository's own `data/cathedra.db`. Set `CATHEDRA_DATA_DIR`
before starting the backend to select another folder. Use disposable folders for
tests. For a built frontend served directly by the backend, the default setup
origin is `http://127.0.0.1:8102`; set `CATHEDRA_SETUP_ORIGIN` for another local port.

## Validation and packaging

From `backend`, run `python -m pytest`. From `frontend`, run `npm run lint`,
`npm test`, `npm run test:typecheck` and `npm run build`.

For a clean Windows desktop build:

```powershell
./desktop/build-split-release.ps1
```

The packaging script runs backend/frontend checks and isolated packaged smoke
tests, creates an empty installation seed, and records a unique build identity,
dependency inventory and file hashes. Production data is not included. A fresh
public-source package has its own source identity; it is not the previously
installed office executable.

## Desktop data and recovery

Keep the installed folder together, including `_internal`, `desktop` and the
runtime `data` created on that PC. The installer and launcher apply private folder
permissions for the current Windows user. Existing installations use their own
accounts; browser sign-in is tab scoped. First setup creates a new administrator
only through the private entry opened by the launcher.

Before upgrading or restoring, preserve a verified backup. Test migrations and
restore on copies. Rollback requires the matching previous application and its
pre-upgrade database; older builds must not open a newer schema. No synchronization
or automatic merging occurs between folders, computers or FSDP.
