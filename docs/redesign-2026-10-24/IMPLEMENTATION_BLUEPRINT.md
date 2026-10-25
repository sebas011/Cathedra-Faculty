# Cathedra Faculty — UI/UX implementation blueprint

Prepared 24 October 2026; implementation notes updated 25 October 2026. This handoff follows the user's clarification that the
redesign targets the **current Faculty app**. Faculty profiles, academic
background, teaching workloads, review and approval, overload estimates, reports,
Google Sheets connections and local recovery remain the product's domain.
Scholar, grant and disbursement modules are not part of this implementation.

The existing application uses React, TypeScript and React Router over the local
FastAPI service. HTML, Tailwind and HTMX examples below describe equivalent
rendering patterns for this interface. They are handoff examples, not a decision
to replace the current framework or claims that new fragment endpoints exist.

## 1. Product direction

**Cathedra Faculty is an office workspace for moving from complete records to
reviewed workloads and defensible planning estimates.** The redesign makes that
sequence visible: locate a record, understand its state, complete the missing
information, then review or export the result.

The visual identity combines a warm paper canvas, an ink navigation rail, cobalt
actions and restrained apricot emphasis. Content leads the page; decorative
effects do not compete with tables or financial figures. Generous section spacing
is paired with compact row spacing, so a calm screen can still hold useful data.
The previous green styling is not a constraint.

### Functional invariants

- Existing routes, record identifiers, API contracts, permissions and account
  recovery behavior remain valid.
- Workload calculations, imported-hour precedence, compensation rules,
  allocation policy, frozen approval history and provisional-status treatment
  retain their current meaning. The interface formats server results; it does
  not introduce an alternative calculation.
- Office-period settings control the shared dashboard semester. A person's
  temporary report filters do not silently change that office setting.
- An unavailable figure is not displayed as zero. A provisional difference is
  labeled before the user reaches an export or planning decision.
- Salary and teaching values are planning estimates, not actual payroll paid.
  Regular Faculty overload remains distinct from internal/external part-time
  teaching, and historical approvals remain distinct from current calculations.
- Database backups, restore confirmation, administrator access and the three
  independent Google Sheets destinations retain their existing protections.

## 2. Information architecture and navigation

Use one persistent workspace shell with a short primary rail and contextual
navigation within Reports and Settings. The rail communicates destination, while
page tabs communicate the view inside that destination. Do not put record-level
commands in the primary navigation.

| Navigation group | Destination | Existing route | Main task |
| --- | --- | --- | --- |
| Workspace | Dashboard | `/` | Review workload totals, office-period estimates and outstanding checks |
| Workspace | Faculty Profile | `/faculty-profiles` | Find a person, inspect academic background and update permitted details |
| Workspace | Faculty Workload | `/workload` | Locate records by year/term, manage assignments, review and approve |
| Workspace | Expenses Projection | `/expenses` | Inspect Regular Faculty overload against the intended semester; administrator only |
| Review & reporting | Reports | `/reports` | Open approved history, salary/teaching planning and saved estimates |
| Review & reporting | Needs Verification | `/verification` | Resolve record gaps without treating an incomplete queue as clear |
| Review & reporting | Semester Closeout | `/semester-closeout` | Use the existing administrator closeout workflow |
| Review & reporting | Academic Calendar | `/calendar` | Review existing academic calendar information |
| Office tools | Settings | `/settings` | Open authorized compensation, office-period and account controls |
| Office tools | Backup & Export | `/backup-export` | Protect local records and update the three Google Sheets reports |
| Office tools | System Readiness | `/system-readiness` | Inspect current readiness checks |
| Office tools | Activity History | `/activity` | Inspect recorded actions; administrator only |
| Office tools | Office Guide | `/office-guide` | Open existing local operating guidance |

Existing direct links such as `/workload/:id`, `/workload/:id/edit`,
`/faculty-profiles/:id`, `/reports/workload`, `/reports/projection` and
`/reports/saved-estimates/:id` remain usable. Existing legacy redirects remain in
place. Administrator-only destinations stay guarded by both the existing React
access checks and their API authorization.

### Shell anatomy

