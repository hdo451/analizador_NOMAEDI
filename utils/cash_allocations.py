"""Session-only, deterministic allocation of cash withdrawals."""

from __future__ import annotations

import copy
from typing import Dict, Iterable, List, Optional


CASH_WITHDRAWAL_MARKERS = (
    "atm withdrawal",
    "cash withdrawal",
    "cash advance",
    "retiro cajero",
    "retiro en cajero",
    "retiro de efectivo",
    "giro cajero",
    "cajero automatico",
    "cajero automático",
)


def is_cash_withdrawal(transaction: Dict) -> bool:
    """Return True only for an outgoing cash movement with explicit evidence."""
    if transaction.get("cash_allocation_parent_id"):
        return False
    if transaction.get("cash_allocation_kind"):
        return False
    if not transaction.get("direction_known", True):
        return False
    if not transaction.get("is_debit"):
        return False
    if transaction.get("category") == "fees":
        return False
    description = str(transaction.get("description") or "").casefold()
    category = str(transaction.get("category") or "")
    return category == "atm_cash" or any(
        marker in description for marker in CASH_WITHDRAWAL_MARKERS
    )


def cash_withdrawals(transactions: Iterable[Dict]) -> List[Dict]:
    return [txn for txn in transactions if is_cash_withdrawal(txn)]


def cash_allocation_state(transactions: Iterable[Dict], parent_id: str) -> Dict:
    txns = list(transactions)
    parent = next(
        (txn for txn in txns if txn.get("transaction_id") == parent_id), None
    )
    if parent is None:
        raise ValueError("Cash withdrawal was not found")
    allocations = [
        txn
        for txn in txns
        if txn.get("cash_allocation_parent_id") == parent_id
        and txn.get("cash_allocation_kind") == "user"
    ]
    allocated = round(sum(float(txn.get("amount") or 0.0) for txn in allocations), 2)
    total = round(float(parent.get("amount") or 0.0), 2)
    return {
        "parent": parent,
        "allocations": allocations,
        "total": total,
        "allocated": allocated,
        "remaining": round(max(total - allocated, 0.0), 2),
    }


def add_cash_allocation(
    transactions: Iterable[Dict],
    parent_id: str,
    description: str,
    amount: float,
    category: str,
) -> List[Dict]:
    """Add one spending line while keeping the withdrawal total unchanged."""
    txns = copy.deepcopy(list(transactions))
    state = cash_allocation_state(txns, parent_id)
    parent = state["parent"]
    clean_description = " ".join(str(description or "").split()).strip()
    rounded_amount = round(float(amount or 0.0), 2)
    if not is_cash_withdrawal(parent):
        raise ValueError("The selected movement is not an eligible cash withdrawal")
    if not clean_description:
        raise ValueError("Describe what the cash was used for")
    if rounded_amount <= 0:
        raise ValueError("The allocation amount must be greater than zero")
    if rounded_amount > state["remaining"] + 0.001:
        raise ValueError("The allocation exceeds the unassigned cash amount")
    if not str(category or "").strip():
        raise ValueError("Choose a category")

    existing = list(state["allocations"])
    sequence = max(
        [int(txn.get("cash_allocation_sequence") or 0) for txn in existing] or [0]
    ) + 1
    child = _build_child(
        parent,
        description=clean_description,
        amount=rounded_amount,
        category=category,
        kind="user",
        sequence=sequence,
    )
    return _rebuild_parent_group(txns, parent_id, existing + [child])


