import copy

from agents.analysis_generator import AnalysisGeneratorAgent
from main_coordinator import BankStatementAnalyzer
from streamlit_app import (
    _category_code_to_label,
    _category_label_to_code,
    _category_method_label,
    _category_review_label,
    _apply_transaction_review_row,
    _selectable_category_labels,
    _transaction_category_label_to_code,
    _transactions_to_editor_df,
)
from utils.internal_transfers import (
    INTERNAL_TRANSFER_CATEGORY,
    TRANSFER_OVERRIDE_AUTO,
    TRANSFER_OVERRIDE_NORMAL,
    TRANSFER_OVERRIDE_TRANSFER,
    apply_transfer_override,
)


def _transaction(**updates):
    transaction = {
        "date": "2026-07-10",
        "description": "Local purchase",
        "amount": 100.0,
        "is_debit": True,
        "effective_is_spending": True,
        "effective_is_income": False,
        "category": "other",
        "document_type": "bank_account",
        "movement_type": "bank_movement",
        "source_document_id": "checking",
        "confidence": 0.95,
        "source": "deterministic",
    }
    transaction.update(updates)
    return transaction


def _detect(transactions):
    analyzer = BankStatementAnalyzer.__new__(BankStatementAnalyzer)
    return analyzer.detect_internal_transfers(transactions)


def test_explicit_spanish_internal_transfer_is_detected_and_excluded():
    transactions = [
        _transaction(description="Transferencia entre mis cuentas")
    ]

    _detect(transactions)

    transaction = transactions[0]
    assert transaction["detected_internal_transfer"] is True
    assert transaction["internal_transfer_override"] == TRANSFER_OVERRIDE_AUTO
    assert transaction["possible_internal_transfer"] is True
    assert transaction["effective_is_spending"] is False
    assert transaction["internal_transfer_detection_reason"]
    assert transaction["category"] == INTERNAL_TRANSFER_CATEGORY


def test_online_banking_transfer_description_is_detected():
    transaction = _transaction(
        description="Online Banking transfer from SAV 0445 Confirmation 183746"
    )

    _detect([transaction])

    assert transaction["detected_internal_transfer"] is True
    assert transaction["category"] == INTERNAL_TRANSFER_CATEGORY
    assert transaction["effective_is_spending"] is False


def test_manual_normal_override_corrects_false_positive_and_auto_restores_it():
    transaction = _transaction(description="Internal transfer")
    _detect([transaction])

    assert apply_transfer_override(transaction, TRANSFER_OVERRIDE_NORMAL) is True
    assert transaction["detected_internal_transfer"] is True
    assert transaction["possible_internal_transfer"] is False
    assert transaction["effective_is_spending"] is True
    assert transaction["category"] == "other"

    _detect([transaction])
    assert transaction["internal_transfer_override"] == TRANSFER_OVERRIDE_NORMAL
    assert transaction["detected_internal_transfer"] is True
    assert transaction["possible_internal_transfer"] is False
    assert transaction["effective_is_spending"] is True
    assert transaction["category"] == "other"

    assert apply_transfer_override(transaction, TRANSFER_OVERRIDE_AUTO) is True
    assert transaction["possible_internal_transfer"] is True
    assert transaction["effective_is_spending"] is False
    assert transaction["category"] == INTERNAL_TRANSFER_CATEGORY


def test_manual_transfer_override_excludes_ordinary_debit_and_credit():
    debit = _transaction()
    credit = _transaction(
        is_debit=False,
        effective_is_spending=False,
        effective_is_income=True,
        description="Incoming movement",
    )

    apply_transfer_override(debit, TRANSFER_OVERRIDE_TRANSFER)
    apply_transfer_override(credit, TRANSFER_OVERRIDE_TRANSFER)

    assert debit["effective_is_spending"] is False
    assert debit["effective_is_income"] is False
    assert credit["effective_is_spending"] is False
    assert credit["effective_is_income"] is False
    assert debit["category"] == INTERNAL_TRANSFER_CATEGORY
    assert credit["category"] == INTERNAL_TRANSFER_CATEGORY

    summary = AnalysisGeneratorAgent().process([debit, credit])["financial_summary"]
    assert summary["total_spent"] == 0
    assert summary["total_income"] == 0