1. **Skip link:** first keyboard target, visible on focus; moves to the main page.
2. **Navigation rail:** wordmark, grouped links, active marker and account/exit
   controls. The active link uses `aria-current="page"` and a non-color cue.
3. **Workspace header:** current destination, real account context and a working
   **Jump to a page** dialog opened by its button or Ctrl/Command+K. It filters
   the existing destinations permitted to the user; it does not search records.
   Record search remains inside its directory.
4. **Page heading:** one `h1`, a one-sentence purpose, visible reporting scope and
   one primary action. Secondary actions use quieter styling.
5. **Content canvas:** metric strip, task panels, filters, tables or forms.
6. **Feedback layer:** inline validation near its field, page-level outcome at
   the relevant section, and modal confirmation only for meaningful decisions.

## 3. Design system contract

The canonical implementation stylesheet owns the `--ui-*` tokens. Components
reference roles rather than restating hex values. Legacy CSS selectors may be
adapted to those roles during migration so every existing page receives a
coherent treatment before individual screens are reworked.

| Role | Reference value | Use |
| --- | --- | --- |
| Canvas | `#F6F7F4` | Main workspace background |
| Ink | `#182231` | Main text and navigation surface |
| Primary | `#3154D9` | Main actions, selected controls and data emphasis |
| Accent | `#F3B189` | Secondary editorial highlights and selected chart series |
| Surface | `#FFFFFF` | Tables, forms and panels |
| Muted text | Tokenized neutral with verified contrast | Supporting copy and metadata |
| Border | Tokenized neutral | Row separators, form outlines and panel boundaries |
| Danger / warning / success | Dedicated semantic tokens | Validation and record-state feedback, with visible text/icons |

Typography uses the shipped UI/display font tokens with a system fallback so
the desktop app remains readable offline. Do not make a font download a
prerequisite for showing records. Use tabular numerals for counts, money and
hours; preserve name readability and localized currency formatting.

| Element | Target treatment |
| --- | --- |
| Page title | Georgia, regular weight, responsive 30–40 px; dashboard hero 32–44 px |
| Section title | 18–20 px, strong weight |
| Body and inputs | 14 px base and field text in the current CSS; consider 16 px fields if mobile browser zoom testing requires it |
| Table text | 13–14 px; identifiers and metadata remain readable |
| Helper text | Generally 11–13 px; compact nonessential labels 9–10 px in the current CSS; no warning solely in small labels |
| Spacing | 4 px base; 8/12/16 px control spacing, 24/32 px section spacing |
| Controls | 40–44 px practical target; visible keyboard focus |
| Corners | Small control radius and modest panel radius; avoid decorative nested cards |
| Motion | Short state transitions; disable nonessential motion for reduced-motion users |

### Shared component inventory

| Component | Required variants and behavior |
| --- | --- |
| `WorkspaceShell` | Desktop rail, narrow-screen menu, current location, skip link, main landmark |
| `WorkspaceSearch` | Native modal, role-filtered page destinations, query/empty state, Ctrl/Command+K and Escape |
| `RecentActivity` | Five actual activity entries for administrators; independent loading, empty, retry and failure states |
| `PageHeader` | Title, purpose, breadcrumb/context, primary action and optional secondary actions |
| `MetricStrip` | Value, label, scope, source note; unavailable and provisional states |
| `ScopeBar` | Academic year, term and active-office indicator; personal filters distinguished from shared settings |
| `ActionQueue` | Issue, affected scope/count and direct existing resolution link; partial/error/empty states |
| `FilterToolbar` | Labeled search, filters, reset, result count and page state |
| `DataTable` | Semantic headings, stable row keys, numeric alignment, loading/empty/error states and scroll region |
| `StatusBadge` | Text plus icon/shape; Draft, Reviewed, Approved and relevant coverage statuses |
| `FormSection` | Heading, explanation, labels, field errors and permission/read-only treatment |
| `AssignmentEditor` | Add/edit a course assignment; retain existing lecture/lab validation and row identity |
| `RecordActions` | Existing permitted edit/review/approve/reopen/delete actions; no invented bulk approval |
| `ConfirmationDialog` | Accessible modal, clear consequence, safe initial focus and opener-focus restoration |
| `FeedbackNotice` | Informational, warning, error and success; action stays close to its affected content |
| `GoogleSheetsDestinationCard` | Independent destination, account, last success, test/update/disconnect and key-file state |

