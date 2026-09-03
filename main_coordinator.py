"""
Main Coordinator: Orchestrates all 3 agents with deterministic routing
====================================================================

This is the main entry point for the entire system.
Uses deterministic if/else routing (NO LLM for routing decisions).

Coordinates:
- Agent 1: Document Processor (0 LLM calls)
- Agent 2: Content Analyzer (1 LLM call)  
- Agent 3: Analysis Generator (0-1 LLM calls)

Total system: ≤2 LLM calls per bank statement
"""

import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional
from dotenv import load_dotenv

# Import all agents
from agents.document_processor import DocumentProcessorAgent
from agents.content_analyzer import ContentAnalyzerAgent
from agents.analysis_generator import AnalysisGeneratorAgent
from utils.llm_interface import (
    DeterministicLLMInterface,
    LLMInterface,
    resolve_openai_api_key,
)
from utils.internal_transfers import (
    INTERNAL_TRANSFER_CATEGORY,
    capture_pre_transfer_state,
    set_automatic_transfer_detection,
)

class BankStatementAnalyzer:
    """
    Main coordinator using deterministic routing
    Follows exact project requirements for hybrid multi-agent system
    """
    
    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        deterministic_only: bool = False,
        category_model: str = "gpt-5.6",
        enable_ai_insights: bool = True,
        load_user_rules: Optional[bool] = None,
    ):
        """Initialize the complete 3-agent system"""
        
        print("🏦 INITIALIZING BANK STATEMENT ANALYZER")
        print("=" * 50)
        
        # Initialize centralized LLM interface
        self.deterministic_only = deterministic_only
        self.llm = (
            DeterministicLLMInterface()
            if deterministic_only
            else LLMInterface(openai_api_key, model=category_model)
        )

        if load_user_rules is None:
            load_user_rules = not deterministic_only
        
        # Initialize all 3 agents (following project architecture)
        self.agent1 = DocumentProcessorAgent(
            load_user_rules=load_user_rules
        )
        self.agent2 = ContentAnalyzerAgent(
            None if deterministic_only else self.llm,
            deterministic_only=deterministic_only,
        )
        self.agent3 = AnalysisGeneratorAgent(
            None if deterministic_only or not enable_ai_insights else self.llm
        )
        
        # System state tracking
        self.session_state = {
            'analyses_performed': 0,
            'total_llm_calls': 0,
            'total_cost': 0.0,
            'last_analysis': None
        }
        
        print(f"✅ All agents initialized successfully")
        print(f"⚠️  WARNING: Educational project only - do not use with real financial data")
        print("")
    
    def analyze_statement(self, pdf_path: str, generate_ai_insights: bool = False) -> Dict:
        """
        Main entry point: Complete bank statement analysis
        
        Uses deterministic routing (if/else logic, not LLM-based)
        
        Args:
            pdf_path: Path to bank statement PDF
            generate_ai_insights: Whether to use LLM for personalized advice
            
        Returns:
            Complete financial analysis results
        """

        single_statement = {
            'pdf_path': pdf_path,
            'metadata': {
                'file_name': os.path.basename(pdf_path),
                'document_type': 'bank_account',
                'person': 'default',
                'account_label': 'default',
            }
        }
        return self.analyze_statements([single_statement], generate_ai_insights=generate_ai_insights)

    def analyze_statements(self, statements: List[Dict], generate_ai_insights: bool = False) -> Dict:
        """Analyze multiple statements deterministically and return a consolidated result."""
        if not statements:
            return self._create_error_response("No statements were provided for analysis")

        # RESET LLM counters for this analysis batch
        self.llm.reset_counters()
        self.agent1.llm_calls_made = 0
        self.agent2.llm_calls_made = 0
        self.agent3.llm_calls_made = 0

        print("🚀 ANALYZING BANK STATEMENTS")
        print("=" * 50)
        print(f"📄 Documents: {len(statements)}")
        print(f"🤖 AI insights: {'Enabled' if generate_ai_insights else 'Disabled'}")
        print(f"🕐 Started: {datetime.now().strftime('%H:%M:%S')}")
        print("")

        all_transactions: List[Dict] = []
        document_results: List[Dict] = []
        document_debug: List[Dict] = []

        try:
            for index, statement in enumerate(statements, start=1):
                pdf_path = statement.get('pdf_path', '')
                metadata = statement.get('metadata', {}) or {}

                validation_result = self._validate_input(pdf_path)
                if not validation_result['valid']:
                    return self._create_error_response(f"Document {index} validation failed: {validation_result['error']}")

                print(f"{index}️⃣ AGENT 1: Document Processing - {os.path.basename(pdf_path)}")
                print("-" * 30)
                doc_result = self.agent1.process(pdf_path)

                if not doc_result['success']:
                    return self._create_error_response(
                        f"Document processing failed for {os.path.basename(pdf_path)}: {doc_result['error']}",
                        debug_info={'document_processing': doc_result}
                    )

                raw_transactions = doc_result.get('transactions', [])
                if len(raw_transactions) == 0:
                    return self._create_error_response(
                        f"No transactions found in {os.path.basename(pdf_path)}. The statement format may need additional parsing rules.",
                        debug_info={
                            'parsing_stats': doc_result.get('parsing_stats', {}),
                            'sample_transaction_lines': doc_result.get('raw_transaction_lines', [])[:10]
                        }
                    )
                if len(raw_transactions) > 2000:
                    return self._create_error_response(f"Too many transactions in {os.path.basename(pdf_path)} (>2000)")

                normalized_metadata = self._build_statement_metadata(pdf_path, raw_transactions, doc_result, metadata, index)
                normalized_transactions = self.normalize_transactions(raw_transactions, normalized_metadata)

                # Direction, dates, amounts and movement type are application-owned.
                # Classify them before the category agent so it receives context but
                # can never supply or change these values.
                for txn in normalized_transactions:
                    self.classify_transaction(txn)
                    txn['deterministic_category'] = txn.get('category') or 'uncategorized'
                    txn['deterministic_confidence'] = float(txn.get('confidence') or 0.0)
                    txn['deterministic_source'] = txn.get('source') or 'deterministic'

                print(f"\n{index}️⃣ AGENT 2: Smart Categorization")
                print("-" * 30)
                categorized_transactions = self.agent2.process(normalized_transactions)

                for txn in categorized_transactions:
                    self.classify_transaction(txn)
                    # Preserve the automatic financial classification for audit
                    # purposes. A later session-only custom choice replaces only
                    # the effective reporting category.
                    txn['detected_category'] = txn.get('category') or 'other'
                    txn['category_source'] = (
                        'agent_expert' if txn.get('source') == 'llm' else 'automatic'
                    )

                all_transactions.extend(categorized_transactions)
                document_results.append({
                    'document_id': normalized_metadata['document_id'],
                    'metadata': normalized_metadata,
                    'transactions': categorized_transactions,
                })
                document_debug.append({
                    'document_id': normalized_metadata['document_id'],
                    'file_name': normalized_metadata['file_name'],
                    'parsing_stats': doc_result.get('parsing_stats', {}),
                    'statement_profile': doc_result.get('statement_profile', ''),
                    'reconciliation': doc_result.get('reconciliation', {}),
                    'excluded_row_count': len(doc_result.get('excluded_rows', [])),
                    'sample_excluded_rows': doc_result.get('excluded_rows', [])[:10],
                    'sample_transaction_lines': doc_result.get('raw_transaction_lines', [])[:10],
                })

            merged_transactions = self.merge_statements(document_results)
            merged_transactions = self.detect_internal_transfers(merged_transactions)

            print("\n3️⃣ AGENT 3: Analysis Generation")
            print("-" * 30)
            final_analysis = self.agent3.process(
                merged_transactions,
                generate_ai_insights=generate_ai_insights
            )

            monthly_summary = self.aggregate_by_month(merged_transactions)
            monthly_trends = self.compute_monthly_trends(monthly_summary)

            total_llm_calls = (
                self.agent1.llm_calls_made +
                self.agent2.llm_calls_made +
                self.agent3.llm_calls_made
            )
            self._update_session_state(total_llm_calls)

            result = {
                'success': True,
                'analysis': final_analysis,
                'transactions': merged_transactions,
                'documents': [d['metadata'] for d in document_results],
                'document_results': document_results,
                'document_debug': document_debug,
                'monthly_summary': monthly_summary,
                'monthly_trends': monthly_trends,
                'multi_document': len(document_results) > 1,
                'system_metrics': {
                    'total_llm_calls': total_llm_calls,
                    'estimated_cost': self.llm.total_cost,
                    'category_model': getattr(self.llm, 'model', None),
                    'input_tokens': getattr(self.llm, 'input_tokens', 0),
                    'output_tokens': getattr(self.llm, 'output_tokens', 0),
                    'processing_time': datetime.now().isoformat(),
                    'agent_breakdown': {
                        'agent1_llm_calls': self.agent1.llm_calls_made,
                        'agent2_llm_calls': self.agent2.llm_calls_made,
                        'agent3_llm_calls': self.agent3.llm_calls_made
                    }
                },
                'session_state': self.session_state.copy()
            }

            self._print_final_results(result)
            return result

        except Exception as e:
            error_msg = f"System error during analysis: {str(e)}"
            print(f"❌ {error_msg}")
            return self._create_error_response(error_msg)

    def _build_statement_metadata(
        self,
        pdf_path: str,
        transactions: List[Dict],
        doc_result: Dict,
        metadata_hint: Dict,
        index: int,
    ) -> Dict:
        file_name = (
            str(metadata_hint.get('file_name') or '').strip()
            or os.path.basename(pdf_path)
        )
        detected_kind = doc_result.get('statement_kind')
        document_type = self._detect_document_type(
            file_name,
            metadata_hint.get('document_type') or detected_kind,
        )
        min_date, max_date = self._detect_statement_date_range(transactions)
        profile_code = re.sub(
            r'_(?:bank_account|credit_card)$',
            '',
            str(doc_result.get('statement_profile') or ''),
        )
        profile_labels = {
            'wells_fargo': 'Wells Fargo',
            'chase': 'Chase',
            'bank_of_america': 'Bank of America',
            'citi': 'Citi',
            'capital_one': 'Capital One',
            'american_express': 'American Express',
            'truist': 'Truist',
            'us_bank': 'U.S. Bank',
            'pnc': 'PNC',
            'td_bank': 'TD Bank',
            'santander': 'Santander',
            'scotiabank': 'Scotiabank',
            'bancoestado': 'BancoEstado',
            'bbva': 'BBVA',
            'bci': 'BCI',
            'itau': 'Itaú',
        }
        institution = self._detect_financial_institution(
            doc_result.get('raw_transaction_lines', []),
            file_name,
            metadata_hint.get('institution') or (
                profile_labels.get(profile_code)
            ),
        )

        person = (metadata_hint.get('person') or 'default').strip() or 'default'
        account_label = (metadata_hint.get('account_label') or f"account_{index}").strip() or f"account_{index}"
        if (
            metadata_hint.get('account_profile_inferred')
            and document_type == 'credit_card'
            and account_label in {'checking', 'savings', 'joint', 'other_account'}
        ):
            account_label = 'credit_card_primary'
        document_id = f"doc_{index}_{re.sub(r'[^a-z0-9]+', '_', file_name.lower()).strip('_')}"

        return {
            'document_id': document_id,
            'file_name': file_name,
            'pdf_path': pdf_path,
            'document_type': document_type,
            'person': person,
            'account_label': account_label,
            'institution': institution,
            'statement_profile': doc_result.get('statement_profile', 'generic_bank_account'),
            'reconciliation': doc_result.get('reconciliation', {}),
            'date_range': {
                'start': min_date,
                'end': max_date,
            },
            'provided_metadata': metadata_hint,
        }

    def _detect_document_type(self, file_name: str, hint: Optional[str] = None) -> str:
        allowed = {'bank_account', 'credit_card', 'other'}
        if hint in allowed:
            return hint

        lower = file_name.lower()
        if any(token in lower for token in ['card', 'tarjeta', 'visa', 'mastercard', 'amex']):
            return 'credit_card'
        if any(token in lower for token in ['statement', 'cartola', 'checking', 'savings', 'banco']):
            return 'bank_account'
        return 'other'

    def _detect_financial_institution(self, lines: List[str], file_name: str, hint: Optional[str] = None) -> str:
        if hint:
            return hint

        candidates = {
            'chase': 'Chase',
            'wells fargo': 'Wells Fargo',
            'bank of america': 'Bank of America',
            'citibank': 'Citi',
            'citi': 'Citi',
            'capital one': 'Capital One',
            'american express': 'American Express',
            'amex': 'American Express',
            'truist': 'Truist',
            'u.s. bank': 'U.S. Bank',
            'us bank': 'U.S. Bank',
            'pnc': 'PNC',
            'td bank': 'TD Bank',
            'santander': 'Santander',
            'bbva': 'BBVA',
            'bci': 'BCI',
            'scotiabank': 'Scotiabank',
            'itau': 'Itaú',
            'bancoestado': 'BancoEstado',
        }
        text = "\n".join(lines[:40]).lower() + "\n" + file_name.lower()
        for key, institution in candidates.items():
            if key in text:
                return institution
        return 'unknown'

    def _detect_statement_date_range(self, transactions: List[Dict]) -> tuple[str, str]:
        valid_dates = []
        for txn in transactions:
            date_text = str(txn.get('date') or '').strip()
            try:
                dt = datetime.strptime(date_text, '%Y-%m-%d')
                valid_dates.append(dt)
            except Exception:
                continue

        if not valid_dates:
            return '', ''

        min_date = min(valid_dates).strftime('%Y-%m-%d')
        max_date = max(valid_dates).strftime('%Y-%m-%d')
        return min_date, max_date

    def normalize_transactions(self, raw_transactions: List[Dict], metadata: Dict) -> List[Dict]:
        """Normalize transactions into a unified schema while preserving document traceability."""
        normalized: List[Dict] = []
        for idx, txn in enumerate(raw_transactions, start=1):
            normalized_txn = dict(txn)
            normalized_txn['source_document_id'] = metadata['document_id']
            normalized_txn['source_file_name'] = metadata['file_name']
            normalized_txn['document_type'] = metadata['document_type']
            normalized_txn['person'] = metadata['person']
            normalized_txn['account_label'] = metadata['account_label']
            normalized_txn['institution'] = metadata['institution']
            normalized_txn['statement_profile'] = metadata.get('statement_profile', '')
            normalized_txn['statement_date_start'] = metadata['date_range']['start']
            normalized_txn['statement_date_end'] = metadata['date_range']['end']
            normalized_txn['local_txn_id'] = txn.get('transaction_id') or f"txn_{idx}"
            normalized_txn['transaction_id'] = f"{metadata['document_id']}::{normalized_txn['local_txn_id']}"
            direction_known = bool(txn.get('direction_known', True))
            normalized_txn['direction_known'] = direction_known
            normalized_txn['effective_is_spending'] = (
                direction_known and bool(txn.get('is_debit', False))
            )
            normalized_txn['effective_is_income'] = (
                direction_known and not bool(txn.get('is_debit', False))
            )
            normalized_txn['excluded_from_totals'] = not direction_known
            if not direction_known:
                normalized_txn['exclusion_reason'] = 'Transaction direction is unresolved'

            date_text = str(txn.get('date') or '').strip()
            normalized_txn['month'] = date_text[:7] if len(date_text) >= 7 else 'unknown'

            normalized.append(normalized_txn)
        return normalized

    def classify_transaction(self, transaction: Dict) -> Dict:
        """Assign deterministic movement tags, especially for credit card statements."""
        desc = str(transaction.get('description') or '').lower()
        is_debit = bool(transaction.get('is_debit', False))
        doc_type = transaction.get('document_type', 'other')

        if not transaction.get('direction_known', True):
            transaction['movement_type'] = 'unknown_direction'
            transaction['effective_is_spending'] = False
            transaction['effective_is_income'] = False
            return transaction

        movement_type = 'other'
        if doc_type == 'credit_card':
            if is_debit:
                if any(k in desc for k in ['interest', 'interes', 'interés']):
                    movement_type = 'card_interest'
                    transaction['category'] = 'fees' if transaction.get('category') == 'uncategorized' else transaction.get('category')
                elif any(k in desc for k in ['fee', 'cargo', 'comision', 'comisión', 'late payment', 'maintenance']):
                    movement_type = 'card_fee'
                    transaction['category'] = 'fees' if transaction.get('category') == 'uncategorized' else transaction.get('category')
                else:
                    movement_type = 'card_purchase'
            else:
                if any(k in desc for k in ['payment', 'pago', 'abono', 'transferencia']):
                    movement_type = 'card_payment'
                elif any(k in desc for k in ['refund', 'reversal', 'devolucion', 'devolución', 'credito', 'crédito']):
                    movement_type = 'card_refund'
                else:
                    movement_type = 'card_credit'
        else:
            if is_debit and any(k in desc for k in ['payment', 'pago', 'tarjeta', 'credit card', 'tc']):
                movement_type = 'possible_card_payment'
            elif (not is_debit) and any(k in desc for k in [
                'online transfer from',
                'transfer from',
                'deposit',
                'direct deposit',
                'salary',
                'payroll',
                'refund',
                'interest',
                'abono',
                'credito',
                'crédito',
                'ingreso',
                'transferencia recibida',
                'devolucion',
                'devolución',
            ]):
                movement_type = 'income_credit'
                transaction['effective_is_spending'] = False
                transaction['effective_is_income'] = True
                if transaction.get('category') in {'uncategorized', 'other'}:
                    transaction['category'] = 'income'
            elif not is_debit and any(k in desc for k in ['salary', 'nomina', 'nómina', 'deposit', 'abono']):
                movement_type = 'income_credit'
            elif is_debit and transaction.get('category') == 'fees':
                movement_type = 'bank_fee'
            else:
                movement_type = 'bank_movement'

        transaction['movement_type'] = movement_type
        return transaction

    def merge_statements(self, statement_results: List[Dict]) -> List[Dict]:
        """Merge already-normalized per-document transactions in deterministic order."""
        merged = []
        for doc in statement_results:
            merged.extend(doc.get('transactions', []))

        def sort_key(txn: Dict):
            return (
                str(txn.get('date') or ''),
                str(txn.get('source_document_id') or ''),
                str(txn.get('local_txn_id') or ''),
            )

        return sorted(merged, key=sort_key)

    def detect_internal_transfers(self, transactions: List[Dict]) -> List[Dict]:
        """Detect likely internal transfers without overwriting user corrections."""
        card_purchases_by_person_month = defaultdict(float)

        for txn in transactions:
            if txn.get('document_type') == 'credit_card' and txn.get('movement_type') == 'card_purchase':
                key = (txn.get('person') or 'default', txn.get('month') or 'unknown')
                card_purchases_by_person_month[key] += float(txn.get('amount') or 0.0)

        detections = [False] * len(transactions)
        reasons: List[List[str]] = [[] for _ in transactions]

        for txn in transactions:
            capture_pre_transfer_state(txn)

        for index, txn in enumerate(transactions):

            desc = str(txn.get('description') or '').lower()
            month = txn.get('month') or 'unknown'
            person = txn.get('person') or 'default'

            if txn.get('category') == INTERNAL_TRANSFER_CATEGORY:
                detections[index] = True
                reasons[index].append(
                    'Classified as a transfer between the user\'s own accounts'
                )

            if txn.get('movement_type') == 'possible_card_payment' and txn.get('is_debit'):
                paid_amount = float(txn.get('amount') or 0.0)
                monthly_card_spend = card_purchases_by_person_month.get((person, month), 0.0)

                if monthly_card_spend > 0:
                    ratio = paid_amount / monthly_card_spend if monthly_card_spend else 0.0
                    if 0.60 <= ratio <= 1.40:
                        detections[index] = True
                        reasons[index].append(
                            f"Possible card payment matched to purchases for {month} "
                            f"(payment={paid_amount:.2f}, purchases={monthly_card_spend:.2f})"
                        )

            if txn.get('document_type') == 'credit_card' and txn.get('movement_type') == 'card_payment' and not txn.get('is_debit'):
                detections[index] = True
                reasons[index].append(
                    'Credit-card payment credit, excluded from income'
                )

            explicit_internal_markers = [
                'internal transfer',
                'between my accounts',
                'own account',
                'transfer to my account',
                'transfer from my account',
                'online transfer to',
                'online transfer from',
                'online banking transfer to',
                'online banking transfer from',
                'online scheduled transfer to',
                'online scheduled transfer from',
                'transfer to checking',
                'transfer from checking',
                'transfer to savings',
                'transfer from savings',
                'traspaso propio',
                'traspaso entre cuentas',
                'transferencia entre mis cuentas',
                'transferencia a cuenta propia',
                'transferencia desde cuenta propia',
            ]
            if any(marker in desc for marker in explicit_internal_markers):
                detections[index] = True
                reasons[index].append(
                    'The description explicitly indicates an internal transfer'
                )

        self._detect_matching_transfer_pairs(transactions, detections, reasons)

        for index, txn in enumerate(transactions):
            set_automatic_transfer_detection(
                txn,
                detections[index],
                '; '.join(dict.fromkeys(reasons[index])),
            )

        return transactions

    def _detect_matching_transfer_pairs(
        self,
        transactions: List[Dict],
        detections: List[bool],
        reasons: List[List[str]],
    ) -> None:
        """Match opposite movements using account, amount, date and text evidence."""
        generic_markers = ('transfer', 'transferencia', 'traspaso', 'xfer')
        international_markers = ('international', 'internacional', 'swift', 'wire')
        movement_markers = (
            'ach', 'deposit', 'withdrawal', 'online banking', 'zelle', 'venmo',
            'cash transfer', 'abono', 'retiro', 'cargo cuenta',
        )
        external_income_markers = (
            'salary', 'payroll', 'nomina', 'nómina', 'refund', 'reembolso',
            'interest', 'dividend', 'pension', 'pensión',
        )
        candidates = []

        for left_index, left in enumerate(transactions):
            for right_index in range(left_index + 1, len(transactions)):
                right = transactions[right_index]
                if not left.get('direction_known', True) or not right.get('direction_known', True):
                    continue
                if bool(left.get('is_debit')) == bool(right.get('is_debit')):
                    continue
                if left.get('source_document_id') == right.get('source_document_id'):
                    continue
                # Several monthly PDFs may belong to one account. Opposite
                # movements across those documents are not transfers between
                # accounts and must never be auto-paired.
                left_account = str(left.get('account_label') or '').strip()
                right_account = str(right.get('account_label') or '').strip()
                if left_account and right_account and left_account == right_account:
                    continue
                if (left.get('person') or 'default') != (right.get('person') or 'default'):
                    continue
                left_currency = left.get('currency') or 'unknown'
                right_currency = right.get('currency') or 'unknown'
                if left_currency != right_currency:
                    continue
                if abs(float(left.get('amount') or 0.0) - float(right.get('amount') or 0.0)) > 0.01:
                    continue

                descriptions = (
                    str(left.get('description') or '').lower(),
                    str(right.get('description') or '').lower(),
                )
                combined = ' '.join(descriptions)
                if any(marker in combined for marker in international_markers):
                    continue

                try:
                    left_date = datetime.strptime(str(left.get('date') or ''), '%Y-%m-%d')
                    right_date = datetime.strptime(str(right.get('date') or ''), '%Y-%m-%d')
                except ValueError:
                    continue

                date_gap = abs((left_date - right_date).days)
                if date_gap > 3:
                    continue

                generic_count = sum(
                    any(marker in description for marker in generic_markers)
                    for description in descriptions
                )
                movement_count = sum(
                    any(marker in description for marker in movement_markers)
                    for description in descriptions
                )
                left_refs = set(re.findall(r'\b\d{4,}\b', descriptions[0]))
                right_refs = set(re.findall(r'\b\d{4,}\b', descriptions[1]))
                shared_reference = bool(left_refs & right_refs)
                external_income = any(
                    marker in combined for marker in external_income_markers
                )

                accepted = (
                    generic_count >= 1
                    or shared_reference
                    or (
                        movement_count == 2
                        and date_gap <= 1
                        and not external_income
                    )
                )
                if not accepted:
                    continue

                score = (
                    generic_count * 3
                    + movement_count
                    + (3 if shared_reference else 0)
                    - date_gap * 0.25
                )
                candidates.append((-score, date_gap, left_index, right_index))

        matched = set()
        pair_number = 0
        for negative_score, date_gap, left_index, right_index in sorted(candidates):
            if left_index in matched or right_index in matched:
                continue
            matched.update((left_index, right_index))
            pair_number += 1
            pair_id = f'internal_transfer_pair_{pair_number}'
            reason = (
                'Opposite account movements with the same amount '
                f'within {date_gap} day(s); evidence score={-negative_score:.2f}'
            )
            for index in (left_index, right_index):
                detections[index] = True
                reasons[index].append(reason)
                transactions[index]['transfer_pair_id'] = pair_id
                transactions[index]['transfer_match_score'] = -negative_score

    def aggregate_by_month(self, transactions: List[Dict]) -> List[Dict]:
        monthly = {}
        for txn in transactions:
            month = txn.get('month') or 'unknown'
            bucket = monthly.setdefault(month, {
                'month': month,
                'total_spent': 0.0,
                'total_income': 0.0,
                'net_change': 0.0,
                'transaction_count': 0,
                'spending_transactions': 0,
                'income_transactions': 0,
                'by_category': {},
            })

            amount = float(txn.get('amount') or 0.0)
            category = txn.get('category') or 'other'
            bucket['transaction_count'] += 1

            if txn.get('is_debit') and txn.get('effective_is_spending', True):
                bucket['total_spent'] += amount
                bucket['spending_transactions'] += 1
                bucket['by_category'][category] = bucket['by_category'].get(category, 0.0) + amount
            elif (not txn.get('is_debit')) and txn.get('effective_is_income', True):
                bucket['total_income'] += amount
                bucket['income_transactions'] += 1

        rows = []
        for month in sorted(monthly.keys()):
            row = monthly[month]
            row['net_change'] = row['total_income'] - row['total_spent']
            rows.append(row)
        return rows

    def compute_monthly_trends(self, monthly_summary: List[Dict], threshold: float = 0.08) -> Dict:
        if len(monthly_summary) < 2:
            return {
                'classification': 'insufficient_data',
                'threshold': threshold,
                'changes': [],
                'details': 'At least two months are required for trend analysis.'
            }

        changes = []
        for idx in range(1, len(monthly_summary)):
            prev = monthly_summary[idx - 1]
            curr = monthly_summary[idx]
            prev_spent = float(prev.get('total_spent') or 0.0)
            curr_spent = float(curr.get('total_spent') or 0.0)
            if prev_spent <= 0:
                pct_change = 0.0
            else:
                pct_change = (curr_spent - prev_spent) / prev_spent

            changes.append({
                'from_month': prev.get('month'),
                'to_month': curr.get('month'),
                'pct_change': pct_change,
                'direction': 'up' if pct_change > 0 else 'down' if pct_change < 0 else 'flat',
            })

        up_streak = 0
        down_streak = 0
        max_up_streak = 0
        max_down_streak = 0
        stable_count = 0

        for change in changes:
            pct = change['pct_change']
            if pct >= threshold:
                up_streak += 1
                down_streak = 0
            elif pct <= -threshold:
                down_streak += 1
                up_streak = 0
            else:
                stable_count += 1
                up_streak = 0
                down_streak = 0

            max_up_streak = max(max_up_streak, up_streak)
            max_down_streak = max(max_down_streak, down_streak)

        if max_up_streak >= 2:
            classification = 'uptrend'
            details = f'Spending increased by more than {threshold*100:.1f}% for at least two consecutive month-over-month intervals.'
        elif max_down_streak >= 2:
            classification = 'downtrend'
            details = f'Spending decreased by more than {threshold*100:.1f}% for at least two consecutive month-over-month intervals.'
        elif stable_count == len(changes):
            classification = 'stable'
            details = 'Month-over-month spending stayed within the configured variation range.'
        else:
            classification = 'irregular'
            details = 'High variation exists without a consistent directional pattern.'

        return {
            'classification': classification,
            'threshold': threshold,
            'changes': changes,
            'details': details,
        }
    
    def _validate_input(self, pdf_path: str) -> Dict:
        """Deterministic input validation"""
        
        # Check file exists
        if not os.path.exists(pdf_path):
            return {'valid': False, 'error': f"File not found: {pdf_path}"}
        
        # Check file extension
        if not pdf_path.lower().endswith('.pdf'):
            return {'valid': False, 'error': "Only PDF files are supported"}
        
        # Check file size (basic validation)
        try:
            file_size = os.path.getsize(pdf_path)
            if file_size > 10 * 1024 * 1024:  # 10MB limit
                return {'valid': False, 'error': "File too large (>10MB)"}
            elif file_size == 0:
                return {'valid': False, 'error': "File is empty"}
        except:
            return {'valid': False, 'error': "Cannot access file"}
        
        return {'valid': True}
    
    def _create_error_response(self, error_message: str, debug_info: Optional[Dict] = None) -> Dict:
        """Standardized error response"""
        response = {
            'success': False,
            'error': error_message,
            'system_metrics': {
                'total_llm_calls': 0,
                'estimated_cost': 0.0,
                'agent_breakdown': {
                    'agent1_llm_calls': 0,
                    'agent2_llm_calls': 0, 
                    'agent3_llm_calls': 0
                }
            }
        }
        if debug_info:
            response['debug_info'] = debug_info
        return response
    
    def _update_session_state(self, llm_calls_used: int):
        """Update session tracking"""
        self.session_state['analyses_performed'] += 1
        self.session_state['total_llm_calls'] += llm_calls_used
        self.session_state['total_cost'] += self.llm.total_cost
        self.session_state['last_analysis'] = datetime.now().isoformat()
    
    def _print_final_results(self, result: Dict):
        """Print beautiful final summary"""
        metrics = result['system_metrics']
        analysis = result['analysis']
        summary = analysis['financial_summary']
        
        print(f"\n🎉 ANALYSIS COMPLETE!")
        print("=" * 50)
        print(f"💰 Total Spent: ${summary['total_spent']:.2f}")
        print(f"💵 Total Income: ${summary['total_income']:.2f}")
        print(f"📊 Net Change: ${summary['net_change']:.2f}")
        print(f"🤖 LLM Calls Used: {metrics['total_llm_calls']}/2")
        print(f"💵 Cost: ${metrics['estimated_cost']:.4f}")
        
        if analysis['category_breakdown']:
            top_category = analysis['category_breakdown'][0]
            print(f"🏆 Top Category: {top_category['category']} ({top_category['percentage']:.1f}%)")
        
        print("=" * 50)
    
    def get_system_status(self) -> Dict:
        """Get current system status and metrics"""
        return {
            'agents_initialized': True,
            'session_state': self.session_state.copy(),
            'current_llm_usage': self.llm.get_metrics(),
            'agent_status': {
                'agent1': self.agent1.get_metrics(),
                'agent2': self.agent2.get_metrics(),
                'agent3': self.agent3.get_metrics()
            }
        }

