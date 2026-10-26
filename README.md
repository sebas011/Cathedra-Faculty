# Cathedra Faculty

Windows desktop application for faculty profiles, teaching workloads, approvals,
reports and expense projections. Version 0.3.7 adds a single-file Windows setup for simpler office updates.
The backend uses FastAPI, SQLAlchemy and SQLite; the frontend uses React and TypeScript.
FSDP is maintained separately and is not registered in this application's UI or API.

## Redesigned Faculty workspace — 0.3.6

Clearer profile/workload directories, grouped forms, scoped dashboard figures,
administrator recent activity and Ctrl+K page navigation improve everyday office
work. Existing data, approval states, calculations and the three separate Google
Sheets connections keep their behavior. Schema remains 24.

Read the [release notes](docs/RELEASE_036.md),
[design system](docs/redesign-2026-10-24/DESIGN_SYSTEM.md), and
[implementation blueprint](docs/redesign-2026-10-24/IMPLEMENTATION_BLUEPRINT.md).
The optional [HTML/Tailwind/HTMX handoff](design/faculty-redesign/templates/README.md)
is separate from the production React app. Design screenshots use synthetic data.

## Download and use on your office PC

**[Download Cathedra-Faculty-Setup.exe](https://github.com/sebas011/Cathedra-Faculty/releases/latest/download/Cathedra-Faculty-Setup.exe)**

1. Save your work and choose **Exit Cathedra**.
2. Open the downloaded **Cathedra-Faculty-Setup.exe**.
3. Choose **Update Cathedra**. On a new PC, choose **Install Cathedra**.

Setup checks and extracts its package, creates and verifies a private recovery
copy, keeps your records and accounts, and opens the updated app. No ZIP
extraction, manual file moves, administrator account, Python or Node.js is needed.
Use your normal Windows account. Setup installs in
`%USERPROFILE%\Cathedra-Faculty`; use the desktop shortcut afterward.

If Cathedra is still open, save and exit it, then choose **Try again** in setup.
See the [simple update guide](docs/SIMPLE_OFFICE_UPDATE.md).
The Windows ZIP remains an optional alternative; GitHub's Source code ZIP is for
development and is not the office installer.

New PCs start with an empty database. The public download contains no office
records, accounts or Google credentials. Transfer records privately using Backup
& Export. Restore replaces destination records and accounts; keep a backup first.
Computers do not automatically synchronize or merge databases.

## Updating the original 0.3.2 installation

Use the latest **0.3.7 setup** or a later corrected release. It recognizes the
original manifest and seven known legacy sidecar files automatically, verifies
the application and saves a complete private recovery copy. Do not remove old
files or edit manifests to make an update pass.
Read the [migration guide](docs/UPGRADE_FROM_032.md).

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

This is a clean publication of the current application source (version 0.3.7,
schema 24). It includes backend and frontend runtime code, synthetic application
tests, dependency locks, the desktop launcher, packaging and Windows CI workflows.

Office databases, account credentials, personnel source documents, office screenshots,
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
