"""Deploy one agent to Agent Runtime, with canary traffic split.

Shared deploy script — one copy for every agent. Point it at an agent folder
with --agent-dir; the agent source and its canary percentage come from
agents/<name>/ (app/agent.py + agent.yaml). Step 1's deploy and the loop's Step 4
deploy share this path.

For the agent_runtime target the deploy is fully managed (no Terraform / no
containers). OpenTelemetry tracing is OFF unless you ask for it, and we turn it
on in BOTH backends below — telemetry for the observability dashboard AND
message-content capture in spans. The latter is REQUIRED for GEAP Agent
Evaluation: an eval run drives the deployed agent and reads the prompt/response
out of its traces, so without captured content the run fails ("traces with no
prompt/response log cannot be evaluated"). Deploying also AUTO-REGISTERS the
revision in Agent Registry.

The first deploy doubles as the wiring check: confirm a trace lands in Cloud
Trace, logs route, and Agent Identity is issued.

Deploy modes:
  * DEFAULT: `agents-cli deploy` (the official tool) — source/container build,
    populates runtime revisions, + Agent Identity. Needs the agent in agents-cli
    shape (app/ + agents-cli-manifest.yaml) and agents-cli (+ uv) on PATH.
  * --source: the in-repo SDK source/container builder (same mechanism; revisions),
    a dependency-free fallback for environments without agents-cli.
  * --sdk:    legacy raw Vertex SDK pickle deploy (no runtime revisions).
All three force EVENT_ONLY message-content capture so GEAP managed eval can read
prompt/response from the agent's traces.
"""

import argparse
import importlib.util
import os

import yaml


def load_config(agent_dir):
    with open(os.path.join(agent_dir, "agent.yaml")) as f:
        return yaml.safe_load(f)


