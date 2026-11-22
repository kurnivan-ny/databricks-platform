-- One-time Unity Catalog setup for the PoC (run once in the Databricks SQL editor).
-- The catalogs `dev` and `prod` already exist. Schemas are shared by all projects, so
-- they are created here rather than by any single project bundle (a bundle destroy must
-- never drop a schema another project uses).

CREATE SCHEMA IF NOT EXISTS dev.bronze COMMENT 'Raw landing data (all projects).';
CREATE SCHEMA IF NOT EXISTS dev.silver COMMENT 'Cleaned, conformed data (all projects).';
CREATE SCHEMA IF NOT EXISTS dev.gold   COMMENT 'Business measures and metric views (all projects).';

CREATE SCHEMA IF NOT EXISTS prod.bronze COMMENT 'Raw landing data (all projects).';
CREATE SCHEMA IF NOT EXISTS prod.silver COMMENT 'Cleaned, conformed data (all projects).';
CREATE SCHEMA IF NOT EXISTS prod.gold   COMMENT 'Business measures and metric views (all projects).';

-- Check:
SHOW SCHEMAS IN dev;
SHOW SCHEMAS IN prod;
