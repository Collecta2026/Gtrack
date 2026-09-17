#!/usr/bin/env bash
# ===================================================================
#  Gtrack - Import & Equipment Tracking
#  macOS / Linux quick start
# ===================================================================
set -e

# Gtrack uses its own GTRACK_DATABASE_URL. Clear any stray value for this shell
# so a test run can never touch another application's database.
unset GTRACK_DATABASE_URL

PY=$(command -v python3 || command -v python)

echo ""
echo "  [1/3] Installing dependencies..."
"$PY" -m pip install -r requirements.txt

echo ""
echo "  [2/3] Building the test database..."
if [ -f "instance/gtrack.db" ]; then
  echo "        An existing database was found - keeping it."
  echo "        Delete instance/gtrack.db first if you want a clean rebuild."
  "$PY" seed.py --keep
else
  "$PY" seed.py
fi

echo ""
echo "  [3/3] Starting Gtrack..."
echo "        Open http://127.0.0.1:5000"
echo "        Sign in with any demo account, password: demo1234"
echo "        Press Ctrl+C to stop."
echo ""
"$PY" run.py
