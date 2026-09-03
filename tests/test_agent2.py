"""
Test Agent 2: Content Analyzer
==============================
Tests the LLM-based categorization agent
"""

from agents.document_processor import DocumentProcessorAgent
from agents.content_analyzer import ContentAnalyzerAgent
from utils.llm_interface import LLMInterface
import os
import pytest
from dotenv import load_dotenv

pytestmark = pytest.mark.skipif(
    os.getenv('RUN_OPENAI_INTEGRATION_TESTS') != '1',
    reason='Live OpenAI integration test; opt in with RUN_OPENAI_INTEGRATION_TESTS=1',
)

def test_agent2():
    """Test Agent 2 with real data from Agent 1"""
    
    load_dotenv()
    api_key = os.getenv('OPENAI_API_KEY')
    
    print("🧪 TESTING AGENT 2: Content Analyzer")
    print("=" * 50)
    
    # Step 1: Get uncategorized transactions from Agent 1
    print("\n1️⃣ Getting data from Agent 1...")
    agent1 = DocumentProcessorAgent()
    result1 = agent1.process('bank_statements/chase_statement.pdf')
    
    if not result1['success']:
        print("❌ Agent 1 failed - can't test Agent 2")
        return
    
    transactions = result1['transactions']
    uncategorized = [t for t in transactions if t['category'] == 'uncategorized']
    categorized = [t for t in transactions if t['category'] != 'uncategorized']
    
    print(f"   📊 Agent 1 results:")
    print(f"   ✅ Already categorized: {len(categorized)}")
    print(f"   🤖 Needs LLM: {len(uncategorized)}")
    
    if not uncategorized:
        print("   🎉 No uncategorized transactions - Agent 2 not needed!")
        return
    
    # Step 2: Test Agent 2
    print(f"\n2️⃣ Testing Agent 2 with {len(uncategorized)} unclear transactions...")
    
    llm = LLMInterface(api_key)
    agent2 = ContentAnalyzerAgent(llm)
    
    print(f"   Agent 2 name: {agent2.name}")
    print(f"   Uses LLM: {agent2.uses_llm}")
    print(f"   Initial LLM calls: {agent2.llm_calls_made}")
    
    # Process with Agent 2
    final_transactions = agent2.process(transactions)
    
    # Analyze results
    print(f"\n3️⃣ AGENT 2 RESULTS:")
    print(f"   🤖 LLM calls made: {agent2.llm_calls_made}")
    print(f"   💰 Cost: ${llm.get_metrics()['estimated_cost']:.4f}")
    
    # Show what Agent 2 categorized
    newly_categorized = [t for t in final_transactions 
                        if t.get('source') == 'llm']
    
    if newly_categorized:
        print(f"\n🤖 Transactions categorized by Agent 2:")
        for txn in newly_categorized[:5]:  # Show first 5
            print(f"   '{txn['description'][:30]}...' → {txn['category']} ({txn['confidence']:.1%})")
            print(f"      Reasoning: {txn.get('reasoning', 'N/A')}")
    
    # Final system stats
    all_categorized = [t for t in final_transactions if t['category'] != 'uncategorized']
    final_categorization_rate = len(all_categorized) / len(final_transactions)
    
    print(f"\n📊 COMPLETE SYSTEM PERFORMANCE:")
    print(f"   📋 Total transactions: {len(final_transactions)}")
    print(f"   ✅ Agent 1 (deterministic): {len(categorized)}")
    print(f"   🤖 Agent 2 (LLM): {len(newly_categorized)}")
    print(f"   📈 Final categorization rate: {final_categorization_rate:.1%}")
    print(f"   💰 Total LLM calls: {llm.call_count}")
    print(f"   💵 Total cost: ${llm.total_cost:.4f}")
    
    # Success criteria
    success = (
        agent2.llm_calls_made == 1 and  # Exactly 1 LLM call
        final_categorization_rate >= 0.90 and  # 90%+ categorized
        llm.call_count <= 2  # Within project limits
    )
    
    if success:
        print(f"\n🎉 ✅ AGENT 2 TEST PASSED!")
        print(f"✅ Uses exactly 1 LLM call")
        print(f"✅ High categorization success rate")
        print(f"✅ Within cost limits")
        print(f"✅ Ready for Step 9: Agent 3!")
    else:
        print(f"\n❌ AGENT 2 TEST FAILED")
        print(f"Issues to fix before Step 9")

if __name__ == "__main__":
    test_agent2()
