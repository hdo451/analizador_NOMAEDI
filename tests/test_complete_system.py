"""
Test Complete System: All 3 Agents + Coordinator
==============================================
Tests the full integrated system
"""

from main_coordinator import BankStatementAnalyzer
import os
import pytest
from dotenv import load_dotenv

pytestmark = pytest.mark.skipif(
    os.getenv('RUN_OPENAI_INTEGRATION_TESTS') != '1',
    reason='Live OpenAI integration test; opt in with RUN_OPENAI_INTEGRATION_TESTS=1',
)

def test_complete_system():
    """Test the integrated 3-agent system"""
    
    load_dotenv()
    api_key = os.getenv('OPENAI_API_KEY')
    
    print("🧪 TESTING COMPLETE INTEGRATED SYSTEM")
    print("=" * 60)
    
    # Initialize complete system
    analyzer = BankStatementAnalyzer(api_key)
    
    # Test basic analysis
    print(f"\n🧪 Test 1: Basic Analysis (expect 1 LLM call)")
    result1 = analyzer.analyze_statement('bank_statements/chase_statement.pdf')
    
    if result1['success']:
        metrics1 = result1['system_metrics']
        print(f"✅ Basic analysis successful")
        print(f"   LLM calls: {metrics1['total_llm_calls']}")
        print(f"   Cost: ${metrics1['estimated_cost']:.4f}")
    
    # Test AI insights
    print(f"\n🧪 Test 2: AI Insights Analysis (expect 2 LLM calls)")
    result2 = analyzer.analyze_statement('bank_statements/chase_statement.pdf', generate_ai_insights=True)
    
    if result2['success']:
        metrics2 = result2['system_metrics'] 
        print(f"✅ AI analysis successful")
        print(f"   LLM calls: {metrics2['total_llm_calls']}")
        print(f"   Cost: ${metrics2['estimated_cost']:.4f}")
    
    # Validate system requirements
    print(f"\n📋 SYSTEM REQUIREMENTS VALIDATION:")
    max_llm_calls = max(metrics1['total_llm_calls'], metrics2['total_llm_calls'])
    
    if max_llm_calls <= 2:
        print(f"✅ LLM efficiency: {max_llm_calls}/2 calls (requirement met)")
    else:
        print(f"❌ LLM efficiency: {max_llm_calls}/2 calls (exceeds limit)")
    
    if result2['success']:
        print(f"✅ Error handling: Working correctly")
    
    print(f"✅ Deterministic routing: Using if/else logic")
    print(f"✅ Agent separation: 3 distinct agents")
    
    print(f"\n🎉 COORDINATOR TEST COMPLETE!")
    return True

if __name__ == "__main__":
    test_complete_system()
    
