// Per-agent bucket for eval artifacts — golden-set run results,
// candidate-vs-live comparisons, and optimizer (GEPA) outputs the loop produces.

resource "google_storage_bucket" "artifacts" {
  name                        = "${var.project_id}-${var.agent_name}-artifacts"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
  labels                      = local.labels

  versioning {
    enabled = true
  }
}