# Command Line Interface (for non-UI usage)
def main_cli():
    """Command line interface for the system"""
    
    # Load API key
    load_dotenv()
    api_key = resolve_openai_api_key()
    
    if not api_key:
        print("❌ Please set OPENAI_API_KEY in .env file or Streamlit Secrets")
        return
    
    # Initialize system
    analyzer = BankStatementAnalyzer(api_key)
    
    while True:
        print(f"\n{'='*60}")
        print("🏦 BANK STATEMENT ANALYZER - CLI")
        print('='*60)
        print("1. Analyze statement (basic)")
        print("2. Analyze statement (with AI insights)")
        print("3. View system status")
        print("4. Exit")
        
        choice = input("\nSelect option (1-4): ").strip()
        
        if choice == '1':
            pdf_path = input("Enter PDF file path: ").strip()
            result = analyzer.analyze_statement(pdf_path, generate_ai_insights=False)
            
        elif choice == '2':
            pdf_path = input("Enter PDF file path: ").strip()
            result = analyzer.analyze_statement(pdf_path, generate_ai_insights=True)
            
        elif choice == '3':
            status = analyzer.get_system_status()
            print(f"\n📊 SYSTEM STATUS:")
            print(f"   Analyses performed: {status['session_state']['analyses_performed']}")
            print(f"   Total LLM calls: {status['session_state']['total_llm_calls']}")
            print(f"   Total cost: ${status['session_state']['total_cost']:.4f}")
            
        elif choice == '4':
            print("👋 Goodbye!")
            break
            
        else:
            print("❌ Invalid choice")

if __name__ == "__main__":
    main_cli()
