# Bilingual API Errors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every refusal the backend sends reaches a French user in French, and the Conditionnement "PRODUCTION_FIRST" refusal tells the operator what to do.

**Architecture:** `Err` (the shared result type) gains an optional `message_fr`; one helper `err_detail()` turns an `Err` into the HTTP error body `{code, message, message_fr}`; every `Err(...)` and raw `HTTPException` detail gets its French next to the English. The frontend's `apiFetch` picks `message_fr` when the stored language is French, so the 128 existing `error.message` displays need no change.

**Tech Stack:** FastAPI + psycopg (Python 3, pytest), React 18 + TS (Vite, `tsc -b`), no frontend test runner.

**Spec:** `docs/superpowers/specs/2026-09-25-bilingual-api-errors-design.md`

## Global Constraints

- Backend commands run from `backend/` with `.venv/Scripts/python` (Windows). Frontend type check: `cd frontend && npx tsc -b --force`.
- DB-backed tests (`*_integration.py`) **skip** when no DB is reachable. After every pytest run, read the summary line: a run whose `skipped` count covers the integration tests tested nothing. Start the DB (`postgresql://erp:erp@localhost:5432/erp`, migrated) before Task 5.
- **No commits unless the user asks.** The worktree is shared with other sessions that leave uncommitted work in the same files. Each task ends with a *Checkpoint* step listing its files; commit them (with `git add <those files>` only, never `git add -A`) only when the user has asked for commits.
- Never `git stash`. Browser checks use a private headless Chrome, not the shared Playwright session (see memory `feedback_shared_worktree.md`, `feedback_verify_frontend_in_repo.md`).
- **Do not reword the English** of any message except `PRODUCTION_FIRST` (Task 5). Existing tests and logs match on it.
- `Err` positional order stays `Err(code, message, message_fr)`. French goes as the **third positional argument**.
- Technical identifiers inside messages stay untouched: permission codes (`core.manage_permissions`), enum values (`'day'`, `'week'`), field/payload keys, `{...!r}` values, IDs. Only the prose around them is translated.
- French style: plain, direct, vous-form, lower-case start (matching the English, which starts lower-case), a normal space before `:` `;` `?` `!`. Use the UI's own words:

  | English | French |
  |---|---|
  | work order / OF | OF |
  | shift | shift |
  | lot | lot |
  | packing / packing row | conditionnement / ligne de conditionnement |
  | run (production run) | passage de production |
  | location / store | emplacement / magasin |
  | work center / line | poste de charge / ligne |
  | stock | stock |
  | packaging | emballage |
  | raw material | matière première |
  | finished goods | produit fini |
  | regrind | rebroyat |
  | waste | déchets |
  | recipe | recette |
  | product | produit |
  | quantity | quantité |
  | partner / supplier / customer | partenaire / fournisseur / client |
  | purchase order / sales order | commande d'achat / commande client |
  | invoice | facture |
  | lead / opportunity / activity / contact | prospect / opportunité / activité / contact |
  | non-conformity / quality report | non-conformité / rapport qualité |
  | employee / contract / payroll | employé / contrat / paie |
  | equipment | équipement |
  | role / permission / user | rôle / permission / utilisateur |
  | draft / submitted / validated | brouillon / rendu / validé |
  | hand in (a section) / send back | rendre / renvoyer |
  | not found | introuvable |
  | must be positive / must not be negative | doit être positif / ne peut pas être négatif |
  | is required | est obligatoire |
  | already exists | existe déjà |

  For anything not in the table, reuse the `fr` value of the matching key in `frontend/src/lib/i18n.tsx` or `frontend/src/features/production/shift/shiftText.ts` (search the English there first).

### How to translate an `Err(...)` site (used by Tasks 5–13)

1. Add the French as the third positional argument, interpolating the same values:
   ```python
   # before
   return Err("INVALID_QUANTITY", f"quantity must be positive, got {quantity}")
   # after
   return Err("INVALID_QUANTITY", f"quantity must be positive, got {quantity}", f"la quantité doit être positive, reçu {quantity}")
   ```
2. A multi-line call gets the French on its own line, keeping the file's formatting:
   ```python
   return Err(
       "PACKAGING_STORES_DIFFER",
       f"packing row {index}: its packaging items have different default storage locations; "
       "packaging is taken from one store per row",
       f"ligne de conditionnement {index} : ses articles d'emballage ont des emplacements par défaut différents ; "
       "l'emballage est pris dans un seul magasin par ligne",
   )
   ```
3. A message table becomes `{code: (en, fr)}` and both halves are formatted:
   ```python
   en, fr = _PROBLEMS[problem]
   return Err(problem, en.format(n=index), fr.format(n=index))
   ```
4. An `Err` built from another `Err` (a prefix wrapper) wraps both, falling back to the inner English:
   ```python
   return Err(checked.code, f"run {index}: {checked.message}", f"passage {index} : {checked.message_fr or checked.message}")
   ```
5. An `Err` whose message is an exception's text (`str(exc)`, `exc.diag.message_primary`) keeps the raw text in both, with French prose around it:
   ```python
   return Err("INVALID_VALUE", f"the shift cannot be posted as entered: {exc.diag.message_primary or exc}",
              f"le shift ne peut pas être comptabilisé tel que saisi : {exc.diag.message_primary or exc}")
   ```
6. After a file is done, `.venv/Scripts/python -m core.test_error_translations <path>` (Task 3) must print `0 left` for it.

