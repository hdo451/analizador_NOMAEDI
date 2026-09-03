import json

from agents.content_analyzer import ContentAnalyzerAgent
from agents.document_processor import DocumentProcessorAgent
from main_coordinator import BankStatementAnalyzer


def _parse_raw_statement(raw_text: str):
    agent = DocumentProcessorAgent()
    agent._statement_date_range_hint = agent._infer_statement_date_range(raw_text)
    agent._opening_balance_hint, agent._closing_balance_hint = (
        agent._infer_statement_balance_hints(raw_text)
    )
    agent._statement_profile, agent._statement_kind = (
        agent._infer_statement_profile(raw_text, 'uploaded_statement.pdf')
    )
    candidates = agent._find_transaction_lines(raw_text)
    transactions = agent._parse_transaction_lines(candidates)
    reconciliation = agent._reconcile_transaction_directions(transactions)
    return agent, candidates, transactions, reconciliation


def test_aggregate_balance_rows_are_excluded_before_parsing():
    raw_text = """
--- PAGE 1 TEXT ---
Previous Balance: $1,000.00
Transaction History
Date Description Amount Balance
01/02/2026 COFFEE SHOP -$10.00 $990.00
01/03/2026 DIRECT DEP EMPLOYER $500.00 $1,490.00
01/31/2026 ENDING BALANCE $1,490.00
01/31/2026 TOTAL ACTIVITY $510.00
Ending Balance: $1,490.00
--- END PAGE 1 TEXT ---
"""

    agent, candidates, transactions, reconciliation = _parse_raw_statement(raw_text)

    assert len(candidates) == 2
    assert len(transactions) == 2
    assert {row['row_type'] for row in agent._last_excluded_rows} >= {
        'opening_balance', 'closing_balance', 'aggregate'
    }
    deposit = next(txn for txn in transactions if 'DIRECT DEP' in txn['description'])
    assert deposit['is_debit'] is False
    assert deposit['direction_known'] is True
    assert deposit['direction_source'] == 'running_balance'
    assert reconciliation['reconciled'] is True


def test_account_word_inside_real_description_is_not_filtered():
    raw_text = """
--- PAGE 1 TEXT ---
Transaction History
01/02/2026 TRANSFER TO EXTERNAL ACCOUNT -$25.00 $975.00
--- END PAGE 1 TEXT ---
"""
    _, candidates, transactions, _ = _parse_raw_statement(raw_text)

    assert len(candidates) == 1
    assert len(transactions) == 1


def test_unknown_direction_is_retained_but_fails_closed_in_totals():
    raw_text = """
--- PAGE 1 TEXT ---
Transaction History
01/02/2026 UNLABELED MOVEMENT $25.00
--- END PAGE 1 TEXT ---
"""
    _, _, transactions, reconciliation = _parse_raw_statement(raw_text)
    transaction = transactions[0]
    assert transaction['direction_known'] is False
    assert reconciliation['unknown_direction_count'] == 1

    analyzer = BankStatementAnalyzer.__new__(BankStatementAnalyzer)
    metadata = {
        'document_id': 'doc_1',
        'file_name': 'statement.pdf',
        'document_type': 'bank_account',
        'person': 'default',
        'account_label': 'checking',
        'institution': 'unknown',
        'statement_profile': 'generic_bank_account',
        'date_range': {'start': '2026-01-02', 'end': '2026-01-02'},
    }
    normalized = analyzer.normalize_transactions(transactions, metadata)[0]
    assert normalized['effective_is_spending'] is False
    assert normalized['effective_is_income'] is False
    assert normalized['excluded_from_totals'] is True


def test_wells_fargo_fixture_reconciles_without_balance_rows():
    result = DocumentProcessorAgent().process(
        'bank_statements/wells_fargo_statement.pdf'
    )

    assert result['success'] is True
    assert len(result['transactions']) == 26
    assert all('BALANCE' not in txn['description'] for txn in result['transactions'])
    deposit = next(
        txn for txn in result['transactions']
        if 'DIRECT DEP ACME CORP' in txn['description']
    )
    assert deposit['is_debit'] is False
    assert deposit['amount'] == 3200.0
    assert result['reconciliation']['reconciled'] is True
    assert abs(result['reconciliation']['difference']) <= 0.02


class _InvalidCategoryLLM:
    def __init__(self):
        self.call_count = 0

    def make_call(
        self, prompt, system_prompt=None, expect_json=False, response_schema=None
    ):
        self.call_count += 1
        return json.dumps({
            'categorizations': [{
                'transaction_id': 'txn_0',
                'category': 'invented_category',
                'confidence': 0.99,
                'reasoning': 'invalid on purpose',
            }]
        })


def test_llm_cannot_invent_category_or_reorder_statement():
    transactions = [
        {
            'transaction_id': 'txn_1',
            'date': '2026-01-01',
            'description': 'Known grocery',
            'amount': 10.0,
            'is_debit': True,
            'direction_known': True,
            'category': 'groceries',
        },
        {
            'transaction_id': 'txn_2',
            'date': '2026-01-02',
            'description': 'Unknown merchant',
            'amount': 20.0,
            'is_debit': True,
            'direction_known': True,
            'category': 'uncategorized',
        },
    ]
    original_ids = [txn['transaction_id'] for txn in transactions]

    result = ContentAnalyzerAgent(_InvalidCategoryLLM()).process(transactions)

    assert [txn['transaction_id'] for txn in result] == original_ids
    assert result[1]['category'] == 'other'
    assert result[1]['source'] == 'fallback'


def test_debit_description_containing_deposit_is_not_changed_to_income():
    analyzer = BankStatementAnalyzer.__new__(BankStatementAnalyzer)
    transaction = {
        'description': 'Deposit correction fee',
        'is_debit': True,
        'direction_known': True,
        'document_type': 'bank_account',
        'category': 'fees',
        'effective_is_spending': True,
        'effective_is_income': False,
    }

    analyzer.classify_transaction(transaction)

    assert transaction['effective_is_spending'] is True
    assert transaction['effective_is_income'] is False
