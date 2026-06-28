#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Drift-sicheres Veroeffentlichen von LANDING-PAGE-INHALTEN auf jarvis-ai.info.
#
# Anders als build.sh (lädt jarvis.exe + patcht nur den Versionsstring) fuegt
# dieses Skript NEUE Feature-Karten in das LIVE index.html ein, OHNE andere
# Live-Inhalte zu verlieren: Live laden -> Karten nach der Office-Karte
# einsetzen (idempotent) -> per SSH zurueckspielen -> verifizieren.
#
# Auth: SSH Public-Key (keyless). Override via JARVIS_SSH_HOST / JARVIS_SSH_KEY /
# JARVIS_DOCROOT. FTP/FTPS wird bewusst NICHT genutzt (FTP-ALG kapert AUTH).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

# Deploy via SSH (keyless Public-Key). FTP/FTPS ist ueber manche Netze unbrauchbar
# (FTP-ALG kapert AUTH). Ueberschreibbar via JARVIS_SSH_HOST / JARVIS_SSH_KEY / JARVIS_DOCROOT.
SSH_HOST="${JARVIS_SSH_HOST:-jarvis@jarvis-ai.info}"
SSH_KEY="${JARVIS_SSH_KEY:-$HOME/.ssh/id_rsa}"
DOCROOT="${JARVIS_DOCROOT:-/var/www/vhosts/jarvis-ai.info/www}"
SCP=(scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=20)

TMP_LIVE="$(mktemp)"
TMP_NEW="$(mktemp)"
trap 'rm -f "$TMP_LIVE" "$TMP_NEW"' EXIT

echo "1) Live index.html laden (SSH) …"
"${SCP[@]}" "$SSH_HOST:$DOCROOT/index.html" "$TMP_LIVE"

echo "2) Feature-Karten einsetzen (idempotent) …"
python3 - "$TMP_LIVE" "$TMP_NEW" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
html = open(src, encoding="utf-8").read()

CARDS = '''
            <div class="feature-card reveal">
                <div class="feature-icon">🔗</div>
                <div class="feature-title t-de">Confluence &amp; Jira</div>
                <div class="feature-title t-en">Confluence &amp; Jira</div>
                <div class="feature-desc t-de">Durchsucht Confluence-Seiten und Jira-Tickets read-only direkt im Chat – nach Relevanz sortiert, mit Quell-Links. Confluence-Seiten lassen sich zudem als Wissensquelle in die RAG-Datenbank importieren. Read-only: keine ungewollten Änderungen an deinen Systemen.</div>
                <div class="feature-desc t-en">Searches Confluence pages and Jira tickets read-only directly in the chat – ranked by relevance, with source links. Confluence pages can also be imported into the RAG knowledge base. Read-only: no unintended changes to your systems.</div>
            </div>
            <div class="feature-card reveal">
                <div class="feature-icon">🎧</div>
                <div class="feature-title t-de">Support-Portal &amp; -Assistent</div>
                <div class="feature-title t-en">Support Portal &amp; Assistant</div>
                <div class="feature-desc t-de">Eigene Support-Oberfläche (/support &amp; /portal): durchsucht Wissensdatenbank, Jira und Confluence gleichzeitig, sortiert nach Relevanz (%) und fasst per LLM zusammen – mit Quell-Links zum Original. Auch als externe Support-API (API-Key) für andere Anwendungen.</div>
                <div class="feature-desc t-en">A dedicated support interface (/support &amp; /portal): searches the knowledge base, Jira and Confluence simultaneously, ranked by relevance (%) and summarized by the LLM – with source links to the original. Also available as an external support API (API key) for other applications.</div>
            </div>
            <div class="feature-card reveal">
                <div class="feature-icon">📦</div>
                <div class="feature-title t-de">Wissens-Export (JSON)</div>
                <div class="feature-title t-en">Knowledge Export (JSON)</div>
                <div class="feature-desc t-de">Exportiere die komplette Wissensbasis als strukturiertes JSON (title/summary/facts/qa_pairs/content) – als eine Datei oder je eine JSON pro Dokument (ZIP). Optional per LLM angereichert oder inkl. Roh-Vektoren. So lässt sich dein Wissen in Fremdsysteme übernehmen.</div>
                <div class="feature-desc t-en">Export the entire knowledge base as structured JSON (title/summary/facts/qa_pairs/content) – as a single file or one JSON per document (ZIP). Optionally LLM-enriched or including raw vectors. Take your knowledge into other systems.</div>
            </div>'''

if "Support-Portal &amp; -Assistent" in html or "Knowledge Export (JSON)" in html:
    print("   -> Karten bereits vorhanden, nichts zu tun.")
    open(dst, "w", encoding="utf-8").write(html)
    sys.exit(0)

# Anker: Ende der Office-Karte (engl. Beschreibung), danach folgt das schliessende </div> der Karte.
anchor = "not just a path.</div>"
i = html.find(anchor)
if i < 0:
    sys.stderr.write("FEHLER: Office-Karte (Anker) im Live-HTML nicht gefunden – Abbruch.\n")
    sys.exit(2)
# Naechstes </div> nach dem Anker schliesst die Karte; danach einfuegen.
close = html.find("</div>", i + len(anchor))
if close < 0:
    sys.stderr.write("FEHLER: Karten-Abschluss nicht gefunden – Abbruch.\n")
    sys.exit(3)
ins = close + len("</div>")
new = html[:ins] + CARDS + html[ins:]
open(dst, "w", encoding="utf-8").write(new)
print("   -> 3 Karten eingefuegt.")
PY

# Wenn keine Aenderung noetig war (idempotent), trotzdem nichts hochladen-Schaden:
if cmp -s "$TMP_LIVE" "$TMP_NEW"; then
  echo "   Keine Aenderung – Upload uebersprungen."
  exit 0
fi

echo "3) index.html per SSH hochladen …"
"${SCP[@]}" "$TMP_NEW" "$SSH_HOST:$DOCROOT/index.html"

echo "4) Verifizieren (HTTPS) …"
if curl -fsS --insecure "https://jarvis-ai.info/?t=$(date +%s)" | grep -q "Knowledge Export (JSON)"; then
  echo "   ✓ Veroeffentlicht – neue Karten sind live."
else
  echo "   ⚠ Upload erfolgt, aber Verifikation fand die Karten (noch) nicht (Cache?)." >&2
fi