## Review Focus

1. **First visit, nothing stored in `localStorage`**: the UI shows English (`readStoredLanguage()` defaults to `en`), and errors must be English too — the same reader decides both. Pinned by Task 4 Step 6 (browser, storage cleared).
2. **Backend sends no or empty `message_fr`** (an untranslated site, or an old server during deploy): a French user must see the English text, never an empty toast or `undefined`. Pinned by Task 4 Step 5 (before any translation exists, every error is in this state).
3. **Network down / server restarting (every push redeploys)**: the user must see the French network message and must **not** be logged out. Pinned by Task 4 Step 7 (Chrome offline emulation).
4. **Expired session (401)**: `auth:unauthorized` must still fire before the error is built, and the new coded 401 bodies must still log the user out. Pinned by Task 12 Step 4.
5. **A wrapped error whose inner `Err` has no French yet**: French prefix + English inner text, never `None` printed into the message. Pinned by Task 6 Step 1's test of `ligne de conditionnement … : …` with an untranslated inner (`message_fr=None`).

---

### Task 1: `Err.message_fr` and `err_detail`

**Files:**
- Modify: `backend/core/domain/result.py`
- Create: `backend/core/domain/test_result.py`

**Interfaces:**
- Produces: `Err(code: str, message: str, message_fr: str | None = None)`; `err_detail(err: Err) -> dict[str, str | None]` returning `{"code", "message", "message_fr"}`. Both importable from `core.domain.result`.

- [ ] **Step 1: Write the failing test**

`backend/core/domain/test_result.py`:
```python
from core.domain.result import Err, err_detail


def test_an_error_without_french_still_builds():
    err = Err("NOT_FOUND", "user 1 not found")
    assert err.message_fr is None


def test_the_detail_carries_both_languages():
    err = Err("NOT_FOUND", "user 1 not found", "utilisateur 1 introuvable")
    assert err_detail(err) == {"code": "NOT_FOUND", "message": "user 1 not found", "message_fr": "utilisateur 1 introuvable"}


def test_the_detail_of_an_untranslated_error_says_so_with_none():
    assert err_detail(Err("X", "english only")) == {"code": "X", "message": "english only", "message_fr": None}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest core/domain/test_result.py -q`
Expected: FAIL — `ImportError: cannot import name 'err_detail'`.

- [ ] **Step 3: Implement**

`backend/core/domain/result.py` becomes:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Ok(Generic[T]):
    value: T


@dataclass(frozen=True)
class Err:
    code: str
    message: str
    # The same refusal in French, for a user working in French. The English stays in `message`
    # for logs, scripts and tests; `None` until the site that builds the error is translated.
    message_fr: str | None = None


Result = Ok[T] | Err


def err_detail(err: Err) -> dict[str, str | None]:
    """The HTTP error body for a refusal: the frontend shows `message_fr` to a French user."""
    return {"code": err.code, "message": err.message, "message_fr": err.message_fr}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/Scripts/python -m pytest core/domain/test_result.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Checkpoint** — `backend/core/domain/result.py`, `backend/core/domain/test_result.py`.

---

### Task 2: Routers send the French through

The 115 router conversions all read exactly `{"code": result.code, "message": result.message}`. Until they use `err_detail`, any French is dropped at the router.

**Files:**
- Create: `backend/scripts/use_err_detail.py` (one-off rewrite script; delete in Step 5)
- Modify (by the script): `backend/core/exchange_rates.py`, `backend/core/partners.py`, `backend/core/products.py`, `backend/core/report_options.py`, `backend/modules/{crm,finance,hr,maintenance,procurement,production,qc,sales,warehouse}/api/router.py`

**Interfaces:**
- Consumes: `err_detail` from Task 1.

- [ ] **Step 1: Record the before-state**

Run: `grep -rn '"code": result.code, "message": result.message' --include=*.py core modules | wc -l`
Expected: `115`.

- [ ] **Step 2: Write the rewrite script**

`backend/scripts/use_err_detail.py`:
```python
"""One-off: route every Err-to-HTTP conversion through err_detail. Delete after use."""
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parent.parent
OLD = '{"code": result.code, "message": result.message}'
IMPORT_LINE = re.compile(r"^from core\.domain\.result import (.+)$", re.M)

for path in sorted([*BACKEND.glob("core/*.py"), *BACKEND.glob("modules/*/api/router.py")]):
    text = path.read_text(encoding="utf-8")
    if OLD not in text:
        continue
    text = text.replace(OLD, "err_detail(result)")
    found = IMPORT_LINE.search(text)
    if found and "(" not in found.group(1):
        names = [n.strip() for n in found.group(1).split(",")]
        if "err_detail" not in names:
            names.append("err_detail")
        text = text[: found.start(1)] + ", ".join(sorted(names, key=str.lower)) + text[found.end(1):]
    elif not found:
        first = re.search(r"^from (core|modules)\.", text, re.M)
        text = text[: first.start()] + "from core.domain.result import err_detail\n" + text[first.start():]
    else:
        raise SystemExit(f"{path}: parenthesised import of core.domain.result, add err_detail by hand")
    path.write_text(text, encoding="utf-8", newline="\n")
    print("rewrote", path.relative_to(BACKEND).as_posix())
```

- [ ] **Step 3: Run it and check nothing is left**

