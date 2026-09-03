"""Mes a Mes — simplified, deterministic bank-statement analyzer."""

from __future__ import annotations

import copy
import hashlib
import re
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from main_coordinator import BankStatementAnalyzer
from utils.cash_allocations import (
    add_cash_allocation,
    cash_allocation_state,
    cash_withdrawals,
    remove_cash_allocation,
)
from utils.custom_categories import (
    CUSTOM_CATEGORY_IDS,
    assign_effective_category,
    default_custom_category_labels,
    is_custom_category,
    validate_custom_category_labels,
)
from utils.internal_transfers import (
    INTERNAL_TRANSFER_CATEGORY,
    TRANSFER_OVERRIDE_NORMAL,
    TRANSFER_OVERRIDE_TRANSFER,
    apply_transfer_override,
)
from utils.llm_interface import resolve_openai_api_key
from utils.monthly_analysis import (
    ACCOUNT_PROFILE_BY_CODE,
    MAX_ACCOUNTS,
    available_months,
    category_comparison,
    compare_months,
    comparison_coverage,
    default_month_pair,
    infer_account_profile,
    plain_language_findings,
    summarize_months,
)


CATEGORY_CODES = [
    "food_dining",
    "groceries",
    "transportation",
    "shopping",
    "bills_utilities",
    "entertainment",
    "healthcare",
    "atm_cash",
    "income",
    "other_income",
    "international_transfer_in",
    "international_transfer_out",
    INTERNAL_TRANSFER_CATEGORY,
    "fees",
    "other",
    "uncategorized",
]

CATEGORY_LABELS = {
    "food_dining": "Comidas y restaurantes",
    "groceries": "Supermercado",
    "transportation": "Transporte",
    "shopping": "Compras",
    "bills_utilities": "Cuentas y servicios",
    "entertainment": "Entretenimiento",
    "healthcare": "Salud",
    "atm_cash": "Retiro de efectivo",
    "income": "Ingresos",
    "other_income": "Otros ingresos",
    "international_transfer_in": "Transferencia internacional recibida",
    "international_transfer_out": "Transferencia internacional enviada",
    INTERNAL_TRANSFER_CATEGORY: "Transferencias entre mis cuentas",
    "fees": "Comisiones",
    "other": "Otros",
    "uncategorized": "Por revisar",
}

LEGACY_CATEGORY_LABELS_EN = {
    "other_income": "Other Income",
    "international_transfer_in": "International Transfer Received",
    "international_transfer_out": "International Transfer Sent",
    INTERNAL_TRANSFER_CATEGORY: "Transfers Between My Accounts",
}

MONTH_NAMES = {
    "01": "ene", "02": "feb", "03": "mar", "04": "abr",
    "05": "may", "06": "jun", "07": "jul", "08": "ago",
    "09": "sep", "10": "oct", "11": "nov", "12": "dic",
}

APP_CSS = """
<style>
    :root { --ink:#233663; --paper:#f5f5fa; --gold:#dca943; --blue-soft:#526b9d; }
    .stApp { background:var(--paper); color:var(--ink); }
    [data-testid="stSidebar"] { background:#233663; }
    [data-testid="stSidebar"] * { color:#f5f5fa; }
    [data-testid="stSidebar"] .stButton button { background:transparent; border-color:#dca943; color:#f5f5fa; }
    .hero { background:linear-gradient(135deg,#233663 0%,#324b82 100%); border-radius:24px; color:#fff; padding:2rem 2.25rem; margin-bottom:1.3rem; box-shadow:0 16px 34px rgba(35,54,99,.18); border-bottom:5px solid #dca943; }
    .hero-kicker { color:#f2c45f; font-size:.82rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
    .hero h1 { color:#fff; font-size:3rem; line-height:1; letter-spacing:-.04em; margin:.45rem 0 .8rem; }
    .hero p { color:#eef1f8; font-size:1.05rem; margin:0; max-width:720px; }
    [data-testid="stMetric"] { background:rgba(255,255,255,.82); border:1px solid #d7ddeb; border-radius:16px; padding:1rem; }
    .simple-card { background:rgba(255,255,255,.82); border:1px solid #d7ddeb; border-left:5px solid #dca943; border-radius:14px; padding:1.15rem 1.3rem; margin:.4rem 0; }
    .rule-chip { display:inline-block; background:#fff2cd; color:#233663; border:1px solid #dca943; border-radius:999px; padding:.35rem .7rem; font-weight:700; }
    div.stButton > button[kind="primary"] { background:#dca943; border-color:#dca943; color:#233663; font-weight:800; border-radius:12px; }
    h1,h2,h3 { color:#233663; }
</style>
"""


def _category_code_to_label(code: str) -> str:
    custom = st.session_state.get("custom_category_labels", default_custom_category_labels())
    return str(custom.get(code) or CATEGORY_LABELS.get(code) or code)


