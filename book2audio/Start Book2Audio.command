#!/bin/sh
# Double-click this file to start Book2Audio. Closing this window stops it.
if command -v book2audio >/dev/null 2>&1; then
  book2audio ui "$@"
elif python3 -c "import book2audio" >/dev/null 2>&1; then
  python3 -m book2audio ui "$@"
else
  echo
  echo "Book2Audio is not installed yet."
  echo "Open README.md in this folder and follow the Install steps, then double-click this file again."
  printf "Press Return to close this window. "
  read -r _
fi
