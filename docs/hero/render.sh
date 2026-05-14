#!/usr/bin/env bash
# Records the interactive demo and renders it to demo.svg.
# Run from anywhere -- the script cd's into its own directory first.
#
# Prerequisites (one-time):
#   sudo apt install expect asciinema    # or: brew install expect asciinema
#   sudo npm install -g svg-term-cli
#   chmod +x render.sh record.exp

set -euo pipefail

cd "$(dirname "$0")"

# Pin the recorded PTY size so the SVG dimensions don't depend on the host
# terminal. Width must comfortably exceed octowrap's --line-length (88) plus
# diff prefixes; bump if the demo ever wraps awkwardly.
cols=90
rows=38

asciinema rec --overwrite --cols "$cols" --rows "$rows" \
    --command ./record.exp demo.cast
svg-term --in demo.cast --out demo.svg --window --padding 16
# svg-term-cli omits the trailing newline; append one so pre-commit's
# end-of-file-fixer leaves the file alone on subsequent runs.
printf '\n' >> demo.svg

echo "Wrote $(pwd)/demo.svg"
