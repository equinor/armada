# New repository checklist

Conventions used by sara-*, flotilla, and isar-* repositories in `equinor/`. When creating a new service repo (usually from [`equinor/sara-python-template`](https://github.com/equinor/sara-python-template)), work through this checklist.

Every item includes a `gh`/`gh api` command to verify it. Run these against an existing well-configured repo (e.g. `equinor/sara-timeseries`) if you're unsure what the target state looks like.

---

## 0. Prerequisites

- Repo exists under `equinor/`.
- You have `Admin` on the repo (needed for most items below).
- `gh` is authenticated (`gh auth status`).

```bash
REPO=equinor/sara-your-service
```

---

## 1. Repository settings

| Setting | Value | Rationale |
|---|---|---|
| Allow squash merging | off | Rebase-only keeps linear history matching the required-linear-history ruleset |
| Allow merge commits | off | Same |
| Allow rebase merging | on | Only supported merge method |
| Automatically delete head branches | on | Keeps branch list clean |

**Set:**
```bash
gh api -X PATCH "/repos/$REPO" \
  -F allow_squash_merge=false \
  -F allow_merge_commit=false \
  -F allow_rebase_merge=true \
  -F delete_branch_on_merge=true
```

**Verify:**
```bash
gh api "/repos/$REPO" --jq '{squash:.allow_squash_merge, merge:.allow_merge_commit, rebase:.allow_rebase_merge, del:.delete_branch_on_merge}'
# Expected: {"squash":false,"merge":false,"rebase":true,"del":true}
```

---

## 2. Branch ruleset on `main`

We use a **repository ruleset** (not the legacy "branch protection" API) named `main`, targeting the default branch.

Rules:
- `deletion` — block deletion of `main`
- `non_fast_forward` — block force-pushes
- `required_linear_history`
- `pull_request` — require a PR before merging, with:
  - `required_approving_review_count: 1`
  - `require_code_owner_review: false`
  - `allowed_merge_methods: ["rebase"]`

**Set (adjust `bypass_actors` team id to match your admin/dev team):**
```bash
gh api -X POST "/repos/$REPO/rulesets" \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 1,
      "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false,
      "allowed_merge_methods": ["rebase"]
    }}
  ]
}
JSON
```

**Verify:**
```bash
gh api "/repos/$REPO/rulesets" --jq '.[] | {name, target, enforcement, rules: [.rules[]?.type]}'
```

Expected output includes a ruleset with `["deletion","non_fast_forward","required_linear_history","pull_request"]`.

**Known drift across existing repos:**
- `sara-utilities`, `sara-stid` have no ruleset — need one added.
- `sara-anonymizer` uses `required_approving_review_count: 0`; the convention is `1`.

---

## 3. Required status checks

Once the workflows have run at least once (so the check contexts are visible), add them to the ruleset. Standard checks for a Python service using the template:

- `test-and-lint-python-package / build (3.14)`
- `trivy-scan / Scan with Trivy`

**Add to the existing ruleset:**
```bash
RULESET_ID=$(gh api "/repos/$REPO/rulesets" --jq '.[] | select(.name=="main") | .id')
gh api -X PUT "/repos/$REPO/rulesets/$RULESET_ID" \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {"type": "pull_request", "parameters": {
      "required_approving_review_count": 1,
      "dismiss_stale_reviews_on_push": false,
      "require_code_owner_review": false,
      "require_last_push_approval": false,
      "required_review_thread_resolution": false,
      "allowed_merge_methods": ["rebase"]
    }},
    {"type": "required_status_checks", "parameters": {
      "strict_required_status_checks_policy": true,
      "required_status_checks": [
        {"context": "test-and-lint-python-package / build (3.14)"},
        {"context": "trivy-scan / Scan with Trivy"}
      ]
    }}
  ]
}
JSON
```

**Verify:**
```bash
gh api "/repos/$REPO/rulesets/$RULESET_ID" \
  --jq '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context'
```

---

## 4. GitHub Environments

Optional, but required if the deploy workflows are called with `environment_name: Development`.

| Environment | Required reviewers | Deployment branch policy |
|---|---|---|
| `Development` | usually none | `main` only |
| `Staging` | usually none | tags matching `v*` |
| `Production` | 1+ reviewers | tags matching `v*` |

**Create (example, `Development`):**
```bash
gh api -X PUT "/repos/$REPO/environments/Development" \
  -F 'deployment_branch_policy[protected_branches]=false' \
  -F 'deployment_branch_policy[custom_branch_policies]=true'
```

**Verify environments exist:**
```bash
gh api "/repos/$REPO/environments" --jq '.environments[].name'
```

**Known drift:** most sara repos have zero environments; `sara-anonymizer` has `Development` and `Staging` but no `Production`. Set up all three or none, but keep consistent.

---

## 5. Actions secrets

The deploy workflows in `equinor/armada` expect these **repository secrets** (or org-inherited). Only add per-repo secrets if the values are actually specific to this repo — otherwise inherit from the org.

Required:

- `ROBOTICS_ROBOTICSDEVACR_USERNAME` / `_PASSWORD` — dev registry
- `ROBOTICS_ROBOTICSSTAGINGACR_USERNAME` / `_PASSWORD` — staging registry
- `ROBOTICS_ROBOTICSPRODACR_USERNAME` / `_PASSWORD` — prod registry
- `ANALYTICS_INFRASTRUCTURE_DEPLOY_KEY` or `ROBOTICS_INFRASTRUCTURE_DEPLOY_KEY` — SSH deploy key on the target infrastructure repo

**Verify (names only, values never surface):**
```bash
gh api "/repos/$REPO/actions/secrets" --jq '.secrets[].name'
```

**Known drift:** several sara repos still have obsolete secrets (`ROBOTICS_AURORADEVACR_*`, `ROBOTICS_AURORAPRODACR_*`) left over from before the registry consolidation. Safe to delete:

```bash
gh api -X DELETE "/repos/$REPO/actions/secrets/ROBOTICS_AURORADEVACR_USERNAME"
# ...repeat for other obsolete ones
```

---

## 6. Actions variables

Set only if the service needs environment-specific values that are safe to expose.

- `AZURE_SUBSCRIPTION_ID` — required only if the workflow calls `run_dotnet_migrations.yml` (flotilla/sara pattern; not needed for typical Python services).

**Verify:**
```bash
gh api "/repos/$REPO/actions/variables" --jq '.variables[].name'
```

Empty is fine for most Python services.

---

## 7. Labels

Standard label set is managed by `synchronize_labels.yml` (already in the template). Trigger it once after the repo is created:

```bash
gh workflow run "Execute label synchronization" --repo "$REPO"
```

**Verify:**
```bash
gh label list --repo "$REPO"
```

Expected labels include `bug`, `enhancement`, `documentation`, `stale`, etc. — the exact list is defined in `equinor/armada/.github/workflows/synchronize_labels.yml`.

---

## 8. Dependabot

Ships with the template as `.github/dependabot.yml` if you want it — otherwise not enabled by default. Verify a config is present:

```bash
gh api "/repos/$REPO/contents/.github/dependabot.yml" --jq '.path' 2>/dev/null \
  || echo "No dependabot.yml (optional)"
```

---

## 9. CODEOWNERS (optional)

If a specific team should be auto-requested on PRs, add `.github/CODEOWNERS`. Not standard across the sara-* repos today, so skip unless you have a reason.

---

## 10. Register in infrastructure

Not a GitHub setting, but easily forgotten:

- Add overlays for `development`, `staging`, `production` in `equinor/analytics-infrastructure` (sara services) or `equinor/robotics-infrastructure` (flotilla/isar services) under `k8s_kustomize/overlays/*/kustomization.yaml`.
- Registry image path must match what the workflow passes as `image_name` (e.g. `robotics/sara-your-service`).

---

## Compliance check for existing repos

Quick one-shot verification against an existing repo:

```bash
REPO=equinor/sara-your-service

# Repo settings
gh api "/repos/$REPO" --jq '{
  squash:.allow_squash_merge, merge:.allow_merge_commit,
  rebase:.allow_rebase_merge, del:.delete_branch_on_merge
}'

# Rulesets
gh api "/repos/$REPO/rulesets" --jq '.[] | {name, rules: [.rules[]?.type]}'

# Environments
gh api "/repos/$REPO/environments" --jq '.environments[].name'

# Secrets
gh api "/repos/$REPO/actions/secrets" --jq '.secrets[].name'
```

---

## Notes

- These values are **conventions**, not enforced by tooling. If enforcement matters, promote them to an **org-level ruleset** targeting `sara-*` / `flotilla` / `isar-*`; that removes the per-repo drift problem entirely.
- Repos created before this document exists likely deviate. See the "Known drift" callouts under each section.
