#!/bin/bash
# Protokolliert, WELCHE Instruktionsdatei WANN und WARUM in den Kontext geladen wurde.
# Zweck: ein `paths:`-Glob in .claude/rules/, das nicht mehr trifft, laesst Wissen
# STILL ausfallen. Dieses Log macht daraus eine Messung statt einer Annahme.
# Exit-Code wird von Claude Code ignoriert (reines Benachrichtigungs-Ereignis).
set -u
LOG="${CLAUDE_PROJECT_DIR:-.}/.claude/instructions-loaded.log"
eingabe=$(cat)
datei=$(printf '%s' "$eingabe" | jq -r '.file_path // "?"')
grund=$(printf '%s' "$eingabe" | jq -r '.load_reason // "?"')
groesse=$(printf '%s' "$eingabe" | jq -r '.file_content // "" | length')
printf '%s  %-18s %7s Z  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$grund" "$groesse" "$datei" >> "$LOG"
exit 0
