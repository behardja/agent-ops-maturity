# Workload Identity Federation — keyless GitHub Actions → GCP auth for the CD pipeline.
# Lets the workflow deploy WITHOUT a service-account JSON key (no long-lived secret).
# Apply once per project (staging and prod). `agents-cli infra cicd` generates an
# equivalent of this; it's reproduced here as the reference shape.
#
# Inputs follow the repo convention (same as terraform/): project/region fall back to
# ../configs/defaults.yaml, and the GitHub repo comes from its `cicd.github_repo` key.
# Override any with -var or a terraform.tfvars (see terraform.tfvars.example).
# github_repo is "owner/repo" — NOT a secret, so it's fine in defaults.yaml.

variable "project_id" {
  type    = string
  default = "" # falls back to configs/defaults.yaml project.id
}

variable "region" {
  type    = string
  default = "" # falls back to configs/defaults.yaml project.region
}

variable "github_repo" {
  type        = string
  default     = "" # falls back to configs/defaults.yaml cicd.github_repo
  description = "owner/repo allowed to mint credentials"
}

locals {
  global      = yamldecode(file("${path.root}/../configs/defaults.yaml"))
  cicd        = try(local.global.cicd, {})
  project_id  = var.project_id != "" ? var.project_id : local.global.project.id
  region      = var.region != "" ? var.region : local.global.project.region
  github_repo = var.github_repo != "" ? var.github_repo : try(local.cicd.github_repo, "")

  required_services = [
    "iam.googleapis.com",
    "sts.googleapis.com",
    "iamcredentials.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "aiplatform.googleapis.com",
  ]
}

# 0. Enable the APIs WIF + the deploy need (the PDF's "enable the API" step, as code).
resource "google_project_service" "required" {
  for_each           = toset(local.required_services)
  project            = local.project_id
  service            = each.value
  disable_on_destroy = false
}

# 1. A pool + OIDC provider that trusts GitHub's token issuer.
resource "google_iam_workload_identity_pool" "github" {
  project                   = local.project_id
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.required]

  lifecycle {
    precondition {
      condition     = local.github_repo != ""
      error_message = "Set cicd.github_repo in configs/defaults.yaml (or pass -var github_repo=OWNER/REPO)."
    }
  }
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = local.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }

  # Only tokens from THIS repo may use the pool (stops other repos minting creds).
  attribute_condition = "assertion.repository == \"${local.github_repo}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# 2. The deployer service account the workflow impersonates.
resource "google_service_account" "deployer" {
  project      = local.project_id
  account_id   = "agent-cd-deployer"
  display_name = "Agent CD deployer"
  depends_on   = [google_project_service.required]
}

# 3. Let the GitHub repo impersonate that SA through the pool.
resource "google_service_account_iam_member" "wif_bind" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${local.github_repo}"
}

# 4. Roles the deployer needs to build + deploy the agent.
locals {
  deployer_roles = [
    "roles/aiplatform.user",          # create/update Reasoning Engines (Agent Runtime)
    "roles/artifactregistry.writer",  # push the built container image
    "roles/storage.admin",            # staging bucket + payload uploads
    "roles/cloudbuild.builds.editor", # the source -> image build
    "roles/logging.viewer",
  ]
}

resource "google_project_iam_member" "deployer_roles" {
  for_each = toset(local.deployer_roles)
  project  = local.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

# 5. Artifact Registry repo that holds the agent's container image.
resource "google_artifact_registry_repository" "agents" {
  project       = local.project_id
  location      = local.region
  repository_id = "agents"
  format        = "DOCKER"
  depends_on    = [google_project_service.required]
}

output "workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  value = google_service_account.deployer.email
}
