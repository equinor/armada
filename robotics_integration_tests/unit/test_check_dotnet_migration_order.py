import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "scripts"
    / "check_dotnet_migration_order.py"
)

MIGRATION_A = "20261016111819_MigrationA"
MIGRATION_B = "20261023063911_MigrationB"
MIGRATION_C = "20261030080000_MigrationC"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def add_migration(repo: Path, migrations_dir: str, migration_id: str) -> None:
    directory = repo / migrations_dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{migration_id}.cs").write_text(f"// {migration_id}\n")
    (directory / f"{migration_id}.Designer.cs").write_text(
        f'[Migration("{migration_id}")]\n'
    )
    (directory / "AppDbContextModelSnapshot.cs").write_text(f"// {migration_id}\n")


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "--allow-empty", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def run_check(
    repo: Path, base: str, head: str = "HEAD", migrations_dir: str = "api/Migrations"
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--base",
            base,
            "--head",
            head,
            "--migrations-dir",
            migrations_dir,
            "--repo",
            str(repo),
        ],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    commit(tmp_path, "initial")
    return tmp_path


def create_branch_with_migrations(
    repo: Path,
    branch: str,
    start: str,
    migration_ids: List[str],
    migrations_dir: str = "api/Migrations",
) -> str:
    git(repo, "checkout", "-q", "-b", branch, start)
    for migration_id in migration_ids:
        add_migration(repo, migrations_dir, migration_id)
    return commit(repo, branch)


def merge_into_main(repo: Path, branch: str) -> str:
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-X", "theirs", "-m", f"merge {branch}", branch)
    return git(repo, "rev-parse", "HEAD")


def test_stale_migration_fails_after_newer_migration_is_merged(repo: Path) -> None:
    start = git(repo, "rev-parse", "main")
    create_branch_with_migrations(repo, "a", start, [MIGRATION_A])
    create_branch_with_migrations(repo, "b", start, [MIGRATION_B])
    main_after_b = merge_into_main(repo, "b")

    git(repo, "checkout", "-q", "a")
    git(repo, "rebase", "-q", "-X", "theirs", "main")

    result = run_check(repo, base=main_after_b)

    assert result.returncode == 1
    assert MIGRATION_A in result.stdout
    assert f"Latest migration on the target branch: {MIGRATION_B}" in result.stdout
    assert "regenerate" in result.stdout


def test_regenerated_migration_passes(repo: Path) -> None:
    start = git(repo, "rev-parse", "main")
    create_branch_with_migrations(repo, "b", start, [MIGRATION_B])
    main_after_b = merge_into_main(repo, "b")
    create_branch_with_migrations(repo, "a", main_after_b, [MIGRATION_C])

    result = run_check(repo, base=main_after_b)

    assert result.returncode == 0, result.stdout


def test_merge_order_b_a_c_requires_each_to_regenerate(repo: Path) -> None:
    start = git(repo, "rev-parse", "main")
    create_branch_with_migrations(repo, "b", start, ["20261020000000_B"])
    main_after_b = merge_into_main(repo, "b")

    create_branch_with_migrations(repo, "a", main_after_b, ["20261021000000_A"])
    main_after_a = merge_into_main(repo, "a")

    create_branch_with_migrations(repo, "c-stale", main_after_b, ["20261019000000_C"])
    assert run_check(repo, base=main_after_a).returncode == 1

    create_branch_with_migrations(repo, "c", main_after_a, ["20261022000000_C"])
    assert run_check(repo, base=main_after_a).returncode == 0


def test_multiple_newer_migrations_pass(repo: Path) -> None:
    start = git(repo, "rev-parse", "main")
    create_branch_with_migrations(repo, "base", start, [MIGRATION_A])
    main_after_base = merge_into_main(repo, "base")
    create_branch_with_migrations(
        repo, "feature", main_after_base, [MIGRATION_B, MIGRATION_C]
    )

    assert run_check(repo, base=main_after_base).returncode == 0


def test_no_new_migrations_passes(repo: Path) -> None:
    start = git(repo, "rev-parse", "main")
    create_branch_with_migrations(repo, "base", start, [MIGRATION_B])
    main_after_base = merge_into_main(repo, "base")
    git(repo, "checkout", "-q", "-b", "feature", main_after_base)
    (repo / "api" / "Migrations" / "AppDbContextModelSnapshot.cs").write_text("// x\n")
    commit(repo, "snapshot only")

    assert run_check(repo, base=main_after_base).returncode == 0


def test_empty_target_history_passes(repo: Path) -> None:
    start = git(repo, "rev-parse", "main")
    create_branch_with_migrations(repo, "feature", start, [MIGRATION_A, MIGRATION_B])

    assert run_check(repo, base=start).returncode == 0


def test_compares_with_latest_target_not_merge_base(repo: Path) -> None:
    start = git(repo, "rev-parse", "main")
    feature_head = create_branch_with_migrations(repo, "a", start, [MIGRATION_A])
    main_after_b = create_branch_with_migrations(repo, "b", start, [MIGRATION_B])

    result = run_check(repo, base=main_after_b, head=feature_head)

    assert result.returncode == 1
    assert MIGRATION_A in result.stdout


@pytest.mark.parametrize("migrations_dir", ["api/Migrations", "backend/api/Migrations"])
def test_supports_consumer_layouts(repo: Path, migrations_dir: str) -> None:
    start = git(repo, "rev-parse", "main")
    create_branch_with_migrations(repo, "b", start, [MIGRATION_B], migrations_dir)
    main_after_b = merge_into_main(repo, "b")
    create_branch_with_migrations(
        repo, "a", main_after_b, [MIGRATION_A], migrations_dir
    )

    result = run_check(repo, base=main_after_b, migrations_dir=migrations_dir)

    assert result.returncode == 1
    assert MIGRATION_A in result.stdout


def test_unknown_base_fails(repo: Path) -> None:
    result = run_check(repo, base="0" * 40)

    assert result.returncode == 1
    assert "::error::" in result.stdout
