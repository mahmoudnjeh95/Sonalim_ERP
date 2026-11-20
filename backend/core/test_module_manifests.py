"""Every module.json says what the code really does (WP-0.5).

The manifests are the module contract: which modules a module needs, which events it publishes
and consumes, which services it offers. Nothing enforced them, so they drifted. These tests read
the source (AST, no database) and the live consumer registry, and fail when a manifest, the code,
`events/CATALOG.md` and the worker disagree.

Rules:
- `depends`: another module imported at module level by non-test code. The module cannot be
  imported without it. Every module depends on `core`. The `depends` graph has no cycle.
- `optional_depends`: another module imported only inside a function or a guard (called at run
  time on some paths). Tests may import any module; they are not counted.
- Both lists are exact: a module listed without such an import is an error.
- `publishes_events`: exactly the event types passed to `publish_event` with
  `producer="<module>"`. Literals, module constants and `a if c else b` are read from the code;
  computed names are listed in `DYNAMIC_EVENT_TYPES` below, which a new computed call site must
  join before the test passes.
- `subscribes_events`: exactly the event types the module's `events/` handlers register.
- `provides_api`: each name is a class or submodule of the module's `api/`, and every `*Service`
  class, or `api` submodule imported whole, that another module uses is listed.
- The catalog has one row per published event, its Producer is the publishing module and its
  Consumers name exactly the subscribing modules.
"""
from __future__ import annotations

import ast
import functools
import importlib
import json
import pathlib
import re

import pytest

from core.events import consumers as event_consumers

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MODULES_DIR = BACKEND / "modules"
CATALOG = BACKEND / "events" / "CATALOG.md"
WORKER = BACKEND / "worker" / "main.py"

MANIFESTS = {path.parent.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(MODULES_DIR.glob("*/module.json"))}
MODULE_NAMES = sorted(MANIFESTS)

# publish_event calls whose event_type is computed. Key: (module, file relative to the module,
# enclosing function). Value: every event type the call can produce.
DYNAMIC_EVENT_TYPES: dict[tuple[str, str, str], set[str]] = {
    ("crm", "api/opportunity_service.py", "transition_stage"): {"crm.opportunity.won", "crm.opportunity.lost"},
    ("finance", "api/service.py", "_apply_transition"): {"finance.invoice.issued", "finance.invoice.paid"},
    ("payroll", "api/run_service.py", "_publish"): {"payroll.run.approved", "payroll.run.paid", "payroll.run.reversed"},
    ("treasury", "api/document_service.py", "_publish"): {
        "treasury.receipt.posted",
        "treasury.receipt.cancelled",
        "treasury.disbursement.posted",
        "treasury.disbursement.cancelled",
    },
}


def _is_test_file(path: pathlib.Path) -> bool:
    return path.name.startswith("test_") or path.name == "conftest.py"


def _source_files(module: str) -> list[pathlib.Path]:
    return [path for path in sorted((MODULES_DIR / module).rglob("*.py")) if not _is_test_file(path)]


@functools.cache
def _parse(path: pathlib.Path) -> ast.Module:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]
    return tree


def _ancestors(node: ast.AST):
    while hasattr(node, "parent"):
        node = node.parent  # type: ignore[attr-defined]
        yield node


def _imported_modules(node: ast.AST) -> list[tuple[str, list[str]]]:
    """(other module, names imported from it) for an import of `modules.<other>...`."""
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        parts = node.module.split(".")
        if parts[0] == "modules" and len(parts) > 1:
            return [(parts[1], [alias.name for alias in node.names])]
    if isinstance(node, ast.Import):
        found = []
        for alias in node.names:
            parts = alias.name.split(".")
            if parts[0] == "modules" and len(parts) > 1:
                found.append((parts[1], []))
        return found
    return []


