// APIs the agent + ops stack depend on. Everything else in this module
// depends on these being enabled first.

resource "google_project_service" "required" {
  for_each = toset([
    "aiplatform.googleapis.com",     // Agent Runtime + Agent Evaluation
    "cloudtrace.googleapis.com",     // tracing (OTel gen_ai.*) — telemetry path
    "logging.googleapis.com",        // logging + log-based metric source
    "monitoring.googleapis.com",     // metrics, alert policy, dashboard
    "pubsub.googleapis.com",         // trigger bus into the loop
    "cloudscheduler.googleapis.com", // scheduled-offline-eval trigger
    "storage.googleapis.com",        // eval artifact bucket
  ])
  service            = each.value
  disable_on_destroy = false
}
