#!/usr/bin/env bash
# Checks a candidate's changed files against allowed-path patterns (ADR-020). CI pipes in the changed paths,
# NUL-separated (git diff --name-only -z), and sets CANDIDATE_ALLOWED_PATHS from a repository Actions variable:
# one extended regular expression per line, matched against the whole path; blank lines and # lines are ignored.
# Prints counts and the refused files only, never the patterns.
#   exit 0  every changed file is allowed
#   exit 1  at least one file is outside the patterns
#   exit 2  the pattern list is missing, empty or invalid (fails closed)
set -uo pipefail

patterns=()
while IFS= read -r line; do
  line="${line%$'\r'}"
  [[ -z "${line//[[:space:]]/}" || "$line" == \#* ]] && continue
  patterns+=("$line")
done <<<"${CANDIDATE_ALLOWED_PATHS:-}"

if [ "${#patterns[@]}" -eq 0 ]; then
  echo "::error::CANDIDATE_ALLOWED_PATHS is not set; refusing every candidate"
  exit 2
fi
for p in "${patterns[@]}"; do
  # bash names an invalid pattern on stderr, so that is silenced; status 2 means the pattern did not compile
  ( [[ "" =~ ^($p)$ ]] ) 2>/dev/null
  if [ $? -eq 2 ]; then
    echo "::error::CANDIDATE_ALLOWED_PATHS holds an invalid pattern; refusing every candidate"
    exit 2
  fi
done

total=0 allowed=0 refused=0
while IFS= read -r -d '' f; do
  total=$((total + 1))
  ok=0
  for p in "${patterns[@]}"; do
    if [[ "$f" =~ ^($p)$ ]]; then ok=1; break; fi
  done
  if [ "$ok" -eq 1 ]; then
    allowed=$((allowed + 1))
  else
    refused=$((refused + 1))
    # GitHub's workflow-command escaping, so a file name can't start a command of its own
    safe="${f//%/%25}"; safe="${safe//$'\r'/%0D}"; safe="${safe//$'\n'/%0A}"
    echo "::error::a candidate may not change $safe"
  fi
done

echo "$total changed file(s): $allowed allowed, $refused refused"
[ "$refused" -eq 0 ]
