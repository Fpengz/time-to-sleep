#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Time-to-Sleep Usage
# @raycast.mode inline
# @raycast.refreshTime 1m

# Optional parameters:
# @raycast.icon 🌙
# @raycast.packageName AI Assistant Usage Monitor

# Documentation:
# @raycast.description Glance at your current Claude, Codex, and Antigravity usage quotas
# @raycast.author Antigravity Team

if command -v time-to-sleep &> /dev/null; then
    time-to-sleep prompt --format=compact
elif [ -f "$HOME/.local/bin/time-to-sleep" ]; then
    "$HOME/.local/bin/time-to-sleep" prompt --format=compact
else
    # Fallback to local API endpoint
    curl -s http://127.0.0.1:4141/v1/usage | python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
    parts = []
    for acc in data.get("accounts", []):
        prov = acc.get("provider", "")[:3].upper()
        wins = acc.get("windows", [])
        pct = int(round(max([w.get("used_percent", 0) for w in wins], default=0)))
        parts.append(f"{prov}:{pct}%")
    print("[" + " | ".join(parts) + "]")
except Exception:
    print("[Time-to-Sleep: Offline]")
'
fi
