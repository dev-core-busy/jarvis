#!/usr/bin/env python3
"""Gegenproben: Reihenfolge der AI-Maus-Fragen per Ziehen.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter beisst.
Eine Probe, die nicht beisst, ist ein Testmangel – kein Beweis.

⚠ SICHERUNG AUF PLATTE: wird dieser Lauf abgeschossen, bliebe der Arbeitsbaum
sabotiert zurueck und der naechste Testlauf meldete Fehler, die der Code nicht
hat. Ein Rueckstand wird beim naechsten Start selbst zurueckgenommen, nach dem
Wiederherstellen auf BYTE-Gleichheit geprueft.

⚠ GEMESSEN WIRD EXIT-CODE UND BILANZZEILE, nicht die Zahl der FAIL-Zeilen: ein
Waechter, der abbricht, liefert 0 FAIL und sieht wie ein bestandener aus.
"""
import atexit
import hashlib
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_ai_mouse.py"
ABLAGE = Path.home() / ".gegen-am-reihenfolge"

ZIELE = {
    "fragen": ROOT / "backend" / "ai_mouse_fragen.py",
    "main": ROOT / "backend" / "main.py",
    "js": ROOT / "frontend" / "js" / "ai_mouse.js",
    "html": ROOT / "frontend" / "ai_mouse.html",
    "css": ROOT / "frontend" / "css" / "jira_addon.css",
    "i18n": ROOT / "frontend" / "js" / "i18n.js",
    # ⚠ MIT SICHERN, obwohl keine Probe sie anfasst: der GEPRUEFTE Lauf
    # schreibt `Vorgaben.cs` (er ruft `paket_bauen`) und stellt sie selbst
    # wieder her – wird er mitten darin abgeschossen, bleibt sie verbogen.
    "vorgaben": (ROOT / "ai-mouse" / "src" / "AiMouse" / "Configuration"
                 / "Vorgaben.cs"),
}


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


ABLAGE.mkdir(mode=0o700, exist_ok=True)
SOLL = {}
for name, ziel in ZIELE.items():
    sich = ABLAGE / (name + ".bak")
    if sich.exists():
        if md5(sich) != md5(ziel):
            print("⚠ Rueckstand von %s gefunden – stelle her." % name)
            shutil.copy2(sich, ziel)
        sich.unlink()
    shutil.copy2(ziel, sich)
    SOLL[name] = md5(ziel)


def zurueck(*_a):
    for name, ziel in ZIELE.items():
        sich = ABLAGE / (name + ".bak")
        if sich.exists():
            shutil.copy2(sich, ziel)
            if md5(ziel) != SOLL[name]:
                print("⚠⚠ %s NICHT BYTE-GLEICH wiederhergestellt!" % name)
            sich.unlink()


atexit.register(zurueck)
signal.signal(signal.SIGTERM, lambda *a: (zurueck(), sys.exit(2)))

ORIG = {n: z.read_text(encoding="utf-8") for n, z in ZIELE.items()}


def lauf():
    p = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                       text=True, timeout=540)
    bilanz = ""
    for z in reversed((p.stdout or "").splitlines()):
        if " OK, " in z and "FAIL" in z:
            bilanz = z.strip()
            break
    return p.returncode, (p.stdout or "").count("  FAIL "), bilanz


def probe(name, datei, alt, neu, anzahl=1):
    s = ORIG[datei]
    if alt not in s:
        print("  ⚠ %-50s ANKER NICHT GETROFFEN" % name)
        return
    ZIELE[datei].write_text(s.replace(alt, neu, anzahl), encoding="utf-8")
    rc, fails, bilanz = lauf()
    ZIELE[datei].write_text(s, encoding="utf-8")
    if not bilanz:
        print("  ⚠ %-50s ABBRUCH OHNE BILANZ (rc=%d)" % (name, rc))
    elif rc == 0:
        print("  ✗ %-50s BEISST NICHT (%s)" % (name, bilanz))
    else:
        print("  ✓ %-50s %d FAIL  (%s)" % (name, fails, bilanz))


print("=" * 84)
rc, fails, bilanz = lauf()
print("Basis: rc=%d  %s" % (rc, bilanz))
if rc != 0:
    print("ABBRUCH: Basis ist nicht gruen.")
    sys.exit(2)
print("=" * 84)

# ── Backend: die Sortierregel ───────────────────────────────────────────────
probe("unbekannte Kennung legt einen leeren Platz an", "fragen",
      "            if e is not None and eid not in gesehen:",
      "            if eid not in gesehen:")

probe("nicht genannte Eintraege fallen weg", "fragen",
      '        raus += [e for e in vorhanden if e.get("id") not in gesehen]',
      "        pass")

probe("doppelte Kennung verdoppelt den Eintrag", "fragen",
      "        raus, gesehen = [], set()", "        raus, gesehen = [], list()")

probe("leere Liste wirft alles um (Sortierung ohne Wunschfolge)", "fragen",
      "        raus += [e for e in vorhanden if e.get(\"id\") not in gesehen]",
      "        raus += list(reversed([e for e in vorhanden "
      "if e.get(\"id\") not in gesehen]))")

