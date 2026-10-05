# Manuel utilisateur illustré — Finance, Comptabilité, RH, Paie, CRM

Date: 2026-09-30
Status: design, awaiting review

## Why this exists

The plant's Finance, Comptabilité, RH, Paie and CRM screens are used by people who
may have had little or no formal schooling. Some of them cannot reliably read
French prose. Today there is no end-user documentation at all: everything under
`docs/` is developer-facing (specs, plans, `go-live-data-reset.md`).

The deliverable is five illustrated French guides that a person can follow by
looking at pictures, where the words are a fallback rather than the carrier of
meaning.

### Who it is for

Two readers per module, both assumed inexperienced:

- the **clerk who enters** data (creates the invoice, records the employee,
  keys the leave request),
- the **supervisor who approves** it (validates leave, confirms a payroll run,
  closes an accounting period).

Accountants using the Comptabilité guide are *not* assumed trained. Decision
taken 2026-09-30: all five modules get the same beginner depth.

### Success criteria

1. A reader who cannot read French prose can still complete a task by following
   the numbered badges on the photographs.
2. Every instruction names a control that exists on screen, using the exact
   French label the app renders.
3. A reader can tell, without asking anyone, whether the task worked.
4. Each guide opens offline by double-clicking one file, and prints on A4
   without cutting a screenshot in half.

## Decisions taken (2026-09-30, with the client)

| Question | Decision |
|---|---|
| Language | **French only.** French is the plant's working language and the app's default (`readStoredLanguage()` returns `fr` unless overridden). No English edition. |
| Depth | All five modules at full beginner depth, covering both the entering clerk and the approving supervisor. |
| Format | **One self-contained HTML page per module.** No build step, no framework, opens offline. |
| Screenshot data | The local demo seed as-is (`demo@sonalim-erp.local`). Nothing real is exposed. |
| Finance vs Comptabilité | Split **by job, not by code.** They are one module in the repo (`/finance/*`); the guides divide them by who does the work. |
| Step presentation | **Numbered badges drawn over the screenshot**, one short French sentence per badge. |
| Irreversible actions | Performed for real on the **local dev DB only**, to capture true result screens. Nothing touches the server. |

## Scope

### The five guides

Output lives in a new `docs/manuel/` folder, with a cover page linking the five:

| File | Routes covered | Reader |
|---|---|---|
| `01-crm.html` | `/crm`, `/crm/leads`, `/crm/partners`, `/crm/opportunities`, `/crm/pipeline`, `/crm/activities` | Commercial |
| `02-finance.html` | `/finance` (Factures): list, new-invoice dialog, invoice payment status (`LedgerPostingStatus`), and the `finance.failures` / `finance.balances` views a clerk must react to | Caissier / clerc |
| `03-comptabilite.html` | `/finance/accounts`, `/finance/entries`, `/finance/posting-rules`, `/finance/trial-balance`, `/finance/ledger`, `/finance/periods` | Comptable |
| `04-rh.html` | `/hr`, `/hr/employees`, `/hr/employees/:id` (7 tabs), `/hr/organisation`, `/hr/presence`, `/hr/leave`, `/hr/schedules` | RH |
| `05-paie.html` | `/payroll/rules`, `/payroll/inputs`, `/payroll/runs`, `/payroll/runs/:id`, `/payroll/payslips/:id`, payout batches, declarations | Paie |

Roughly 35 task blocks and ~50 screenshots in total.

Layout:

```
docs/manuel/
  index.html            cover page, links the five guides
  01-crm.html … 05-paie.html
  manuel.css            shared stylesheet (also inlined per page — see below)
  images/crm/*.png      screenshots, one folder per module
  images/finance/…
```

Each guide inlines its CSS in a `<style>` block so a single copied file still
renders correctly; `manuel.css` is the source of truth those blocks are generated
from.

