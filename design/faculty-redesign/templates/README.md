# Faculty redesign: HTML, Tailwind and HTMX handoff

These eight files are **engineering templates**, not an additional running app.
The production application remains React + TypeScript. No dependencies, endpoints,
authentication mechanisms or production records were added by this template kit.
Every example uses the actual Faculty domain: profiles, academic backgrounds,
workloads, approval states and salary/teaching planning estimates.

## Files

| File | Responsibility |
| --- | --- |
| `base.html` | Shared shell, semantic navigation, feedback, icon/pill/field macros |
| `dashboard.html` | Executive overview, scoped estimates, attention queue, activity |
| `faculty-directory.html` | Search/filter, identity-first grid, empty state, pagination |
| `faculty-form.html` | Appointment, academic background and optional profile details |
| `workload-form.html` | Section steps, assignment editor, review and final save |
| `theme.css` | Shared components, focus, responsive and print treatment |
| `tailwind.config.cjs` | Tailwind CSS **3.x** compatibility configuration |

Compile `theme.css` with an already approved, locally installed Tailwind CSS 3.x
toolchain and this configuration. Publish its output as `/assets/cathedra-redesign.css`.
This versioned configuration is deliberate; it is not a claim about the newest
Tailwind version. The current React build does not need Tailwind installed.
For a Tailwind 4 integration, port the same tokens through that version's build
configuration rather than mixing this 3.x input with its compiler conventions.

Render `.html` with a Jinja-compatible renderer configured with **autoescaping**.
`base.html` provides inherited macros. All attributes and text remain escaped;
do not mark personnel names, notes, URLs or server errors `safe`. Vendor an
approved HTMX build at `/assets/vendor/htmx.min.js`; no CDN/network dependency is
included. Do not put bearer tokens or private keys into these documents.

## Proposed server-rendering adapter contracts

The `/ui/...` routes below are **proposed adapters, not existing FastAPI routes**.
Existing `/api/v1/...` endpoints exchange JSON and use the application's current
authorization/concurrency checks. HTMX form submissions must not be pointed at
those JSON endpoints without a conversion and authentication layer.

| Proposed route | Request | Response / existing business integration |
| --- | --- | --- |
| `GET /ui/faculty` | Search, service status, page | Full directory; adapter calls existing faculty page read with matching filters |
| `GET /ui/fragments/faculty` | Same read-only parameters | `#faculty-results` fragment; render `directory_results` macro |
| `GET /ui/faculty/new`, `GET /ui/faculty/{id}/edit` | Role-authorized read | Full faculty form with salary-scale and current revision context |
| `POST /ui/faculty`, `POST /ui/faculty/{id}` | CSRF + fields + revision on edits | Validate/normalize into existing create/update models; retain actual role and salary-field permissions |
| `GET /ui/workloads/new`, `GET /ui/workloads/{id}/edit` | Existing profile options and editable workload | Full workload form, with reviewed/approved locks enforced on the server |
| `POST /ui/workloads/draft/assignments` | User-scoped draft ID, current form fields, `add` or `remove:{opaque_row_id}` intent | Refresh the `workload_form` macro, assignment list and review summary; never silently saves a business workload |
| `POST /ui/workloads`, `POST /ui/workloads/{id}` | CSRF + draft ID + current revision | Existing workload JSON create/update service; assignments validated; retain optimistic concurrency |

Full page submissions follow Post/Redirect/Get. HTMX success may return a safe
same-origin `HX-Redirect`. An update adapter converts the hidden `revision` to the
existing **`If-Match`** contract; a hidden value alone provides no protection.
Reject stale changes with **409**, preserve entered values and offer reload plus
an explicit comparison. Preserve the current Draft → Reviewed → Approved /
administrator Reopen behavior; saving an edit must not approve it.

The examples use a proposed secure **same-origin cookie/session adapter** with
CSRF fields. They do not replace the current application's bearer-token flow.
Validate CSRF and authorization server-side for every write. Keep session cookies
HttpOnly and apply the deployment's appropriate SameSite/Secure policy. The
`_csrf` and `draft_id` fields are adapter placeholders, never an auth bypass.

