import entrypoint


def test_bootstrap_locates_repo_without_files_root(project_dir):
    assert entrypoint._bootstrap(None) == project_dir


def test_bootstrap_accepts_workspace_style_root(project_dir, repo_root):
    assert entrypoint._bootstrap(str(repo_root)) == project_dir


def test_landing_path_is_built_from_identifiers():
    args = entrypoint.parse_args(["generate-data", "--catalog", "prod"])
    assert entrypoint._landing_path(args) == "/Volumes/prod/bronze/sales_landing"


def test_generate_data_is_incremental(tmp_path, monkeypatch, project_dir):
    monkeypatch.setattr(entrypoint, "_landing_path", lambda args: str(tmp_path))
    argv = [
        "generate-data",
        "--catalog",
        "dev",
        "--start-date",
        "2026-01-01",
        "--end-date",
        "2026-01-03",
    ]

    entrypoint.cmd_generate_data(entrypoint.parse_args(argv), project_dir)
    transactions = sorted(p.name for p in (tmp_path / "transactions").iterdir())
    assert transactions == [f"transactions_2026-01-0{d}.json" for d in (1, 2, 3)]
    assert len(list((tmp_path / "traffic").iterdir())) == 3
    assert (tmp_path / "stores" / "stores.json").is_file()
    assert not list(tmp_path.rglob("_tmp_*")), "temp files must be renamed away"

    first_write = (tmp_path / "transactions" / "transactions_2026-01-01.json").stat().st_mtime_ns
    argv[-1] = "2026-01-04"
    entrypoint.cmd_generate_data(entrypoint.parse_args(argv), project_dir)
    assert len(list((tmp_path / "transactions").iterdir())) == 4
    # Existing days are not rewritten.
    assert (
        tmp_path / "transactions" / "transactions_2026-01-01.json"
    ).stat().st_mtime_ns == first_write
