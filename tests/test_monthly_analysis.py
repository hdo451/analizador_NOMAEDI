import pytest

from agents.content_analyzer import ContentAnalyzerAgent
from main_coordinator import BankStatementAnalyzer
from utils.monthly_analysis import (
    ACCOUNT_PROFILES,
    available_months,
    category_comparison,
    compare_months,
    comparison_coverage,
    default_month_pair,
    infer_account_profile,
    plain_language_findings,
    summarize_months,
)


def _txn(month, amount, *, debit=True, category="other", account="checking", **updates):
    txn = {
        "month": month,
        "date": f"{month}-10",
        "amount": amount,
        "is_debit": debit,
        "direction_known": True,
        "effective_is_spending": debit,
        "effective_is_income": not debit,
        "category": category,
        "account_label": account,
    }
    txn.update(updates)
    return txn


def test_exactly_six_account_profiles_and_filename_inference():
    assert len(ACCOUNT_PROFILES) == 6
    assert infer_account_profile("bank_savings_january.pdf") == "savings"
    assert infer_account_profile("visa-credit-february.pdf") == "credit_card_primary"
    assert infer_account_profile("checking.pdf") == "checking"


def test_month_summary_is_chronological_and_excludes_unresolved_direction():
    transactions = [
        _txn("2026-02", 130, category="groceries"),
        _txn("2026-01", 100, category="groceries"),
        _txn("2026-02", 500, debit=False),
        _txn(
            "2026-02",
            999,
            direction_known=False,
            effective_is_spending=False,
            effective_is_income=False,
        ),
        _txn("unknown", 200),
    ]

    assert available_months(transactions) == ["2026-01", "2026-02"]
    assert default_month_pair(available_months(transactions)) == (
        "2026-01",
        "2026-02",
    )
    rows = summarize_months(transactions)

    assert [row["month"] for row in rows] == ["2026-01", "2026-02"]
    assert rows[1]["total_spent"] == 130
    assert rows[1]["total_income"] == 500
    assert rows[1]["spending_difference"] == 30
    assert rows[1]["spending_pct_change"] == pytest.approx(0.30)


def test_month_comparison_reports_exact_differences_and_zero_baseline():
    transactions = [
        _txn("2026-01", 100),
        _txn("2026-01", 300, debit=False),
        _txn("2026-02", 140),
        _txn("2026-02", 350, debit=False),
    ]
    comparison = compare_months(transactions, "2026-01", "2026-02")

    assert comparison["spending_difference"] == 40
    assert comparison["income_difference"] == 50
    assert comparison["net_difference"] == 10
    assert comparison["spending_pct_change"] == pytest.approx(0.40)

    no_baseline = compare_months(
        [_txn("2026-02", 25)], "2026-01", "2026-02"
    )
    assert no_baseline["spending_pct_change"] is None


def test_category_comparison_has_at_most_six_rows_and_preserves_totals():
    transactions = []
    for index in range(8):
        transactions.extend(
            [
                _txn("2026-01", 10 + index, category=f"category_{index}"),
                _txn("2026-02", 20 + index, category=f"category_{index}"),
            ]
        )

    rows = category_comparison(
        transactions, "2026-01", "2026-02", max_rows=6
    )

    assert len(rows) == 6
    assert rows[-1]["category"] == "__remaining__"
    assert sum(row["base"] for row in rows) == sum(range(10, 18))
    assert sum(row["current"] for row in rows) == sum(range(20, 28))


def test_account_coverage_flags_an_incomplete_comparison():
    transactions = [
        _txn("2026-01", 10, account="checking"),
        _txn("2026-01", 20, account="savings"),
        _txn("2026-02", 15, account="checking"),
    ]
    coverage = comparison_coverage(transactions, "2026-01", "2026-02")

    assert coverage["comparable"] is False
    assert coverage["only_in_base"] == ["savings"]
    assert coverage["only_in_current"] == []


def test_plain_language_findings_come_from_fixed_rules():
    comparison = compare_months(
        [_txn("2026-01", 100), _txn("2026-02", 80)],
        "2026-01",
        "2026-02",
    )
    rows = category_comparison(
        [_txn("2026-01", 100), _txn("2026-02", 80)],
        "2026-01",
        "2026-02",
    )

    findings = plain_language_findings(comparison, rows)

    assert "menos" in findings[0]
    assert "Otros" not in findings[1]  # raw code is used only without a label map
    assert len(findings) == 3


def test_deterministic_content_fallback_never_calls_a_model():
    transactions = [
        {
            "transaction_id": "txn_1",
            "date": "2026-01-01",
            "description": "Unknown merchant",
            "amount": 10.0,
            "is_debit": True,
            "direction_known": True,
            "category": "uncategorized",
        }
    ]

    agent = ContentAnalyzerAgent(None, deterministic_only=True)
    result = agent.process(transactions)

    assert agent.llm_calls_made == 0
    assert result[0]["category"] == "other"
    assert result[0]["source"] == "deterministic_fallback"


def test_coordinator_can_initialize_without_an_api_key_in_deterministic_mode():
    analyzer = BankStatementAnalyzer(deterministic_only=True)

    assert analyzer.llm.call_count == 0
    assert analyzer.agent2.uses_llm is False
    assert analyzer.agent3.uses_llm is False
    assert analyzer.agent1.merchant_db.user_category_overrides == {}
    assert analyzer.agent1.merchant_db.save_user_category_rule(
        "Session-only merchant", "groceries"
    ) is False
