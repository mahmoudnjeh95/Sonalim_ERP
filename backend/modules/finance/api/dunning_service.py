"""Dunning (relances): which customers to chase and how hard, what was done about it, and the letters.

A customer's lateness is measured on its oldest unpaid installment past due. Each level has a delay after
the due date; reaching a level the customer hasn't been sent a letter for in this run of lateness puts it
on the list. A promise to pay keeps it off until the promised date; once that date passes with the money
still late, the promise is broken and the customer is back on the list. The last default level puts the
account on hold: sales refuses new orders (see ReceivablesService.check_order_credit).

There is no e-mail facility in the platform, so letters are printed (or saved as PDF from the print
dialog) and recorded here; the people who chase are told in the app."""
from __future__ import annotations

import datetime
import json
from decimal import Decimal
from typing import Any

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from core.notifications import notify, users_with_permission
from modules.finance.domain.receivables import DEFAULT_LEVELS, level_reached

ACTION_KINDS = ("letter", "call", "email", "promise", "note")
MANAGE_PERMISSION = "finance.manage_dunning"
_LEVEL_COLUMNS = "level, days_after_due, name_fr, name_en, letter_fr, letter_en, blocks_orders"
_ACTION_COLUMNS = ("id, partner_id, kind, level, note, invoice_ids, amount_due, promise_date, promise_amount, promise_status, "
                   "created_by, created_at")


def _level_row(row) -> dict[str, Any]:
    keys = ("level", "days_after_due", "name_fr", "name_en", "letter_fr", "letter_en", "blocks_orders")
    return dict(zip(keys, row))


def _action_row(row) -> dict[str, Any]:
    keys = ("id", "partner_id", "kind", "level", "note", "invoice_ids", "amount_due", "promise_date", "promise_amount",
            "promise_status", "created_by", "created_at")
    return dict(zip(keys, row))