**How a reader reaches it.** The guides live in the repo, so the plant gets them
by one of: opening `docs/manuel/index.html` from a copied folder, or printing the
pages to paper. Because the CSS is inlined and the only external references are
the sibling `images/` files, copying the whole `docs/manuel/` folder to a USB
stick or a shared drive is sufficient — there is no server and no internet
dependency. Distribution beyond that (who copies it where) is the client's call
and out of scope here.

### Out of scope

- English edition (French only, decided).
- In-app help pages inside the React SPA. This is documentation, not frontend work;
  no file under `frontend/src/` is touched.
- Production, Warehouse, QC, Sales, Procurement, Maintenance modules.
- Any change to application behaviour, translations, or the seed scripts.
- Screenshots of the live server.

## The page pattern

Every screen is one `TÂCHE` block in a fixed rhythm, so the reader learns the
shape once and reuses it everywhere:

1. **Title in plain French.** « Enregistrer un nouvel employé », never
   « Gestion du référentiel employé ».
2. **The screenshot at full page width**, with red numbered badges ①②③ layered
   on the exact controls.
3. **One line per badge**, in the same order: one action, one verb, imperative
   present, under ~12 words. « ① Cliquez le bouton vert « Nouveau ». »
4. **An amber `ATTENTION` box**, only where a real mistake is possible — an
   irreversible confirmation, a closed period, a payment that cannot be undone.
5. **A green `C'EST RÉUSSI QUAND…` box** naming the visible proof the task
   worked, so a reader with no other way to judge can self-verify.

The numbers carry the meaning. Every instruction is anchored to a circled number
sitting on the thing to press, so a reader who cannot read the sentence can still
see which control the step is about.

### Badge rendering

Badges are **HTML/CSS overlays, not pixels burned into the image**:

```html
<figure class="shot">
  <img src="images/crm/leads-list.png" alt="Écran Prospects">
  <span class="badge" style="left:78.4%; top:12.1%">1</span>
</figure>
```

The `<figure>` is `position:relative`, the badge `position:absolute`. Reasons
this beats annotating the PNG:

- no image-processing dependency (Pillow is absent from `backend/.venv`),
- badges stay sharp at any zoom and when printed,
- a misplaced badge is fixed by editing one percentage, not re-rendering an image,
- the alt text and the badge remain real text, so the page stays searchable.

Coordinates come from **measured element geometry**, not the eye: Playwright
reports the target control's bounding box, which is converted to a percentage of
the screenshot dimensions. Badges therefore land on the real buttons.

### Writing rules (French)

- Every quoted control label is copied from `frontend/src/lib/i18n.fr.ts`, never
  invented. The manual must not teach vocabulary the app does not use. The
  dictionary already carries the plant's terms — *Prospects*, *Opportunités*,
  *Bulletins de paie*, *Agenda*, *Plan comptable*, *Écritures comptables*,
  *Éléments variables*, *Périodes comptables*.
- One instruction per sentence. No subordinate clauses, no « afin de », no passive.
- Colours and shapes are named alongside labels (« le bouton vert », « la case du
  haut »), because they survive a reader who cannot read the label.
- No invented threshold, delay, or approval rule. If the UI does not display it,
  it does not appear in the manual. (Standing project rule: every judgement must
  trace to a recorded field.)
- Amounts appear exactly as the app renders them, in XOF.

### Ordering inside a guide

Tasks run easiest-first and follow the real working day, not the menu order.
The RH guide opens with *finding an employee*, not with configuring departments.
Configuration screens (`/hr/organisation`, `/hr/schedules`, `/payroll/rules`)
come last, as reference, because a clerk rarely touches them.

## Screenshot capture

### Environment

Verified on 2026-09-30:

- Postgres is already running natively on `localhost:5432` (`docker` is not on
  PATH in this shell; the compose stack is not used locally).
- All migrations are applied, including the five `payroll` ones. The `payroll`
  schema has its 21 tables.
