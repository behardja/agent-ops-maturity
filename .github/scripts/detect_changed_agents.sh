#!/usr/bin/env bash
# Detect which agents under agents/ were added or modified in this PR, filter to the
# DEPLOYABLE subset, and emit a GitHub Actions matrix. Pure git + grep + jq — no cloud.
#
# Why git diff (not a paths-filter list): a brand-new agents/<foo>/ folder shows up in
# the diff automatically, so new agents are detected with zero pre-registration.
#
# Deployable opt-in: an agent ships only if its agents-cli-manifest.yaml has
#     deployable: true        # false/absent => CI tests it, CD skips it
# (so a --prototype can live in agents/ without being deployed).
#
# Shared-code change (deployment/, eval_tool/, loop/, requirements-dev.txt, .github/):
# every deployable agent's serving could be affected, so the matrix expands to all of them.
#
# Outputs (to $GITHUB_OUTPUT):
#   agents      JSON array of agent dirs to deploy, e.g. ["agents/foo","agents/bar"]
#   has_agents  "true" | "false"   (false => CD is skipped, pipeline stays green)
set -euo pipefail

REF="${GITHUB_BASE_REF:?missing GITHUB_BASE_REF}"
git fetch origin "$REF" --depth=1 >/dev/null 2>&1 || true

# Resolve the diff base: prefer origin/<ref> (CI), else a local <ref>, else HEAD~1.
if   git rev-parse --verify -q "origin/$REF" >/dev/null 2>&1; then BASE="origin/$REF"
elif git rev-parse --verify -q "$REF"        >/dev/null 2>&1; then BASE="$REF"
else BASE="HEAD~1"; fi

DIFF="$(git diff --name-only "${BASE}...HEAD")"

# Shared-code change => consider every agent; else just the diffed agent dirs.
SHARED_RE='^(deployment/|eval_tool/|loop/|requirements-dev\.txt|\.github/workflows/)'
if echo "$DIFF" | grep -qE "$SHARED_RE"; then
  echo "shared code changed -> consider all agents" >&2
  CANDIDATES="$(ls -d agents/*/ 2>/dev/null | sed 's:/$::' || true)"
else
  CANDIDATES="$(echo "$DIFF" | grep -E '^agents/[^/]+/' | cut -d/ -f1-2 | sort -u || true)"
fi

# Keep only agents whose manifest opts in with `deployable: true`
# (tolerant of an optional quote / trailing space / comment).
DEPLOYABLE=""
while IFS= read -r dir; do
  [ -z "$dir" ] && continue
  manifest="$dir/agents-cli-manifest.yaml"
  [ -f "$manifest" ] || { echo "skip $dir (no manifest)" >&2; continue; }
  if grep -Eq '^[[:space:]]*deployable:[[:space:]]*"?true"?([[:space:]]|#|$)' "$manifest"; then
    DEPLOYABLE="${DEPLOYABLE}${dir}"$'\n'
  else
    echo "skip $dir (deployable != true)" >&2
  fi
done <<< "$CANDIDATES"

MATRIX="$(printf '%s' "$DEPLOYABLE" | grep -v '^$' | jq -R -s -c 'split("\n") | map(select(length>0))' 2>/dev/null || true)"
[ -z "$MATRIX" ] && MATRIX="[]"

echo "agents=$MATRIX" >> "${GITHUB_OUTPUT:?missing GITHUB_OUTPUT}"
if [ "$MATRIX" = "[]" ]; then
  echo "has_agents=false" >> "$GITHUB_OUTPUT"
else
  echo "has_agents=true" >> "$GITHUB_OUTPUT"
fi
echo "matrix: $MATRIX" >&2
