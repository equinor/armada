#!/usr/bin/env python3
"""Fail if a change adds EF Core migrations that sort before the target branch's latest migration.

EF Core applies migrations ordered by ID (the timestamped file name). If a migration created
before another, already merged migration is merged afterwards, fresh databases and existing
databases apply them in different orders. This check compares the migration IDs in the
proposed (merged) tree with those on the target commit and requires every new ID to sort
after the latest existing one.

"""

import argparse
import re
import subprocess
import sys
from pathlib import PurePosixPath
from typing import List, Set

MIGRATION_FILE_PATTERN = re.compile(r"^(\d{14}_[^.]+)\.cs$")


def list_migration_ids(revision: str, migrations_dir: str, repo: str) -> Set[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", revision, "--", migrations_dir],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not list '{migrations_dir}' at '{revision}': {result.stderr.strip()}"
        )
    ids: Set[str] = set()
    for path in result.stdout.splitlines():
        match = MIGRATION_FILE_PATTERN.match(PurePosixPath(path).name)
        if match:
            ids.add(match.group(1))
    return ids


def find_out_of_order_migrations(base_ids: Set[str], head_ids: Set[str]) -> List[str]:
    if not base_ids:
        return []
    latest_base_id = max(base_ids)
    return sorted(i for i in head_ids - base_ids if i <= latest_base_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Target branch commit")
    parser.add_argument("--head", default="HEAD", help="Proposed (merged) commit")
    parser.add_argument(
        "--migrations-dir",
        required=True,
        help="Migrations directory relative to the repository root (Ex: 'api/Migrations')",
    )
    parser.add_argument("--repo", default=".", help="Path to the git repository")
    args = parser.parse_args()

    migrations_dir = args.migrations_dir.strip("/")
    try:
        base_ids = list_migration_ids(args.base, migrations_dir, args.repo)
        head_ids = list_migration_ids(args.head, migrations_dir, args.repo)
    except RuntimeError as error:
        print(f"::error::{error}")
        return 1

    new_ids = sorted(head_ids - base_ids)
    out_of_order = find_out_of_order_migrations(base_ids, head_ids)
    if not out_of_order:
        print(
            f"Migration order OK: {len(new_ids)} new migration(s) in '{migrations_dir}'."
        )
        return 0

    latest_base_id = max(base_ids)
    print(
        "::error::New migrations must be newer than the latest migration on the target branch."
    )
    print(f"Latest migration on the target branch: {latest_base_id}")
    print("New migrations that are older than or equal to it:")
    for migration_id in out_of_order:
        print(f"  - {migration_id}")
    print(
        "\nAnother migration was merged after these were generated. Update your branch with the "
        "target branch, remove your own unmerged migrations (and revert their snapshot changes), "
        "and regenerate them with 'dotnet ef migrations add'. Do not only rename the files: the "
        "migration and model snapshot must be regenerated on top of the latest target branch.\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