- Backend and frontend are **not** running and will be started
  (`backend/.venv/Scripts/python -m uvicorn app.main:app` and `npm run dev`).

### Seed state

Counted 2026-09-30 — enough to photograph everything without empty tables:

| Table | Rows |
|---|---|
| `hr.employees` / `hr.contracts` / `hr.presence_days` | 67 / 72 / 1691 |
| `hr.departments` / `hr.leave_requests` | 11 / 4 |
| `payroll.runs` / `payroll.payslips` / `payroll.rule_sets` | 1 / 64 / 1 |
| `payroll.advances` / `payroll.payout_batches` | 3 / **0** |
| `finance.invoices` / `finance.journal_entries` / `finance.accounts` / `finance.periods` | 35 / 59 / 76 / 12 |
| `crm.leads` / `crm.opportunities` / `crm.activities` | 29 / 33 / 105 |

`payroll.payout_batches` is empty, so the payment-batch screens are captured by
performing the flow (permitted below) rather than from seeded rows.

### Capture procedure

1. Start backend and frontend; log in as `demo@sonalim-erp.local` / `demo1234`.
2. Force French (`localStorage["sonalim-erp.language"] = "fr"`).
3. Fixed **1440×900** viewport for every shot, so all images share one scale and
   the page rhythm stays even.
4. Per task: navigate, wait for the data to render (never photograph a loader or
   a skeleton), read the bounding boxes of the controls the steps refer to,
   capture the PNG into `docs/manuel/images/<module>/`.
5. Filenames are descriptive and stable — `leads-new-dialog.png`, not a
   timestamp. The existing `.playwright-mcp/*.png` files are timestamp-named
   captures from unrelated production/QC work and are **not** reused.

Permissions: new permission codes are not auto-granted to the demo user. If a
screen 403s, grant the code via `POST /core/users/{id}/permissions` rather than
photographing an error page.

### Write actions

Performed for real on the local dev DB to capture true result screens, including
success messages. The local database is disposable; the server is untouched.
Flows exercised: create a lead and convert it, create an invoice, post a manual
entry, create and approve a leave request, create a payout batch, and — where
the seed allows a second run — a payroll confirmation and a period close.

If performing a flow would destroy a screen another task still needs to
photograph, that task is captured first. Order of capture is planned per module
before the browser is driven.

## Verification

Per guide, before it is considered done:

- Opened in a real browser from the `file://` path, offline.
- No broken image; every `<img>` resolves.
- Every badge visually sits on the control its sentence names — checked against
  the screenshot, not assumed from the coordinate.
- Print preview at A4 shows no screenshot split across a page break.
- Every quoted French label grepped against `i18n.fr.ts` to confirm it is the
  string the app actually renders.

No test suite is run: this change touches no application code. (Project rule:
tests are not run before commit/push.)

## Build order

CRM is built first, in full, as the **reference specimen** — it is the smallest
module and its screens are read-mostly. The client reviews that one guide and
corrects the pattern (badge size, sentence length, terminology) before the
remaining four are produced, so a wrong pattern is corrected once rather than
five times.

Then: Finance → Comptabilité → RH → Paie, hardest last.

## Risks

| Risk | Handling |
|---|---|
| A guide drifts as the UI changes | Guides state the capture date; labels are quoted from `i18n.fr.ts` so a renamed key is greppable. Accepted: this is a snapshot, not generated documentation. |
| Badge coordinates wrong after a screenshot is re-taken | Coordinates are per-image percentages; re-capturing a screen means re-reading its boxes. Verification step catches misplacement visually. |
| Reader still cannot follow the text | The numbered badges are the primary channel by design. If review shows the prose is still too dense, the fallback is fewer steps per screen, not simpler words on a crowded screen. |
| Seeded demo names look unrealistic to the client | Seed used as-is by decision. If the client objects on the CRM specimen, the seed can be curated before the other four are captured. |
