import pdfplumber
import re
import unicodedata
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from .base_agent import BaseAgent
from utils.merchant_database import MerchantDatabase

class DocumentProcessorAgent(BaseAgent):
    """
    Agent 1: Pure deterministic document processing
    NO LLM CALLS - extracts and parses transaction data
    """

    def __init__(self, load_user_rules: bool = True):
        super().__init__("Document Processor", uses_llm=False)
        self.merchant_db = MerchantDatabase(load_user_rules=load_user_rules)
        self._statement_date_range_hint: Optional[Tuple[datetime, datetime]] = None
        self._opening_balance_hint: Optional[float] = None
        self._closing_balance_hint: Optional[float] = None
        self._statement_profile = 'generic_bank_account'
        self._statement_kind = 'bank_account'
        self._last_excluded_rows: List[Dict] = []
        print(f"🏗️ {self.name} initialized - 0 LLM calls")

    def process(self, pdf_path: str) -> Dict:
        """Main entry point: PDF → Structured transaction data"""
        print(f"\n📄 {self.name} processing: {pdf_path}")
        
        try:
            # Step 1: Extract raw text
            raw_text = self._extract_text_from_pdf(pdf_path)
            
            if not raw_text.strip():
                return {'success': False, 'error': 'No text in PDF', 'transactions': []}

            self._statement_date_range_hint = self._infer_statement_date_range(raw_text)
            self._opening_balance_hint, self._closing_balance_hint = (
                self._infer_statement_balance_hints(raw_text)
            )
            self._statement_profile, self._statement_kind = (
                self._infer_statement_profile(raw_text, pdf_path)
            )
            
            print(f"   ✅ Extracted {len(raw_text)} characters")
            
            # Step 2: Find transaction lines
            transaction_lines = self._find_transaction_lines(raw_text)
            
            if not transaction_lines:
                return {
                    'success': True, 
                    'transactions': [],
                    'raw_text': raw_text,
                    'message': 'No transaction lines found - might need different parsing approach'
                }
            
            # NEW Step 3: Parse transaction lines into structured data
            parsed_transactions = self._parse_transaction_lines(transaction_lines)
            reconciliation = self._reconcile_transaction_directions(parsed_transactions)
            
            categorized_transactions = self._apply_basic_categorization(parsed_transactions)

            return {
                'success': True,
                'transactions': categorized_transactions,  # Changed from parsed_transactions
                'total_transactions': len(categorized_transactions),
                'raw_transaction_lines': [
                    item.get('text', '') if isinstance(item, dict) else str(item)
                    for item in transaction_lines
                ],
                'excluded_rows': list(self._last_excluded_rows),
                'statement_profile': self._statement_profile,
                'statement_kind': self._statement_kind,
                'balance_hints': {
                    'opening': self._opening_balance_hint,
                    'closing': self._closing_balance_hint,
                },
                'reconciliation': reconciliation,
                'parsing_stats': {
                    'lines_found': len(transaction_lines),
                    'successfully_parsed': len(parsed_transactions),
                    'parse_success_rate': len(parsed_transactions) / len(transaction_lines) if transaction_lines else 0,
                    'categorized_deterministically': len([t for t in categorized_transactions if t['category'] != 'uncategorized']),
                    'needs_llm': len([t for t in categorized_transactions if t['category'] == 'uncategorized'])
                }
            }

            
        except Exception as e:
            return {'success': False, 'error': str(e), 'transactions': []}
        
    def _extract_text_from_pdf(self, pdf_path: str) -> str:
        """
        Enhanced PDF extraction - handles both text and tables
        """
        full_text = ""
        
        with pdfplumber.open(pdf_path) as pdf:
            print(f"   📖 PDF has {len(pdf.pages)} pages")
            
            for page_num, page in enumerate(pdf.pages, 1):
                print(f"   📄 Processing page {page_num}...")
                
                # Method 1: Try table extraction first (for structured data)
                tables = page.extract_tables()
                if tables:
                    print(f"   📊 Found {len(tables)} tables on page {page_num}")
                    
                    for table_num, table in enumerate(tables, 1):
                        full_text += f"\n--- PAGE {page_num} TABLE {table_num} ---\n"
                        
                        for row_num, row in enumerate(table):
                            if row and any(cell for cell in row if cell and str(cell).strip()):
                                # Join non-empty cells with tabs
                                row_text = '\t'.join(str(cell).strip() if cell else '' for cell in row)
                                full_text += f"ROW_{row_num}: {row_text}\n"
                        
                        full_text += f"--- END TABLE {table_num} ---\n"
                
                # Method 2: Regular text extraction as backup
                # Preserve horizontal spacing so debit/credit columns remain
                # distinguishable even when pdfplumber cannot extract a table.
                page_text = page.extract_text(layout=True)
                if page_text:
                    full_text += f"\n--- PAGE {page_num} TEXT ---\n"
                    full_text += page_text
                    full_text += f"\n--- END PAGE {page_num} TEXT ---\n"
                
                # Method 3: Character-level extraction for stubborn PDFs
                if not tables and not page_text:
                    print(f"   ⚠️  Trying character-level extraction...")
                    chars = page.chars
                    if chars:
                        full_text += f"\n--- PAGE {page_num} CHARS ---\n"
                        for char in chars[:100]:  # First 100 characters for debugging
                            full_text += char.get('text', '')
                        full_text += f"\n--- END CHARS ---\n"
            
            return full_text
    
    def _find_transaction_lines(self, text: str) -> List[Dict]:
        """
        Find transaction lines while retaining page, extraction source, and
        statement-section context.

        Page text is preferred when available. Table rows are used only as a
        fallback for pages whose text layer yields no transactions. This avoids
        counting the same transaction once from a table and again from text,
        while preserving legitimate repeated rows within the selected source.
        """
        self._last_excluded_rows = []
        page_text_blocks: Dict[int, str] = {}
        page_table_blocks: Dict[int, List[str]] = {}

        for match in re.finditer(
            r'--- PAGE (\d+) TEXT ---\s*(.*?)\s*--- END PAGE \1 TEXT ---',
            text,
            re.DOTALL,
        ):
            page_text_blocks[int(match.group(1))] = match.group(2)

        for match in re.finditer(
            r'--- PAGE (\d+) TABLE \d+ ---\s*(.*?)\s*--- END TABLE \d+ ---',
            text,
            re.DOTALL,
        ):
            page_table_blocks.setdefault(int(match.group(1)), []).append(match.group(2))

        has_transaction_marker = any(
            marker in text.lower()
            for marker in ('transaction detail', 'detail de transacciones')
        )
        scan_enabled = not has_transaction_marker
        current_section: Optional[str] = None
        current_section_label = ''
        potential_transactions: List[Dict] = []

        if page_text_blocks or page_table_blocks:
            pages = sorted(set(page_text_blocks) | set(page_table_blocks))
            total_lines = sum(
                len(page_text_blocks.get(page, '').splitlines())
                for page in pages
            )
            print(f"   🔍 Scanning {total_lines} page-text lines for transactions...")

            for page_num in pages:
                page_start_section = current_section
                page_start_label = current_section_label
                page_start_enabled = scan_enabled

                text_candidates, current_section, current_section_label, scan_enabled = (
                    self._scan_transaction_block(
                        page_text_blocks.get(page_num, ''),
                        page_num=page_num,
                        source='page_text',
                        current_section=current_section,
                        current_section_label=current_section_label,
                        scan_enabled=scan_enabled,
                    )
                )

                if text_candidates:
                    potential_transactions.extend(text_candidates)
                    continue

                table_candidates: List[Dict] = []
                table_section = page_start_section
                table_label = page_start_label
                table_enabled = page_start_enabled
                for table_text in page_table_blocks.get(page_num, []):
                    found, table_section, table_label, table_enabled = (
                        self._scan_transaction_block(
                            table_text,
                            page_num=page_num,
                            source='table',
                            current_section=table_section,
                            current_section_label=table_label,
                            scan_enabled=table_enabled,
                        )
                    )
                    table_candidates.extend(found)
                potential_transactions.extend(table_candidates)
        else:
            print(f"   🔍 Scanning {len(text.splitlines())} lines for transactions...")
            found, _, _, _ = self._scan_transaction_block(
                text,
                page_num=None,
                source='plain_text',
                current_section=None,
                current_section_label='',
                scan_enabled=scan_enabled,
            )
            potential_transactions.extend(found)

        print(f"   📊 Found {len(potential_transactions)} potential transaction lines")
        return potential_transactions

    def _scan_transaction_block(
        self,
        block_text: str,
        page_num: Optional[int],
        source: str,
        current_section: Optional[str],
        current_section_label: str,
        scan_enabled: bool,
    ) -> Tuple[List[Dict], Optional[str], str, bool]:
        """Scan one ordered text block and carry section state forward."""
        candidates: List[Dict] = []
        column_layout: Optional[Dict[str, int]] = None

        for line_num, raw_line in enumerate(block_text.splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue

            line_lower = line.lower()
            if 'transaction detail' in line_lower or 'detail de transacciones' in line_lower:
                scan_enabled = True
                print(f"   📍 Found transaction block on page {page_num or '?'}")

            section_event = self._detect_section_event(line)
            if section_event:
                event_type, section_code, section_label = section_event
                if event_type == 'end':
                    current_section = None
                    current_section_label = ''
                else:
                    current_section = section_code
                    current_section_label = section_label
                continue

            if not scan_enabled:
                continue

            detected_layout = self._detect_column_layout(line)
            if detected_layout:
                column_layout = detected_layout

            row_type = self._classify_non_transaction_row(line)
            if row_type:
                if self._line_has_date_and_amount(line) or row_type in {
                    'opening_balance', 'closing_balance', 'aggregate'
                }:
                    self._last_excluded_rows.append({
                        'text': line,
                        'row_type': row_type,
                        'page': page_num,
                        'source': source,
                        'source_line_number': line_num,
                    })
                continue
            if not self._looks_like_transaction(line):
                continue

            candidates.append({
                'text': line,
                'page': page_num,
                'source': source,
                'statement_section': current_section,
                'section_label': current_section_label,
                'source_line_number': line_num,
                'column_direction': self._infer_direction_from_columns(
                    line, column_layout
                ),
            })
            print(
                f"   ✅ Page {page_num or '?'} line {line_num}: "
                f"{line[:50]}..."
            )

        return candidates, current_section, current_section_label, scan_enabled

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Normalize labels without altering the original transaction text."""
        decomposed = unicodedata.normalize('NFKD', str(value or ''))
        ascii_text = ''.join(ch for ch in decomposed if not unicodedata.combining(ch))
        return re.sub(r'\s+', ' ', ascii_text).strip().casefold()

    def _classify_non_transaction_row(self, line: str) -> Optional[str]:
        """Classify headers and aggregates before transaction parsing.

        Rules are anchored to the row label so legitimate descriptions such as
        ``Transfer to savings account`` are not discarded merely because they
        contain the word ``account``.
        """
        cleaned = re.sub(r'^ROW_\d+:\s*', '', line, flags=re.IGNORECASE).strip()
        normalized = self._normalize_text(cleaned)
        normalized = re.sub(
            r'^\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,4})?\s+', '', normalized
        )
        label = normalized.lstrip('-:| ')

        if re.match(
            r'^(?:your\s+)?(?:beginning|opening|previous|starting) balance\b|'
            r'^(?:saldo inicial|saldo anterior|balance inicial)\b',
            label,
        ):
            return 'opening_balance'
        if re.match(
            r'^(?:your\s+)?(?:ending|closing|new|current) balance\b|'
            r'^(?:saldo final|saldo de cierre|balance final)\b',
            label,
        ):
            return 'closing_balance'
        if re.match(
            r'^(?:total|subtotal|summary|resumen|totales|average daily balance|'
            r'promedio de saldo)\b',
            label,
        ):
            return 'aggregate'

        header_patterns = [
            r'^(?:date|fecha)\s+(?:transaction )?(?:description|descripcion)',
            r'^(?:account transactions|transaction history|account activity|'
            r'transaction detail|detalle de transacciones)$',
            r'^(?:account|statement|balance information|statement period|issue date)\s*:',
            r'^(?:cartola|cuenta|periodo|periodo de cartola)\s*:',
            r'^(?:page|pagina)\s+\d+\b',
            r'^(?:paid in|paid out|payment type|account holder)\b',
            r'^(?:note|nota)\s*:',
            r'^[-=_]+$',
        ]
        if any(re.search(pattern, label) for pattern in header_patterns):
            return 'header_footer'
        return None

    def _line_has_date_and_amount(self, line: str) -> bool:
        return bool(
            re.search(
                r'\b(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|'
                r'\d{4}[/-]\d{1,2}[/-]\d{1,2})\b',
                line,
            )
            and re.search(self._amount_pattern(), line)
        )

    def _detect_column_layout(self, line: str) -> Optional[Dict[str, int]]:
        """Capture debit/credit column positions from a table header."""
        normalized = self._normalize_text(line)
        if not re.search(r'\b(?:date|fecha)\b', normalized):
            return None

        aliases = {
            'debit': ('withdrawals', 'withdrawal', 'debits', 'debit', 'cargos', 'cargo', 'retiros', 'retiro'),
            'credit': ('deposits', 'deposit', 'credits', 'credit', 'abonos', 'abono', 'ingresos', 'ingreso'),
            'balance': ('balance', 'saldo'),
        }
        positions: Dict[str, int] = {}
        decomposed = unicodedata.normalize('NFKD', str(line or ''))
        lower_line = ''.join(
            ch for ch in decomposed if not unicodedata.combining(ch)
        ).casefold()
        for field, names in aliases.items():
            found = [lower_line.find(name) for name in names if lower_line.find(name) >= 0]
            if found:
                positions[field] = min(found)
        if 'debit' in positions and 'credit' in positions:
            return positions
        return None

    def _infer_direction_from_columns(
        self, line: str, column_layout: Optional[Dict[str, int]]
    ) -> Optional[str]:
        if not column_layout:
            return None
        date_match = re.search(
            r'\b(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|'
            r'\d{4}[/-]\d{1,2}[/-]\d{1,2})\b',
            line,
        )
        if not date_match:
            return None
        amount_matches = list(re.finditer(self._amount_pattern(), line[date_match.end():]))
        if not amount_matches:
            return None
        transaction_match = amount_matches[-2] if len(amount_matches) >= 2 else amount_matches[0]
        amount_position = date_match.end() + transaction_match.start()
        choices = [
            (abs(amount_position - position), direction)
            for direction, position in column_layout.items()
            if direction in {'debit', 'credit'}
        ]
        return min(choices)[1] if choices else None

    def _detect_section_event(self, line: str) -> Optional[Tuple[str, Optional[str], str]]:
        """Recognize deterministic credit/debit section boundaries."""
        normalized = re.sub(r'^ROW_\d+:\s*', '', line, flags=re.IGNORECASE)
        normalized = re.sub(r'^[^A-Za-zÀ-ÿ]+', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip().rstrip(':').casefold()

        if normalized.startswith('total'):
            total_label = re.sub(
                r'\s*(?:=)?\s*\$?[\d.,]+\s*$',
                '',
                normalized[5:].lstrip(),
            ).strip()
            if self._matches_credit_section_header(total_label):
                return ('end', None, '')
            if self._matches_debit_section_header(total_label):
                return ('end', None, '')

        if self._matches_credit_section_header(normalized):
            return ('start', 'deposits_credits_interest', normalized)
        if self._matches_debit_section_header(normalized):
            return ('start', 'withdrawals_debits_charges', normalized)
        return None

    def _matches_credit_section_header(self, normalized: str) -> bool:
        patterns = [
            r'deposits?,? credits? and interest',
            r'deposits? and (?:other )?credits?',
            r'credits? and deposits?',
            r'deposits?\s*/\s*credits?',
            r'credits?\s*/\s*deposits?',
            r'dep[oó]sitos?,? abonos? e intereses?',
            r'dep[oó]sitos? y (?:otros )?cr[eé]ditos?',
            r'abonos? y dep[oó]sitos?',
        ]
        if any(re.fullmatch(pattern, normalized) for pattern in patterns):
            return True

        compact = re.sub(r'[^a-zà-ÿ]+', '', normalized.casefold())
        compact_patterns = [
            r'deposits?credits?andinterest',
            r'deposits?and(?:other)?credits?',
            r'credits?anddeposits?',
            r'dep[oó]sitos?abonos?eintereses?',
            r'dep[oó]sitos?y(?:otros)?cr[eé]ditos?',
            r'abonos?ydep[oó]sitos?',
        ]
        return any(re.fullmatch(pattern, compact) for pattern in compact_patterns)

    def _matches_debit_section_header(self, normalized: str) -> bool:
        patterns = [
            r'other withdrawals?,? debits? and service charges?',
            r'withdrawals? and (?:other )?debits?',
            r'withdrawals?\s*/\s*debits?',
            r'debits?\s*/\s*withdrawals?',
            r'retiros?,? cargos? y comisiones?',
            r'otros retiros?,? d[eé]bitos? y cargos? por servicio',
        ]
        if any(re.fullmatch(pattern, normalized) for pattern in patterns):
            return True

        compact = re.sub(r'[^a-zà-ÿ]+', '', normalized.casefold())
        compact_patterns = [
            r'otherwithdrawals?debits?andservicecharges?',
            r'withdrawals?and(?:other)?debits?',
            r'debits?andwithdrawals?',
            r'retiros?cargos?ycomisiones?',
            r'otrosretiros?d[eé]bitos?ycargos?porservicio',
        ]
        return any(re.fullmatch(pattern, compact) for pattern in compact_patterns)
    
    def _is_header_or_footer(self, line: str) -> bool:
        """Backwards-compatible wrapper for structural row classification."""
        return self._classify_non_transaction_row(line) is not None

    @staticmethod
    def _amount_pattern() -> str:
        """Return the shared strict monetary-token pattern."""
        return (
            r'[-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})+(?:[\.,]\d{2})?'
            r'|[-+]?\$\s*\d+(?:[\.,]\d{2})?'
            r'|[-+]?\s*\d+[\.,]\d{2}'
        )
    
    def _looks_like_transaction(self, line: str) -> bool:
        """
        Check if line has the pattern of a real transaction
        Must have: date + description + amount
        """
        # Must have a date pattern bounded by word boundaries to prevent matching routing/phone numbers
        date_pattern = r'\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b'
        has_date = bool(re.search(date_pattern, line))
        
        # Must have an amount pattern (strictly requiring either $ or decimal part)
        has_amount = bool(re.search(self._amount_pattern(), line))
        
        # Must have some description text (not just numbers/symbols)
        has_description = bool(re.search(r'[A-Za-zÀ-ÿ]{3,}', line))
        
        return has_date and has_amount and has_description
    
    def _parse_transaction_lines(self, transaction_lines: List) -> List[Dict]:
        """
        Parse each transaction line into structured data
        """
        print(f"   🔧 Parsing {len(transaction_lines)} transaction lines...")
        
        parsed_transactions = []
        failed_parses = 0
        
        for line_num, candidate in enumerate(transaction_lines, 1):
            if isinstance(candidate, dict):
                line = str(candidate.get('text', ''))
                statement_section = candidate.get('statement_section')
                column_direction = candidate.get('column_direction')
            else:
                line = str(candidate)
                statement_section = None
                column_direction = None
            try:
                parsed = self._parse_single_transaction(line)
                if parsed:
                    if statement_section == 'deposits_credits_interest':
                        parsed['is_debit'] = False
                        parsed['direction_source'] = 'section_header'
                        parsed['direction_known'] = True
                        parsed['direction_confidence'] = 0.99
                    elif statement_section == 'withdrawals_debits_charges':
                        parsed['is_debit'] = True
                        parsed['direction_source'] = 'section_header'
                        parsed['direction_known'] = True
                        parsed['direction_confidence'] = 0.99
                    elif column_direction in {'debit', 'credit'}:
                        parsed['is_debit'] = column_direction == 'debit'
                        parsed['direction_source'] = 'amount_column'
                        parsed['direction_known'] = True
                        parsed['direction_confidence'] = 0.99
                    else:
                        parsed.setdefault('direction_source', 'line_heuristic')

                    if isinstance(candidate, dict):
                        parsed['statement_section'] = statement_section
                        parsed['section_label'] = candidate.get('section_label', '')
                        parsed['source_page'] = candidate.get('page')
                        parsed['extraction_source'] = candidate.get('source')

                    parsed['transaction_id'] = f"txn_{len(parsed_transactions) + 1}"
                    parsed_transactions.append(parsed)
                    if line_num <= 3:  # Show first 3 for debugging
                        print(f"   ✅ Parsed line {line_num}: {parsed['description'][:30]}... = ${parsed['amount']}")
                else:
                    failed_parses += 1
                    if failed_parses <= 2:  # Show first 2 failures
                        print(f"   ❌ Failed to parse: {line[:50]}...")
                        
            except Exception as e:
                failed_parses += 1
                if failed_parses <= 2:
                    print(f"   ❌ Parse error: {line[:30]}... → {e}")

        success_rate = len(parsed_transactions) / len(transaction_lines) if transaction_lines else 0
        print(f"   📊 Parsing success: {len(parsed_transactions)}/{len(transaction_lines)} ({success_rate:.1%})")

        return parsed_transactions

    def _parse_single_transaction(self, line: str) -> Optional[Dict]:
        """
        Parse one transaction line using multiple regex patterns
        Returns None if no pattern matches
        """
        
        # Define regex patterns for different bank formats
        # Strict amount pattern: requires $ symbol OR explicit decimal/comma (rejects phone numbers, IDs)
        strict_amount = r'(?:[-+]?\$\s*\d{1,3}(?:[\.,]\d{3})+(?:[\.,]\d{2})?|[-+]?\$\s*\d+(?:[\.,]\d{2})?|[-+]?\s*\d+[\.,]\d{2})'
        
        patterns = [
            # Pattern 1: Chase format "02/01/2024 DUNKIN DONUTS 8901 -$4.50 $1,851.92"
            {
                'regex': r'(\d{1,2}/\d{1,2}/\d{4})\s+([^-+$\d]+?)\s+(' + strict_amount + r')\s+\$?([\d,]+\.?\d*)',
                'groups': {'date': 1, 'description': 2, 'amount': 3, 'balance': 4},
                'name': 'Chase Format'
            },
            
            # Pattern 2: Wells Fargo format "03-01-2024 BURGER KING #4521 $8.99 $2,136.68"
            {
                'regex': r'(\d{1,2}-\d{1,2}-\d{4})\s+([^$\d]+?)\s+(' + strict_amount + r')\s+\$?([\d,]+\.?\d*)',
                'groups': {'date': 1, 'description': 2, 'amount': 3, 'balance': 4},
                'name': 'Wells Fargo Format'
            },
            
            # Pattern 3: Generic format "01/02/2024 STARBUCKS STORE 1234 -$5.67 $2,494.33"
            {
                'regex': r'(\d{1,2}/\d{1,2}/\d{4})\s+([A-Za-z][^-+$\d]*?)\s+(' + strict_amount + r')\s+\$?([\d,]+\.?\d*)',
                'groups': {'date': 1, 'description': 2, 'amount': 3, 'balance': 4},
                'name': 'Generic Format'
            },

            # Pattern 4: LatAm format with decimal comma and optional balance
            {
                'regex': r'(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\s+(.+?)\s+((?:[-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})+(?:[\.,]\d{2})?|[-+]?\$\s*\d+(?:[\.,]\d{2})?|[-+]?\s*\d+[\.,]\d{2}))(?:\s+((?:[-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})+(?:[\.,]\d{2})?|[-+]?\$\s*\d+(?:[\.,]\d{2})?|[-+]?\s*\d+[\.,]\d{2})))?$',
                'groups': {'date': 1, 'description': 2, 'amount': 3, 'balance': 4},
                'name': 'LatAm Formats'
            },

            # Pattern 5: ISO date plus free-form text, amount at the end
            {
                'regex': r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})\s+(.+?)\s+((?:[-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})+(?:[\.,]\d{2})?|[-+]?\$\s*\d+(?:[\.,]\d{2})?|[-+]?\s*\d+[\.,]\d{2}))$',
                'groups': {'date': 1, 'description': 2, 'amount': 3},
                'name': 'ISO Date Generic'
            }
        ]
        
        # Try each pattern
        for pattern in patterns:
            match = re.search(pattern['regex'], line)
            if match:
                try:
                    return self._extract_transaction_data(match, pattern, line)
                except Exception as e:
                    continue  # Try next pattern

        # Fallback parser for mixed/unexpected formats
        return self._parse_with_tokenization(line)

    def _parse_with_tokenization(self, line: str) -> Optional[Dict]:
        """Fallback parser that identifies date and numeric tokens and avoids using running balance as amount."""
        date_pattern = r'\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b'
        date_match = re.search(date_pattern, line)
        if not date_match:
            return None

        date_str = date_match.group(1)
        parsed_date = self._parse_date(date_str)
        after_date = line[date_match.end():].strip()

        amount_matches = list(re.finditer(self._amount_pattern(), after_date))
        if not amount_matches:
            return None

        # Heuristic: if there are 2+ numeric tokens, last one is often running balance.
        amount_idx = len(amount_matches) - 1
        if len(amount_matches) >= 2:
            amount_idx = len(amount_matches) - 2

        amount_match = amount_matches[amount_idx]
        amount_str = amount_match.group(0).strip()

        description = after_date[:amount_match.start()].strip()
        if not description:
            description = after_date[:amount_matches[0].start()].strip()
        description = re.sub(r'\s+', ' ', description)
        description = re.sub(r'[#*]\w*', '', description).strip()
        if len(description) < 2:
            return None

        amount = self._parse_amount(amount_str)
        direction = self._infer_line_direction(amount_str, line)

        balance = 0.0
        if amount_idx + 1 < len(amount_matches):
            balance = self._parse_amount(amount_matches[amount_idx + 1].group(0).strip())

        return {
            'date': parsed_date.strftime('%Y-%m-%d'),
            'description': description,
            'amount': abs(amount),
            'is_debit': direction['is_debit'],
            'direction_known': direction['known'],
            'direction_source': direction['source'],
            'direction_confidence': direction['confidence'],
            'balance': balance,
            'has_running_balance': amount_idx + 1 < len(amount_matches),
            'category': 'uncategorized',
            'confidence': 0.0,
            'source': 'deterministic',
            'original_line': line,
            'pattern_used': 'Tokenized Fallback'
        }

    def _extract_transaction_data(self, match, pattern: Dict, original_line: str) -> Dict:
        """Extract structured data from successful regex match"""
        
        groups = match.groups()
        group_map = pattern['groups']
        
        # Extract date
        date_str = groups[group_map['date'] - 1]
        parsed_date = self._parse_date(date_str)
        
        # Extract description (clean it up)
        description = groups[group_map['description'] - 1].strip()
        description = re.sub(r'\s+', ' ', description)  # Remove extra spaces
        description = re.sub(r'[#*]\w*', '', description)  # Remove reference codes
        description = description.strip()
        
        # Extract amount
        amount_str = groups[group_map['amount'] - 1]
        amount = self._parse_amount(amount_str)
        direction = self._infer_line_direction(amount_str, original_line)
        
        # Extract balance (if available)
        balance = 0.0
        has_running_balance = False
        if 'balance' in group_map and len(groups) >= group_map['balance']:
            balance_str = groups[group_map['balance'] - 1]
            if balance_str:
                balance = self._parse_amount(balance_str)
                has_running_balance = True
        
        return {
            'date': parsed_date.strftime('%Y-%m-%d'),
            'description': description,
            'amount': abs(amount),  # Always positive, use is_debit flag
            'is_debit': direction['is_debit'],
            'direction_known': direction['known'],
            'direction_source': direction['source'],
            'direction_confidence': direction['confidence'],
            'balance': balance,
            'has_running_balance': has_running_balance,
            'category': 'uncategorized',  # Will be set later
            'confidence': 0.0,
            'source': 'deterministic',
            'original_line': original_line,
            'pattern_used': pattern['name']
        }

    # Helper methods for parsing components
    def _parse_date(self, date_str: str) -> datetime:
        """Handle different date formats"""
        from datetime import datetime
        
        if re.fullmatch(r'\d{1,2}[/-]\d{1,2}', date_str):
            inferred = self._parse_short_date_with_statement_hint(date_str)
            if inferred:
                return inferred

        date_formats = [
            '%m/%d/%Y',     # 02/01/2024
            '%d/%m/%Y',     # 01/02/2024
            '%m-%d-%Y',     # 03-01-2024  
            '%d-%m-%Y',     # 01-03-2024
            '%d/%m/%y',     # 01/02/24
            '%d-%m-%y',     # 01-02-24
            '%Y-%m-%d',     # 2024-02-01
            '%Y/%m/%d',     # 2024/02/01
            '%d-%b-%Y',     # 01-FEB-2024
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt)
            except:
                continue

        # Handle short date formats without year as current year
        for fmt in ['%d/%m', '%d-%m', '%m/%d', '%m-%d']:
            try:
                parsed = datetime.strptime(date_str, fmt)
                return parsed.replace(year=datetime.now().year)
            except:
                continue
        
        # Fallback to current date if parsing fails
        print(f"   ⚠️  Couldn't parse date: {date_str}")
        return datetime.now()

    def _infer_statement_date_range(self, text: str) -> Optional[Tuple[datetime, datetime]]:
        """Infer a statement window from explicit balance/period labels."""
        date_tokens: List[str] = []
        label_patterns = [
            r'previous balance as of\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
            r'new balance as of\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
            r'opening balance as of\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
            r'closing balance as of\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
            r'saldo anterior al\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
            r'saldo final al\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
        ]
        lowered = text.casefold()
        for pattern in label_patterns:
            date_tokens.extend(re.findall(pattern, lowered, flags=re.IGNORECASE))

        dates: List[datetime] = []
        for token in date_tokens:
            for fmt in ('%m/%d/%Y', '%m-%d-%Y', '%d/%m/%Y', '%d-%m-%Y'):
                try:
                    dates.append(datetime.strptime(token, fmt))
                    break
                except ValueError:
                    continue

        if len(dates) < 2:
            return None
        start_date, end_date = min(dates), max(dates)
        if (end_date - start_date).days > 62:
            return None
        print(
            f"   🗓️ Statement period inferred: "
            f"{start_date.date()} to {end_date.date()}"
        )
        return start_date, end_date

    def _parse_short_date_with_statement_hint(self, date_str: str) -> Optional[datetime]:
        """Resolve MM/DD vs DD/MM by selecting the candidate inside the statement window."""
        if not self._statement_date_range_hint:
            return None

        first, second = [int(part) for part in re.split(r'[/-]', date_str)]
        start_date, end_date = self._statement_date_range_hint
        years = sorted({start_date.year, end_date.year})
        candidates: List[datetime] = []

        for year in years:
            for month, day in ((first, second), (second, first)):
                try:
                    candidate = datetime(year, month, day)
                except ValueError:
                    continue
                if candidate not in candidates:
                    candidates.append(candidate)

        tolerance_start = start_date - timedelta(days=3)
        tolerance_end = end_date + timedelta(days=3)
        in_window = [
            candidate
            for candidate in candidates
            if tolerance_start <= candidate <= tolerance_end
        ]
        if not in_window:
            return None
        return min(in_window, key=lambda candidate: abs((end_date - candidate).days))

    def _infer_statement_balance_hints(
        self, text: str
    ) -> Tuple[Optional[float], Optional[float]]:
        """Read opening and closing balances without treating them as movements."""
        normalized = re.sub(r'\s+', ' ', str(text or ''))
        amount = r'([-$+]?\s*\$?\s*[\d.,]+)'
        opening_patterns = [
            rf'(?:beginning|opening|previous|starting) balance(?:\s+as\s+of\s+[\d/-]+)?\s*:?\s*{amount}',
            rf'(?:saldo inicial|saldo anterior|balance inicial)\s*:?\s*{amount}',
        ]
        closing_patterns = [
            rf'(?:ending|closing|new) balance(?:\s+as\s+of\s+[\d/-]+)?\s*:?\s*{amount}',
            rf'(?:saldo final|saldo de cierre|balance final)\s*:?\s*{amount}',
        ]

        def first_value(patterns: List[str]) -> Optional[float]:
            for pattern in patterns:
                match = re.search(pattern, normalized, flags=re.IGNORECASE)
                if match:
                    return abs(self._parse_amount(match.group(1)))
            return None

        return first_value(opening_patterns), first_value(closing_patterns)

    def _infer_statement_profile(self, text: str, pdf_path: str) -> Tuple[str, str]:
        """Identify a conservative parser profile from document-owned evidence."""
        file_text = str(pdf_path or '').casefold()
        page_text_match = re.search(
            r'--- PAGE \d+ TEXT ---\s*(.*?)(?:--- END PAGE|$)',
            str(text or ''),
            flags=re.DOTALL,
        )
        header_text = page_text_match.group(1) if page_text_match else str(text or '')
        header_text = re.split(
            r'\b(?:account transactions|transaction history|account activity|'
            r'transaction detail|detalle de transacciones)\b',
            header_text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        haystack = f"{file_text}\n{header_text[:4000]}".casefold()
        kind = 'credit_card' if re.search(
            r'\b(?:credit card|tarjeta de credito|tarjeta de crédito)\b', haystack
        ) else 'bank_account'

        institutions = [
            ('wells fargo', 'wells_fargo'),
            ('chase', 'chase'),
            ('bank of america', 'bank_of_america'),
            ('citibank', 'citi'),
            ('citi', 'citi'),
            ('capital one', 'capital_one'),
            ('american express', 'american_express'),
            ('amex', 'american_express'),
            ('truist', 'truist'),
            ('u.s. bank', 'us_bank'),
            ('us bank', 'us_bank'),
            ('pnc', 'pnc'),
            ('td bank', 'td_bank'),
            ('santander', 'santander'),
            ('scotiabank', 'scotiabank'),
            ('bancoestado', 'bancoestado'),
            ('bbva', 'bbva'),
            ('bci', 'bci'),
            ('itau', 'itau'),
            ('itaú', 'itau'),
        ]
        institution = next(
            (code for marker, code in institutions if marker in file_text),
            None,
        )
        if institution is None:
            institution = next(
                (code for marker, code in institutions if marker in haystack),
                'generic',
            )
        return f'{institution}_{kind}', kind

    def _reconcile_transaction_directions(self, transactions: List[Dict]) -> Dict:
        """Validate direction against running-balance changes when available."""
        previous_balance = self._opening_balance_hint
        verified = 0
        conflicts = 0
        unexplained = 0

        for transaction in transactions:
            transaction['statement_profile'] = self._statement_profile
            transaction['statement_kind'] = self._statement_kind
            transaction.setdefault('direction_conflict', False)
            transaction.setdefault('direction_known', False)
            transaction.setdefault('direction_confidence', 0.0)

            if self._statement_kind != 'bank_account':
                continue
            if not transaction.get('has_running_balance'):
                continue

            current_balance = float(transaction.get('balance') or 0.0)
            amount = float(transaction.get('amount') or 0.0)
            if previous_balance is not None:
                delta = current_balance - previous_balance
                tolerance = max(0.02, amount * 0.00001)
                if abs(abs(delta) - amount) <= tolerance:
                    balance_is_debit = delta < 0
                    if (
                        transaction.get('direction_known')
                        and bool(transaction.get('is_debit')) != balance_is_debit
                    ):
                        transaction['direction_conflict'] = True
                        conflicts += 1
                    transaction['is_debit'] = balance_is_debit
                    transaction['direction_known'] = True
                    transaction['direction_source'] = 'running_balance'
                    transaction['direction_confidence'] = 1.0
                    transaction['verified_by_running_balance'] = True
                    verified += 1
                else:
                    transaction['balance_delta_difference'] = round(
                        abs(abs(delta) - amount), 2
                    )
                    unexplained += 1
            previous_balance = current_balance

        known = [t for t in transactions if t.get('direction_known')]
        debits = sum(float(t.get('amount') or 0.0) for t in known if t.get('is_debit'))
        credits = sum(float(t.get('amount') or 0.0) for t in known if not t.get('is_debit'))
        computed_closing = None
        difference = None
        if self._opening_balance_hint is not None:
            computed_closing = self._opening_balance_hint + credits - debits
            if self._closing_balance_hint is not None:
                difference = computed_closing - self._closing_balance_hint

        return {
            'profile': self._statement_profile,
            'opening_balance': self._opening_balance_hint,
            'closing_balance': self._closing_balance_hint,
            'computed_closing_balance': computed_closing,
            'difference': difference,
            'directions_verified_by_balance': verified,
            'direction_conflicts_resolved': conflicts,
            'unexplained_balance_changes': unexplained,
            'unknown_direction_count': sum(
                not bool(t.get('direction_known')) for t in transactions
            ),
            'reconciled': difference is not None and abs(difference) <= 0.02,
        }

    def _parse_amount(self, amount_str: str) -> float:
        """Clean and parse amount string"""
        clean_amount = amount_str.strip()
        clean_amount = clean_amount.replace(' ', '')
        clean_amount = re.sub(r'[$€£]', '', clean_amount)

        # Normalize accounting negatives like (1.234,56)
        negative = False
        if clean_amount.startswith('(') and clean_amount.endswith(')'):
            negative = True
            clean_amount = clean_amount[1:-1]

        # Determine decimal separator by the last separator occurrence
        if ',' in clean_amount and '.' in clean_amount:
            if clean_amount.rfind(',') > clean_amount.rfind('.'):
                # 1.234,56 -> decimal comma
                clean_amount = clean_amount.replace('.', '').replace(',', '.')
            else:
                # 1,234.56 -> decimal dot
                clean_amount = clean_amount.replace(',', '')
        elif ',' in clean_amount:
            # If there are exactly 2 decimal digits after comma, treat as decimal separator
            if re.search(r',\d{2}$', clean_amount):
                clean_amount = clean_amount.replace('.', '').replace(',', '.')
            else:
                clean_amount = clean_amount.replace(',', '')
        else:
            # Dot-only numbers: keep decimal dot, remove thousands commas if any
            clean_amount = clean_amount.replace(',', '')

        try:
            value = float(clean_amount)
            return -value if negative else value
        except:
            print(f"   ⚠️  Couldn't parse amount: {amount_str}")
            return 0.0

    def _is_debit_transaction(self, amount_str: str, line: str) -> bool:
        """Compatibility wrapper around evidence-bearing direction inference."""
        return bool(self._infer_line_direction(amount_str, line)['is_debit'])

    def _infer_line_direction(self, amount_str: str, line: str) -> Dict:
        """Infer direction while preserving whether the conclusion is reliable."""
        stripped_amount = str(amount_str or '').strip()
        if stripped_amount.startswith('-') or stripped_amount.startswith('+'):
            return {
                'is_debit': stripped_amount.startswith('-'),
                'known': True,
                'source': 'explicit_sign',
                'confidence': 1.0,
            }

        normalized = self._normalize_text(line)
        debit_pattern = (
            r'\b(?:db|dr|debit|withdrawal|purchase|payment|fee|charge|cargo|'
            r'compra|egreso|retiro|cashout)\b'
        )
        credit_pattern = (
            r'\b(?:cr|credit|deposit|direct\s+dep|dep\s+direct|salary|payroll|'
            r'refund|income|abono|credito|ingreso|nomina|devolucion)\b'
        )
        debit_match = bool(re.search(debit_pattern, normalized))
        credit_match = bool(re.search(credit_pattern, normalized))
        if debit_match != credit_match:
            return {
                'is_debit': debit_match,
                'known': True,
                'source': 'line_heuristic',
                'evidence': 'keyword',
                'confidence': 0.80,
            }

        # Retain a boolean for backwards compatibility, but mark it unknown so
        # downstream totals can fail closed instead of silently counting it.
        return {
            'is_debit': True,
            'known': False,
            'source': 'unknown',
            'confidence': 0.0,
        }
    
    def _apply_basic_categorization(self, transactions: List[Dict]) -> List[Dict]:
        """
        Step 4: Apply deterministic categorization using merchant database
        NO LLM CALLS - pure keyword matching
        """
        print(f"   🏷️ Applying basic categorization to {len(transactions)} transactions...")
        
        categorized_count = 0
        
        for txn in transactions:
            if txn.get('statement_section') == 'deposits_credits_interest':
                txn['is_debit'] = False
                txn['category'] = 'income'
                txn['confidence'] = 0.99
                txn['source'] = 'deterministic_section'
                categorized_count += 1
                continue

            categorization = self.merchant_db.categorize_transaction_with_details(
                txn['description'],
                is_debit=txn.get('is_debit'),
                document_type=txn.get('statement_kind') or self._statement_kind,
                institution=re.sub(
                    r'_(?:bank_account|credit_card)$',
                    '',
                    str(self._statement_profile),
                ),
            )
            category = categorization['category']
            confidence = categorization['confidence']
            
            if category != 'uncategorized':
                txn['category'] = category
                txn['confidence'] = confidence
                source_labels = {
                    'user_rule': 'deterministic_user_rule',
                    'catalog_rule': 'deterministic_catalog',
                    'direction_rule': 'deterministic_direction',
                }
                txn['source'] = source_labels.get(
                    categorization.get('source'), 'deterministic'
                )
                if categorization.get('transaction_type') == 'third_party_transfer':
                    txn['source'] = 'deterministic_third_party_transfer'
                    txn['third_party_transfer_candidate'] = True
                    txn['category_review_required'] = True
                txn['category_rule_id'] = categorization.get('rule_id', '')
                txn['category_matched_pattern'] = categorization.get(
                    'matched_pattern', ''
                )
                categorized_count += 1
            # else: remains 'uncategorized' for Agent 2
        
        categorization_rate = categorized_count / len(transactions) if transactions else 0
        print(f"   📊 Deterministic categorization: {categorized_count}/{len(transactions)} ({categorization_rate:.1%})")
        print(f"   🤖 Will need LLM for: {len(transactions) - categorized_count} transactions")
        
        return transactions