def test_same_amount_opposite_movements_across_accounts_are_paired():
    debit = _transaction(
        description="Transfer to savings",
        source_document_id="checking",
    )
    credit = _transaction(
        date="2026-07-11",
        description="Deposit",
        is_debit=False,
        effective_is_spending=False,
        effective_is_income=True,
        source_document_id="savings",
    )

    transactions = [debit, credit]
    _detect(transactions)

    assert all(txn["detected_internal_transfer"] for txn in transactions)
    assert all(not txn["effective_is_spending"] for txn in transactions)
    assert all(not txn["effective_is_income"] for txn in transactions)
    assert all(txn["category"] == INTERNAL_TRANSFER_CATEGORY for txn in transactions)
    assert transactions[0]["transfer_pair_id"] == transactions[1]["transfer_pair_id"]


def test_opposite_movements_from_two_statements_of_same_account_are_not_paired():
    debit = _transaction(
        description="ACH withdrawal 7744",
        source_document_id="checking_january",
        account_label="checking",
    )
    credit = _transaction(
        date="2026-07-11",
        description="ACH deposit 7744",
        is_debit=False,
        effective_is_spending=False,
        effective_is_income=True,
        source_document_id="checking_february",
        account_label="checking",
    )

    transactions = [debit, credit]
    _detect(transactions)

    assert all(not txn["detected_internal_transfer"] for txn in transactions)
    assert all("transfer_pair_id" not in txn for txn in transactions)


def test_matching_ach_movements_can_pair_without_transfer_word():
    debit = _transaction(
        description="ACH withdrawal checking 7744",
        source_document_id="checking",
        person="owner",
    )
    credit = _transaction(
        date="2026-07-11",
        description="ACH deposit savings 7744",
        is_debit=False,
        effective_is_spending=False,
        effective_is_income=True,
        source_document_id="savings",
        person="owner",
    )

    transactions = [debit, credit]
    _detect(transactions)

    assert all(txn["detected_internal_transfer"] for txn in transactions)
    assert transactions[0]["transfer_pair_id"] == transactions[1]["transfer_pair_id"]


def test_same_amount_movements_for_different_people_are_not_paired():
    debit = _transaction(
        description="Transfer to savings",
        source_document_id="checking",
        person="person_a",
    )
    credit = _transaction(
        description="Deposit",
        is_debit=False,
        effective_is_spending=False,
        effective_is_income=True,
        source_document_id="savings",
        person="person_b",
    )

    transactions = [debit, credit]
    _detect(transactions)

    # The explicit debit remains detectable from its own description, but it
    # must not be linked to a different person's credit.
    assert "transfer_pair_id" not in debit
    assert credit["detected_internal_transfer"] is False


def test_international_transfer_pair_is_not_treated_as_internal():
    debit = _transaction(
        description="International SWIFT transfer",
        source_document_id="checking",
    )
    credit = _transaction(
        description="International SWIFT transfer received",
        is_debit=False,
        effective_is_spending=False,
        effective_is_income=True,
        source_document_id="foreign_account",
    )

    transactions = copy.deepcopy([debit, credit])
    _detect(transactions)

    assert all(not txn["detected_internal_transfer"] for txn in transactions)
    assert all(txn["category"] == "other" for txn in transactions)


def test_editor_uses_category_as_the_only_visible_transfer_control():
    transaction = _transaction(description="Internal transfer")
    _detect([transaction])

    automatic_row = _transactions_to_editor_df([transaction]).iloc[0]
    assert "¿Transferencia automática?" not in automatic_row.index
    assert "Transfer Treatment" not in automatic_row.index
    assert "Category" not in automatic_row.index
    assert automatic_row["Explicación de transferencia"]
    assert automatic_row["Categoría"] == "Transferencias entre mis cuentas"
    assert _category_label_to_code("Transfers Between My Accounts") == (
        INTERNAL_TRANSFER_CATEGORY
    )
    assert _transaction_category_label_to_code(
        "Transferencias entre mis cuentas"
    ) == INTERNAL_TRANSFER_CATEGORY

    apply_transfer_override(transaction, TRANSFER_OVERRIDE_NORMAL)
    corrected_row = _transactions_to_editor_df([transaction]).iloc[0]
    assert corrected_row["Categoría"] == "Otros"
    assert bool(corrected_row["Cuenta como gasto"]) is True


