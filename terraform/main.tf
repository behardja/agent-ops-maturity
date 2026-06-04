// Root module — discovers every agent under ../agents/ and provisions one
// agent_ops stack per agent. Adding an agent = drop a new agents/<name>/ folder
// (with an agent.yaml); the next `terraform apply` picks it up automatically.
//
// Per-agent resources live in modules/agent_ops. Project-level resources that
// are shared across all agents (enabled APIs, the notification channel) live at
// this root.

locals {
  // Global fallbacks (project id, region) — the runtime scripts read the same file.
  global = yamldecode(file("${path.root}/../configs/defaults.yaml"))

  project_id = var.project_id != "" ? var.project_id : local.global.project.id
  region     = var.region != "" ? var.region : local.global.project.region

  // Discover agents: each agents/<name>/agent.yaml is one agent.
  agent_files = fileset("${path.root}/../agents", "*/agent.yaml")
  agents = {
    for f in local.agent_files :
    dirname(f) => yamldecode(file("${path.root}/../agents/${f}"))
  }
}

// Shared, project-level staging bucket for the SDK deploy. Staging is ephemeral
// build scratch (the SDK packages + uploads the agent here before building the
// Agent Engine), so it is NOT per-agent — one bucket serves every agent. This is
// distinct from each agent's modules/agent_ops/storage.tf *-artifacts bucket,
// which holds eval outputs. The deploy script defaults to this exact name.
resource "google_storage_bucket" "staging" {
  name                        = "${local.project_id}-agent-staging"
  location                    = local.region
  uniform_bucket_level_access = true
  force_destroy               = true

  versioning {
    enabled = true
  }

  depends_on = [google_project_service.required]
}

module "agent_ops" {
  source   = "./modules/agent_ops"
  for_each = local.agents

  project_id     = local.project_id
  region         = local.region
  agent_name     = each.key
  agent_path     = "${path.root}/../agents/${each.key}"
  config         = each.value
  staging_bucket = google_storage_bucket.staging.name

  enable_scheduled_eval = var.enable_scheduled_eval
  deploy_agent          = var.deploy_agent
  enable_online_monitor = var.enable_online_monitor
  notification_channels = var.notification_email != "" ? [google_monitoring_notification_channel.email[0].id] : []

  depends_on = [google_project_service.required, google_storage_bucket.staging]
}
