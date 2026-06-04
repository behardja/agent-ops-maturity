"""Cloud Function (CloudEvent) subscriber that closes the Agent Ops L1 loop.

This is the deployable that NB2 deferred to NB3 — the piece that turns the
drift alert into a fully hands-off Continuous-Iteration loop:

    drift alert -> Pub/Sub <agent>-loop-trigger -> THIS function -> run_ct_loop.py

On each published message it runs the shared loop driver for the named agent
UNATTENDED — it lets the loop deploy the winning candidate (no --no-deploy),
because in the locked operating model human judgment is front-loaded into the
golden evalset, not a per-cycle approval. Switch to cautious-rollout by adding
--require-approval (won't work headless) or --no-deploy (notify-only).

Scope: this auto-deploy targets the STAGING environment only (this reference uses
the sandbox project as staging). Per GEAP deployment best practices, promotion to
PRODUCTION is always a manual approval gate — the closed loop never ships to
production unattended.

Deploy with the whole repo as source so loop/, eval_tool/, deployment/, and
agents/ are importable and run_ct_loop's relative subprocess paths resolve.
The agent name is read from the message: a Pub/Sub attribute "agent", else the
Cloud Monitoring incident payload's metric labels, else DEFAULT_AGENT.
"""

import base64
import json
import os
import subprocess

import functions_framework


def _find_repo_root(start):
    """Walk up until we find the dir holding loop/ + eval_tool/. Robust to both
    layouts: in-repo this file sits at deployment/loop_subscriber/, but NB3 stages
    it at the build root (next to loop/) for the Cloud Functions deploy."""
    d = start
    while True:
        if os.path.isdir(os.path.join(d, "loop")) and os.path.isdir(os.path.join(d, "eval_tool")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise RuntimeError("repo root (with loop/ + eval_tool/) not found")
        d = parent


REPO_ROOT = _find_repo_root(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_AGENT = os.environ.get("DEFAULT_AGENT", "brand-guidelines-checker")


def _agent_from_event(cloud_event):
    """Pull the agent name from the Pub/Sub message; fall back to DEFAULT_AGENT."""
    message = cloud_event.data.get("message", {})

    attributes = message.get("attributes") or {}
    if attributes.get("agent"):
        return attributes["agent"]

    data = message.get("data")
    if data:
        try:
            payload = json.loads(base64.b64decode(data))
        except (ValueError, TypeError):
            payload = {}
        # Cloud Monitoring notification payloads nest the metric labels here.
        labels = payload.get("incident", {}).get("metric", {}).get("labels", {})
        if labels.get("agent"):
            return labels["agent"]

    return DEFAULT_AGENT


@functions_framework.cloud_event
def run_loop(cloud_event):
    agent = _agent_from_event(cloud_event)
    agent_dir = os.path.join("agents", agent)
    print(f"drift trigger received -> running Continuous-Iteration loop for {agent}")
    subprocess.run(
        ["python", "loop/run_ct_loop.py", "--agent-dir", agent_dir, "--policy", "match"],
        cwd=REPO_ROOT,
        check=True,
    )
    print(f"loop finished for {agent}")
