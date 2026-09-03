import copy

from agents.analysis_generator import AnalysisGeneratorAgent
from main_coordinator import BankStatementAnalyzer
from streamlit_app import _annotate_meta_category_types


def _transactions():
    return [
        {
            "date": "2026-07-01",
            "description": "Neighborhood Pharmacy",
            "amount": 100.0,
            "is_debit": True,
            "effective_is_spending": True,
            "effective_is_income": False,
            "category": "healthcare",
        },
        {
            "date": "2026-07-02",
            "description": "Local Market",
            "amount": 50.0,
            "is_debit": True,
            "effective_is_spending": True,
            "effective_is_income": False,
            "category": "groceries",
        },
        {
            "date": "2026-07-03",
            "description": "Salary",
            "amount": 1000.0,
            "is_debit": False,
            "effective_is_spending": False,
            "effective_is_income": True,
            "category": "income",
        },
    ]


def test_custom_category_replaces_visible_category_without_double_counting():
    transactions = _transactions()
    transactions[0].update(
        {
            "detected_category": "healthcare",
            "category": "custom_aux_1",
            "category_source": "user_custom",
        }
    )

    result = AnalysisGeneratorAgent().process(
        transactions,
        category_labels={"custom_aux_1": "Hermana enferma"},
    )

    assert result["financial_summary"]["total_spent"] == 150.0
    breakdown = {item["category"]: item for item in result["category_breakdown"]}
    assert "healthcare" not in breakdown
    assert breakdown["custom_aux_1"]["total"] == 100.0
    assert breakdown["custom_aux_1"]["category_label"] == "Hermana enferma"
    assert breakdown["custom_aux_1"]["category_type"] == "user_custom"
    assert breakdown["groceries"]["total"] == 50.0


def test_renaming_custom_slot_keeps_assignments_and_totals():
    transactions = _transactions()
    transactions[0]["category"] = "custom_aux_1"

    agent = AnalysisGeneratorAgent()
    first = agent.process(
        copy.deepcopy(transactions),
        category_labels={"custom_aux_1": "Auxiliar 1"},
    )
    renamed = agent.process(
        copy.deepcopy(transactions),
        category_labels={"custom_aux_1": "Hermana enferma"},
    )

    first_custom = next(
        item for item in first["category_breakdown"]
        if item["category"] == "custom_aux_1"
    )
    renamed_custom = next(
        item for item in renamed["category_breakdown"]
        if item["category"] == "custom_aux_1"
    )

    assert first_custom["total"] == renamed_custom["total"] == 100.0
    assert first_custom["category_label"] == "Auxiliar 1"
    assert renamed_custom["category_label"] == "Hermana enferma"


def test_meta_response_recovers_authoritative_custom_category_metadata():
    payload = {
        "category_breakdown": [
            {
                "category": "custom_aux_1",
                "category_label": "Hermana enferma",
                "category_type": "user_custom",
                "total": 100.0,
            }
        ]
    }
    meta_result = {
        "category_analysis": [
            {
                "category": "Hermana enferma",
                "spent": 100.0,
            }
        ]
    }

    annotated = _annotate_meta_category_types(meta_result, payload)
    category = annotated["category_analysis"][0]

    assert category["category"] == "custom_aux_1"
    assert category["category_label"] == "Hermana enferma"
    assert category["category_type"] == "user_custom"


def test_coordinator_preserves_automatic_category_before_manual_review(monkeypatch):
    analyzer = BankStatementAnalyzer("test-key-not-used")
    monkeypatch.setattr(
        analyzer.agent1,
        "process",
        lambda _path: {
            "success": True,
            "transactions": [
                {
                    "date": "2026-07-01",
                    "description": "Neighborhood Pharmacy",
                    "amount": 25.0,
                    "is_debit": True,
                    "balance": 975.0,
                    "category": "healthcare",
                    "transaction_id": "txn_1",
                    "confidence": 0.95,
                    "source": "deterministic",
                }
            ],
            "parsing_stats": {},
            "raw_transaction_lines": [],
        },
    )
    monkeypatch.setattr(
        analyzer.agent2,
        "process",
        lambda transactions: transactions,
    )
    analyzer.agent3 = AnalysisGeneratorAgent()

    result = analyzer.analyze_statement("bank_statements/sample_statement.pdf")

    assert result["success"] is True
    transaction = result["transactions"][0]
    assert transaction["category"] == "healthcare"
    assert transaction["detected_category"] == "healthcare"
    assert transaction["category_source"] == "automatic"
