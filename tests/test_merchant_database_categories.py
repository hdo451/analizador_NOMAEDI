import json

from utils.merchant_database import MerchantDatabase


def test_international_transfer_uses_transaction_direction():
    database = MerchantDatabase()

    incoming = database.categorize_transaction(
        "Incoming SWIFT international transfer", is_debit=False
    )
    outgoing = database.categorize_transaction(
        "Outgoing SWIFT international transfer", is_debit=True
    )

    assert incoming == ("international_transfer_in", 0.95)
    assert outgoing == ("international_transfer_out", 0.95)


def test_international_transfer_requires_known_direction():
    database = MerchantDatabase()

    category, _ = database.categorize_transaction("International wire transfer")

    assert category == "uncategorized"


def test_other_income_requires_credit_direction():
    database = MerchantDatabase()

    credit = database.categorize_transaction("Freelance income July", is_debit=False)
    debit = database.categorize_transaction("Freelance income course", is_debit=True)

    assert credit == ("other_income", 0.90)
    assert debit[0] != "other_income"


def test_existing_keyword_category_is_preserved():
    database = MerchantDatabase()

    assert database.categorize_transaction(
        "STARBUCKS STORE 123", is_debit=True
    )[0] == "food_dining"


def test_versioned_catalog_categorizes_common_groceries_and_services():
    database = MerchantDatabase(load_user_rules=False)

    grocery = database.categorize_transaction_with_details(
        "POS WHOLEFDS MKT 10456 BETHESDA", is_debit=True
    )
    service = database.categorize_transaction_with_details(
        "AUTOPAY XFINITY INTERNET 8009346489", is_debit=True
    )

    assert grocery["category"] == "groceries"
    assert grocery["source"] == "catalog_rule"
    assert grocery["rule_id"] == "groceries_us_supermarkets"
    assert service["category"] == "bills_utilities"
    assert service["source"] == "catalog_rule"


def test_outgoing_third_party_transfer_defaults_to_shopping_and_review():
    database = MerchantDatabase(load_user_rules=False)

    result = database.categorize_transaction_with_details(
        "ZELLE PAYMENT TO JUAN PEREZ", is_debit=True
    )

    assert result["category"] == "shopping"
    assert result["source"] == "catalog_rule"
    assert result["rule_id"] == "outgoing_third_party_transfers"
    assert result["transaction_type"] == "third_party_transfer"
    assert result["review_required"] is True


def test_third_party_transfer_rule_requires_an_outgoing_direction():
    database = MerchantDatabase(load_user_rules=False)

    incoming = database.categorize_transaction_with_details(
        "ZELLE PAYMENT TO JUAN PEREZ", is_debit=False
    )

    assert incoming["rule_id"] != "outgoing_third_party_transfers"
    assert incoming["transaction_type"] != "third_party_transfer"


def test_explicit_own_account_transfer_beats_third_party_transfer_rule():
    database = MerchantDatabase(load_user_rules=False)

    result = database.categorize_transaction_with_details(
        "TRANSFER TO MY ACCOUNT SAVINGS", is_debit=True
    )

    assert result["category"] == "internal_transfer"
    assert result["rule_id"] == "own_account_transfers"
    assert result["transaction_type"] != "third_party_transfer"
    assert result["review_required"] is False


def test_catalog_uses_word_boundaries_and_avoids_ambiguous_big_box_names():
    database = MerchantDatabase(load_user_rules=False)

    assert database.categorize_transaction_with_details(
        "VALIDI CONSULTING", is_debit=True
    )["category"] == "uncategorized"
    assert database.categorize_transaction(
        "WALMART SUPERCENTER", is_debit=True
    )[0] == "uncategorized"
    assert database.categorize_transaction_with_details(
        "WALMART GROCERY PICKUP", is_debit=True
    )["category"] == "groceries"


def test_custom_categories_are_never_saved_as_merchant_rules(tmp_path):
    database = MerchantDatabase()
    database.user_rules_path = str(tmp_path / "rules.json")

    saved = database.save_user_category_rule(
        "Neighborhood Pharmacy", "custom_aux_1"
    )

    assert saved is False
    assert "neighborhood pharmacy" not in database.user_category_overrides
    assert not (tmp_path / "rules.json").exists()

    assert database.save_user_category_rule(
        "Future custom slot", "custom_aux_99"
    ) is False


def test_custom_rules_are_ignored_if_found_in_a_rules_file(tmp_path):
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "normal merchant": "groceries",
                "personal merchant": "custom_aux_1",
            }
        ),
        encoding="utf-8",
    )
    database = MerchantDatabase()
    database.user_rules_path = str(rules_path)

    loaded = database._load_user_category_overrides()

    assert loaded == {"normal merchant": "groceries"}


def test_standard_financial_category_still_persists(tmp_path):
    database = MerchantDatabase()
    database.user_rules_path = str(tmp_path / "rules.json")
    database.user_category_overrides = {}

    assert database.save_user_category_rule(
        "Neighborhood Pharmacy", "healthcare"
    ) is True

    saved = json.loads((tmp_path / "rules.json").read_text(encoding="utf-8"))
    assert saved == {"neighborhood pharmacy": "healthcare"}


def test_remembered_correction_is_direction_scoped_and_beats_catalog(tmp_path):
    rules_path = tmp_path / "rules.json"
    database = MerchantDatabase(
        load_user_rules=True, user_rules_path=str(rules_path)
    )

    assert database.save_user_category_rule(
        "WHOLE FOODS MARKET 123456", "shopping", is_debit=True
    )
    assert database.save_user_category_rule(
        "WHOLE FOODS MARKET 123456", "income", is_debit=False
    )

    reloaded = MerchantDatabase(
        load_user_rules=True, user_rules_path=str(rules_path)
    )
    debit = reloaded.categorize_transaction_with_details(
        "WHOLE FOODS MARKET 999999", is_debit=True
    )
    credit = reloaded.categorize_transaction_with_details(
        "WHOLE FOODS MARKET 777777", is_debit=False
    )

    assert debit["category"] == "shopping"
    assert credit["category"] == "income"
    assert debit["source"] == credit["source"] == "user_rule"


def test_invalid_catalog_rules_are_ignored(tmp_path):
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps({
            "schema_version": 1,
            "rules": [
                {
                    "id": "bad-category",
                    "category": "invented",
                    "direction": "debit",
                    "confidence": 1,
                    "patterns": ["merchant"],
                },
                {
                    "id": "good-category",
                    "category": "groceries",
                    "direction": "debit",
                    "confidence": 0.95,
                    "patterns": ["safe market"],
                },
            ],
        }),
        encoding="utf-8",
    )

    database = MerchantDatabase(
        load_user_rules=False, catalog_path=str(catalog_path)
    )

    assert [rule["id"] for rule in database.catalog_rules] == ["good-category"]