## 4. Screen specifications

### Overview: evidence first, next action second

The first viewport answers **what period is this, how much work is recorded and
what needs attention?** A title/context row leads into a workload metric strip.
For administrators, a planning panel shows the shared office semester and the
existing Regular Faculty overload-versus-budget result. A visible coverage label
travels with that figure.

Use a two-column lower workspace on wide screens: department/college comparison
and supporting planning summaries on the wider side, actionable checks on the
other. A comparison chart has named series, visible values and a readable table
equivalent. Its labels must match the API grouping: a college aggregation cannot
be relabeled as a department aggregation solely for visual copy.

Keep independent data-source loading and error states. A failed budget request
does not replace successful workload totals with a full-page failure. A partially
loaded attention queue says it is incomplete and offers its existing retry.
Staff do not see administrator-only financial panels or actions.

The administrator dashboard now loads its five-entry Recent activity feed from
the existing activity API and links to `/activity`. Staff do not request this
administrator-only feed. Loading, empty and retry states are independent of the
other dashboard panels. There are no invented trend deltas or year-over-year
growth claims without comparable data from the same scope.

### Faculty directory and profile

The directory prioritizes name, college/department, rank or appointment context,
and record state. Search and filters sit immediately above the table with a
visible result count. Keep the existing pagination, debouncing, request ordering
and directory-memory behavior; avoid fetching an entire database merely to
achieve a visual filter.

The person's name remains a real detail link. A preview drawer can be added as a
progressive enhancement later, with a full-page fallback, but the initial redesign
must not replace working profile navigation with a nonfunctional drawer.

In the detail view, group fields under **Identity & organization**, **Appointment
& salary**, **Academic background**, and **Notes & source**. Academic fields keep
the existing bachelor's, master's and doctoral degree semantics. Do not introduce
a repeatable academic-history data model unless its persistence and migration
are separately implemented. A layout can improve the grouping without changing
what the database records.

Use explicit Save Changes and Cancel behavior. Read-only salary-driving fields
remain readable to the extent existing authorization permits; their editing
controls follow existing field permissions. Leaving a dirty form retains the
existing unsaved-change confirmation. A failed save keeps entered values.

### Workload directory, assignment entry and approval

The directory shows academic year and term before hours or cost. Keep **Records**
and **Data checks** as recognizable views. Each record's state is visible before
the user opens its action menu. Row actions are real buttons or links with an
accessible label that identifies the record.

The implemented editor has three visible anchor-linked sections: **Faculty &
period**, **Teaching assignments**, and **Review & save**. All fields remain in
the same form; changing sections does not hide controls or save partial records.
The review summary identifies the person, period and assignment count. A sticky summary may show current
lecture/laboratory/weekly hours and existing preparation/overload results, but it
does not become an alternative source of compensation math. On a narrow screen,
the summary becomes a normal section after the assignments.

Assignment entry remains fast: aligned course code/title/section fields, lecture
and laboratory hours, an explicit Add/Save Assignment action, then a compact
assignment list with edit/remove controls. Required-field and numeric-range errors
stay next to their controls, and focus moves to the first invalid field or error
summary after submission.

Preserve the workflow boundary: Draft can be edited, review/approval actions use
their existing permissions and revisions, and Reviewed/Approved records require
the existing administrator reopen flow before editing. Approval details and
frozen summaries remain discoverable through their current routes. Styling must
not imply that a current calculation rewrites historical approved values.

If a true multi-step editor is added later, it is an interaction over the same
final payload: back/next preserves unsaved data, the review step shows all entered
values, and the final action submits once. Intermediate progress is not called
saved unless a backend draft has actually been committed.

### Overload and reports

Put the academic year, term and filter scope above every total. Show **Regular
Faculty overload**, the recorded semester budget and the corresponding difference
as distinct values. A missing budget is an action to set the amount, not zero.
A provisional result must keep its coverage explanation visible beside the value.

The detailed salary/teaching report retains its broader scope, including part-time
teaching and salary estimates, with clear navigation from the overload view.
Saved estimates are historical saved snapshots. Current recalculation, frozen
approval and saved estimate are different states with different copy and dates.

