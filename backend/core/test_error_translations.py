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


def test_every_refusal_carries_its_french():
    problems = untranslated(ROOTS)
    assert not problems, "\n".join(problems)


if __name__ == "__main__":
    left = untranslated(sys.argv[1:] or ROOTS)
    print("\n".join(left))
    print(f"{len(left)} left")
