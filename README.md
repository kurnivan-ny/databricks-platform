# Databricks CI/CD platform (PoC)

A local-first CI/CD proof of concept built on:

* **Databricks Free Edition**
* **Databricks Asset Bundles**
* **GitHub Actions**

The repo is a monorepo of independent project bundles. Environments are separated by Unity
Catalog catalogs (`dev`, `prod`), and PROD deployments wait for manual approval.

![Architecture](docs/diagrams/architecture.svg)

| Doc | What's in it |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Design, Free Edition findings, limitations, open assumptions |
| [docs/kpi-definitions.md](docs/kpi-definitions.md) | Sales KPI formulas (net sales, SSSG, margin, sales/m², traffic, conversion, ATV, UPT, ASP, …) |
| [docs/github-setup.md](docs/github-setup.md) | One-time GitHub setup: secrets, environments, approval, rules |

## Repository layout

```text
.github/workflows/      ci.yml · deploy-dev.yml · deploy-prod.yml · _deploy.yml (reusable)
projects/
  sales/                independent bundle (databricks.yml)
    resources/          job, landing volume, dashboard
    src/tables/         tables.yml registry + SQL SELECT files (silver/, gold/)
    src/metric_views/   Unity Catalog metric views (all KPI formulas)
    src/sales/          data generator, KPI reference, quality checks (Python)
    src/jobs/           entrypoint.py: the only Python entry point for job tasks
    dashboards/         AI/BI dashboard template (__CATALOG__ tokens)
    tests/              unit tests
shared/python/          platform_common: table builder, metric views, quality, identifiers
scripts/                bundle.sh, changed_projects.py, verify_dashboards.py, ... (CI-agnostic)
docs/                   architecture, KPI definitions, setup, SVG diagrams
```

## Local setup (Windows; macOS/Linux are the same with `/` paths)

Prerequisites:

* Python 3.11+
* Git (Git Bash runs `scripts/*.sh`)
* VS Code with the recommended extensions (`.vscode/extensions.json`)
* Databricks CLI **1.23.0**, the version in `.databricks-cli-version`. On Windows,
  download `databricks_cli_1.23.0_windows_amd64.zip` from the CLI's GitHub releases page
  and put `databricks.exe` on your PATH. On Linux/macOS, run
  `bash scripts/install_databricks_cli.sh`.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pytest                                 # 109 unit tests, no workspace needed
.venv/Scripts/ruff check . && .venv/Scripts/ruff format --check .
```

### Connect to the workspace (once)

1. In the Databricks SQL editor, run `scripts/bootstrap_uc.sql`. It creates the
   `bronze`, `silver` and `gold` schemas in `dev` and `prod`.
2. Create a personal access token: **Settings → Developer → Access tokens**.
3. Add a CLI profile and select it:

   ```bash
   databricks configure --profile free-edition     # prompts for host + token
   export DATABRICKS_CONFIG_PROFILE=free-edition   # PowerShell: $env:DATABRICKS_CONFIG_PROFILE="free-edition"
   databricks current-user me                      # sanity check
   ```

### Work with a project bundle

Run these from Git Bash with the venv active. `scripts/bundle.sh` is the same entry point
CI uses.

```bash
bash scripts/bundle.sh sales dev validate     # render dashboard + bundle validate
bash scripts/bundle.sh sales dev deploy       # deploy job, volume, dashboard to DEV
bash scripts/bundle.sh sales dev run          # run sales_daily: data → tables → metric views → checks
bash scripts/bundle.sh sales dev verify       # execute every dashboard widget query
```

PROD is deployed by CI only. `bundle.sh` refuses a local `prod` deploy unless
`ALLOW_LOCAL_PROD=1` is set.

## CI/CD

![CI/CD flow](docs/diagrams/cicd-flow.svg)

1. **Feature branch → PR into `develop`.** `ci.yml` runs ruff and pytest, then
   `bundle validate` for the dev and prod targets of **affected projects only**.
2. **Merge to `develop`.** `deploy-dev.yml` deploys the projects that changed since their
   `deploy/dev/<project>` tag. For each one it validates, deploys, runs the job as the
   integration test, verifies the dashboard, and moves the tag.
3. **PR `develop` → `main`.** The same CI runs.
4. **Merge to `main`.** `deploy-prod.yml` waits for approval in the GitHub `prod`
   environment. It then runs the same steps against the `prod` catalog and adds a
   `release/<project>/<timestamp>` tag.

**Roll back one project:** Actions → *Deploy PROD* → Run workflow with `project=sales` and
`ref=release/sales/<timestamp>`. Approve the run, then revert the bad change on `main`.

**Run any project by hand:** *Deploy DEV* → Run workflow with `projects=sales` (or `all`).

## Everyday changes

| Change | Where |
|---|---|
| New/changed table | add a `SELECT` file under `src/tables/<layer>/` and an entry in `src/tables/tables.yml` |
| New/changed KPI | `src/metric_views/*.yaml`, `src/sales/kpis.py`, `docs/kpi-definitions.md` |
| Dashboard layout | edit in the DEV dashboard UI, then `bash scripts/bundle.sh sales dev capture-dashboard sales_overview` and commit |
| New project | copy `projects/sales` to `projects/<name>`, rename the bundle, job and package; CI picks it up automatically |
