"""The 'good enough?' threshold check: compare a candidate revision against the live agent.

Decision rule (locked, see plan §7 and §4a):
  PASS the threshold when the candidate MATCHES the live agent's Final Response Quality
  within the bootstrap noise band AND shows zero regressions on existing
  golden cases. We do not chase a higher bare mean that sits inside the noise.
  (A stricter 'must beat' policy would instead require the candidate's CI
  lower bound to clear the live mean — toggled with --policy beat.)

Two distinct statistics, kept separate:
  * Variance of the METRIC — bootstrap CI on Final Response Quality. Cheap: resamples
    per-case scores already computed, no extra inference. This has threshold teeth.
  * Variance of the OUTPUT — behavioral, run the same input N times. Computed
    by run_eval (optional) and only LOGGED here, never part of the threshold.

Shared threshold check — one copy for every agent. Point it at an agent folder with
--agent-dir; the candidate/live result files and the bootstrap resamples default
from agents/<name>/ (results/ + agent.yaml).

Usage:
    python eval_tool/compare.py --agent-dir agents/brand-guidelines-checker
"""

import argparse
import json
import os
import random

import yaml


def final_response_quality_scores(result):
    """Per-case Final Response Quality scores from a run_eval output file.

    This is the continuous LLM-judge score (rubric_based_final_response_quality_v1
    mean), so the bootstrap CI quantifies real metric uncertainty, not a coarse 0/1.
    """
    return [r["final_response_quality"] for r in result["per_case"]]


def bootstrap_ci(scores, resamples=2000, alpha=0.05, seed=0):
    """Percentile bootstrap CI on the mean of 0/1 per-case scores."""
    if not scores:
        return (0.0, 0.0, 0.0)
    rng = random.Random(seed)
    n = len(scores)
    means = []
    for _ in range(resamples):
        sample = [scores[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int((alpha / 2) * resamples)]
    hi = means[int((1 - alpha / 2) * resamples) - 1]
    return (sum(scores) / n, lo, hi)


def regressions(candidate, live):
    """Golden case ids the live agent passed but the candidate fails.

    Keyed on the all-metrics `passed` flag (final_eval_status PASSED on every
    run): a regression is a case that cleared every threshold metric live but no
    longer does on the candidate.
    """
    live_by_id = {r["id"]: r["passed"] for r in live["per_case"]}
    out = []
    for r in candidate["per_case"]:
        if r["passed"] == 0 and live_by_id.get(r["id"]) == 1:
            out.append(r["id"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default="agents/brand-guidelines-checker",
                    help="defaults candidate/live/resamples/policy from this agent")
    ap.add_argument("--candidate", help="defaults to <agent-dir>/results/candidate.json")
    ap.add_argument("--live", help="defaults to <agent-dir>/results/live.json")
    ap.add_argument("--resamples", type=int, help="defaults to agent.yaml eval.bootstrap_resamples")
    ap.add_argument("--policy", choices=["match", "beat"],
                    help="defaults to agent.yaml eval.policy")
    args = ap.parse_args()

    cfg = {}
    cfg_path = os.path.join(args.agent_dir, "agent.yaml")
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
    eval_cfg = cfg.get("eval", {})

    candidate_path = args.candidate or os.path.join(args.agent_dir, "results/candidate.json")
    live_path = args.live or os.path.join(args.agent_dir, "results/live.json")
    resamples = args.resamples or eval_cfg.get("bootstrap_resamples", 2000)
    policy = args.policy or eval_cfg.get("policy", "match")

    with open(candidate_path) as f:
        cand = json.load(f)
    with open(live_path) as f:
        live = json.load(f)

    c_mean, c_lo, c_hi = bootstrap_ci(final_response_quality_scores(cand), resamples)
    l_mean, l_lo, l_hi = bootstrap_ci(final_response_quality_scores(live), resamples)
    regressed = regressions(cand, live)

    if policy == "beat":
        # CI lower bound of candidate clears the live mean.
        quality_ok = c_lo > l_mean
        rule = "candidate CI lower bound > live mean"
    else:
        # Match within noise: candidate mean not below the live CI lower bound.
        quality_ok = c_mean >= l_lo
        rule = "candidate mean within live noise band (>= live CI lower bound)"

    passed = quality_ok and not regressed

    print(f"candidate final_response_quality = {c_mean:.3f}  CI[{c_lo:.3f}, {c_hi:.3f}]")
    print(f"live      final_response_quality = {l_mean:.3f}  CI[{l_lo:.3f}, {l_hi:.3f}]")
    print(f"regressions: {regressed or 'none'}")
    print(f"policy={policy} ({rule})")
    print(f"THRESHOLD: {'PASS' if passed else 'FAIL'}")

    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
