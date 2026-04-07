#!/bin/bash
# Cross-Compile jarvis.exe für Windows (von Linux aus)
set -e

# Buildnummer aus buildnum.txt lesen und inkrementieren
NUMFILE="$(dirname "$0")/buildnum.txt"
NUM=$(cat "$NUMFILE" 2>/dev/null || echo "800")
NUM=$((NUM + 1))
echo "$NUM" > "$NUMFILE"
VERSION="0.$(printf '%03d' "$NUM")"
echo "Build $VERSION..."

CGO_ENABLED=1 \
GOOS=windows \
GOARCH=amd64 \
CC=x86_64-w64-mingw32-gcc \
CXX=x86_64-w64-mingw32-g++ \
go build -ldflags="-H windowsgui -s -w -X main.AppVersion=$VERSION" -o jarvis.exe .

echo "Fertig: $(ls -lh jarvis.exe)  [Build $VERSION]"