def load_root_agent(agent_dir):
    cfg = load_config(agent_dir)
    os.environ.setdefault("MODEL", cfg.get("model", "gemini-2.5-flash"))
    spec = importlib.util.spec_from_file_location(
        "agent_to_deploy", os.path.join(agent_dir, "app", "agent.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.root_agent


def deploy_cli(agent_dir, project, region):
    """Deploy via `agents-cli deploy` (the DEFAULT) — the official source/container deploy.

    Verified equivalent to our `--source` path: agents-cli uses `source_packages` +
    `AgentEngineConfig(agent_framework="google-adk")` + `agent_engines.create/update`,
    so runtime revisions populate (not pickle) and lineage is preserved via upsert.
    Requires the agent to be agents-cli-shaped (app/ + agents-cli-manifest.yaml) and
    `agents-cli` (+ uv) on PATH.

    We FORCE EVENT_ONLY telemetry capture (+ the OTEL set) via --update-env-vars:
    GEAP managed eval reads prompt/response FROM the agent's traces, and agents-cli's
    serving wrapper defaults to NO_CONTENT — without this an eval run fails ("traces
    with no prompt/response log cannot be evaluated"). GOOGLE_CLOUD_LOCATION=global
    routes model calls to the global endpoint (serves global-only models, e.g. 3.5).
    """
    import subprocess

    payload_path = f"{staging_bucket_uri(project)}/agent-payloads"
    env = (
        "GOOGLE_CLOUD_LOCATION=global,"
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true,"
        "OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental,"
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY,"
        "OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT=jsonl,"
        "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK=upload,"
        f"OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH={payload_path}"
    )
    # agents-cli 0.3.0 is manifest-driven: run from the agent dir (no --agent-path).
    subprocess.run(
        ["agents-cli", "deploy", "--agent-identity",
         "--project", project, "--region", region, "--update-env-vars", env],
        cwd=agent_dir, check=True,
    )


def staging_bucket_uri(project):
    """Generic, project-level staging bucket shared by all agents. Staging is just
    ephemeral build scratch (the SDK packages + uploads the agent here before
    building the Agent Engine), so it is not per-agent — unlike Terraform's
    per-agent {project}-{agent_name}-artifacts bucket, which holds eval outputs."""
    return f"gs://{project}-agent-staging"


def deploy_sdk(agent_dir, project, region, staging_bucket):
    """What the CLI wraps, shown for reference."""
    import vertexai
    from vertexai import agent_engines

    cfg = load_config(agent_dir)
    app_name = cfg.get("name") or os.path.basename(agent_dir.rstrip("/"))
    # display_name is what shows in the Agent Runtime / Registry console; without it the
    # engine has no name and renders as "UNKNOWN". Defaults to the agent name; agent.yaml
    # may override with display_name / description.
    display_name = cfg.get("display_name") or app_name
    description = cfg.get("description")
    root_agent = load_root_agent(agent_dir)
    vertexai.init(project=project, location=region, staging_bucket=staging_bucket)
    # Wrap in AdkApp with an explicit app_name. Without it, the ADK template's set_up()
    # falls back to GOOGLE_CLOUD_AGENT_ENGINE_ID (the numeric engine id) as the app name,
    # which google-adk's App validator rejects ("must start with a letter"), crashing the
    # container on startup. The kebab-case agent name is a valid app name.
    # Telemetry has two controls, and the Cloud Console banner ("OpenTelemetry is not
    # instrumented") keys off the NEWER one:
    #   * GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY (env var) — the canonical switch the
    #     console toggle + observability dashboard read. Must be set for the banner to clear
    #     and for OTel *logging* to turn on. enable_tracing alone does NOT satisfy it.
    #   * enable_tracing=True (legacy AdkApp flag) — still useful: it additionally sets
    #     ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true so prompts/responses show up in the spans.
    # We set both so the dashboard populates and the traces carry message content.
    app = agent_engines.AdkApp(agent=root_agent, app_name=app_name, enable_tracing=True)
    # Telemetry + OTEL GenAI message-content capture so traces carry prompt/response
    # for GEAP Agent Evaluation (per the evaluate-offline doc). enable_tracing=True
    # alone only sets the legacy span flag, not the gen_ai inference event the rater reads.
    # The UPLOAD_* vars also store payloads in GCS (console "storage location: Cloud
    # Storage"; Cloud Logging is the default) — uses the shared staging bucket (one GCS
    # bucket for the demo); the runtime SA needs roles/storage.objectCreator on it.
    env_vars = {
        # Route the agent's MODEL CALLS to the global endpoint so a regionally-deployed
        # engine can serve global-only models (e.g. gemini-3.5-flash, the migration
        # candidate). The engine itself stays regional: its session/memory services read
        # GOOGLE_CLOUD_AGENT_ENGINE_LOCATION, which the runtime sets to the deploy region.
        # This override is honored since b/475865240 removed GOOGLE_CLOUD_LOCATION from the
        # reserved-vars list (set_up fills it only if absent). Verified 2026-06-04: a
        # us-central1 engine serves gemini-3.5-flash with this set. Drop it only if every
        # model used is published in the deploy region.
        "GOOGLE_CLOUD_LOCATION": "global",
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "EVENT_ONLY",
        "OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT": "jsonl",
        "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK": "upload",
        "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH": f"{staging_bucket}/agent-payloads",
    }
    # Upsert: UPDATE the engine in place if it exists (keeps the same resource_name, so the
    # eval lookup + monitors stay pointed at it = lineage), else CREATE. Verified 2026-06-03
    # that update-in-place re-serves on a clean engine (an earlier "empties" scare was a
    # region-unavailable model -- gemini-3.5-flash 404'd from us-central1 -- NOT update; that
    # is now handled by GOOGLE_CLOUD_LOCATION=global in env_vars above, verified 2026-06-04).
    # Note: runtimeRevisions stays 0 for these AdkApp deploys, so per-revision traffic-split
    # isn't available; rollback = redeploy the prior instruction via update.
    existing = [
        e for e in agent_engines.list()
        if (getattr(e, "display_name", "") or "") == display_name
    ]
    if existing:
        agent_engines.update(
            existing[0].resource_name,
            agent_engine=app,
            requirements=os.path.join(agent_dir, "requirements.txt"),
            display_name=display_name,
            description=description,
            env_vars=env_vars,
        )
    else:
        agent_engines.create(
            app,
            requirements=os.path.join(agent_dir, "requirements.txt"),
            display_name=display_name,
            description=description,
            env_vars=env_vars,
        )


def deploy_sdk_source(agent_dir, project, region, staging_bucket):
    """Source/container deploy (L2): ship source files so the platform BUILDS a container
    image. The engine then gets a `sourceCodeSpec` (not a pickled `packageSpec`) and runtime
    revisions populate — which is what enables traffic-split rollback. Mirrors NB1's deploy.

    Stages a dashless `_serving_build/` package under the cwd: the agent dir name has dashes
    (not importable), and source files must live under the working dir. `app.py` exposes a
    wrapped `AdkApp` (a raw LlmAgent fails startup); the instruction is baked into the image.
    """
    import shutil

    import vertexai
    from vertexai import agent_engines
    from google.genai import types as genai_types
    from vertexai._genai.types.common import AgentEngineConfig
    import vertexai._genai._agent_engines_utils as aeu
    from google.adk.agents import Agent

    cfg = load_config(agent_dir)
    display_name = cfg.get("display_name") or cfg.get("name") or os.path.basename(agent_dir.rstrip("/"))
    description = cfg.get("description")
    # agent.py is the single source of truth for name/model/instruction (honours $MODEL and
    # $AGENT_INSTRUCTION_FILE the same way the pickle path does).
    root_agent = load_root_agent(agent_dir)
    name, model, instruction = root_agent.name, root_agent.model, root_agent.instruction

    build_pkg = "_serving_build"
    shutil.rmtree(build_pkg, ignore_errors=True)
    os.makedirs(build_pkg)
    with open(os.path.join(build_pkg, "app.py"), "w") as f:
        f.write(
            "import os\n"
            "from google.adk.agents import Agent\n"
            "from vertexai import agent_engines\n"
            "_here = os.path.dirname(os.path.abspath(__file__))\n"
            f"MODEL = os.environ.get('MODEL', {model!r})\n"
            "with open(os.path.join(_here, 'instruction.txt')) as fh:\n"
            "    INSTRUCTION = fh.read().strip()\n"
            f"root_agent = Agent(name={name!r}, model=MODEL, instruction=INSTRUCTION)\n"
            f"app = agent_engines.AdkApp(agent=root_agent, app_name={name!r}, enable_tracing=True)\n"
        )
    with open(os.path.join(build_pkg, "instruction.txt"), "w") as f:
        f.write(instruction)
    with open(os.path.join(build_pkg, "requirements.txt"), "w") as f, \
            open(os.path.join(agent_dir, "requirements.txt")) as src:
        f.write(src.read())

    vertexai.init(project=project, location=region, staging_bucket=staging_bucket)
    # class_methods the source server registers (source deploys require it explicitly).
    local_app = agent_engines.AdkApp(
        agent=Agent(name=name, model=model, instruction=instruction), app_name=name)
    class_methods = [aeu._to_dict(s) for s in aeu._generate_class_methods_spec_or_raise(
        agent=local_app, operations=local_app.register_operations())]

    env_vars = {
        "GOOGLE_CLOUD_LOCATION": "global",  # model calls -> global endpoint (serves global-only models)
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "EVENT_ONLY",
        "OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT": "jsonl",
        "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK": "upload",
        "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH": f"{staging_bucket}/agent-payloads",
    }
    deploy_cfg = AgentEngineConfig(
        staging_bucket=staging_bucket, source_packages=[build_pkg],
        entrypoint_module=f"{build_pkg}.app", entrypoint_object="app",
        class_methods=class_methods, requirements_file=f"{build_pkg}/requirements.txt",
        agent_framework="google-adk", env_vars=env_vars,
        display_name=display_name, description=description,
    )
    client = vertexai.Client(
        project=project, location=region,
        http_options=genai_types.HttpOptions(api_version="v1beta1"))
    existing = [e for e in agent_engines.list()
                if (getattr(e, "display_name", "") or "") == display_name]
    if existing:
        client.agent_engines.update(name=existing[0].resource_name, config=deploy_cfg)
        print("updated in place (new revision):", existing[0].resource_name)
    else:
        client.agent_engines.create(config=deploy_cfg)
        print("created new source engine")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-dir", default="agents/brand-guidelines-checker",
                    help="agent folder (app/agent.py + agent.yaml)")
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                    help="GCP project id (defaults to $GOOGLE_CLOUD_PROJECT)")
    ap.add_argument("--region", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    ap.add_argument("--staging-bucket", default=None,
                    help="GCS staging bucket; defaults to gs://{project}-agent-staging")
    ap.add_argument("--sdk", action="store_true",
                    help="legacy: raw Vertex SDK pickle deploy (no runtime revisions)")
    ap.add_argument("--source", action="store_true",
                    help="in-repo SDK source/container builder (revisions) — equivalent fallback "
                         "to the default, for environments without agents-cli")
    args = ap.parse_args()

    if args.sdk:
        staging_bucket = args.staging_bucket or staging_bucket_uri(args.project)
        deploy_sdk(args.agent_dir, args.project, args.region, staging_bucket)
    elif args.source:
        staging_bucket = args.staging_bucket or staging_bucket_uri(args.project)
        deploy_sdk_source(args.agent_dir, args.project, args.region, staging_bucket)
    else:
        # DEFAULT: delegate to agents-cli (official source/container deploy + Agent Identity).
        deploy_cli(args.agent_dir, args.project, args.region)

    print("deployed. verify: trace in Cloud Trace · logs route · identity issued · "
          "revision auto-registered in Agent Registry")


if __name__ == "__main__":
    main()
