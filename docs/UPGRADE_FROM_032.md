# Update Cathedra Faculty 0.3.2

Use an official Windows office release that includes the legacy migration fix.
Older installers may reject authentic 0.3.2 installations before starting their
backup. A matching ZIP checksum does not fix an installer compatibility issue.

## Why the old update stopped

The original 0.3.2 manifest records `product`, `version` and each application
file's path, SHA-256 and byte size. It predates `build_identity`,
`source_snapshot_sha256` and the `_internal/BUILD_ID` file. These missing fields
are legitimate for that release. Do not edit the manifest or invent values.

The corrected installer recognizes only that installed 0.3.2 format. It still
checks every listed file, rejects unsafe paths and unexpected/missing application
files, and checks the product and backend/frontend version markers. Some real
0.3.2 installations also contain seven known sidecar files outside the recorded
payload: `OFFICE-UPDATE-VALIDATION.json`, `START HERE - OFFICE SETUP.txt`,
`TRANSFER-VALIDATION.json`, and four design-reference files under `docs/`.
Only those exact paths are tolerated in a recognized installed 0.3.2 tree. They
are included in the complete recovery copy but not promoted into the new release.
Arbitrary unlisted files remain rejected. The incoming download must pass the
complete current manifest and checksum checks.

## Step-by-step upgrade

1. In the old app, save any open work. Use **Exit Cathedra**, then close all other
   Cathedra windows using the same records.
2. Leave `Cathedra-Faculty` in its existing Windows user folder and keep any
   backup you already made. Setup creates an additional verified recovery copy
   automatically; you do not need to move the old files.
3. Download **[Cathedra-Faculty-Setup.exe](https://github.com/sebas011/Cathedra-Faculty/releases/latest/download/Cathedra-Faculty-Setup.exe)**.
   Use the latest official setup containing the legacy sidecar correction.
4. Open the setup file. It checks and extracts the complete package for you.
   You do not need to move old files or extract a ZIP.
5. Choose **Update Cathedra** as
   the same normal Windows account used for the existing app. No Python, Node.js
   or administrator account is needed. For example, the default installed path
   is `C:\Users\YourName\Cathedra-Faculty`.
6. Setup recognizes the original **0.3.2** format, verifies
   its recorded application files, locks the data folder, and creates a private
   recovery copy of the **complete old application and data** before replacement.
   It verifies that copy and keeps the old manifest unchanged inside it.
7. Wait for setup to report **Cathedra is ready**. Keep the recovery folder shown
   on screen. The installer leaves the existing `data` folder in place and
   checks its contents against the original file hashes.
8. The app opens and upgrades its existing database schema on first startup.
   Sign in using your existing account. Check representative faculty profiles,
   workload assignments, approvals and projections before normal office use.
9. Keep the verified recovery copy until your office accepts the update. New
   Google Sheets connections are configured separately; updating does not upload
   records to Google automatically.

The installer does not merge records from another PC, replace the existing
database with its empty seed, reset passwords or rewrite the old manifest. A new
installation without existing data starts empty. Setup detects the default
installation automatically. A renamed or custom install folder can be supplied through
the installer's `-InstallFolder` option by the office's support person.

## If verification stops

- **Using an older download:** download the latest **Cathedra-Faculty-Setup.exe**
  and open that complete file. Do not replace scripts inside an older extracted
  package; its wrapper checksums intentionally detect changed files.
- **Old application checksum, missing file or unexpected file:** keep the old
  installation, database and backup. Request support with the exact message and
  installed version. Do not delete records, strip files or change manifest hashes
  to force the update. The legacy exception does not bypass file verification.
- **App/data folder in use:** use Exit Cathedra in every window/account using
  those records and retry after it is closed.
- **Database migration or sign-in error on first startup:** keep both the new
  installation and the complete pre-upgrade recovery copy. An ambiguous pair of
  usernames differing only by letter case requires office support; the app does
  not automatically merge or rename accounts.

## Recovery

If application replacement fails, the installer attempts to restore and verify
the old application, including the original legacy manifest, while keeping the
data unchanged. If it reports a recovery problem, retain all named recovery and
staging folders and seek support before opening the app.

After the new app has started, its database may have migrated from schema 21 to
24. To return to 0.3.2, close the app, preserve any new office work separately,
and restore the **matching old application and old data together** from the
complete recovery copy. Restoring only the old executable can leave it reading
a newer database. Database migration does not create a second automatic
pre-migration backup; the installer's verified full backup is the recovery point.

Keep office records, passwords and recovery copies private. Do not upload them
with a public support report.
