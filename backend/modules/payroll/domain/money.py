"""XOF amounts: whole francs, Decimal only, rounded the way the rule set says."""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal

ZERO = Decimal(0)
HUNDRED = Decimal(100)
ROUND_MODES = ("half_up", "down", "up")
_ROUNDING = {"half_up": ROUND_HALF_UP, "down": ROUND_DOWN, "up": ROUND_UP}


def round_amount(value: Decimal, *, round_to: int = 1, mode: str = "half_up") -> Decimal:
    """Round to a multiple of `round_to` francs.

    'down' goes toward zero, 'up' away from zero, 'half_up' to the nearest multiple with halves
    away from zero — the same on both signs, so a negative line (unpaid absence) rounds like its
    positive twin.
    """
    if round_to < 1:
        raise ValueError("round_to must be at least 1")
    if mode not in _ROUNDING:
        raise ValueError(f"unknown round mode {mode!r}")
    step = Decimal(round_to)
    return (value / step).quantize(Decimal(1), rounding=_ROUNDING[mode]) * step


def percent_of(amount: Decimal, percent: Decimal) -> Decimal:
    """`percent` is written the way the accountant writes it: 3.6 means 3.6 %. Not rounded."""
    return amount * percent / HUNDRED
