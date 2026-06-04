// Per-agent least-privilege service account. Each agent gets its own identity
// for provisioning + the loop's automated eval/deploy calls. (The agent's
// RUNTIME identity, Agent Identity / SPIFFE, is issued automatically by Agent
// Runtime at deploy time — that is not this SA.)

resource "google_service_account" "agent" {
  account_id   = "${var.agent_name}-sa"
  display_name = "Agent Ops L1 — ${var.agent_name}"
}

resource "google_project_iam_member" "agent" {
  for_each = toset([
    "roles/aiplatform.user",         // run Agent Evaluation + deploy revisions
    "roles/logging.logWriter",       // emit logs (the final_response_quality metric source)
    "roles/cloudtrace.agent",        // emit traces
    "roles/monitoring.metricWriter", // write score metrics
    "roles/storage.objectAdmin",     // read/write eval artifacts in the bucket
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.agent.email}"
}
