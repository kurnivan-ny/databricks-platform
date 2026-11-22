import json
import subprocess

import pytest
from changed_projects import affected_by_paths, deploy_candidates, discover_projects, main, select

PROJECTS = ["finance", "sales"]


def test_affected_by_paths():
    assert affected_by_paths(["projects/sales/src/x.sql"], PROJECTS) == ["sales"]
    assert affected_by_paths(["README.md", ".github/workflows/ci.yml"], PROJECTS) == []
    assert affected_by_paths(["shared/python/platform_common/tables.py"], PROJECTS) == PROJECTS
    assert affected_by_paths(["projects\\finance\\databricks.yml"], PROJECTS) == ["finance"]
    assert affected_by_paths(["projects/salesforce/x"], PROJECTS) == []


def git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def commit(repo, path, content="x"):
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"change {path}")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "ci@example.invalid")
    git(tmp_path, "config", "user.name", "CI")
    for project in PROJECTS:
        commit(tmp_path, f"projects/{project}/databricks.yml", f"bundle: {{name: {project}}}")
    commit(tmp_path, "projects/notabundle/readme.md")
    return tmp_path


def test_discover_projects_requires_bundle_file(repo):
    assert discover_projects(repo) == PROJECTS


def test_deploy_mode_uses_per_project_tags(repo):
    assert deploy_candidates(repo, "dev") == PROJECTS  # nothing deployed yet
    git(repo, "tag", "deploy/dev/sales")
    git(repo, "tag", "deploy/dev/finance")
    assert deploy_candidates(repo, "dev") == []

    commit(repo, "projects/sales/src/a.sql")
    commit(repo, "docs/notes.md")
    assert deploy_candidates(repo, "dev") == ["sales"]
    assert deploy_candidates(repo, "prod") == PROJECTS  # prod tags are independent

    commit(repo, "shared/python/x.py")
    assert deploy_candidates(repo, "dev") == PROJECTS


def test_diff_mode_against_branch(repo, capsys):
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, "projects/finance/src/b.sql")
    assert main(["diff", "--base", "main", "--repo", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out) == ["finance"]


def test_select_mode(repo):
    assert select(repo, "all") == PROJECTS
    assert select(repo, " sales , sales") == ["sales"]
    with pytest.raises(SystemExit):
        select(repo, "marketing")


def test_github_output(repo, tmp_path, monkeypatch, capsys):
    output = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    main(["select", "--projects", "sales", "--repo", str(repo), "--github-output"])
    assert output.read_text() == 'projects=["sales"]\n'
