# How it works (beginner guide)

A plain-language tour of the platform: where the code goes, what happens in Databricks, and
how `databricks.yml` and the bundle resources fit together. For the detailed design
decisions, see [architecture.md](architecture.md).

1. [The big picture](#1-the-big-picture)
2. [DEV and PROD](#2-dev-and-prod)
3. [How one change travels](#3-how-one-change-travels)
4. [What happens inside Databricks](#4-what-happens-inside-databricks)
5. [What a bundle is](#5-what-a-bundle-is)
6. [`databricks.yml`, section by section](#6-databricksyml-section-by-section)
7. [The resource files](#7-the-resource-files)
8. [What `bundle deploy` actually does](#8-what-bundle-deploy-actually-does)
9. [Commands you will use](#9-commands-you-will-use)
10. [Safety features](#10-safety-features)
11. [Glossary](#11-glossary)

## 1. The big picture

There are three places, and your code moves through them in order:

```text
 1. YOUR LAPTOP            2. GITHUB                       3. DATABRICKS
 ───────────────           ─────────────────────           ──────────────────────────
 write SQL / YAML   push   store the code           deploy  run the job, build tables,
 run tests locally  ────►  check it automatically   ─────►  show the dashboard
                           ask for approval (PROD)
```

Think of it as a restaurant:

| Place | Role in the restaurant |
|---|---|
| Laptop | The test kitchen, where you try a new recipe |
| GitHub | The head chef, who checks the recipe before it reaches customers |
| Databricks | The real kitchen, where the food is cooked and served |

## 2. DEV and PROD

One Databricks workspace, split into two separate areas:

| | **DEV** (practice) | **PROD** (real) |
|---|---|---|
| Git branch | `develop` | `main` |
| Data goes to catalog | `dev` | `prod` |
| Code lives in folder | `/Workspace/databricks-platform/dev/sales` | `/Workspace/databricks-platform/prod/sales` |
| Deploy | automatic after a merge | only after **you click Approve** |
| Daily schedule | paused | runs every day at 06:00 UTC |

DEV is where mistakes are allowed. PROD is what people trust.

## 3. How one change travels

Example: you change the formula for **net sales**.

1. **On your laptop**, edit the SQL or the metric-view YAML, run `pytest`, and push a
   feature branch.
2. **Open a pull request into `develop`.** GitHub runs **CI** automatically:
   * **lint**: is the code tidy?
   * **unit tests**: are the KPI formulas correct?
   * **bundle validate**: will Databricks accept the configuration?

   If anything is red, you cannot merge.
3. **Merge into `develop`.** **Deploy DEV** starts by itself. It uploads the code to the
   DEV folder, runs the job, and checks that every dashboard chart still works.
4. **Open a pull request from `develop` to `main` and merge it.** **Deploy PROD** waits
   until you approve it in GitHub, then does the same steps for PROD.
5. **Each PROD deploy gets a tag**, `release/sales/<time>`. That is your save point for
   rollback.

## 4. What happens inside Databricks

The job `sales_daily` runs six steps, one after another:

```text
generate data → BRONZE → SILVER → GOLD → METRIC VIEWS → QUALITY CHECKS
                                              │
                                              ▼
                                          DASHBOARD
```

| Step | What it is | In restaurant terms |
|---|---|---|
| **Generate data** | writes synthetic till receipts and door-counter files into the landing volume | the delivery truck arrives |
| **Bronze** | raw data, copied as-is | the groceries as delivered |
| **Silver** | cleaned data; bad rows go to a `_quarantine` table | washed and cut; rotten pieces set aside |
| **Gold** | totals per store per day and month | cooked dishes |
| **Metric views** | every KPI formula, written once (net sales, SSSG, ATV, UPT, YoY, …) | the official recipe book |
| **Quality checks** | 10 automatic tests on the results | taste test before serving |
| **Dashboard** | two pages, *Sales* and *Store performance* | the plate the customer sees |

* **Why metric views?** A KPI such as *conversion rate* is defined in one place only. The
  dashboard, SQL and Genie all use that same formula, so the numbers always agree.
* **Why SQL plus a Python wrapper?** You write only `SELECT` statements and list them in
  `src/tables/tables.yml`. The shared Python code (`shared/python/platform_common`) does
  the rest: create, merge, quarantine and check. Adding a table needs no new Python.

## 5. What a bundle is

A **Databricks Asset Bundle** is a folder that describes *everything one project needs* in
Databricks, written as files in Git:

```text
projects/sales/                 ← one bundle
├── databricks.yml              ← the "main settings" file
├── resources/                  ← what to create in Databricks
│   ├── storage.yml             │   a volume (folder for landing files)
│   ├── job.yml                 │   the daily job with its 6 tasks
│   └── dashboard.yml           │   the dashboard
├── src/                        ← the code the job runs (SQL, YAML, Python)
└── dashboards/                 ← dashboard template
```

Instead of clicking around the Databricks UI, you describe the job and dashboard in YAML.
The Databricks CLI then reads these files and makes the workspace match them. Because it
is all in Git, every change is reviewed, versioned and can be rolled back.

Each project (`sales`, later `finance`, `retail`) is its **own bundle**, so it deploys on
its own without touching the others.

## 6. `databricks.yml`, section by section

[`projects/sales/databricks.yml`](../projects/sales/databricks.yml) has five parts.

### `bundle`: the name

```yaml
bundle:
  name: sales
```

The project's name. It is used in folder paths (`${bundle.name}`) and to keep this
project's deployment separate from the others.

### `include`: the other files to read

```yaml
include:
  - resources/*.yml
```

The settings are split over several files to keep them short. This line tells the CLI to
read every YAML file in `resources/` as part of this bundle.

### `sync`: which files to upload

```yaml
sync:
  paths:
    - .                      # this project
    - ../../shared/python    # the shared Python package
  exclude:
    - tests/**               # tests stay in Git, not in Databricks
```

On deploy, the CLI uploads these files to the workspace. Because `shared/python` sits
outside the project folder, the upload keeps the repository layout:

```text
<deploy folder>/files/projects/sales/...
<deploy folder>/files/shared/python/...
```

The job's `entrypoint.py` relies on this layout to find the project code and the shared
code.

### `variables`: values that change per environment

```yaml
variables:
  catalog:                 # no default: each target must set it
  bronze_schema: {default: bronze}
  silver_schema: {default: silver}
  gold_schema:   {default: gold}
  warehouse_id:
    lookup:
      warehouse: Serverless Starter Warehouse   # name → ID, looked up at deploy time
  sample_start_date: {default: "2025-08-01"}
```

Variables are like blanks in a form. Resource files use them as `${var.catalog}`, and the
CLI fills them in at deploy time. So the **same** job definition writes to `dev.gold...`
in DEV and to `prod.gold...` in PROD.

`warehouse_id` is a *lookup*. You give the warehouse's name, and the CLI finds its ID, so
no workspace-specific ID is stored in Git.

### `targets`: one block per environment

A target is one place you can deploy to. The command `-t dev` or `-t prod` picks it.

```yaml
targets:
  dev:
    default: true                                          # used when no -t is given
    workspace:
      root_path: /Workspace/databricks-platform/dev/${bundle.name}
    permissions:
      - {level: CAN_MANAGE, group_name: users}             # everyone can work in DEV
    presets:
      trigger_pause_status: PAUSED                         # DEV schedule does not run
      tags: {project: sales, environment: dev}
    variables:
      catalog: dev                                         # fills in ${var.catalog}

  prod:
    mode: production                                       # extra safety checks
    workspace:
      root_path: /Workspace/databricks-platform/prod/${bundle.name}
    presets:
      tags: {project: sales, environment: prod}
    variables:
      catalog: prod
    run_as:
      user_name: ${workspace.current_user.userName}        # who the job runs as
    permissions:
      - {level: CAN_MANAGE, user_name: ${workspace.current_user.userName}}
      - {level: CAN_VIEW, group_name: users}               # others can only look
```

| Setting | Meaning |
|---|---|
| `root_path` | The workspace folder for this deployment. Without it, the CLI would use your personal home folder. |
| `permissions` | Who may change or view the job, dashboard and folder. |
| `presets` | Settings applied to every resource: pause the schedule, add tags. |
| `variables` | The values for this environment. They override the defaults above. |
| `mode: production` | Turns on extra safety checks before deploying, for example a warning when the deploy folder is a personal one. |
| `run_as` | The identity the PROD job runs as. Today it is the deploying user; later it should be a service principal. |

**How a value is chosen:** the target's value wins over the default. For example,
`${var.catalog}` becomes `dev` with `-t dev` and `prod` with `-t prod`.

## 7. The resource files

These are the **artefacts** the bundle creates in Databricks.

### `resources/storage.yml`: the landing volume

```yaml
volumes:
  sales_landing:
    catalog_name: ${var.catalog}
    schema_name: ${var.bronze_schema}
    name: sales_landing
    volume_type: MANAGED
```

Creates a Unity Catalog **volume**, a folder for files, at
`/Volumes/<catalog>/bronze/sales_landing`. The generator writes raw files here, and bronze
reads them.

### `resources/job.yml`: the daily job

```yaml
jobs:
  sales_daily:
    name: "[${bundle.target}] sales_daily"   # "[dev] sales_daily" / "[prod] sales_daily"
    max_concurrent_runs: 1                    # never two runs at once
    schedule:
      quartz_cron_expression: "0 0 6 * * ?"   # 06:00 every day
      timezone_id: UTC
    environments:
      - environment_key: default
        spec: {environment_version: "4"}     # serverless Python environment
    tasks:
      - task_key: generate_data
        spark_python_task:
          python_file: ../src/jobs/entrypoint.py
          parameters: [generate-data, --catalog=${var.catalog}, ...]
      - task_key: build_bronze
        depends_on: [{task_key: generate_data}]   # waits for the step before
        ...
```

* All six tasks run **the same Python file**, `entrypoint.py`. The first parameter says
  which step to do (`generate-data`, `build-tables`, `publish-metric-views`,
  `quality-checks`).
* `depends_on` chains the tasks, so they run in order and the job stops at the first
  failure.
* `--files-root=${workspace.file_path}` tells the task where the uploaded code lives.
* `python_file` is written relative to `job.yml`, so `../src/...` means
  `projects/sales/src/...`.

### `resources/dashboard.yml`: the dashboard

```yaml
dashboards:
  sales_overview:
    display_name: "[${bundle.target}] Sales & Store Performance"
    file_path: ../.build/dashboards/sales_overview.lvdash.json
    warehouse_id: ${var.warehouse_id}
    dataset_catalog: ${var.catalog}
    dataset_schema: ${var.gold_schema}
```

* The dashboard design is a JSON file. The committed template,
  `dashboards/sales_overview.lvdash.json`, contains placeholders like
  `__CATALOG__.__GOLD_SCHEMA__.sales_store_metrics`.
* Before each deploy, `scripts/bundle.sh` fills them in (`dev.gold...` or `prod.gold...`)
  and writes the result to `.build/`, which is not committed. The bundle deploys that
  filled-in copy.
* The placeholders are needed because metric-view datasets require full names, and bundle
  variables cannot reach inside the JSON file.

### What the bundle does *not* create

| Object | Created by | Why |
|---|---|---|
| Catalogs `dev`, `prod` and schemas `bronze`, `silver`, `gold` | you, once, with `scripts/bootstrap_uc.sql` | Several projects share them, so destroying one project must never delete them. |
| Tables (bronze, silver, gold, quarantine) | the job, every run | They are data, built from the SQL files. |
| Metric views | the job's `publish_metric_views` step | Metric views are not yet a bundle resource type. |

## 8. What `bundle deploy` actually does

When you run `bash scripts/bundle.sh sales dev deploy`:

```text
1. render      fill in the dashboard template          → .build/dashboards/*.json
2. read        databricks.yml + resources/*.yml, pick target "dev", fill in ${...}
3. upload      sync.paths files                         → <root_path>/files/
4. compare     what is in Git  vs  what was deployed last time (<root_path>/state/)
5. apply       create / update / delete the volume, job and dashboard to match
6. save        write the new state                      → <root_path>/state/
```

After a DEV deploy, the workspace looks like this:

```text
/Workspace/databricks-platform/dev/sales/
├── files/       the uploaded code (projects/sales/..., shared/python/...)
└── state/       the bundle's record of what it deployed
```

The **state** is how the bundle remembers what it created. If you delete a job from
`job.yml`, the next deploy sees it in the state and removes it from Databricks. If a
change would delete or recreate something, the deploy **stops and asks** instead of doing
it silently.

## 9. Commands you will use

`scripts/bundle.sh <project> <dev|prod> <command>` wraps the Databricks CLI. GitHub
Actions uses the same script, so local and CI behave the same.

| Command | Plain meaning |
|---|---|
| `validate` | "Is my configuration correct?" Checks without changing anything. |
| `deploy` | "Make Databricks match my files." Uploads code and creates or updates resources. |
| `run` | "Start the job now and wait." |
| `verify` | "Does every dashboard chart still work?" Runs each widget's query. |
| `summary` | "What is deployed, and where?" Lists resources with links. |
| `capture-dashboard <key>` | "Save my UI edits." Copies a DEV dashboard edited in the UI back into the template. |
| `destroy` | "Remove this deployment." Refused for PROD unless you set a special flag. |

A typical DEV session:

```bash
bash scripts/bundle.sh sales dev validate
bash scripts/bundle.sh sales dev deploy
bash scripts/bundle.sh sales dev run
bash scripts/bundle.sh sales dev verify
```

## 10. Safety features

* **No passwords in the code.** Secrets live only in GitHub Secrets.
* **PROD needs a human approval** in GitHub.
* **PROD cannot be deployed from a laptop** by accident; `bundle.sh` refuses unless
  `ALLOW_LOCAL_PROD=1` is set.
* **Only changed projects deploy.** A change in `sales` does not redeploy `finance`.
* **Rollback:** run *Deploy PROD* again with an old `release/...` tag. It restores the
  code, job, dashboard and KPI formulas. Data is not rolled back; use Delta time travel
  (`RESTORE TABLE`) for that.
* **Portable.** All logic is in `scripts/`, so moving to GitLab only means rewriting the
  pipeline YAML.

## 11. Glossary

| Word | Meaning |
|---|---|
| **Bundle** | A project folder with `databricks.yml` that describes its Databricks resources. |
| **Target** | One place a bundle can be deployed to: here `dev` or `prod`. |
| **Resource** | Something the bundle creates in Databricks: a job, a dashboard, a volume. |
| **Variable** | A blank such as `${var.catalog}`, filled in per target. |
| **Catalog / schema** | Unity Catalog's folders for tables: `dev.gold.sales_store_monthly`. |
| **Volume** | A Unity Catalog folder for files instead of tables. |
| **Metric view** | A view that stores KPI formulas, queried with `MEASURE(...)`. |
| **State** | The bundle's record of what it deployed last time. |
| **CI** | Automatic checks on every pull request. |
| **Environment (GitHub)** | A GitHub setting that holds secrets and an approval rule for `dev` or `prod`. |
