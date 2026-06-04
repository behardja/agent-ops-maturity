"""Revert Agent Runtime to a prior revision by shifting 100% of traffic to it.

Script mirror of NB4's manual rollback. Now that the agent deploys via the
source/container path (deploy_agent.py --source, used by NB1/NB3), each promotion
registers a runtime revision — so this traffic-split rollback is usable: set the
agent's traffic_config to send 100% to a known-good (active) revision via the
managed revisions/traffic API (v1beta1). It's near-instant and safe (it only
restores a previously-approved revision, never ships anything new). The
`trafficSplitManual` op is documented but verify it on your first real rollback.
(On the legacy *pickle* deploy, runtimeRevisions stay 0 and there is nothing to
split — there, fall back to redeploying the prior instruction in place.)
docs: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-revisions-and-traffic
"""

import argparse
import os

import yaml


def _resolve_resource_name(agent_dir, project, region):
    """Find the deployed engine's resource_name by its display_name (agent.yaml)."""
    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=project, location=region)
    with open(os.path.join(agent_dir, "agent.yaml")) as f:
        cfg = yaml.safe_load(f)
    name = (
        cfg.get("display_name")
        or cfg.get("name")
        or os.path.basename(agent_dir.rstrip("/"))
    )
    matches = [
        e for e in agent_engines.list()
        if (getattr(e, "display_name", "") or "") == name
    ]
    if not matches:
        raise RuntimeError(f"no deployed engine named {name!r} in {project}/{region}")
    return matches[0].resource_name


def rollback(agent_dir, project, region, revision):
    """Shift 100% of traffic back to a known-good revision of this agent."""
    import vertexai
    from google.genai import types as genai_types

    resource = _resolve_resource_name(agent_dir, project, region)
    # Accept either a bare REVISION_ID or a full .../runtimeRevisions/<id> name.
    rev_name = (
        revision
        if "/runtimeRevisions/" in revision
        else f"{resource}/runtimeRevisions/{revision}"
    )
    client = vertexai.Client(
        project=project,
        location=region,
        http_options=genai_types.HttpOptions(api_version="v1beta1"),
    )
    client.agent_engines.update(
        name=resource,
        config={
            "traffic_config": {
                "trafficSplitManual": {
                    "targets": [{"runtimeRevisionName": rev_name, "percent": 100}]
                }
            }
        },
    )
    print(f"rolled back {resource} -> 100% traffic to {rev_name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default="agents/brand-guidelines-checker")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    ap.add_argument("--region", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    ap.add_argument("--revision", required=True,
                    help="known-good revision: bare id or full runtimeRevisions/<id> name")
    args = ap.parse_args()
    rollback(args.agent_dir, args.project, args.region, args.revision)


if __name__ == "__main__":
    main()
