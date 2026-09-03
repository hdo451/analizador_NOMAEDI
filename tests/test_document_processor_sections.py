from datetime import datetime

from agents.document_processor import DocumentProcessorAgent


def _parse_and_categorize(agent, raw_text):
    agent._statement_date_range_hint = agent._infer_statement_date_range(raw_text)
    candidates = agent._find_transaction_lines(raw_text)
    parsed = agent._parse_transaction_lines(candidates)
    return candidates, agent._apply_basic_categorization(parsed)


def test_section_heading_controls_direction_and_short_date_year():
    raw_text = """
--- PAGE 1 TEXT ---
Your previous balance as of04/29/2026
Your new balance as of 05/28/2026
Transaction detail
Otherwithdrawals,debitsandservicecharges
05/04 CTLP COFFEE SHOP 1.50
05/04 CTLP COFFEE SHOP 1.50
Totalotherwithdrawals,debitsandservicecharges = $3.00
Deposits,creditsandinterest
05/01 ZELLE PAYMENT FROM ANA 500.00
05/01 PAYROLL MIAMI PARKING LLC 1,347.94
05/18 DEBIT CARD RETURN TARGET 84.24
Totaldeposits,creditsandinterest = $1,932.18
Your new balance as of 05/28/2026 = $477.65 On 05/07/2026 the interest rate changed from 2.21% to 1.50%
05/19 ZELLE PAYMENT TO ANA 10.00
--- END PAGE 1 TEXT ---
"""
    agent = DocumentProcessorAgent()

    candidates, transactions = _parse_and_categorize(agent, raw_text)

    assert agent._statement_date_range_hint == (
        datetime(2026, 4, 29),
        datetime(2026, 5, 28),
    )
    assert len(candidates) == 6
    assert len(transactions) == 6

    repeated = [
        txn for txn in transactions if 'CTLP COFFEE SHOP' in txn['description']
    ]
    assert len(repeated) == 2
    assert all(txn['is_debit'] for txn in repeated)
    assert all(txn['direction_source'] == 'section_header' for txn in repeated)

    section_credits = [
        txn
        for txn in transactions
        if txn.get('statement_section') == 'deposits_credits_interest'
    ]
    assert len(section_credits) == 3
    assert all(txn['date'].startswith('2026-05-') for txn in section_credits)
    assert all(not txn['is_debit'] for txn in section_credits)
    assert all(txn['category'] == 'income' for txn in section_credits)
    assert all(txn['confidence'] == 0.99 for txn in section_credits)
    assert all(txn['source'] == 'deterministic_section' for txn in section_credits)

    payment_after_total = next(
        txn for txn in transactions if 'PAYMENT TO ANA' in txn['description']
    )
    assert payment_after_total['statement_section'] is None
    assert payment_after_total['direction_source'] == 'line_heuristic'
    assert payment_after_total['is_debit'] is True
    assert payment_after_total['category'] == 'shopping'
    assert payment_after_total['source'] == 'deterministic_third_party_transfer'
    assert payment_after_total['third_party_transfer_candidate'] is True
    assert payment_after_total['category_review_required'] is True


def test_page_text_is_preferred_without_collapsing_legitimate_duplicates():
    raw_text = """
--- PAGE 1 TABLE 1 ---
ROW_0: Transaction detail
ROW_1: Deposits, credits and interest
ROW_2: 05/01\tZELLE PAYMENT FROM ANA\t500.00
--- END TABLE 1 ---
--- PAGE 1 TEXT ---
Your previous balance as of 04/29/2026
Your new balance as of 05/28/2026
Transaction detail
Deposits, credits and interest
05/01 ZELLE PAYMENT FROM ANA 500.00
05/01 ZELLE PAYMENT FROM ANA 500.00
Total deposits, credits and interest = $1,000.00
--- END PAGE 1 TEXT ---
"""
    agent = DocumentProcessorAgent()

    candidates, transactions = _parse_and_categorize(agent, raw_text)

    assert len(candidates) == 2
    assert all(candidate['source'] == 'page_text' for candidate in candidates)
    assert len(transactions) == 2
    assert all(not txn['is_debit'] for txn in transactions)
    assert sum(txn['amount'] for txn in transactions) == 1000.00


def test_spanish_credit_section_is_recognized_deterministically():
    raw_text = """
Detalle de transacciones
Depósitos, abonos e intereses
18/05/2026 DEVOLUCION TARJETA 84,24
Total depósitos, abonos e intereses = $84,24
"""
    agent = DocumentProcessorAgent()

    candidates, transactions = _parse_and_categorize(agent, raw_text)

    assert len(candidates) == 1
    assert transactions[0]['statement_section'] == 'deposits_credits_interest'
    assert transactions[0]['is_debit'] is False
    assert transactions[0]['category'] == 'income'
