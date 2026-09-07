import pytest
from pydantic import ValidationError

from app.auth.models import Principal, ResourceMetadata
from app.auth.policies import can_read
from scripts.demo import IDENTITIES, documents


@pytest.mark.parametrize(
    "identity,expected",
    [
        ("guest", {"public_brochure", "public_faq"}),
        ("client_a", {"public_brochure", "public_faq", "client_a_policy", "client_a_coverage"}),
        ("actuarial", {"public_brochure", "public_faq", "actuarial_pricing"}),
        ("sales", {"public_brochure", "public_faq", "sales_playbook"}),
        (
            "sales_permitted",
            {"public_brochure", "public_faq", "sales_playbook", "actuarial_pricing"},
        ),
    ],
)
def test_access_matrix(identity, expected):
    assert {
        d.id for d in documents() if can_read(IDENTITIES[identity], d.id, d.metadata)
    } == expected


def test_internal_client_requires_explicit_grant():
    doc = next(d for d in documents() if d.id == "client_a_policy")
    employee = Principal(user_id="ops", role="internal", department="operations")
    assert not can_read(employee, doc.id, doc.metadata)
    employee = employee.model_copy(update={"permissions": ["client:read:client_a"]})
    assert can_read(employee, doc.id, doc.metadata)
    other = next(d for d in documents() if d.id == "client_b_policy")
    assert not can_read(employee, other.id, other.metadata)


def test_fail_closed_metadata_and_identity():
    with pytest.raises(ValidationError):
        ResourceMetadata(visibility="client")
    with pytest.raises(ValidationError):
        Principal(user_id="x", role="client")
    with pytest.raises(ValidationError):
        Principal(user_id="x", role="guest", permissions=["internal:read:all"])
    assert not can_read(IDENTITIES["sales"], "private", ResourceMetadata(visibility="internal"))


def test_explicit_role_restriction_wins():
    meta = ResourceMetadata(
        visibility="internal", allowed_roles=["client"], allowed_departments=["actuarial"]
    )
    assert not can_read(IDENTITIES["actuarial"], "x", meta)
