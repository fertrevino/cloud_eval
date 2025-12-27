#!/usr/bin/env sh
set -e

# If the caller explicitly runs `python ...`, hand off directly (so verification scripts still work).
if [ $# -gt 0 ] && [ "$1" = "python" ]; then
  exec "$@"
fi

# If called with "suite" argument, run the suite once and exit
if [ $# -eq 0 ] || [ "$1" = "suite" ]; then
  mkdir -p /app/reports
  chmod -R a+rwx /app/reports
  export PYTHONPATH="${PYTHONPATH:-/app/src}"
  exec python3 -m cloud_eval.suite
fi

# If called with "service" argument, run the FastAPI service
if [ "$1" = "service" ]; then
  mkdir -p /app/reports
  chmod -R a+rwx /app/reports
  export PYTHONPATH="${PYTHONPATH:-/app/src}"
  exec python3 -m cloud_eval.service
fi

# Default: run as service if no arguments
mkdir -p /app/reports
chmod -R a+rwx /app/reports
export PYTHONPATH="${PYTHONPATH:-/app/src}"
exec python3 -m cloud_eval.service
