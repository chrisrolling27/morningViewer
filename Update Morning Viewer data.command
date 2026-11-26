#!/bin/bash
# Morning Viewer: double-click in Finder to download the map's data on this Mac's own internet connection.
# It only runs scripts/fetch_data.py from this folder (safe to run again: it skips what it already has).
cd "$(dirname "$0")" || exit 1
python3 scripts/fetch_data.py
echo
echo "Finished. You can close this window."
