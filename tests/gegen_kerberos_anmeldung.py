#!/usr/bin/env python3
"""Gegenproben zur Windows-Anmeldung (test_kerberos_anmeldung / test_kerberos_kdc).

Dreht je EINE Zusage im Produktcode zurueck und erwartet FAILs MIT
Bilanzzeile; stellt danach byte-gleich wieder her (md5).

Sicherung auf PLATTE mit Laufmarke (``~/.cache/jarvis_gegen_kerberos``): wird
ein Lauf abgeschossen, nimmt der naechste Start den Rueckstand selbst zurueck –
ein gepatchter Arbeitsbaum meldet sonst Fehler, die es im Code nicht gibt.

Die KDC-Probe laeuft nur, wenn ``test_kerberos_kdc.py`` laufen kann
(KRB5_TESTWURZEL); sonst wird sie BENANNT uebersprungen und der Lauf endet
mit Exit 2 statt 0 – unvollstaendig ist nicht bestanden.

BEWUSST OHNE PROBE (nicht messbar, und das gehoert benannt statt verschwiegen):
  * die Mechanismus-Pruefung (OID) und ``GSS_S_CONTINUE_NEEDED`` – ein NTLM-in-
    SPNEGO-Token kann ein MIT-Aufbau nicht erzeugen; das rohe NTLM faengt die
    Vorpruefung, die ihre eigene Probe hat.
  * ``WindowsKontoPasst`` in C# – ohne .NET hier nicht ausfuehrbar.

Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen
bzw. KDC-Probe nicht lauffaehig.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
KM = W / "backend/kerberos_anmeldung.py"
MA = W / "backend/main.py"
JC = W / "ai-mouse/src/AiMouse/Vision/JarvisClient.cs"
TR = W / "ai-mouse/src/AiMouse/TrayApplicationContext.cs"
SB = W / "backend/sandbox.py"
DATEIEN = [KM, MA, JC, TR, SB]
SICH = Path.home() / ".cache" / "jarvis_gegen_kerberos"
MARKE = SICH / "LAUF"
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()  # noqa: E731
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

T1, T2 = "test_kerberos_anmeldung.py", "test_kerberos_kdc.py"

PROBEN = [
    ("NTLM-Vorpruefung entfernt", KM,
     "    if token.startswith(_NTLM_KENNUNG):", "    if False:", T1),
    ("fremder Realm wird angenommen", KM,
     '    if realm.upper() != (realm_erwartet or "").strip().upper():', "    if False:", T1),
    ("Dienst-Principal wird angenommen", KM,
     '    if "/" in name or "\\\\" in name:', "    if False:", T1),
    ("Antwort-Token wird verworfen", KM,
     '        antwort = ctypes.string_at(raus.value, raus.length) if raus.length else b""',
     '        antwort = b""', T2),
    ("Sitzung MIT Admin-Rechten", MA,
     "    token = generate_token(konto, mit_2fa=False, ohne_admin=True)",
     "    token = generate_token(konto, mit_2fa=False, ohne_admin=False)", T1),
    ("lokales Konto per Kerberos erreichbar", MA,
     "    if konto in ALLOWED_USERS:\n        print(f\"[AUTH] Windows-Anmeldung abgewiesen",
     "    if False:\n        print(f\"[AUTH] Windows-Anmeldung abgewiesen", T1),
    ("deaktiviertes AD-Konto kommt herein", MA,
     "        if uac & 0x2:", "        if False:", T1),
    # Der Fall "fehler" hat davor einen EIGENEN Zweig (503) – diese Zeile traegt
    # "alles ausser ja sperrt". Die erste Fassung der Probe hiess "fehler wird zu
    # Einlass" und blieb zahnlos, weil sie die falsche Schranke meinte.
    ("nur 'nein' sperrt, eine unerwartete Antwort laesst herein", MA,
     '    if freigabe != "ja":', '    if freigabe == "nein":', T1),
    ("neue Aufforderung nach abgewiesenem Ticket", MA,
     '"error": "Windows-Anmeldung nicht möglich: %s" % e},\n                            status_code=401)',
     '"error": "Windows-Anmeldung nicht möglich: %s" % e},\n                            status_code=401, '
     'headers={"WWW-Authenticate": "Negotiate"})', T1),
    ("Aufforderung auch ohne Keytab", MA,
     '"eingerichtet (%s)." % grund}, status_code=503)',
     '"eingerichtet (%s)." % grund}, status_code=503, headers={"WWW-Authenticate": "Negotiate"})',
     T1),
    ("Rahmen ohne Sicherheitsprotokoll", MA,
     '    await _anmeldung_protokollieren(request, resp, "windows")', "    pass", T1),
    ("Client folgt Umleitungen", JC,
     "                AllowAutoRedirect = false,", "                AllowAutoRedirect = true,", T1),
    ("Client schickt keine Windows-Anmeldung", JC,
     "                UseDefaultCredentials = true,", "                UseDefaultCredentials = false,",
     T1),
    ("Windows-Anmeldung abgeschaltet (Vorkommen bleibt)", TR,
     "        if (WindowsKontoPasst(_settings) &&\n            await _client.WindowsAnmeldenAsync(ct)",
     "        if (false &&\n            await _client.WindowsAnmeldenAsync(ct)", T1),
    ("Keytab fuer Dateiwerkzeuge lesbar", SB,
     '    "data/kerberos",\n    # Short Tracks', "    # Short Tracks", T1),
    ("Endung .keytab nicht mehr geheim", SB,
     '                  ".keytab"}', "                  }", T1),
    ("Keytab fuer die Shell lesbar", SB,
     "    r'\\.keytab\\b|/kerberos/http\\b|'\n", "", T1),
    ("Start merkt das Windows-Token nicht", TR,
     "                ConfigStore.SaveToken(_client.Token);\n            }\n            await FragenNachladenAsync()",
     "            }\n            await FragenNachladenAsync()", T1),
]

# REGEL statt gepflegter Liste: jede Datei, die eine Probe anfasst, wird gesichert.
_fehlt = {str(p[1]) for p in PROBEN} - {str(d) for d in DATEIEN}
if _fehlt:
    print("ABBRUCH: Probe(n) auf ungesicherte Datei(en): %s" % _fehlt)
    sys.exit(2)


def zurueck():
    if not MARKE.is_file():
        return
    for p in DATEIEN:
        s = SICH / p.name
        if s.is_file():
            p.write_bytes(s.read_bytes())
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def lauf(test):
    r = subprocess.run([sys.executable, str(W / "tests" / test)], capture_output=True,
                       text=True, env=env, timeout=600)
    m = re.search(r"BILANZ: (\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


zurueck()
SICH.mkdir(parents=True, exist_ok=True)
for p in DATEIEN:
    (SICH / p.name).write_bytes(p.read_bytes())
vorher = {p: md5(p) for p in DATEIEN}
MARKE.write_text(str(os.getpid()))

rc_ende = 1
try:
    kdc_da = True
    for t in (T1, T2):
        rc, f = lauf(t)
        if t == T2 and rc == 2:
            kdc_da = False
            print("HINWEIS: %s kann nicht laufen (KRB5_TESTWURZEL?) – KDC-Probe entfaellt." % t)
            continue
        if rc != 0 or f != 0:
            print("ABBRUCH: Basis %s nicht gruen (rc=%s, FAIL=%s)" % (t, rc, f))
            sys.exit(2)
    print("Basis gruen.\n")
    gut, gelaufen = 0, 0
    for name, datei, a, n, t in PROBEN:
        if t == T2 and not kdc_da:
            print("  UEBERSPRUNGEN %s" % name)
            continue
        gelaufen += 1
        txt = (SICH / datei.name).read_text(encoding="utf-8")
        if txt.count(a) != 1:
            print("  VERFEHLT %s: Anker %dx" % (name, txt.count(a)))
            continue
        datei.write_text(txt.replace(a, n, 1), encoding="utf-8")
        try:
            rc, f = lauf(t)
        finally:
            datei.write_bytes((SICH / datei.name).read_bytes())
        biss = rc == 1 and (f or 0) > 0
        gut += biss
        print("  %s %s: %s rc=%s FAIL=%s%s" % ("OK     " if biss else "ZAHNLOS", name, t, rc, f,
                                              "" if f is not None else " (OHNE BILANZ!)"))
    print("\n%d von %d beissen einzeln." % (gut, gelaufen))
    rc_ende = 0 if gut == gelaufen else 1
    if rc_ende == 0 and not kdc_da:
        rc_ende = 2
finally:
    for p in DATEIEN:
        p.write_bytes((SICH / p.name).read_bytes())
    gleich = all(md5(p) == vorher[p] for p in DATEIEN)
    print("byte-gleich:", gleich)
    if gleich and MARKE.is_file():
        MARKE.unlink()
sys.exit(rc_ende)
