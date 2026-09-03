"""Deterministic monthly summaries for the simplified statement experience."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


MAX_ACCOUNTS = 6

ACCOUNT_PROFILES: Tuple[Dict[str, str], ...] = (
    {
        "code": "checking",
        "label": "Cuenta principal",
        "document_type": "bank_account",
    },
    {
        "code": "savings",
        "label": "Ahorros",
        "document_type": "bank_account",
    },
    {
        "code": "credit_card_primary",
        "label": "Tarjeta de crédito",
        "document_type": "credit_card",
    },
    {
        "code": "credit_card_secondary",
        "label": "Segunda tarjeta",
        "document_type": "credit_card",
    },
    {
        "code": "joint",
        "label": "Cuenta conjunta",
        "document_type": "bank_account",
    },
    {
        "code": "other_account",
        "label": "Otra cuenta",
        "document_type": "bank_account",
    },
)

ACCOUNT_PROFILE_BY_CODE = {item["code"]: item for item in ACCOUNT_PROFILES}


def infer_account_profile(file_name: str) -> str:
    """Infer one of six account slots from a filename using fixed rules."""
    normalized = str(file_name or "").casefold()
    if any(word in normalized for word in ("savings", "ahorro", "savin")):
        return "savings"
    if any(word in normalized for word in ("joint", "conjunta", "shared")):
        return "joint"
    if any(word in normalized for word in ("card 2", "card_2", "segunda", "second")):
        return "credit_card_secondary"
    if any(
        word in normalized
        for word in ("credit", "credito", "crédito", "visa", "mastercard", "card")
    ):
        return "credit_card_primary"
    return "checking"


def is_valid_month(value: object) -> bool:
    """Accept only normalized calendar months in YYYY-MM form."""
    text = str(value or "")
    if len(text) != 7 or text[4] != "-":
        return False
    try:
        year = int(text[:4])
        month = int(text[5:])
    except ValueError:
        return False
    return year >= 1900 and 1 <= month <= 12


def available_months(transactions: Iterable[Dict]) -> List[str]:
    return sorted(
        {
            str(txn.get("month"))
            for txn in transactions
            if is_valid_month(txn.get("month"))
        }
    )


def default_month_pair(months: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return previous/latest months, or the only month twice for a snapshot."""
    normalized = sorted({month for month in months if is_valid_month(month)})
    if not normalized:
        return None, None
    if len(normalized) == 1:
        return normalized[0], normalized[0]
    return normalized[-2], normalized[-1]


def _counts_as_spending(txn: Dict) -> bool:
    return (
        bool(txn.get("direction_known", True))
        and bool(txn.get("is_debit"))
        and bool(txn.get("effective_is_spending", True))
    )


def _counts_as_income(txn: Dict) -> bool:
    return (
        bool(txn.get("direction_known", True))
        and not bool(txn.get("is_debit"))
        and bool(txn.get("effective_is_income", True))
    )


def summarize_months(transactions: Iterable[Dict]) -> List[Dict]:
    """Build chronological totals and exact month-over-month differences."""
    buckets: Dict[str, Dict] = {}
    for txn in transactions:
        month = str(txn.get("month") or "")
        if not is_valid_month(month):
            continue
        bucket = buckets.setdefault(
            month,
            {
                "month": month,
                "total_spent": 0.0,
                "total_income": 0.0,
                "net_change": 0.0,
                "transaction_count": 0,
                "accounts": set(),
            },
        )
        bucket["transaction_count"] += 1
        account = str(txn.get("account_label") or "").strip()
        if account:
            bucket["accounts"].add(account)
        amount = float(txn.get("amount") or 0.0)
        if _counts_as_spending(txn):
            bucket["total_spent"] += amount
        elif _counts_as_income(txn):
            bucket["total_income"] += amount

    rows: List[Dict] = []
    previous_spent: Optional[float] = None
    for month in sorted(buckets):
        source = buckets[month]
        spent = round(source["total_spent"], 2)
        income = round(source["total_income"], 2)
        difference = None if previous_spent is None else round(spent - previous_spent, 2)
        pct_change = (
            None
            if previous_spent in (None, 0)
            else (spent - previous_spent) / previous_spent
        )
        rows.append(
            {
                "month": month,
                "total_spent": spent,
                "total_income": income,
                "net_change": round(income - spent, 2),
                "spending_difference": difference,
                "spending_pct_change": pct_change,
                "transaction_count": source["transaction_count"],
                "account_count": len(source["accounts"]),
                "accounts": sorted(source["accounts"]),
            }
        )
        previous_spent = spent
    return rows


def _month_totals(transactions: Iterable[Dict], month: str) -> Dict[str, float]:
    totals = {"spent": 0.0, "income": 0.0}
    for txn in transactions:
        if txn.get("month") != month:
            continue
        amount = float(txn.get("amount") or 0.0)
        if _counts_as_spending(txn):
            totals["spent"] += amount
        elif _counts_as_income(txn):
            totals["income"] += amount
    totals["net"] = totals["income"] - totals["spent"]
    return {key: round(value, 2) for key, value in totals.items()}


