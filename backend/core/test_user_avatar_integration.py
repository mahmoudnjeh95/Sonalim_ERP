"""`/core/users/me/avatar`: the photo a person sets on themself.

Gated by require_session alone -- your own photo is not privileged -- and scoped to the
caller: the route never takes a user id, so there is no other user's avatar to ask for.
"""
from __future__ import annotations

import base64

from types import SimpleNamespace

import pytest
from ulid import ULID

from core.tenancy import TenantContext, require_session

TENANT = "avatar-router-test"

# A one-pixel PNG: the smallest thing Pillow-free validation still recognises by signature.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478"
    "9c6360000002000154a24f5c0000000049454e44ae426082"
)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60 + b"\xff\xd9"


class _Connection:
    """The fixture's connection, with the transaction left to the fixture."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


@pytest.fixture
def avatar_api(db, monkeypatch):
    pytest.importorskip("httpx", reason="the FastAPI test client needs httpx (requirements-dev.txt)")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core import user_avatars as module

    user_id = str(ULID())
    db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (user_id, TENANT, f"{user_id}@test.local"),
    )
    wrapped = _Connection(db)
    monkeypatch.setattr(module, "get_connection", lambda: wrapped)

    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[require_session] = lambda: TenantContext(tenant_id=TENANT, user_id=user_id, session_token="t")
    return SimpleNamespace(client=TestClient(app), db=db, user_id=user_id, tenant_id=TENANT)


def _put(avatar_api, content: bytes):
    return avatar_api.client.put(
        "/core/users/me/avatar",
        json={"data_base64": base64.b64encode(content).decode()},
    )


def test_no_photo_yet_is_404_not_an_error(avatar_api):
    assert avatar_api.client.get("/core/users/me/avatar").status_code == 404


def test_a_photo_comes_back_byte_for_byte(avatar_api):
    assert _put(avatar_api, PNG).status_code == 200
    shown = avatar_api.client.get("/core/users/me/avatar")
    assert shown.status_code == 200
    assert shown.content == PNG
    assert shown.headers["content-type"] == "image/png"


def test_uploading_again_replaces_the_previous_photo(avatar_api):
    _put(avatar_api, PNG)
    _put(avatar_api, JPEG)
    shown = avatar_api.client.get("/core/users/me/avatar")
    assert shown.content == JPEG and shown.headers["content-type"] == "image/jpeg"
    count = avatar_api.db.execute(
        "SELECT count(*) FROM core.user_avatars WHERE user_id = %s", (avatar_api.user_id,)
    ).fetchone()[0]
    assert count == 1


def test_removing_the_photo_leaves_nothing_behind(avatar_api):
    _put(avatar_api, PNG)
    assert avatar_api.client.delete("/core/users/me/avatar").status_code == 204
    assert avatar_api.client.get("/core/users/me/avatar").status_code == 404


def test_removing_a_photo_that_is_not_there_is_not_an_error(avatar_api):
    assert avatar_api.client.delete("/core/users/me/avatar").status_code == 204


def test_a_file_that_is_not_an_image_is_refused(avatar_api):
    refused = _put(avatar_api, b"%PDF-1.4 not an image")
    assert refused.status_code == 415
    assert refused.json()["detail"]["code"] == "UNSUPPORTED_IMAGE_TYPE"


def test_a_body_that_is_not_valid_base64_is_refused(avatar_api):
    refused = avatar_api.client.put("/core/users/me/avatar", json={"data_base64": "not base64!!"})
    assert refused.status_code == 415
    assert refused.json()["detail"]["code"] == "UNSUPPORTED_IMAGE_TYPE"


def test_a_photo_over_the_size_cap_is_refused(avatar_api):
    from core.user_avatars import MAX_AVATAR_BYTES

    refused = _put(avatar_api, PNG + b"\x00" * MAX_AVATAR_BYTES)
    assert refused.status_code == 413
    assert refused.json()["detail"]["code"] == "AVATAR_TOO_LARGE"


def test_the_photo_is_stored_against_the_callers_tenant(avatar_api):
    _put(avatar_api, PNG)
    stored = avatar_api.db.execute(
        "SELECT tenant_id FROM core.user_avatars WHERE user_id = %s", (avatar_api.user_id,)
    ).fetchone()
    assert stored[0] == TENANT


def test_another_users_photo_is_not_reachable_through_this_route(avatar_api):
    """The route is 'me': another user's row exists but no path leads to it."""
    other = str(ULID())
    avatar_api.db.execute(
        "INSERT INTO core.users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, 'x')",
        (other, TENANT, f"{other}@test.local"),
    )
    avatar_api.db.execute(
        "INSERT INTO core.user_avatars (user_id, tenant_id, image, content_type) VALUES (%s, %s, %s, 'image/png')",
        (other, TENANT, JPEG),
    )
    assert avatar_api.client.get("/core/users/me/avatar").status_code == 404
