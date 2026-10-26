# Update the office app

Use the single **Cathedra-Faculty-Setup.exe** file for each office update.

1. **Save and close Cathedra.** Choose **Exit Cathedra** after saving any open work.
2. **[Download setup](https://github.com/sebas011/Cathedra-Faculty/releases/latest/download/Cathedra-Faculty-Setup.exe).** Keep the file name `Cathedra-Faculty-Setup.exe`.
3. **Open the file and choose Update Cathedra.** On a new computer, the button is **Install Cathedra**.

Setup checks the package, extracts it for you and creates a verified private
recovery copy before replacing the existing application. Records, accounts and
settings stay in the installed data folder. Keep the setup window open until it
says **Cathedra is ready**. A large office may take a few minutes.

Cathedra opens automatically. Sign in with your existing account and check a
familiar faculty profile and workload. Keep the recovery folder shown by setup.
For daily use, open the **Cathedra Faculty** desktop shortcut.

Use the same Windows account as before. No manual extraction, administrator
rights, Python, Node.js or command-line steps are needed.

## If setup asks you to close Cathedra

Save your work, choose **Exit Cathedra** in every open Cathedra window, then return
to setup and choose **Try again**. Setup keeps your open work under your control;
it does not force-close the app.

## If you still use version 0.3.2

The corrected installer recognizes seven known extra files from the original
0.3.2 installation. It includes those files in the complete private recovery copy
and keeps them separate from the new app. Leave them in place; there is no need
to move or delete files one by one.

If verification stops for another reason, keep your existing installation,
records and backups. Share the exact setup message with your office support
person. The [0.3.2 migration guide](UPGRADE_FROM_032.md) contains the detailed
verification and recovery procedure.

## Recovery and a new office PC

If application replacement fails, the installer attempts to restore and verify
the previous app. If setup reports a recovery problem, retain every named folder
and ask for support before opening Cathedra. After a new version has started,
returning to an older version requires its matching old app and old database
together. Preserve newer work separately first.

A new computer starts with an empty office. Transfer records privately through
**Backup & Export**. Separate computers do not synchronize or merge records
automatically. Keep databases, passwords, Google keys and recovery copies private.

The [Windows ZIP](https://github.com/sebas011/Cathedra-Faculty/releases/latest)
is an optional alternative: extract all files, then run **Install-or-Update.cmd**.
The single setup file above is the simpler choice for office updates.

Setup is currently unsigned, so Windows may display a publisher warning.
