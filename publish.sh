#!/bin/bash
set -e

# Bump version (patch by default, or pass "minor"/"major" as argument)
BUMP=${1:-patch}
CURRENT=$(grep -oP 'version = "\K[^"]+' pyproject.toml)
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$BUMP" in
  patch) PATCH=$((PATCH + 1)) ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  *) echo "Usage: ./publish.sh [patch|minor|major]"; exit 1 ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"
sed -i "s/version = \"$CURRENT\"/version = \"$NEW_VERSION\"/" pyproject.toml
echo "Version: $CURRENT -> $NEW_VERSION"

# Clean, build, publish
rm -rf dist
python -m hatch build
python -m hatch publish

# Clear uv cache so Claude Code picks up the new version
uv cache clean computer-control-mcp-enhanced

echo ""
echo "Published $NEW_VERSION"
echo "Restart Claude Code to pick up the new version."
