#!/bin/bash
# Cross-Compile Jarvis.exe für Windows (von Linux aus)
set -e

echo "Baue Jarvis.exe für Windows (amd64)..."

CGO_ENABLED=1 \
GOOS=windows \
GOARCH=amd64 \
CC=x86_64-w64-mingw32-gcc \
CXX=x86_64-w64-mingw32-g++ \
go build -ldflags="-H windowsgui -s -w" -o Jarvis.exe .

echo "Fertig: $(ls -lh Jarvis.exe)"
