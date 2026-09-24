"""The example receipt behind "Try an example".

Transcribed from the owner's Target receipt, 2026-09-22 10:15 PM (``spikes/receipts/target2.jpg``,
gitignored); totals verified in ``spikes/chain-tax-codes.md``. The expected split is pinned in
``tests/receipts/test_service.py``: Alex 426, Sam 1503, Jordan 1880 (sum 3809).
"""

from uuid import UUID

from app.domain.receipt import ParsedReceipt
from app.receipts.schemas import Participant, ReceiptState

ALEX = UUID("00000000-0000-4000-8000-000000000001")
SAM = UUID("00000000-0000-4000-8000-000000000002")
JORDAN = UUID("00000000-0000-4000-8000-000000000003")


def _item(line_id: str, name: str, cents: int, taxable: bool, code: str) -> dict[str, object]:
    return {
        "line_id": line_id,
        "kind": "item",
        "name": name,
        "total_cents": cents,
        "taxable": taxable,
        "tax_code": code,
    }


EXAMPLE_STATE = ReceiptState(
    content=ParsedReceipt.model_validate(
        {
            "merchant_name": "Target",
            "lines": [
                _item("ex-1", "Cheetos", 489, False, "NF"),
                _item("ex-2", "e.l.f.", 1112, True, "T"),
                _item("ex-3", "Kitsch", 999, True, "T"),
                _item("ex-4", "e.l.f.", 463, True, "T"),
                _item("ex-5", "Slime Mart", 500, True, "T"),
            ],
            "tax_lines": [{"label": "NY TAX 8%", "amount_cents": 246}],
            "subtotal_cents": 3563,
            "total_cents": 3809,
        }
    ),
    participants=[
        Participant(key=ALEX, display_name="Alex"),
        Participant(key=SAM, display_name="Sam"),
        Participant(key=JORDAN, display_name="Jordan"),
    ],
    assignments={
        "ex-1": [ALEX, SAM],
        "ex-2": [JORDAN],
        "ex-3": [SAM],
        "ex-4": [JORDAN],
        "ex-5": [ALEX, SAM, JORDAN],
    },
)
