"""Test setup — puts the repo root + eval_tool/ on sys.path so the suite can import the
loop/eval modules.

Two categories:
  * Central tests (test_framework.py + test_agents.py) — the eval/loop CODE every agent uses
    AND the generic contract validated against EVERY agents/*/ (add an agent and it's checked
    automatically). Nothing here is tied to one agent.
  * Agent-specific tests (tests/agents/<agent>.py) — one particular agent's own rules; add a
    file here only when an agent needs more than the central contract.

All UNIT / mock — no Google Cloud calls — so CI runs them on every PR without credentials.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "eval_tool")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