class DunningService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- levels ----------------------------------------------------------------------------------------

    def levels(self, *, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            f"SELECT {_LEVEL_COLUMNS} FROM finance.dunning_levels WHERE tenant_id = %s ORDER BY level", (tenant_id,)).fetchall()
        if not rows:
            for level, days, name_fr, name_en, blocks, letter_fr, letter_en in DEFAULT_LEVELS:
                self._connection.execute(
                    f"INSERT INTO finance.dunning_levels (tenant_id, {_LEVEL_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (tenant_id, level, days, name_fr, name_en, letter_fr, letter_en, blocks),
                )
            rows = self._connection.execute(
                f"SELECT {_LEVEL_COLUMNS} FROM finance.dunning_levels WHERE tenant_id = %s ORDER BY level", (tenant_id,)).fetchall()
        return [_level_row(row) for row in rows]

    def save_levels(self, *, tenant_id: str, actor_id: str, levels: list[dict[str, Any]]) -> Result[list[dict[str, Any]]]:
        """Replaces the whole ladder: levels 1..n with strictly increasing delays."""
        if not levels:
            return Err("INVALID_DUNNING_LEVELS", "keep at least one dunning level", "gardez au moins un niveau de relance")
        cleaned = []
        for index, level in enumerate(sorted(levels, key=lambda l: int(l["days_after_due"])), start=1):
            name_fr = str(level.get("name_fr") or "").strip()
            if not name_fr:
                return Err("INVALID_DUNNING_LEVELS", "every level needs a name", "chaque niveau a un nom")
            cleaned.append((index, int(level["days_after_due"]), name_fr, str(level.get("name_en") or name_fr).strip(),
                            str(level.get("letter_fr") or "").strip(), str(level.get("letter_en") or level.get("letter_fr") or "").strip(),
                            bool(level.get("blocks_orders"))))
        delays = [c[1] for c in cleaned]
        if delays[0] < 1 or len(set(delays)) != len(delays) or len(cleaned) > 9:
            return Err("INVALID_DUNNING_LEVELS", "delays start at 1 day, differ from one level to the next, and there are at most 9 levels",
                       "les délais commencent à 1 jour, diffèrent d'un niveau à l'autre, et il y a au plus 9 niveaux")
        self._connection.execute("DELETE FROM finance.dunning_levels WHERE tenant_id = %s", (tenant_id,))
        for row in cleaned:
            self._connection.execute(
                f"INSERT INTO finance.dunning_levels (tenant_id, {_LEVEL_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (tenant_id, *row))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="dunning_levels.updated", entity_type="dunning_levels",
                     entity_id=tenant_id, payload={"levels": [{"level": c[0], "days": c[1], "blocks": c[6]} for c in cleaned]})
        return Ok(self.levels(tenant_id=tenant_id))

    # ---- the list of customers to chase -----------------------------------------------------------------

    def _actions(self, tenant_id: str, partner_id: str | None = None) -> list[dict[str, Any]]:
        clause, params = ("AND partner_id = %s", [tenant_id, partner_id]) if partner_id else ("", [tenant_id])
        rows = self._connection.execute(
            f"SELECT {_ACTION_COLUMNS} FROM finance.dunning_actions WHERE tenant_id = %s {clause} ORDER BY created_at DESC", params
        ).fetchall()
        return [_action_row(row) for row in rows]

    def history(self, *, tenant_id: str, partner_id: str) -> list[dict[str, Any]]:
        return self._actions(tenant_id, partner_id)

    def worklist(self, *, tenant_id: str, today: datetime.date | None = None) -> list[dict[str, Any]]:
        """Every customer with money past due: how much, how late, the level reached, the last letter sent in
        this run of lateness, any open or broken promise, and whether it needs chasing now."""
        from modules.finance.api.receivables_service import ReceivablesService, is_chased

        today = today or datetime.date.today()
        receivables = ReceivablesService(self._connection)
        levels = self.levels(tenant_id=tenant_id)
        chase_from = receivables.settings(tenant_id=tenant_id)["chase_from"]
        late: dict[str, list[dict[str, Any]]] = {}
        for invoice in receivables._open_invoices(tenant_id, None, today):
            if is_chased(invoice, chase_from):
                late.setdefault(invoice["partner_id"], []).append(invoice)
        actions = self._actions(tenant_id)
        names = receivables._partner_names(tenant_id, list(late))
        rows = []
        for partner_id, invoices in late.items():
            since = min(i["oldest_due"] for i in invoices)
            days = max(i["days_overdue"] for i in invoices)
            reached = level_reached(levels, days)
            mine = [a for a in actions if a["partner_id"] == partner_id and a["created_at"].date() >= since]
            letters = [a for a in mine if a["kind"] == "letter" and a["level"]]
            sent_level = max((a["level"] for a in letters), default=0)
            promises = [a for a in mine if a["kind"] == "promise"]
            open_promise = next((p for p in promises if p["promise_status"] == "open" and p["promise_date"] >= today), None)
            broken = [p for p in promises if p["promise_status"] == "broken"
                      or (p["promise_status"] == "open" and p["promise_date"] < today)]
            next_level = None
            if reached and reached["level"] > sent_level:
                next_level = reached
            rows.append({
                "partner_id": partner_id, "partner_name": names.get(partner_id),
                "overdue": sum((i["overdue"] for i in invoices), Decimal("0")),
                "remaining": sum((i["remaining"] for i in invoices), Decimal("0")),
                "days_overdue": days, "since": since, "invoices": invoices,
                "level_reached": reached, "level_sent": sent_level or None, "next_level": next_level,
                "open_promise": open_promise, "broken_promise": broken[0] if broken else None,
                "last_action": mine[0] if mine else None,
                "to_chase": open_promise is None and (next_level is not None or bool(broken)),
                "blocked": bool(reached and reached["blocks_orders"]),
            })
        return sorted(rows, key=lambda r: (not r["to_chase"], -r["days_overdue"], -r["overdue"]))

    # ---- actions ---------------------------------------------------------------------------------------

    def record_action(self, *, tenant_id: str, actor_id: str, partner_id: str, kind: str, level: int | None = None,
                      note: str | None = None, invoice_ids: list[str] | None = None, promise_date: datetime.date | None = None,
                      promise_amount: Decimal | None = None, today: datetime.date | None = None) -> Result[dict[str, Any]]:
        today = today or datetime.date.today()
        if kind not in ACTION_KINDS:
            return Err("INVALID_DUNNING_ACTION", f"unknown action {kind}", f"action inconnue {kind}")
        if kind == "promise":
            if promise_date is None or promise_date < today:
                return Err("INVALID_PROMISE", "a promise to pay needs a date from today on", "une promesse de paiement a une date à partir d'aujourd'hui")
            if promise_amount is not None and Decimal(str(promise_amount)) <= 0:
                return Err("INVALID_PROMISE", "a promised amount is above 0", "un montant promis est supérieur à 0")
        elif promise_date is not None or promise_amount is not None:
            return Err("INVALID_DUNNING_ACTION", "only a promise carries a date and an amount", "seule une promesse a une date et un montant")
        if kind in ("call", "note") and not (note or "").strip():
            return Err("NOTE_REQUIRED", "say what was said or done", "indiquez ce qui a été dit ou fait")
        if level is not None and level not in {l["level"] for l in self.levels(tenant_id=tenant_id)}:
            return Err("INVALID_DUNNING_ACTION", f"unknown dunning level {level}", f"niveau de relance inconnu {level}")
        if not self._connection.execute("SELECT 1 FROM core.partners WHERE tenant_id = %s AND id = %s", (tenant_id, partner_id)).fetchone():
            return Err("NOT_FOUND", f"partner {partner_id} not found", f"partenaire {partner_id} introuvable")
        from modules.finance.api.receivables_service import ReceivablesService

        late = [i for i in ReceivablesService(self._connection)._open_invoices(tenant_id, partner_id, today) if i["overdue"]]
        chosen = invoice_ids if invoice_ids else [i["id"] for i in late]
        amount_due = sum((i["overdue"] for i in late if i["id"] in chosen), Decimal("0"))
        action_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO finance.dunning_actions (id, tenant_id, partner_id, kind, level, note, invoice_ids, amount_due, promise_date,
                                                 promise_amount, promise_status, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (action_id, tenant_id, partner_id, kind, level, (note or "").strip() or None, json.dumps(chosen), amount_due, promise_date,
             promise_amount, "open" if kind == "promise" else None, actor_id),
        )
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action=f"dunning.{kind}_recorded", entity_type="partner",
                     entity_id=partner_id, payload={"action_id": action_id, "level": level, "amount_due": str(amount_due),
                                                    "promise_date": promise_date.isoformat() if promise_date else None})
        row = self._connection.execute(f"SELECT {_ACTION_COLUMNS} FROM finance.dunning_actions WHERE id = %s", (action_id,)).fetchone()
        return Ok(_action_row(row))

    def set_promise_status(self, *, tenant_id: str, actor_id: str, action_id: str, status: str) -> Result[dict[str, Any]]:
        if status not in ("kept", "broken"):
            return Err("INVALID_PROMISE", "a promise is kept or broken", "une promesse est tenue ou non tenue")
        row = self._connection.execute(
            "SELECT kind, promise_status, partner_id FROM finance.dunning_actions WHERE tenant_id = %s AND id = %s FOR UPDATE",
            (tenant_id, action_id),
        ).fetchone()
        if row is None or row[0] != "promise":
            return Err("NOT_FOUND", f"promise {action_id} not found", f"promesse {action_id} introuvable")
        self._connection.execute("UPDATE finance.dunning_actions SET promise_status = %s WHERE id = %s", (status, action_id))
        record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="dunning.promise_status_changed",
                     entity_type="partner", entity_id=row[2], payload={"action_id": action_id, "from": row[1], "to": status})
        row = self._connection.execute(f"SELECT {_ACTION_COLUMNS} FROM finance.dunning_actions WHERE id = %s", (action_id,)).fetchone()
        return Ok(_action_row(row))

    # ---- the daily run ----------------------------------------------------------------------------------

    def run(self, *, tenant_id: str, today: datetime.date | None = None, actor_id: str = "system:dunning") -> dict[str, int]:
        """Settles promises whose date has passed (kept if nothing is late any more, broken otherwise) and tells
        the people who chase about broken promises and customers reaching a new level. Safe to run any number of
        times a day: each customer and level is announced once per run of lateness."""
        today = today or datetime.date.today()
        worklist = {row["partner_id"]: row for row in self.worklist(tenant_id=tenant_id, today=today)}
        recipients = users_with_permission(self._connection, tenant_id, MANAGE_PERMISSION)
        kept = broken = announced = 0
        for promise_id, partner_id, promise_date in self._connection.execute(
            "SELECT id, partner_id, promise_date FROM finance.dunning_actions "
            "WHERE tenant_id = %s AND kind = 'promise' AND promise_status = 'open' AND promise_date < %s",
            (tenant_id, today),
        ).fetchall():
            status = "broken" if partner_id in worklist else "kept"
            self._connection.execute("UPDATE finance.dunning_actions SET promise_status = %s WHERE id = %s", (status, promise_id))
            record_audit(self._connection, tenant_id=tenant_id, actor_id=actor_id, action="dunning.promise_status_changed",
                         entity_type="partner", entity_id=partner_id, payload={"action_id": promise_id, "from": "open", "to": status})
            if status == "kept":
                kept += 1
                continue
            broken += 1
            name = worklist[partner_id]["partner_name"] or partner_id
            notify(self._connection, tenant_id=tenant_id, user_ids=recipients, kind="finance.dunning.promise_broken",
                   title=f"{name} did not pay as promised on {promise_date.isoformat()}",
                   title_fr=f"{name} n'a pas payé comme promis le {promise_date.strftime('%d/%m/%Y')}",
                   link=f"/finance/receivables?partner={partner_id}")
        for partner_id, row in worklist.items():
            level = row["level_reached"]
            if level is None:
                continue
            inserted = self._connection.execute(
                "INSERT INTO finance.dunning_notices (tenant_id, partner_id, level, since) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING RETURNING level",
                (tenant_id, partner_id, level["level"], row["since"]),
            ).fetchone()
            if inserted is None or row["level_sent"] and row["level_sent"] >= level["level"]:
                continue
            announced += 1
            name = row["partner_name"] or partner_id
            notify(self._connection, tenant_id=tenant_id, user_ids=recipients, kind="finance.dunning.level_reached",
                   title=f"{name}: {level['name_en']} due ({row['days_overdue']} days late, {row['overdue']:.0f} F CFA)",
                   title_fr=f"{name} : {level['name_fr']} à envoyer ({row['days_overdue']} jours de retard, {row['overdue']:.0f} F CFA)",
                   link=f"/finance/receivables?partner={partner_id}")
        return {"promises_kept": kept, "promises_broken": broken, "levels_announced": announced}

    def tenants_to_run(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT DISTINCT tenant_id FROM finance.invoices WHERE status IN ('issued', 'partially_paid')").fetchall()
        return [row[0] for row in rows]

    # ---- letters ----------------------------------------------------------------------------------------

    def letter(self, *, tenant_id: str, partner_id: str, level: int | None = None, today: datetime.date | None = None) -> Result[dict[str, Any]]:
        """What a letter shows: the company, the customer, the level's text and the late invoices. The level
        defaults to the one the customer reached."""
        from modules.finance.api.receivables_service import ReceivablesService

        today = today or datetime.date.today()
        partner = self._connection.execute(
            "SELECT name, email, phone FROM core.partners WHERE tenant_id = %s AND id = %s", (tenant_id, partner_id)).fetchone()
        if partner is None:
            return Err("NOT_FOUND", f"partner {partner_id} not found", f"partenaire {partner_id} introuvable")
        receivables = ReceivablesService(self._connection)
        invoices = [i for i in receivables._open_invoices(tenant_id, partner_id, today) if i["overdue"]]
        if not invoices:
            return Err("NOTHING_OVERDUE", "this customer has nothing overdue", "ce client n'a rien en retard")
        levels = self.levels(tenant_id=tenant_id)
        chosen = (next((l for l in levels if l["level"] == level), None) if level is not None
                  else level_reached(levels, max(i["days_overdue"] for i in invoices))) or levels[0]
        return Ok({
            "date": today, "company": receivables.settings(tenant_id=tenant_id),
            "partner": {"id": partner_id, "name": partner[0], "email": partner[1], "phone": partner[2]},
            "level": chosen, "invoices": invoices,
            "overdue": sum((i["overdue"] for i in invoices), Decimal("0")),
            "remaining": sum((i["remaining"] for i in invoices), Decimal("0")),
        })
