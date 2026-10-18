# Cathedra Faculty

Windows desktop application for faculty profiles, teaching workloads, approvals,
reports and expense projections. The interface retains the established green palette.
The backend uses FastAPI, SQLAlchemy and SQLite; the frontend uses React and TypeScript.
FSDP is maintained separately and is not registered in this application's UI or API.

## Repository scope

This is a clean publication of the current application source (version 0.3.3,
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

Keep the complete packaged folder together, including `_internal`, `desktop`
and runtime `data`. Run `desktop/Prepare-Office-Copy.cmd` as the intended Windows
user after copying to another computer. The launcher verifies private folder
permissions. Existing installations use their own accounts; browser sign-in is
tab scoped. First setup creates a new administrator only through the private entry.

Before upgrading or restoring, preserve a verified backup. Test migrations and
restore on copies. Rollback requires the matching previous application and its
pre-upgrade database; older builds must not open a newer schema. No synchronization
or automatic merging occurs between folders, computers or FSDP.