def compare_months(
    transactions: Iterable[Dict],
    base_month: str,
    current_month: str,
) -> Dict:
    """Compare two calendar months without estimates, inference, or model calls."""
    txns = list(transactions)
    base = _month_totals(txns, base_month)
    current = _month_totals(txns, current_month)
    spending_difference = round(current["spent"] - base["spent"], 2)
    income_difference = round(current["income"] - base["income"], 2)
    pct_change = (
        None if base["spent"] == 0 else spending_difference / base["spent"]
    )
    return {
        "base_month": base_month,
        "current_month": current_month,
        "base": base,
        "current": current,
        "spending_difference": spending_difference,
        "income_difference": income_difference,
        "net_difference": round(current["net"] - base["net"], 2),
        "spending_pct_change": pct_change,
    }


def category_comparison(
    transactions: Iterable[Dict],
    base_month: str,
    current_month: str,
    category_labels: Optional[Dict[str, str]] = None,
    max_rows: int = 6,
) -> List[Dict]:
    """Compare spending categories, folding the tail into one auditable row."""
    if max_rows < 2:
        raise ValueError("max_rows must be at least 2")
    labels = category_labels or {}
    totals: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"base": 0.0, "current": 0.0}
    )
    for txn in transactions:
        if not _counts_as_spending(txn):
            continue
        month = txn.get("month")
        if month not in {base_month, current_month}:
            continue
        category = str(txn.get("category") or "other")
        side = "base" if month == base_month else "current"
        totals[category][side] += float(txn.get("amount") or 0.0)

    ordered = sorted(
        totals,
        key=lambda category: (
            -(totals[category]["base"] + totals[category]["current"]),
            category,
        ),
    )
    visible = ordered
    folded: List[str] = []
    if len(ordered) > max_rows:
        visible = ordered[: max_rows - 1]
        folded = ordered[max_rows - 1 :]

    rows = []
    for category in visible:
        base = round(totals[category]["base"], 2)
        current = round(totals[category]["current"], 2)
        rows.append(
            _category_row(
                category,
                labels.get(category, category),
                base,
                current,
                [category],
            )
        )

    if folded:
        base = round(sum(totals[category]["base"] for category in folded), 2)
        current = round(sum(totals[category]["current"] for category in folded), 2)
        rows.append(
            _category_row(
                "__remaining__",
                "Resto de categorías",
                base,
                current,
                folded,
            )
        )
    return rows


def _category_row(
    code: str,
    label: str,
    base: float,
    current: float,
    included_categories: List[str],
) -> Dict:
    difference = round(current - base, 2)
    return {
        "category": code,
        "category_label": label,
        "base": base,
        "current": current,
        "difference": difference,
        "pct_change": None if base == 0 else difference / base,
        "included_categories": included_categories,
    }


def comparison_coverage(
    transactions: Iterable[Dict],
    base_month: str,
    current_month: str,
) -> Dict:
    """Expose account-coverage differences that can distort a comparison."""
    accounts_by_month = {base_month: set(), current_month: set()}
    for txn in transactions:
        month = txn.get("month")
        if month not in accounts_by_month:
            continue
        account = str(txn.get("account_label") or "").strip()
        if account:
            accounts_by_month[month].add(account)

    base_accounts = accounts_by_month[base_month]
    current_accounts = accounts_by_month[current_month]
    return {
        "comparable": base_accounts == current_accounts,
        "base_accounts": sorted(base_accounts),
        "current_accounts": sorted(current_accounts),
        "only_in_base": sorted(base_accounts - current_accounts),
        "only_in_current": sorted(current_accounts - base_accounts),
        "common_accounts": sorted(base_accounts & current_accounts),
    }


def plain_language_findings(comparison: Dict, category_rows: Sequence[Dict]) -> List[str]:
    """Generate short Spanish explanations from fixed numerical rules."""
    difference = float(comparison.get("spending_difference") or 0.0)
    pct_change = comparison.get("spending_pct_change")
    base_month = comparison.get("base_month")
    current_month = comparison.get("current_month")

    if difference == 0:
        change_text = f"Gastaste lo mismo en {current_month} que en {base_month}."
    elif difference > 0:
        percentage = f" ({abs(pct_change):.1%})" if pct_change is not None else ""
        change_text = (
            f"Gastaste ${abs(difference):,.2f} más en {current_month}{percentage}."
        )
    else:
        percentage = f" ({abs(pct_change):.1%})" if pct_change is not None else ""
        change_text = (
            f"Gastaste ${abs(difference):,.2f} menos en {current_month}{percentage}."
        )

    findings = [change_text]
    if category_rows:
        main_change = max(
            category_rows,
            key=lambda row: (abs(float(row.get("difference") or 0.0)), row["category"]),
        )
        category_difference = float(main_change.get("difference") or 0.0)
        direction = "subió" if category_difference > 0 else "bajó" if category_difference < 0 else "no cambió"
        findings.append(
            f"El cambio más grande estuvo en {main_change['category_label']}: "
            f"{direction} ${abs(category_difference):,.2f}."
        )

    current_net = float(comparison.get("current", {}).get("net") or 0.0)
    if current_net >= 0:
        findings.append(
            f"En {current_month}, los ingresos superaron los gastos por ${current_net:,.2f}."
        )
    else:
        findings.append(
            f"En {current_month}, los gastos superaron los ingresos por ${abs(current_net):,.2f}."
        )
    return findings

