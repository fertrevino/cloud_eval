#!/usr/bin/env sh
set -e

# If the caller explicitly runs `python ...`, hand off directly (so verification scripts still work).
if [ $# -gt 0 ] && [ "$1" = "python" ]; then
  exec "$@"
fi

exec python3 -m cloud_eval.suite