Tables use currency/hours headers, right-aligned numerical values and consistent
rounding for display. Retain full-precision server calculations and existing
export/print behavior. A dash means unavailable rather than zero payment.

### Backup, export and connected spreadsheets

Organize the page into **Local recovery**, **Spreadsheet reports** and **Exports**,
keeping the existing controls and authorization. Restore remains a separately
confirmed operation that explains record/account replacement and sign-out.
Backup protection, download and deletion behavior are unchanged.

The three spreadsheet cards remain separate: Faculty Workload, Overload
Projection and Faculty Profile. Each has its own destination and last-success
status. Do not combine their credentials, imply automatic synchronization or
change one card's state in response to another card's update. Display only the
service-account email; retain private key-file handling and sanitization.

## 5. Data-heavy interaction rules

| Situation | Required interaction |
| --- | --- |
| Filtering | Keep a stable toolbar and table heading; show the new scope and count; apply only the latest request response |
| Sorting | Use actual supported sorting; preserve stable secondary order; add `aria-sort` only to the sorted column |
| Selection | Do not add row checkboxes without a concrete permitted action and defined scope; never imply bulk approval exists |
| Dense data | Provide horizontal overflow and a labeled keyboard-accessible scroll region; preserve the name/action columns |
| Pagination | Visible page and total; changing search/filter resets or clamps to a valid page using current logic |
| Empty directory | Explain there are no records and show the permitted creation action |
| No filter matches | Keep filters visible, name the active scope and offer Clear filters |
| Failed request | Keep successful independent content; show Retry for the failed area and avoid stale values posing as current |
| Save in progress | Prevent duplicate submission; show the active action and preserve form values |
| Timeout/unknown save | Say the save is unconfirmed and ask the user to check the record before retrying |
| Revision conflict | Preserve the user's input, explain the newer server record and offer reload/compare; never silently overwrite |
| Unsaved navigation | Keep the existing dirty-form guard; Cancel returns to the same input and scroll context |
| Permission change | Respect the service response; do not expose hidden salary actions after session/role changes |

## 6. Responsive and accessible behavior

| Width | Shell and content behavior |
| --- | --- |
| Above 1250 px | Persistent 248 px rail (76 px collapsed); dashboard main grid uses two columns; 36 px canvas gutters above 1180 px |
| 761–1250 px | Persistent collapsible rail; dashboard main grid becomes one column; gutters reduce to 24 px at 1180 px |
| 761–900 px | Supporting dashboard panels also stack; filters wrap; readable tables retain their own scroll area |
| 760 px and below | A 264 px menu opens over the canvas; 16 px gutters; headings/actions stack; form columns collapse; tables scroll within their region |
| 640 px and below | Workload section links stack; review summary becomes one column; record-row actions use 44 px targets |
| 320–390 px | No viewport-wide horizontal overflow; controls remain reachable and long names wrap; no fixed action bar obscures fields/errors |

Use semantic `nav`, `main`, `section`, `form`, `fieldset`, `label` and `table`
elements. Avoid `role="grid"` unless full grid keyboard behavior is implemented;
a normal data table with real controls is the default. An icon-only action needs
a meaningful accessible name, and status/color is always accompanied by text.

Keyboard order follows reading order. Escape closes a dismissible modal/menu,
focus is contained in an open modal, and closing returns focus to its opener.
Visible focus remains discernible on both ink and white backgrounds. Use polite
live announcements for outcomes/count changes and assertive alerts for failures
requiring immediate attention. Do not announce every keystroke or skeleton cell.

Check normal text at 4.5:1 and large text/interface boundaries at their applicable
contrast targets. Apricot is an accent, not a default text-on-white color. Check
200% zoom, keyboard-only operation, reduced motion and a screen-reader pass on
the directory, editor and confirmation flow. Print CSS removes navigation and
interactive controls while retaining scope, dates, values and record context.

## 7. React implementation map

