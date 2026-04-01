#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCALES_DIR="$(realpath "$SCRIPT_DIR/../locales/")"
echo "Looking for languages in: $LOCALES_DIR"

# Fetch all languages from the locales directory
LANGS=()
for dir in "$LOCALES_DIR/"*/; do
    LANGS+=("$(basename "$dir")")
done

echo -e "Found ${#LANGS[@]} languages in the locales/ directory: \n" "${LANGS[@]}"

# Update .pot
xgettext -o locales/messages.pot -k_ -kgettext -kgettext_noop --from-code=UTF-8 src/main.py

# Update .po
for lang in "${LANGS[@]}"; do
    msgmerge --update "$LOCALES_DIR/${lang}/LC_MESSAGES/messages.po" locales/messages.pot
    echo "Updated translations for language: $lang"
done