For HTMX, configure response handling so **422** responses swap the returned
validated form and focus its error summary; **409** swaps the conflict notice,
**401** redirects to sign-in, and **403** displays denied access. Without that
configuration HTMX may not swap a 4xx response. Implement this in a locally
vendored external integration script; the templates disable inline evaluation.
Announce loading and completion, disable only the initiating submit action, and
restore it on failure. `hx-sync="this:replace"` prevents stale filter results from
winning a later search. Normal GET and POST actions remain functional without JS.
Draft assignment submissions include the complete current form. Preserve those
values in the user-scoped draft before rendering the updated form. Assignment
fields do not have HTML `required` attributes because final save must not demand
an unused editor row; validate them only for the Add intent. Final Save rejects
an unfinished nonblank editor and requires at least one committed draft row.
The no-JavaScript draft response must render the complete page after a redirect.

## Context and privacy

Supply `user`, role-filtered `navigation_groups`, `release_version`, `page_name`,
`request_path`, optional `page_error` and `flash_message`. Navigation URLs must be
selected from a server-owned allowlist, not personnel content. The dashboard
receives **prepared, correctly scoped** workload/estimate/coverage data; do not
reimplement compensation formulas in templates or treat missing values as zero.
Show salary/projection/activity sections only to roles authorized by the existing
application. Activity requires an administrator. Do not substitute invented
percentage changes or “live” status for unavailable data.

Money strings, date strings, tabular values and chart ratios are prepared by the
adapter. Clamp validated chart ratios to 0–100 and apply a nonce/hash-compatible
style policy if using inline bar widths. “Overload” includes Regular Faculty only;
internal/external part-time teaching and salary estimates remain separate.
Forms receive server-owned `submit_path`, `cancel_path` and `latest_path` values.
Use `errors` only for field/section IDs present in the returned form; display
unrelated errors in `page_error`. `can_edit_profile`, `can_view_compensation` and
`can_edit_workload` are presentation flags derived from existing permissions,
never authorization in themselves. Preserve omitted protected salary fields on
the server; derive salary grade mappings, step values and monthly amounts from
the existing salary scale. Program options must match the selected department,
and validate faculty service status against the selected workload period again
on final save. Refresh dependent options through the same draft adapter or a
normal form refresh; the templates do not invent a new client business-rule engine.

Use `Cache-Control: no-store` for private HTML/fragments and authenticated data.
HTMX history caching is disabled; personnel forms are not persisted in browser
storage. A proposed server-side form draft is scoped to the current user, expires,
has an opaque ID and is discarded on sign-out. It is distinct from saved records.
Add an unsaved-change guard for navigation, refresh and sign-out, matching the
existing React app. Any added draft store is an explicit backend task.

## Interaction/accessibility acceptance

- Preserve keyboard order, visible focus and a working skip link; mobile Menu is
  a native disclosure, not an unfocused modal overlay.
- Use table headers and a caption; keep horizontal scrolling inside the grid,
  not the page. Links have contextual names; no fake sorting or bulk actions.
- Validate both the field and the error summary. Error links focus the field;
  do not rely on color alone. Mandatory inputs use `required` and visible `*`.
- Steps are **visible section anchors**, not fake completed steps or hidden
  validation. A small progress navigator never discards entered data.
- Add/remove assignment actions operate on the draft; final Save alone persists
  the workload. Imported hour overrides and approval snapshots retain existing rules.
- Test 360/768/1280/1600 widths, 200% zoom, long names, empty datasets, permission
  denial, slow reads, invalid saves, stale revisions and print before release.

See the current project implementation blueprint for the React rollout. These
templates are a parallel delivery option, not authorization to migrate frameworks
or invent scholarship/grant modules.

## Validation status

Static validation checks balanced Jinja blocks, HTML form nesting, route naming,
and the eight-file inventory. This workspace does not include Jinja or Tailwind
3.x compilers, so these handoff files have **not** been rendered or CSS-compiled
here. Before adopting them, compile the theme and render every full page and
fragment with strict undefined-variable handling, autoescaping and realistic
empty/error/conflict/unauthorized contexts. The actual React implementation is
verified separately by its own frontend checks.
