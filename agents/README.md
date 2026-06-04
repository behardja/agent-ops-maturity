# Bring Your Own Agent (BYOA)

Each agent is a folder under `agents/<name>/` — an **agents-cli project** (the `app/` structure + deploy) plus **our maturity layer** (`agent.yaml`, `eval/`, `observability/`). Two ways to add one. `<name>` is kebab-case, ≤ 30 chars (Terraform derives the `{name}-sa` service account).

## Path 1 — `agents-cli create` (recommended)

Let the official tool write the structure:
```bash
agents-cli create <name> -o agents/ -a adk -d agent_runtime --cicd-runner skip --prototype
```
- Writes `agents/<name>/app/` + `agents-cli-manifest.yaml` + `pyproject.toml`.
- Set `region: us-central1` in the manifest.
- Then add the maturity layer (below). An AI coding assistant can do this by following `skills/add-agent.md`.

## Path 2 — bring your own (match the structure)

Drop your existing ADK agent in and match this layout:
- `app/agent.py`: exposes `root_agent` (ADK `Agent`) **and** `app = App(root_agent=root_agent, name="<snake_name>")`; sets `GOOGLE_GENAI_USE_VERTEXAI`; reads `MODEL` + `AGENT_INSTRUCTION_FILE` from env (the loop's hill-climb knobs).
- `app/agent_runtime_app.py` + `app/app_utils/`: the agents-cli serving wrapper — copy from an existing agent, or run `agents-cli scaffold enhance .`.
- `agents-cli-manifest.yaml`: `agent_directory: app`, `region: us-central1`, `deployment_target: agent_runtime`.
- `pyproject.toml`: dependencies + an `eval` extra.

## Both paths — add the maturity layer

Copy from `brand-guidelines-checker/` and adapt:
- `agent.yaml`: model, eval policy, monitor thresholds, canary %.
- `eval/golden.evalset.json`: regression cases — unique ids, valid verdicts, BOTH pass + fail.
- `eval/criteria.json` + `eval/weak_instruction.txt`.
- `observability/{metric,alert,canary_alert,monitor}.yaml` + `dashboard.json` (displayNames → `<name>`).

## Then

- `python -m pytest tests/` — the central contract auto-covers the new agent.
- `terraform apply` discovers the folder via `fileset()` and stands up its ops stack.
- Drive it: pass `--agent-dir agents/<name>` to `loop/run_ct_loop.py` / `eval_tool/run_eval.py`; deploy with `deployment/deploy_agent.py` (defaults to `agents-cli deploy`).
