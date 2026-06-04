# eval_tool — the shared "good enough?" check

The scoring + threshold tool every agent reuses (the "good enough?" gate of the L1 loop).
Point it at an agent folder with `--agent-dir`; everything agent-specific (golden set,
criteria, model) comes from `agents/<name>/`.

## `run_eval.py` — score an agent on its golden set

Runs the agent over the golden evalset and writes a results JSON (the loop's baseline /
candidate scores; also NB2's offline run).

- `--agent-dir`: the agent folder (default `agents/brand-guidelines-checker`).
- `--evalset`: defaults to `<agent-dir>/eval/golden.evalset.json`.
- `--criteria`: defaults to `<agent-dir>/eval/criteria.json`.
- `--out`: results JSON; defaults to `<agent-dir>/results/eval.json`.
- `--num-runs`: re-run inference and average, to absorb temperature-1 noise (defaults to `agent.yaml eval.num_runs`, else 2).
- `--model`: override the agent's model (the loop's model-migration knob).
- `--engine {local,managed}`: `local` = ADK `LocalEvalService` (fast, no console run); `managed` = GCP managed Agent Evaluation (console-tracked, via `managed_eval.py`).
- `--emit-logs`: also print one structured JSON line per case to stdout (`metric=final_response_quality`) — the source for the log-based drift metric.
- `--dest`: (managed) GCS uri prefix to persist the run.

Output JSON `per_case[]`:
- `id`: the golden case id.
- `final_response_quality`: mean primary-metric score across runs.
- `passed`: 1 if every run cleared its thresholds, else 0.
- `verdict_correct`: mean PASS/FAIL match vs the golden answer.
- `metric_scores`: per-metric mean, for transparency.

The LLM judges run on GEAP, so `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` must resolve
(defaulted from `configs/defaults.yaml` if unset).

## `compare.py` — the threshold gate

The "good enough?" decision: candidate vs live.

- **PASS** when the candidate **matches** the live agent's Final Response Quality within the **bootstrap noise band** AND has **zero regressions** on existing golden cases. (`--policy beat` = stricter: the candidate's CI lower bound must clear the live mean.)
- Two separate stats: **metric variance** (bootstrap CI on Final Response Quality — this is the gate) vs **output variance** (behavioral, from `--num-runs` — logged only, never gates).
- Shared; `--agent-dir` reads the candidate/live result files from `results/`.

## `managed_eval.py` — the managed backend

The platform twin of `run_eval.py`'s local engine: `run_inference(agent) → evaluate(dataset, metrics)`
via `vertexai` `client.evals`, optionally persisted to a GCS `dest`. Adapts the results to the
**same schema** `run_eval.py` writes, so `compare.py` is unchanged.

> The golden evalset **grows from triage** — every genuine flagged production failure becomes a new
> regression case (see `loop/README.md`).
