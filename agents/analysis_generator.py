"""
Agent 3: Analysis Generator - Create spending insights and reports
================================================================

This agent generates financial analysis from categorized transactions.
Mostly deterministic (calculations, charts) with optional LLM insights.

0 LLM calls for basic analysis, 0-1 LLM calls for personalized insights.
"""

import json
import re
from typing import List, Dict, Optional
from datetime import datetime
from .base_agent import BaseAgent
from utils.custom_categories import is_custom_category, resolve_category_label

class AnalysisGeneratorAgent(BaseAgent):
    """
    Agent 3: Generate spending analysis and insights
    Mostly deterministic, optional LLM for personalized recommendations
    """
    
    def __init__(self, llm_interface=None):
        super().__init__("Analysis Generator", uses_llm=bool(llm_interface))
        self.llm = llm_interface
        print(f"📊 {self.name} initialized - {'with' if llm_interface else 'without'} LLM capability")
    
    def process(
        self,
        transactions: List[Dict],
        generate_ai_insights: bool = False,
        category_labels: Optional[Dict[str, str]] = None,
    ) -> Dict:
        """
        Generate comprehensive financial analysis
        
        Args:
            transactions: Fully categorized transactions from Agent 2
            generate_ai_insights: Whether to use LLM for personalized advice
        """
        
        print(f"\n📊 {self.name} generating analysis...")
        print(f"   📋 Processing {len(transactions)} categorized transactions")
        print(f"   🤖 AI insights requested: {generate_ai_insights}")
        
        # Step 1: Calculate basic financial summary (deterministic)
        summary = self._calculate_financial_summary(transactions)
        
        # Step 2: Analyze spending by category (deterministic)
        category_analysis = self._analyze_spending_by_category(transactions, category_labels)
        
        # Step 3: Find spending patterns (deterministic)
        patterns = self._identify_spending_patterns(transactions, category_labels)
        
        # Step 4: Generate basic insights (deterministic)
        basic_insights = self._generate_basic_insights(summary, category_analysis)
        
        # Step 5: Optional AI insights (0-1 LLM call)
        ai_insights = None
        if generate_ai_insights and self.llm:
            ai_insights = self._generate_ai_insights(summary, category_analysis, patterns)
            if ai_insights:  # Only increment if LLM was actually called
                self.llm_calls_made += 1
        
        result = {
            'financial_summary': summary,
            'category_breakdown': category_analysis,
            'spending_patterns': patterns,
            'basic_insights': basic_insights,
            'ai_insights': ai_insights,
            'report_generated_at': datetime.now().isoformat(),
            'total_transactions_analyzed': len(transactions)
        }
        
        self._print_analysis_summary(result)
        return result
    
    def _calculate_financial_summary(self, transactions: List[Dict]) -> Dict:
        """Calculate basic financial metrics (deterministic)"""
        print("   💰 Calculating financial summary...")
        
        # Separate debits and credits
        debits = [t for t in transactions if self._is_spending_debit(t)]
        credits = [t for t in transactions if self._is_income_credit(t)]
        
        # Calculate totals
        total_spent = sum(t['amount'] for t in debits)
        total_income = sum(t['amount'] for t in credits)
        net_change = total_income - total_spent
        
        # Calculate averages
        avg_transaction = total_spent / len(debits) if debits else 0
        avg_daily_spending = total_spent / 30 if debits else 0  # Assume ~30 days
        
        return {
            'total_transactions': len(transactions),
            'total_spent': total_spent,
            'total_income': total_income,
            'net_change': net_change,
            'average_transaction': avg_transaction,
            'average_daily_spending': avg_daily_spending,
            'debit_count': len(debits),
            'credit_count': len(credits)
        }
    
    def _analyze_spending_by_category(
        self,
        transactions: List[Dict],
        category_labels: Optional[Dict[str, str]] = None,
    ) -> List[Dict]:
        """Analyze spending breakdown by category (deterministic)"""
        print("   🏷️ Analyzing spending by category...")
        
        # Only analyze debit transactions (money going out)
        debit_transactions = [t for t in transactions if self._is_spending_debit(t)]
        total_spent = sum(t['amount'] for t in debit_transactions)
        
        # Group by category
        category_totals = {}
        category_counts = {}
        category_transactions = {}
        
        for txn in debit_transactions:
            cat = txn['category']
            category_totals[cat] = category_totals.get(cat, 0) + txn['amount']
            category_counts[cat] = category_counts.get(cat, 0) + 1
            
            if cat not in category_transactions:
                category_transactions[cat] = []
            category_transactions[cat].append(txn)
        
        # Build analysis
        category_analysis = []
        for category, total in category_totals.items():
            percentage = (total / total_spent * 100) if total_spent > 0 else 0
            avg_per_transaction = total / category_counts[category]
            
            # Find largest transaction in this category
            largest_txn = max(category_transactions[category], 
                            key=lambda x: x['amount'])
            
            category_analysis.append({
                'category': category,
                'category_label': resolve_category_label(category, category_labels),
                'category_type': 'user_custom' if is_custom_category(category) else 'system',
                'total': total,
                'percentage': percentage,
                'transaction_count': category_counts[category],
                'average_per_transaction': avg_per_transaction,
                'largest_transaction': {
                    'description': largest_txn['description'],
                    'amount': largest_txn['amount'],
                    'date': largest_txn['date']
                }
            })
        
        # Sort by total spending (highest first)
        return sorted(category_analysis, key=lambda x: x['total'], reverse=True)
    
    def _identify_spending_patterns(
        self,
        transactions: List[Dict],
        category_labels: Optional[Dict[str, str]] = None,
    ) -> Dict:
        """Identify interesting spending patterns (deterministic)"""
        print("   🔍 Identifying spending patterns...")
        
        debit_transactions = [t for t in transactions if self._is_spending_debit(t)]
        
        if not debit_transactions:
            return {}
        
        # Find top merchants
        merchant_totals = {}
        for txn in debit_transactions:
            # Get base merchant name (remove numbers/codes)
            merchant = re.sub(r'[#\d]*$', '', txn['description']).strip()
            merchant_totals[merchant] = merchant_totals.get(merchant, 0) + txn['amount']
        
        top_merchants = sorted(merchant_totals.items(), 
                             key=lambda x: x[1], reverse=True)[:5]
        
        # Find largest single transaction
        largest_transaction = max(debit_transactions, key=lambda x: x['amount'])
        
        # Count transactions by day of week (if we had more data)
        # For now, just basic patterns
        
        return {
            'top_merchants': [
                {'name': merchant, 'total': total} 
                for merchant, total in top_merchants
            ],
            'largest_single_purchase': {
                'description': largest_transaction['description'],
                'amount': largest_transaction['amount'],
                'date': largest_transaction['date'],
                'category': largest_transaction['category'],
                'category_label': resolve_category_label(
                    largest_transaction['category'], category_labels
                ),
                'category_type': (
                    'user_custom'
                    if is_custom_category(largest_transaction['category'])
                    else 'system'
                ),
            },
            'unique_merchants': len(merchant_totals),
            'average_transactions_per_day': len(debit_transactions) / 30
        }

    def _is_spending_debit(self, transaction: Dict) -> bool:
        return bool(transaction.get('is_debit')) and bool(transaction.get('effective_is_spending', True))

    def _is_income_credit(self, transaction: Dict) -> bool:
        return (not bool(transaction.get('is_debit'))) and bool(transaction.get('effective_is_income', True))
    
    def _generate_basic_insights(self, summary: Dict, category_analysis: List[Dict]) -> List[str]:
        """Generate template-based insights (deterministic)"""
        print("   💡 Generating basic insights...")
        
        insights = []
        
        # Spending insights
        if summary['total_spent'] > 0:
            insights.append(f"You spent ${summary['total_spent']:.2f} across {summary['debit_count']} transactions")
            insights.append(f"Average spending per transaction: ${summary['average_transaction']:.2f}")
            insights.append(f"Average daily spending: ${summary['average_daily_spending']:.2f}")
        
        # Category insights
        if category_analysis:
            top_category = category_analysis[0]
            top_label = top_category.get('category_label', top_category['category'])
            insights.append(f"Your top spending category is {top_label} at {top_category['percentage']:.1f}% of total")
            
            if top_category['percentage'] > 30:
                insights.append(f"⚠️ {top_label} represents a large portion of your spending")
        
        # Income vs spending
        if summary['net_change'] > 0:
            insights.append(f"✅ Positive cash flow: +${summary['net_change']:.2f}")
        else:
            insights.append(f"⚠️ Negative cash flow: ${summary['net_change']:.2f}")
        
        return insights
    
    def _generate_ai_insights(self, summary: Dict, category_analysis: List[Dict], patterns: Dict) -> Optional[List[str]]:
        """Generate personalized insights using LLM (0-1 LLM call)"""
        print("   🤖 Generating AI insights...")
        
        if not self.llm:
            return None
        
        # Prepare data for the LLM
        analysis_data = {
            'spending_summary': summary,
            'top_categories': category_analysis[:5],  # Top 5 categories
            'spending_patterns': patterns
        }
        
        system_prompt = """You are a personal finance advisor. Analyze this spending data and provide 3-5 personalized insights and recommendations. Be specific and actionable.

Focus on:
1. Spending patterns and potential areas for improvement
2. Budget allocation suggestions
3. Specific actionable recommendations

Categories marked category_type=user_custom are temporary reporting buckets chosen by the user. Do not infer whether they are fixed, variable, discretionary, unnecessary, or reducible solely from their label. Do not treat them as learned merchant categories.

Keep insights concise and practical."""

        user_prompt = f"Analyze this spending data and provide personalized insights:\n{json.dumps(analysis_data, indent=2)}"
        
        try:
            response = self.llm.make_call(user_prompt, system_prompt)
            
            if response:
                # Parse response into list of insights
                insights = [insight.strip() for insight in response.split('\n') if insight.strip()]
                return insights[:5]  # Limit to 5 insights
            
        except Exception as e:
            print(f"   ❌ AI insights failed: {e}")
        
        return None
    
    def _print_analysis_summary(self, result: Dict):
        """Print a beautiful summary of the analysis"""
        summary = result['financial_summary']
        categories = result['category_breakdown']
        
        print(f"\n📈 ANALYSIS COMPLETE:")
        print(f"   💰 Total Spent: ${summary['total_spent']:.2f}")
        print(f"   💵 Total Income: ${summary['total_income']:.2f}")
        print(f"   📊 Net Change: ${summary['net_change']:.2f}")
        
        if categories:
            top_label = categories[0].get('category_label', categories[0]['category'])
            print(f"   🏆 Top Category: {top_label} ({categories[0]['percentage']:.1f}%)")
        
        print(f"   🤖 LLM calls made: {self.llm_calls_made}")
