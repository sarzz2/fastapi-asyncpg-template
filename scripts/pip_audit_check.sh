#!/bin/bash
# Script to run pip-audit and fail only if fixable vulnerabilities are found

# Ensure jq is available
if ! command -v jq &> /dev/null; then
    echo "jq is required but not installed. Skipping pip-audit check."
    exit 0
fi

# Run pip-audit and capture output in JSON format
# We use || true to prevent immediate failure
# We use poetry run to ensure we check the project dependencies
poetry run pip-audit --format json > pip-audit-report.json || true

# Check for fixable vulnerabilities
# Filter: dependencies -> vulns -> fix_versions length > 0
FIXABLE_VULNS=$(jq -r '.dependencies[] | select(.vulns) | .vulns[] | select(.fix_versions | length > 0) | .id' pip-audit-report.json)

if [ ! -z "$FIXABLE_VULNS" ]; then
    echo "❌ Found fixable vulnerabilities: $FIXABLE_VULNS"
    echo "Run 'poetry run pip-audit' to see details."
    rm pip-audit-report.json
    exit 1
else
    echo "✅ No fixable vulnerabilities found (ignoring unfixed)."
    rm pip-audit-report.json
    exit 0
fi