@functools.cache
def _code_dependencies(module: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Other modules imported at module level and lazily, each with the files that import it."""
    eager: dict[str, set[str]] = {}
    lazy: dict[str, set[str]] = {}
    for path in _source_files(module):
        relative = str(path.relative_to(MODULES_DIR / module))
        for node in ast.walk(_parse(path)):
            for other, _names in _imported_modules(node):
                if other == module:
                    continue
                guarded = any(
                    isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.If, ast.Try))
                    for ancestor in _ancestors(node)
                )
                (lazy if guarded else eager).setdefault(other, set()).add(relative)
    return eager, lazy


def _module_constants(tree: ast.Module) -> dict[str, str]:
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = node.value.value
    return constants


def _resolve(expression: ast.expr, constants: dict[str, str]) -> set[str] | None:
    """The strings an expression can be, or None when it is computed."""
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return {expression.value}
    if isinstance(expression, ast.Name) and expression.id in constants:
        return {constants[expression.id]}
    if isinstance(expression, ast.IfExp):
        body, orelse = _resolve(expression.body, constants), _resolve(expression.orelse, constants)
        if body is not None and orelse is not None:
            return body | orelse
    return None


def _enclosing_function(node: ast.AST) -> str:
    for ancestor in _ancestors(node):
        if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return ancestor.name
    return "<module>"


@functools.cache
def _published_events() -> tuple[dict[str, set[str]], list[str]]:
    """Event types each producer publishes, plus problems (computed names not listed, bad producer)."""
    published: dict[str, set[str]] = {}
    problems: list[str] = []
    used_dynamic: set[tuple[str, str, str]] = set()
    files = [(module, path) for module in MODULE_NAMES for path in _source_files(module)]
    files += [("core", path) for path in sorted((BACKEND / "core").rglob("*.py")) if not _is_test_file(path)]
    for module, path in files:
        tree = _parse(path)
        constants = _module_constants(tree)
        base = MODULES_DIR / module if module != "core" else BACKEND / "core"
        relative = str(path.relative_to(base))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if callee != "publish_event":
                continue
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            where = f"{module}/{relative}:{node.lineno}"
            producer = _resolve(keywords["producer"], constants) if "producer" in keywords else None
            if producer != {module}:
                problems.append(f"{where}: producer must be {module!r}")
            event_types = _resolve(keywords["event_type"], constants) if "event_type" in keywords else None
            if event_types is None:
                key = (module, relative, _enclosing_function(node))
                if key not in DYNAMIC_EVENT_TYPES:
                    problems.append(f"{where}: computed event_type; list what it can be in DYNAMIC_EVENT_TYPES as {key}")
                    continue
                used_dynamic.add(key)
                event_types = DYNAMIC_EVENT_TYPES[key]
            published.setdefault(module, set()).update(event_types)
    for key in sorted(set(DYNAMIC_EVENT_TYPES) - used_dynamic):
        problems.append(f"DYNAMIC_EVENT_TYPES entry {key} matches no publish_event call any more")
    return published, problems


def _consumer_files() -> list[pathlib.Path]:
    return [
        path
        for path in sorted(MODULES_DIR.glob("*/events/*.py"))
        if not _is_test_file(path) and "register(" in path.read_text(encoding="utf-8")
    ]


@functools.cache
def _subscribed_events() -> dict[str, set[str]]:
    for path in _consumer_files():
        importlib.import_module(".".join(path.relative_to(BACKEND).with_suffix("").parts))
    subscribed: dict[str, set[str]] = {}
    for event_type, handlers in event_consumers._registry.items():
        for _consumer_name, handler in handlers:
            parts = handler.__module__.split(".")
            if parts[0] == "modules":
                subscribed.setdefault(parts[1], set()).add(event_type)
    return subscribed


def _catalog_rows() -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    for line in CATALOG.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*`([a-z_]+\.[a-z_]+\.[a-z_]+)`\s*\|([^|]*)\|([^|]*)\|([^|]*)\|", line)
        if match:
            event_type, _version, producer, consumers = (part.strip() for part in match.groups())
            assert event_type not in rows, f"{event_type} has two rows in CATALOG.md"
            rows[event_type] = (producer, consumers)
    return rows


def _modules_named(text: str) -> set[str]:
    words = set(re.findall(r"[a-z_]+", re.sub(r"\([^)]*\)", "", text)))
    return words & (set(MODULE_NAMES) | {"core"})


# --- dependencies -----------------------------------------------------------------------------


@pytest.mark.parametrize("module", MODULE_NAMES)
def test_depends_lists_the_modules_imported_at_module_level(module):
    eager, _lazy = _code_dependencies(module)
    manifest = MANIFESTS[module]
    assert manifest["depends"][0] == "core"
    declared = set(manifest["depends"]) - {"core"}
    missing = {other: sorted(files) for other, files in eager.items() if other not in declared}
    assert not missing, f"{module}: imported at module level, add to depends: {missing}"
    unused = declared - set(eager)
    assert not unused, f"{module}: in depends but never imported at module level: {sorted(unused)}"


@pytest.mark.parametrize("module", MODULE_NAMES)
def test_optional_depends_lists_the_modules_imported_lazily(module):
    eager, lazy = _code_dependencies(module)
    manifest = MANIFESTS[module]
    expected = set(lazy) - set(eager)
    declared = set(manifest["optional_depends"])
    assert not declared & set(manifest["depends"]), f"{module}: a module is in both depends and optional_depends"
    missing = {other: sorted(lazy[other]) for other in expected - declared}
    assert not missing, f"{module}: imported only inside functions, add to optional_depends: {missing}"
    unused = declared - expected
    assert not unused, f"{module}: in optional_depends but not lazily imported: {sorted(unused)}"


def test_every_dependency_is_a_known_module():
    known = set(MODULE_NAMES) | {"core"}
    for module, manifest in MANIFESTS.items():
        assert manifest["name"] == module
        unknown = (set(manifest["depends"]) | set(manifest["optional_depends"])) - known
        assert not unknown, f"{module}: unknown modules {sorted(unknown)}"


def test_the_depends_graph_has_no_cycle():
    graph = {module: [other for other in MANIFESTS[module]["depends"] if other != "core"] for module in MODULE_NAMES}
    state: dict[str, str] = {}

    def visit(module: str, path: list[str]) -> None:
        if state.get(module) == "done":
            return
        assert state.get(module) != "visiting", f"depends cycle: {' -> '.join(path + [module])}"
        state[module] = "visiting"
        for other in graph[module]:
            visit(other, path + [module])
        state[module] = "done"

    for module in MODULE_NAMES:
        visit(module, [])


# --- events -----------------------------------------------------------------------------------


def test_publish_event_calls_are_readable():
    _published, problems = _published_events()
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("module", MODULE_NAMES)
def test_publishes_events_matches_the_code(module):
    published, _problems = _published_events()
    declared = MANIFESTS[module]["publishes_events"]
    assert len(declared) == len(set(declared)), f"{module}: duplicate in publishes_events"
    code = published.get(module, set())
    assert not code - set(declared), f"{module}: published but not declared: {sorted(code - set(declared))}"
    assert not set(declared) - code, f"{module}: declared but never published: {sorted(set(declared) - code)}"
    for event_type in declared:
        assert event_type.split(".")[0] == module, f"{module}: {event_type} is named after another module"


@pytest.mark.parametrize("module", MODULE_NAMES)
def test_subscribes_events_matches_the_registered_handlers(module):
    declared = MANIFESTS[module]["subscribes_events"]
    assert len(declared) == len(set(declared)), f"{module}: duplicate in subscribes_events"
    code = _subscribed_events().get(module, set())
    assert not code - set(declared), f"{module}: handled but not declared: {sorted(code - set(declared))}"
    assert not set(declared) - code, f"{module}: declared but no handler: {sorted(set(declared) - code)}"


def test_every_subscribed_event_is_published_somewhere():
    published, _problems = _published_events()
    every_published = set().union(*published.values())
    for module, manifest in MANIFESTS.items():
        orphans = set(manifest["subscribes_events"]) - every_published
        assert not orphans, f"{module}: subscribes to events nobody publishes: {sorted(orphans)}"


def test_the_worker_loads_every_consumer_file():
    worker_imports = set()
    for node in ast.walk(_parse(WORKER)):
        if isinstance(node, ast.ImportFrom) and node.module:
            worker_imports.update(f"{node.module}.{alias.name}" for alias in node.names)
        if isinstance(node, ast.Import):
            worker_imports.update(alias.name for alias in node.names)
    for path in _consumer_files():
        dotted = ".".join(path.relative_to(BACKEND).with_suffix("").parts)
        assert dotted in worker_imports, f"worker/main.py does not import {dotted}, so its handlers never run"


def test_the_catalog_matches_the_publishers_and_consumers():
    published, _problems = _published_events()
    subscribed = _subscribed_events()
    rows = _catalog_rows()
    producers = {event_type: module for module, events in published.items() for event_type in events}
    missing = sorted(set(producers) - set(rows))
    assert not missing, f"published but not in CATALOG.md: {missing}"
    stale = sorted(set(rows) - set(producers))
    assert not stale, f"in CATALOG.md but nobody publishes it: {stale}"
    wrong = []
    for event_type, (producer, consumers) in sorted(rows.items()):
        if producer != producers[event_type]:
            wrong.append(f"{event_type}: producer {producer!r}, code {producers[event_type]!r}")
        actual = {module for module, events in subscribed.items() if event_type in events}
        named = _modules_named(consumers)
        if named != actual:
            wrong.append(f"{event_type}: Consumers names {sorted(named)}, handlers are in {sorted(actual)}")
    assert not wrong, "CATALOG.md disagrees with the code:\n" + "\n".join(wrong)


# --- provided services ------------------------------------------------------------------------


@functools.cache
def _api_names(module: str) -> set[str]:
    """Classes defined in the module's api/ package, and its submodules (e.g. `report_queries`)."""
    names = set()
    for path in _source_files(module):
        if "api" not in path.relative_to(MODULES_DIR / module).parts:
            continue
        names.add(path.stem)
        names.update(node.name for node in _parse(path).body if isinstance(node, ast.ClassDef))
    return names


@functools.cache
def _api_submodules(module: str) -> set[str]:
    return {path.stem for path in (MODULES_DIR / module / "api").glob("*.py") if not _is_test_file(path)} - {"__init__"}


@pytest.mark.parametrize("module", MODULE_NAMES)
def test_provides_api_names_real_classes(module):
    declared = MANIFESTS[module]["provides_api"]
    assert len(declared) == len(set(declared)), f"{module}: duplicate in provides_api"
    unknown = set(declared) - _api_names(module)
    assert not unknown, f"{module}: provides_api names no class or submodule in api/: {sorted(unknown)}"


def test_services_used_by_other_modules_are_in_provides_api():
    """Counts `*Service` classes and `from modules.<x>.api import <submodule>`; helpers and constants are not."""
    used: dict[str, dict[str, set[str]]] = {}
    for module in MODULE_NAMES:
        for path in _source_files(module):
            for node in ast.walk(_parse(path)):
                for other, names in _imported_modules(node):
                    if other != module and other in MANIFESTS:
                        submodules = _api_submodules(other) if getattr(node, "module", None) == f"modules.{other}.api" else set()
                        for name in names:
                            if name.endswith("Service") or name in submodules:
                                used.setdefault(other, {}).setdefault(name, set()).add(module)
    missing = {
        f"{other}.{name}": sorted(users)
        for other, services in sorted(used.items())
        for name, users in services.items()
        if name not in MANIFESTS[other]["provides_api"]
    }
    assert not missing, f"imported by other modules, add to the owner's provides_api: {missing}"
