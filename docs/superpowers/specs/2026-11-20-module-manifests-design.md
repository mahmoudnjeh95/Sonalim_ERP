# Module manifests match the code (WP-0.5)

## Problem

Each `backend/modules/<module>/module.json` declares what the module needs (`depends`,
`optional_depends`), offers (`provides_api`), publishes and consumes (events). Nothing checked
these lists, so they no longer matched the code. Two examples: production listed only `core` in
`depends` while it imports warehouse, procurement, maintenance and hr when it loads, and the
catalog said payroll consumes `hr.presence_month.closed`, which no handler does. The manifests
also had no defined meaning for "optional".

## Rule (what each field means)

- `depends`: the modules imported at module level by the module's non-test code. Without them
  the module cannot be imported. Always starts with `core`. The graph has no cycle.
- `optional_depends`: the modules imported only inside a function or under a guard. They are
  used at run time on some code paths. Test files can import any module; they are not counted.
- Both lists are exact: listing a module that is not imported that way is an error. Events are
  not dependencies. A module that only reacts to another's events lists those events in
  `subscribes_events` and does not list the module.
- `publishes_events`: exactly the event types passed to `publish_event(producer="<module>")`.
- `subscribes_events`: exactly the event types the module's `events/` handlers `register`.
- `provides_api`: names that exist in the module's `api/` (a class or a submodule), and every
  `*Service` class (or `api` submodule imported whole) that another module uses.
- `events/CATALOG.md`: one row per published event. Its Producer is the publishing module and its
  Consumers column names exactly the modules with a handler. Text in parentheses is a comment
  and is not read.
- `worker/main.py` imports every `events/` file that registers handlers, or they never run.

## Check

`backend/core/test_module_manifests.py`, no database. It reads the source with `ast`, imports the
consumer files and reads the live `core.events.consumers` registry. A computed `event_type` (an
f-string or a parameter) cannot be read from the source. Each such call site is listed in the
test's `DYNAMIC_EVENT_TYPES` with the events it can produce. A new computed site fails the test
until it is listed there, and an entry that no longer matches a call site fails it too.

## Changes to the code

- Manifests corrected in crm, finance, hr, maintenance, procurement, production, qc, scan,
  treasury and warehouse (deps, a non-existent `HrDashboardService`, services used across modules).
- `maintenance/api/history_export.py` imported production's spreadsheet style at module level
  while production imports maintenance the same way, which made a dependency cycle. The import
  now runs inside `journal_workbook`, so production stays an optional dependency of maintenance.
- Catalog: hr is listed as a consumer of `payroll.run.approved` / `.reversed`.
  `hr.presence_month.closed` is marked as having no consumer yet.

No schema, API, event or frontend change.
