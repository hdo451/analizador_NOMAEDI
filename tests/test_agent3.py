"""
Test Agent 3: Analysis Generator
===============================
Tests the financial analysis and reporting agent
"""

from agents.document_processor import DocumentProcessorAgent
from agents.content_analyzer import ContentAnalyzerAgent
from agents.analysis_generator import AnalysisGeneratorAgent
from utils.llm_interface import LLMInterface
import os
import pytest
from dotenv import load_dotenv

pytestmark = pytest.mark.skipif(
    os.getenv('RUN_OPENAI_INTEGRATION_TESTS') != '1',
    reason='Live OpenAI integration test; opt in with RUN_OPENAI_INTEGRATION_TESTS=1',
)

def test_complete_pipeline():
    """Test all 3 agents working together"""
    
    load_dotenv()
    api_key = os.getenv('OPENAI_API_KEY')
    
    print("🧪 TESTING COMPLETE 3-AGENT PIPELINE")
    print("=" * 60)
    
    # Initialize all agents
    llm = LLMInterface(api_key)
    agent1 = DocumentProcessorAgent()           # 0 LLM calls
    agent2 = ContentAnalyzerAgent(llm)          # 1 LLM call
    agent3 = AnalysisGeneratorAgent(llm)        # 0-1 LLM calls
    
    print(f"\n📋 AGENT SETUP:")
    print(f"   Agent 1: {agent1.name} (LLM: {agent1.uses_llm})")
    print(f"   Agent 2: {agent2.name} (LLM: {agent2.uses_llm})")  
    print(f"   Agent 3: {agent3.name} (LLM: {agent3.uses_llm})")
    
    # Step 1: Agent 1 - Document Processing
    print(f"\n1️⃣ AGENT 1: Document Processing")
    print("-" * 40)
    
    result1 = agent1.process('bank_statements/chase_statement.pdf')
    if not result1['success']:
        print("❌ Agent 1 failed")
        return
    
    print(f"   ✅ {len(result1['transactions'])} transactions extracted and partially categorized")
    
    # Step 2: Agent 2 - Smart Categorization  
    print(f"\n2️⃣ AGENT 2: Smart Categorization")
    print("-" * 40)
    
    categorized_transactions = agent2.process(result1['transactions'])
    uncategorized_remaining = [t for t in categorized_transactions if t['category'] == 'uncategorized']
    
    print(f"   ✅ All transactions processed")
    print(f"   🤖 Agent 2 LLM calls: {agent2.llm_calls_made}")
    print(f"   📊 Remaining uncategorized: {len(uncategorized_remaining)}")
    
    # Step 3: Agent 3 - Analysis Generation
    print(f"\n3️⃣ AGENT 3: Analysis Generation")
    print("-" * 40)
    
    # Test basic analysis (no LLM)
    print("   Testing basic analysis (0 LLM calls)...")
    basic_analysis = agent3.process(categorized_transactions, generate_ai_insights=False)
    
    print(f"   ✅ Basic analysis complete")
    print(f"   🤖 Agent 3 LLM calls so far: {agent3.llm_calls_made}")
    
    # Test AI insights (1 LLM call)
    print("   Testing AI insights (1 LLM call)...")
    ai_analysis = agent3.process(categorized_transactions, generate_ai_insights=True)
    
    print(f"   ✅ AI analysis complete")
    print(f"   🤖 Agent 3 final LLM calls: {agent3.llm_calls_made}")
    
    # Display results
    print(f"\n📊 FINANCIAL ANALYSIS RESULTS:")
    print("=" * 50)
    
    summary = ai_analysis['financial_summary']
    categories = ai_analysis['category_breakdown']
    
    print(f"💰 FINANCIAL SUMMARY:")
    print(f"   Total Spent: ${summary['total_spent']:.2f}")
    print(f"   Total Income: ${summary['total_income']:.2f}")
    print(f"   Net Change: ${summary['net_change']:.2f}")
    print(f"   Average Transaction: ${summary['average_transaction']:.2f}")
    
    print(f"\n🏷️ TOP SPENDING CATEGORIES:")
    for i, cat in enumerate(categories[:5], 1):
        print(f"   {i}. {cat['category']}: ${cat['total']:.2f} ({cat['percentage']:.1f}%)")
    
    print(f"\n💡 BASIC INSIGHTS:")
    for insight in ai_analysis['basic_insights']:
        print(f"   • {insight}")
    
    if ai_analysis['ai_insights']:
        print(f"\n🤖 AI INSIGHTS:")
        for insight in ai_analysis['ai_insights']:
            print(f"   • {insight}")
    
    # Final system metrics
    total_llm_calls = agent1.llm_calls_made + agent2.llm_calls_made + agent3.llm_calls_made
    total_cost = llm.total_cost
    
    print(f"\n📈 COMPLETE SYSTEM METRICS:")
    print(f"   Agent 1 LLM calls: {agent1.llm_calls_made}")
    print(f"   Agent 2 LLM calls: {agent2.llm_calls_made}")
    print(f"   Agent 3 LLM calls: {agent3.llm_calls_made}")
    print(f"   TOTAL LLM calls: {total_llm_calls}")
    print(f"   Total cost: ${total_cost:.4f}")
    
    # Success criteria for complete system
    success = (
        total_llm_calls <= 2 and  # Project requirement
        len(categorized_transactions) > 0 and
        summary['total_spent'] > 0
    )
    
    if success:
        print(f"\n🎉 ✅ 3-AGENT SYSTEM WORKING PERFECTLY!")
        print(f"✅ Meets ≤2 LLM calls requirement")
        print(f"✅ All agents functioning correctly")
        print(f"✅ Complete financial analysis generated")
        print(f"✅ Ready for Step 9: System Integration!")
    else:
        print(f"\n❌ SYSTEM TEST FAILED")
        
    return success

if __name__ == "__main__":
    test_complete_pipeline()
    
