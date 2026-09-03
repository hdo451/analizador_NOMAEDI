"""Agent 2: expert, guarded categorization of ambiguous transactions."""

import json
import re
from typing import Dict, List, Set
from pydantic import BaseModel, Field
from .base_agent import BaseAgent

# Pydantic models for LLM response validation
class TransactionCategory(BaseModel):
    """Single transaction categorization result"""
    transaction_id: str
    category: str
    confidence: float = Field(ge=0, le=1)  # Must be between 0 and 1
    reasoning: str
    merchant_name: str = ""
    review_required: bool = False

class BatchCategorizationResponse(BaseModel):
    """Validate batch LLM response structure"""
    categorizations: List[TransactionCategory]

class ContentAnalyzerAgent(BaseAgent):
    """
    Expert categorization with a deterministic safety envelope.

    The model only sees selected transaction metadata and can only suggest a
    category. It cannot alter dates, amounts, direction, account or ordering.
    """
    
    def __init__(self, llm_interface=None, deterministic_only: bool = False):
        super().__init__(
            "Content Analyzer",
            uses_llm=bool(llm_interface) and not deterministic_only,
        )
        self.llm = llm_interface
        self.deterministic_only = deterministic_only
        
        # Define categories that LLM can choose from
        self.valid_categories = {
            'food_dining': 'Restaurants, coffee shops, food delivery, dining out',
            'groceries': 'Grocery stores, supermarkets, food shopping',
            'transportation': 'Gas stations, rideshare, public transit, car expenses',
            'shopping': 'Retail purchases, online shopping, clothing, electronics',
            'bills_utilities': 'Electric, water, internet, phone bills, utilities',
            'entertainment': 'Streaming services, movies, games, events, recreation',
            'healthcare': 'Medical, dental, pharmacy, health-related expenses',
            'atm_cash': 'Cash withdrawal or ATM cash advance',
            'income': 'Salary, payroll, interest, benefit or clearly identified recurring income',
            'other_income': 'Alternative earnings explicitly identified as freelance, professional services, rental, or other income',
            'international_transfer_in': 'International transfer or SWIFT payment received from abroad',
            'international_transfer_out': 'International transfer or SWIFT payment sent abroad',
            'fees': 'Bank fees, penalties, service charges, maintenance fees',
            'other': 'Transactions that don\'t clearly fit other categories'
        }
        
        mode = "deterministic fallback" if deterministic_only else "LLM fallback"
        print(f"🧠 {self.name} initialized - {mode} for unclear transactions")
    
    def process(self, transactions: List[Dict]) -> List[Dict]:
        """
        Review uncategorized and low-confidence deterministic categories.
        """
        
        unresolved_direction = [
            t for t in transactions
            if not t.get('direction_known', True)
            and t.get('category') in {'uncategorized', 'other'}
        ]

        for txn in unresolved_direction:
            txn['category'] = 'other'
            txn['confidence'] = 0.0
            txn['source'] = 'deterministic_guardrail'
            txn['reasoning'] = 'Direction unresolved; excluded from financial totals'

        if self.deterministic_only:
            needs_fallback = [
                txn for txn in transactions
                if txn.get('category') == 'uncategorized'
                and txn.get('direction_known', True)
            ]
            already_categorized = len(transactions) - len(needs_fallback) - len(unresolved_direction)
            print(f"\n🧠 {self.name} processing:")
            print(f"   ✅ Already categorized: {already_categorized}")
            print(f"   ⚠️ Direction unresolved: {len(unresolved_direction)}")
            print(f"   ⚪ Needs fallback categorization: {len(needs_fallback)}")
            if not needs_fallback:
                return transactions
            return self._apply_deterministic_fallback(needs_fallback, transactions)

        needs_llm = [txn for txn in transactions if self._should_be_reviewed(txn)]
        already_categorized = len(transactions) - len(needs_llm) - len(unresolved_direction)
        
        print(f"\n🧠 {self.name} processing:")
        print(f"   ✅ Already categorized: {already_categorized}")
        print(f"   ⚠️ Direction unresolved: {len(unresolved_direction)}")
        print(f"   ⚪ Needs fallback categorization: {len(needs_llm)}")
        
        if not needs_llm:
            print("   🎉 No LLM call needed - all transactions already categorized!")
            return transactions

        print(f"   🚀 Reviewing {len(needs_llm)} transactions with the expert agent...")
        before_calls = self.llm.call_count
        self._batch_categorize_with_llm(needs_llm)
        used_calls = self.llm.call_count - before_calls
        self.llm_calls_made += max(used_calls, 0)
        
        print(f"   ✅ LLM categorization complete! Calls used: {used_calls}")
        
        # Categorization mutates the original transaction dictionaries. Return
        # the original list so statement order and transaction IDs remain stable.
        return transactions

    def _should_be_reviewed(self, txn: Dict) -> bool:
        """Select only safe, useful candidates for remote categorization."""
        if not txn.get('direction_known', True):
            return False
        category_source = str(txn.get('category_source') or '')
        if txn.get('cash_allocation_kind') or category_source.startswith('user'):
            return False
        source = str(txn.get('source') or '')
        if source in {'user_review', 'manual', 'cash_allocation'}:
            return False
        if source in {
            'deterministic_user_rule', 'deterministic_catalog',
            'deterministic_third_party_transfer',
        }:
            return False
        category = str(txn.get('category') or 'uncategorized')
        confidence = float(txn.get('confidence') or 0.0)
        return category in {'uncategorized', 'other'} or (
            source.startswith('deterministic') and confidence < 0.99
        )

    def _apply_deterministic_fallback(
        self,
        needs_fallback: List[Dict],
        original_transactions: List[Dict],
    ) -> List[Dict]:
        """Assign a fixed, auditable fallback without making a model call."""
        for txn in needs_fallback:
            txn['category'] = 'other'
            txn['confidence'] = 0.0
            txn['source'] = 'deterministic_fallback'
            txn['reasoning'] = (
                'No deterministic merchant rule matched; assigned to Other for review'
            )
        return original_transactions
    
    def _batch_categorize_with_llm(self, transactions: List[Dict]) -> List[Dict]:
        """
        Categorize unclear transactions in bounded chunks.
        """
        # Smaller bounded batches reduce incomplete output while keeping context
        # for repeated merchants within the same statement.
        chunk_size = 35
        categorized_all = []

        for start in range(0, len(transactions), chunk_size):
            chunk = transactions[start:start + chunk_size]
            categorized_chunk = self._categorize_chunk_with_llm(chunk)
            categorized_all.extend(categorized_chunk)

        return categorized_all

    def _categorize_chunk_with_llm(self, transactions: List[Dict]) -> List[Dict]:
        """Categorize one chunk of transactions through the LLM."""
        transaction_data = []
        for i, txn in enumerate(transactions):
            transaction_data.append({
                'id': f"txn_{i}",
                'description': self._redact_long_identifiers(txn.get('description', '')),
                'amount': round(float(txn.get('amount') or 0.0), 2),
                'direction': 'debit' if txn.get('is_debit') else 'credit',
                'direction_source': txn.get('direction_source', ''),
                'date': txn.get('date', ''),
                'document_type': txn.get('document_type', 'other'),
                'institution': txn.get('institution', 'unknown'),
                'statement_profile': txn.get('statement_profile', ''),
                'account_profile': txn.get('account_label', ''),
                'movement_type': txn.get('movement_type', ''),
                'rule_category': txn.get('category', 'uncategorized'),
                'rule_confidence': float(txn.get('confidence') or 0.0),
            })

        system_prompt = f"""You are the expert transaction-categorization agent for a
personal-finance statement analyzer. You are highly familiar with common statement
descriptors, merchant abbreviations and posting conventions used by major U.S. and
Latin American institutions, including Chase, Wells Fargo, Bank of America, Citi,
Capital One, American Express, Truist, U.S. Bank, PNC, TD, Santander, BBVA,
Scotiabank, Itaú, BCI and BancoEstado. Institution familiarity is context, never a
reason to invent facts.

Categorize each supplied transaction into exactly one of these categories:
{json.dumps(self.valid_categories, indent=2)}

Hard rules:
1. Return one result for every input id, preserving every id exactly once.
2. Never infer or change transaction direction. A debit cannot be income or an
   incoming international transfer. A credit cannot be an expense, fee, ATM
   withdrawal or outgoing international transfer.
3. Use description, institution, document type and movement type together. A card
   payment, transfer, refund, interest charge and merchant purchase are different.
4. Prefer a specific category only when evidence supports it. Use "other" and set
   review_required=true when merchant identity or purpose remains ambiguous.
5. Do not treat ordinary account-to-account transfers as income. Internal-transfer
   matching is handled separately by deterministic code.
6. Be consistent for repeated normalized merchants in this batch.
7. Confidence is calibrated evidence strength, not optimism. Reasoning must be a
   short Spanish explanation based only on visible evidence.
8. merchant_name is a cleaned merchant/payee name when identifiable, otherwise "".

You only label categories. Amount, date, direction, account and document metadata
are immutable application-owned facts."""

        user_prompt = f"Categorize these unclear transactions:\n{json.dumps(transaction_data, indent=2)}"

        try:
            response_schema = {
                'type': 'object',
                'properties': {
                    'categorizations': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'transaction_id': {'type': 'string'},
                                'category': {
                                    'type': 'string',
                                    'enum': list(self.valid_categories),
                                },
                                'confidence': {
                                    'type': 'number', 'minimum': 0, 'maximum': 1
                                },
                                'reasoning': {'type': 'string'},
                                'merchant_name': {'type': 'string'},
                                'review_required': {'type': 'boolean'},
                            },
                            'required': [
                                'transaction_id', 'category', 'confidence',
                                'reasoning', 'merchant_name', 'review_required'
                            ],
                            'additionalProperties': False,
                        },
                    }
                },
                'required': ['categorizations'],
                'additionalProperties': False,
            }
            response = self.llm.make_call(
                user_prompt,
                system_prompt,
                expect_json=True,
                response_schema=response_schema,
            )
            
            if response:
                parsed_json = self._extract_json_object(response)
                result = BatchCategorizationResponse(**parsed_json)
                return self._apply_llm_categorization(transactions, result.categorizations)
            else:
                print("   ❌ LLM call failed - applying fallback categorization")
                return self._apply_fallback_categorization(transactions)
                
        except Exception as e:
            print(f"   ❌ LLM categorization error: {e}")
            return self._apply_fallback_categorization(transactions)
    
    def _apply_llm_categorization(self, transactions: List[Dict], categorizations: List[TransactionCategory]) -> List[Dict]:
        """Apply LLM categorizations to transactions"""
        
        # Reject duplicate ids rather than silently allowing the last one to win.
        duplicate_ids: Set[str] = set()
        cat_lookup = {}
        for cat in categorizations:
            if cat.transaction_id in cat_lookup:
                duplicate_ids.add(cat.transaction_id)
            else:
                cat_lookup[cat.transaction_id] = cat
        
        for i, txn in enumerate(transactions):
            txn_id = f"txn_{i}"
            if txn_id in cat_lookup and txn_id not in duplicate_ids:
                cat = cat_lookup[txn_id]
                if (
                    cat.category in self.valid_categories
                    and cat.category in self._allowed_categories_for_direction(txn)
                ):
                    txn['category'] = cat.category
                    txn['confidence'] = cat.confidence
                    txn['source'] = 'llm'
                    txn['reasoning'] = cat.reasoning
                    txn['merchant_name'] = cat.merchant_name
                    txn['category_review_required'] = bool(
                        cat.review_required or cat.confidence < 0.72
                    )
                    print(f"   🤖 {txn['description'][:25]}... → {cat.category} ({cat.confidence:.1%})")
                else:
                    self._apply_safe_fallback(
                        txn,
                        'Agent suggestion rejected by the category/direction guardrail',
                    )
            else:
                # Fallback if LLM didn't categorize this one
                self._apply_safe_fallback(txn, 'LLM response incomplete')
        
        return transactions

    def _allowed_categories_for_direction(self, txn: Dict) -> Set[str]:
        """Prevent category suggestions that contradict parsed cash direction."""
        if txn.get('is_debit'):
            return {
                'food_dining', 'groceries', 'transportation', 'shopping',
                'bills_utilities', 'entertainment', 'healthcare', 'atm_cash',
                'international_transfer_out', 'fees', 'other',
            }
        return {
            'income', 'other_income', 'international_transfer_in', 'other',
        }

    def _redact_long_identifiers(self, description: str) -> str:
        """Mask likely account/card/reference numbers while retaining merchant text."""
        text = re.sub(r"\b(?:\d[ -]?){12,19}\b", "[CARD]", str(description))
        return re.sub(r"\b\d{6,}\b", "[REF]", text)

    def _apply_safe_fallback(self, txn: Dict, reason: str) -> None:
        """Keep a compatible rule result when the agent output cannot be used."""
        rule_category = str(
            txn.get('deterministic_category') or txn.get('category') or 'other'
        )
        if (
            rule_category in self.valid_categories
            and rule_category in self._allowed_categories_for_direction(txn)
            and rule_category != 'other'
        ):
            txn['category'] = rule_category
            txn['confidence'] = float(
                txn.get('deterministic_confidence')
                if txn.get('deterministic_confidence') is not None
                else txn.get('confidence') or 0.0
            )
            txn['source'] = 'agent_fallback_rule'
        else:
            txn['category'] = 'other'
            txn['confidence'] = 0.0
            txn['source'] = 'fallback'
        txn['category_review_required'] = True
        txn['reasoning'] = reason

    def _extract_json_object(self, response_text: str) -> Dict:
        """Extract JSON safely even if model wraps it with extra text or markdown fences."""
        cleaned = response_text.strip()

        # Direct parse first
        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # Strip markdown fences if present
        fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL)
        if fenced_match:
            return json.loads(fenced_match.group(1))

        # Fallback: first JSON object in text
        obj_match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if obj_match:
            return json.loads(obj_match.group(1))

        raise ValueError("No valid JSON object found in LLM response")
    
    def _apply_fallback_categorization(self, transactions: List[Dict]) -> List[Dict]:
        """Fallback when LLM completely fails"""
        print("   🛟 Applying fallback categorization...")
        
        for txn in transactions:
            self._apply_safe_fallback(txn, 'LLM unavailable')
        
        return transactions