Run: `.venv/Scripts/python scripts/use_err_detail.py`
Then: `grep -rn '"message": result.message' --include=*.py core modules | wc -l` → Expected: `0`.
Then: `grep -rln "err_detail(result)" --include=*.py core modules | xargs grep -L "import.*err_detail"` → Expected: no output (every file using it imports it).
If the script stopped on a parenthesised import, add `err_detail` to that import by hand and rerun.

- [ ] **Step 4: Prove every router still imports and the suite is unchanged**

Run: `.venv/Scripts/python -c "import app.main"` → Expected: no error.
Run: `.venv/Scripts/python -m pytest core modules -q -x` → Expected: same pass count as before this task, no new failures (note the skip count; see Global Constraints).

- [ ] **Step 5: Delete the script**

Run: `rm scripts/use_err_detail.py`

- [ ] **Step 6: Checkpoint** — the files listed by the script's `rewrote` lines.

---

### Task 3: The guard that finds English-only refusals

Lands now, marked `xfail(strict=True)`, so later tasks use it as their progress meter and Task 13 turns it on.

**Files:**
- Create: `backend/core/test_error_translations.py`

**Interfaces:**
- Produces: `untranslated(paths: Iterable[str]) -> list[str]` (entries `"<path>:<line>: <why>"`), and a CLI: `.venv/Scripts/python -m core.test_error_translations [path ...]` printing offenders then `N left`.

- [ ] **Step 1: Write the guard**

`backend/core/test_error_translations.py`:
```python
"""Every refusal the API can send carries its French.

A user working in French otherwise gets an English sentence in a French screen. This walks the
backend's own code (not tests, not scripts) and lists each `Err(...)` built without French and each
`HTTPException` whose detail has no `message_fr`.

List what is left under some paths:
    .venv/Scripts/python -m core.test_error_translations modules/qc core/auth.py
"""
from __future__ import annotations

import ast
import pathlib
import sys
from collections.abc import Iterable, Iterator

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent
ROOTS = ("core", "modules")


def _named(node: ast.expr, name: str) -> bool:
    return (isinstance(node, ast.Name) and node.id == name) or (isinstance(node, ast.Attribute) and node.attr == name)


def _keys(node: ast.Dict) -> set[str]:
    return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _problems(path: pathlib.Path) -> Iterator[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _named(node.func, "Err"):
            if len(node.args) < 3 and not any(k.arg == "message_fr" for k in node.keywords):
                yield node.lineno, "Err without French"
        elif _named(node.func, "HTTPException"):
            details = [*node.args[1:2], *(k.value for k in node.keywords if k.arg == "detail")]
            for detail in details:
                if isinstance(detail, (ast.Constant, ast.JoinedStr)):
                    yield node.lineno, "HTTPException with a plain-text detail"
                elif isinstance(detail, ast.Dict) and "message" in _keys(detail) and "message_fr" not in _keys(detail):
                    yield node.lineno, "HTTPException detail without message_fr"


def untranslated(paths: Iterable[str]) -> list[str]:
    found: list[str] = []
    for root in paths:
        base = BACKEND / root
        files = [base] if base.is_file() else sorted(base.rglob("*.py"))
        for path in files:
            if ".venv" in path.parts or path.name.startswith("test_") or path.name == "conftest.py":
                continue
            found.extend(f"{path.relative_to(BACKEND).as_posix()}:{line}: {why}" for line, why in _problems(path))
    return found


@pytest.mark.xfail(strict=True, reason="French is added module by module; the last task of the plan removes this mark")
def test_every_refusal_carries_its_french():
    problems = untranslated(ROOTS)
    assert not problems, "\n".join(problems)


if __name__ == "__main__":
    left = untranslated(sys.argv[1:] or ROOTS)
    print("\n".join(left))
    print(f"{len(left)} left")
```

- [ ] **Step 2: Run the CLI to see the starting count**

Run: `.venv/Scripts/python -m core.test_error_translations | tail -1`
Expected: about `520 left` (≈481 `Err` + 35 coded dicts + 7 plain-text details). Write the number down; later tasks drive it to 0.

- [ ] **Step 3: Check the guard sees a translated site as done**

Run: `.venv/Scripts/python -c "import ast,pathlib,tempfile; from core.test_error_translations import _problems; p=pathlib.Path(tempfile.mkdtemp())/'x.py'; p.write_text('Err(\"A\",\"a\",\"b\")\nErr(\"A\",\"a\")\nHTTPException(1,{\"code\":\"A\",\"message\":\"a\",\"message_fr\":\"b\"})\nHTTPException(1,\"plain\")\nHTTPException(1,err_detail(r))\n',encoding='utf-8'); print(list(_problems(p)))"`
Expected: `[(2, 'Err without French'), (4, 'HTTPException with a plain-text detail')]`.

- [ ] **Step 4: Run it as a test**

Run: `.venv/Scripts/python -m pytest core/test_error_translations.py -q`
Expected: `1 xfailed`.

- [ ] **Step 5: Checkpoint** — `backend/core/test_error_translations.py`.

---

### Task 4: The frontend shows the French

