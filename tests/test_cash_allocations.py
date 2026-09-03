import pytest

from utils.cash_allocations import (
    add_cash_allocation,
    cash_allocation_state,
    is_cash_withdrawal,
    remove_cash_allocation,
)
from utils.monthly_analysis import summarize_months


def _withdrawal(**updates):
    transaction = {
        "transaction_id": "doc_1::atm_1",
        "local_txn_id": "atm_1",
        "date": "2026-08-10",
        "month": "2026-08",
        "description": "ATM WITHDRAWAL 1234",
        "amount": 100.0,
        "is_debit": True,
        "direction_known": True,
        "effective_is_spending": True,
        "effective_is_income": False,
        "category": "atm_cash",
        "source": "deterministic",
        "account_label": "checking",
        "source_document_id": "doc_1",
        "source_file_name": "august.pdf",
    }
    transaction.update(updates)
    return transaction


def test_cash_detection_requires_an_outgoing_non_fee_movement():
    assert is_cash_withdrawal(_withdrawal()) is True
    assert is_cash_withdrawal(_withdrawal(is_debit=False)) is False
    assert is_cash_withdrawal(
        _withdrawal(description="ATM FEE", category="fees")
    ) is False


def test_cash_allocation_adds_lines_without_changing_monthly_total():
    original = [_withdrawal()]
    updated = add_cash_allocation(
        original,
        "doc_1::atm_1",
        "Feria del barrio",
        35.0,
        "groceries",
    )

    assert original[0]["effective_is_spending"] is True
    assert updated[0]["effective_is_spending"] is False
    state = cash_allocation_state(updated, "doc_1::atm_1")
    assert state["allocated"] == 35.0
    assert state["remaining"] == 65.0
    assert state["allocations"][0]["description"] == "Feria del barrio"
    assert state["allocations"][0]["category"] == "groceries"
    assert summarize_months(updated)[0]["total_spent"] == 100.0


def test_multiple_cash_lines_can_explain_the_entire_withdrawal():
    transactions = add_cash_allocation(
        [_withdrawal()], "doc_1::atm_1", "Mercado", 60.0, "groceries"
    )
    transactions = add_cash_allocation(
        transactions, "doc_1::atm_1", "Transporte", 40.0, "transportation"
    )
    state = cash_allocation_state(transactions, "doc_1::atm_1")

    assert state["allocated"] == 100.0
    assert state["remaining"] == 0.0
    assert len(state["allocations"]) == 2
    assert not any(
        txn.get("cash_allocation_kind") == "remainder" for txn in transactions
    )
    assert summarize_months(transactions)[0]["total_spent"] == 100.0


def test_allocation_cannot_exceed_the_original_withdrawal():
    with pytest.raises(ValueError, match="exceeds"):
        add_cash_allocation(
            [_withdrawal()], "doc_1::atm_1", "Too much", 100.01, "other"
        )


def test_removing_last_line_restores_original_withdrawal():
    transactions = add_cash_allocation(
        [_withdrawal()], "doc_1::atm_1", "Farmacia", 25.0, "healthcare"
    )
    child_id = cash_allocation_state(
        transactions, "doc_1::atm_1"
    )["allocations"][0]["transaction_id"]
    restored = remove_cash_allocation(transactions, child_id)

    assert len(restored) == 1
    assert restored[0]["effective_is_spending"] is True
    assert "cash_allocation_active" not in restored[0]
    assert summarize_months(restored)[0]["total_spent"] == 100.0

