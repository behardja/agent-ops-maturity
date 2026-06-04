# Continuous-Iteration loop — runbook

How the loop runs, and the checklist for operating it. Level 1 ≡ MLOps
Continuous Training (CT): this loop automates the agent's **improvement +
deployment**. CI/CD around the code is Level 2.

## The loop

One process, signal-source-agnostic trigger:

```
trigger → hill climb → evaluate → good enough? → deploy
```

### Triggers (three entry points, same four steps)

1. **Online (recommended)** — Cloud Monitoring alert on the online monitor's
   Final Response Quality score (`observability/alerts/final_response_quality_alert.yaml`). Catches
   real production decay, including novel inputs the golden set misses.
2. **Scheduled offline (lightest entry)** — run the offline eval on the golden
   set on a schedule (nightly, or after any model release) and alert on drop.
   No live-traffic monitoring required — the cheapest way to clear the L1 bar.
3. **Human on demand** — run `loop/run_ct_loop.py` directly (e.g. "a newer
   model shipped").

### The four steps

1. **Hill climb** — produce a candidate. Two combinable knobs:
   - (a) prompt optimization — ADK `SimplePromptOptimizer`
     (`loop/hillclimb_prompt.py`)
   - (b) model migration — swap `model=` (`loop/hillclimb_model.py`)

   Either alone counts if it clears the threshold.
2. **Evaluate** — offline Agent Evaluation; `eval_tool/run_eval.py` scores the
   candidate over the golden evalset. Two engines (`--engine`, default from
   `agent.yaml` `eval.engine`): **managed** (GCP Agent Evaluation via
   `client.evals.evaluate`; `eval_tool/managed_eval.py`) or **local** (ADK
   `LocalEvalService`). Both write the same results schema. See "Managed vs. local
   eval engine" below.
3. **Good enough?** — `eval_tool/compare.py` runs the threshold check: candidate must **match live
   Final Response Quality within the bootstrap noise band and show zero regressions**.
   Judge "within noise" with the bootstrap CI, not bare means (outputs vary at
   temperature 1). Unattended by default; `--require-approval` puts a human here.
4. **Deploy (to staging)** — canary the new revision **in the staging
   environment**; the online monitor is the post-deploy safety net. The revision
   **auto-registers** in Agent Registry — registration falls out of the deploy,
   not a manual step. **Promotion to production is a separate, always-manual
   approval gate** (see "Staging vs. production" below) — the unattended loop
   stops at staging.

## Managed vs. local eval engine

`eval.engine` (in `agent.yaml` / `configs/defaults.yaml`, default **managed**)
selects how `run_eval.py` scores, following the documented GEAP evaluation workflow:

- **managed** (`eval_tool/managed_eval.py`) — Google Cloud's **Agent Evaluation**.
  Runs the local ADK agent over the golden inputs (`run_inference`) then scores the
  metric menu in one `client.evals.evaluate` call; pass `--dest gs://…` to persist
  results to a Cloud Storage output path (the evaluate-offline "Output data path").
  Needs `google-cloud-aiplatform>=1.154.0`.
- **local** — ADK `LocalEvalService`. Fast, fully offline; the fallback / CI engine.

Both write the **same `live.json` schema**, so `compare.py` and the rest of the loop
are unchanged. The optimizer's **inner hill-climb scoring always stays local**
(intermediate candidates are throwaway — no need to spend managed-eval calls on them).

**Metric menu for this single-turn, tool-less agent.** The predefined Agent
*Final Response Quality* and *Hallucination* raters need a tool trajectory
(`response_steps`) or grounding context this agent doesn't have (they error), so:

- **headline = a custom *Final Response Quality* `LLMMetric`** (our cites_rule /
  actionable_fix rubric), computed by `evaluate`.
- **Safety** + **General Quality** — predefined.

All three are scored in the single `evaluate` call (custom metric inline, per the
manage-metrics docs).

## Two reactions to one drift signal (improve vs. protect)

The online monitor's quality signal drives **two** automated reactions, which must
use **distinct alert scopes** so they never collide:

- **Improve (SLOW)** — `observability/alert.yaml`: a rolling 1h mean over *all*
  production traffic. A sustained drop fires `loop/run_ct_loop.py` to hill-climb a
  better candidate. Topic `<agent>-loop-trigger`; hands-off via
  `deployment/loop_subscriber/`.
- **Protect (FAST)** — `observability/canary_alert.yaml`: a short window scoped to
  the *canary revision only* (`metric.label.revision`). A freshly-shipped dud is
  reverted to the prior known-good revision by `deployment/rollback.py` within its
  bake. Topic `<agent>-rollback-trigger`; hands-off via
  `deployment/rollback_subscriber/`. Walkthrough: `notebooks/04-canary-rollback.ipynb`.

Auto-rollback is safe to automate even under the manual production gate: it only
ever *removes* a bad revision and restores an already-approved one — it never ships
anything new. It protects **staging**; production promotion stays manual.

## Staging vs. production (the production gate)

The unattended auto-deploy in this loop targets a **staging environment** — this
reference uses the sandbox project as staging. That matches GEAP deployment best
practices, which split deploy into two tiers: **automated post-merge validation in
staging** vs. **gated production deployment**. Production promotion is therefore
**always a manual approval gate**: a product owner / agent owner / lead AI engineer
signs off before the candidate replaces the live production agent. The loop
automates everything *up to* the staging canary; the production go/no-go stays a
deliberate human decision and is out of scope for this L1 reference.

## Operating decisions (locked)

- **Default mode = closed-loop / unattended (in staging).** Human judgment is
  front-loaded into the curated golden evalset, not a per-cycle approval. This
  applies to the staging loop; **production promotion is always manually gated**
  (see above). Per-cycle approval on the staging canary is an optional
  cautious-rollout mode (`--require-approval`).
- **No standing threshold-check owner** by default — assign one only in cautious mode.
- **Threshold = match within the noise band + zero regressions** (not
  "strictly beat"). Convergence quirk (accepted, not a safety risk): a
  drift-triggered run may redeploy a candidate that's merely *as good*, leaning
  on the next trigger to retry — nothing worse ships.

## The loop that feeds the loop

Every flagged trace that turns out to be a genuine failure is promoted into the
golden evalset as a new case (the real production input + its corrected expected
verdict). Monitor surfaces a miss → miss becomes a permanent regression test →
next candidate is checked against it. The evalset grows from real failures, not
guesses.

> Full-auto is only as safe as the golden set is representative — a
> non-representative set yields a confidently-wrong tight bootstrap CI. Growing
> the set from real failures is the safety net.

## Human-approval checklist (cautious-rollout mode only)

- [ ] Candidate Final Response Quality matches live within the bootstrap CI
- [ ] Zero regressions on existing golden cases
- [ ] Output-variance metric (behavioral) within normal range
- [ ] No new hallucinated rules / vague fixes flagged by the judge criteria
- [ ] Canary percentage set; rollback revision noted

## Teardown

Spin-down mirrors the two provisioning paths, and they stay independent — tearing
one down does not touch the other's resources.

- **Notebook path** — run `notebooks/05-teardown.ipynb` (guarded by
  `RUN_TEARDOWN=False`). It undeploys the Agent Runtime via
  `deployment/teardown_agent.py`, deletes the loop / rollback Cloud Functions,
  deletes the `<agent>-loop-trigger` and `<agent>-rollback-trigger` Pub/Sub
  topics, and deletes the drift + canary breach alert policies + overview
  dashboard by the exact `displayName` read from `agents/<name>/observability/`.
- **Terraform path** — `terraform destroy`. The deploy and online-monitor
  `null_resource`s now carry destroy-time provisioners, so destroy also undeploys
  the managed agent (via `teardown_agent.py`) instead of silently leaving it
  running.

Manual either way: the **online monitor is Preview** (console-only, no scripted
delete) — remove it by hand. Service accounts / IAM created by
`agents-cli infra single-project` are owned by that command's own Terraform and
are torn down separately.

## Maturity caveats

- Agent Runtime revision management (versioning, instant rollback, traffic
  split) is an **API-only Public Preview** capability the deploy step depends
  on. Confirm availability; fallback is full redeploy.
- Agent Registry is **Preview**.
