"""The photo a person sets on their own profile.

Deliberately gated by require_session only, not a manage_* permission: your own picture is
not privileged the way core.manage_permissions is. The routes never take a user id either,
so there is no path from here to anyone else's photo.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from core.audit import record_audit
from core.db import get_connection
from core.tenancy import TenantContext, require_session

router = APIRouter(prefix="/core", tags=["core.user_avatars"])

# The browser crops and re-encodes to a small square before uploading, so a real avatar is
# tens of kilobytes. The cap is generous enough for a phone photo that skipped that step and
# small enough that the row stays cheap to read on every page load.
MAX_AVATAR_BYTES = 2 * 1024 * 1024

# What the bytes themselves must start with. The declared content type is the client's word;
# these are the file's own, so a renamed PDF does not become an avatar.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"RIFF", "image/webp"),
)

_UNSUPPORTED = HTTPException(
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    {
        "code": "UNSUPPORTED_IMAGE_TYPE",
        "message": "the photo must be a PNG, JPEG or WebP image",
        "message_fr": "la photo doit être une image PNG, JPEG ou WebP",
    },
)


def _detected_type(content: bytes) -> str | None:
    for signature, media_type in _SIGNATURES:
        if content.startswith(signature):
            # RIFF also heads WAV and AVI; only a WebP carries the tag at byte 8.
            if media_type == "image/webp" and content[8:12] != b"WEBP":
                continue
            return media_type
    return None


@router.get("/users/me/avatar")
def get_my_avatar(tenant: TenantContext = Depends(require_session)) -> Response:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT image, content_type FROM core.user_avatars WHERE user_id = %s",
            (tenant.user_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "NOT_FOUND", "message": "no photo set", "message_fr": "aucune photo définie"},
        )
    # private: the photo belongs to one signed-in person, so no shared cache may keep it.
    return Response(content=bytes(row[0]), media_type=row[1], headers={"Cache-Control": "private, max-age=60"})


class AvatarUpload(BaseModel):
    """The cropped square the browser produced, base64 as the scan module's uploads are:
    JSON all the way through, so no multipart dependency is needed to accept a photo."""

    data_base64: str


@router.put("/users/me/avatar")
def set_my_avatar(
    body: AvatarUpload,
    tenant: TenantContext = Depends(require_session),
) -> dict:
    try:
        content = base64.b64decode(body.data_base64 or "", validate=True)
    except (ValueError, TypeError):
        raise _UNSUPPORTED from None
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            {
                "code": "AVATAR_TOO_LARGE",
                "message": f"the photo must be under {MAX_AVATAR_BYTES // (1024 * 1024)} MB",
                "message_fr": f"la photo doit faire moins de {MAX_AVATAR_BYTES // (1024 * 1024)} Mo",
            },
        )
    content_type = _detected_type(content)
    if content_type is None:
        raise _UNSUPPORTED

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO core.user_avatars (user_id, tenant_id, image, content_type)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET image = EXCLUDED.image, content_type = EXCLUDED.content_type, updated_at = NOW()
            """,
            (tenant.user_id, tenant.tenant_id, content, content_type),
        )
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="user.avatar_set",
            entity_type="user",
            entity_id=tenant.user_id,
            payload={"content_type": content_type, "bytes": len(content)},
        )
        connection.commit()
    return {"content_type": content_type, "bytes": len(content)}


@router.delete("/users/me/avatar", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_my_avatar(tenant: TenantContext = Depends(require_session)) -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM core.user_avatars WHERE user_id = %s", (tenant.user_id,))
        record_audit(
            connection,
            tenant_id=tenant.tenant_id,
            actor_id=tenant.user_id,
            action="user.avatar_removed",
            entity_type="user",
            entity_id=tenant.user_id,
            payload={},
        )
        connection.commit()
