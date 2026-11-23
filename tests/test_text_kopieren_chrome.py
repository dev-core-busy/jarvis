#!/usr/bin/env python3
"""Waechter: "Text kopieren" steht nur im Menue, wenn der Zeiger AUF Text steht (2026-11-23).

DER FEHLER, DEN DAS VERHINDERT: das Kontextmenue einer Sprechblase bot
"Text kopieren" bei jedem Rechtsklick in der Zeile an – auf dem Rand der
Blase, im Leerraum neben der letzten Zeile, auf dem Zeitstempel. Dort ist
nicht eindeutig, WELCHER Text gemeint ist (Meldung des Betreibers). Seitdem
fragt `chatlib.textUnterPunkt(ev)`, ob unter dem Zeiger ein Zeichen liegt,
und /chat (`_buildBubbleCtxItems`) und /userchat (`_buildDmCtxItems`) nehmen
den Eintrag nur auf, wenn dieses Zeichen IN der Sprechblase steht.

Gemessen im ECHTEN Chrome, weil jsdom kein Layout rechnet und
`caretRangeFromPoint` dort nicht existiert. Die Probeseite laedt das echte
chatlib.js und icons.js und die beiden Menue-Funktionen, aus chat.js bzw.
userchat.js geschnitten. Klickpunkte:

* mitten auf einem Zeichen                 -> Eintrag da (Positivkontrolle)
* Innenabstand der Blase                    -> kein Eintrag
* Leerraum rechts neben dem kurzen Text     -> kein Eintrag
* Zeitstempel (Text, aber NICHT die Blase)  -> kein Eintrag
* Long-Press (touchstart-artiges Ereignis)  -> gleiche Regel ueber touches[0]

"Chat als PDF" und "Löschen" stehen in JEDEM Fall im Menue – sonst waere ein
leeres Menue auch "ohne Text kopieren".

CHATLIB_JS / CHAT_JS / USERCHAT_JS legen sabotierte KOPIEN vor (Gegenprobe).
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_text_kopieren_chrome.py
"""
import html as htmlmod
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "frontend" / "js"

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def abbruch(text):
    print(f"ABBRUCH: {text}")
    sys.exit(2)


def lesen(env, standard):
    p = Path(os.environ.get(env) or standard)
    try:
        return p.read_text(encoding="utf-8")
    except OSError as e:
        abbruch(f"{p} nicht lesbar: {e}")


def schneide(src, name):
    """Funktion `name` samt Rumpf ueber Klammerzaehlung. Leer, wenn nicht gefunden."""
    m = re.search(r"function " + re.escape(name) + r"\s*\(", src)
    if not m:
        return ""
    i = src.find("{", m.end())
    if i < 0:
        return ""
    tiefe = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            tiefe += 1
        elif src[j] == "}":
            tiefe -= 1
            if tiefe == 0:
                return src[m.start():j + 1]
    return ""


CHROME = next((p for p in map(shutil.which, ("google-chrome", "chromium", "chromium-browser")) if p), None)
if not CHROME:
    abbruch("kein Chrome/Chromium gefunden (gesucht: google-chrome, chromium, chromium-browser)")

CHATLIB = lesen("CHATLIB_JS", JS / "chatlib.js")
ICONS = lesen("ICONS_JS", JS / "icons.js")
CHAT = lesen("CHAT_JS", JS / "chat.js")
USERCHAT = lesen("USERCHAT_JS", JS / "userchat.js")

teile_chat = [schneide(CHAT, n) for n in ("_ctxPdfItem", "_buildBubbleCtxItems")]
teil_uc = schneide(USERCHAT, "_buildDmCtxItems")
if not all(teile_chat) or not teil_uc:
    abbruch("Menue-Funktionen in chat.js/userchat.js nicht gefunden – Schnitt blind")

# Die Funktionen laufen im Seiten-Scope; was sie aus ihrem Modul brauchen,
# stellt der Prolog (Register: ein fehlender Name stirbt als ReferenceError).
PROLOG = """
var _selCtl = { startSelectionDelete: function(){} };
var _sessions = [], _activeSid = null, _currentUser = '';
function _editUserBubble(){} function _exportChatPdf(){}
function _isMe(){ return true; } function _editDmBubble(){}
var messagesEl = document.getElementById('messages');
"""

