---
name: add-agent
description: Onboard a new agent into this Agent Ops framework. Scaffolds the official agents-cli `app/` structure with `agents-cli create`, then layers our maturity bits (eval golden set, observability specs, agent.yaml) and validates against the CI contract so it passes by construction. Use when adding a new agent under agents/.
---

# Add a new agent

A repeatable procedure for onboarding a new agent. Run it with an AI assistant ("follow
`skills/add-agent.md` to add a returns-policy agent") or as a manual checklist.

This framework scales by folders: every agent is `agents/<name>/`, and the shared engine
(`loop/`, `eval_tool/`, `deployment/`, `terraform/`) drives it via `--agent-dir`. **Structure +
deploy come from agents-cli (official); the loop + eval + observability are ours.** Don't modify the
shared engine — it stays unchanged across agents.

## Inputs (ask the user for any that are missing)
- **name** — domain/shape name, **kebab-case**, **≤ 30 chars** (Terraform derives the service-account
  id `{name}-sa`, 30-char limit). No uppercase, no underscores.
- **purpose** — one line: what the agent does and the rules/behavior it enforces.
- **shape** — `single-turn (no tools)` | `tool-calling` | `multi-turn` (see `EXAMPLE-AGENTS-ROADMAP.md`).

## Steps

1. **Scaffold the agents-cli structure** — let the official tool write the `app/` shape:
   ```bash
   agents-cli create <name> -o agents/ -a adk -d agent_runtime --cicd-runner skip --prototype --auto-approve
   ```
   Creates `agents/<name>/` with `app/agent.py`, `app/agent_runtime_app.py`, `app/app_utils/`,
   `agents-cli-manifest.yaml`, `pyproject.toml`. `--prototype` skips per-agent CI/CD + Terraform
   (we use the repo-level `cicd/` + `terraform/`). Set `region: us-central1` in the manifest.
   The shared engine's loaders + Terraform `filesha256` read `app/agent.py` directly — no root shim.

2. **Author the agent** in `app/agent.py` (model it on `brand-guidelines-checker/app/agent.py`):
   - expose `root_agent` (an ADK `Agent`) **and** `app = App(root_agent=root_agent, name="<snake_name>")`
     (the deploy entrypoint `agent_runtime_app.py` imports `app`).
   - keep `os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")` and the `MODEL` /
     `AGENT_INSTRUCTION_FILE` env overrides the loop's hill-climb relies on.

3. **Layer the maturity bits** (ours — copy from `brand-guidelines-checker/` and adapt):
   - `agent.yaml` — model / eval policy / monitor thresholds / canary %.
   - `eval/golden.evalset.json` — domain regression set: **unique `id`s, valid verdicts, BOTH passing
     and failing cases** (the CI contract requires both).
   - `eval/criteria.json` — the active rater(s) + thresholds for this shape.
   - `eval/weak_instruction.txt` — a deliberately weak instruction (drops the rules) for the drift demo.
   - `observability/{metric,alert,canary_alert,monitor}.yaml` + `dashboard.json` — displayNames
     referencing `<name>`.
   - ensure `pyproject.toml` has the `eval` extra (so `agents-cli eval` can sync).

4. **(Optional) agent-specific tests** — `tests/agents/test_<name>.py` (load `app/agent.py`);
   `tests/test_brand_guidelines.py` is the model. The central `tests/test_agents.py` auto-covers
   every `agents/*/` (yaml + golden schema) — no edit needed.

5. **Validate — green by construction.** Iterate until both pass:
   ```bash
   python -m pytest tests/ -q     # test_agents.py auto-parametrizes the new agent
   ruff check tests/
   ```

6. **Deploy / wire (when ready)** — describe, don't run:
   - `python deployment/deploy_agent.py --agent-dir agents/<name>` (default = `agents-cli deploy`,
     source/container + Agent Identity, revisions populate), or `terraform apply` (the IaC fan-out
     discovers the folder via `fileset()` and stands up its per-agent ops stack).
   - Drive the loop: `--agent-dir agents/<name>` to `loop/run_ct_loop.py` / `eval_tool/run_eval.py`.

## Guardrails
- Folder name **kebab-case, ≤ 30 chars**. `app/agent.py` exposes `root_agent` + `app`; the shared
  engine's loaders, the notebooks, and Terraform `filesha256` all read `app/agent.py` directly.
- Golden set: unique ids, valid verdicts, both pass + fail cases.
- **Least-privilege:** a new IAM role goes in BOTH the Terraform and the allowlist in
  `tests/test_identity.py` (deny-by-default) — never owner/editor/broad-admin, never a long-lived SA key.
- Agent Identity (SPIFFE) is auto-issued at deploy (`--agent-identity`) — nothing to configure.
- Match the repo's terse voice for generated markdown/docstrings (see `NOTEBOOK-VOICE-GUIDE.md`).

## Output
A new `agents/<name>/` — agents-cli-shaped, with our eval/observability/config layered — that passes
CI by construction, deployable via `agents-cli deploy`.
