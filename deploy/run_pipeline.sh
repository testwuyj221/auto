#!/bin/bash
# Runs one full pipeline pass with logging, safe for unattended cron execution.
# Every run's output goes to a timestamped log file so you can check what
# happened without watching it live.

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

mkdir -p logs
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
LOG_FILE="logs/run_${TIMESTAMP}.log"

echo "=== Run started: $(date) ===" | tee -a "$LOG_FILE"

source venv/bin/activate

# PRIVACY: defaults to "private" so a bad run never goes live unattended.
# Change to "public" only once you've watched several runs and trust the output.
PRIVACY="${SHORTS_PRIVACY:-private}"

python main.py --privacy "$PRIVACY" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "=== Run succeeded: $(date) ===" | tee -a "$LOG_FILE"
else
    echo "=== Run FAILED (exit $EXIT_CODE): $(date) ===" | tee -a "$LOG_FILE"
fi

# Keep only the last 30 logs so disk doesn't fill up over months of runs
ls -t logs/run_*.log | tail -n +31 | xargs -r rm --

exit $EXIT_CODE