def test_editor_headers_and_standard_categories_are_in_spanish():
    row = _transactions_to_editor_df([_transaction(category="groceries")]).iloc[0]

    assert list(row.index) == [
        "_txn_index",
        "Seleccionar",
        "Fecha",
        "Mes",
        "Persona",
        "Documento",
        "Tipo de documento",
        "Descripción",
        "Categoría",
        "Monto",
        "Tipo",
        "Cuenta como gasto",
        "Explicación de transferencia",
        "Confianza",
        "Origen",
    ]
    assert row["Categoría"] == "Supermercado"
    assert row["Tipo"] == "EGRESO"
    assert "Comidas y restaurantes" in _selectable_category_labels()
    assert "Transferencias entre mis cuentas" in _selectable_category_labels()


def test_chart_and_filter_category_labels_are_in_spanish():
    assert _category_code_to_label("food_dining") == "Comidas y restaurantes"
    assert _category_code_to_label("groceries") == "Supermercado"
    assert _category_code_to_label("bills_utilities") == "Cuentas y servicios"
    assert _category_code_to_label(INTERNAL_TRANSFER_CATEGORY) == (
        "Transferencias entre mis cuentas"
    )
    assert _category_label_to_code("Comidas y restaurantes") == "food_dining"


def test_internal_transfer_category_is_detected_even_without_keywords():
    transaction = _transaction(
        description="Movement 48392",
        category=INTERNAL_TRANSFER_CATEGORY,
    )

    _detect([transaction])

    assert transaction["detected_internal_transfer"] is True
    assert transaction["category"] == INTERNAL_TRANSFER_CATEGORY
    assert transaction["effective_is_spending"] is False


def test_category_editor_marks_and_unmarks_internal_transfer():
    transaction = _transaction()
    _detect([transaction])

    marked = _apply_transaction_review_row(
        transaction,
        {
            "Categoría": "Transferencias entre mis cuentas",
        },
    )

    assert marked["row_changed"] is True
    assert marked["rule_category"] is None
    assert transaction["category"] == INTERNAL_TRANSFER_CATEGORY
    assert transaction["internal_transfer_override"] == TRANSFER_OVERRIDE_TRANSFER
    assert transaction["effective_is_spending"] is False
    assert transaction["effective_is_income"] is False

    unmarked = _apply_transaction_review_row(
        transaction,
        {
            "Categoría": "Supermercado",
        },
    )

    assert unmarked["row_changed"] is True
    assert unmarked["rule_category"] == "groceries"
    assert transaction["category"] == "groceries"
    assert transaction["internal_transfer_override"] == TRANSFER_OVERRIDE_NORMAL
    assert transaction["effective_is_spending"] is True


def test_editor_can_correct_transaction_direction_deterministically():
    transaction = _transaction(description="Ambiguous account movement")

    outcome = _apply_transaction_review_row(
        transaction,
        {
            "Categoría": "Otros",
            "Tipo": "INGRESO",
        },
    )

    assert outcome["direction_changed"] is True
    assert transaction["is_debit"] is False
    assert transaction["direction_known"] is True
    assert transaction["direction_source"] == "user_review"
    assert transaction["effective_is_spending"] is False
    assert transaction["effective_is_income"] is True


def test_correcting_third_party_transfer_clears_yellow_review_marker():
    transaction = _transaction(
        description="ZELLE PAYMENT TO JUAN PEREZ",
        category="shopping",
        source="deterministic_third_party_transfer",
        third_party_transfer_candidate=True,
        category_review_required=True,
    )

    outcome = _apply_transaction_review_row(
        transaction,
        {
            "Categoría": "Cuentas y servicios",
            "Tipo": "EGRESO",
        },
    )

    assert outcome["category_changed"] is True
    assert outcome["rule_category"] == "bills_utilities"
    assert transaction["category"] == "bills_utilities"
    assert transaction["third_party_transfer_reviewed"] is True
    assert transaction["category_review_required"] is False


def test_detected_own_transfer_hides_stale_third_party_review_marker():
    transaction = _transaction(
        description="ZELLE PAYMENT TO ANA",
        source_document_id="checking",
        category="shopping",
        source="deterministic_third_party_transfer",
        third_party_transfer_candidate=True,
        category_review_required=True,
    )
    matching_credit = _transaction(
        date="2026-07-11",
        description="ZELLE PAYMENT FROM ANA",
        is_debit=False,
        effective_is_spending=False,
        effective_is_income=True,
        source_document_id="savings",
        category="income",
    )

    _detect([transaction, matching_credit])

    assert transaction["category"] == INTERNAL_TRANSFER_CATEGORY
    assert _category_method_label(transaction) == "Transferencia entre tus cuentas"
    assert _category_review_label(transaction) == ""
