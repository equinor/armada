#!/usr/bin/env bash
#
# sync-copilot.sh — Distribute the canonical Copilot configuration in this
# repository (armada/.github/copilot/) into a target repository.
#
# Usage:
#   ./scripts/sync-copilot.sh <path-to-target-repo>
#
# Behaviour:
#   1. Writes <target>/.github/prompts/review-pr.prompt.md from
#      armada/.github/copilot/prompts/review-pr.prompt.md, prefixed with an
#      AUTO-GENERATED header naming the source commit SHA.
#   2. Updates (or creates) <target>/.github/copilot-instructions.md, replacing
#      the block between
#          <!-- BEGIN SYNCED FROM equinor/armada@<sha> -->
#          <!-- END SYNCED -->
#      with the current contents of armada/.github/copilot/shared-instructions.md.
#      Content outside the markers is preserved verbatim. If the file does not
#      exist, it is created with a placeholder repo-specific header and the
#      synced block appended at the bottom. If the file exists but does not
#      yet contain the markers, the block is appended at the bottom.
#
# The script is idempotent: re-running it with a newer armada checkout
# re-stamps the SHA and refreshes the synced block in place.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <path-to-target-repo>" >&2
    exit 2
fi

target_repo="$1"

if [[ ! -d "$target_repo" ]]; then
    echo "error: target repo '$target_repo' is not a directory" >&2
    exit 1
fi

# Resolve the armada repo root (parent of the directory containing this script).
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
armada_root="$(cd "$script_dir/.." && pwd)"

src_prompt="$armada_root/.github/copilot/prompts/review-pr.prompt.md"
src_shared="$armada_root/.github/copilot/shared-instructions.md"

for f in "$src_prompt" "$src_shared"; do
    if [[ ! -f "$f" ]]; then
        echo "error: missing source file: $f" >&2
        exit 1
    fi
done

# Determine the armada commit SHA (short form). Fall back to "unknown" if the
# tree is not a git checkout.
if sha="$(git -C "$armada_root" rev-parse --short HEAD 2>/dev/null)"; then
    :
else
    sha="unknown"
fi

begin_marker="<!-- BEGIN SYNCED FROM equinor/armada@${sha} -->"
end_marker="<!-- END SYNCED -->"

target_github_dir="$target_repo/.github"
target_prompts_dir="$target_github_dir/prompts"
target_prompt="$target_prompts_dir/review-pr.prompt.md"
target_instructions="$target_github_dir/copilot-instructions.md"

mkdir -p "$target_prompts_dir"

# ---------------------------------------------------------------------------
# 1. Write the prompt file (always overwrite — this is a synced artifact).
# ---------------------------------------------------------------------------
{
    printf '<!-- AUTO-GENERATED from equinor/armada@%s — do not edit. Run scripts/sync-copilot.sh in armada to refresh. -->\n\n' "$sha"
    cat "$src_prompt"
} > "$target_prompt"

echo "wrote   $target_prompt"

# ---------------------------------------------------------------------------
# 2. Build the synced block to inject into copilot-instructions.md.
# ---------------------------------------------------------------------------
synced_block="$(
    printf '%s\n' "$begin_marker"
    printf '<!-- AUTO-GENERATED — do not edit between these markers. Run scripts/sync-copilot.sh in armada to refresh. -->\n\n'
    cat "$src_shared"
    printf '\n%s\n' "$end_marker"
)"

if [[ ! -f "$target_instructions" ]]; then
    # Create a fresh file with a placeholder repo-specific section followed by
    # the synced block.
    {
        cat <<'EOF'
# Copilot instructions

<!-- Repo-specific guidance goes here. Hand-edit freely above the synced
     block. The synced block at the bottom is overwritten by
     equinor/armada/scripts/sync-copilot.sh. -->

EOF
        printf '%s\n' "$synced_block"
    } > "$target_instructions"
    echo "created $target_instructions"
else
    # Existing file: replace the marker block, or append it if no markers yet.
    python3 - "$target_instructions" "$synced_block" <<'PYEOF'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
synced_block = sys.argv[2]

text = path.read_text()

pattern = re.compile(
    r"<!-- BEGIN SYNCED FROM equinor/armada@[^\s>]+ -->.*?<!-- END SYNCED -->",
    re.DOTALL,
)

if pattern.search(text):
    new_text = pattern.sub(lambda _: synced_block.rstrip("\n"), text)
    action = "updated"
else:
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    new_text = text + sep + synced_block
    action = "appended"

path.write_text(new_text)
print(f"{action} synced block in {path}")
PYEOF
fi

echo
echo "Done. Source: equinor/armada@${sha}"
