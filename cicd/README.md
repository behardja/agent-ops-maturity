# CI/CD setup runbook (one-time)

Wire this repo to **GitHub Actions** so a **pull request to `main`** runs **CI then CD in sequence**
(nothing fires on push). Auth is **keyless** via **Workload Identity Federation (WIF)** — no
service-account JSON keys. NB5 (CI) and NB6 (CD) walk this interactively; this is the operator
reference. Do the infra once per GCP project.

There is **no "GitHub connection" resource** for the Actions + WIF path — Actions runs the
workflows in `.github/workflows/` automatically, and WIF is an OIDC *trust*, not a connection.
(A Cloud Build GitHub connection is only needed if you switch the runner to Cloud Build.)

## How it's structured (production-style: reusable workflows)

Three files, separation of concerns:

| File | Trigger | Role |
|---|---|---|
| `.github/workflows/ci.yml` | `workflow_call` (reusable) | lint + pytest — edited independently |
| `.github/workflows/cd.yml` | `workflow_call` (reusable) | eval gate → deploy a new revision → manual prod sign-off — edited independently |
| `.github/workflows/pipeline.yml` | **`pull_request` → `main`** | thin orchestrator: runs `ci.yml`, then `cd.yml` (`cd needs ci`) — **committed**; reads env-specific values from GitHub repo **variables** |

All three are committed and generic — they're identical in every clone. `cd.yml` takes inputs;
`pipeline.yml` passes the env-specific values (project / region / WIF provider / SA) as
`${{ vars.* }}` **GitHub repository variables**, so nothing project-specific is baked into the file.
`terraform apply` sets those four variables for you from its outputs (step 2).

## Prerequisites (local CLI tools — *not* `requirements.txt`)
- **`gcloud`** — with Application Default Credentials (`gcloud auth application-default login`, or a GCP VM SA).
- **`terraform`** ≥ 1.5.
- **`gh`** (GitHub CLI) ≥ 2.9 — for `gh auth login` (the `git push`). Install (no sudo): `conda install -c conda-forge gh`. **Not needed in CI** (runners ship it).

## 0. Configure — `configs/defaults.yaml`
The single config both `wif.tf` (Terraform) and NB6 read. Set `cicd.github_repo`:
```yaml
project:
  id: sandbox-401718                      # already set
  region: us-central1                     # already set
cicd:
  github_repo: "<your-org>/<your-repo>"   # ← FILL IN (owner/repo; not a secret)
```

## 1. GitHub auth (once — no stored secret)
```bash
gh auth login          # interactive browser/device-code; caches a token locally
gh auth status         # verify: "Logged in to github.com as …"
```
`terraform apply` itself needs **no** GitHub auth for the GCP resources, but the apply also sets the
repo variables via `gh` (step 2), so `gh auth login` must be done first. (Headless/CI only: use a PAT
or GitHub App.)

## 2. Provision the infra + set the repo variables (Terraform — the `cicd/` folder only)
```bash
terraform -chdir=cicd init
terraform -chdir=cicd apply        # WIF pool/provider + deployer SA + roles + Artifact Registry; sets the 4 repo variables
```
Scoped to `cicd/` — it does **not** touch the L1 `terraform/` config. `wif.tf` enables the needed
APIs, creates the pool + GitHub OIDC provider (repo-scoped to `cicd.github_repo`), a dedicated
deployer SA (**not** the compute SA) + roles, and an Artifact Registry repo. For a separate prod
project, re-run with `-var project_id=PROD`.

This config writes **no** workflow file — `pipeline.yml` is already committed. Instead,
`pipeline_vars.tf` (a `terraform_data` + `local-exec`) sets the four `${{ vars.* }}` repository
variables the committed `pipeline.yml` reads, straight from the resources — keyless, using your
`gh auth` (no stored secret, no committed values). It re-runs on `apply` whenever any value changes.
So after `apply`, the workflows (`ci.yml`, `cd.yml`, `pipeline.yml`) are committed and wired — there's
nothing to push, and the next PR to `main` triggers the pipeline.

**Manual re-sync / fallback** (e.g. you rotated the deployer SA out-of-band, or want to set them by
hand): the same four variables, from the Terraform outputs —
```bash
gh variable set GCP_PROJECT_ID --body "$(terraform -chdir=cicd output -raw project_id)"
gh variable set GCP_REGION     --body "$(terraform -chdir=cicd output -raw region)"
gh variable set WIF_PROVIDER   --body "$(terraform -chdir=cicd output -raw workload_identity_provider)"
gh variable set DEPLOYER_SA    --body "$(terraform -chdir=cicd output -raw deployer_service_account)"
gh variable list               # verify the four are set
```

## 3. GitHub Environments (the manual prod sign-off)
In **repo Settings → Environments**, create `production` and add a **Required reviewers** rule —
that's the manual approval. Single project/engine, so it's the human sign-off after deploy (in a
multi-project setup it would gate a deploy to the prod project).

## What runs when
- **PR to `main`** → `pipeline.yml` runs `ci.yml` (lint + tests); if it passes, `cd.yml` runs the
  **managed-eval gate** on the candidate, then **deploys a new revision** (`deploy_agent.py --source`,
  update-in-place on the single engine — idempotent), then **production** waits for the manual
  approval sign-off. Same test-then-ship order as the L1 loop. **Nothing runs on push** to any branch.

## Why not `agents-cli infra cicd`?
agents-cli's `infra cicd` provisions CI/CD for a **single** agents-cli project and wires the repo via
the GitHub **Terraform provider** (needs a GitHub **token**). This repo is **multi-agent** and went
**keyless** (WIF + `gh auth`), so we provision **one** `cicd/` for all agents by hand here instead —
its backend is the same WIF + workflows. (Each agent folder *is* agents-cli-shaped for **deploy**;
agents-cli just doesn't drive the repo-wide CI/CD.)

## Troubleshooting
- **`Error 409: Requested entity already exists`** on `terraform apply` — the resource exists in GCP
  but isn't in Terraform state (a prior partial apply / out-of-band creation). **Don't delete it**
  (deleting a WIF pool soft-deletes it for 30 days and blocks re-creating the same id). **Import** it,
  then re-apply:
  ```bash
  terraform -chdir=cicd import google_iam_workload_identity_pool.github \
    projects/PROJECT/locations/global/workloadIdentityPools/github-pool
  # if more 409s: import google_service_account.deployer / google_artifact_registry_repository.agents too
  terraform -chdir=cicd apply        # should report 0 to destroy
  ```
- **Soft-deleted pool** (`… describe --location=global` shows `DELETED`):
  `gcloud iam workload-identity-pools undelete github-pool --location=global` first.

## Security notes
- **Repo-scoped condition** on the provider stops other repos using your pool.
- **Dedicated deployer SA**, least-privilege roles; never the default compute SA.
- Keyless (WIF) — no long-lived JSON key to leak or rotate.

Docs: [WIF for GitHub Actions](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines) ·
[Reusable workflows](https://docs.github.com/actions/using-workflows/reusing-workflows) ·
[agents-cli CI/CD](https://google.github.io/agents-cli/guide/cicd/)