def _category_label_to_code(label: str) -> str:
    normalized = str(label).strip().casefold()
    custom = st.session_state.get("custom_category_labels", default_custom_category_labels())
    for code, display in custom.items():
        if normalized == str(display).strip().casefold():
            return code
    for code, display in CATEGORY_LABELS.items():
        if normalized == display.casefold():
            return code
    for code, display in LEGACY_CATEGORY_LABELS_EN.items():
        if normalized == display.casefold():
            return code
    candidate = normalized.replace(" ", "_")
    return candidate if candidate in CATEGORY_CODES else "other"


def _transaction_category_code_to_label(code: str) -> str:
    return _category_code_to_label(code)


def _transaction_category_label_to_code(label: str) -> str:
    return _category_label_to_code(label)


def _selectable_category_labels() -> list[str]:
    standard = [
        _transaction_category_code_to_label(code)
        for code in CATEGORY_CODES
        if code != "uncategorized"
    ]
    custom = [
        _transaction_category_code_to_label(code)
        for code in CUSTOM_CATEGORY_IDS
    ]
    return standard + custom


def _selectable_spending_category_labels() -> list[str]:
    excluded = {
        "income",
        "other_income",
        "international_transfer_in",
        "international_transfer_out",
        INTERNAL_TRANSFER_CATEGORY,
    }
    standard = [
        _transaction_category_code_to_label(code)
        for code in CATEGORY_CODES
        if code not in excluded and code != "uncategorized"
    ]
    custom = [
        _transaction_category_code_to_label(code)
        for code in CUSTOM_CATEGORY_IDS
    ]
    return standard + custom


def _transactions_to_editor_df(transactions: list) -> pd.DataFrame:
    """Preserve the audited transaction-review schema used by regression tests."""
    rows = []
    for idx, txn in enumerate(transactions):
        if not txn.get("direction_known", True):
            movement = "REVISAR"
        else:
            movement = "EGRESO" if txn.get("is_debit") else "INGRESO"
        rows.append({
            "_txn_index": int(txn.get("_global_index", idx)),
            "Seleccionar": False,
            "Fecha": txn.get("date", ""),
            "Mes": txn.get("month", ""),
            "Persona": txn.get("person", ""),
            "Documento": txn.get("source_file_name", ""),
            "Tipo de documento": txn.get("document_type", ""),
            "Descripción": txn.get("description", ""),
            "Categoría": _transaction_category_code_to_label(txn.get("category", "other")),
            "Monto": float(txn.get("amount") or 0.0),
            "Tipo": movement,
            "Cuenta como gasto": bool(txn.get("effective_is_spending", txn.get("is_debit", False))),
            "Explicación de transferencia": str(txn.get("internal_transfer_detection_reason") or "No se detectó automáticamente una transferencia interna"),
            "Confianza": f"{float(txn.get('confidence') or 0):.0%}",
            "Origen": str(txn.get("source") or "deterministic").title(),
        })
    return pd.DataFrame(rows)


def _category_method_label(transaction: dict) -> str:
    """Explain the effective category source in plain language."""
    category_source = str(transaction.get("category_source") or "")
    source = str(transaction.get("source") or "")
    if transaction.get("category") == INTERNAL_TRANSFER_CATEGORY:
        return "Transferencia entre tus cuentas"
    if category_source.startswith("user"):
        return "Corregida por ti"
    if source == "deterministic_user_rule":
        return "Regla recordada"
    if source == "deterministic_catalog":
        return "Catálogo de comercios"
    if source == "deterministic_third_party_transfer":
        return "Transferencia a tercero"
    if source == "llm" or category_source == "agent_expert":
        return "Agente experto"
    if source in {
        "fallback", "agent_fallback_rule", "deterministic_fallback",
        "deterministic_guardrail",
    }:
        return "Regla · revisar"
    return "Regla automática"


def _category_review_label(transaction: dict) -> str:
    """Return a compact review marker without mislabeling own transfers."""
    if transaction.get("category") == INTERNAL_TRANSFER_CATEGORY:
        return ""
    if (
        transaction.get("third_party_transfer_candidate")
        and not transaction.get("third_party_transfer_reviewed")
    ):
        return "🟨 Transferencia a tercero"
    return "Sí" if transaction.get("category_review_required") else ""


def _annotate_meta_category_types(meta_result: dict, payload: dict) -> dict:
    """Compatibility helper retained for historical category regression tests."""
    lookup = {}
    for item in payload.get("category_breakdown", []):
        for key in (item.get("category"), item.get("category_label")):
            if key:
                lookup[str(key).strip().casefold()] = item
    annotated = copy.deepcopy(meta_result)
    for item in annotated.get("category_analysis", []):
        source = lookup.get(str(item.get("category") or "").strip().casefold())
        if not source:
            source = lookup.get(str(item.get("category_label") or "").strip().casefold())
        if source:
            item["category"] = source.get("category")
            item["category_label"] = source.get("category_label")
            item["category_type"] = source.get("category_type", "system")
    return annotated