SEITE = r"""<!doctype html><html><head><meta charset="utf-8">
<style>
 body { margin: 0; font: 16px/1.4 sans-serif; }
 .msg-row { display: flex; width: 900px; padding: 10px; }
 .msg-bubble { padding: 30px; width: 500px; background: #ddd; }
</style></head><body>
<div id="messages">
 <div class="msg-row user" id="row"><div>
  <div class="msg-time"><span id="zeit">10:00 Uhr Zeitstempel</span></div>
  <div class="msg-bubble" id="blase">Kurzer Text</div>
 </div></div>
</div>
<script>__ICONS__</script>
<script>__CHATLIB__</script>
<script>__PROLOG__
__TEILE__</script>
<script>
(function () {
  var aus = { fehler: null, punkte: {} };
  try {
    var lib = window.JarvisChatLib;
    var row = document.getElementById('row'), blase = document.getElementById('blase');
    var zeit = document.getElementById('zeit');
    var text = blase.firstChild;
    var r = document.createRange(); r.setStart(text, 1); r.setEnd(text, 2);
    var z = r.getBoundingClientRect();            // das Zeichen "u"
    var b = blase.getBoundingClientRect();
    var t = document.createRange(); t.selectNodeContents(text);
    var tr = t.getBoundingClientRect();
    var zr = zeit.getBoundingClientRect();
    var punkte = {
      zeichen:     [z.left + z.width / 2, z.top + z.height / 2],
      innenrand:   [b.left + 8, b.top + 8],
      leerraum:    [Math.min(tr.right + 60, b.right - 40), tr.top + tr.height / 2],
      zeitstempel: [zr.left + 5, zr.top + zr.height / 2],
    };
    var msg = { from: 'ich', text: blase.textContent, msg_id: 'm1' };
    Object.keys(punkte).forEach(function (k) {
      var x = punkte[k][0], y = punkte[k][1];
      var ev = { clientX: x, clientY: y, target: document.elementFromPoint(x, y) };
      var lang = { touches: [{ clientX: x, clientY: y, target: ev.target }], target: ev.target };
      var lbl = function (items) { return (items || []).map(function (i) { return i.label; }); };
      aus.punkte[k] = {
        knoten: !!lib.textUnterPunkt(ev),
        chat: lbl(_buildBubbleCtxItems(row, blase, 'user', ev)),
        chatBot: lbl(_buildBubbleCtxItems(row, blase, 'bot', ev)),
        userchat: lbl(_buildDmCtxItems(row, blase, msg, ev)),
        langChat: lbl(_buildBubbleCtxItems(row, blase, 'user', lang)),
      };
    });
  } catch (e) { aus.fehler = String(e && e.stack || e); }
  document.title = 'TK' + JSON.stringify(aus);
})();
</script></body></html>"""


def einsetzen(seite, marke, js):
    # </script> im Quelltext wuerde den Block beenden – absichern.
    return seite.replace(marke, js.replace("</script", "<\\/script"))


seite = SEITE
seite = einsetzen(seite, "__ICONS__", ICONS)
seite = einsetzen(seite, "__CHATLIB__", CHATLIB)
seite = einsetzen(seite, "__PROLOG__", PROLOG)
seite = einsetzen(seite, "__TEILE__", "\n".join(teile_chat + [teil_uc]))

with tempfile.TemporaryDirectory(dir=str(Path.home()), prefix=".text-kopieren-",
                                 ignore_cleanup_errors=True) as tmp:
    probe = Path(tmp) / "probe.html"
    probe.write_text(seite, encoding="utf-8")
    profil = tempfile.mkdtemp(dir=tmp, prefix="profil_")
    try:
        r = subprocess.run(
            [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
             f"--user-data-dir={profil}", "--window-size=1200,800", "--dump-dom", probe.as_uri()],
            capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as e:
        abbruch(f"Chrome lief nicht ({type(e).__name__}: {e})")
    m = re.search(r"<title>TK(.*?)</title>", r.stdout, flags=re.S)
    if not m:
        abbruch(f"Chrome lieferte keine Messwerte (Exit {r.returncode})")
    try:
        w = json.loads(htmlmod.unescape(m.group(1)))
    except ValueError as e:
        abbruch(f"Messwerte nicht lesbar ({e})")

if w.get("fehler"):
    abbruch(f"Probeseite warf: {w['fehler'][:400]}")
P = w.get("punkte") or {}
if set(P) != {"zeichen", "innenrand", "leerraum", "zeitstempel"}:
    abbruch(f"Messpunkte unvollstaendig: {sorted(P)}")

KOPIE, PDF, LOESCHEN = "Text kopieren", "Chat als PDF", "Löschen"

# Positivkontrolle der Messmethode: auf dem Zeichen MUSS ein Knoten kommen,
# sonst sind alle "kein Eintrag"-Pruefungen trivial wahr.
if not P["zeichen"]["knoten"]:
    abbruch("auf einem Zeichen liefert textUnterPunkt nichts – Messung blind")

print("\nAuf einem Zeichen")
for k in ("chat", "chatBot", "userchat", "langChat"):
    check(KOPIE in P["zeichen"][k], f"{k}: 'Text kopieren' steht im Menue", P["zeichen"][k])

for ort, titel in (("innenrand", "Innenabstand der Blase"),
                   ("leerraum", "Leerraum neben dem Text"),
                   ("zeitstempel", "Zeitstempel (Text ausserhalb der Blase)")):
    print(f"\n{titel}")
    if ort != "zeitstempel":
        check(not P[ort]["knoten"], "textUnterPunkt meldet keinen Text")
    for k in ("chat", "chatBot", "userchat", "langChat"):
        check(KOPIE not in P[ort][k], f"{k}: kein 'Text kopieren'", P[ort][k])

print("\nUebrige Eintraege bleiben")
for ort in P:
    for k in ("chat", "chatBot", "langChat"):
        check(PDF in P[ort][k] and P[ort][k][-1] == LOESCHEN,
              f"{ort}/{k}: 'Chat als PDF' da, 'Löschen' zuletzt", P[ort][k])

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
