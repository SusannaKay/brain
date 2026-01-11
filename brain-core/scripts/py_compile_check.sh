#!/usr/bin/env bash
set -euo pipefail

python3 -m py_compile \
  brain_api/app/main.py \
  brain_api/app/routers/*.py \
  brain_api/app/*.py
