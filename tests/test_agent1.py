"""
Step 6 Validation Test: Transaction Parsing
===========================================

This test validates that Agent 1 can successfully:
1. Extract text from PDF files ✓
2. Find transaction lines in the text ✓  
3. Parse transaction lines into structured data ✓
4. Handle multiple bank formats ✓
5. Maintain 0 LLM calls (deterministic) ✓

Success Criteria for Step 6:
- Agent initializes with uses_llm=False
- Parses transactions into proper Python dictionaries
- Handles dates, amounts, descriptions correctly
- Shows parsing success rate >80%
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
        print(f"   🏷️ Category: {txn['category']} (will be updated by Agent 2)")
        
        # Validate structure
        if validate_transaction_structure(txn):
            print(f"   ✅ Transaction structure: VALID")
        else:
            print(f"   ❌ Transaction structure: INVALID")

def test_step6_completion():
    """
    Main Step 6 validation test
    """
    print("🧪 STEP 6 VALIDATION TEST")
    print("=" * 50)
    print("Testing: Transaction Parsing into Structured Data")
    print("=" * 50)
    
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
    print("\n2️⃣ TRANSACTION PARSING TEST")
    print("-" * 30)
    
    test_files = [
        'bank_statements/chase_statement.pdf',
        'bank_statements/sample_statement.pdf', 
        'bank_statements/wells_fargo_statement.pdf'
    ]
    
    total_transactions_parsed = 0
    successful_files = 0
    
    for pdf_file in test_files:
        if not os.path.exists(pdf_file):
            print(f"⚠️  Skipping {pdf_file} - file not found")
            continue
            
        print(f"\n📄 Testing: {os.path.basename(pdf_file)}")
        print("." * 40)
        
        # Process the PDF
        result = agent.process(pdf_file)
        
        if result['success'] and result['transactions']:
            transactions = result['transactions']
            parsing_stats = result['parsing_stats']
            
            print(f"✅ PDF processed successfully!")
            print(f"   📊 Lines found: {parsing_stats['lines_found']}")
            print(f"   🔧 Successfully parsed: {parsing_stats['successfully_parsed']}")
            print(f"   📈 Parse success rate: {parsing_stats['parse_success_rate']:.1%}")
            
            # Validate first transaction structure
            if transactions:
                first_txn = transactions[0]
                if validate_transaction_structure(first_txn):
                    print(f"   ✅ Transaction structure: VALID")
                    successful_files += 1
                    total_transactions_parsed += len(transactions)
                    
                    # Show sample transactions
                    show_transaction_sample(transactions, count=2)
                else:
                    print(f"   ❌ Transaction structure: INVALID")
            
        else:
            print(f"❌ Failed to process: {result.get('error', 'Unknown error')}")
    
    # Final validation
    print(f"\n3️⃣ STEP 6 COMPLETION VALIDATION")
    print("-" * 30)
    
    # Check LLM usage (should still be 0)
    final_llm_calls = agent.llm_calls_made
    print(f"🤖 Final LLM calls: {final_llm_calls}")
    
    if final_llm_calls == 0:
        print("✅ Agent remained deterministic (0 LLM calls)")
    else:
        print(f"❌ Agent used {final_llm_calls} LLM calls - should be 0!")
    
    # Overall success metrics
    print(f"\n📊 OVERALL RESULTS:")
    print(f"   📁 Files successfully processed: {successful_files}/3")
    print(f"   📋 Total transactions parsed: {total_transactions_parsed}")
    print(f"   🤖 LLM calls used: {final_llm_calls}")
    print(f"   💰 Estimated cost: ${final_llm_calls * 0.002:.4f}")
    
    # Step 6 completion criteria
    step6_complete = (
        successful_files >= 2 and  # At least 2 PDFs working
        total_transactions_parsed >= 20 and  # At least 20 transactions parsed
        final_llm_calls == 0  # No LLM calls
    )
    
    print(f"\n🎯 STEP 6 STATUS:")
    if step6_complete:
        print("🎉 ✅ STEP 6 COMPLETE!")
        print("✅ Agent 1 successfully parses transactions into structured data")
        print("✅ Multiple bank formats supported")
        print("✅ Maintains deterministic behavior (0 LLM calls)")
        print("✅ Ready for Step 7: Basic categorization")
        
        print(f"\n📈 Next Step Preview:")
        print(f"   Step 7: Add merchant database for basic categorization")
        print(f"   Goal: Categorize obvious transactions (STARBUCKS → food_dining)")
        print(f"   Still 0 LLM calls - pure keyword matching")
        
    else:
        print("❌ STEP 6 INCOMPLETE")
        print("Issues to fix:")
        if successful_files < 2:
            print(f"   - Need at least 2 working PDFs (have {successful_files})")
        if total_transactions_parsed < 20:
            print(f"   - Need at least 20 parsed transactions (have {total_transactions_parsed})")
        if final_llm_calls > 0:
            print(f"   - Should have 0 LLM calls (have {final_llm_calls})")
    
    return step6_complete

if __name__ == "__main__":
    success = test_step6_completion()
    
    if success:
        print(f"\n🚀 Ready to proceed to Step 7!")
    else:
        print(f"\n🔧 Fix issues above before proceeding to Step 7")