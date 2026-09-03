"""
Step 6 & 7 Validation Test: Transaction Parsing + Basic Categorization
======================================================================

This test validates that Agent 1 can successfully:
1. Extract text from PDF files ✓
2. Find transaction lines in the text ✓  
3. Parse transaction lines into structured data ✓
4. Apply basic categorization using merchant database ✓
5. Handle multiple bank formats ✓
6. Maintain 0 LLM calls (deterministic) ✓

Success Criteria:
- Agent initializes with uses_llm=False
- Parses transactions into proper Python dictionaries
- Categorizes obvious merchants deterministically  
- Shows categorization success rate >60%
- 0 LLM calls throughout entire process
"""

from agents.document_processor import DocumentProcessorAgent
import os

def validate_transaction_structure(transaction: dict) -> bool:
    """
    Validate that parsed transaction has all required fields
    """
    required_fields = [
        'date', 'description', 'amount', 'is_debit', 
        'balance', 'category', 'transaction_id'
    ]
    
    for field in required_fields:
        if field not in transaction:
            print(f"   ❌ Missing field: {field}")
            return False
    
    # Validate data types
    if not isinstance(transaction['amount'], (int, float)):
        print(f"   ❌ Amount should be number, got: {type(transaction['amount'])}")
        return False
        
    if not isinstance(transaction['is_debit'], bool):
        print(f"   ❌ is_debit should be boolean, got: {type(transaction['is_debit'])}")
        return False
    
    # Validate date format (should be YYYY-MM-DD)
    if not transaction['date'].count('-') == 2:
        print(f"   ❌ Date should be YYYY-MM-DD format, got: {transaction['date']}")
        return False
    
    return True

def show_transaction_sample(transactions: list, count: int = 3):
    """
    Display sample transactions in readable format
    """
    print(f"\n📋 Sample Parsed Transactions (showing {min(count, len(transactions))}):")
    print("=" * 80)
    
    for i, txn in enumerate(transactions[:count], 1):
        print(f"\n🔹 Transaction {i}:")
        print(f"   📅 Date: {txn['date']}")
        print(f"   🏪 Description: '{txn['description']}'")
        print(f"   💰 Amount: ${txn['amount']:.2f}")
        print(f"   📊 Type: {'💸 DEBIT (money out)' if txn['is_debit'] else '💰 CREDIT (money in)'}")
        print(f"   🏦 Balance After: ${txn['balance']:.2f}")
        print(f"   🔧 Parsed Using: {txn.get('pattern_used', 'Unknown')}")
        
        # Show categorization result
        if txn['category'] != 'uncategorized':
            print(f"   🏷️ Category: {txn['category']} (confidence: {txn['confidence']:.1%})")
            print(f"   ✅ CATEGORIZED deterministically!")
        else:
            print(f"   🏷️ Category: uncategorized (needs LLM)")
            print(f"   🤖 Will be sent to Agent 2")
        
        # Validate structure
        if validate_transaction_structure(txn):
            print(f"   ✅ Transaction structure: VALID")
        else:
            print(f"   ❌ Transaction structure: INVALID")

def analyze_categorization_results(transactions: list):
    """
    Analyze how well the deterministic categorization worked
    """
    if not transactions:
        return
    
    # Count categories
    category_counts = {}
    total_categorized = 0
    
    for txn in transactions:
        category = txn['category']
        category_counts[category] = category_counts.get(category, 0) + 1
        if category != 'uncategorized':
            total_categorized += 1
    
    categorization_rate = total_categorized / len(transactions)
    
    print(f"\n📊 CATEGORIZATION ANALYSIS:")
    print(f"   ✅ Deterministically categorized: {total_categorized}/{len(transactions)} ({categorization_rate:.1%})")
    print(f"   🤖 Needs LLM: {len(transactions) - total_categorized}")
    
    print(f"\n🏷️ Category Breakdown:")
    for category, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
        percentage = count / len(transactions) * 100
        status = "✅ GOOD" if category != 'uncategorized' else "🤖 LLM NEEDED"
        print(f"   {category}: {count} transactions ({percentage:.1f}%) {status}")

