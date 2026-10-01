from __future__ import annotations

import psycopg
from ulid import ULID

from core.audit import record_audit
from core.domain.result import Err, Ok, Result
from modules.maintenance.api.spare_parts_service import checkpoint_parts, save_checkpoint_parts, validate_parts
from modules.maintenance.domain.jobs import CHECK_ACTIONS

__all__ = ["MapService", "ALLOWED_IMAGE_MIME", "MAX_IMAGE_BYTES"]

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024

_VIEW_COLUMNS = "id, equipment_id, label, sort_order, image_mime, updated_at"
_CHECKPOINT_COLUMNS = (
    "id, view_id, x_pct, y_pct, label, action, instructions, measure_unit, requires_photo, sort_order, archived_at"
)


def _checkpoint_dict(row) -> dict:
    (checkpoint_id, view_id, x_pct, y_pct, label, action, instructions, measure_unit, requires_photo, sort_order, archived_at) = row
    return {
        "id": checkpoint_id,
        "view_id": view_id,
        "x_pct": float(x_pct),
        "y_pct": float(y_pct),
        "label": label,
        "action": action,
        "instructions": instructions,
        "measure_unit": measure_unit,
        "requires_photo": requires_photo,
        "sort_order": sort_order,
        "archived_at": archived_at.isoformat() if archived_at is not None else None,
    }


def _parts_payload(parts) -> list[dict]:
    """The audit trail's view of a parts list: which product, how many."""
    return [{"product_id": product_id, "quantity": str(quantity)} for product_id, quantity in parts]


