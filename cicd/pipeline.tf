# Render the PR pipeline orchestrator so `terraform apply` writes .github/workflows/pipeline.yml
# with THIS project's values. `terraform destroy` removes it. Not committed in the template — each
# clone generates its own. This is what makes the Terraform route generate the workflow (= NB6 route).
terraform {
  required_providers {
    google = { source = "hashicorp/google" }
    local  = { source = "hashicorp/local" }
  }
}

resource "local_file" "pipeline" {
  filename = "${path.root}/../.github/workflows/pipeline.yml"
  content = templatefile("${path.module}/pipeline.yml.tftpl", {
    project_id                 = local.project_id
    region                     = local.region
    workload_identity_provider = google_iam_workload_identity_pool_provider.github.name
    service_account            = google_service_account.deployer.email
  })
}
