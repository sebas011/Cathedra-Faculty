# Cathedra Faculty design system

Implementation reference, 25 October 2026. The new identity uses a warm canvas,
ink navigation, cobalt actions and apricot accents. It applies to the current
Faculty app and retains the existing record, workload and planning domain.

Production runs React and TypeScript. The canonical tokens are in
`frontend/src/operations-design.css`, imported by `frontend/src/main.tsx`.
`DashboardOperations.css` and `records-redesign.css` provide page-specific
composition. Separate HTML/Jinja/Tailwind/HTMX examples are handoff materials in
`design/faculty-redesign/templates/`; they are not installed server routes.

## Tokens

| Token | Exact value | Use |
| --- | --- | --- |
| `--ui-canvas` | `#F6F7F4` | Workspace background |
| `--ui-surface` | `#FFFFFF` | Forms, tables and panels |
| `--ui-ink` | `#182231` | Body text and navigation surface |
| `--ui-muted` | `#5D6A7B` | Supporting copy and metadata |
| `--ui-primary` | `#3154D9` | Primary action, links, selection |
| `--ui-primary-dark` | `#253EAD` | Primary hover |
| `--ui-primary-soft` | `#EDF1FF` | Quiet primary backgrounds |
| `--ui-accent` | `var(--ui-primary)` | Compatibility role for record components |
| `--ui-accent-soft` | `var(--ui-primary-soft)` | Compatibility role for record backgrounds |
| `--ui-apricot` | `#F3B189` | Decorative accent and highlighted values on ink |
| `--ui-line` | `#DDE2E8` | Separators and nonessential panel outlines |
| `--field-line` | `#8492A4` | Input boundaries; screen stylesheet compatibility token |
| `--ui-success` | `#21674E` | Positive state, paired with text |
| `--ui-danger` | `#A92F3B` | Destructive/error state, paired with text |
| `--ui-warning` | `#855710` | Caution state, paired with text |
| `--ui-font-sans` | `Aptos, "Segoe UI Variable", "Segoe UI", system-ui, sans-serif` | Offline UI typography |
| `--ui-font-display` | `Georgia, "Times New Roman", serif` | Editorial page titles and wordmark |
| `--ui-radius` | `12px` | Standard panels |
| `--ui-sidebar` | `248px` | Expanded desktop navigation |

Legacy names such as `--green`, `--green-dark`, `--green-soft`, `--ink`,
`--canvas` and `--line` map to these new roles inside screen styles. Their names
do not retain the previous visual identity. Existing print styles are kept
separate from these screen overrides.

## Type, spacing and geometry

| Element | Current implementation |
| --- | --- |
| Body | 14 px / 1.55, sans family |
| Page title | Georgia regular, `clamp(30px, 2.7vw, 40px)`, line-height 1.18 |
| Dashboard title | Georgia regular, `clamp(32px, 3vw, 44px)`, line-height 1.16; 35 px mobile |
| Section title | 18 px / 1.35, weight 650 |
| Body copy in panels | 13 px / 1.65; hero explanation 14 px |
| Table cells | 13 px / 1.5; faculty name links 14 px |
| Table headers | 10 px, uppercase, .07em tracking |
| Labels / field hints | 13 px / 12 px respectively |
| Compact dashboard metadata | 10–12 px; nonessential eyebrow labels can be 9 px |
| Main panels | 24 px padding; dashboard panels 26 px; mobile generally 18–20 px |
| Canvas | 34 px top, 36 px sides, 56 px bottom on wide desktop |
| Controls | Fields at least 42 px high; buttons 40 px desktop and 44 px in mobile page content |
| Compact row actions | At least 34 px desktop, 44 px at 640 px and below |
| Radii | 7 px controls, 12 px panels, 14 px page-search dialog, 16 px confirmation dialog |
| Spacing rhythm | 4 px base; 8/12/16 px local gaps, 20/24/28 px section gaps |

The display scale creates hierarchy without making every panel a large title.
Financial values, counts and hours use tabular numerals where their existing
selectors support them. Long names remain readable rather than relying on
initials; initials are decorative identity aids. Small metadata must never be
the only place to disclose an error, provisional amount or destructive effect.

## Component and interaction contracts

