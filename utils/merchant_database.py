import re
import os
import json
import unicodedata
from typing import Dict, List, Optional

from utils.custom_categories import CUSTOM_CATEGORY_PREFIX

"""
Merchant Database for Deterministic Categorization
This handles OBVIOUS transactions that don't need LLM analysis.
"""

class MerchantDatabase:
    """
    Keyword-based categorization for obvious merchants
    NO LLM CALLS - pure pattern matching
    """
    
    def __init__(
        self,
        load_user_rules: bool = True,
        catalog_path: Optional[str] = None,
        user_rules_path: Optional[str] = None,
    ):
        print("🏪 Initializing Merchant Database...")
        self.allow_persistent_rules = load_user_rules
        project_root = os.path.dirname(os.path.dirname(__file__))
        self.user_rules_path = user_rules_path or os.path.join(
            project_root, 'data', 'user_category_rules.json'
        )
        self.catalog_path = catalog_path or os.path.join(
            project_root, 'data', 'deterministic_merchant_rules.json'
        )
        
        # Extensive keyword database (professor emphasized this)
        self.merchant_keywords = {
            'food_dining': [
                # Coffee & Fast Food
                'starbucks', 'dunkin', 'dunkin donuts', 'coffee', 'cafe',
                'mcdonalds', 'burger king', 'subway', 'kfc', 'taco bell',
                'chipotle', 'panera', 'panda express', 'pizza hut', 'dominos',
                
                # Restaurants
                'restaurant', 'bistro', 'grill', 'kitchen', 'diner', 'eatery',
                'food truck', 'catering', 'bakery',
                
                # Food Delivery
                'uber eats', 'doordash', 'grubhub', 'postmates', 'food delivery',

                # Spanish keywords
                'restaurante', 'cafeteria', 'cafe', 'comida', 'almuerzo', 'desayuno',
                'cena', 'sandwicheria', 'pizzeria', 'delivery'
            ],
            
            'groceries': [
                'kroger', 'safeway', 'publix', 'wegmans', 'giant', 'stop shop',
                'whole foods', 'trader joe', 'aldi', 'food lion', 'harris teeter',
                'market', 'grocery', 'supermarket', 'food store',
                'supermercado', 'almacen', 'minimarket', 'feria'
            ],
            
            'transportation': [
                # Gas Stations
                'shell', 'exxon', 'chevron', 'bp', 'mobil', 'citgo', 'arco',
                'gas station', 'fuel', 'gasoline', 'petrol',
                
                # Rideshare & Transit
                'uber', 'lyft', 'taxi', 'cab', 'rideshare',
                'metro', 'mta', 'transit', 'bus', 'train', 'subway',
                'parking', 'garage', 'meter',
                
                # Travel
                'airline', 'airport', 'flight', 'car rental', 'hertz', 'enterprise',
                'bencina', 'peaje', 'autopista', 'combustible', 'estacion de servicio', 'metro de'
            ],
            
            'shopping': [
                'amazon', 'ebay', 'etsy', 'best buy', 'apple store', 'microsoft',
                'home depot', 'lowes', 'macys', 'kohls', 'tj maxx', 'marshalls',
                'ross', 'old navy', 'gap', 'nike', 'adidas', 'mall', 'outlet',
                'tienda', 'retail', 'falabella', 'paris', 'ripley', 'mercadolibre'
            ],
            
            'bills_utilities': [
                'electric', 'power', 'energy', 'utility', 'water', 'sewer',
                'gas bill', 'internet', 'cable', 'phone', 'wireless',
                'verizon', 'att', 'at&t', 'comcast', 'spectrum', 'xfinity',
                'municipal', 'city of', 'county of',
                'luz', 'agua', 'gas', 'telefono', 'movil', 'celular', 'entel', 'movistar', 'wom', 'vtr', 'claro'
            ],
            
            'entertainment': [
                'netflix', 'spotify', 'hulu', 'disney', 'amazon prime',
                'apple music', 'youtube', 'gaming', 'steam', 'playstation',
                'xbox', 'nintendo', 'movie', 'theater', 'cinema', 'concert'
            ],
            
            'healthcare': [
                'cvs', 'walgreens', 'rite aid', 'pharmacy', 'medical',
                'doctor', 'dentist', 'hospital', 'clinic', 'health',
                'farmacia', 'medico', 'dentista', 'clinica', 'isapre', 'fonasa'
            ],

            # These categories use direction-sensitive rules below rather than
            # ordinary substring matching.
            'other_income': [],
            'international_transfer_in': [],
            'international_transfer_out': [],
            'internal_transfer': [],
            
            'atm_cash': [
                'atm', 'withdrawal', 'cash advance', 'cash back', 'cashout'
            ],
            
            'income': [
                'direct deposit', 'salary', 'payroll', 'interest', 'dividend',
                'refund', 'tax refund', 'deposit', 'credit',
                'abono', 'sueldo', 'nomina', 'transferencia recibida', 'devolucion'
            ],
            
            'fees': [
                'fee', 'charge', 'penalty', 'overdraft', 'maintenance',
                'service charge', 'foreign', 'atm fee',
                'comision', 'mantencion', 'cargo por servicio', 'sobregiro'
            ]
        }
        
        categories_count = sum(len(keywords) for keywords in self.merchant_keywords.values())
        print(f"   📚 Loaded {len(self.merchant_keywords)} categories")
        print(f"   🔑 Total keywords: {categories_count}")

        self.catalog_rules = self._load_catalog_rules()
        print(f"   📋 Catalog rules: {len(self.catalog_rules)}")

        # User rules are exact/normalized description overrides learned from manual review.
        self.user_category_overrides = (
            self._load_user_category_overrides() if load_user_rules else {}
        )
        print(f"   🧠 User category rules: {len(self.user_category_overrides)}")
    
    def categorize_transaction(
        self,
        description: str,
        is_debit=None,
        document_type: Optional[str] = None,
        institution: Optional[str] = None,
    ) -> tuple:
        """
        Categorize transaction based on merchant description
        Returns: (category, confidence) or ('uncategorized', 0.0).
        Direction-sensitive categories are only applied when is_debit is known.
        """
        result = self.categorize_transaction_with_details(
            description,
            is_debit=is_debit,
            document_type=document_type,
            institution=institution,
        )
        return result['category'], result['confidence']

    def categorize_transaction_with_details(
        self,
        description: str,
        is_debit=None,
        document_type: Optional[str] = None,
        institution: Optional[str] = None,
    ) -> Dict:
        """Return category plus the exact deterministic rule that matched."""
        desc_lower = description.lower().strip()
        desc_clean = self._clean_description_for_matching(desc_lower)

        # First priority: user-learned overrides from manual review.
        user_category = self._find_user_category_override(desc_clean, is_debit)
        if user_category:
            return {
                'category': user_category,
                'confidence': 0.99,
                'source': 'user_rule',
                'rule_id': f'user::{desc_clean}',
            }

        # Require an explicit international-transfer marker and use the parsed
        # debit/credit direction. This avoids treating ordinary transfers as
        # international movements.
        international_transfer_markers = [
            'international transfer', 'international wire', 'intl transfer',
            'intl wire', 'wire transfer international', 'swift transfer',
            'swift payment', 'transferencia internacional', 'giro internacional',
            'transferencia swift', 'pago swift',
        ]
        if any(marker in desc_clean for marker in international_transfer_markers):
            if is_debit is True:
                return self._result(
                    'international_transfer_out', 0.95,
                    'direction_rule', 'international_transfer_out',
                )
            if is_debit is False:
                return self._result(
                    'international_transfer_in', 0.95,
                    'direction_rule', 'international_transfer_in',
                )

        # Be conservative with residual income: require both a credit and an
        # explicit alternative-income signal.
        other_income_markers = [
            'other income', 'misc income', 'miscellaneous income',
            'additional income', 'otros ingresos', 'otro ingreso',
            'ingreso adicional', 'honorarios', 'freelance income',
            'rental income', 'arriendo recibido',
        ]
        if is_debit is False and any(marker in desc_clean for marker in other_income_markers):
            return self._result(
                'other_income', 0.90, 'direction_rule', 'other_income',
            )

        catalog_match = self._match_catalog_rule(
            description,
            is_debit=is_debit,
            document_type=document_type,
            institution=institution,
        )
        if catalog_match:
            return catalog_match
        
        # Check legacy keywords with word/phrase boundaries. This avoids false
        # matches such as "aldi" inside an unrelated name.
        normalized_catalog_description = self._normalize_catalog_text(description)
        for category, keywords in self.merchant_keywords.items():
            for keyword in keywords:
                normalized_keyword = self._normalize_catalog_text(keyword)
                if self._contains_normalized_phrase(
                    normalized_catalog_description, normalized_keyword
                ):
                    confidence = self._calculate_confidence(keyword, desc_clean)
                    return self._result(
                        category, confidence, 'keyword_rule', f'keyword::{keyword}'
                    )
        
        # No match found - will need LLM
        return self._result('uncategorized', 0.0, 'none', '')

    def save_user_category_rule(
        self, description: str, category: str, is_debit=None
    ) -> bool:
        """
        Persist a user override so future statements are categorized locally.

        New UI-created rules are scoped to debit or credit. Calls that omit
        ``is_debit`` retain the legacy direction-agnostic file format.
        """
        if not self.allow_persistent_rules:
            return False
        if not description or not category:
            return False

        # User-defined auxiliary categories are deliberately session-only and
        # must never become merchant-learning rules.
        category = str(category)
        if (
            category.startswith(CUSTOM_CATEGORY_PREFIX)
            or category == 'internal_transfer'
            or category not in self._persistable_categories()
        ):
            return False

        normalized_desc = self._clean_description_for_matching(description.lower().strip())
        if not normalized_desc:
            return False

        if is_debit is None:
            self.user_category_overrides[normalized_desc] = category
        else:
            direction = 'debit' if bool(is_debit) else 'credit'
            existing = self.user_category_overrides.get(normalized_desc)
            if isinstance(existing, dict):
                scoped = dict(existing)
            elif isinstance(existing, str) and existing:
                scoped = {'any': existing}
            else:
                scoped = {}
            scoped[direction] = category
            self.user_category_overrides[normalized_desc] = scoped
        return self._persist_user_category_overrides()

    def enable_user_rules(self) -> None:
        """Enable and load persistent corrections for an existing analyzer."""
        if not self.allow_persistent_rules:
            self.allow_persistent_rules = True
            self.user_category_overrides = self._load_user_category_overrides()

    def _load_user_category_overrides(self) -> dict:
        """Load persisted manual categorization rules from disk."""
        if not os.path.exists(self.user_rules_path):
            return {}

        try:
            with open(self.user_rules_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                cleaned = {}
                for description, configured in data.items():
                    normalized = self._clean_description_for_matching(
                        str(description).lower().strip()
                    )
                    if not normalized:
                        continue
                    if isinstance(configured, str):
                        if self._is_persistable_category(configured):
                            cleaned[normalized] = configured
                        continue
                    if isinstance(configured, dict):
                        scoped = {
                            direction: category
                            for direction, category in configured.items()
                            if direction in {'any', 'debit', 'credit'}
                            and self._is_persistable_category(category)
                        }
                        if scoped:
                            cleaned[normalized] = scoped
                return cleaned
        except Exception:
            return {}

        return {}

    def _persist_user_category_overrides(self) -> bool:
        """Save manual categorization rules to disk."""
        try:
            os.makedirs(os.path.dirname(self.user_rules_path), exist_ok=True)
            with open(self.user_rules_path, 'w', encoding='utf-8') as f:
                json.dump(self.user_category_overrides, f, indent=2, sort_keys=True)
            return True
        except Exception:
            return False

    def _find_user_category_override(self, description: str, is_debit) -> Optional[str]:
        configured = self.user_category_overrides.get(description)
        if isinstance(configured, str):
            return configured if self._is_persistable_category(configured) else None
        if not isinstance(configured, dict):
            return None
        direction = (
            'debit' if is_debit is True
            else 'credit' if is_debit is False
            else 'any'
        )
        category = configured.get(direction) or configured.get('any')
        return str(category) if self._is_persistable_category(category) else None

    def _persistable_categories(self) -> set:
        return set(self.merchant_keywords) | {'other'}

    def _is_persistable_category(self, category) -> bool:
        text = str(category or '')
        return (
            text in self._persistable_categories()
            and text != 'internal_transfer'
            and not text.startswith(CUSTOM_CATEGORY_PREFIX)
        )

    def _result(
        self, category: str, confidence: float, source: str, rule_id: str,
        matched_pattern: str = '',
        review_required: bool = False,
        transaction_type: str = '',
    ) -> Dict:
        return {
            'category': category,
            'confidence': float(confidence),
            'source': source,
            'rule_id': rule_id,
            'matched_pattern': matched_pattern,
            'review_required': bool(review_required),
            'transaction_type': str(transaction_type or ''),
        }

    def _load_catalog_rules(self) -> List[Dict]:
        """Load and validate the editable deterministic merchant catalog."""
        try:
            with open(self.catalog_path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
        except Exception as exc:
            print(f"   ⚠️ Merchant catalog unavailable: {exc}")
            return []

        if not isinstance(payload, dict) or payload.get('schema_version') != 1:
            print("   ⚠️ Merchant catalog has an unsupported schema")
            return []

        valid_rules = []
        seen_ids = set()
        allowed_categories = set(self.merchant_keywords)
        for raw_rule in payload.get('rules', []):
            if not isinstance(raw_rule, dict):
                continue
            rule_id = str(raw_rule.get('id') or '').strip()
            category = str(raw_rule.get('category') or '').strip()
            direction = str(raw_rule.get('direction') or 'any').strip()
            patterns = [
                self._normalize_catalog_text(pattern)
                for pattern in raw_rule.get('patterns', [])
                if str(pattern).strip()
            ]
            patterns = [pattern for pattern in patterns if pattern]
            try:
                confidence = float(raw_rule.get('confidence', 0.95))
            except (TypeError, ValueError):
                continue
            if (
                not rule_id
                or rule_id in seen_ids
                or category not in allowed_categories
                or direction not in {'any', 'debit', 'credit'}
                or not 0 <= confidence <= 1
                or not patterns
            ):
                continue
            seen_ids.add(rule_id)
            valid_rules.append({
                'id': rule_id,
                'category': category,
                'direction': direction,
                'confidence': confidence,
                'review_required': bool(raw_rule.get('review_required', False)),
                'transaction_type': str(
                    raw_rule.get('transaction_type') or ''
                ).strip(),
                'patterns': patterns,
                'document_types': {
                    str(value).strip()
                    for value in raw_rule.get('document_types', [])
                    if str(value).strip()
                },
                'institutions': {
                    self._normalize_catalog_text(value)
                    for value in raw_rule.get('institutions', [])
                    if str(value).strip()
                },
            })
        return valid_rules

    def _match_catalog_rule(
        self,
        description: str,
        is_debit=None,
        document_type: Optional[str] = None,
        institution: Optional[str] = None,
    ) -> Optional[Dict]:
        normalized = self._normalize_catalog_text(description)
        direction = (
            'debit' if is_debit is True
            else 'credit' if is_debit is False
            else 'unknown'
        )
        normalized_institution = self._normalize_catalog_text(institution or '')
        for rule in self.catalog_rules:
            if rule['direction'] != 'any' and rule['direction'] != direction:
                continue
            if rule['document_types'] and document_type not in rule['document_types']:
                continue
            if rule['institutions'] and normalized_institution not in rule['institutions']:
                continue
            for pattern in rule['patterns']:
                if self._contains_normalized_phrase(normalized, pattern):
                    return self._result(
                        rule['category'], rule['confidence'], 'catalog_rule',
                        rule['id'], matched_pattern=pattern,
                        review_required=rule['review_required'],
                        transaction_type=rule['transaction_type'],
                    )
        return None

    def _normalize_catalog_text(self, value) -> str:
        text = unicodedata.normalize('NFKD', str(value or '').casefold())
        text = ''.join(char for char in text if not unicodedata.combining(char))
        text = re.sub(r'[^a-z0-9]+', ' ', text)
        return re.sub(r'\s+', ' ', text).strip()

    def _contains_normalized_phrase(self, text: str, phrase: str) -> bool:
        if not text or not phrase:
            return False
        return bool(re.search(rf'(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])', text))
    
    def _clean_description_for_matching(self, description: str) -> str:
        """Clean description to improve keyword matching"""
        # Remove common noise
        desc = re.sub(r'[#*]\w*', '', description)  # Remove reference codes
        desc = re.sub(r'\d{4,}', '', desc)  # Remove long numbers
        desc = re.sub(r'\s+', ' ', desc)    # Normalize spaces
        return desc.strip()
    
    def _calculate_confidence(self, matched_keyword: str, description: str) -> float:
        """Calculate confidence based on keyword match quality"""
        
        # Exact brand matches get high confidence
        if matched_keyword in ['starbucks', 'walmart', 'amazon', 'netflix']:
            return 0.95
        
        # Specific store types get high confidence  
        if matched_keyword in ['gas station', 'grocery', 'pharmacy']:
            return 0.90
        
        # Generic keywords get medium confidence
        if matched_keyword in ['restaurant', 'cafe', 'market']:
            return 0.75
        
        # Default confidence for keyword matches
        return 0.80
    
    def get_statistics(self) -> dict:
        """Return database statistics"""
        return {
            'total_categories': len(self.merchant_keywords),
            'total_keywords': sum(len(keywords) for keywords in self.merchant_keywords.values()),
            'categories': list(self.merchant_keywords.keys())
        }
