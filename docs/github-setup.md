# GitHub setup (one time)

Everything below is done in the GitHub web UI; no extra tools are needed.

## 1. Repository

1. Create a **public** repository (on the free plan, required reviewers for environments
   only work in public repos). No secrets are stored in the code.
2. Push `main` and `develop`:

   ```bash
   git remote add origin https://github.com/<you>/databricks-platform.git
   git push -u origin main develop
   ```
3. **Settings → General**: set the default branch to `develop`, so feature PRs target it.

## 2. Personal access tokens (Databricks)

In the Databricks workspace: **Settings → Developer → Access tokens → Generate new token**.

* Create **two** tokens, `github-ci-dev` and `github-ci-prod`, each with a lifetime of
  about 90 days.
* Put an expiry reminder in your calendar. CI fails with `401` when a token expires.

## 3. Secrets and environments

**Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `DATABRICKS_HOST` | workspace URL, e.g. `https://<workspace>.cloud.databricks.com` |
| `DATABRICKS_TOKEN` | the **dev** token |

**Settings → Environments**

| Environment | Deployment branches | Protection | Secrets |
|---|---|---|---|
| `dev` | `develop` only | none | none (uses the repo secrets) |
| `prod` | `main` only | **Required reviewers**: you (and/or teammates) | `DATABRICKS_TOKEN` = the **prod** token |

An environment secret overrides the repository secret with the same name, so PROD jobs use
the prod token automatically.

If you are the only reviewer, leave **Prevent self-review** unchecked so you can approve
your own deployments.

## 4. Branch rules

**Settings → Rules → Rulesets → New branch ruleset** for `main` and `develop`:

* Require a pull request before merging.
* Require status checks to pass: `Lint and unit tests`. Add the `Validate bundle · sales`
  check once it has run at least once.
* Block force pushes.

## 5. First run

1. Open a PR from a feature branch into `develop` and check that **CI** is green.
2. Merge it. **Deploy DEV** runs and tags `deploy/dev/sales`.
3. Open a PR `develop → main`, merge it, and approve the waiting **Deploy PROD** run.

Manual runs are under **Actions → Deploy DEV / Deploy PROD → Run workflow**.
