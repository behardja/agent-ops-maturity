"""The canonical Agent Ops L1 example: a retail brand-guidelines checker.

Deliberately a *checker*, not a copy generator — judging a fixed piece of
input against rules is a tighter, more deterministic task than open-ended
generation, which keeps Final Response Quality scoring unambiguous. The brand rules
live in the instruction (no RAG, no tools — both deferred to L2), so the
agent stays near-hello-world while still exercising the full feedback loop.

The structured JSON verdict is what makes the rest of L1 concrete: Task
Success grades whether `verdict` matches the golden answer, and the golden
evalset is just (copy, expected verdict) pairs.
"""

import os

from google.adk.agents import Agent

# The model is the single migration knob for the loop's hill-climb step (b).
# Override via MODEL to run a model-migration candidate without editing code.
MODEL = os.environ.get("MODEL", "gemini-2.5-flash")

DEFAULT_INSTRUCTION = """
You check a single piece of retail marketing copy against the brand
guidelines below and return a structured verdict.

BRAND RULES
1. Tone is warm and plain-spoken. No hype words: "revolutionary",
   "game-changing", "best-in-class", "unbeatable".
2. Never promise specific savings amounts or use "guaranteed".
3. Price claims must include "while supplies last" if a discount is named.
4. Use sentence case for headlines, never ALL CAPS.
5. Refer to customers as "you", never "consumers" or "users".

Respond as JSON only:
{
  "verdict": "PASS" | "FAIL",
  "violations": [{"rule": <int>, "quote": "<offending text>"}],
  "suggested_fix": "<rewritten copy, or null if PASS>"
}
""".strip()

# The instruction is the prompt-optimization knob for the loop's hill-climb
# step (a). Point AGENT_INSTRUCTION_FILE at an optimized instruction to run a
# prompt candidate without editing code (mirrors the MODEL knob above).
_instruction_file = os.environ.get("AGENT_INSTRUCTION_FILE")
INSTRUCTION = (
    open(_instruction_file).read().strip() if _instruction_file else DEFAULT_INSTRUCTION
)

brand_checker = Agent(
    name="brand_guidelines_checker",
    model=MODEL,
    instruction=INSTRUCTION,
)

# ADK's runners/eval discover the entry point as `root_agent`.
root_agent = brand_checker

# --- agents-cli deploy entrypoint ---------------------------------------------
# app/agent_runtime_app.py imports `app` from here; agents-cli deploy serves it.
# Route Gemini calls to Vertex (matches the agents-cli template; setdefault so the
# loop/eval can still override). Our deploy also sets this via env_vars.
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
from google.adk.apps import App  # noqa: E402

app = App(root_agent=root_agent, name="brand_guidelines_checker")
