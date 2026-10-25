# Cathedra Faculty 0.3.6

The Faculty workspace has a new ink-and-cobalt visual identity with a warm canvas,
clear typography, consistent controls and responsive layouts. The application
continues to manage faculty profiles, academic backgrounds, workloads, approvals,
reports and financial planning.

## Changes

- Reworked dashboard with explicit reporting scopes, active-semester planning,
  coverage notices, review items and recent activity for administrators.
- Page navigation with **Ctrl+K** (or **Command+K**), filtered to the current role.
- Clearer faculty and workload directories, record counts and contained horizontal
  scrolling. Narrower tables avoid pinned-column overlap.
- Grouped faculty fields and three visible workload-entry sections: faculty and
  period, teaching assignments, then review and save.
- Consistent styles across reports, projections, settings, accounts, calendar,
  verification, recovery and the three Google Sheets destinations.
- Mobile control sizing, keyboard focus, reduced-motion support, and a dashboard
  print baseline that preserves textual figures without oversized SVG icons.
- Build dependency setuptools is pinned to 84.1.0, the patched version for the
  [Windows legacy-wheel installation advisory](https://github.com/advisories/GHSA-xmj3-9gf7-h52w).

Existing calculation rules, approval states, optimistic concurrency, unsaved-edit
confirmations and backend authorization remain unchanged. The database schema is
still **24**; this release adds no database migration.

## Install or update

Download the complete Windows ZIP from the
[0.3.6 release](https://github.com/sebas011/Cathedra-Faculty/releases/tag/v0.3.6-office.2),
extract all files and run **Install-or-Update.cmd**. Close Cathedra first. The
installer verifies the application and creates a complete private recovery copy
before replacing it; existing records and accounts stay in their data folder.

Original 0.3.2 installations remain supported by the corrected installer. Follow
the [migration guide](UPGRADE_FROM_032.md); do not edit the old manifest.

New installations start with an empty database. Public downloads and source do
not contain office records, accounts, Google credentials or private spreadsheet
links. Use Backup & Export to transfer existing records privately between PCs.

## Design handoff

The [design system](redesign-2026-10-24/DESIGN_SYSTEM.md) and
[implementation blueprint](redesign-2026-10-24/IMPLEMENTATION_BLUEPRINT.md) describe
the delivered UI. [HTML/Tailwind/HTMX templates](../design/faculty-redesign/templates/README.md)
are a separate engineering handoff; production remains React and TypeScript.
The proposed HTML adapters are not implemented API endpoints.