probe("Nicht-Admin darf gemeinsame umsortieren", "fragen",
      "        if ist_admin:\n            glob_neu, glob_anders",
      "        if True:\n            glob_neu, glob_anders")

# ── Endpunkt ───────────────────────────────────────────────────────────────
probe("Endpunkt ohne Bereichs-Freigabe", "main",
      'async def ai_mouse_fragen_sortieren(request: Request,\n'
      '                                    user: str = Depends(require_aimouse_access)):',
      'async def ai_mouse_fragen_sortieren(request: Request,\n'
      '                                    user: str = Depends(require_auth)):')

probe("Benutzer aus dem Rumpf", "main",
      "    bewegt = await asyncio.to_thread(amf.sortieren, user, ids,",
      '    user = str((body or {}).get("user") or user)\n'
      "    bewegt = await asyncio.to_thread(amf.sortieren, user, ids,")

probe("Typpruefung der Kennungsliste raus", "main",
      "    if not isinstance(ids, list):", "    if False:")

probe("kein Deckel auf die Anzahl", "main",
      "    if len(ids) > (amf.MAX_JE_BENUTZER + amf.MAX_GEMEINSAM):", "    if False:")

probe("Admin-Recht nicht durchgereicht", "main",
      "    bewegt = await asyncio.to_thread(amf.sortieren, user, ids,\n"
      "                                     _is_admin_user(user))",
      "    bewegt = await asyncio.to_thread(amf.sortieren, user, ids, False)")

probe("blockierend im Event-Loop", "main",
      "    bewegt = await asyncio.to_thread(amf.sortieren, user, ids,\n"
      "                                     _is_admin_user(user))",
      "    bewegt = amf.sortieren(user, ids, _is_admin_user(user))")

# ⚠ MIT GENUG KONTEXT: `"fragen": amf.liste(user, _is_admin_user(user))})`
# steht ZWEIMAL in main.py – auch im GET-Endpunkt, der weiter oben liegt.
# `replace(..., 1)` traf deshalb eine FREMDE Funktion, und die Probe sah wie
# ein zahnloser Waechter aus. Sie war nur schlecht platziert (Register).
probe("die neue Liste kommt nicht zurueck", "main",
      '    return JSONResponse({"ok": True, "bewegt": bewegt,\n'
      '                         "fragen": amf.liste(user, _is_admin_user(user))})',
      '    return JSONResponse({"ok": True, "bewegt": bewegt})')

# ── Oberflaeche ────────────────────────────────────────────────────────────
probe("Griff auch ohne darf_aendern", "js",
      "            var griff = f.darf_aendern", "            var griff = true")

probe("dragover ohne Gruppenpruefung", "js",
      "                if (ziel.getAttribute('data-gem') !== _zieht.getAttribute('data-gem')) {\n"
      "                    return;\n                }\n                ev.preventDefault();",
      "                ev.preventDefault();")

probe("dragover ohne preventDefault", "js",
      "                ev.preventDefault();          // erst das erlaubt das Ablegen",
      "                /* kein preventDefault */")

probe("dragstart ohne Nutzlast", "js",
      "                    ev.dataTransfer.setData('text/plain',",
      "                    void (function(){}) || (function(){})(\n"
      "                        'text/plain',")

probe("keine Tastaturbedienung", "js",
      "                if (!ev.ctrlKey || (ev.key !== 'ArrowUp' && ev.key !== 'ArrowDown')) {",
      "                if (true) {")

probe("der Fokus wandert nicht mit", "js",
      "                        if (neu && neu.focus) { neu.focus(); }", "                        void neu;")

probe("zeichnet aus dem DOM statt aus der Antwort", "js",
      "            if (d && d.fragen) { _fragen = d.fragen; fragenZeichnen(); }",
      "            void d;")

probe("Fehlschlag wird verschwiegen", "js",
      "            zugMelden(String((e && e.message) || e)", "            void (")

probe("Meldeplatz nicht im Markup", "html",
      '<div id="am-q-zug" class="am-q-zug" role="status" aria-live="polite" hidden></div>',
      "")

probe("Hinweistext mit data-i18n statt data-i18n-html", "html",
      'data-i18n-html="aimouse.q_order"', 'data-i18n="aimouse.q_order"')

probe("i18n nur deutsch", "i18n",
      "        'aimouse.q_move':        'Move (drag, or Ctrl+Arrow)',\n", "")

probe("Griff gibt in der Flex-Zeile nach", "css",
      ".am-q-griff { flex: 0 0 auto; width: 20px;",
      ".am-q-griff { flex: 1 1 auto; width: 20px;")

probe("kein sichtbarer Tastatur-Fokus", "css",
      ".am-q-griff:focus-visible { outline: 2px solid var(--accent);",
      ".am-q-griff:focus-nie { outline: 2px solid var(--accent);")

print("=" * 84)
print("✓ = beisst · ✗ = Testmangel · ⚠ = Probe/Waechter untauglich")