def _apply_transaction_review_row(transaction: dict, row) -> dict:
    """Apply a deterministic direction/category correction to one transaction."""
    original_category = str(transaction.get("category") or "other")
    new_category = _transaction_category_label_to_code(row["Categoría"])
    transfer_changed = False
    rejected_category = False
    direction_changed = False
    requested_type = str(row.get("Tipo", "") or "").strip().upper()
    if requested_type in {"EGRESO", "INGRESO"}:
        requested_is_debit = requested_type == "EGRESO"
        if not transaction.get("direction_known", True) or bool(transaction.get("is_debit")) != requested_is_debit:
            transaction["is_debit"] = requested_is_debit
            transaction["direction_known"] = True
            transaction["direction_source"] = "user_review"
            transaction["direction_confidence"] = 1.0
            transaction["excluded_from_totals"] = False
            transaction.pop("exclusion_reason", None)
            transaction["pre_transfer_is_spending"] = requested_is_debit
            transaction["pre_transfer_is_income"] = not requested_is_debit
            if transaction.get("category") != INTERNAL_TRANSFER_CATEGORY:
                transaction["effective_is_spending"] = requested_is_debit
                transaction["effective_is_income"] = not requested_is_debit
            direction_changed = True
    if original_category == INTERNAL_TRANSFER_CATEGORY and new_category != INTERNAL_TRANSFER_CATEGORY:
        transfer_changed = apply_transfer_override(transaction, TRANSFER_OVERRIDE_NORMAL)
    if new_category != str(transaction.get("category") or "other"):
        try:
            assigned = assign_effective_category(transaction, new_category)
            if assigned and new_category != INTERNAL_TRANSFER_CATEGORY:
                transaction["pre_transfer_category"] = new_category
                transaction["pre_transfer_category_source"] = "user_review"
        except ValueError:
            rejected_category = True
    if new_category == INTERNAL_TRANSFER_CATEGORY and original_category != INTERNAL_TRANSFER_CATEGORY and not rejected_category:
        transfer_changed = apply_transfer_override(transaction, TRANSFER_OVERRIDE_TRANSFER) or transfer_changed
    final_category = str(transaction.get("category") or "other")
    category_changed = final_category != original_category
    if category_changed:
        transaction["category_review_required"] = False
        if transaction.get("third_party_transfer_candidate"):
            transaction["third_party_transfer_reviewed"] = True
    return {
        "row_changed": transfer_changed or category_changed or direction_changed,
        "transfer_changed": transfer_changed,
        "category_changed": category_changed,
        "direction_changed": direction_changed,
        "rejected_custom_category": rejected_category,
        "rule_category": final_category if category_changed and final_category == new_category and not is_custom_category(final_category) and final_category != INTERNAL_TRANSFER_CATEGORY else None,
    }


def _month_label(month: str) -> str:
    if not month or len(month) != 7:
        return month
    return f"{MONTH_NAMES.get(month[5:], month[5:])} {month[:4]}"


def _money(value: float) -> str:
    return f"${float(value):,.2f}"


def _account_label(code: str) -> str:
    return ACCOUNT_PROFILE_BY_CODE.get(code, {}).get("label", code)


def _build_statement_inputs_from_uploads(uploaded_files: list, account_assignments: Optional[dict] = None) -> list:
    """Attach one of the six auditable account profiles to every uploaded PDF."""
    assignments = account_assignments or {}
    statement_inputs = []
    for idx, uploaded_file in enumerate(uploaded_files):
        selected_code = assignments.get(idx) or assignments.get(uploaded_file.name)
        explicitly_assigned = selected_code in ACCOUNT_PROFILE_BY_CODE
        if selected_code not in ACCOUNT_PROFILE_BY_CODE:
            selected_code = infer_account_profile(uploaded_file.name)
        profile = ACCOUNT_PROFILE_BY_CODE[selected_code]
        metadata = {
            "file_name": uploaded_file.name,
            "person": "default",
            "account_label": profile["code"],
            "account_profile_inferred": not explicitly_assigned,
            "institution": "",
        }
        # A manual assignment is authoritative. Without one, Agent 1 detects
        # bank-account versus credit-card semantics from the PDF itself.
        if explicitly_assigned:
            metadata["document_type"] = profile["document_type"]
        statement_inputs.append({
            "uploaded_file": uploaded_file,
            "metadata": metadata,
        })
    return statement_inputs


def initialize_session_state():
    if "analyzer" not in st.session_state:
        st.session_state.analyzer = BankStatementAnalyzer(deterministic_only=True)
    if "analysis_result" not in st.session_state:
        st.session_state.analysis_result = None
    if "session_instance_id" not in st.session_state:
        st.session_state.session_instance_id = uuid.uuid4().hex
    if "custom_category_labels" not in st.session_state:
        st.session_state.custom_category_labels = default_custom_category_labels()
    if "transaction_revision_version" not in st.session_state:
        st.session_state.transaction_revision_version = 0


