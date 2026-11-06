#!/bin/sh
# Resolve this physical root and use only its bundled Python.
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || exit 1
exec "$ROOT/runtime/python/bin/python3" -I -B "$ROOT/.studio/windows_runtime.py" "$@"
