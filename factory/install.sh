#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p .claude/agents .claude/commands
cp "$SCRIPT_DIR/agents/"*.md .claude/agents/
cp "$SCRIPT_DIR/commands/"*.md .claude/commands/
for d in "$SCRIPT_DIR/skills/"*/; do
    n=$(basename "$d")
    mkdir -p ".claude/skills/$n"
    cp "$d/SKILL.md" ".claude/skills/$n/SKILL.md"
done
echo "✅ Instalado em .claude/ — verifique com: ls -la .claude/"
