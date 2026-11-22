# GitHub setup

One-time setup, done in the GitHub and Databricks web UIs. It takes about 10 minutes.

1. [Repository and branches](#1-repository-and-branches)
2. [Databricks tokens](#2-databricks-tokens)
3. [Secrets](#3-secrets)
4. [Environments](#4-environments)
5. [Branch rules](#5-branch-rules)
6. [First run](#6-first-run)

## 1. Repository and branches

| Setting | Value | Why |
|---|---|---|
| Visibility | **Public** | On the free plan, required reviewers for environments only work in public repositories. The repository contains no secrets. |
| Branches | `main` (PROD), `develop` (DEV) | Merging to each branch deploys to its environment. |
| Default branch | `develop` | Feature pull requests target `develop` by default. |

## 2. Databricks tokens

In Databricks, go to **Settings → Developer → Access tokens → Generate new token** and
create two tokens:

| Token name | Lifetime | Used by |
|---|---|---|
| `github-ci-dev` | 90 days | CI validation and Deploy DEV |
| `github-ci-prod` | 90 days | Deploy PROD |

Never paste tokens into chat, issues or code; enter them only in the GitHub secret form.
Rotation is described in the [runbook](runbook.md#rotate-tokens).

## 3. Secrets

**Settings → Secrets and variables → Actions → Repository secrets**

| Name | Value |
|---|---|
| `DATABRICKS_HOST` | workspace URL, e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com` |
| `DATABRICKS_TOKEN` | the `github-ci-dev` token |

## 4. Environments

**Settings → Environments → New environment**

| Environment | Deployment branches | Protection rules | Environment secrets |
|---|---|---|---|
| `dev` | `develop` | none | none (uses the repository secrets) |
| `prod` | `main` | **Required reviewers**: you or your team | `DATABRICKS_TOKEN` = the `github-ci-prod` token |

* The `prod` environment secret overrides the repository secret with the same name, so
  PROD jobs use the PROD token automatically.
* If you are the only reviewer, leave **Prevent self-review** unchecked so you can approve
  your own deployments.

## 5. Branch rules

**Settings → Rules → Rulesets → New branch ruleset**, targeting `main` and `develop`:

* Require a pull request before merging.
* Require status checks to pass: **Lint and unit tests**. Add **Validate bundle · sales**
  after it has run once.
* Block force pushes.

## 6. First run

1. Create a feature branch, change something small, and open a pull request into
   `develop`. Check that **CI** is green.
2. Merge it. **Deploy DEV** deploys `sales` to `/Workspace/databricks-platform/dev/sales`
   and tags `deploy/dev/sales`.
3. Open a pull request from `develop` to `main` and merge it.
4. Approve the waiting **Deploy PROD** run. It deploys to
   `/Workspace/databricks-platform/prod/sales` and tags `release/sales/<timestamp>`.
