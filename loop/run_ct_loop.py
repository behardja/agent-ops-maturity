"""The Continuous-Iteration loop driver — the heart of Agent Ops L1.

Shared driver: one copy runs the loop for ANY agent. Point it at an agent folder
with --agent-dir; everything agent-specific (evalset, criteria, model, threshold
policy, results location) is read from agents/<name>/. Run it per agent to
close-loop iterate each one independently.

One process, signal-source-agnostic trigger. However it's entered — an online
drift alert, a scheduled offline eval, or a human on demand — the loop is the
same four steps:

    trigger -> hill climb -> evaluate -> good enough? -> deploy

Runs unattended by default; a human approval can sit at the threshold in
cautious-rollout mode (--require-approval).
"""

import argparse
import os
import subprocess
import sys

import yaml

from hillclimb_prompt import optimize_prompt
from hillclimb_model import migrate_model


def resolve_engine(agent_dir, cli_engine):
    """Engine from --engine, else agent.yaml eval.engine, else 'local'."""
    if cli_engine:
        return cli_engine
    try:
        with open(os.path.join(agent_dir, "agent.yaml")) as f:
            return (yaml.safe_load(f).get("eval") or {}).get("engine", "local")
    except (OSError, AttributeError):
        return "local"


def evaluate(agent_dir, out, engine="local"):
    """Step 2 — run the offline threshold check over the agent's golden evalset.

    `engine` selects the scoring backend (local ADK or managed GCP Agent Evaluation);
    both write the same results schema. The optimizer's inner scoring always stays local.
    """
    cmd = [sys.executable, "eval_tool/run_eval.py", "--agent-dir", agent_dir, "--out", out]
    if engine:
        cmd += ["--engine", engine]
    subprocess.run(cmd, check=True)


def threshold_check(agent_dir, candidate_results, live_results, policy):
    """Step 3 — 'good enough?': candidate matches live within noise, no regressions."""
    result = subprocess.run(
        [
            sys.executable, "eval_tool/compare.py",
            "--agent-dir", agent_dir,
            "--candidate", candidate_results,
            "--live", live_results,
            "--policy", policy,
        ]
    )
    return result.returncode == 0


def deploy(agent_dir):
    """Step 4 — canary the new revision; it auto-registers in Agent Registry."""
    subprocess.run(
        [sys.executable, "deployment/deploy_agent.py", "--agent-dir", agent_dir],
        check=True,
    )


def run_loop(agent_dir, knob, max_iters, policy, require_approval, no_deploy=False,
             engine="local"):
    live_results = os.path.join(agent_dir, "results/live.json")
    candidate_results = os.path.join(agent_dir, "results/candidate.json")

    # Baseline: score the live agent once so the threshold check has something to match.
    evaluate(agent_dir, live_results, engine)

    for i in range(1, max_iters + 1):
        print(f"\n=== hill-climb iteration {i}/{max_iters} (knob={knob}) ===")

        # Step 1 — hill climb: produce a candidate. Two combinable knobs. Each
        # returns the agent-dir to evaluate (the model knob also sets MODEL).
        # NOTE: the optimizer's INNER scoring (hillclimb_prompt -> run_eval.run_engine)
        # stays on the fast local engine by design — intermediate candidates are
        # throwaway, so we don't spend managed-eval calls on them.
        candidate_dir = agent_dir
        if knob in ("prompt", "both"):
            candidate_dir = optimize_prompt(agent_dir)
        if knob in ("model", "both"):
            candidate_dir = migrate_model(agent_dir)

        # Step 2 — evaluate the candidate offline (same engine as the baseline).
        evaluate(candidate_dir, candidate_results, engine)

        # Step 3 — good enough?
        if not threshold_check(agent_dir, candidate_results, live_results, policy):
            print("threshold FAIL — loop back to hill climb")
            continue

        # Threshold cleared: the candidate met the Final Response Quality threshold.
        # Deploying is a separate decision — skip it when --no-deploy (the loop's
        # job is to catch the trigger and prove the threshold is met; a
        # human/automation decides the canary rollout).
        if no_deploy:
            print("threshold PASS — candidate cleared the threshold (no-deploy; "
                  "deploy separately)")
            return

        if require_approval and input("Threshold passed. Deploy? [y/N] ").lower() != "y":
            print("human declined — stopping")
            return

        # Step 4 — deploy (canary). Online monitor is the post-deploy safety net.
        deploy(candidate_dir)
        print("deployed new revision; cycle complete")
        return

    print(f"no candidate cleared the threshold in {max_iters} iterations")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default="agents/brand-guidelines-checker",
                    help="which agent to close-loop iterate")
    ap.add_argument("--knob", choices=["prompt", "model", "both"], default="prompt",
                    help="which hill-climb knob to turn")
    ap.add_argument("--max-iters", type=int, default=3)
    ap.add_argument("--policy", choices=["match", "beat"], default="match")
    ap.add_argument("--require-approval", action="store_true",
                    help="cautious-rollout mode: a human approves the threshold")
    ap.add_argument("--no-deploy", action="store_true",
                    help="stop once the threshold passes; don't canary-deploy "
                         "(deploy as a separate, deliberate step)")
    ap.add_argument("--engine", choices=["local", "managed"],
                    help="eval backend for the baseline + candidate scoring. Defaults to "
                         "agent.yaml eval.engine, else 'local'. The optimizer's inner "
                         "scoring always stays local.")
    args = ap.parse_args()
    engine = resolve_engine(args.agent_dir, args.engine)
    run_loop(args.agent_dir, args.knob, args.max_iters, args.policy,
             args.require_approval, args.no_deploy, engine)


if __name__ == "__main__":
    main()