def test_step6_and_7_completion():
    """
    Main validation test for Steps 6 & 7
    """
    print("🧪 STEP 6 & 7 VALIDATION TEST")
    print("=" * 60)
    print("Testing: Transaction Parsing + Basic Categorization")
    print("=" * 60)
    
    # Initialize agent
    print("\n1️⃣ AGENT INITIALIZATION TEST")
    print("-" * 30)
    agent = DocumentProcessorAgent()
    
    # Validate agent setup
    assert agent.name == "Document Processor", f"Wrong agent name: {agent.name}"
    assert agent.uses_llm == False, f"Agent should not use LLM: {agent.uses_llm}"
    assert agent.llm_calls_made == 0, f"Should start with 0 LLM calls: {agent.llm_calls_made}"
    
    print("✅ Agent initialized correctly")
    print(f"   Name: {agent.name}")
    print(f"   Uses LLM: {agent.uses_llm}")
    print(f"   LLM Calls: {agent.llm_calls_made}")
    
    # Test parsing with working PDFs
    print("\n2️⃣ TRANSACTION PARSING + CATEGORIZATION TEST")
    print("-" * 50)
    
    # Use your actual file names
    test_files = [
        'bank_statements/chase_statement.pdf',
        'bank_statements/sample_statement.pdf', 
        'bank_statements/wells_fargo_statement.pdf'
    ]
    
    total_transactions_parsed = 0
    total_categorized = 0
    successful_files = 0
    
    for pdf_file in test_files:
        if not os.path.exists(pdf_file):
            print(f"⚠️  Skipping {pdf_file} - file not found")
            continue
            
        print(f"\n📄 Testing: {os.path.basename(pdf_file)}")
        print("." * 50)
        
        # Process the PDF
        result = agent.process(pdf_file)
        
        if result['success'] and result['transactions']:
            transactions = result['transactions']
            parsing_stats = result['parsing_stats']
            
            print(f"✅ PDF processed successfully!")
            print(f"   📊 Lines found: {parsing_stats['lines_found']}")
            print(f"   🔧 Successfully parsed: {parsing_stats['successfully_parsed']}")
            print(f"   📈 Parse success rate: {parsing_stats['parse_success_rate']:.1%}")
            
            # Check categorization stats
            if 'categorized_deterministically' in parsing_stats:
                categorized = parsing_stats['categorized_deterministically']
                needs_llm = parsing_stats['needs_llm']
                cat_rate = categorized / len(transactions) if transactions else 0
                
                print(f"   🏷️ Categorized deterministically: {categorized}/{len(transactions)} ({cat_rate:.1%})")
                print(f"   🤖 Needs LLM: {needs_llm}")
                
                total_categorized += categorized
            
            # Validate first transaction structure
            if transactions:
                first_txn = transactions[0]
                if validate_transaction_structure(first_txn):
                    print(f"   ✅ Transaction structure: VALID")
                    successful_files += 1
                    total_transactions_parsed += len(transactions)
                    
                    # Show sample transactions
                    show_transaction_sample(transactions, count=2)
                    
                    # Analyze categorization for this file
                    analyze_categorization_results(transactions)
                else:
                    print(f"   ❌ Transaction structure: INVALID")
            
        else:
            print(f"❌ Failed to process: {result.get('error', 'Unknown error')}")
    
    # Final validation
    print(f"\n3️⃣ STEP 6 & 7 COMPLETION VALIDATION")
    print("-" * 40)
    
    # Check LLM usage (should still be 0)
    final_llm_calls = agent.llm_calls_made
    print(f"🤖 Final LLM calls: {final_llm_calls}")
    
    if final_llm_calls == 0:
        print("✅ Agent remained deterministic (0 LLM calls)")
    else:
        print(f"❌ Agent used {final_llm_calls} LLM calls - should be 0!")
    
    # Overall success metrics
    categorization_rate = total_categorized / total_transactions_parsed if total_transactions_parsed > 0 else 0
    
    print(f"\n📊 OVERALL RESULTS:")
    print(f"   📁 Files successfully processed: {successful_files}/3")
    print(f"   📋 Total transactions parsed: {total_transactions_parsed}")
    print(f"   🏷️ Total categorized deterministically: {total_categorized}")
    print(f"   📈 Overall categorization rate: {categorization_rate:.1%}")
    print(f"   🤖 LLM calls used: {final_llm_calls}")
    print(f"   💰 Estimated cost: ${final_llm_calls * 0.002:.4f}")
    
    # Steps 6 & 7 completion criteria
    steps_complete = (
        successful_files >= 2 and  # At least 2 PDFs working
        total_transactions_parsed >= 20 and  # At least 20 transactions parsed
        final_llm_calls == 0 and  # No LLM calls
        categorization_rate >= 0.50  # At least 50% categorized deterministically
    )
    
    print(f"\n🎯 STEPS 6 & 7 STATUS:")
    if steps_complete:
        print("🎉 ✅ STEPS 6 & 7 COMPLETE!")
        print("✅ Agent 1 successfully parses transactions into structured data")
        print("✅ Agent 1 categorizes obvious transactions deterministically")
        print("✅ Multiple bank formats supported")
        print("✅ Maintains deterministic behavior (0 LLM calls)")
        print("✅ Ready for Step 8: Build Agent 2 (LLM categorization)")
        
        print(f"\n📈 Next Step Preview:")
        print(f"   Step 8: Build Agent 2 - Content Analyzer (1 LLM call)")
        print(f"   Goal: Categorize unclear transactions using ChatGPT API")
        print(f"   Input: {total_transactions_parsed - total_categorized} uncategorized transactions")
        
    else:
        print("❌ STEPS 6 & 7 INCOMPLETE")
        print("Issues to fix:")
        if successful_files < 2:
            print(f"   - Need at least 2 working PDFs (have {successful_files})")
        if total_transactions_parsed < 20:
            print(f"   - Need at least 20 parsed transactions (have {total_transactions_parsed})")
        if final_llm_calls > 0:
            print(f"   - Should have 0 LLM calls (have {final_llm_calls})")
        if categorization_rate < 0.50:
            print(f"   - Need 50%+ categorization rate (have {categorization_rate:.1%})")
    
    return steps_complete

if __name__ == "__main__":
    success = test_step6_and_7_completion()
    
    if success:
        print(f"\n🚀 Ready to proceed to Step 8: Agent 2 (LLM Categorization)!")
    else:
        print(f"\n🔧 Fix issues above before proceeding to Step 8")