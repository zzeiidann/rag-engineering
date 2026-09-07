import json
from pathlib import Path

from app.auth.models import Principal
from app.models import Document

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"
IDENTITIES = {
    "guest": Principal(user_id="guest", role="guest"),
    "client_a": Principal(user_id="user_a", role="client", client_id="client_a"),
    "client_b": Principal(user_id="user_b", role="client", client_id="client_b"),
    "actuarial": Principal(user_id="actuary", role="internal", department="actuarial"),
    "sales": Principal(user_id="sales", role="internal", department="sales"),
    "sales_permitted": Principal(
        user_id="sales_special",
        role="internal",
        department="sales",
        permissions=["resource:read:actuarial_pricing"],
    ),
}
# Relevance judgments include only resources the scenario identity is entitled to read.
SCENARIOS = [
    ("guest", "What is the pricing methodology?", {"public_faq", "public_brochure"}),
    ("client_a", "What is my coverage limit?", {"client_a_policy", "client_a_coverage"}),
    ("client_a", "Platinum international transplant coverage overseas organ transplants", set()),
    ("actuarial", "How is risk pricing calculated?", {"actuarial_pricing"}),
    ("sales", "How is risk pricing calculated?", {"public_faq", "public_brochure"}),
    ("sales_permitted", "How is risk pricing calculated?", {"actuarial_pricing"}),
]


def documents() -> list[Document]:
    return [
        Document(
            id=row["id"],
            title=row["title"],
            metadata=row["metadata"],
            text=(SAMPLE / row["file"]).read_text(),
        )
        for row in json.loads((SAMPLE / "manifest.json").read_text())
    ]
