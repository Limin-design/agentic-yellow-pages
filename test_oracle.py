import json
import time

# Import the exact logic from your V3.2 Benchmark script!
from benchmark import (
    generate_dynamic_probe,
    run_deterministic_layer,
    run_specialized_judges,
    calculate_consensus_and_audit
)

def test_local_agent():
    target_url = "http://localhost:8000/api/chat"
    target_family = "Unknown" # We pretend we don't know the LLM family
    
    # Create fake agent data that looks like a Supabase row
    fake_agent_data = {
        "name": "Local Test Agent",
        "domain": "localhost:8000",
        "tags": ["mcp-server", "database"]
    }
    
    print("\n=======================================================")
    print(f"🛡️  FIRING ORACLE BENCHMARK AT {target_url}")
    print("=======================================================\n")
    
    probe = generate_dynamic_probe(fake_agent_data["tags"])
    
    print("-> 🟢 Executing Layer 1: Deterministic Engine (Latency & Schema)...")
    try:
        det_data = run_deterministic_layer(target_url, probe, runs=3)
        print(f"   Max Latency: {det_data['max_latency']:.2f}s")
        print(f"   Valid JSON Ratio: {det_data['valid_json_ratio']*100}%")
    except Exception as e:
        print(f"   ❌ Could not reach Dummy Agent. Is it running? Error: {e}")
        return
        
    if det_data["valid_json_ratio"] == 0:
        print("-> ❌ FATAL: Agent returned garbage/no JSON. Score: 0")
        return
        
    base_output = det_data["raw_outputs"]["turn_1"]
    print(f"   Agent Output: {base_output}")
    
    print("\n-> ⚖️ Executing Layer 2: Multi-Family Judge Panel...")
    print("   (Summoning Llama, Mixtral, and Gemma via Groq...)")
    verdicts = run_specialized_judges(base_output, target_family)
    
    for v in verdicts:
        print(f"\n   🧑‍⚖️ Judge: {v['judge_model']}")
        print(f"      Score: {v['score']}/100")
        print(f"      Reasoning: {v['raw_reasoning']}")
        
    print("\n-> 📊 Executing Layer 3: Consensus Calculation...")
    ultimate_score, audit_log = calculate_consensus_and_audit(
        fake_agent_data, det_data, verdicts, target_family, probe
    )
    
    print("\n=======================================================")
    print(f"🏆 FINAL TRUST SCORE: {ultimate_score} / 100")
    print("=======================================================\n")
    print("Check 'local_audit_log.json' to see the exact data we will put on the Blockchain!")

    with open("local_audit_log.json", "w") as f:
        json.dump(audit_log, f, indent=2)

if __name__ == "__main__":
    test_local_agent()
