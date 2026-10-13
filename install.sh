#!/bin/bash

# For a checkout you want to work from: link it in as the plugin, then hand
# over to `nightlight setup`, which is where anything that actually changes
# your desktop gets disclosed and agreed to. Placing files here starts nothing
# and schedules nothing.
#
#   ./install.sh              place files, then run setup interactively
#   ./install.sh --no-bar     do not add the bar widget to shell.json
#   ./install.sh --yes        accept setup's changes without prompting
#   ./install.sh --place-only place files and stop; run setup yourself later

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ID="sviat.nightlight"
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"

add_bar="true"
place_only="false"
assume_yes=""

while (( $# > 0 )); do
  case "$1" in
  --no-bar) add_bar="false" ;;
  --place-only) place_only="true" ;;
  --yes | -y) assume_yes="--yes" ;;
  -h | --help)
    sed -n '3,11p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
    exit 0
    ;;
  *)
    echo "install.sh: unknown option: $1" >&2
    exit 1
    ;;
  esac
  shift
done

echo "Placing files from $REPO"

if [[ -e $PLUGIN_DIR && ! -L $PLUGIN_DIR ]]; then
  echo "  plugin   $PLUGIN_DIR already exists and is not a symlink, leaving it"
else
  mkdir -p "$(dirname "$PLUGIN_DIR")"
  ln -sfn "$REPO" "$PLUGIN_DIR"
  echo "  plugin   $PLUGIN_DIR"
fi

# The bar widget. This is the one edit to shell.json, and it only places an
# icon -- the schedule is not touched here.
if [[ $add_bar == "true" ]]; then
  if grep -q "$PLUGIN_ID" "$HOME/.config/omarchy/shell.json" 2>/dev/null; then
    echo "  bar      already placed"
  else
    omarchy bar put "$PLUGIN_ID" --section center
    echo "  bar      widget added to the centre section"
  fi
fi

echo
if [[ $place_only == "true" ]]; then
  echo "Nothing is running yet. When you are ready:"
  echo "  $REPO/bin/nightlight setup"
  exit 0
fi

# Everything with an effect on the desktop lives behind this, which prints what
# it would change and waits for you to agree.
exec "$REPO/bin/nightlight" setup $assume_yes
