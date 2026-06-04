"""Hill-climb knob (b): model migration — the showcase run.

Same agent, same golden evalset, swap `model=` for a newer model. If Final
Response Quality holds or improves with no regressions, the candidate clears the
threshold and gets canaried. This is exactly the "keep agents current as models evolve"
workflow — and because the loop is human-triggerable, you don't have to wait for
a drift alert to run it.

Each agent reads its model from the MODEL env var (see agents/<name>/app/agent.py),
so a migration candidate is just the same agent-dir with MODEL overridden.
"""

import os

# Candidate model to migrate to. Override per run.
CANDIDATE_MODEL = os.environ.get("CANDIDATE_MODEL", "gemini-3.5-flash")


def migrate_model(agent_dir="agents/brand-guidelines-checker", model=CANDIDATE_MODEL):
    """Select the candidate model and return the agent-dir to evaluate.

    Setting MODEL here means a fresh load of the agent builds it on the candidate
    model — no code edit, same instruction, same evalset, same agent folder.
    """
    os.environ["MODEL"] = model
    print(f"model-migration candidate for {agent_dir}: MODEL={model}")
    return agent_dir


if __name__ == "__main__":
    print(migrate_model())