**Files:**
- Modify: `frontend/src/lib/i18n.tsx` (export `readStoredLanguage`; add `login.failed` to `en` and `fr`)
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/features/production/api.ts:800-832` (the two exports)
- Modify: `frontend/src/routes/LoginPage.tsx:31`

**Interfaces:**
- Consumes: the backend body `{"detail": {"code", "message", "message_fr"}}` from Tasks 1–2.
- Produces: `ApiError(status, code, message, messageEn = message)` — `message` in the user's language, `messageEn` always English; `apiErrorFromResponse(response: Response): Promise<ApiError>`; codes `VALIDATION_ERROR` (422 list detail) and `NETWORK_ERROR` (status 0).

- [ ] **Step 1: Export the language reader**

In `frontend/src/lib/i18n.tsx` (≈line 6941) change `function readStoredLanguage(): Language {` to:
```ts
/** The language the user picked, readable outside React (the API client uses it for error text). */
export function readStoredLanguage(): Language {
```

- [ ] **Step 2: Add the login fallback key in both dictionaries**

In the `en` dictionary, after `"login.submitting": "Signing in…",` (≈line 313):
```ts
  "login.failed": "Unable to sign in",
```
In the `fr` dictionary, after `"login.submitting": "Connexion…",` (≈line 3776):
```ts
  "login.failed": "Connexion impossible",
```

- [ ] **Step 3: Rewrite `frontend/src/lib/api.ts`**

```ts
import { readStoredLanguage } from "./i18n";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    /** Shown to the user, in the language they picked. */
    message: string,
    /** The backend's English, for logs; equal to `message` for an English user. */
    public messageEn: string = message,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
}

interface Bilingual {
  en: string;
  fr: string;
}

// Refusals the backend cannot word itself: FastAPI's own request validation (its detail is a
// list of field errors) and a server that never answered.
const VALIDATION_FAILED: Bilingual = {
  en: "Some values sent are not valid.",
  fr: "Certaines valeurs envoyées ne sont pas valides.",
};
const SERVER_UNREACHABLE: Bilingual = {
  en: "The server cannot be reached. Check the connection and try again.",
  fr: "Le serveur est injoignable. Vérifiez la connexion et réessayez.",
};

function fixedError(status: number, code: string, text: Bilingual): ApiError {
  return new ApiError(status, code, text[readStoredLanguage()], text.en);
}

// Mirrors the {"code", "message", "message_fr"} detail every router raises (core.domain.result.err_detail).
// A French user gets `message_fr`; a refusal nobody has translated yet falls back to the English.
export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
  const payload = await response.json().catch(() => null);
  const detail = payload?.detail;
  if (Array.isArray(detail)) {
    return fixedError(response.status, "VALIDATION_ERROR", VALIDATION_FAILED);
  }
  if (typeof detail === "object" && detail !== null) {
    const english = typeof detail.message === "string" ? detail.message : response.statusText;
    const french = typeof detail.message_fr === "string" && detail.message_fr ? detail.message_fr : null;
    const shown = readStoredLanguage() === "fr" && french ? french : english;
    return new ApiError(response.status, typeof detail.code === "string" ? detail.code : "UNKNOWN", shown, english);
  }
  return new ApiError(response.status, "UNKNOWN", typeof detail === "string" ? detail : response.statusText);
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? "GET",
      headers: {
        "Content-Type": "application/json",
        ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    // No response at all (server down or restarting, network lost). Status 0 is not a 401,
    // so this never logs the user out.
    throw fixedError(0, "NETWORK_ERROR", SERVER_UNREACHABLE);
  }

  if (!response.ok) {
    if (response.status === 401) {
      // Told AuthProvider directly rather than importing it here — api.ts
      // has no business knowing about session state, only HTTP.
      window.dispatchEvent(new Event("auth:unauthorized"));
    }
    throw await apiErrorFromResponse(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
```

- [ ] **Step 4: Point the two exports and the login page at it**

In `frontend/src/features/production/api.ts`, in both `exportConsumptionBySupplier` and `exportProductionRecap`, replace
```ts
    throw new ApiError(response.status, "EXPORT_FAILED", response.statusText);
```
with
```ts
    throw await apiErrorFromResponse(response);
```
and add `apiErrorFromResponse` to that file's existing import from `../../lib/api` (keep `ApiError` if still used elsewhere in the file; `tsc` will say).

In `frontend/src/routes/LoginPage.tsx:31` replace `"Unable to sign in"` with `t("login.failed")` (`t` is already in scope from `useI18n()` at line 16).

Run: `cd frontend && npx tsc -b --force` → Expected: no errors.

- [ ] **Step 5: Browser check — untranslated errors fall back to English (Review Focus 2)**

Start backend (`cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000`) and frontend (`cd frontend && npm run dev`) if not running. In a private headless Chrome, log in as `demo@sonalim-erp.local` / `demo1234`, set language to French, open the shift report, add a Conditionnement row with no OF on a shift with no production, press **Rendre**.
Expected: toast title « Cela n'a pas fonctionné », body the **English** `packing row 1: …` text (nothing translated yet), not empty, not `undefined`.

- [ ] **Step 6: Browser check — first visit (Review Focus 1)**

Clear `localStorage` (`localStorage.clear()` in the page), reload, log in with a wrong password.
Expected: the login page is in English and so is the error (`invalid credentials`). Then stop the backend and submit again in French → « Le serveur est injoignable… », not the hard-coded "Unable to sign in".

- [ ] **Step 7: Browser check — network down (Review Focus 3)**

With French selected and logged in, emulate offline via CDP (`Network.emulateNetworkConditions` with `offline: true`), then trigger any save (e.g. **Enregistrer le brouillon**).
Expected: body « Le serveur est injoignable. Vérifiez la connexion et réessayez. »; the user stays logged in (no redirect to `/login`). Turn offline off.

- [ ] **Step 8: Checkpoint** — `frontend/src/lib/api.ts`, `frontend/src/lib/i18n.tsx`, `frontend/src/features/production/api.ts`, `frontend/src/routes/LoginPage.tsx`.

---

### Task 5: The screenshot's refusal, in both languages

**Files:**
- Modify: `backend/modules/production/api/packing_derivation_service.py:26-29,72-73,105-109`
- Test: `backend/modules/production/api/test_packing_derivation_integration.py:88-101`

**Interfaces:**
- Consumes: `Err(code, message, message_fr)` from Task 1.

- [ ] **Step 1: Write the failing assertions**

In `test_packing_derivation_integration.py`, extend the two tests:
```python
def test_a_row_with_no_production_on_the_shift_is_refused_on_save(db, env):
    service = ShiftReportService(db)
    shift_id = _ok(service.open_shift(tenant_id=TENANT, actor_id=env["actor"], work_center_id=env["work_center"], report_date=DAY, shift="night"))["id"]
    refused = _save_packing(service, env, shift_id, [{"carton_quantity": 3}])
    assert isinstance(refused, Err) and refused.code == "PRODUCTION_FIRST"
    # It names both ways out: pick the OF on the row, or save the production it can be taken from.
    assert refused.message == (
        "packing row 1: pick this lot's OF, or save this shift's production first so it can be taken from there"
    )
    assert refused.message_fr == (
        "ligne de conditionnement 1 : choisissez l'OF de ce lot, "
        "ou enregistrez d'abord la production de ce shift pour qu'il en soit repris"
    )


def test_packaging_kept_in_different_stores_is_refused(db, env):
    service, shift_id, _, run_id = _shift_with_run(db, env)
    db.execute("UPDATE core.products SET default_location_id = %s WHERE id = %s", (env["other"], env["carton"]))
    refused = _save_packing(service, env, shift_id, [{
        "run_id": run_id, "film_product_id": env["film"], "carton_product_id": env["carton"], "film_quantity": 1, "carton_quantity": 1,
    }])
    assert isinstance(refused, Err) and refused.code == "PACKAGING_STORES_DIFFER"
    assert refused.message_fr.startswith("ligne de conditionnement 1 : ")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest modules/production/api/test_packing_derivation_integration.py -q`
Expected: 2 FAIL on the new assertions (and **0 skipped** — if skipped, start the DB first).

- [ ] **Step 3: Implement**

In `packing_derivation_service.py` replace `_ORDER_PROBLEMS` with:
```python
_ORDER_PROBLEMS = {
    "PRODUCTION_FIRST": (
        "packing row {n}: pick this lot's OF, or save this shift's production first so it can be taken from there",
        "ligne de conditionnement {n} : choisissez l'OF de ce lot, "
        "ou enregistrez d'abord la production de ce shift pour qu'il en soit repris",
    ),
    "OF_AMBIGUOUS": (
        "packing row {n}: this shift ran several work orders; pick the OF for this lot",
        "ligne de conditionnement {n} : ce shift a tourné sur plusieurs OF ; choisissez l'OF de ce lot",
    ),
}
```
Replace `return Err(problem, _ORDER_PROBLEMS[problem].format(n=index))` with:
```python
            en, fr = _ORDER_PROBLEMS[problem]
            return Err(problem, en.format(n=index), fr.format(n=index))
```
Replace the `PACKAGING_STORES_DIFFER` return with:
```python
                return Err(
                    "PACKAGING_STORES_DIFFER",
                    f"packing row {index}: its packaging items have different default storage locations; "
                    "packaging is taken from one store per row",
                    f"ligne de conditionnement {index} : ses articles d'emballage ont des emplacements par défaut différents ; "
                    "l'emballage est pris dans un seul magasin par ligne",
                )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest modules/production/api/test_packing_derivation_integration.py -q` → all pass, 0 skipped.
Run: `.venv/Scripts/python -m core.test_error_translations modules/production/api/packing_derivation_service.py | tail -1` → `0 left`.

- [ ] **Step 5: Browser check — the screenshot, fixed**

Repeat Task 4 Step 5 in French. Expected body: « ligne de conditionnement 1 : choisissez l'OF de ce lot, ou enregistrez d'abord la production de ce shift pour qu'il en soit repris ». Switch to English, press **Rendre** again → the English version.

- [ ] **Step 6: Checkpoint** — the two files above.

---

### Task 6: Production — the shift report services

**Files (Err count):** `backend/modules/production/api/shift_sections.py` (10), `shift_validation_service.py` (24), `shift_report_service.py` (12), `shift_stock_service.py` (7), `stock_release_service.py` (11), `legacy_report_ledger.py` (4), `day_sheet_service.py` (2)
- Test: `backend/modules/production/api/test_packing_derivation_integration.py` (Review Focus 5)

**Interfaces:**
- Consumes: `Err(code, message, message_fr)`. The wrap sites use the rule in "How to translate an `Err(...)` site", item 4.

- [ ] **Step 1: Write the failing test for the wrappers (Review Focus 5)**

The `run {index}:` and `packing row {index}:` wrappers (`shift_sections.py:717,759`) wrap domain refusals that stay English until Task 7. Add to `test_packing_derivation_integration.py` (needs no DB):
```python
def test_a_wrapped_refusal_without_french_keeps_the_english_inside():
    from modules.production.api.shift_sections import _wrap_packing_check, _wrap_run_check

    inner = Err("NO_STORE", "no store set")  # not translated yet: message_fr is None
    packing = _wrap_packing_check(3, inner)
    assert (packing.code, packing.message, packing.message_fr) == (
        "NO_STORE", "packing row 3: no store set", "ligne de conditionnement 3 : no store set",
    )
    run = _wrap_run_check(2, Err("NO_STORE", "no store set", "aucun magasin"))
    assert (run.message, run.message_fr) == ("run 2: no store set", "passage 2 : aucun magasin")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest modules/production/api/test_packing_derivation_integration.py -q -k wrapped`
Expected: FAIL — `ImportError: cannot import name '_wrap_packing_check'`.

- [ ] **Step 3: Add the wrappers and use them**

In `shift_sections.py`, above the function containing lines 717/759:
```python
def _wrap_run_check(index: int, checked: Err) -> Err:
    return Err(checked.code, f"run {index}: {checked.message}",
               f"passage {index} : {checked.message_fr or checked.message}")


def _wrap_packing_check(index: int, checked: Err) -> Err:
    return Err(checked.code, f"packing row {index}: {checked.message}",
               f"ligne de conditionnement {index} : {checked.message_fr or checked.message}")
```
Replace line 717 with `return _wrap_run_check(index, checked)` and line 759 with `return _wrap_packing_check(index, checked)`.

Run: `.venv/Scripts/python -m pytest modules/production/api/test_packing_derivation_integration.py -q -k wrapped` → PASS.

- [ ] **Step 4: Translate every other `Err` in the seven files**

Follow "How to translate an `Err(...)` site". `stock_release_service.py:265` is a wrap: 
```python
raise _Abort(Err(moved.code, f"{name}: {moved.message}", f"{name} : {moved.message_fr or moved.message}"))
```
`shift_validation_service.py:221` is an exception-text site (rule 5).

- [ ] **Step 5: Check nothing is left**

Run: `.venv/Scripts/python -m core.test_error_translations modules/production/api/shift_sections.py modules/production/api/shift_validation_service.py modules/production/api/shift_report_service.py modules/production/api/shift_stock_service.py modules/production/api/stock_release_service.py modules/production/api/legacy_report_ledger.py modules/production/api/day_sheet_service.py | tail -1`
Expected: `0 left`.

- [ ] **Step 6: Run the production tests**

Run: `.venv/Scripts/python -m pytest modules/production -q`
Expected: no failures; integration tests ran (skip count small).

- [ ] **Step 7: Checkpoint** — the seven files + the test file.

---

### Task 7: Production — domain rules

**Files (Err count):** `backend/modules/production/domain/production_report.py` (31), `product_classification.py` (8), `dashboard.py` (8), `recipe.py` (5), `work_center.py` (4), `regrind.py` (4), `resource_type.py` (3), `packaging_bom.py` (3), `waste_type.py` (2), `mold.py` (2), `entities.py` (1)

- [ ] **Step 1: Translate every `Err` in these files** (procedure in Global Constraints).
- [ ] **Step 2: Check** — `.venv/Scripts/python -m core.test_error_translations modules/production/domain | tail -1` → `0 left`.
- [ ] **Step 3: Run** — `.venv/Scripts/python -m pytest modules/production/domain -q` → no failures (domain tests need no DB).
- [ ] **Step 4: Checkpoint** — the files above.

---

### Task 8: Production — report, conditionnement and regrind services

**Files (Err count):** `backend/modules/production/api/production_report_service.py` (36), `conditionnement_service.py` (15), `regrind_service.py` (14)

- [ ] **Step 1: Translate every `Err` in these files.**
- [ ] **Step 2: Check** — `.venv/Scripts/python -m core.test_error_translations modules/production/api/production_report_service.py modules/production/api/conditionnement_service.py modules/production/api/regrind_service.py | tail -1` → `0 left`.
- [ ] **Step 3: Run** — `.venv/Scripts/python -m pytest modules/production -q` → no failures, integration tests ran.
- [ ] **Step 4: Checkpoint** — the three files.

---

### Task 9: Production — remaining services and the router's own refusals

**Files (Err count):** `backend/modules/production/api/service.py` (9), `dashboard_settings_service.py` (8), `recipe_service.py` (5), `packaging_bom_service.py` (4), `work_center_service.py` (3), `waste_type_service.py` (3), `resource_type_service.py` (3), `packaging_variance_service.py` (3), `recipe_check_service.py` (1), `of_consolidation_service.py` (1), `mold_service.py` (1); and `backend/modules/production/api/router.py` (20 coded `HTTPException` dicts)

Out of scope in `service.py`: the `warnings.append({...})` dicts at ≈lines 491–520 (spec: order-close warnings). They are not `Err` or `HTTPException`, so the guard ignores them — leave them.

- [ ] **Step 1: Translate every `Err` in the service files.**

- [ ] **Step 2: Add `message_fr` to the router's 20 dicts, with this exact French:**

| Line ≈ | English (unchanged) | `message_fr` |
|---|---|---|
| 691, 706, 731 | `f"conversation {conversation_id} not found"` | `f"conversation {conversation_id} introuvable"` |
| 734 | `str(exc)` (RATE_LIMITED) | `"l'assistant reçoit trop de demandes ; réessayez dans un instant"` |
| 737 | `str(exc)` (UNAVAILABLE) | `"l'assistant est indisponible pour le moment ; réessayez plus tard"` |
| 892 | `f"no computable yield for work order {work_order_id}"` | `f"aucun rendement calculable pour l'OF {work_order_id}"` |
| 1086 | `f"no classification for {product_id}"` | `f"aucune classification pour {product_id}"` |
| 1132 | `f"packaging BOM {bom_id} not found"` | `f"nomenclature d'emballage {bom_id} introuvable"` |
| 1547 | `f"recipe {recipe_id} not found"` | `f"recette {recipe_id} introuvable"` |
| 1778 | `f"regrind batch {work_order_id} not found"` | `f"lot de rebroyat {work_order_id} introuvable"` |
| 1916, 1940 | `f"grain must be one of {GRAINS}"` | `f"le regroupement doit être l'un de {GRAINS}"` |
| 2025 | `f"category must be one of {CATEGORIES}"` | `f"la catégorie doit être l'une de {CATEGORIES}"` |
| 2087, 2144 | `"period must be one of 'day', 'week', 'month'"` | `"la période doit être 'day', 'week' ou 'month'"` |
| 2157 | `f"report {report_id} not found"` | `f"rapport {report_id} introuvable"` |
| 2614 | `f"granularity must be one of {GRANULARITIES}"` | `f"la granularité doit être l'une de {GRANULARITIES}"` |
| 2619 | `"date_from cannot be after date_to"` | `"la date de début ne peut pas être après la date de fin"` |
| 2657 | `f"missing permission: {permission}"` | `f"permission manquante : {permission}"` |
| 2665 | `f"unknown section {section_key!r}"` | `f"section inconnue {section_key!r}"` |

Example (line 2657):
```python
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        {"code": "FORBIDDEN", "message": f"missing permission: {permission}", "message_fr": f"permission manquante : {permission}"},
    )
```

- [ ] **Step 3: Check** — `.venv/Scripts/python -m core.test_error_translations modules/production | tail -1` → `0 left` (all of production is now done).
- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest modules/production -q` → no failures, integration tests ran.
- [ ] **Step 5: Checkpoint** — the files above.

---

### Task 10: Warehouse and QC

**Files (Err count):** `backend/modules/warehouse/domain/entities.py` (13), `domain/lot.py` (7), `api/service.py` (7), `api/location_service.py` (3), `api/lot_service.py` (2); `backend/modules/qc/api/quality_service.py` (25), `domain/non_conformity.py` (12), `domain/quality.py` (7), `api/non_conformity_service.py` (7), `domain/parameters.py` (4); `backend/modules/qc/api/router.py` (3 coded dicts)

- [ ] **Step 1: Translate every `Err` in these files.**
- [ ] **Step 2: Add `message_fr` to the QC router dicts:**

| Line ≈ | English | `message_fr` |
|---|---|---|
| 204 | `f"grain must be one of {QualityReportService.GRAINS}"` | `f"le regroupement doit être l'un de {QualityReportService.GRAINS}"` |
| 235 | `f"quality report {report_id} not found"` | `f"rapport qualité {report_id} introuvable"` |
| 584 | `f"non-conformity {non_conformity_id} not found"` | `f"non-conformité {non_conformity_id} introuvable"` |

- [ ] **Step 3: Check** — `.venv/Scripts/python -m core.test_error_translations modules/warehouse modules/qc | tail -1` → `0 left`.
- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest modules/warehouse modules/qc -q` → no failures, integration tests ran.
- [ ] **Step 5: Checkpoint** — the files above.

---

### Task 11: CRM, procurement, HR, maintenance, finance, sales

**Files (Err count):** `backend/modules/crm/api/lead_service.py` (6), `crm/domain/opportunity.py` (5), `crm/api/activity_service.py` (5), `crm/api/contact_service.py` (4), `crm/domain/activity.py` (3), `crm/api/opportunity_service.py` (3), `crm/domain/entities.py` (2); `procurement/api/service.py` (17), `procurement/domain/entities.py` (10); `hr/api/service.py` (9), `hr/api/payroll_service.py` (6), `hr/domain/entities.py` (4), `hr/api/contract_service.py` (2); `maintenance/api/equipment_service.py` (5), `maintenance/domain/equipment.py` (3); `finance/api/service.py` (3), `finance/domain/entities.py` (1); `sales/api/service.py` (2), `sales/domain/entities.py` (1); and `backend/modules/procurement/api/router.py:377` (1 coded dict)

- [ ] **Step 1: Translate every `Err` in these files.**
- [ ] **Step 2: Procurement router line ≈377** — `message_fr`: `f"réception de commande d'achat {receipt_id} introuvable"`.
- [ ] **Step 3: Check** — `.venv/Scripts/python -m core.test_error_translations modules | tail -1` → `0 left` (every module is now done).
- [ ] **Step 4: Run** — `.venv/Scripts/python -m pytest modules/crm modules/procurement modules/hr modules/maintenance modules/finance modules/sales -q` → no failures, integration tests ran.
- [ ] **Step 5: Checkpoint** — the files above.

---

### Task 12: Core — shared kernel, roles/users, login and session

**Files:** `backend/core/domain/entities.py` (24 Err), `backend/core/api/service.py` (18), `backend/core/report_options.py` (7), `backend/core/domain/partner.py` (4), `backend/core/domain/exchange_rate.py` (1); coded dicts in `backend/core/partners.py`, `core/roles.py`, `core/users.py`, `core/tenancy.py`; plain-text details in `backend/core/auth.py`, `core/tenancy.py`

- [ ] **Step 1: Translate every `Err` in the five files.**

- [ ] **Step 2: Add `message_fr` to the core coded dicts:**

| File:line ≈ | English | `message_fr` |
|---|---|---|
| partners.py:108 | `f"partner {partner_id} not found"` | `f"partenaire {partner_id} introuvable"` |
| roles.py:49 | `f"not declared permissions: {', '.join(unknown)}"` | `f"permissions non déclarées : {', '.join(unknown)}"` |
| roles.py:59, users.py:133 | `f"user {user_id} not found"` | `f"utilisateur {user_id} introuvable"` |
| roles.py:68 | `f"role {role_id} not found"` | `f"rôle {role_id} introuvable"` |
| roles.py:124 | `f"role code {body.code} already exists"` | `f"le code de rôle {body.code} existe déjà"` |
| roles.py:216 | `"unassign this role from every user before deleting it"` | `"retirez ce rôle de tous les utilisateurs avant de le supprimer"` |
| roles.py:286 | `"cannot unassign your own only source of core.manage_permissions"` | `"vous ne pouvez pas retirer votre seule source de core.manage_permissions"` |
| users.py:146 | `f"{body.permission} is not a declared permission"` | `f"{body.permission} n'est pas une permission déclarée"` |
| users.py:181 | `"cannot revoke your own core.manage_permissions"` | `"vous ne pouvez pas retirer votre propre core.manage_permissions"` |
| tenancy.py:74 | `f"missing permission: {permission}"` | `f"permission manquante : {permission}"` |

- [ ] **Step 3: Turn the plain-text login/session details into coded dicts**

English text is unchanged; each gets a code and French:

| File:line ≈ | code | message (unchanged) | `message_fr` |
|---|---|---|---|
| auth.py:137 (429) | `TOO_MANY_ATTEMPTS` | `"too many failed login attempts; try again later"` | `"trop de tentatives de connexion échouées ; réessayez plus tard"` |
| auth.py:150 | `INVALID_CREDENTIALS` | `"invalid credentials"` | `"e-mail ou mot de passe incorrect"` |
| auth.py:186 | `INVALID_REFRESH_TOKEN` | `"invalid refresh token"` | `"session invalide ; reconnectez-vous"` |
| auth.py:202 | `REFRESH_TOKEN_USED` | `"refresh token already used"` | `"session déjà renouvelée ; reconnectez-vous"` |
| auth.py:205 | `REFRESH_TOKEN_EXPIRED` | `"refresh token expired"` | `"session expirée ; reconnectez-vous"` |
| tenancy.py:20 | `MISSING_TOKEN` | `"missing bearer token"` | `"vous n'êtes pas connecté"` |
| tenancy.py:34 | `INVALID_SESSION` | `"invalid or expired session"` | `"session invalide ou expirée ; reconnectez-vous"` |

Example (auth.py:150):
```python
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                {"code": "INVALID_CREDENTIALS", "message": "invalid credentials", "message_fr": "e-mail ou mot de passe incorrect"},
            )
```

- [ ] **Step 4: Browser check — expired session still logs out (Review Focus 4)**

Logged in, in French: in DevTools set the stored session's access token to garbage (`sessionStorage["sonalim-erp.session"]`, edit the token field), then trigger any request.
Expected: redirected to `/login` exactly as before (401 still fires `auth:unauthorized`). On the login page, wrong password → « e-mail ou mot de passe incorrect ».

- [ ] **Step 5: Check** — `.venv/Scripts/python -m core.test_error_translations | tail -1` → `0 left` (whole backend).
- [ ] **Step 6: Run** — `.venv/Scripts/python -m pytest core -q` → exactly one failure, `test_every_refusal_carries_its_french [XPASS(strict)]`. That is the guard reporting that nothing is left in English only; Task 13 removes its mark. Any other failure is a real problem. Integration tests ran.
- [ ] **Step 7: Checkpoint** — the files above.

---

### Task 13: Turn the guard on and verify end to end

**Files:**
- Modify: `backend/core/test_error_translations.py` (remove the `xfail` mark)
- Modify: `docs/superpowers/specs/2026-09-25-bilingual-api-errors-design.md` (follow-up note)

- [ ] **Step 1: Remove the mark**

Delete the line `@pytest.mark.xfail(strict=True, reason="French is added module by module; the last task of the plan removes this mark")`.

- [ ] **Step 2: Run the whole backend suite**

Run: `.venv/Scripts/python -m pytest core modules -q`
Expected: all pass, including `test_every_refusal_carries_its_french`; integration tests ran (small skip count).

- [ ] **Step 3: Frontend type check**

Run: `cd frontend && npx tsc -b --force` → no errors.

- [ ] **Step 4: Browser check in French across modules**

In French, confirm a French body on: the screenshot flow (Task 5 Step 5); creating a role with an existing code (Admin → Rôles) → « le code de rôle … existe déjà »; one QC or warehouse refusal of your choice (e.g. a negative quantity). Switch to English and repeat one → English.

- [ ] **Step 5: Record the follow-up**

Append to the spec's "Out of scope" section: `Follow-up: translate the order-close warnings in production/api/service.py (NO_VALIDATED_REPORTS, MISSING_START_DATE, OPEN_QUALITY_FOLLOW_UPS, OPEN_NON_CONFORMITIES) and wherever the frontend renders them.`

- [ ] **Step 6: Checkpoint** — `backend/core/test_error_translations.py`, the spec.
