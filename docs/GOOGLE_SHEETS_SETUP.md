# Google Sheets setup for Cathedra

Last reviewed: **22 October 2026**.

Use this guide to connect a Google Sheet once, then send your current Cathedra records whenever you press **Update Google Sheet**. The Google Sheets card is available to an **administrator** under **Backup & Export**.

To download another copy from the app, open **Connect Google Sheet** (or **Edit connection**) and choose **Download detailed setup guide** in the expanded setup area.

## What this connection does

- Sends a snapshot of the latest **saved records on the computer running Cathedra**. Save any open forms before updating.
- Runs only when an administrator chooses **Update Google Sheet** and confirms. Saving records in Cathedra does not automatically update Google Sheets.
- Creates and refreshes twelve Cathedra tabs inside your selected spreadsheet. Your existing tabs are kept.
- Includes faculty, workloads, assignments, approved workload history, cost settings, projections, and saved financial summaries, including **salary information**. Everyone who can access the spreadsheet may see that information.
- Sends data in one direction: **Cathedra → Google Sheets**. Changes in Google Sheets do not change Cathedra. Edits made inside Cathedra's export tabs will be replaced by the next update.

This is a shared report, not a replacement for Cathedra database backups or automatic synchronization between computers. If two computers hold different Cathedra data, the computer that performs the next update supplies the snapshot. Choose one current source computer for routine updates.

## Before you start

Have the following ready:

1. An administrator account in Cathedra.
2. A Google account that can edit and share the destination spreadsheet.
3. Permission to create or use a Google Cloud project, enable the Google Sheets API, and create a service account key. A school or workplace IT administrator may need to do these steps.
4. Internet access for Google Cloud setup, **Test connection**, and **Update Google Sheet**. Normal local Cathedra work remains available offline.
5. A protected location for the downloaded JSON key. It is a credential, similar to a password.