def _render_sidebar():
    with st.sidebar:
        root = Path(__file__).resolve().parent
        logo_path = next(
            (
                path
                for path in (
                    root / "Hispanic_Wealth.png",
                    root / "HispanicWealth_IMAGE.png",
                )
                if path.exists()
            ),
            None,
        )
        if logo_path:
            st.image(str(logo_path), width="stretch")
        st.markdown("## Mes a Mes")
        st.caption("Una lectura clara de tus estados de cuenta.")
        st.divider()
        st.markdown("**Cómo funciona**")
        st.write("1. Sube uno o más PDFs.")
        st.write(f"2. Identificamos automáticamente hasta {MAX_ACCOUNTS} tipos de cuenta.")
        st.write("3. Elige dos meses para comparar.")
        st.divider()
        st.markdown('<span class="rule-chip">Cálculos trazables</span>', unsafe_allow_html=True)
        st.caption(
            "Montos, fechas, saldos, transferencias y comparaciones se resuelven "
            "con reglas. El agente opcional solo propone categorías."
        )
        st.divider()
        confirm = st.checkbox("Confirmo que quiero borrar la sesión")
        if st.button("Borrar sesión", width="stretch", disabled=not confirm):
            st.session_state.clear()
            st.rerun()


def _render_custom_category_manager():
    """Let the owner name three session-only categories in plain language."""
    with st.expander("Crear mis propias categorías", expanded=False):
        st.caption(
            "Puedes cambiar estos tres nombres, por ejemplo: Casa de mamá, "
            "Gastos del perro o Proyecto personal. No se guardan al cerrar la sesión."
        )
        current = st.session_state.custom_category_labels
        proposed = {}
        columns = st.columns(3)
        for index, category_id in enumerate(CUSTOM_CATEGORY_IDS):
            proposed[category_id] = columns[index].text_input(
                f"Categoría personal {index + 1}",
                value=current[category_id],
                key=f"custom_label_{category_id}",
            )
        if st.button("Guardar nombres de categorías", width="stretch"):
            try:
                normalized = validate_custom_category_labels(
                    proposed,
                    reserved_labels=CATEGORY_LABELS.values(),
                )
            except ValueError as exc:
                st.error(str(exc))
                return
            st.session_state.custom_category_labels = normalized
            st.session_state.transaction_revision_version += 1
            st.rerun()


def _render_upload_area():
    st.markdown("## Agrega tus estados de cuenta")
    st.caption("Puedes subir varios meses y varios documentos de una misma cuenta. Los PDFs escaneados como imagen todavía no son compatibles.")
    uploaded_files = st.file_uploader(
        "Arrastra aquí tus archivos PDF",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"monthly_upload_{st.session_state.session_instance_id}",
    )
    if not uploaded_files:
        st.markdown('<div class="simple-card"><b>Para empezar</b><br>Sube al menos un estado de cuenta. Para ver cambios, incluye documentos que contengan transacciones de dos meses distintos.</div>', unsafe_allow_html=True)
        return

    api_key_available = bool(resolve_openai_api_key())
    with st.expander("Agente experto de categorización", expanded=True):
        use_expert_agent = st.checkbox(
            "Usar el agente para mejorar las categorías automáticas",
            value=api_key_available,
            disabled=not api_key_available,
            help=(
                "Revisa movimientos categorizados por comercio o sin categoría; "
                "no puede cambiar sus montos, fechas ni sentido."
            ),
        )
        if not api_key_available:
            st.info(
                "El agente está listo, pero falta configurar OPENAI_API_KEY en "
                ".env o en los secretos de Streamlit. El análisis por reglas sigue disponible."
            )
        consent = st.checkbox(
            "Autorizo enviar a OpenAI la descripción, fecha, monto, sentido, banco y tipo de cuenta de los movimientos seleccionados.",
            value=False,
            disabled=not use_expert_agent,
        )
        st.caption(
            "Se ocultan números largos que parezcan tarjetas, cuentas o referencias. "
            "El PDF completo no se envía al agente."
        )

    analyze_disabled = bool(use_expert_agent and not consent)
    if st.button(
        "Analizar mis meses",
        type="primary",
        width="stretch",
        disabled=analyze_disabled,
    ):
        process_uploaded_files(
            _build_statement_inputs_from_uploads(uploaded_files),
            use_expert_agent=bool(use_expert_agent and consent),
        )


def _validate_unique_uploads(statement_inputs: list) -> Optional[str]:
    seen = {}
    for item in statement_inputs:
        uploaded = item["uploaded_file"]
        digest = hashlib.sha256(uploaded.getvalue()).hexdigest()
        if digest in seen:
            return f"{uploaded.name} tiene el mismo contenido que {seen[digest]}. Elimina el duplicado para no contar movimientos dos veces."
        seen[digest] = uploaded.name
    return None


