"""Agent-specific tests — the brand-guidelines-checker's own domain rules, BEYOND the central
contract in tests/test_agents.py. The pattern for a single agent: add a file here only when an
agent needs more than the central checks.

Pure: imports agent.py and reads the agent's files; no Google Cloud calls.
"""
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENT_DIR = os.path.join(ROOT, "agents", "brand-guidelines-checker")

# This agent encodes exactly five brand rules — that count is what makes these tests agent-specific.
BRAND_RULES = (1, 2, 3, 4, 5)


def _agent_module():
    spec = importlib.util.spec_from_file_location("brand_agent", os.path.join(AGENT_DIR, "app", "agent.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _golden_cases():
    with open(os.path.join(AGENT_DIR, "eval", "golden.evalset.json")) as f:
        return json.load(f)["eval_cases"]


def test_instruction_enumerates_all_five_rules():
    instr = _agent_module().DEFAULT_INSTRUCTION
    for n in BRAND_RULES:
        assert f"{n}." in instr, f"brand rule {n} is not enumerated in the instruction"


def test_instruction_declares_json_verdict_contract():
    instr = _agent_module().DEFAULT_INSTRUCTION
    assert "verdict" in instr and "PASS" in instr and "FAIL" in instr


def test_golden_exercises_every_brand_rule():
    cited = {v["rule"] for c in _golden_cases() for v in c["expected"].get("violations", [])}
    missing = set(BRAND_RULES) - cited
    assert not missing, f"golden set never exercises brand rule(s): {sorted(missing)}"


def test_weak_baseline_keeps_contract_but_drops_rules():
    # The deliberately-drifted baseline must stay parseable (keeps the verdict contract) yet NOT
    # spell out the rules — that's the premise that lets GEPA rediscover them in NB3.
    weak = open(os.path.join(AGENT_DIR, "eval", "weak_instruction.txt")).read()
    assert "verdict" in weak.lower(), "weak instruction must keep the JSON verdict contract"
    assert not all(f"{n}." in weak for n in BRAND_RULES), "weak instruction should NOT list all rules"
