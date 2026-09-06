#!/usr/bin/env bash
# Rebuild every chosen moment once, to check each against the record, and
# leave one transcript per SESSION (its longest moment) for the watcher pass.
set -u
cd "$(dirname "$0")"
# The moment's hash goes FIRST: the watcher keys its state on the first 16
# characters of the session id, so ids that share a prefix share state.
for m in wedge_bare_ep2_9 wedge_dk_ep1_16 healthy_dk_ep1_11 healthy_dk_ep2_6 wedge_dk_ep1_10 wedge_bare_ep2_7 wedge_bare_ep2_8 wedge_dk_ep1_11 wedge_dk_ep1_13 wedge_dk_ep1_15; do
  sid="$(printf '%08x' $(echo -n "$m" | cksum | cut -d' ' -f1))-0000-4000-8000-bbbbbbbbbbbb"
  echo "=== $m ($sid)"
  timeout 1200 python3 build.py "$m" "$sid" 2>&1 | grep -vE "^  skip"
done
