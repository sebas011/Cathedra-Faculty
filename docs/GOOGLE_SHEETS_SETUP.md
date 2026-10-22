# Google Sheets setup for Cathedra

Last reviewed: **22 October 2026**. Applies to **0.3.5 and later**.

Administrators use **Backup & Export → Google Sheets** to connect three separate
Google spreadsheets. Each category has its own **Update Google Sheet** action,
connection, test, last successful update and disconnect control.

| App card | Button | Contents |
| --- | --- | --- |
| Faculty Workload | **Update workload sheet** | Workload records, course assignments and approved workload history; no salary or calculated payment columns. |
| Overload Projection | **Update overload sheet** | Regular Faculty overload estimates, overload budgets and relevant cost settings; no monthly salary projection or part-time teaching costs. |
| Faculty Profile | **Update profile sheet** | Faculty profile fields, including the salary fields recorded on the profile. |

Use **three different spreadsheet links**. You can use the same Google service
account and JSON key for all three; share each spreadsheet with that account as
**Editor**, and choose its JSON file when saving each connection. You can instead
use a different service account for each destination if office access rules require it.

Updates send the latest **saved records on this computer** and run only when you
click and confirm the selected button. Save open forms first. Each update creates
or replaces only that category's Cathedra tabs, keeping your other tabs. Editing
Google Sheets does not change Cathedra. Separate computers do not automatically
synchronize or merge databases; choose one current source computer for reporting.

The profile spreadsheet contains personnel and salary data. The overload sheet
contains financial planning estimates. Review readers for each spreadsheet and
keep **General access → Restricted**. Store the original JSON key privately.
The spreadsheet snapshots do not replace database backups.

The generic guide is downloadable from an expanded **Connect Google Sheet** or
**Edit connection** form using **Download detailed setup guide**. It contains no
private spreadsheet links or Google credential.

## Before you start

You need an administrator account in Cathedra, permission to edit/share the three
spreadsheets, internet access, and permission to create/use a Google Cloud project,
enable its Sheets API and obtain an approved service account JSON key. A school
or workplace IT administrator may need to do the Google Cloud steps.