| Existing file or pattern | Redesign responsibility | Preserve |
| --- | --- | --- |
| `frontend/src/components/AppShell.tsx` | New identity, rail/header structure and responsive shell | Outlet, real navigation, active state, current user and Exit Cathedra |
| `frontend/src/pages/DashboardPage.tsx` | Hierarchy, metric strip, planning panel and action queue | Existing API calls, independent failures, office-period ownership and admin financial access |
| `frontend/src/components/WorkspaceSearch.tsx` | Working keyboard-accessible page navigation | Existing destinations and role restrictions; no record-search claim |
| `frontend/src/components/RecentActivity.tsx` | Actual administrator activity feed with retry | Existing activity API and authorization boundary |
| Faculty list/detail pages | Filter/table/form presentation and academic grouping | Real data, revisions, field permissions and unsaved-change handling |
| Workload list/form/detail pages | Scannable records, assignment editor and clear workflow state | Calculations, imported values, review/approval/reopen and record links |
| Expenses/report pages | Visible scope, readable figures and coverage hierarchy | Existing server totals, provisional treatment, snapshots and export semantics |
| `GoogleSheetsCard.tsx` | Cohesive destination cards and feedback presentation | Three independent settings/keys/states, confirmations and safe outbound links |
| `ConfirmationDialog.tsx` and `useActionDialog` | New visual treatment | Native modal behavior, safe focus, cancellation and existing consequences |
| `TableRegion.tsx` | Shared overflow treatment | Labeled region and keyboard scrolling |
| Shared CSS/tokens | New palette, typography, spacing and component states | Existing layouts' functional visibility and print output |
| `frontend/src/api/client.ts` | No visual rewrite needed | Session handling, authorization, timeout/unknown-save messages and error sanitization |

Do not migrate framework, persistence or authentication as a side effect of this
visual work. Remove old hardcoded styling incrementally only after its selectors
have been mapped to the new system and affected screens have been checked.

## 8. Tailwind / HTML / HTMX handoff patterns

These are proposed HTML-rendering equivalents. **The listed fragment routes do
not exist in the current React product.** Implementing them later requires a
separate routing/authentication decision, server templates and tests. Keep the
existing React JSON endpoints as the current source of data and authorization.

Use semantic HTML and native form/link actions first. Tailwind may reference the
shared CSS custom properties, for example `bg-[color:var(--ui-canvas)]` and
`text-[color:var(--ui-ink)]`; compile the required classes locally for the offline
desktop package. A CDN script is not an offline production dependency strategy.

| Proposed HTML contract | Full-page fallback | Enhanced response |
| --- | --- | --- |
| `GET /faculty-profiles?search=…&college=…&page=…` | Directory page | Results region, count and pagination from the same query |
| `GET /faculty-profiles/{id}` | Complete profile | Optional future preview content with a real full-profile link |
| `GET /workload/new` | Existing-field editor page | Editor panel, only if its navigation/focus behavior is implemented |
| `POST /ui/workload-form` | Validate existing workload payload and render outcome | Proposed server adapter; calls the same business service and revision checks |
| `GET /ui/overview` | Office overview page | Independently refreshable real metrics and attention region |

Do not point HTMX directly at a JSON endpoint and expect an HTML fragment. The
proposed `/ui/…` layer must render escaped server-owned HTML and must not recreate
business logic in template expressions. Full-page and fragment responses can
negotiate with `HX-Request`; cache them with `Vary: HX-Request` and appropriate
private/no-store policy so authenticated fragments are not shared across users.

```html
<!-- Proposed server-rendered equivalent; these fragment routes require implementation. -->
<form action="/faculty-profiles" method="get"
      hx-get="/faculty-profiles" hx-target="#faculty-results"
      hx-select="#faculty-results" hx-swap="outerHTML"
      hx-push-url="true" hx-indicator="#faculty-loading">
  <label for="faculty-search">Search faculty</label>
  <input id="faculty-search" name="search" type="search"
         autocomplete="off" value="{{ escaped_search }}">
  <button type="submit">Search</button>
  <span id="faculty-loading" class="htmx-indicator" role="status">Loading records…</span>
</form>
<section id="faculty-results" aria-labelledby="faculty-results-heading">
  <h2 id="faculty-results-heading">Faculty records</h2>
  <!-- Server-rendered escaped count, semantic table and pagination. -->
</section>
```

