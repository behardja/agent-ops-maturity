"""Verify auto-registration in Agent Registry (you don't register manually).

Deploying to Agent Runtime AUTO-REGISTERS the agent in Agent Registry with
zero config, and updates/deletes auto-synchronize. So this is a *confirmation*
helper, not a manual registration step — it checks the deployed agent shows up
in the Registry catalog.

The manual "Register a custom ADK agent" workflow only applies if you deploy
OFF Agent Runtime (e.g. self-hosted), which isn't this repo's case. Distinct
from registration: `agents-cli publish gemini-enterprise` makes the agent
available in the Gemini Enterprise frontend — a separate, deliberate, optional
action.

NOTE: Agent Registry is Preview; confirm the exact list/describe surface in
your project.
"""

import argparse
import os

import yaml


def verify(project, region, agent_name):
    """Confirm the agent shows up after deploy.

    Agent Registry's own list/describe surface is Preview and console-driven (no
    stable gcloud command), but deploying to Agent Runtime auto-registers the
    engine, so the practical confirmation is that the engine exists in Agent
    Runtime. We list engines via the Vertex SDK and match on display name.
    """
    print(f"Checking Agent Runtime for '{agent_name}' in {project}/{region} ...")
    import vertexai
    from vertexai import agent_engines

    def norm(s):
        return "".join(c for c in s.lower() if c.isalnum())

    target = norm(agent_name)
    vertexai.init(project=project, location=region)
    matches = []
    for e in agent_engines.list():
        display = getattr(e, "display_name", None) or ""
        resource = getattr(e, "resource_name", None) or getattr(e, "name", "")
        if target in norm(display) or agent_name in resource:
            matches.append((display, resource))

    if matches:
        for display, resource in matches:
            print(f"  found: {display} | {resource}")
        print("Auto-registration worked — the engine is live in Agent Runtime "
              "(and auto-synced into the Agent Registry catalog). Nothing to do.")
    else:
        print(f"  no engine matching '{agent_name}' found yet — if you just "
              "deployed, give it a moment and re-run, or check the deploy logs.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default="agents/brand-guidelines-checker",
                    help="folder holding agent.yaml (agent name is read from it)")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    ap.add_argument("--region", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    ap.add_argument("--agent-name", help="overrides the name in agent.yaml")
    args = ap.parse_args()

    agent_name = args.agent_name
    if not agent_name:
        with open(os.path.join(args.agent_dir, "agent.yaml")) as f:
            agent_name = yaml.safe_load(f).get("name")
    verify(args.project, args.region, agent_name)


if __name__ == "__main__":
    main()
