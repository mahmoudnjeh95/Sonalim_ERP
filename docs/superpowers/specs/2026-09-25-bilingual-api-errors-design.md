# Bilingual API errors — design

Date: 2026-09-25
Status: approved in conversation, awaiting spec review

## Problem

A user working in French hands in the Conditionnement section and gets a toast whose title is
French (« Cela n'a pas fonctionné ») but whose body is English (« packing row 1: enter and save
this shift's production first; a lot is filed under its work order »).

The title comes from the frontend dictionary. The body is `ApiError.message`, which is the
backend's `detail.message` passed through untouched, and every backend error message is written
in English only. The frontend shows that raw text in 128 places across 49 files, so the whole
application mixes languages whenever something is refused.

The refusal itself is correct: the packing row names no OF, and the shift has no saved
production run to take one from, so the lot cannot be filed under a work order. The message just
does not say what to do about it, and it is not in the user's language.

## Goal

Every error the backend refuses a request with reaches a French user in French, with the same
meaning as the English. Nothing gets worse for an error nobody has translated yet: it keeps
showing the English text it shows today.

## Inventory (measured 2026-09-25)

| Where | Count | Shape |
|---|---|---|
| `Err(code, message)` constructions (domain + service layers, every module) | 481 in ~65 files | `core/domain/result.py` dataclass |
| Router conversions `{"code": result.code, "message": result.message}` | 115, all identical | core/*.py + every module router |
| Raw `HTTPException` dicts with a code | 35 | core/*.py, production/qc/procurement routers |
| Plain-string `HTTPException` details | ~6 | `core/auth.py`, `core/tenancy.py` (credentials, bearer, session, refresh token) |
| `Err` re-wrapped with a prefix | 4 | `shift_sections.py:717,759`, `shift_validation_service.py:221`, `stock_release_service.py:265` |
| Frontend `error.message` displays | 128 in 49 files | `toast.error(..., { description: error instanceof ApiError ? error.message : undefined })` and similar |
| Frontend branches on error text | 0 | the 4 branches that exist test `error.code` |
| Frontend `fetch` calls outside `apiFetch` | 2 | the two Excel exports in `features/production/api.ts` |

Out of scope: the order-close warnings built in `production/api/service.py` (`NO_VALIDATED_REPORTS`,
`MISSING_START_DATE`, `OPEN_QUALITY_FOLLOW_UPS`, `OPEN_NON_CONFORMITIES`). They are advisory rows
in a response body, not refusals, and are shown by a different screen. Listed as a follow-up.

Also out of scope: messages written only to logs or scripts (`events/consumers.py` RuntimeErrors,
`scripts/seed_*.py` prints). They never reach a user.

Follow-up: translate the order-close warnings in production/api/service.py (NO_VALIDATED_REPORTS, MISSING_START_DATE, OPEN_QUALITY_FOLLOW_UPS, OPEN_NON_CONFORMITIES) and wherever the frontend renders them.

## Design

### Backend: the French travels with the English

1. **`Err` gains an optional French message.**
   `core/domain/result.py`:
   ```python
   @dataclass(frozen=True)
   class Err:
       code: str
       message: str
       message_fr: str | None = None
   ```
   Positional order is unchanged, so every existing `Err(code, message)` still works, and every
   test that asserts on `.message` keeps asserting on the same English text.

2. **One helper builds the HTTP detail.**
   `core/domain/result.py` gains:
   ```python
   def err_detail(err: Err) -> dict[str, str | None]:
       return {"code": err.code, "message": err.message, "message_fr": err.message_fr}
   ```
   The 115 router conversions `{"code": result.code, "message": result.message}` become
   `err_detail(result)`. Without this step the French would be dropped at the router.

3. **Every `Err(...)` construction gets its French.**
   All 481 sites, written next to the English as the third argument. Dynamic values (row
   numbers, names, quantities, codes) are interpolated into both strings the same way.
   Named message tables such as `_ORDER_PROBLEMS` in `packing_derivation_service.py` become
   `{code: (en, fr)}` pairs.

4. **Wrapped errors wrap both languages.**
   The 4 prefixing sites build the French from the inner `message_fr`, falling back to the inner
   English when the inner error has no French yet:
   ```python
   return Err(checked.code, f"packing row {index}: {checked.message}",
              f"ligne de conditionnement {index} : {checked.message_fr or checked.message}")
   ```

5. **Raw `HTTPException` dicts and plain strings get `message_fr` too.**
   The 35 coded dicts gain a `"message_fr"` key. The plain-string details in `auth.py` and
   `tenancy.py` become `{"code", "message", "message_fr"}` dicts with codes
   `INVALID_CREDENTIALS`, `MISSING_TOKEN`, `INVALID_SESSION`, `INVALID_REFRESH_TOKEN`,
   `REFRESH_TOKEN_USED`, `REFRESH_TOKEN_EXPIRED`. The frontend already reads a dict detail, and
   no frontend code branches on these strings.

### Frontend: one file

`frontend/src/lib/api.ts`, in `apiFetch`'s error branch:

- If the detail is a dict: use `detail.message_fr` when the stored language is `fr` and the key is
  present and non-empty, otherwise `detail.message`. The language is read with the module-level
  reader `i18n.tsx` already uses for `currentLocale()`, exported for this purpose.
- If the detail is a list (FastAPI's own 422 request validation): show
  « Certaines valeurs envoyées ne sont pas valides. » / "Some values sent are not valid.", with
  code `VALIDATION_ERROR`, instead of today's raw `statusText` ("Unprocessable Entity").
- If `fetch` itself throws (server down, network lost): throw an `ApiError` with status 0, code
  `NETWORK_ERROR` and « Le serveur est injoignable. Vérifiez la connexion et réessayez. » /
  "The server cannot be reached. Check the connection and try again." instead of the browser's
  "Failed to fetch". Status 0 does not trigger the 401 logout path.
- Any other non-dict, non-string detail keeps today's `statusText` fallback.

The response-to-`ApiError` step is pulled out of `apiFetch` into an exported
`apiErrorFromResponse(response)`, so the two blob downloads in `features/production/api.ts`
(`exportConsumptionBySupplier`, `exportProductionRecap`), which call `fetch` directly and today
throw `response.statusText`, use it too. They are the only `fetch` calls outside `lib/api.ts`.

Because `ApiError.message` is already in the right language, none of the 49 files that show
`error.message` change. `ApiError` also keeps the English as a `messageEn` property for anyone
who needs to log or compare it.

A language switch after an error was thrown does not re-translate that toast; the next error uses
the new language. Accepted: toasts are short-lived.

### The screenshot's message

`PRODUCTION_FIRST` is reworded so it names both ways out, in both languages:

- en: "packing row {n}: pick this lot's OF, or save this shift's production first so it can be taken from there"
- fr: « ligne de conditionnement {n} : choisissez l'OF de ce lot, ou enregistrez d'abord la production de ce shift pour qu'il en soit repris »

`OF_AMBIGUOUS` and `PACKAGING_STORES_DIFFER` are translated with their meaning unchanged.
Behaviour of `resolve_packing_order` is unchanged.

## Translation rules

- French is written for plant operators and office staff: plain, direct, vous-form, using the
  vocabulary the UI already uses (OF, shift, lot, conditionnement, rendre, valider, brouillon,
  magasin, F CFA). When in doubt, reuse the wording of the matching `fr` key in `i18n.tsx` or
  `shiftText.ts`.
- French typography: a non-breaking space is not required; a normal space before `:`, `;`, `?`,
  `!` and inside « » is used consistently.
- Technical identifiers inside messages (permission codes, enum values like `day`/`week`, field
  names in `grain must be one of …`) stay as they are; only the prose around them is translated.
- The English text is not reworded, except `PRODUCTION_FIRST` above, so existing tests and logs
  stay stable.

## Guarding against regressions

- A backend test walks every `.py` file under `backend/core` and `backend/modules` (excluding
  tests), parses it with `ast`, and fails on any `Err(...)` call with fewer than three positional
  arguments and no `message_fr=` keyword, and on any `HTTPException` whose detail dict literal has
  a `"message"` key but no `"message_fr"` key. It prints each offender as `file:line`.
  New English-only errors therefore fail CI instead of shipping.
- `err_detail` gets a unit test.
- `packing_derivation` gets a domain test for the reworded `PRODUCTION_FIRST` in both languages.
- `apiFetch` language selection, 422-list fallback and network fallback get a unit test if the
  frontend has a test runner; otherwise they are verified in the browser.

## Verification

- `pytest` for each module after its sites are translated (DB-backed tests must actually run, not
  skip — check the skip count).
- `tsc -b --force` for the frontend.
- Browser, in French: reproduce the screenshot (Conditionnement row with no OF on a shift with no
  saved production → Rendre) and see the French message; trigger one error in another module
  (e.g. a duplicate role code) and see French; switch to English and see English.

## Rollout order

1. Mechanism: `Err.message_fr`, `err_detail`, the 115 router conversions, `api.ts`. After this
   step the app behaves exactly as today (no French yet), which proves the plumbing is inert.
2. The screenshot's flow: `packing_derivation_service.py` and the production shift services.
3. Remaining modules one at a time: production (rest), core, warehouse, qc, crm, procurement,
   maintenance, finance, sales, hr. Each step ends with that module's tests.
4. Raw `HTTPException` dicts and the auth/tenancy plain strings.
5. Turn on the regression guard test (it fails until step 3–4 are complete, so it lands last).
