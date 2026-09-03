import json
from types import SimpleNamespace

from agents.content_analyzer import ContentAnalyzerAgent
from utils.llm_interface import LLMInterface


class FakeCategorizationLLM:
    def __init__(self, categorizations):
        self.call_count = 0
        self.categorizations = categorizations
        self.prompt = ""
        self.system_prompt = ""
        self.schema = None

    def make_call(
        self, prompt, system_prompt=None, expect_json=False, response_schema=None
    ):
        self.call_count += 1
        self.prompt = prompt
        self.system_prompt = system_prompt
        self.schema = response_schema
        return json.dumps({"categorizations": self.categorizations})


def _transaction(**overrides):
    transaction = {
        "transaction_id": "stable-1",
        "date": "2026-07-10",
        "description": "SQ *LA ESQUINA 987654321",
        "amount": 24.75,
        "is_debit": True,
        "direction_known": True,
        "direction_source": "amount_column",
        "document_type": "bank_account",
        "institution": "Chase",
        "statement_profile": "chase_bank_account",
        "account_label": "checking_primary",
        "movement_type": "bank_movement",
        "category": "other",
        "confidence": 0.4,
        "source": "deterministic",
    }
    transaction.update(overrides)
    return transaction


def test_expert_reviews_low_confidence_rule_without_changing_financial_facts():
    llm = FakeCategorizationLLM([
        {
            "transaction_id": "txn_0",
            "category": "food_dining",
            "confidence": 0.91,
            "reasoning": "Descriptor compatible con restaurante.",
            "merchant_name": "La Esquina",
            "review_required": False,
        }
    ])
    original = _transaction()
    result = ContentAnalyzerAgent(llm).process([original])

    assert result[0]["category"] == "food_dining"
    assert result[0]["source"] == "llm"
    assert result[0]["transaction_id"] == "stable-1"
    assert result[0]["amount"] == 24.75
    assert result[0]["date"] == "2026-07-10"
    assert result[0]["is_debit"] is True
    assert "987654321" not in llm.prompt
    assert "[REF]" in llm.prompt


def test_direction_guard_rejects_income_category_for_a_debit():
    llm = FakeCategorizationLLM([
        {
            "transaction_id": "txn_0",
            "category": "income",
            "confidence": 0.99,
            "reasoning": "Incorrect on purpose",
            "merchant_name": "",
            "review_required": False,
        }
    ])

    result = ContentAnalyzerAgent(llm).process([_transaction()])

    assert result[0]["category"] == "other"
    assert result[0]["source"] == "fallback"
    assert result[0]["category_review_required"] is True


def test_agent_failure_preserves_a_compatible_rule_category():
    llm = FakeCategorizationLLM([
        {
            "transaction_id": "txn_0",
            "category": "income",
            "confidence": 0.99,
            "reasoning": "Incorrect on purpose",
            "merchant_name": "",
            "review_required": False,
        }
    ])
    transaction = _transaction(
        category="groceries",
        confidence=0.90,
        deterministic_category="groceries",
        deterministic_confidence=0.90,
    )

    result = ContentAnalyzerAgent(llm).process([transaction])

    assert result[0]["category"] == "groceries"
    assert result[0]["confidence"] == 0.90
    assert result[0]["source"] == "agent_fallback_rule"
    assert result[0]["category_review_required"] is True


def test_structural_rule_is_not_sent_to_the_agent():
    llm = FakeCategorizationLLM([])
    transaction = _transaction(
        category="groceries", confidence=0.99, source="deterministic_section"
    )

    result = ContentAnalyzerAgent(llm).process([transaction])

    assert llm.call_count == 0
    assert result[0]["category"] == "groceries"


def test_catalog_and_remembered_rules_are_not_sent_to_the_agent():
    llm = FakeCategorizationLLM([])
    transactions = [
        _transaction(
            transaction_id="catalog",
            category="groceries",
            confidence=0.97,
            source="deterministic_catalog",
        ),
        _transaction(
            transaction_id="remembered",
            category="bills_utilities",
            confidence=0.99,
            source="deterministic_user_rule",
        ),
        _transaction(
            transaction_id="third-party-transfer",
            category="shopping",
            confidence=0.80,
            source="deterministic_third_party_transfer",
            third_party_transfer_candidate=True,
            category_review_required=True,
        ),
    ]

    result = ContentAnalyzerAgent(llm).process(transactions)

    assert llm.call_count == 0
    assert [txn["category"] for txn in result] == [
        "groceries", "bills_utilities", "shopping"
    ]


def test_responses_adapter_uses_strict_schema_and_does_not_store_request():
    captured = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                status="completed",
                output_text='{"ok": true}',
                usage=SimpleNamespace(input_tokens=12, output_tokens=4),
            )

    interface = LLMInterface.__new__(LLMInterface)
    interface.client = SimpleNamespace(responses=FakeResponses())
    interface.model = "gpt-5.6"
    interface.call_count = 0
    interface.total_cost = 0.0
    interface.input_tokens = 0
    interface.output_tokens = 0

    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    output = interface.make_call(
        "categorize", "instructions", expect_json=True, response_schema=schema
    )

    assert output == '{"ok": true}'
    assert captured["model"] == "gpt-5.6"
    assert captured["store"] is False
    assert captured["text"]["format"]["strict"] is True
    assert captured["text"]["format"]["schema"] == schema
    assert interface.input_tokens == 12
    assert interface.output_tokens == 4