`{{ escaped_search }}` denotes escaped template output, not a ready-to-use
engine-specific expression. URL encoding, HTML escaping, authorization and filter
validation remain server responsibilities. GET requests must remain read-only.

### Mutation and error contract for a future HTML adapter

- Authenticate every request and authorize both the resource and edited fields.
  A cookie-based adapter requires its own CSRF protection; the current React
  bearer-token transport must not be silently replaced or stored in markup.
- Submit the same record revision/ETag required by the existing mutation.
  Surface a 409 conflict with the entered values preserved. Do not force a retry
  using a new revision without the user's review.
- Return escaped field errors with the submitted values for validation failures.
  HTMX does not swap all error statuses by default: explicitly define a scoped
  response policy for 422 validation and 409 conflict fragments, then focus the
  error summary/first invalid field. Do not globally swap arbitrary error bodies.
- Handle 401 as a full authentication transition, not a login form inserted into
  a table. Handle 403 as denied access without inventing an elevated client role.
- Use a post/redirect/get outcome for native full-page submission and an explicit
  successful fragment/redirect for enhanced submission. Only announce “Saved”
  after the server confirms persistence.
- Disable the submitting action while it is in flight; idempotency and retry
  behavior must be defined for any operation that can create duplicate records.
- Keep templates and request URLs same-origin. Do not use inline event strings
  that interpolate record data into JavaScript or permit arbitrary target HTML.
- Protect sensitive drafts. Keep the current in-memory editing behavior unless
  an explicit, authenticated draft-storage feature is designed. Do not silently
  put personnel, salary, account or Google-key material in browser local storage.

## 9. Five delivery phases and acceptance gates

| Phase | Deliverable | Gate before moving on |
| --- | --- | --- |
| 1 — Foundation | `--ui-*` tokens, typography, buttons/fields/notices, shell/navigation and print baseline | No inaccessible focus states, unreadable text or hidden existing actions at desktop/mobile widths |
| 2 — Overview | Real metric hierarchy, explicit office period, overload coverage/budget and actionable checks | Figures and destinations match the existing API; staff/admin views and partial loading failures work |
| 3 — Records | Faculty/workload directories, profile sections and assignment-entry presentation | Search, filters, pagination, unsaved edits, permissions and all existing record actions still work |
| 4 — Planning and operations | Expense/report scope, snapshots, sheets, backup/restore and account visual alignment | Financial meanings, independent sheet settings and destructive confirmations remain intact |
| 5 — Verification | Responsive/keyboard/contrast/print review and existing automated regression gates | Current checks pass; representative create/edit/review/approve/reopen/export/restore flows pass on disposable data |

The present React redesign can complete phases without implementing any HTMX
adapter. The page-jump dialog and real administrator dashboard feed are included
in the source changes. A framework migration, profile preview drawer, persistent
staged drafts or cross-module record search remain separate scope.

### Current implementation status

The production React entry imports `operations-design.css` instead of the prior
visual theme. The shell, dashboard, faculty/workload registers and workload-entry
presentation have been changed. Shared screen-only styles also align existing
reports, settings, recovery and account screens. Existing print rules remain
separate. No backend, database schema, routes or financial rules were changed
for this redesign.

The companion `DESIGN_SYSTEM.md` records exact implementation tokens and states.
Equivalent HTML/Jinja/Tailwind/HTMX handoff files are in
`design/faculty-redesign/templates/`; they are not active product routes.

Frontend verification passed: lint, test TypeScript checks, all 136 tests in
15 suites, and the production build. Live checks exercised the main page families,
the page-search shortcut, unsaved-edit cancellation, and narrow layouts using
isolated synthetic data. See `VERIFICATION.md` and `layout-checks.json` for the
scope and limitations. This is source implementation evidence, not a claim of
physical print, live spreadsheet upload or office-device acceptance.

### Completion evidence

Record which screens changed, what meaningful interactions were exercised, the
viewport sizes checked, automated check results and any remaining limitations.
Use synthetic/disposable records for verification. Keep real office databases,
account credentials and spreadsheet keys out of screenshots, fixtures and public
design examples. Do not claim a live Google upload, physical print or restored
office-device acceptance from a static prototype or a passing layout check.