This uses a service account directly shared on each sheet. No Google Sheets
add-on, Apps Script, Google Drive API, OAuth consent screen or domain-wide
delegation is required. [Google: service accounts and direct file sharing](https://developers.google.com/workspace/guides/create-credentials#service-account).

## Part 1 — Prepare three destination spreadsheets

1. Open your intended workload, overload and faculty profile spreadsheets. If
   needed, create three blank spreadsheets at [Google Sheets](https://sheets.google.com/).
2. Give them recognizable names, such as **Cathedra — Faculty Workload**,
   **Cathedra — Overload Projection** and **Cathedra — Faculty Profile**.
3. Confirm you can edit and share each one. Review existing readers in **Share**
   and keep **General access → Restricted**. Different readers can be used on each.
4. Keep their existing tabs. Cathedra adds its own tabs alongside them.
5. Copy each full `https://docs.google.com/spreadsheets/d/…/edit` link and label
   which category it belongs to. The three spreadsheet IDs must be different.

A `#gid=…` suffix selects a tab inside one spreadsheet. Three tabs or three
different `gid` links in the same file are not three separate spreadsheets.
Cathedra normalizes the link to the spreadsheet's main edit URL.
Google explains sharing roles in its [file-sharing guide](https://support.google.com/drive/answer/2494822).

## Part 2 — Create or select a Google Cloud project

1. Open the [Google Cloud console](https://console.cloud.google.com/).
2. Sign in with the Google account authorized to manage this connection.
3. Use the project selector at the top to select an existing approved project, or choose **New project**. The console also provides **IAM & Admin → Create a Project**.
4. If creating one, enter a recognizable name, such as `Cathedra Sheets`.
5. Select the organization/location required by your school or office, then choose **Create**.
6. Wait for creation to finish and select that project before continuing. Keep the same project selected for the API, service account, and key steps below.

Project creation and API administration require permissions on your Google Cloud account. These permissions belong to the person doing setup and are separate from the service account's access to your sheet. [Google: create a Cloud project](https://developers.google.com/workspace/guides/create-project).

### Enable the Google Sheets API

1. In the selected project, open **APIs & Services → Library**.
2. Search for **Google Sheets API**.
3. Open **Google Sheets API**, then choose **Enable**.
4. If it already shows **Manage**, the API is already enabled for that project.

You can also open the [Google Sheets API library page](https://console.cloud.google.com/apis/library/sheets.googleapis.com) and check the selected project before enabling it. [Google: enable Workspace APIs](https://developers.google.com/workspace/guides/enable-apis).

Do not assume this setup has no costs under every policy or usage level. Check the project's current quota and billing requirements with your administrator. At this guide's review date, Google's usage page says standard use has no additional cost and over-quota charges are planned for later in 2026. [Google: Sheets API usage limits and pricing](https://developers.google.com/workspace/sheets/api/limits#pricing).

## Part 3 — Create the service account

1. In the same project, open **IAM & Admin → Service Accounts**.
2. Choose **Create service account**.
3. Enter a recognizable name, such as `Cathedra Sheet Export`.
4. Leave the generated service account ID, or choose a suitable ID before creation. Add a description if helpful.
5. Choose **Create and continue**, or **Done** if the console offers that shortcut.
6. If shown **Grant this service account access to project**, leave the optional role selection empty. This app needs access to the specific spreadsheet through its Share dialog; it does not need the Google Cloud **Owner** or **Editor** project role.
7. Leave the optional fields for people who can use/manage this service account empty unless your IT administrator requires an approved arrangement.
8. Choose **Done**.
9. Copy its **email address**. It ends in `.iam.gserviceaccount.com`. This is the address you will add to the spreadsheet.

If the console requires the IAM API to be enabled for service account administration, follow the console's prompt or ask IT. The data connection itself uses the Google Sheets API. Google's [service account creation guide](https://docs.cloud.google.com/iam/docs/service-accounts-create) describes these optional roles. Its [Workspace credentials guide](https://developers.google.com/workspace/guides/create-credentials#service-account) explains why Cloud IAM roles do not grant access to a Google Sheet.

## Part 4 — Download one JSON key

1. In **IAM & Admin → Service Accounts**, select the service account's email address.
2. Open the **Keys** tab.
3. Choose **Add key → Create new key**.
4. Select **JSON** as the key type.
5. Choose **Create**. Your browser downloads a `.json` file.
6. Move the file to a protected location you can find again. Do not edit the downloaded contents.

Google allows the private key to be downloaded only when it is created. If the original is lost, you create a replacement key rather than download the old one again. If **Create new key** is unavailable or an organization-policy error appears, ask IT to supply an approved key or connection approach. [Google: create and delete service account keys](https://docs.cloud.google.com/iam/docs/keys-create-delete).

**Keep the JSON private.** Do not paste its contents into chat, email, screenshots, GitHub, source files, or a shared spreadsheet. Do not include it in routine Cathedra database backups or release packages. Someone with the key can act as the service account against resources shared with it. Follow your organization's credential storage rules. [Google: managing service account keys](https://docs.cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys).

An API key or OAuth client configuration file will not work here. Use the JSON key downloaded from the service account's **Keys** tab.

## Part 5 — Connect each matching spreadsheet

1. Open Cathedra, sign in as an administrator, and open **Backup & Export**.
2. Find the three **Google Sheets** destination cards.
3. On **Faculty Workload**, choose **Connect Google Sheet**.
4. Paste the **workload spreadsheet** URL into **Google Sheet link**.
5. Under **Service account JSON key**, choose the JSON downloaded in Part 4.
   It must be no larger than **64 KiB**. Wait for the service account email.
6. In that spreadsheet's **Share** dialog, add the exact service account email
   as **Editor**. Deselect **Notify people** if shown, and apply the share.
7. Return to Cathedra and choose **Save connection**. Then **Test connection**.
8. Repeat on **Overload Projection**, using its own spreadsheet link. Choose
   the same JSON if using one service account, and share this spreadsheet too.
9. Repeat on **Faculty Profile**, using the profile spreadsheet link and sharing
   it with the displayed account. Review its readers because salary fields are included.
10. Confirm all three cards point to the intended **different spreadsheets**.

Saving a connection is local and does not upload records. **Test connection**
only reads spreadsheet metadata. It does not verify Editor/write permission;
the first successful update is the write check.

Each connection stores its own key and status in private files under
`data/.google-sheets` beside the active database. Windows protects saved keys for
the current Windows user using DPAPI. Database backups exclude all Google
connection settings and keys. Reconnect on another PC or Windows account using
the protected original JSON or an approved replacement.

## Part 6 — Perform the first category updates

1. Save current records and confirm this is the intended source computer.
2. On **Faculty Workload**, choose **Update workload sheet**, review its
   destination and workload-only confirmation, and confirm.
3. Wait for success and check that card's **Last successful update** and counts.
4. Use **Open Google Sheet** on that card. In **Cathedra Overview**, check
   **Snapshot generated at (UTC)** and sample records. The app displays its last
   successful update in local time. Confirm original tabs remain.
5. On **Overload Projection**, choose **Update overload sheet**, confirm, and
   check the overload spreadsheet in the same way.
6. On **Faculty Profile**, choose **Update profile sheet**, confirm the
   personnel/salary scope, and check the profile spreadsheet.

Each update affects only the selected connection. Success or failure on one card
does not change another card's last update. Disconnecting one does not disconnect
the others. An interrupted update may already have reached Google: check that
destination's Overview timestamp before retrying.

## Category tabs and boundaries

| Spreadsheet | Cathedra tabs |
| --- | --- |
| Faculty Workload | **Cathedra Overview**, **Cathedra Workloads**, **Cathedra Assignments**, **Cathedra Approved Workloads** |
| Overload Projection | **Cathedra Overview**, **Cathedra Overload Projection**, **Cathedra Overload Budgets**, **Cathedra Cost Settings** |
| Faculty Profile | **Cathedra Overview**, **Cathedra Faculty** |

Overview contains only the selected category's context, counts and relevant
warnings. Workload history preserves approved workload identity/hours instead
of recalculating historical values. Overload estimates use the app's existing
current Regular Faculty overload calculations, active office period and applicable
weeks; they are planning estimates rather than payments already disbursed.
Internal/external part-time teaching, salary projections, combined saved financial
estimates and qualification drafts are excluded from the overload spreadsheet.

If the overload period or cost settings are missing, the projection contains
headers and no estimate rows, with an explanation in **Cathedra Overview**.
Set the intended period/settings in Cathedra, save, and update that category again.
Profile and workload exports do not need projection settings.

Accounts, passwords, sessions, activity logs, private keys, internal import
provenance and raw stored snapshots are never exported.

Cathedra marks the tabs it creates. Updates replace only their marked category
tabs and clear surplus old rows. Other tabs remain in place. If an existing
unowned tab has a conflicting name, rename it while retaining its data; Cathedra
refuses to take ownership or overwrite it. Keep manual notes/formulas in your own
tabs because Cathedra's export tabs are replaced by the next update. App values
are written as literal cells, including formula-like text.

Each spreadsheet update is one atomic batch. A rejected batch applies none of its
changes; a lost response can leave the outcome uncertain. [Google: batch updates](https://developers.google.com/workspace/sheets/api/guides/batchupdate).

## Normal updates and connection changes

Save app records, open **Backup & Export**, and use the update button for the
category you need. Update all three individually if you want all reports refreshed.
No update is scheduled automatically after saving records, restarting or reconnecting
to the internet. You do not repeat Google Cloud setup each time.

To change a destination, share the new sheet with its saved service account as
Editor, choose **Edit connection** on that category, replace its link, leave the
key unselected to keep that category's saved credential, save and test. The new
spreadsheet must differ from the other category destinations. Previously exported
data in the old sheet remains; manage that sheet's sharing separately.

To replace a key, edit each connection using that key, choose the replacement
JSON, save and test. Share with the new email too if changing service accounts.
Have the Cloud administrator revoke the old key after the replacement works, or
immediately if exposed. [Google: key management](https://docs.cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys).

Choose **Disconnect** on one category to remove only its local saved connection
and key. Previously exported Google data remains. Revoke remote access through
the sheet's Share dialog or Google Cloud if needed. A shared service account's key
revocation affects every connection using that key.

## Upgrading from the single combined connection

A previous combined connection remains separate; its data, key and spreadsheet
are not silently migrated or deleted. The new interface shows a notice when one
is saved and does not offer a combined update button. Use three new separate
destinations and configure each explicitly. A sheet still assigned to the old
combined connection cannot be reused as a category destination. Existing combined
tabs stay available for historical reference.

To remove its saved local credential, choose **Disconnect previous connection**
in the notice and confirm. This keeps the old Google spreadsheet and its data;
the three category connections remain intact. The same action can clear unreadable
legacy settings before you reconnect. A linked settings directory needs manual
local-folder repair; the app refuses to follow it when disconnecting.

If you later reuse an older combined spreadsheet, review its readers and existing
tabs first. Disconnecting the app does not remove its old salary, profile or
workload tabs, and category updates preserve other tabs. Use fresh category
spreadsheets to keep each report exclusive without carrying old exported data.

## Troubleshooting

| What you see | What to check or do |
| --- | --- |
| A spreadsheet is already assigned | Use three distinct spreadsheet IDs, not different tabs of one spreadsheet. Use a separate sheet from the old combined connection too. |
| Another saved connection could not be checked | On the affected category choose **Disconnect**, or use **Disconnect previous connection** for old combined settings, then retry and reconnect with the original JSON. This keeps remote tabs and the other connections. A linked settings directory requires local-folder repair; do not overwrite another folder to work around it. |
| The Google Sheets cards are missing | Sign in to Cathedra as an administrator and open **Backup & Export**. |
| The sheet link is rejected | Copy the spreadsheet URL from the browser. Use the HTTPS `docs.google.com/spreadsheets/d/…` edit link, not a published-to-web link, a Drive folder, or a tab ID alone. |
| The JSON file is rejected | Choose the unedited service account JSON downloaded from Google Cloud. An API key, OAuth client file, screenshot, or renamed text file will not work. The maximum size is 64 KiB. |
| Google Cloud prevents project or key creation | Ask your IT administrator for an approved project/key. Do not weaken an organization policy to follow this guide. |
| Google Sheets prevents sharing with the service account | Your school or work account may restrict external sharing. Ask IT to approve or provide the appropriate destination and service account. Keep General access Restricted. |
| API disabled / 403 | Enable **Google Sheets API** in the project named by the selected JSON key. Confirm you did not enable it in a different project. Wait briefly after enabling and test again. |
| Not found / 404, or access denied / 403 | Check the spreadsheet link and share the exact service account email with the destination sheet. An inaccessible sheet can appear unavailable even when it opens under your personal Google account. |
| Test succeeds but update fails with permission denied | In the sheet's **Share** dialog, change the service account from Viewer/Commenter to **Editor**. Check for sheet protections that prevent the required edits. A read test does not verify write access. |
| Authentication error / 401, invalid or revoked credential | Check whether the key was revoked, expired, or replaced, or the service account was disabled. Save an approved replacement JSON key and test again. Make sure Windows date/time is correct. |
| Connection cannot be opened after moving the app or changing Windows users | Reconnect using the original protected JSON file or an approved replacement. Copying app data or restoring the database does not replace this step. |
| Offline / network / firewall error | Restore internet access. Ask IT whether access to Google's authentication and Sheets API endpoints is allowed, then test and update again. Local Cathedra records remain available. |
| Too many requests / 429 | Wait at least a minute before trying again. Avoid repeated clicks or simultaneous updates from several computers. Your administrator can review Google Cloud quotas. |
| A Cathedra tab name is already in use | Rename the existing unowned tab in Google Sheets, keeping its data. Retry after the conflicting name is free. Cathedra will not take ownership of an unrelated tab. |
| Timeout, lost connection, or update “not confirmed” | Open the sheet first. Check **Snapshot generated at (UTC)** in **Cathedra Overview** and a sample record. The request may have completed at Google before the response was lost. Retry only after checking; do not assume failure or click repeatedly. |
| Rows look old or a recent change is missing | Save the form in Cathedra, confirm this is the correct source computer/database and sheet, then update. Check **Last successful update** and the Overview timestamp. |
| Calculated costs/projections are missing | Read the warning in **Cathedra Overview**. Complete the required cost settings and select the intended active office period in Cathedra, save, and update again. No active period means the affected projection tabs contain headers without data rows. |

Google's [usage limits](https://developers.google.com/workspace/sheets/api/limits) explain quota responses and timeouts. If an error persists, give IT the message, action attempted, approximate time, and the service account email. **Do not send the JSON file or private key through chat or a support screenshot.**

## Setup completion checklist

- [ ] Sheets API enabled; approved service account and private JSON ready.
- [ ] Three different spreadsheet links assigned to their matching categories.
- [ ] Each sheet shared with its connection's account as Editor; readers reviewed.
- [ ] All three connections saved and read tests passed.
- [ ] Each category update succeeded; Overview timestamp and sample data checked.
- [ ] Existing tabs remain intact in all three spreadsheets.
- [ ] Original JSON kept private; reconnect plan documented for another PC.

The guide is not proof of a live Google update. Real credentials, spreadsheet
sharing and a successful confirmed update are needed on the intended computer.