def process_uploaded_files(statement_inputs: list, use_expert_agent: bool = False):
    """Process uploads with deterministic math and optional guarded categorization."""
    duplicate_error = _validate_unique_uploads(statement_inputs)
    if duplicate_error:
        st.error(duplicate_error)
        return
    temp_paths = []
    try:
        api_key = resolve_openai_api_key() if use_expert_agent else None
        if use_expert_agent and not api_key:
            st.error("No se encontró OPENAI_API_KEY. Desactiva el agente o configura la clave.")
            return
        st.session_state.analyzer = BankStatementAnalyzer(
            openai_api_key=api_key,
            deterministic_only=not use_expert_agent,
            category_model="gpt-5.6",
            enable_ai_insights=False,
            load_user_rules=True,
        )
        statements = []
        for idx, item in enumerate(statement_inputs, start=1):
            uploaded = item["uploaded_file"]
            safe_name = Path(uploaded.name).name or f"estado_{idx}.pdf"
            prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(safe_name).stem)[:30] or f"estado_{idx}"
            with tempfile.NamedTemporaryFile(prefix=f"{prefix}_{idx}_", suffix=".pdf", delete=False) as temporary:
                temporary.write(uploaded.getbuffer())
                temp_path = temporary.name
            temp_paths.append(temp_path)
            statements.append({"pdf_path": temp_path, "metadata": item.get("metadata", {})})
        spinner_text = (
            "Leyendo, conciliando y revisando categorías con el agente..."
            if use_expert_agent
            else "Leyendo movimientos y conciliando saldos..."
        )
        with st.spinner(spinner_text):
            result = st.session_state.analyzer.analyze_statements(statements, generate_ai_insights=False)
        if result.get("success"):
            st.session_state.analysis_result = result
            if use_expert_agent:
                categorized = sum(
                    1 for txn in result.get("transactions", [])
                    if txn.get("source") == "llm"
                )
                st.success(
                    f"Listo. El agente revisó categorías y aceptamos {categorized} "
                    "propuesta(s); todos los cálculos siguen siendo determinísticos."
                )
            else:
                st.success("Listo. Los meses se calcularon con reglas determinísticas.")
        else:
            st.error(result.get("error", "No fue posible analizar los archivos."))
    except Exception as exc:
        st.error(f"No fue posible completar el análisis: {exc}")
    finally:
        for temp_path in temp_paths:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except OSError:
                pass


def _render_quality_note(result: dict):
    transactions = result.get("transactions", [])
    unresolved = sum(1 for txn in transactions if not txn.get("direction_known", True))
    fallback = sum(
        1 for txn in transactions
        if txn.get("source") in {
            "deterministic_fallback", "fallback", "agent_fallback_rule"
        }
    )
    agent_categorized = sum(1 for txn in transactions if txn.get("source") == "llm")
    catalog_categorized = sum(
        1 for txn in transactions if txn.get("source") == "deterministic_catalog"
    )
    remembered_categorized = sum(
        1 for txn in transactions if txn.get("source") == "deterministic_user_rule"
    )
    review_required = sum(
        1 for txn in transactions if txn.get("category_review_required")
    )
    reconciled = sum(1 for item in result.get("document_debug", []) if item.get("reconciliation", {}).get("reconciled") is True)
    total_docs = len(result.get("documents", []))
    calls = int(result.get("system_metrics", {}).get("total_llm_calls") or 0)
    st.caption(
        f"Control de datos: {reconciled}/{total_docs} documentos conciliados · "
        f"{unresolved} movimientos sin dirección · {fallback} fallbacks · "
        f"{catalog_categorized} por catálogo · {remembered_categorized} recordadas · "
        f"{agent_categorized} del agente · {calls} llamada(s) al agente"
    )
    if unresolved:
        st.warning(f"Hay {unresolved} movimiento(s) cuyo sentido no pudo probarse. No se incluyeron en ingresos ni gastos; puedes corregirlos en la tabla.")
    if review_required:
        st.info(
            f"El agente marcó {review_required} movimiento(s) para revisión. "
            "Puedes corregirlos en la tabla de movimientos."
        )


def _render_monthly_overview(month_rows: list):
    month_df = pd.DataFrame(month_rows)
    fig = go.Figure()
    month_labels = [_month_label(month) for month in month_df["month"]]
    fig.add_bar(x=month_labels, y=month_df["total_spent"], name="Gastos", marker_color="#DCA943", hovertemplate="%{x}<br>Gastos: $%{y:,.2f}<extra></extra>")
    fig.add_bar(x=month_labels, y=month_df["total_income"], name="Ingresos", marker_color="#233663", hovertemplate="%{x}<br>Ingresos: $%{y:,.2f}<extra></extra>")
    fig.update_layout(title="Ingresos y gastos por mes", barmode="group", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_orientation="h", margin=dict(l=10, r=10, t=55, b=10), yaxis_title="Monto", xaxis_title="")
    st.plotly_chart(fig, width="stretch")


def _render_category_charts(rows: list, base_month: str, current_month: str):
    labels = [row["category_label"] for row in rows]
    grouped = go.Figure()
    grouped.add_bar(y=labels, x=[row["base"] for row in rows], name=_month_label(base_month), orientation="h", marker_color="#8B9ABB")
    grouped.add_bar(y=labels, x=[row["current"] for row in rows], name=_month_label(current_month), orientation="h", marker_color="#DCA943")
    grouped.update_layout(title="Las mismas categorías, lado a lado", barmode="group", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_orientation="h", margin=dict(l=10, r=10, t=55, b=10), xaxis_title="Gasto", yaxis_title="", yaxis={"autorange": "reversed"})
    st.plotly_chart(grouped, width="stretch")


