// Two honesty seams for things Terraform can't model natively.
//
// 1. Agent Runtime deploy: there is no native TF resource for deploying to the
//    managed Agent Runtime. We shell out to deployment/deploy_agent.py, gated
//    behind var.deploy_agent (default false) so a plain `terraform apply`
//    provisions ops scaffolding WITHOUT mutating live agent traffic. Re-runs when
//    the agent's source changes (filesha256 trigger).
//
// 2. Online monitor: the live Agent monitor is Preview and has no stable TF
//    resource, so it's a gated local-exec too (default false). Drift detection
//    does NOT depend on this — observability.tf's log-based metric + alert work
//    on any project. This just adds the richer live signal when a project opts in.

resource "null_resource" "deploy" {
  count = var.deploy_agent ? 1 : 0

  // Stash the values the destroy-time provisioner needs: destroy provisioners
  // may reference only self.triggers (vars aren't available at destroy time).
  triggers = {
    agent_source = filesha256("${var.agent_path}/app/agent.py")
    agent_config = filesha256("${var.agent_path}/agent.yaml")
    canary       = local.canary_traffic
    agent_name   = var.agent_name
    project      = var.project_id
    region       = var.region
  }

  // Deploy via deploy_agent.py --source: the in-repo SDK source/container builder.
  // It's the SAME source_packages + AgentEngineConfig mechanism as `agents-cli
  // deploy` (the default everywhere else) — so the engine gets a sourceCodeSpec and
  // runtime REVISIONS populate — but it needs NO agents-cli/uv on the IaC runner.
  // (Switch to the default `agents-cli deploy` by dropping --source if your runner
  // has agents-cli.) A deploy ships the new revision; traffic-split rollback to a
  // prior revision is the separate trafficSplitManual op shown in NB4.
  provisioner "local-exec" {
    working_dir = "${path.root}/.."
    command     = "python deployment/deploy_agent.py --agent-dir agents/${var.agent_name} --project ${var.project_id} --region ${var.region} --staging-bucket gs://${var.staging_bucket} --source"
  }

  // `terraform destroy` undeploys the managed Agent Runtime (no native TF
  // resource owns it, so without this destroy would silently leave it running).
  provisioner "local-exec" {
    when        = destroy
    working_dir = "${path.root}/.."
    command     = "python deployment/teardown_agent.py --agent-dir agents/${self.triggers.agent_name} --project ${self.triggers.project} --region ${self.triggers.region}"
  }
}

resource "null_resource" "online_monitor" {
  count = var.enable_online_monitor ? 1 : 0

  triggers = {
    agent_config = filesha256("${var.agent_path}/agent.yaml")
    agent_name   = var.agent_name
  }

  provisioner "local-exec" {
    working_dir = "${path.root}/.."
    command     = "python deployment/create_online_monitor.py --agent-dir agents/${var.agent_name} --project ${var.project_id} --region ${var.region}"
  }

  // The online monitor is Preview/console-driven and has no scripted delete;
  // remind the operator to remove it by hand rather than fake a teardown.
  provisioner "local-exec" {
    when    = destroy
    command = "echo 'Reminder: remove the Preview online monitor for ${self.triggers.agent_name} in the Agent Platform console — it is not torn down automatically.'"
  }

  depends_on = [null_resource.deploy]
}
