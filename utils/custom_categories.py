"""Session-only custom category definitions and validation helpers.

Custom categories are intentionally never persisted here.  Their display names
live in Streamlit session state, while these stable IDs allow a category to be
renamed without rewriting every assigned transaction.
"""

from typing import Dict, Iterable, Mapping, MutableMapping, Optional


CUSTOM_CATEGORY_PREFIX = "custom_aux_"
CUSTOM_CATEGORY_IDS = (
    "custom_aux_1",
    "custom_aux_2",
    "custom_aux_3",
)
DEFAULT_CUSTOM_CATEGORY_LABELS = {
    "custom_aux_1": "Auxiliar 1",
    "custom_aux_2": "Auxiliar 2",
    "custom_aux_3": "Auxiliar 3",
}
MAX_CUSTOM_CATEGORY_LABEL_LENGTH = 50


def is_custom_category(category: object) -> bool:
    """Return whether ``category`` is one of the supported custom slots."""
    return str(category or "") in CUSTOM_CATEGORY_IDS


def default_custom_category_labels() -> Dict[str, str]:
    """Return a fresh copy of the default labels for a new user session."""
    return dict(DEFAULT_CUSTOM_CATEGORY_LABELS)


def can_assign_custom_category(transaction: Mapping[str, object]) -> bool:
    """Return whether a transaction is an effective spending debit."""
    return bool(transaction.get("is_debit")) and bool(
        transaction.get("effective_is_spending", True)
    )


def assign_effective_category(
    transaction: MutableMapping[str, object], new_category: str
) -> bool:
    """Apply a user category choice while preserving the automatic category.

    Returns ``True`` only when the effective category changed. Custom categories
    are rejected for transactions that do not count as spending.
    """
    old_category = str(transaction.get("category") or "other")
    if is_custom_category(new_category) and not can_assign_custom_category(transaction):
        raise ValueError(
            "Las categorías personalizadas solo pueden asignarse a transacciones que cuentan como gasto."
        )

    transaction.setdefault(
        "detected_category",
        old_category if not is_custom_category(old_category) else "other",
    )
    if new_category == old_category:
        return False

    transaction["category"] = new_category
    transaction["category_source"] = (
        "user_custom" if is_custom_category(new_category) else "user_standard"
    )
    return True


def validate_custom_category_labels(
    labels: Mapping[str, object],
    reserved_labels: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Normalize and validate the three session-only custom labels.

    Labels must be present, unique, reasonably short, and distinct from the
    built-in category labels offered in the same selector.
    """
    normalized: Dict[str, str] = {}
    seen = set()
    reserved = {
        str(label).strip().casefold()
        for label in (reserved_labels or [])
        if str(label).strip()
    }

    for category_id in CUSTOM_CATEGORY_IDS:
        label = str(labels.get(category_id, "")).strip()
        if not label:
            raise ValueError("Los nombres de las categorías personalizadas no pueden quedar vacíos.")
        if len(label) > MAX_CUSTOM_CATEGORY_LABEL_LENGTH:
            raise ValueError(
                f"Cada nombre puede tener como máximo {MAX_CUSTOM_CATEGORY_LABEL_LENGTH} caracteres."
            )

        comparable = label.casefold()
        if comparable in seen:
            raise ValueError("Los nombres de las categorías personalizadas deben ser diferentes.")
        if comparable in reserved:
            raise ValueError(
                f"'{label}' ya corresponde a una categoría financiera existente."
            )

        seen.add(comparable)
        normalized[category_id] = label

    return normalized


def resolve_category_label(
    category: object,
    custom_labels: Optional[Mapping[str, str]] = None,
    system_labels: Optional[Mapping[str, str]] = None,
) -> str:
    """Resolve a category code to a user-facing label."""
    code = str(category or "other")
    if is_custom_category(code):
        return str((custom_labels or {}).get(code) or DEFAULT_CUSTOM_CATEGORY_LABELS[code])
    if system_labels and code in system_labels:
        return str(system_labels[code])
    return code.replace("_", " ").title()
