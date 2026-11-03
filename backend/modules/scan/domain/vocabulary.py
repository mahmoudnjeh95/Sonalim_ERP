"""Turning what is written on a fiche ("BSK1", "Déchet Presse", "C2") into a system value.

A learned alias always wins: it is what a person chose for exactly this writing. Then
an exact name or code, then a name whose words all appear in the writing (or the
reverse) -- a partial match a person should glance at. Several candidates are narrowed
by a preferred value (the default OF's product) when it is one of them; otherwise the
result is ambiguous. Nothing is guessed beyond that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from modules.scan.domain.text import normalize, tokens

KINDS: tuple[str, ...] = (
    "raw_material", "regrind_item", "finished_product", "film_item", "waste_production", "waste_packing",
    "equipment", "mold", "downtime_motif", "line_state", "check_state", "team", "person",
)


@dataclass(frozen=True)
class Term:
    value: str
    names: tuple[str, ...]
    attrs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Vocabulary:
    terms: Mapping[str, tuple[Term, ...]]

    def of(self, kind: str) -> tuple[Term, ...]:
        return tuple(self.terms.get(kind, ()))

    def attr(self, kind: str, value: str, key: str) -> Any:
        term = next((t for t in self.of(kind) if t.value == value), None)
        return term.attrs.get(key) if term else None

    def label(self, kind: str, value: str) -> str | None:
        term = next((t for t in self.of(kind) if t.value == value), None)
        return next((n for n in term.names if n), None) if term else None


@dataclass(frozen=True)
class Resolution:
    value: str | None
    how: str
    candidates: tuple[str, ...] = ()

    @property
    def sure(self) -> bool:
        return self.how in ("alias", "exact", "narrowed")


def _contains(name: str, written: set[str]) -> bool:
    words = tokens(name)
    return bool(words) and (words <= written or written <= words)


def resolve(
    vocabulary: Vocabulary, aliases: Mapping[tuple[str, str], str], kind: str, text: str | None, prefer: str | None = None
) -> Resolution:
    key = normalize(text)
    if not key:
        return Resolution(None, "empty")
    learned = aliases.get((kind, key))
    if learned is not None:
        return Resolution(learned, "alias")
    terms = vocabulary.of(kind)
    exact = list(dict.fromkeys(t.value for t in terms if any(normalize(n) == key for n in t.names)))
    if len(exact) == 1:
        return Resolution(exact[0], "exact")
    written = tokens(text)
    matches = exact or list(dict.fromkeys(t.value for t in terms if any(_contains(n, written) for n in t.names)))
    if prefer is not None and prefer in matches:
        return Resolution(prefer, "narrowed", tuple(matches))
    if len(matches) == 1:
        return Resolution(matches[0], "contained")
    if matches:
        return Resolution(None, "ambiguous", tuple(matches))
    return Resolution(None, "none")
