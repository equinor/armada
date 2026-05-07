# Shared Copilot configuration for the Flotilla–SARA system

This directory holds the **canonical** GitHub Copilot configuration shared across
the Flotilla–SARA repositories (e.g. `flotilla`, `isar`, `isar-robot`,
`isar-anymal`, `isar-taurob`, `sara`, `sara-*`, `robotics-infrastructure`,
`analytics-infrastructure`, `eq_robot_utility_scripts`).

Copilot only reads files that physically exist inside the repo it is operating
on. To avoid hand-maintaining N copies, this repo (`armada`) is the single
source of truth, and consuming repos receive synced copies stamped with the
source commit SHA.

## Contents

```
.github/copilot/
├── README.md                        # this file
├── shared-instructions.md           # block injected into each consumer's
│                                    # .github/copilot-instructions.md
└── prompts/
    └── review-pr.prompt.md          # full PR-review prompt for VS Code / CLI
```

A small bash script `armada/scripts/sync-copilot.sh` distributes these files
into a target repo.

## How to consume in another repo

From an `armada` checkout, run:

```bash
./scripts/sync-copilot.sh <path-to-target-repo>
```

The script will:

1. Copy `prompts/review-pr.prompt.md` to
   `<target>/.github/prompts/review-pr.prompt.md` with an
   `<!-- AUTO-GENERATED from equinor/armada@<sha> -->` header.
2. Update (or create) `<target>/.github/copilot-instructions.md`, replacing the
   block between

   ```
   <!-- BEGIN SYNCED FROM equinor/armada@<sha> -->
   ...
   <!-- END SYNCED -->
   ```

   with the current contents of `shared-instructions.md`. Any content **outside**
   those markers is preserved verbatim.

The script is idempotent: running it again with a newer `armada` checkout
re-stamps the SHA and refreshes the synced block in place.

## Editing rules

- **Edit `shared-instructions.md` and `prompts/review-pr.prompt.md` here, in
  `armada`.** Never hand-edit the synced copies in consuming repos — they will
  be overwritten on the next sync.
- Repo-specific guidance belongs in the consumer's own
  `.github/copilot-instructions.md`, *outside* the synced markers.
- Prefer additive changes; consumers may rely on the existing structure.

## Why `armada`?

`armada` is the integration-test harness that already orchestrates the whole
Flotilla–SARA system (it runs container images of `flotilla`, `isar-robot` and
`sara` together), so it is the natural home for cross-system knowledge and
review heuristics.
