#!/usr/bin/env bash
# Rebuild every chosen moment once, to check each against the record, and
# leave one transcript per SESSION (its longest moment) for the watcher pass.
set -u
cd "$(dirname "$0")"
for m in wedge_dk_ep1_16 healthy_dk_ep1_11 healthy_dk_ep2_6 wedge_dk_ep1_10 wedge_bare_ep2_7 wedge_bare_ep2_8 wedge_dk_ep1_11 wedge_dk_ep1_13 wedge_dk_ep1_15; do
  sid="bbbbbbbb-0000-4000-8000-$(printf '%012x' $(echo -n "$m" | cksum | cut -d' ' -f1))"
  echo "=== $m ($sid)"
  timeout 1200 python3 build.py "$m" "$sid" 2>&1 | grep -vE "^  skip"
done
