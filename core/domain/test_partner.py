from core.domain.result import Err, Ok
from core.domain.partner import Partner, transition_partner, validate_partner_name


def _partner(status: str = "active") -> Partner:
    return Partner(
        id="1",
        tenant_id="demo",
        name="Acme Corp",
        kind="customer",
        industry=None,
        website=None,
        phone=None,
        email=None,
        status=status,
    )


def test_active_partner_can_be_archived():
    result = transition_partner(_partner(), "archived")
    assert isinstance(result, Ok)
    assert result.value.status == "archived"


def test_archived_partner_cannot_be_reactivated():
    result = transition_partner(_partner("archived"), "active")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_blank_name_is_invalid():
    result = validate_partner_name("   ")
    assert isinstance(result, Err)
    assert result.code == "INVALID_NAME"
