#!/bin/bash
# ── Machbarkeitsprobe "Claude Subagent" ──────────────────────────────────────
# Legt den Arbeitsbereich an. Treu zum Zielentwurf:
#   * Wegwerf-Klon unter /tmp  -> der Lauf kann UNPRIVILEGIERT arbeiten
#     (sandbox.py: /tmp ist Lese- UND Schreibwurzel fuer Domain-Benutzer)
#   * Basis = origin/master    -> NICHT /opt/jarvis, dessen git-HEAD ist alt
#     und die Arbeitskopie driftet per scp (CLAUDE.md)
#
# PROBE-ABKUERZUNG: die Rechte werden hier grob auf a+rwX gesetzt, damit sowohl
# das filesystem-Werkzeug (laeuft als 'jarvis') als auch shell_execute (laeuft
# als 'jarvis_sandbox') arbeiten koennen. Im Zielentwurf legt der Endpunkt den
# Klon als Dienstbenutzer an - hier ist es Wegwerf-Material in tmpfs.
set -u

BASE=/tmp/csprobe
WORK="$BASE/work"

rm -rf "$BASE"
mkdir -p "$BASE"

echo "=== Klon anlegen (flach, origin/master) ==="
if ! git clone --depth 1 https://github.com/dev-core-busy/jarvis.git "$WORK" 2>&1 | tail -3; then
    echo "FEHLER: clone gescheitert"
    exit 1
fi

chmod -R a+rwX "$BASE"

echo
echo "=== Arbeitsbereich ==="
echo "Pfad:      $WORK"
echo "HEAD:      $(git -C "$WORK" rev-parse --short HEAD)"
echo "Dateien:   $(find "$WORK" -type f -not -path '*/.git/*' | wc -l)"
echo "Groesse:   $(du -sh --exclude=.git "$WORK" | cut -f1)"
echo "tests/:    $(ls "$WORK/tests" 2>/dev/null | wc -l) Dateien"
echo
echo "=== Basislauf der beiden Waechter (Sollwerte fuer die Probe) ==="
cd "$WORK" || exit 1
export PYTHONDONTWRITEBYTECODE=1
echo -n "test_branding_aliase.py : "
python3 tests/test_branding_aliase.py 2>&1 | grep -oE '[0-9]+ OK, [0-9]+ FAIL' | tail -1
echo -n "test_icon_semantik.js   : "
node tests/test_icon_semantik.js 2>&1 | grep -oE 'Ergebnis: [0-9]+/[0-9]+' | tail -1
