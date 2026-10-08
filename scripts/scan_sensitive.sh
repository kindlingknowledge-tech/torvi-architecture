#!/usr/bin/env bash
# Blocks commits/pushes that contain real identifiers.
#  - Generic patterns (Indian mobiles, AWS account IDs, ARNs, tokens) live here.
#  - Exact private terms (real society name, resource IDs) live in .sensitive-terms,
#    which is git-ignored and never committed. CI can supply it as a secret.
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

files=$(git ls-files 2>/dev/null || find . -type f -not -path './.git/*')
fail=0

check() {  # $1 label, $2 regex
  local hits
  hits=$(echo "$files" | xargs grep -nIE "$2" -- 2>/dev/null | grep -v 'scripts/scan_sensitive.sh' || true)
  if [[ -n "$hits" ]]; then echo "✗ $1"; echo "$hits" | sed 's/^/    /'; fail=1; fi
}

check "Indian mobile number"      '(\+?91[ -]?)?[6-9][0-9]{4}[ -]?[0-9]{5}\b'
check "AWS account ID / ARN"      '\b[0-9]{12}\b|arn:aws:[a-z0-9-]+:[a-z0-9-]*:[0-9]{12}'
check "Meta/WhatsApp token"       '\bEAA[A-Za-z0-9]{20,}'
check "Generic secret assignment" '(api[_-]?key|secret|token)[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9/+_-]{16,}'
check "Private key"               'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'

if [[ -f .sensitive-terms ]]; then
  while IFS= read -r term; do
    [[ -z "$term" || "$term" == \#* ]] && continue
    hits=$(echo "$files" | xargs grep -nIiF -- "$term" 2>/dev/null || true)
    if [[ -n "$hits" ]]; then echo "✗ private term: $term"; echo "$hits" | sed 's/^/    /'; fail=1; fi
  done < .sensitive-terms
fi

if [[ $fail -eq 0 ]]; then echo "✓ no sensitive data found"; fi
exit $fail