No Google Sheets add-on or Apps Script needs to be installed. This connection uses a service account: a Google identity for the app. It does not need the Google Drive API, an OAuth consent screen, or domain-wide delegation. Google documents direct sharing for access to a specific sheet. [Google: choosing credentials and direct file sharing](https://developers.google.com/workspace/guides/create-credentials#service-account).

Google's console wording can change. If your organization prevents project creation, key creation, or sharing with a service account, ask its IT administrator for help. Keep the organization's controls in place.

## Part 1 — Prepare the destination spreadsheet

1. Open the Google Sheet you want Cathedra to update. Use a sheet intended for the people who are allowed to see faculty and salary data.
2. Confirm that you have **Editor** or **Owner** access and permission to share it.
3. Keep the existing worksheet tabs. Cathedra adds its own tabs alongside them; you do not need to delete or empty anything.
4. Click **Share**. Check **General access** and keep it **Restricted**. Review the people and groups already listed, including any access inherited from a folder.
5. Copy the full spreadsheet link from your browser's address bar. It should begin with `https://docs.google.com/spreadsheets/d/`.

The part after `/d/` identifies the entire spreadsheet. A suffix such as `#gid=0` selects a tab in your browser; it does not limit Cathedra to that tab. Cathedra normalizes the saved link to the spreadsheet's main edit URL.

Google explains the available sharing roles and Restricted access in its [file-sharing guide](https://support.google.com/drive/answer/2494822).

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

## Part 5 — Choose the key in Cathedra and share the sheet

1. Open Cathedra and sign in as an administrator.
2. Open **Backup & Export**.
3. Find the **GOOGLE SHEETS** card, titled **Keep your shared sheet up to date**.
4. Choose **Connect Google Sheet**. The one-time setup and connection form expand.
5. Paste your spreadsheet URL into **Google Sheet link**.
6. Under **Service account JSON key**, choose the `.json` file downloaded in Part 4. The file must be no larger than **64 KiB**.
7. Wait until Cathedra displays the service account email under the file field. The app shows the email, not the private key.
8. In Google Sheets, open the destination spreadsheet and choose **Share**.
9. Paste the **exact service account email shown by Cathedra** into the field for adding people. Do not add your own personal email in its place.
10. Choose **Editor** for that service account.
11. Deselect **Notify people** if the option is present; service accounts do not have an inbox. Choose **Share** or **Send** to apply the permission.
12. Confirm that the service account is now listed as **Editor** and **General access** is still **Restricted**.

Sharing the individual spreadsheet grants the required document access. [Google: share a file directly with a service account](https://developers.google.com/workspace/guides/create-credentials#access-google-workspace-files-directly-with-a-service-account).

## Part 6 — Save and test the connection

1. Return to the expanded form in Cathedra.
2. Choose **Save connection**.
3. Confirm that the card shows **Connection saved**. This stores the connection locally; it does not upload your records or change the Google Sheet.
4. Choose **Test connection**.
5. Wait for the result and check that the connected sheet and service account shown on the card are the ones you intended.

**Test connection only reads spreadsheet metadata. It does not write cells and does not prove that the service account has Editor permission.** A Viewer can pass a read test and still fail the update. The first successful **Update Google Sheet** is the write check.

The app's connection settings and credential are stored separately in a `.google-sheets` folder beside the active database, normally `data/.google-sheets`. On Windows, the saved credential is protected for the current Windows user using Windows Data Protection (DPAPI). A different Windows user or computer cannot reuse that saved credential; reconnect using the original protected JSON or an approved replacement. Cathedra database backups do not include the connection settings or key.

## Part 7 — Perform the first update

1. Save any faculty, workload, cost-setting, or other forms you have been editing in Cathedra.
2. Check that this computer has the records you intend to publish.
3. In **Backup & Export → GOOGLE SHEETS**, choose **Update Google Sheet**.
4. Read the confirmation. It explains that faculty, workloads, approvals, and financial summaries, including salary information, will be sent and that Cathedra replaces its own tabs while keeping other tabs.
5. Choose **Update Google Sheet** in the confirmation to proceed, or cancel if the destination/access is wrong.
6. Wait for the result. Avoid starting another update while the card says **Updating…**.
7. Confirm that the card reports success and **Last successful update** shows the new time. Review the row counts from that update.
8. Choose **Open Google Sheet**.
9. Open **Cathedra Overview** and check **Snapshot generated at (UTC)**. This timestamp is in UTC; the app's **Last successful update** is displayed in your local time. Check a faculty row and a workload or financial summary against the saved records in Cathedra.
10. Confirm that your original tabs are still present.

The first update has succeeded only after the app confirms it and you verify the destination. A downloaded guide or a saved connection alone does not mean data has reached Google Sheets.

## The twelve Cathedra tabs

The exact tab names and contents are:

| Tab | What it contains |
| --- | --- |
| Cathedra Overview | **Snapshot generated at (UTC)**, snapshot context, record counts, and warnings about missing calculation settings. |
| Cathedra Faculty | Saved faculty profile details. |
| Cathedra Workloads | Saved faculty workload records. |
| Cathedra Assignments | Course/teaching assignments associated with workloads. |
| Cathedra Approved Workloads | Frozen approved workload history. Historical approvals remain historical snapshots, rather than being recalculated with today's settings. |
| Cathedra Cost Settings | Saved cost and compensation settings used by the app. |
| Cathedra Qualification Draft | Qualification-rate draft information, clearly identified as a draft that has **not been applied**. |
| Cathedra Salary Projection | Salary projection information based on the saved data and required settings. |
| Cathedra Teaching Projection | Teaching projection for the active office period. If no active period is set, the tab has headers and no projection rows. |
| Cathedra Saved Estimates | Summaries of saved estimates. |
| Cathedra Overload Budgets | Saved overload budget information. |
| Cathedra No Teaching | Saved records for faculty with no teaching assignment. |

When required cost settings are missing, Cathedra withholds calculated costs/projections and includes an explanation in **Cathedra Overview**. It also warns when no active office period is selected and leaves the affected projection tabs without data rows. Complete the missing settings in Cathedra, save, and update again.

Authentication accounts, passwords, sessions, activity history, internal credentials, and private keys are excluded. The spreadsheet is a reporting snapshot, so keep using **Backup & Export** database backups for recovery.

### How Cathedra keeps existing tabs

Cathedra marks the tabs it creates as its own. An update replaces only those marked export tabs and clears old rows that are no longer in the current snapshot. It does not delete all spreadsheet tabs. Your other tabs, including your original first tab, remain in place.

If an existing unowned tab already has a name Cathedra needs, the update stops rather than overwrite that tab. In Google Sheets, rename your existing tab to a different name, such as a name ending in `Original`, then retry. Do not delete useful data to resolve the conflict.

Keep manual notes and formulas in your own tabs. Text supplied by the app is written as literal text, including names or values starting with formula-like characters. The export does not execute those strings as Google Sheets formulas.

The changes are submitted together in one batch, including clearing stale exported rows. A rejected batch applies none of its changes. An interrupted response can still leave the final result uncertain, so use the timestamp check described below before retrying. Google documents this batch behavior in [Update spreadsheets](https://developers.google.com/workspace/sheets/api/guides/batchupdate).

## Your normal update routine

1. Finish and save the current records in Cathedra.
2. Connect to the internet.
3. Open **Backup & Export** and check the connected destination.
4. Choose **Update Google Sheet**, review the confirmation, and confirm.
5. Check the success message and **Last successful update**. Open the sheet when you need to review or share the report.

You do not need to repeat Google Cloud setup for each update. Closing the browser, restarting the app, or losing the internet does not schedule an update. When the internet returns, update manually when ready.

## Change, replace, move, or disconnect a connection

### Use a different sheet

1. Share the new spreadsheet with the saved service account as **Editor**.
2. In Cathedra, choose **Edit connection**.
3. Replace **Google Sheet link**.
4. Leave the key unselected to keep the saved credential, then choose **Save connection**.
5. Choose **Test connection**, check the new destination, then run **Update Google Sheet** when ready.

The old spreadsheet and its previously exported data remain. Manage its sharing separately if it should no longer be available to the service account or other readers.

### Replace a lost, expired, or revoked key

1. Ask the authorized Google Cloud administrator to create a new JSON key for the approved service account.
2. In Cathedra, choose **Edit connection**, choose the replacement JSON file, then **Save connection**.
3. Run **Test connection** and an update.
4. Have the administrator remove the old key in Google Cloud once the replacement works, or immediately if the old key was exposed. Removing a key in Google Cloud is separate from disconnecting this app.

If the replacement belongs to a different service account, share the spreadsheet with its new email as **Editor** too. Follow Google's [key management guidance](https://docs.cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys).

### Move to another computer or Windows account

Restore the intended Cathedra database using the normal backup procedure, then reconnect Google Sheets on that computer using the spreadsheet link and original protected JSON file, or an approved replacement key. The saved Windows credential is tied to the Windows user, and a database backup does not carry the Google connection credential. Check the restored records before updating the shared sheet.

### Disconnect

Choose **Disconnect** on the Google Sheets card and confirm. This removes the locally saved connection and credential. The Google Sheet and all data already sent to it remain. To revoke the service account's access at Google, remove it through the sheet's **Share** dialog or have the administrator revoke the key.

## Troubleshooting

| What you see | What to check or do |
| --- | --- |
| The Google Sheets card is missing | Sign in to Cathedra as an administrator and open **Backup & Export**. |
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

- [ ] Google Sheets API enabled in the intended project.
- [ ] Approved service account and JSON key created.
- [ ] Original JSON stored privately outside source code and routine database backups.
- [ ] Destination sheet shared with the exact service account email as **Editor**.
- [ ] General access kept **Restricted** and existing readers reviewed.
- [ ] Connection saved in Cathedra and destination checked.
- [ ] **Test connection** successful.
- [ ] First **Update Google Sheet** successful; Overview timestamp and sample records verified.
- [ ] Original spreadsheet tabs confirmed intact.

This guide describes the setup procedure. A live Google connection and update require your Google credentials and must be completed and verified on your computer.