class MapService:
    def __init__(self, connection: psycopg.Connection) -> None:
        self._connection = connection

    # ---- equipment views -------------------------------------------------

    def list_views(self, *, tenant_id: str, equipment_id: str, include_archived: bool = False) -> list[dict]:
        rows = self._connection.execute(
            f"SELECT {_VIEW_COLUMNS} FROM maintenance.equipment_views WHERE tenant_id = %s AND equipment_id = %s ORDER BY sort_order, created_at",
            (tenant_id, equipment_id),
        ).fetchall()
        return [self._view_dict(tenant_id, row, include_archived=include_archived) for row in rows]

    def create_view(
        self, *, tenant_id: str, actor_id: str, equipment_id: str, label: str, image: bytes, mime: str
    ) -> Result[dict]:
        invalid_image = self._validate_image(image, mime)
        if invalid_image is not None:
            return invalid_image
        if not self._equipment_exists(tenant_id, equipment_id):
            return Err("NOT_FOUND", f"equipment {equipment_id} not found", f"équipement {equipment_id} introuvable")

        view_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO maintenance.equipment_views (id, tenant_id, equipment_id, label, image, image_mime)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (view_id, tenant_id, equipment_id, label, psycopg.Binary(image), mime),
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="equipment_view.created",
            entity_type="equipment_view",
            entity_id=view_id,
            payload={"equipment_id": equipment_id, "label": label, "image_mime": mime},
        )
        return Ok(self.get_view(tenant_id=tenant_id, view_id=view_id))

    def update_view(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        view_id: str,
        label: str | None = None,
        sort_order: int | None = None,
        image: bytes | None = None,
        mime: str | None = None,
    ) -> Result[dict]:
        row = self._connection.execute(
            f"SELECT {_VIEW_COLUMNS} FROM maintenance.equipment_views WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (view_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"view {view_id} not found", f"vue {view_id} introuvable")

        if image is not None:
            invalid_image = self._validate_image(image, mime or "")
            if invalid_image is not None:
                return invalid_image
            self._connection.execute(
                "UPDATE maintenance.equipment_views SET image = %s, image_mime = %s, updated_at = NOW() WHERE id = %s",
                (psycopg.Binary(image), mime, view_id),
            )
        if label is not None:
            self._connection.execute(
                "UPDATE maintenance.equipment_views SET label = %s, updated_at = NOW() WHERE id = %s", (label, view_id)
            )
        if sort_order is not None:
            self._connection.execute(
                "UPDATE maintenance.equipment_views SET sort_order = %s, updated_at = NOW() WHERE id = %s",
                (sort_order, view_id),
            )

        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="equipment_view.updated",
            entity_type="equipment_view",
            entity_id=view_id,
            payload={"label": label, "sort_order": sort_order, "image_replaced": image is not None},
        )
        return Ok(self.get_view(tenant_id=tenant_id, view_id=view_id))

    def delete_view(self, *, tenant_id: str, actor_id: str, view_id: str) -> Result[None]:
        row = self._connection.execute(
            "SELECT id FROM maintenance.equipment_views WHERE id = %s AND tenant_id = %s FOR UPDATE", (view_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"view {view_id} not found", f"vue {view_id} introuvable")

        in_use = self._connection.execute(
            "SELECT 1 FROM maintenance.job_checks WHERE tenant_id = %s AND view_id = %s LIMIT 1", (tenant_id, view_id)
        ).fetchone()
        if in_use is not None:
            return Err(
                "VIEW_IN_USE",
                "this map is referenced by an existing job and cannot be deleted",
                "ce plan est référencé par une intervention existante et ne peut pas être supprimé",
            )

        self._connection.execute("DELETE FROM maintenance.checkpoints WHERE view_id = %s", (view_id,))
        self._connection.execute("DELETE FROM maintenance.equipment_views WHERE id = %s", (view_id,))
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="equipment_view.deleted",
            entity_type="equipment_view",
            entity_id=view_id,
            payload={},
        )
        return Ok(None)

    def get_view(self, *, tenant_id: str, view_id: str, include_archived: bool = True) -> dict | None:
        row = self._connection.execute(
            f"SELECT {_VIEW_COLUMNS} FROM maintenance.equipment_views WHERE id = %s AND tenant_id = %s", (view_id, tenant_id)
        ).fetchone()
        return None if row is None else self._view_dict(tenant_id, row, include_archived=include_archived)

    def get_image(self, *, tenant_id: str, view_id: str) -> tuple[bytes, str] | None:
        row = self._connection.execute(
            "SELECT image, image_mime FROM maintenance.equipment_views WHERE id = %s AND tenant_id = %s", (view_id, tenant_id)
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return bytes(row[0]), row[1]

    # ---- checkpoints -------------------------------------------------------

    def add_checkpoint(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        view_id: str,
        x_pct: float,
        y_pct: float,
        label: str,
        action: str,
        instructions: str | None = None,
        measure_unit: str | None = None,
        requires_photo: bool = False,
        parts: list[dict] | None = None,
    ) -> Result[dict]:
        """`parts` are the spare parts the point's work needs, `{product_id, quantity}`
        in each product's own unit (see `validate_parts`)."""
        view = self._connection.execute(
            "SELECT id FROM maintenance.equipment_views WHERE id = %s AND tenant_id = %s", (view_id, tenant_id)
        ).fetchone()
        if view is None:
            return Err("NOT_FOUND", f"view {view_id} not found", f"vue {view_id} introuvable")

        invalid = self._validate_checkpoint(x_pct, y_pct, action)
        if invalid is not None:
            return invalid
        checked_parts = validate_parts(self._connection, tenant_id, parts or [])
        if isinstance(checked_parts, Err):
            return checked_parts

        checkpoint_id = str(ULID())
        self._connection.execute(
            """
            INSERT INTO maintenance.checkpoints
                (id, tenant_id, view_id, x_pct, y_pct, label, action, instructions, measure_unit, requires_photo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (checkpoint_id, tenant_id, view_id, x_pct, y_pct, label, action, instructions, measure_unit, requires_photo),
        )
        save_checkpoint_parts(self._connection, tenant_id, checkpoint_id, checked_parts.value)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="checkpoint.created",
            entity_type="checkpoint",
            entity_id=checkpoint_id,
            payload={"view_id": view_id, "label": label, "action": action, "parts": _parts_payload(checked_parts.value)},
        )
        return Ok(self._get_checkpoint(tenant_id, checkpoint_id))

    def update_checkpoint(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        checkpoint_id: str,
        x_pct: float | None = None,
        y_pct: float | None = None,
        label: str | None = None,
        action: str | None = None,
        instructions: str | None = None,
        instructions_set: bool = False,
        measure_unit: str | None = None,
        measure_unit_set: bool = False,
        requires_photo: bool | None = None,
        sort_order: int | None = None,
        parts: list[dict] | None = None,
    ) -> Result[dict]:
        """Only the given fields change. `parts` replaces the point's whole list ([]
        clears it); None leaves it alone."""
        row = self._connection.execute(
            f"SELECT {_CHECKPOINT_COLUMNS} FROM maintenance.checkpoints WHERE id = %s AND tenant_id = %s FOR UPDATE",
            (checkpoint_id, tenant_id),
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"checkpoint {checkpoint_id} not found", f"point de contrôle {checkpoint_id} introuvable")

        current = _checkpoint_dict(row)
        updated_x = current["x_pct"] if x_pct is None else x_pct
        updated_y = current["y_pct"] if y_pct is None else y_pct
        updated_label = current["label"] if label is None else label
        updated_action = current["action"] if action is None else action
        updated_instructions = current["instructions"] if not instructions_set else instructions
        updated_measure_unit = current["measure_unit"] if not measure_unit_set else measure_unit
        updated_requires_photo = current["requires_photo"] if requires_photo is None else requires_photo
        updated_sort_order = current["sort_order"] if sort_order is None else sort_order

        invalid = self._validate_checkpoint(updated_x, updated_y, updated_action)
        if invalid is not None:
            return invalid
        checked_parts = validate_parts(self._connection, tenant_id, parts) if parts is not None else None
        if isinstance(checked_parts, Err):
            return checked_parts

        self._connection.execute(
            """
            UPDATE maintenance.checkpoints
            SET x_pct = %s, y_pct = %s, label = %s, action = %s, instructions = %s,
                measure_unit = %s, requires_photo = %s, sort_order = %s
            WHERE id = %s
            """,
            (
                updated_x,
                updated_y,
                updated_label,
                updated_action,
                updated_instructions,
                updated_measure_unit,
                updated_requires_photo,
                updated_sort_order,
                checkpoint_id,
            ),
        )
        payload: dict = {"label": updated_label, "action": updated_action}
        if checked_parts is not None:
            save_checkpoint_parts(self._connection, tenant_id, checkpoint_id, checked_parts.value)
            payload["parts"] = _parts_payload(checked_parts.value)
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="checkpoint.updated",
            entity_type="checkpoint",
            entity_id=checkpoint_id,
            payload=payload,
        )
        return Ok(self._get_checkpoint(tenant_id, checkpoint_id))

    def archive_checkpoint(self, *, tenant_id: str, actor_id: str, checkpoint_id: str) -> Result[dict]:
        row = self._connection.execute(
            "SELECT id FROM maintenance.checkpoints WHERE id = %s AND tenant_id = %s FOR UPDATE", (checkpoint_id, tenant_id)
        ).fetchone()
        if row is None:
            return Err("NOT_FOUND", f"checkpoint {checkpoint_id} not found", f"point de contrôle {checkpoint_id} introuvable")

        self._connection.execute(
            "UPDATE maintenance.checkpoints SET archived_at = NOW() WHERE id = %s", (checkpoint_id,)
        )
        record_audit(
            self._connection,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="checkpoint.archived",
            entity_type="checkpoint",
            entity_id=checkpoint_id,
            payload={},
        )
        return Ok(self._get_checkpoint(tenant_id, checkpoint_id))

    def active_checkpoints(self, *, tenant_id: str, equipment_id: str) -> list[dict]:
        rows = self._connection.execute(
            f"""
            SELECT {', '.join('c.' + col for col in _CHECKPOINT_COLUMNS.split(', '))}
            FROM maintenance.checkpoints c
            JOIN maintenance.equipment_views v ON v.id = c.view_id
            WHERE c.tenant_id = %s AND v.equipment_id = %s AND c.archived_at IS NULL
            ORDER BY v.sort_order, c.sort_order
            """,
            (tenant_id, equipment_id),
        ).fetchall()
        return self._with_parts(tenant_id, [_checkpoint_dict(row) for row in rows])

    def checkpoints_by_ids(self, *, tenant_id: str, ids: list[str]) -> Result[list[dict]]:
        """Used by B4 to snapshot a job's checks from the map. Err `UNKNOWN_CHECKPOINT`
        if any id is missing or archived; checking the ids all belong to the same
        machine is B4's job, not this one's."""
        distinct_ids = list(dict.fromkeys(ids))
        if not distinct_ids:
            return Ok([])
        rows = self._connection.execute(
            f"SELECT {_CHECKPOINT_COLUMNS} FROM maintenance.checkpoints WHERE tenant_id = %s AND id = ANY(%s) AND archived_at IS NULL",
            (tenant_id, distinct_ids),
        ).fetchall()
        found = {checkpoint["id"]: checkpoint for checkpoint in self._with_parts(tenant_id, [_checkpoint_dict(row) for row in rows])}
        missing = [cid for cid in distinct_ids if cid not in found]
        if missing:
            return Err(
                "UNKNOWN_CHECKPOINT",
                f"unknown or archived checkpoint id(s): {', '.join(missing)}",
                f"point(s) de contrôle inconnu(s) ou archivé(s) : {', '.join(missing)}",
            )
        return Ok([found[cid] for cid in distinct_ids])

    # ---- internals -----------------------------------------------------

    def _equipment_exists(self, tenant_id: str, equipment_id: str) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM maintenance.equipment WHERE id = %s AND tenant_id = %s", (equipment_id, tenant_id)
            ).fetchone()
            is not None
        )

    def _validate_image(self, image: bytes, mime: str) -> Err | None:
        if mime not in ALLOWED_IMAGE_MIME or not image or len(image) > MAX_IMAGE_BYTES:
            return Err(
                "INVALID_IMAGE",
                "image must be JPEG, PNG or WebP and at most 10 MB",
                "l'image doit être au format JPEG, PNG ou WebP et faire au plus 10 Mo",
            )
        return None

    def _validate_checkpoint(self, x_pct: float, y_pct: float, action: str) -> Err | None:
        if not (0 <= x_pct <= 100) or not (0 <= y_pct <= 100):
            return Err(
                "INVALID_POSITION", "x_pct and y_pct must be between 0 and 100", "x_pct et y_pct doivent être compris entre 0 et 100"
            )
        if action not in CHECK_ACTIONS:
            return Err("INVALID_ACTION", f"unknown action: {action}", f"action inconnue : {action}")
        return None

    def _get_checkpoint(self, tenant_id: str, checkpoint_id: str) -> dict:
        row = self._connection.execute(
            f"SELECT {_CHECKPOINT_COLUMNS} FROM maintenance.checkpoints WHERE id = %s AND tenant_id = %s", (checkpoint_id, tenant_id)
        ).fetchone()
        return self._with_parts(tenant_id, [_checkpoint_dict(row)])[0]

    def _view_dict(self, tenant_id: str, row: tuple, *, include_archived: bool) -> dict:
        view_id, equipment_id, label, sort_order, image_mime, updated_at = row
        clause = "" if include_archived else "AND archived_at IS NULL"
        checkpoint_rows = self._connection.execute(
            f"SELECT {_CHECKPOINT_COLUMNS} FROM maintenance.checkpoints WHERE view_id = %s {clause} ORDER BY sort_order",
            (view_id,),
        ).fetchall()
        return {
            "id": view_id,
            "equipment_id": equipment_id,
            "label": label,
            "sort_order": sort_order,
            "image_mime": image_mime,
            "updated_at": updated_at.isoformat(),
            "checkpoints": self._with_parts(tenant_id, [_checkpoint_dict(r) for r in checkpoint_rows]),
        }

    def _with_parts(self, tenant_id: str, checkpoints: list[dict]) -> list[dict]:
        """Sets each checkpoint's `parts` (the spare parts its work needs), in one query."""
        parts = checkpoint_parts(self._connection, tenant_id, [checkpoint["id"] for checkpoint in checkpoints])
        for checkpoint in checkpoints:
            checkpoint["parts"] = parts.get(checkpoint["id"], [])
        return checkpoints
