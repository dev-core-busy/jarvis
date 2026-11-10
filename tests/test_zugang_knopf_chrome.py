#!/usr/bin/env python3
"""Waechter: wirkt ``hidden`` an den Knoepfen von /sap und /vemas? (2026-11-10)

DER FEHLER, DEN DAS VERHINDERT: ``.sp-hist-btn`` / ``.vm-hist-btn`` setzen
``display: flex`` und ueberstimmen damit das ``hidden``-Attribut. "Von SAP
abmelden" trug ``hidden`` im Markup und stand trotzdem da – in Chrome gemessen,
berechnet ``display: flex``. Ein Knopf, den das Skript per ``.hidden`` verbirgt,
waere genauso sichtbar geblieben; der Verhaltens-Waechter
(test_zugang_entfernen_ui.js) kann das nicht sehen, weil jsdom die Kaskade
nicht rechnet.

Gemessen wird im ECHTEN Chrome an der ECHTEN Seite (Markup + Inline-CSS, die
Skripte sind entfernt – sie wuerden ohne Sitzung umleiten):

* Kein Element, das im Markup ``hidden`` traegt, ist sichtbar.
* "Eigenen Zugang entfernen" und "Abmelden": verborgen -> ``display: none``,
  eingeblendet -> sichtbar.

GELTUNGSBEREICH, bewusst eng: die Elemente mit ``hidden`` im Markup und die
beiden Knoepfe. Andere Klassen dieser Seiten ueberstimmen ``hidden`` ebenfalls
(gemessen u. a. ``.sp-field``, ``.sp-actions``, ``.sp-note``) – sie werden
heute nirgends per ``hidden`` verborgen und sind deshalb kein Befund.

ZUGANG_SAP_HTML / ZUGANG_VEMAS_HTML legen sabotierte KOPIEN vor (Gegenprobe
tests/gegen_zugang_entfernen.py).
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen (kein Chrome, keine
Messwerte, Messmethode blind).

    python3 tests/test_zugang_knopf_chrome.py
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


CHROME = next((p for p in map(shutil.which, ("google-chrome", "chromium", "chromium-browser")) if p), None)
if not CHROME:
    abbruch("kein Chrome/Chromium gefunden (gesucht: google-chrome, chromium, chromium-browser)")

SEITEN = [
    ("/sap", Path(os.environ.get("ZUGANG_SAP_HTML") or ROOT / "frontend" / "sap.html"), "sp"),
    ("/vemas", Path(os.environ.get("ZUGANG_VEMAS_HTML") or ROOT / "frontend" / "vemas.html"), "vm"),
]

# Laeuft in der Seite. Zwei Kontrollen der Messmethode stehen mit im Markup:
# ein per Inline-Style erzwungen sichtbares Element MIT hidden (die Sonde muss
# es als sichtbar melden) und ein gewoehnliches verborgenes (als verborgen).
SONDE = r"""
<div id="zk-sichtbar" hidden style="display:flex">x</div>
<div id="zk-verborgen" hidden>x</div>
<script>
(function () {
    function d(e) { return getComputedStyle(e).display; }
    var aus = { kontrolle: {}, markup: [], knoepfe: {} };
    aus.kontrolle.sichtbar = d(document.getElementById('zk-sichtbar'));
    aus.kontrolle.verborgen = d(document.getElementById('zk-verborgen'));
    document.querySelectorAll('[hidden]').forEach(function (e) {
        if (e.id === 'zk-sichtbar' || e.id === 'zk-verborgen') return;
        aus.markup.push({ wer: e.id || e.className || e.tagName, display: d(e) });
    });
    __IDS__.forEach(function (id) {
        var e = document.getElementById(id);
        if (!e) { aus.knoepfe[id] = null; return; }
        var vor = e.hidden;
        e.hidden = true;  var zu = d(e);
        e.hidden = false; var auf = d(e);
        e.hidden = vor;
        aus.knoepfe[id] = { klasse: e.className, markupHidden: vor, zu: zu, auf: auf };
    });
    document.title = 'ZK' + JSON.stringify(aus);
})();
</script>
"""


def messen(quelle: Path, ids: list, tmp: Path) -> dict:
    try:
        text = quelle.read_text(encoding="utf-8")
    except OSError as e:
        abbruch(f"{quelle} nicht lesbar: {e}")
    ohne, n = re.subn(r"<script\b.*?</script>", "", text, flags=re.S | re.I)
    teile = ohne.rsplit("</body>", 1)
    if n == 0 or len(teile) != 2:
        abbruch(f"{quelle.name}: Seite nicht wie erwartet aufgebaut (Skripte {n}, </body> fehlt?)")
    probe = tmp / f"probe_{quelle.name}"
    probe.write_text(teile[0] + SONDE.replace("__IDS__", json.dumps(ids)) + "</body>" + teile[1],
                     encoding="utf-8")
    profil = tempfile.mkdtemp(dir=str(tmp), prefix="profil_")
    try:
        r = subprocess.run(
            [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
             f"--user-data-dir={profil}", "--dump-dom", probe.as_uri()],
            capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as e:
        abbruch(f"Chrome lief nicht ({type(e).__name__}: {e})")
    m = re.search(r"<title>ZK(.*?)</title>", r.stdout, flags=re.S)
    if not m:
        abbruch(f"{quelle.name}: Chrome lieferte keine Messwerte (Exit {r.returncode})")
    try:
        return json.loads(htmlmod.unescape(m.group(1)))
    except ValueError as e:
        abbruch(f"{quelle.name}: Messwerte nicht lesbar ({e})")


# Ablage im HOME, nicht in /tmp: ein Snap-Chromium liest dort nicht, und ein
# fester /tmp-Name stirbt am Tag nach einem Lauf unter fremdem Benutzer.
with tempfile.TemporaryDirectory(dir=str(Path.home()), prefix=".zugang-knopf-",
                                 ignore_cleanup_errors=True) as _tmp:
    for titel, quelle, pre in SEITEN:
        print(f"\n{titel}")
        knoepfe = [f"{pre}-acc-del", f"{pre}-acc-logout"]
        w = messen(quelle, knoepfe, Path(_tmp))

        # Positivkontrolle der Messmethode – sonst waere alles darunter trivial.
        k = w.get("kontrolle", {})
        if k.get("sichtbar") != "flex" or k.get("verborgen") != "none":
            abbruch(f"{titel}: die Sonde unterscheidet sichtbar/verborgen nicht ({k})")
        if not w.get("markup"):
            abbruch(f"{titel}: kein Element mit hidden im Markup gefunden – die Regel waere leer")
        if any(w["knoepfe"].get(i) is None for i in knoepfe):
            abbruch(f"{titel}: Knopf fehlt im Markup ({w['knoepfe']})")

        sichtbar = [f"{e['wer']}:{e['display']}" for e in w["markup"] if e["display"] != "none"]
        check(not sichtbar, f"kein Element mit hidden im Markup ist sichtbar ({len(w['markup'])} geprueft)",
              ", ".join(sichtbar))
        for i in knoepfe:
            b = w["knoepfe"][i]
            check(b["zu"] == "none", f"{i}: verborgen heisst display:none", f"{b['zu']} (Klasse {b['klasse']})")
            check(b["auf"] != "none", f"{i}: eingeblendet ist er sichtbar", b["auf"])
        check(w["knoepfe"][f"{pre}-acc-del"]["markupHidden"] is True,
              f"{pre}-acc-del ist im Markup verborgen vorbelegt")

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
