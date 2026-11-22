# Architecture

1. [Goals](#goals)
2. [Free Edition constraints](#free-edition-constraints)
3. [Environments and workspace layout](#environments-and-workspace-layout)
4. [Data and transformation design](#data-and-transformation-design)
5. [CI/CD design](#cicd-design)
6. [Security](#security)
7. [Verification status](#verification-status)
8. [Limitations](#limitations)

## Goals

* Build a local-first CI/CD on **Databricks Free Edition** and **GitHub Actions**.
* Deploy each project as its own Databricks Asset Bundle, and deploy only projects that
  changed.
* Separate DEV and PROD by Unity Catalog catalog inside one workspace.
* Deploy to DEV automatically; deploy to PROD after manual approval.
* Allow rollback per project.
* Keep all logic in scripts, so moving to GitLab CI only means rewriting the pipeline YAML.

![Platform architecture](diagrams/architecture.svg)

*Laptop → GitHub → Databricks. Actions deploys and runs bundles. Environments gate PROD.
Secrets hold the workspace URL and tokens.*

## Free Edition constraints

| Constraint (Databricks docs, Nov 2026) | Design response |
|---|---|
| Serverless compute only | Job tasks use serverless environments (`environment_version: "4"`) |
| One SQL warehouse, 2X-Small | Dashboards look up *Serverless Starter Warehouse* by name |
| 5 concurrent job tasks per account | Tasks run in sequence; CI deploys one project at a time |
| One active pipeline per type | Not relevant: no Lakeflow pipeline, only plain Delta tables |
| No account console or account APIs | No service principals or GitHub OIDC, so CI uses **personal access tokens** |
| Daily fair-use compute quota | Small synthetic dataset; data generation is incremental |
| Not for commercial use | PoC with synthetic data only |

On the GitHub **free plan**, environment required reviewers work only in **public**
repositories, so the repository is public. Secrets never appear in the code.

## Environments and workspace layout

| | DEV | PROD |
|---|---|---|
| Git branch | `develop` | `main` |
| Workflow | `deploy-dev.yml`, automatic | `deploy-prod.yml`, after approval |
| Bundle target | `dev` (job schedule paused) | `prod` (`mode: production`, schedule active) |
| Catalog | `dev` | `prod` |
| Schemas | `bronze`, `silver`, `gold` | `bronze`, `silver`, `gold` |
| Workspace folder | `/Workspace/databricks-platform/dev/<project>` | `/Workspace/databricks-platform/prod/<project>` |
| Folder, job and dashboard permissions | all users: manage | deployer: manage · all users: view |
| Token | repo secret `DATABRICKS_TOKEN` | `prod` environment secret `DATABRICKS_TOKEN` |

```text
/Workspace/databricks-platform/
├── dev/<project>/     files, state and resources deployed from develop
└── prod/<project>/    files, state and resources deployed from main
```

* **Both environments live under one platform folder.** That makes the deployed code easy
  to find. The paths are set explicitly in `databricks.yml`; without them the CLI would
  deploy into the deploying user's home folder.
* **`Shared` is not used.** Every user can edit `Shared`, and Databricks advises against it
  for production deployments.
* **Schemas are created once by `scripts/bootstrap_uc.sql`, not by bundles.** Destroying
  one project can therefore never drop a schema another project uses.

## Data and transformation design

![Sales data flow](diagrams/data-flow.svg)

*Each arrow is one job task step. Bronze loads only new files, silver merges on keys and
quarantines rejected rows, gold aggregates, and the metric views hold every KPI formula.*

| Decision | Why |
|---|---|
| **SQL holds the logic; a config-driven Python wrapper runs it.** Each table is one `SELECT` file plus an entry in `src/tables/tables.yml`. | Adding a table needs no Python. The wrapper (`shared/python/platform_common/tables.py`) is shared by all projects. |
| **Plain managed Delta tables.** No streaming tables, no Lakeflow pipeline, no materialized views. | The data is small and full gold rebuilds are cheap. This also avoids the one-active-pipeline limit. |
| **Write modes:** bronze `append_new_files`, silver `merge`, gold `replace`. | Bronze is idempotent per file; silver upserts by business key; gold is always consistent. |
| **Expectations:** `expect` (warn), `expect_or_drop` (rows go to `<table>_quarantine`), `expect_or_fail` (stop the build). | Bad data is visible, not silent. |
| **Unity Catalog metric views are the semantic layer.** Gold tables hold only additive measures; every ratio, prior-year and YoY measure is defined once. | Ratios stay correct at any filter or grouping. The dashboard, SQL and Genie share one definition. |
| **The job publishes the metric views.** It runs `CREATE OR REPLACE VIEW … WITH METRICS`. | Metric views are not yet a bundle resource type. Redeploying an old release and re-running the job also rolls them back. |
| **The dashboard reads the metric views directly.** Templates use `__CATALOG__` tokens, rendered per target. | Metric-view datasets need fully qualified names, which bundle variables cannot reach inside the JSON file. |

## CI/CD design

![CI/CD flow](diagrams/cicd-flow.svg)

*Top lane: merging to `develop` deploys to DEV automatically. Bottom lane: merging to
`main` waits for approval before deploying to PROD. Rollback goes through the same
approval.*

* **Change detection.**
  * A PR validates projects changed relative to its base branch.
  * A deploy compares each project with its tag `deploy/<env>/<project>`, which moves only
    after success, so a failed or cancelled run never hides a change.
  * Changes under `shared/` affect every project.
* **Each deploy is also the integration test.** It runs `bundle validate`, then
  `bundle deploy`, then the project job (data → tables → metric views → quality checks).
  Finally `verify_dashboards.py` runs every widget query of the deployed dashboard.
* **Rollback.**
  * Every PROD deploy creates an immutable tag, `release/<project>/<UTC timestamp>`.
  * Re-running *Deploy PROD* with that tag restores the code, job, dashboard and metric
    views.
  * Data is not rolled back; use Delta time travel if needed.
* **Portability.** The workflows only call scripts in `scripts/`. The GitLab mapping:

  | GitHub | GitLab |
  |---|---|
  | workflows | `.gitlab-ci.yml` |
  | environments | protected environments |
  | secrets | masked CI/CD variables |

## Security

* No hosts, tokens or workspace IDs are in the repository. A unit test fails if a token
  pattern is committed.
* Pull requests from forks never receive secrets; bundle validation runs only for
  same-repository PRs.
* `bundle.sh` refuses a local `prod` deploy unless `ALLOW_LOCAL_PROD=1` is set, and refuses
  `destroy` on prod unless `ALLOW_PROD_DESTROY=1` is set.
* Deploys never auto-approve destructive changes; CI stops for a human instead.
* The Databricks CLI is pinned (`.databricks-cli-version`) and its download is checked
  against the release SHA-256 sums.

## Verification status

| Item | Status |
|---|---|
| Unit tests (109) and ruff | ✅ passing locally |
| Bundle schema keys used in YAML | ✅ match CLI 1.23.0 `bundle schema` |
| `bundle validate` for `dev` and `prod` | ✅ against the workspace |
| Shared code layout after `sync.paths` (`files/projects/...`, `files/shared/python/...`) | ✅ confirmed after the first DEV deploy |
| Warehouse name *Serverless Starter Warehouse* | ✅ confirmed |
| Top-level folder `/Workspace/databricks-platform` allowed | ✅ confirmed |
| Serverless `environment_version: "4"`, metric-view DDL from a job, dashboard JSON for metric-view datasets | ⏳ confirmed by the first full job run and `verify` |
| CI workflows on GitHub | ⏳ after GitHub secrets and environments are set up |

## Limitations

* **One identity.** Both tokens belong to the same user, so DEV and PROD are separated by
  catalog, folder and process, not by permissions. On a paid workspace, use one service
  principal per environment (OAuth or GitHub OIDC) and give the DEV identity no access to
  `prod`.
* **Shared compute.** DEV and PROD share one workspace, one warehouse and one daily
  compute quota.
* **Rollback restores code, not data.**
* **Dashboard UI edits are not saved automatically.** Capture them back into the template
  (see the runbook).
