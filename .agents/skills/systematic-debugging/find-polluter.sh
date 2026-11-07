#!/usr/bin/env bash
# Bisection script to find which test creates unwanted files/state.
# Usage: ./find-polluter.sh <file_or_dir_to_check> <test_pattern>
# Example: ./find-polluter.sh 'db.sqlite3' 'backend/apps/**/test_*.py'

set -u

if [ $# -ne 2 ]; then
  echo "Usage: $0 <file_to_check> <test_pattern>"
  echo "Example: $0 'db.sqlite3' 'backend/apps/**/test_*.py'"
  exit 1
fi

POLLUTION_CHECK="$1"
TEST_PATTERN="$2"

if ! python -m pytest --version > /dev/null 2>&1; then
  echo "pytest is not runnable with 'python -m pytest' (activate the project venv first)."
  exit 1
fi

echo "Searching for test that creates: $POLLUTION_CHECK"
echo "Test pattern: $TEST_PATTERN"
echo ""

# Get list of test files (find prints paths with a leading ./)
case "$TEST_PATTERN" in
  ./*) FIND_PATTERN="$TEST_PATTERN" ;;
  *) FIND_PATTERN="./$TEST_PATTERN" ;;
esac
TEST_FILES=$(find . -path "$FIND_PATTERN" | sort)
TOTAL=$(printf '%s\n' "$TEST_FILES" | grep -c .)

if [ "$TOTAL" -eq 0 ]; then
  echo "No test files match: $TEST_PATTERN"
  exit 1
fi

echo "Found $TOTAL test files"
echo ""

COUNT=0
for TEST_FILE in $TEST_FILES; do
  COUNT=$((COUNT + 1))

  # Skip if pollution already exists
  if [ -e "$POLLUTION_CHECK" ]; then
    echo "Pollution already exists before test $COUNT/$TOTAL"
    echo "   Skipping: $TEST_FILE"
    continue
  fi

  echo "[$COUNT/$TOTAL] Testing: $TEST_FILE"

  # 0 = passed, 1 = tests failed: both are real outcomes, and either can leave pollution.
  # 2 = interrupted, 3 = internal error, 4 = usage error: stop instead of reporting all-clear.
  python -m pytest "$TEST_FILE" -q -p no:randomly
  STATUS=$?
  if [ "$STATUS" -eq 5 ]; then
    echo "   No tests collected in $TEST_FILE; skipping."
    continue
  fi
  if [ "$STATUS" -ge 2 ]; then
    echo "pytest exited $STATUS on $TEST_FILE; cannot continue."
    exit 1
  fi

  # Check if pollution appeared
  if [ -e "$POLLUTION_CHECK" ]; then
    echo ""
    echo "FOUND POLLUTER!"
    echo "   Test: $TEST_FILE"
    echo "   Created: $POLLUTION_CHECK"
    echo ""
    echo "Pollution details:"
    ls -la "$POLLUTION_CHECK"
    echo ""
    echo "To investigate:"
    echo "  python -m pytest $TEST_FILE    # Run just this test"
    echo "  cat $TEST_FILE                 # Review test code"
    exit 1
  fi
done

echo ""
echo "No polluter found - all tests clean!"
exit 0
