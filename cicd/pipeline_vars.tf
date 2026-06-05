# Set the four GitHub repository variables that the committed pipeline.yml reads, straight from
# this config's resources — so a single `terraform apply` provisions the infra AND wires the
# workflow (mirrors the NB6 `gh variable set` cell). Keyless: shells out to `gh`, which uses your
# `gh auth login` (a prerequisite already required before apply — see cicd/README.md). Nothing is
# stored in Terraform state beyond the trigger values, and no GitHub token is needed.
#
# Re-runs whenever any of the four values (or the target repo) change. terraform_data is a built-in
# resource (Terraform >= 1.4), so this needs no extra provider.
resource "terraform_data" "repo_vars" {
  triggers_replace = [
    local.project_id,
    local.region,
    google_iam_workload_identity_pool_provider.github.name,
    google_service_account.deployer.email,
    local.github_repo,
  ]

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      command -v gh >/dev/null 2>&1 || { echo "ERROR: gh CLI not found — install it and run 'gh auth login' (see cicd/README.md), then re-apply."; exit 1; }
      gh auth status >/dev/null 2>&1 || { echo "ERROR: gh is not authenticated — run 'gh auth login' first, then re-apply."; exit 1; }
      gh variable set GCP_PROJECT_ID --repo "${local.github_repo}" --body "${local.project_id}"
      gh variable set GCP_REGION     --repo "${local.github_repo}" --body "${local.region}"
      gh variable set WIF_PROVIDER   --repo "${local.github_repo}" --body "${google_iam_workload_identity_pool_provider.github.name}"
      gh variable set DEPLOYER_SA    --repo "${local.github_repo}" --body "${google_service_account.deployer.email}"
      echo "set 4 repo variables (GCP_PROJECT_ID, GCP_REGION, WIF_PROVIDER, DEPLOYER_SA) on ${local.github_repo}"
    EOT
  }
}
