import pytest

from utils.custom_categories import (
    CUSTOM_CATEGORY_IDS,
    assign_effective_category,
    can_assign_custom_category,
    default_custom_category_labels,
    is_custom_category,
    resolve_category_label,
    validate_custom_category_labels,
)


def test_default_labels_are_fresh_and_generic():
    first = default_custom_category_labels()
    second = default_custom_category_labels()

    assert tuple(first) == CUSTOM_CATEGORY_IDS
    assert list(first.values()) == ["Auxiliar 1", "Auxiliar 2", "Auxiliar 3"]
    assert first is not second


def test_custom_labels_accept_accents_and_are_normalized():
    labels = validate_custom_category_labels(
        {
            "custom_aux_1": "  Hermana enferma  ",
            "custom_aux_2": "Educación de José",
            "custom_aux_3": "Viaje familiar",
        },
        reserved_labels=["Healthcare", "Transportation"],
    )

    assert labels["custom_aux_1"] == "Hermana enferma"
    assert resolve_category_label("custom_aux_2", labels) == "Educación de José"


@pytest.mark.parametrize(
    "labels",
    [
        {
            "custom_aux_1": "",
            "custom_aux_2": "Dos",
            "custom_aux_3": "Tres",
        },
        {
            "custom_aux_1": "Familia",
            "custom_aux_2": "familia",
            "custom_aux_3": "Tres",
        },
        {
            "custom_aux_1": "Healthcare",
            "custom_aux_2": "Dos",
            "custom_aux_3": "Tres",
        },
    ],
)
def test_invalid_or_reserved_custom_labels_are_rejected(labels):
    with pytest.raises(ValueError):
        validate_custom_category_labels(labels, reserved_labels=["Healthcare"])


def test_only_supported_slots_are_custom_categories():
    assert is_custom_category("custom_aux_1")
    assert not is_custom_category("custom_aux_4")
    assert not is_custom_category("healthcare")


def test_custom_categories_only_accept_effective_spending_debits():
    assert can_assign_custom_category(
        {"is_debit": True, "effective_is_spending": True}
    )
    assert not can_assign_custom_category(
        {"is_debit": False, "effective_is_spending": False}
    )
    assert not can_assign_custom_category(
        {"is_debit": True, "effective_is_spending": False}
    )


def test_assignment_preserves_detected_category_and_tracks_user_source():
    transaction = {
        "category": "healthcare",
        "is_debit": True,
        "effective_is_spending": True,
    }

    assert assign_effective_category(transaction, "custom_aux_1") is True
    assert transaction["detected_category"] == "healthcare"
    assert transaction["category"] == "custom_aux_1"
    assert transaction["category_source"] == "user_custom"

    assert assign_effective_category(transaction, "groceries") is True
    assert transaction["detected_category"] == "healthcare"
    assert transaction["category_source"] == "user_standard"


def test_assignment_rejects_custom_category_for_income():
    transaction = {
        "category": "income",
        "is_debit": False,
        "effective_is_spending": False,
    }

    with pytest.raises(ValueError):
        assign_effective_category(transaction, "custom_aux_1")

    assert transaction["category"] == "income"
    assert "detected_category" not in transaction
