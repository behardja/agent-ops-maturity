"""Cloud Function (CloudEvent) subscriber that auto-rolls-back a bad canary.

⚠️ NOT BUILT in the notebooks — the automated trigger plumbing (alert → Pub/Sub →
this function) is described in NB4, not wired. The traffic-split rollback it calls
(deployment/rollback.py) IS usable now that the agent deploys via the source/
container path (revisions populate); this function just adds the hands-off trigger
on a canary-scoped alert when you want it. Use it like loop_subscriber/.

The FAST "protect" twin of loop_subscriber/. Where loop_subscriber runs the
hill-climb loop in response to slow, overall-production drift, THIS function
reacts to the tight canary-scoped breach alert and reverts immediately:

    canary breach alert -> Pub/Sub <agent>-rollback-trigger -> THIS function
        -> deployment/rollback.py  (shift 100% traffic back to known-good)

Rollback is SAFE to automate even though forward production deploys are a manual
gate (see GEAP deployment best practices): rolling back only ever REMOVES a bad
revision and restores a previously-approved one — it never ships anything new.
This protects the STAGING canary; production promotion stays a manual approval
gate and is never auto-rolled here.

Two values must be resolved from the event/env:
  * agent     — which agent's canary breached (same resolution as loop_subscriber:
                Pub/Sub attribute "agent" -> incident metric labels -> DEFAULT_AGENT).
  * revision  — the known-good revision to roll back TO. The canary deployer knows
                the prior live revision, so it stamps it on the trigger (Pub/Sub
                attribute "revision" / incident label) or on this function's env
                (KNOWN_GOOD_REVISION). rollback.py shifts 100% of traffic to it via
                the managed revisions/traffic API (v1beta1, Public Preview):
                https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-revisions-and-traffic

Deploy with the whole repo as source so loop/, eval_tool/, deployment/, and
agents/ are importable and rollback.py's relative paths resolve.
"""

import base64
import json
import os
import subprocess

import functions_framework


def _find_repo_root(start):
    """Walk up until we find the dir holding loop/ + eval_tool/ (same as
    loop_subscriber): robust to both the in-repo deployment/rollback_subscriber/
    layout and the staged-at-build-root layout NB4 uses for the deploy."""
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


def _message(cloud_event):
    return cloud_event.data.get("message", {})


def _incident_labels(message):
    """Cloud Monitoring notification payloads nest the metric labels here."""
    data = message.get("data")
    if not data:
        return {}
    try:
        payload = json.loads(base64.b64decode(data))
    except (ValueError, TypeError):
        return {}
    return payload.get("incident", {}).get("metric", {}).get("labels", {})


def _agent_from_event(cloud_event):
    message = _message(cloud_event)
    attributes = message.get("attributes") or {}
    if attributes.get("agent"):
        return attributes["agent"]
    labels = _incident_labels(message)
    if labels.get("agent"):
        return labels["agent"]
    return DEFAULT_AGENT


def _revision_from_event(cloud_event):
    """The known-good revision to roll back TO: trigger attribute -> incident
    label -> KNOWN_GOOD_REVISION env. Returns None if none is supplied (then we
    cannot safely auto-rollback and raise, rather than guess a target)."""
    message = _message(cloud_event)
    attributes = message.get("attributes") or {}
    if attributes.get("revision"):
        return attributes["revision"]
    labels = _incident_labels(message)
    if labels.get("revision"):
        return labels["revision"]
    return os.environ.get("KNOWN_GOOD_REVISION")


@functions_framework.cloud_event
def run_rollback(cloud_event):
    agent = _agent_from_event(cloud_event)
    revision = _revision_from_event(cloud_event)
    if not revision:
        raise RuntimeError(
            "no known-good revision supplied (trigger attribute 'revision', "
            "incident label 'revision', or KNOWN_GOOD_REVISION env) — refusing "
            "to guess a rollback target"
        )
    agent_dir = os.path.join("agents", agent)
    print(f"canary breach received -> rolling back {agent} to {revision}")
    cmd = ["python", "deployment/rollback.py", "--agent-dir", agent_dir, "--revision", revision]
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        cmd += ["--project", os.environ["GOOGLE_CLOUD_PROJECT"]]
    if os.environ.get("GOOGLE_CLOUD_LOCATION"):
        cmd += ["--region", os.environ["GOOGLE_CLOUD_LOCATION"]]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    print(f"rollback finished for {agent} -> {revision}")
