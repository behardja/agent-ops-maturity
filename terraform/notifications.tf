// Shared notification channel — one email channel routes every agent's drift
// alert. Optional: without an email the alerts still fire (and can be wired to a
// webhook channel that runs the loop), they just won't email anyone.

resource "google_monitoring_notification_channel" "email" {
  count        = var.notification_email != "" ? 1 : 0
  display_name = "Agent Ops L1 — drift alerts"
  type         = "email"
  labels = {
    email_address = var.notification_email
  }
  depends_on = [google_project_service.required]
}