| Component | Variants and states | Interaction / accessibility |
| --- | --- | --- |
| Workspace shell | Expanded, 76 px collapsed rail, mobile menu, service/release warnings | Semantic navigation and main; active link; skip link; mobile Escape and focus containment retain existing behavior |
| Page navigation | Closed, open, matching results, no matches | Button or Ctrl/Command+K; native dialog; input label; Tab then Enter follows links; Escape closes; role-filtered destinations only |
| Button | Primary cobalt, secondary white, danger pale red, disabled | Hover changes color/border in 140 ms; disabled prevents duplicate actions as existing logic dictates; icon-only controls require a label |
| Field | Default, focus, invalid, disabled/read-only | Visible label and field error; 3 px focus outline; `aria-invalid` changes border to danger; values remain after failed save |
| Notice | Informational, success, error and existing warning presentations | Outcome stays near its content; error alerts and loading status are semantic; no color-only meaning |
| Record table | Loading, ready, no records, no matches, failed request | Semantic table inside existing labeled scroll region; stable IDs, links, filter/pagination behavior retained; row hover is supplementary |
| Status | Draft neutral, Reviewed cobalt, Approved/Active green, Warning amber | Visible words carry the state; preserve existing status and authorization semantics |
| Workload entry | Three visible sections and review summary | Anchor navigation over one form; no intermediate save claim; sticky final actions; existing unsaved guard and final payload retained |
| Confirmation | Open, submitting, failed/cancelled | Existing native modal, safe focus, Escape/cancel and actual consequence text |
| Dashboard metric | Value, unavailable, provisional, independent loading/error | Preserve period scope and server calculation; never replace unavailable with zero or invent trends |
| Recent activity | Loading, first five real entries, empty, failed with Retry | Administrator dashboard only; existing activity API; view-all link; real timestamps and account/area context |
| Spreadsheet destination | Existing independent settings/test/update/error/success states | Three separate destinations and permission checks; private key material stays out of presentation examples |

## Responsive composition

| Breakpoint | Behavior |
| --- | --- |
| Above 1250 px | Dashboard planning and attention use a 1.55:1 main grid; supporting panels use 1.15:1 |
| 1250 px and below | Main dashboard grid stacks; attention items can use two columns |
| 1180 px and below | Canvas gutters become 24 px; account detail and long page-search trigger copy are hidden |
| 1100 px and below | Workload section links simplify; review summary becomes two columns |
| 900 px and below | Supporting dashboard panels stack |
| 760 px and below | Desktop rail becomes a 264 px off-canvas menu; workspace margin resets; gutters 16 px; dashboard/cards/actions stack; login illustration hides |
| 640 px and below | Workload section links and review summary become one column; row actions use 44 px targets |
| 480 px and below | The three workload KPIs become compact label/value rows, preserving legible totals |

Tables retain horizontal scrolling in their own region. The document must not
overflow sideways. A collapsed desktop rail does not remain collapsed inside
the mobile menu. Final live testing must check long names, large currency values,
dirty forms and the final action bar at narrow widths and zoom.

## Contrast and focus

Calculated from the exact sRGB token pairs using WCAG relative luminance:

| Pair | Ratio | Interpretation |
| --- | --- | --- |
| Ink / canvas | 14.89:1 | Normal text passes AA |
| White / primary | 6.18:1 | Primary button text passes AA |
| Muted / white | 5.51:1 | Supporting text passes AA |
| Ink / apricot | 8.74:1 | Accent surface text passes AA |
| Danger / white | 6.65:1 | Error text passes AA |
| Success / white | 6.74:1 | Positive text passes AA |
| Warning / white | 6.24:1 | Warning text passes AA |
| Field boundary / white | 3.17:1 | Input boundary meets 3:1 |
| Focus `#637FEE` / white | 3.62:1 | Focus indicator meets 3:1 against white |
| Apricot / white | 1.83:1 | Decorative/background use only; unsuitable for normal text or essential boundaries |

The pale `--ui-line` is a separator token, not the sole boundary for fields.
These token checks do not prove every rendered page meets WCAG: composites,
legacy styles, focus against dark surfaces, zoom and assistive technology still
need inspection. Reduced-motion mode disables transitions and animation.

## Implementation and validation boundaries

Production source changes include the new shared theme, shell/page navigation,
dashboard/real activity, faculty/workload registers and workload form sections.
Backend endpoints, database schema, permissions and financial calculations have
not been rewritten for the redesign. No Tailwind or HTMX production migration
is implied by the companion templates.

Frontend lint, test TypeScript checks, all 136 tests, and the production build
passed. Main page families and narrow layouts were inspected with synthetic
records; the page-search and unsaved-edit interactions were exercised in-browser.
See `VERIFICATION.md` for evidence and remaining release acceptance boundaries.
Screenshots contain synthetic records. Physical printing, live Google uploads,
restored office devices and full screen-reader acceptance were not exercised.
