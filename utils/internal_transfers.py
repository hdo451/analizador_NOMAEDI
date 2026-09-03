"""Deterministic state handling for automatic and manual internal transfers."""

from typing import Mapping, MutableMapping


TRANSFER_OVERRIDE_AUTO = "auto"
TRANSFER_OVERRIDE_TRANSFER = "transfer"
TRANSFER_OVERRIDE_NORMAL = "normal"
INTERNAL_TRANSFER_CATEGORY = "internal_transfer"
VALID_TRANSFER_OVERRIDES = {
    TRANSFER_OVERRIDE_AUTO,
    TRANSFER_OVERRIDE_TRANSFER,
    TRANSFER_OVERRIDE_NORMAL,
}


def normalize_transfer_override(value: object) -> str:
    """Return a supported override value, defaulting safely to automatic mode."""
    normalized = str(value or TRANSFER_OVERRIDE_AUTO).strip().lower()
    if normalized not in VALID_TRANSFER_OVERRIDES:
        return TRANSFER_OVERRIDE_AUTO
    return normalized


def capture_pre_transfer_state(transaction: MutableMapping[str, object]) -> None:
    """Preserve the financial treatment that existed before transfer detection."""
    is_debit = bool(transaction.get("is_debit"))
    legacy_transfer = bool(
        transaction.get(
            "detected_internal_transfer",
            transaction.get("possible_internal_transfer", False),
        )
    )
    transaction.setdefault(
        "pre_transfer_is_spending",
        (
            is_debit
            if legacy_transfer
            else bool(transaction.get("effective_is_spending", is_debit))
        ),
    )
    transaction.setdefault(
        "pre_transfer_is_income",
        (
            not is_debit
            if legacy_transfer
            else bool(transaction.get("effective_is_income", not is_debit))
        ),
    )
    current_category = str(transaction.get("category") or "other")
    if current_category != INTERNAL_TRANSFER_CATEGORY:
        transaction.setdefault("pre_transfer_category", current_category)
        transaction.setdefault(
            "pre_transfer_category_source",
            str(transaction.get("category_source") or "automatic"),
        )
    else:
        detected_category = str(transaction.get("detected_category") or "other")
        if detected_category == INTERNAL_TRANSFER_CATEGORY:
            detected_category = "other"
        transaction.setdefault("pre_transfer_category", detected_category)
        transaction.setdefault("pre_transfer_category_source", "automatic")


def effective_internal_transfer(transaction: Mapping[str, object]) -> bool:
    """Resolve the effective transfer status from detection plus user override."""
    override = normalize_transfer_override(
        transaction.get("internal_transfer_override")
    )
    if override == TRANSFER_OVERRIDE_TRANSFER:
        return True
    if override == TRANSFER_OVERRIDE_NORMAL:
        return False
    return bool(
        transaction.get(
            "detected_internal_transfer",
            transaction.get("possible_internal_transfer", False),
        )
    )


def apply_transfer_override(
    transaction: MutableMapping[str, object], override: object
) -> bool:
    """Apply a three-state user choice and synchronize reporting flags.

    ``possible_internal_transfer`` remains the backwards-compatible effective
    value. Automatic detection is kept separately so a user can override it and
    later return to automatic mode without losing the analyzer's conclusion.
    """
    capture_pre_transfer_state(transaction)
    normalized_override = normalize_transfer_override(override)
    before = (
        normalize_transfer_override(transaction.get("internal_transfer_override")),
        bool(transaction.get("possible_internal_transfer", False)),
        bool(transaction.get("effective_is_spending", False)),
        bool(transaction.get("effective_is_income", False)),
        str(transaction.get("category") or "other"),
    )

    transaction["internal_transfer_override"] = normalized_override
    is_transfer = effective_internal_transfer(transaction)
    transaction["possible_internal_transfer"] = is_transfer

    if is_transfer:
        transaction["effective_is_spending"] = False
        transaction["effective_is_income"] = False
        transaction["category"] = INTERNAL_TRANSFER_CATEGORY
    else:
        transaction["effective_is_spending"] = bool(
            transaction.get("pre_transfer_is_spending", False)
        )
        transaction["effective_is_income"] = bool(
            transaction.get("pre_transfer_is_income", False)
        )
        if transaction.get("category") == INTERNAL_TRANSFER_CATEGORY:
            transaction["category"] = str(
                transaction.get("pre_transfer_category") or "other"
            )
            transaction["category_source"] = str(
                transaction.get("pre_transfer_category_source") or "automatic"
            )

    if normalized_override == TRANSFER_OVERRIDE_TRANSFER:
        transaction["internal_transfer_source"] = "manual_transfer"
        transaction["category_source"] = "user_transfer"
        transaction["internal_transfer_reason"] = (
            "Marked as an internal transfer by the user"
        )
    elif normalized_override == TRANSFER_OVERRIDE_NORMAL:
        transaction["internal_transfer_source"] = "manual_normal"
        transaction["internal_transfer_reason"] = (
            "The user overrode the automatic transfer treatment"
        )
    else:
        transaction["internal_transfer_source"] = "automatic"
        if is_transfer:
            transaction["category_source"] = "automatic_transfer"
        transaction["internal_transfer_reason"] = str(
            transaction.get("internal_transfer_detection_reason") or ""
        )

    after = (
        normalized_override,
        bool(transaction.get("possible_internal_transfer", False)),
        bool(transaction.get("effective_is_spending", False)),
        bool(transaction.get("effective_is_income", False)),
        str(transaction.get("category") or "other"),
    )
    return before != after


def set_automatic_transfer_detection(
    transaction: MutableMapping[str, object], detected: bool, reason: str = ""
) -> None:
    """Store a fresh automatic conclusion and resolve its effective treatment."""
    capture_pre_transfer_state(transaction)
    transaction["detected_internal_transfer"] = bool(detected)
    transaction["internal_transfer_detection_reason"] = reason if detected else ""
    transaction.setdefault("internal_transfer_override", TRANSFER_OVERRIDE_AUTO)
    apply_transfer_override(transaction, transaction["internal_transfer_override"])
