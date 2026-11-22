# Runbook

Day-to-day operations for the platform. Commands run from the repository root in Git Bash
(Windows) or any POSIX shell.

1. [Local setup](#local-setup)
2. [Deploy, run and verify a project](#deploy-run-and-verify-a-project)
3. [Release to PROD](#release-to-prod)
4. [Roll back a project](#roll-back-a-project)
5. [Change tables, KPIs or the dashboard](#change-tables-kpis-or-the-dashboard)
6. [Add a project](#add-a-project)
7. [Rotate tokens](#rotate-tokens)
8. [Troubleshooting](#troubleshooting)

## Local setup

1. **Install the tools.**
   * Python 3.11+, Git, and VS Code with the recommended extensions.
   * Databricks CLI at the version in `.databricks-cli-version`. On Linux/macOS, run
     `bash scripts/install_databricks_cli.sh`. On Windows, download
     `databricks_cli_<version>_windows_amd64.zip` from the CLI's GitHub releases and add
     `databricks.exe` to your PATH.
2. **Create the Python environment.**

   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -r requirements-dev.txt
   .venv/Scripts/python -m pytest
   ```
3. **Connect to the workspace.** In Databricks, create a personal access token under
   **Settings → Developer → Access tokens**. Then:

   ```bash
   databricks configure --profile free-edition    # prompts for workspace URL and token
   export DATABRICKS_CONFIG_PROFILE=free-edition  # PowerShell: $env:DATABRICKS_CONFIG_PROFILE="free-edition"
   databricks current-user me
   ```
4. **One-time Unity Catalog setup.** Run `scripts/bootstrap_uc.sql` in the SQL editor. It
   creates `bronze`, `silver` and `gold` in `dev` and `prod`.

## Deploy, run and verify a project

`scripts/bundle.sh <project> <dev|prod> <command>` is the single entry point, both for
people and for CI.

| Command | What it does |
|---|---|
| `validate` | renders dashboard templates, then `databricks bundle validate` |
| `deploy` | renders, then `databricks bundle deploy` (stops on destructive changes) |
| `run` | runs the project job `<project>_daily` and waits for it |
| `verify` | runs every widget query of the deployed dashboard |
| `summary` | shows deployed resources and their URLs |
| `capture-dashboard <key>` | pulls UI edits of a DEV dashboard back into the template |
| `destroy` | removes the deployment (refused for prod unless `ALLOW_PROD_DESTROY=1`) |

```bash
bash scripts/bundle.sh sales dev deploy
bash scripts/bundle.sh sales dev run
bash scripts/bundle.sh sales dev verify
```

Deployments land in `/Workspace/databricks-platform/<target>/<project>`. A manual DEV
deploy overwrites what CI deployed from `develop`; the next merge to `develop` puts it back.

## Release to PROD

1. Open a pull request from `develop` to `main` and wait for CI to pass.
2. Merge it. **Deploy PROD** starts and waits in the `prod` environment.
3. In GitHub, open **Actions → Deploy PROD → Review deployments** and approve.
4. The workflow deploys, runs the job, verifies the dashboard and tags
   `release/<project>/<timestamp>`.

## Roll back a project

1. List the rollback points:

   ```bash
   git fetch --tags
   git tag -l 'release/sales/*' --sort=-creatordate
   ```
2. In GitHub, open **Actions → Deploy PROD → Run workflow** and set
   `project = sales` and `ref = release/sales/<timestamp>`.
3. Approve the run. It restores the code, job, dashboard and metric views of that release.
4. Revert the faulty change on `main`. Otherwise the next merge that touches the project
   deploys it again.

Data is not rolled back. To restore a table, use Delta time travel, e.g.
`RESTORE TABLE prod.gold.sales_store_monthly TO VERSION AS OF <n>`.

## Change tables, KPIs or the dashboard

| Change | Steps |
|---|---|
| **Table** | Add or edit a `SELECT` file under `src/tables/<layer>/`, then add or edit its entry in `src/tables/tables.yml`. Tables build top to bottom. |
| **KPI** | Edit the measure in `src/metric_views/*.yaml`, the matching function in `src/sales/kpis.py` with its test, and `docs/kpi-definitions.md`. |
| **Dashboard** | Edit the DEV dashboard in the UI, run `bash scripts/bundle.sh sales dev capture-dashboard sales_overview`, review the diff and commit. |

Before pushing, run `.venv/Scripts/python -m pytest`. The tests check that every dashboard
field exists in the metric views and that every table reads only tables built before it.

## Add a project

1. Copy `projects/sales` to `projects/<name>`.
2. Rename the bundle (`bundle.name`), the job key (`<name>_daily`), the Python package and
   the landing volume.
3. Replace the SQL, metric views and dashboard with the new project's content.
4. Open a pull request. CI detects the new project automatically, and it deploys only when
   its own files change.

## Rotate tokens

Tokens expire (90 days is recommended). Before that:

1. Create a new token in Databricks (**Settings → Developer → Access tokens**).
2. Update GitHub:
   * DEV: **Settings → Secrets → Actions → `DATABRICKS_TOKEN`**.
   * PROD: **Environments → prod → `DATABRICKS_TOKEN`**.
3. Run **Deploy DEV** manually to confirm it works.
4. Revoke the old token in Databricks.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `401` / `invalid access token` in CI | Token expired or revoked. Rotate it (see above). |
| `Path (C:/Program Files/Git/Workspace/...) doesn't start with '/'` | Git Bash rewrote a workspace path. Prefix the command with `MSYS_NO_PATHCONV=1`. |
| Deploy stops asking to confirm deleting or recreating resources | A destructive change was detected. Review it locally with `bash scripts/bundle.sh <p> dev deploy`. Only after review, run `databricks bundle deploy --auto-approve`. |
| Job fails in `quality_checks` | The failing check is printed in the task output. KPI mismatches mean the metric view and `src/sales/kpis.py` disagree. |
| `verify` fails on a widget | The printed SQL is exactly what the widget runs. A missing measure or dimension means the dashboard and the metric view are out of sync. |
| Compute stopped for the day | The Free Edition fair-use quota is used up. Wait until the next day. |
| `prod is deployed by CI only` | Intentional. Use the *Deploy PROD* workflow. |