def _recompute_result(result: dict, transactions: list) -> dict:
    """Recalculate all reports locally after a session-only user edit."""
    updated = copy.deepcopy(result)
    updated["transactions"] = transactions
    updated["analysis"] = st.session_state.analyzer.agent3.process(
        transactions,
        generate_ai_insights=False,
        category_labels=st.session_state.custom_category_labels,
    )
    updated["monthly_summary"] = st.session_state.analyzer.aggregate_by_month(
        transactions
    )
    updated["monthly_trends"] = st.session_state.analyzer.compute_monthly_trends(
        updated["monthly_summary"]
    )
    return updated


def _render_cash_allocations(result: dict):
    st.markdown("## ¿Sacaste efectivo del cajero?")
    st.caption(
        "Puedes dividir un retiro en nuevas líneas para indicar en qué usaste el "
        "efectivo. El total del retiro nunca cambia ni se cuenta dos veces."
    )
    withdrawals = cash_withdrawals(result.get("transactions", []))
    if not withdrawals:
        st.info(
            "No detectamos retiros de efectivo. Si alguno aparece con otro nombre, "
            "cambia primero su categoría a ‘Retiro de efectivo’ en la tabla."
        )
        return

    labels_by_id = {
        str(txn["transaction_id"]): (
            f"{txn.get('date', '')} · {_account_label(str(txn.get('account_label') or ''))} "
            f"· {_money(float(txn.get('amount') or 0))} · {txn.get('description', '')}"
        )
        for txn in withdrawals
    }
    parent_id = st.selectbox(
        "Selecciona el retiro",
        list(labels_by_id),
        format_func=lambda value: labels_by_id[value],
        key="cash_withdrawal_choice",
    )
    state = cash_allocation_state(result["transactions"], parent_id)
    summary_columns = st.columns(3)
    summary_columns[0].metric("Retiro original", _money(state["total"]))
    summary_columns[1].metric("Ya explicado", _money(state["allocated"]))
    summary_columns[2].metric("Falta explicar", _money(state["remaining"]))

    if state["remaining"] > 0:
        with st.form("cash_allocation_form", clear_on_submit=True):
            form_columns = st.columns([3, 1.4, 2])
            description = form_columns[0].text_input(
                "¿En qué usaste una parte del efectivo?",
                placeholder="Ej.: feria del barrio",
            )
            amount = form_columns[1].number_input(
                "Monto",
                min_value=0.01,
                max_value=float(state["remaining"]),
                value=min(float(state["remaining"]), 1.0),
                step=1.0,
            )
            category_label = form_columns[2].selectbox(
                "Categoría", _selectable_spending_category_labels()
            )
            add_line = st.form_submit_button(
                "Agregar línea al retiro", width="stretch"
            )
        if add_line:
            try:
                transactions = add_cash_allocation(
                    result["transactions"],
                    parent_id,
                    description,
                    amount,
                    _transaction_category_label_to_code(category_label),
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.session_state.analysis_result = _recompute_result(
                    result, transactions
                )
                st.session_state.transaction_revision_version += 1
                st.rerun()
    else:
        st.success("Todo el retiro está explicado.")

    if state["allocations"]:
        st.markdown("**Líneas agregadas a este retiro**")
        allocation_table = pd.DataFrame(
            {
                "Detalle": [txn["description"] for txn in state["allocations"]],
                "Categoría": [
                    _transaction_category_code_to_label(txn["category"])
                    for txn in state["allocations"]
                ],
                "Monto": [txn["amount"] for txn in state["allocations"]],
            }
        )
        st.dataframe(
            allocation_table,
            width="stretch",
            hide_index=True,
            column_config={
                "Monto": st.column_config.NumberColumn(format="$%.2f")
            },
        )
        removable = {
            str(txn["transaction_id"]): (
                f"{txn['description']} · {_money(float(txn['amount']))}"
            )
            for txn in state["allocations"]
        }
        remove_id = st.selectbox(
            "Línea que quieres eliminar",
            list(removable),
            format_func=lambda value: removable[value],
        )
        if st.button("Eliminar línea seleccionada"):
            transactions = remove_cash_allocation(
                result["transactions"], remove_id
            )
            st.session_state.analysis_result = _recompute_result(
                result, transactions
            )
            st.session_state.transaction_revision_version += 1
            st.rerun()


def _render_transaction_review(result: dict):
    st.markdown("## Todos tus movimientos")
    st.caption(
        "Aquí puedes ver cada línea y corregir su categoría o indicar si fue un "
        "ingreso o un gasto. Los cambios recalculan inmediatamente el informe."
    )
    memory_notice = st.session_state.pop("category_memory_notice", None)
    if memory_notice:
        if memory_notice.get("saved"):
            st.success(memory_notice["message"])
        else:
            st.warning(memory_notice["message"])
    _render_custom_category_manager()
    transactions = result.get("transactions", [])
    editor = _transactions_to_editor_df(transactions)
    if editor.empty:
        st.info("No hay movimientos para revisar.")
        return

    editor["Cómo se categorizó"] = [
        _category_method_label(txn) for txn in transactions
    ]
    editor["Revisar categoría"] = [
        _category_review_label(txn) for txn in transactions
    ]

    filter_columns = st.columns([1.1, 2.9])
    month_options = ["Todos"] + sorted(editor["Mes"].dropna().unique().tolist())
    selected_month = filter_columns[0].selectbox(
        "Mes", month_options, key="transaction_month_filter"
    )
    search = filter_columns[1].text_input(
        "Buscar movimiento", placeholder="Comercio o detalle"
    ).strip().casefold()

    mask = pd.Series(True, index=editor.index)
    if selected_month != "Todos":
        mask &= editor["Mes"] == selected_month
    if search:
        mask &= editor["Descripción"].astype(str).str.casefold().str.contains(
            search, regex=False
        )
    filtered = editor.loc[mask]
    st.caption(f"Mostrando {len(filtered)} de {len(editor)} movimientos")
    third_party_count = sum(
        bool(txn.get("third_party_transfer_candidate"))
        and not bool(txn.get("third_party_transfer_reviewed"))
        and txn.get("category") != INTERNAL_TRANSFER_CATEGORY
        for txn in transactions
    )
    if third_party_count:
        st.warning(
            f"🟨 {third_party_count} transferencia(s) saliente(s) a terceros se "
            "clasificaron provisionalmente como Compras. Revísalas y corrige "
            "la categoría si conoces el destino."
        )
    visible = filtered[
        [
            "_txn_index",
            "Fecha",
            "Mes",
            "Descripción",
            "Categoría",
            "Monto",
            "Tipo",
            "Cómo se categorizó",
            "Revisar categoría",
        ]
    ]
    edited = st.data_editor(
        visible,
        width="stretch",
        hide_index=True,
        key=f"transaction_editor_{st.session_state.transaction_revision_version}",
        height=min(720, max(260, 38 * (len(visible) + 1))),
        column_config={
            "_txn_index": None,
            "Fecha": st.column_config.TextColumn(disabled=True),
            "Mes": st.column_config.TextColumn(disabled=True),
            "Descripción": st.column_config.TextColumn(disabled=True),
            "Monto": st.column_config.NumberColumn(format="$%.2f", disabled=True),
            "Cómo se categorizó": st.column_config.TextColumn(disabled=True),
            "Revisar categoría": st.column_config.TextColumn(disabled=True),
            "Categoría": st.column_config.SelectboxColumn(
                options=_selectable_category_labels(), required=True
            ),
            "Tipo": st.column_config.SelectboxColumn(
                options=["EGRESO", "INGRESO", "REVISAR"], required=True
            ),
        },
    )
    remember_corrections = st.checkbox(
        "Recordar mis correcciones para próximos estados de cuenta",
        value=True,
        help=(
            "Guarda localmente la descripción normalizada, su sentido y la "
            "categoría elegida. No recuerda categorías personales ni transferencias."
        ),
    )
    st.caption(
        "Las reglas recordadas se aplican antes del catálogo general y del "
        "agente. Se guardan en el archivo local de esta instalación; en "
        "Streamlit Community Cloud pueden perderse cuando la app se reinicia."
    )
    if st.button("Aplicar cambios de la tabla", type="primary", width="stretch"):
        _apply_manual_updates(
            result, edited, remember_corrections=remember_corrections
        )


def _apply_manual_updates(
    result: dict,
    edited_df: pd.DataFrame,
    remember_corrections: bool = False,
):
    updated_transactions = copy.deepcopy(result.get("transactions", []))
    changed = 0
    rules_to_remember = set()
    for _, row in edited_df.iterrows():
        index = int(row["_txn_index"])
        if 0 <= index < len(updated_transactions):
            transaction = updated_transactions[index]
            outcome = _apply_transaction_review_row(transaction, row)
            changed += int(outcome["row_changed"])
            if remember_corrections and outcome.get("rule_category"):
                rules_to_remember.add((
                    str(transaction.get("description") or ""),
                    str(outcome["rule_category"]),
                    bool(transaction.get("is_debit")),
                ))
    if not changed:
        st.info("No hay cambios para aplicar.")
        return

    if rules_to_remember:
        merchant_db = st.session_state.analyzer.agent1.merchant_db
        merchant_db.enable_user_rules()
        saved_count = sum(
            merchant_db.save_user_category_rule(
                description, category, is_debit=is_debit
            )
            for description, category, is_debit in sorted(rules_to_remember)
        )
        if saved_count:
            st.session_state.category_memory_notice = {
                "saved": True,
                "message": (
                    f"Recordamos {saved_count} corrección(es). Se aplicarán "
                    "automáticamente en los próximos estados de cuenta."
                ),
            }
        else:
            st.session_state.category_memory_notice = {
                "saved": False,
                "message": "Los cambios se aplicaron, pero no se pudo guardar la regla local.",
            }
    st.session_state.analysis_result = _recompute_result(
        result, updated_transactions
    )
    st.session_state.transaction_revision_version += 1
    st.rerun()


def _redact_diagnostic_line(line: str) -> str:
    text = re.sub(r"\b\d{6,}\b", "••••", str(line))
    return re.sub(r"\b(?:\d[ -]*?){12,19}\b", "••••", text)


def _render_diagnostics(result: dict):
    with st.expander("Detalles de verificación", expanded=False):
        for item in result.get("document_debug", []):
            st.write(f"**{item.get('file_name', 'Documento')}**")
            st.json({
                "perfil_detectado": item.get("statement_profile"),
                "conciliacion": item.get("reconciliation", {}),
                "filas_no_transaccionales_excluidas": item.get("excluded_row_count", 0),
            })
            for line in item.get("sample_transaction_lines", [])[:2]:
                st.code(_redact_diagnostic_line(line))


def display_results(result: dict):
    transactions = result.get("transactions", [])
    months = available_months(transactions)
    if not months:
        st.warning("No se detectó ningún mes válido en los movimientos.")
        _render_diagnostics(result)
        return
    st.divider()
    st.markdown("## Tu resumen")
    _render_quality_note(result)
    month_rows = summarize_months(transactions)
    _render_monthly_overview(month_rows)
    default_base, default_current = default_month_pair(months)
    st.markdown("## Compara dos meses")
    selectors = st.columns(2)
    base_month = selectors[0].selectbox("Mes de referencia", months, index=months.index(default_base), format_func=_month_label)
    current_month = selectors[1].selectbox("Mes para comparar", months, index=months.index(default_current), format_func=_month_label)
    comparison = compare_months(transactions, base_month, current_month)
    coverage = comparison_coverage(transactions, base_month, current_month)
    if base_month == current_month:
        st.info("Sube otro mes o selecciona dos meses distintos para ver la variación.")
    elif not coverage["comparable"]:
        base_only = ", ".join(_account_label(code) for code in coverage["only_in_base"])
        current_only = ", ".join(_account_label(code) for code in coverage["only_in_current"])
        details = []
        if base_only:
            details.append(f"solo en el primer mes: {base_only}")
        if current_only:
            details.append(f"solo en el segundo mes: {current_only}")
        st.warning("Los meses no contienen las mismas cuentas; la diferencia puede deberse a cobertura incompleta (" + "; ".join(details) + ").")
    metrics = st.columns(4)
    metrics[0].metric(
        f"Gastos · {_month_label(base_month)}",
        _money(comparison["base"]["spent"]),
    )
    metrics[1].metric(
        f"Ingresos · {_month_label(base_month)}",
        _money(comparison["base"]["income"]),
    )
    metrics[2].metric(
        f"Gastos · {_month_label(current_month)}",
        _money(comparison["current"]["spent"]),
    )
    metrics[3].metric(
        f"Ingresos · {_month_label(current_month)}",
        _money(comparison["current"]["income"]),
    )
    visible_category_labels = {
        **CATEGORY_LABELS,
        **st.session_state.custom_category_labels,
    }
    rows = category_comparison(
        transactions,
        base_month,
        current_month,
        category_labels=visible_category_labels,
        max_rows=6,
    )
    if rows:
        _render_category_charts(rows, base_month, current_month)
        table = pd.DataFrame({
            "Categoría": [row["category_label"] for row in rows],
            _month_label(base_month): [row["base"] for row in rows],
            _month_label(current_month): [row["current"] for row in rows],
            "Diferencia": [row["difference"] for row in rows],
        })
        st.dataframe(table, width="stretch", hide_index=True, column_config={
            _month_label(base_month): st.column_config.NumberColumn(format="$%.2f"),
            _month_label(current_month): st.column_config.NumberColumn(format="$%.2f"),
            "Diferencia": st.column_config.NumberColumn(format="$%+.2f"),
        })
    st.markdown("## En palabras simples")
    for finding in plain_language_findings(comparison, rows):
        st.markdown(f'<div class="simple-card">{finding}</div>', unsafe_allow_html=True)
    _render_cash_allocations(result)
    _render_transaction_review(result)
    _render_diagnostics(result)


def main():
    st.set_page_config(page_title="Mes a Mes", page_icon="↗", layout="wide", initial_sidebar_state="expanded")
    st.markdown(APP_CSS, unsafe_allow_html=True)
    initialize_session_state()
    _render_sidebar()
    st.markdown("""
        <div class="hero">
            <div class="hero-kicker">Tu dinero, sin complicaciones</div>
            <h1>Mes a Mes</h1>
            <p>Reúne tus estados de cuenta, entiende en qué gastaste y descubre exactamente qué cambió de un mes al siguiente.</p>
        </div>
    """, unsafe_allow_html=True)
    _render_upload_area()
    if st.session_state.analysis_result:
        display_results(st.session_state.analysis_result)
    st.caption("Herramienta educativa. Verifica los movimientos marcados para revisión antes de tomar decisiones financieras.")


if __name__ == "__main__":
    main()
