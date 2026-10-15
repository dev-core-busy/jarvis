#!/usr/bin/env bash
# jsdom fuer die UI-Testsuiten bereitstellen (Entwicklungsmaschine).
#
# WARUM ES DAS GIBT: die 31 UI-Suiten laden jsdom ueber
# `require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom')`. `/tmp` wird
# beim Neustart geleert – danach brechen ALLE mit MODULE_NOT_FOUND ab. Das ist
# der teuerste Zustand, den ein Waechter haben kann: er meldet keinen Fehler,
# er meldet gar nichts. Genau so blieb der veraltete Theme-Waechter im
# Excel-Add-in nach der Umstellung auf das helle Vorgabe-Thema (2026-08-25)
# wochenlang unbemerkt.
#
# Deshalb liegt jsdom im REPO (`node_modules/`, gitignored) und `/tmp` bekommt
# nur einen Verweis darauf.
#
# ⚠ VERSION IST GEBUNDEN: jsdom ab 26 verlangt Node >= 22. Auf Node 20 laedt es
# zwar, wirft aber beim ersten `new JSDOM(...)`
# "webidl.util.markAsUncloneable is not a function" – ein Fehler, der wie ein
# Testfehler aussieht und keiner ist.
#
# Lauf:  bash tests/tools/jsdom_bereitstellen.sh
set -euo pipefail
WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$WURZEL"

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
PAKET="jsdom@25"
[ "$NODE_MAJOR" -ge 22 ] && PAKET="jsdom"

if [ ! -d node_modules/jsdom ]; then
    echo "Installiere $PAKET nach $WURZEL/node_modules ..."
    npm install --no-save --no-audit --no-fund "$PAKET"
fi

mkdir -p /tmp/node_modules
ln -sfn "$WURZEL/node_modules/jsdom" /tmp/node_modules/jsdom

# Nachpruefen statt behaupten: `require` allein beweist nichts, der Fehler oben
# faellt erst beim Bauen eines Fensters auf.
node -e "
const { JSDOM } = require('/tmp/node_modules/jsdom');
const d = new JSDOM('<p id=x>ok</p>');
if (d.window.document.getElementById('x').textContent !== 'ok') process.exit(1);
console.log('jsdom ' + require('/tmp/node_modules/jsdom/package.json').version + ' einsatzbereit (Node ' + process.versions.node + ')');
"
