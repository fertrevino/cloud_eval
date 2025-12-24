#!/usr/bin/env sh
set -e

# If the caller explicitly runs `python ...`, hand off directly (so verification scripts still work).
if [ $# -gt 0 ] && [ "$1" = "python" ]; then
  exec "$@"
fi

mkdir -p /app/reports
# Ensure bind-mounted reports directory is writable inside the container.
chmod -R a+rwx /app/reports

export PYTHONPATH="${PYTHONPATH:-/app/src}"
exec python3 -m cloud_eval.suite
