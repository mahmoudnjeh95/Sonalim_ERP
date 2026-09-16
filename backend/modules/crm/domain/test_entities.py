from core.domain.result import Err, Ok
from modules.crm.domain.entities import Lead, transition


def test_new_lead_can_be_qualified():
    lead = Lead(id="1", contact_name="Jordan", email="jordan@example.com", status="new")
    result = transition(lead, "qualified")
    assert isinstance(result, Ok)
    assert result.value.status == "qualified"


def test_new_lead_cannot_be_converted_directly():
    lead = Lead(id="1", contact_name="Jordan", email="jordan@example.com", status="new")
    result = transition(lead, "converted")
    assert isinstance(result, Err)
    assert result.code == "INVALID_TRANSITION"


def test_qualified_lead_can_be_converted():
    lead = Lead(id="1", contact_name="Jordan", email="jordan@example.com", status="qualified")
    result = transition(lead, "converted")
    assert isinstance(result, Ok)
    assert result.value.status == "converted"