def remove_cash_allocation(
    transactions: Iterable[Dict], child_id: str
) -> List[Dict]:
    """Remove one user-entered line and restore the exact unassigned remainder."""
    txns = copy.deepcopy(list(transactions))
    child = next(
        (
            txn
            for txn in txns
            if txn.get("transaction_id") == child_id
            and txn.get("cash_allocation_kind") == "user"
        ),
        None,
    )
    if child is None:
        raise ValueError("Cash allocation line was not found")
    parent_id = str(child.get("cash_allocation_parent_id") or "")
    remaining_allocations = [
        txn
        for txn in txns
        if txn.get("cash_allocation_parent_id") == parent_id
        and txn.get("cash_allocation_kind") == "user"
        and txn.get("transaction_id") != child_id
    ]
    return _rebuild_parent_group(txns, parent_id, remaining_allocations)


def _build_child(
    parent: Dict,
    *,
    description: str,
    amount: float,
    category: str,
    kind: str,
    sequence: Optional[int] = None,
) -> Dict:
    parent_id = str(parent.get("transaction_id") or "cash_withdrawal")
    suffix = f"line_{sequence}" if kind == "user" else "remaining"
    child = {
        key: parent.get(key)
        for key in (
            "date",
            "month",
            "person",
            "source_document_id",
            "source_file_name",
            "document_type",
            "account_label",
            "institution",
            "currency",
            "statement_profile",
        )
        if key in parent
    }
    child.update(
        {
            "transaction_id": f"{parent_id}::cash::{suffix}",
            "local_txn_id": f"cash::{suffix}",
            "description": description,
            "amount": round(float(amount), 2),
            "is_debit": True,
            "direction_known": True,
            "direction_source": "cash_allocation",
            "direction_confidence": 1.0,
            "effective_is_spending": True,
            "effective_is_income": False,
            "excluded_from_totals": False,
            "category": category,
            "detected_category": category,
            "category_source": "user_cash_allocation" if kind == "user" else "deterministic_cash_remainder",
            "confidence": 1.0 if kind == "user" else 0.0,
            "source": "user_cash_allocation" if kind == "user" else "deterministic_cash_remainder",
            "reasoning": "Cash use supplied by the user" if kind == "user" else "Unassigned portion of cash withdrawal",
            "movement_type": "cash_allocation",
            "cash_allocation_parent_id": parent_id,
            "cash_allocation_kind": kind,
            "cash_allocation_sequence": sequence,
        }
    )
    return child


def _rebuild_parent_group(
    transactions: List[Dict], parent_id: str, user_allocations: List[Dict]
) -> List[Dict]:
    parent = next(
        (txn for txn in transactions if txn.get("transaction_id") == parent_id), None
    )
    if parent is None:
        raise ValueError("Cash withdrawal was not found")

    clean = [
        txn
        for txn in transactions
        if txn.get("cash_allocation_parent_id") != parent_id
    ]
    parent = next(txn for txn in clean if txn.get("transaction_id") == parent_id)
    if not user_allocations:
        parent["effective_is_spending"] = bool(
            parent.pop("cash_original_effective_is_spending", True)
        )
        parent.pop("cash_allocation_active", None)
        return clean

    if "cash_original_effective_is_spending" not in parent:
        parent["cash_original_effective_is_spending"] = bool(
            parent.get("effective_is_spending", True)
        )
    parent["effective_is_spending"] = False
    parent["cash_allocation_active"] = True

    total = round(float(parent.get("amount") or 0.0), 2)
    allocated = round(
        sum(float(txn.get("amount") or 0.0) for txn in user_allocations), 2
    )
    if allocated > total + 0.001:
        raise ValueError("Cash allocation lines exceed the withdrawal total")
    remainder = round(total - allocated, 2)
    children = sorted(
        user_allocations,
        key=lambda txn: int(txn.get("cash_allocation_sequence") or 0),
    )
    if remainder > 0:
        children.append(
            _build_child(
                parent,
                description="Efectivo pendiente de asignar",
                amount=remainder,
                category="other",
                kind="remainder",
            )
        )

    parent_index = next(
        index
        for index, txn in enumerate(clean)
        if txn.get("transaction_id") == parent_id
    )
    return clean[: parent_index + 1] + children + clean[parent_index + 1 :]

