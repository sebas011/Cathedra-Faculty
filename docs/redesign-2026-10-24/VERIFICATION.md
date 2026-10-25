# Faculty redesign verification

Verified on 25 October 2026, Asia/Manila. The redesign targets the current Faculty
application. The separate scholar/grant description was superseded by the user's
clarification. This delivery changes frontend presentation and navigation; it does
not change compensation formulas, database schema or backend permissions.

## Automated checks

| Check | Result |
| --- | --- |
| Frontend ESLint | Passed, including the final source presentation changes |
| Test TypeScript compilation | Passed |
| Frontend regression suite | 15 suites, 136 tests passed |
| Production TypeScript/Vite build | Passed after the final visual refinements |

New behavioral coverage verifies keyboard page search, destination filtering and
navigation, empty results and Escape, activity failure/retry and UTC timestamps,
the five-event summary, and no administrator activity/finance requests for staff.
Existing financial coverage still distinguishes confirmed zero from missing
coverage. The final refinements after the regression run were CSS and table-help
copy; they were checked through lint, production builds and the live browser.

## Live application checks

The production frontend build was served by a separate local backend using an
isolated, disposable database: eight synthetic faculty profiles, six draft
workloads, an office period and a sample overload budget. No office records or
installed application files were used for these checks.

The browser opened these page families successfully, with their real data reads:

- Faculty directory, individual faculty profile, workload directory, workload
  details, workload editing and new workload entry.
- Expenses projection, overall reports, office settings, Backup & Export and
  Academic Calendar.
- Needs Verification, System Readiness, semester closeout, Activity History and
  Office Guide.
- Dashboard totals, active-semester planning, coverage notice, academic-unit
  comparison and real recent activity.

Recorded desktop layout checks found no document-wide horizontal overflow and no
unlabelled visible main-content fields in the inspected states. This is a limited
DOM label check, not a complete accessibility scanner. Narrow checks covered the
dashboard, faculty directory, workload entry, expenses, backup, settings and
calendar. Tables scroll inside their own regions.

The browser's existing zoom affected requested viewport dimensions. Requested
1280 px produced approximately 1422 CSS px; the normal panel was approximately
913 CSS px; requested 320 px produced approximately 355 CSS px with a 338 px
document content area after its scrollbar. Final desktop captures used a requested
1152 px, producing approximately 1280 CSS px. `layout-checks.json` records measured
dimensions rather than assuming the requested pixels equal CSS pixels. Temporary
viewport overrides were reset after verification.

Interactions exercised:

1. Open page search with Ctrl+K, filter destinations and follow a result.
2. Open page search while a workload contains unsaved edits. The existing
   confirmation blocks leaving; choosing **Stay and keep editing** retains the
   entered academic year. No record was saved by this check.
3. Close page search with Escape; open and close the mobile navigation with
   Escape and observe its expanded state reset.
4. Focus and horizontally scroll the faculty grid with Arrow Right. At narrower
   desktop widths both edge columns are static, so pinned columns cannot cover
   the middle cells. A visible scrolling hint accompanies the grid.
5. Inspect grouped faculty fields, the three visible workload sections, review
   summary and save bar. Check mobile header controls at approximately 44×44 CSS
   pixels, and confirm narrow KPI values remain legible.

## Accessibility review

The design-system document records calculated token contrast. The final pass
corrected the search trigger's accessible name, mobile control dimensions, input
boundaries, table focus styling and narrow-table overlap. Empty/error/loading
states and explicit financial coverage labels remain visible. Semantic success
states retain green; cobalt identifies primary actions and selection.

This was a focused WCAG 2.1 AA review using rendered screens, DOM information,
keyboard actions and token calculations. NVDA/VoiceOver, a dedicated axe run,
200% browser zoom acceptance and physical printing were not performed. It is not
a claim of complete WCAG conformance.

Before release packaging, review identified that the new dashboard stylesheet
needed its own print rules. A print baseline now hides decorative SVGs, preserves
scope/coverage and monetary text, and lays out figures without intrinsic SVG
sizes. It is a source correction; physical-print acceptance is still separate.

Release review corrected a dashboard print regression: replacing the old shared
dashboard stylesheet with screen-only styling had removed the SVG dimensions in
print media. A separate print baseline now hides decorative dashboard icons and
navigation, formats the textual KPI totals, and retains reporting scope, coverage
notices, review items, department values and activity timestamps. This correction
was verified from the stylesheet rules; physical printing remains untested.

## Handoff and release boundaries

The HTML/Jinja/Tailwind 3/HTMX files are a separate implementation kit. Static
template/form checks and configuration loading passed; Jinja rendering and
Tailwind compilation were not run because those compilers are not installed.
The kit's README defines the required context and proposed adapter contracts.
Those adapters are not implemented product endpoints.

The installed office app, office database and GitHub release were not updated by
this redesign. Live Google uploads, restore operations, physical printing and
office-device release acceptance were not exercised. Existing automated checks
remain the evidence for unchanged workflows; this visual pass does not replace
the release deployment process.

## Previews

- [Desktop dashboard](dashboard-desktop.png)
- [Mobile dashboard](dashboard-mobile.png)
- [Faculty directory](faculty-directory-desktop.png)
- [Desktop workload entry](workload-entry-desktop.png)
- [Mobile workload entry](workload-entry-mobile.png)
- [Measured layout checks](layout-checks.json)

All displayed people and figures are synthetic demonstration data.
