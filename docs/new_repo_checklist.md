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

Set up all three environments or none, but keep the choice consistent across the service's dev/staging/prod workflows.

---

## 5. Actions secrets

The deploy workflows in `equinor/armada` expect these **repository secrets** (or org-inherited). Only add per-repo secrets if the values are actually specific to this repo — otherwise inherit from the org.

Required:

- `ROBOTICS_INFRASTRUCTURE_DEPLOY_KEY` — SSH deploy key on `equinor/robotics-infrastructure`

Registry authentication is done via OIDC federated credentials (see §7), not username/password secrets. If your workflow still uses `use_oidc: false`, you also need `ROBOTICS_ROBOTICS{DEV,STAGING,PROD}ACR_USERNAME` / `_PASSWORD`.

**Verify (names only, values never surface):**
```bash
gh api "/repos/$REPO/actions/secrets" --jq '.secrets[].name'
```

---

## 6. Actions variables

Set only if the service needs environment-specific values that are safe to expose.

- `AZURE_SUBSCRIPTION_ID` — required for OIDC registry auth (see §7) and for workflows that call `run_dotnet_migrations.yml`.
- `AZURE_TENANT_ID` — required for OIDC registry auth.

**Verify:**
```bash
gh api "/repos/$REPO/actions/variables" --jq '.variables[].name'
```

---

## 7. OIDC registry authentication

Service repos authenticate to the robotics ACR with a federated credential instead of a stored username/password. This requires GitHub-side configuration plus a matching federated credential on the Azure-side managed identity.

### GitHub side

**Repo-level variables** (see §6):
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_TENANT_ID`

**Environments** (see §4): `Development`, `Staging`, `Production` — all three are required, because the OIDC subject claim carries the environment name and the federated credential on the Azure side is bound to `repo:<org>/<repo>:environment:<name>`.

**Per-environment variables:** each environment needs `ACR_PUSH_CLIENT_ID` set to the client ID of the managed identity that has AcrPush on the corresponding registry (dev / staging / prod).

**Workflow input:** the caller sets `use_oidc: true`, `environment_name: <env>`, and `azure_subscription_id: ${{ vars.AZURE_SUBSCRIPTION_ID }}`. See `sara-utilities` for a reference wrapper.

### Azure side

The managed identity referenced by each `ACR_PUSH_CLIENT_ID` must have a federated credential whose subject matches `repo:equinor/<repo>:environment:<env>`. Setting that up is out of scope for this checklist — coordinate with whoever owns the robotics ACR subscription.

**Verify (GitHub side only):**
```bash
gh api "/repos/$REPO/actions/variables" --jq '.variables[].name'
gh api "/repos/$REPO/environments" --jq '.environments[].name'
for env in Development Staging Production; do
  echo "$env:"
  gh api "/repos/$REPO/environments/$env/variables" --jq '.variables[].name'
done
```

Expected: repo vars include `AZURE_SUBSCRIPTION_ID` and `AZURE_TENANT_ID`; all three environments exist; each environment has `ACR_PUSH_CLIENT_ID`.

---

---

## 8. Labels

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

## 9. Dependency updates

Use native Dependabot for Python projects managed with `pyproject.toml` and `uv.lock`, rather than a scheduled workflow that upgrades the lockfile and creates its own PR. Commit both files and add this entry to `.github/dependabot.yml`, preserving any existing Docker, GitHub Actions, npm, or other ecosystem entries:

```yaml
version: 2
updates:
  - package-ecosystem: uv
    directory: /
    schedule:
      interval: weekly
      day: monday
    allow:
      - dependency-type: all
    open-pull-requests-limit: 5
    groups:
      python-patch-minor:
        patterns:
          - "*"
        update-types:
          - patch
          - minor
      python-major:
        patterns:
          - "*"
        update-types:
          - major
```

`dependency-type: all` includes transitive lockfile dependencies, not just direct declarations. Keep patch/minor updates together and major updates in a separate group for review; the five-PR limit applies to version updates for this entry. Python updates run weekly on Monday. Keep other ecosystem schedules and groups intentional rather than replacing them with the Python settings.

Inventory **all** Python projects, including nested tools, examples, and test projects. A root `directory: /` entry does not cover independent nested projects with their own lockfiles. Add an entry for each such directory, or replace `directory` with an explicit `directories` list using the same schedule, allowance, PR limit, and groups. Do not configure overlapping entries for the same ecosystem and target branch. Members sharing a uv workspace's root lockfile should be maintained through that workspace root rather than treated as independent lockfiles.

Dependabot natively applies a **three-day cooldown to version updates**, even without a `cooldown` setting; security updates are not delayed by this default. An eligible release is picked up on the next scheduled run after its cooldown. See the [Dependabot cooldown reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#cooldown-).

Remove the repository's obsolete scheduled updater caller when enabling the replacement. Do not remove an Armada reusable helper until all active callers have migrated and merged; verify live default-branch workflows as well as code search results, which can lag behind merges. The Python helper `compile_python_requirements_and_create_pr.yml` has been retired after its remaining active callers (`sara-sap`, `isar-taurob-for-open-source`, and `alitra`) migrated to native Dependabot. The retained reference in archived `isar-anymal-archived-2` is intentionally exempt; do not modify archived repositories.

Keep `npm_dependency_update_and_create_pr.yml`: it is still used by `pointilla_maps`. Close old updater PRs and delete their branches only **after the replacement configuration has merged**.

**Verify:**
```bash
gh api "/repos/$REPO/contents/.github/dependabot.yml" --jq '.content' | base64 --decode
gh api "/repos/$REPO/git/trees/main?recursive=1" \
  --jq '.tree[].path | select(test("(^|/)(pyproject\\.toml|uv\\.lock)$"))'
gh api "/repos/$REPO/actions/workflows" \
  --jq '.workflows[] | {name, path, state}'
```

Confirm every independent `uv.lock` directory is covered and old scheduled updater callers are gone. After merge, inspect Dependabot's update logs and generated PRs to confirm the configuration is active.

---

## 10. CODEOWNERS (optional)

If a specific team should be auto-requested on PRs, add `.github/CODEOWNERS`. Not standard across the sara-* repos today, so skip unless you have a reason.

---

## 11. Register in infrastructure

Not a GitHub setting, but easily forgotten:

- Add overlays for `development`, `staging`, `production` in `equinor/robotics-infrastructure` under `k8s_kustomize/overlays/*/kustomization.yaml`.
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

# Repo variables (should include AZURE_SUBSCRIPTION_ID, AZURE_TENANT_ID for OIDC)
gh api "/repos/$REPO/actions/variables" --jq '.variables[].name'

# Environment variables (each of Development/Staging/Production should have ACR_PUSH_CLIENT_ID)
for env in Development Staging Production; do
  echo "$env:"
  gh api "/repos/$REPO/environments/$env/variables" --jq '.variables[].name'
done
```

---

## Notes

- These values are **conventions**, not enforced by tooling. If enforcement matters, promote them to an **org-level ruleset** targeting `sara-*` / `flotilla` / `isar-*`; that removes the per-repo drift problem entirely.
