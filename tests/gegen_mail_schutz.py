"""Gegenproben zu test_mail_schutz: beisst der Waechter, wenn eine Schranke fehlt?

Je Probe wird GENAU EINE Stelle sabotiert und gezaehlt, wie viele FAIL der
Waechter meldet. Ein Abbruch (Exit 2) zaehlt NICHT als Biss – er ist "konnte
nicht laufen" (Register: eine Sabotage, die den Waechter abstuerzen laesst,
hat nicht gebissen).

    python3 tests/gegen_mail_schutz.py
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import hashlib  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

W = Path(__file__).resolve().parent.parent
TEST = W / "tests" / "test_mail_schutz.py"
S = "backend/mail_schutz.py"
SK = "skills/email/main.py"
RU = "backend/mail_runner.py"
RE = "backend/mail_rules.py"
AC = "backend/mail_accounts.py"

PROBEN = [
    ("Empfaenger-Schranke: niemand gilt als extern", S,
     "    extern = [a for a in empf if not domaene_erlaubt(a, doms)]\n",
     "    extern = []\n"),
    ("Domaene per Teilstring statt an der Grenze", S,
     '    return any(d == x or d.endswith("." + x) for x in domaenen)\n',
     "    return any(x in d for x in domaenen)\n"),
    ("Firmenwissen + extern wird gesendet", S,
     "        if l.weitere_bereiche:\n", "        if False:\n"),
    ("Ausgangspruefung im Versand fehlt", S,
     '    gruende = inhalt_befunde("\\n".join(str(t or "") for t in texte), sperrbegriffe(c))\n',
     "    gruende = []\n"),
    ("Anhaenge nach aussen werden gesendet", S,
     "        if anhaenge:\n", "        if False:\n"),
    ("email_senden ignoriert die Gruende", SK,
     "entwurf=bool(gruende),", "entwurf=False,"),
    ("email_antworten prueft nicht", SK,
     "                gruende = _antwort_pruefen(c, mid, text, allen)\n",
     "                gruende = []\n"),
    ("email_weiterleiten prueft nicht", SK,
     "                gruende = _weiterleitung_pruefen(c, mid, an, text)\n",
     "                gruende = []\n"),
    ("Zitat einer fremden Nachricht wird nicht geprueft", SK,
     '    texte = [text] + ([alt.betreff or "", alt.text or ""] if fremd else [])\n',
     "    texte = [text]\n"),
    ("Regel-Lauf setzt die Schranke nicht", RU,
     "        marke_l = _schutz.lauf_cv.set(_schutz.lauf_fuer(\n"
     '            regel, n, str(getattr(konto, "adresse", "") or "")))\n',
     "        marke_l = _schutz.lauf_cv.set(None)\n"),
    ("Regel-Lauf nimmt die Schranke nicht wieder weg", RU,
     ",\n                           (_schutz.lauf_cv, marke_l)):", "):"),
    ("Regel-Prompt wird nicht geprueft", RE,
     '                   else mail_schutz.feld_pruefen("regel", prompt))\n',
     "                   else [])\n"),
    ("Bestands-Prompt blockiert das Umschalten", RE,
     '        gruende = ([] if bestehend and prompt == (bestehend.get("prompt") or "")\n',
     "        gruende = ([] if False\n"),
    ("Stil: Handlungsanweisungen nicht geprueft", S,
     '    if art == "stil":\n        for name, rx in _STIL_AKTION:\n',
     '    if False:\n        for name, rx in _STIL_AKTION:\n'),
    ("Injektionsmuster nicht geprueft", S,
     '    if art in ("regel", "stil"):\n', "    if False:\n"),
    ("Signatur: versteckter Text erlaubt", S,
     "        if sonde.versteckt:\n", "        if False:\n"),
    ("Signatur: fremde Bilder erlaubt", S,
     '        if fremd:\n            gruende.append("Bild von',
     '        if False:\n            gruende.append("Bild von'),
    ("Stil-Anlegen prueft nicht", AC,
     '    _schutz_pruefen(user, "stil", str(text or "").strip()[:VORGABE_MAX])\n', ""),
    ("Signatur-Anlegen prueft nicht", AC,
     '    _schutz_pruefen(user, "signatur", str(text or "").strip()[:SIG_TEXT_MAX],\n',
     '    (user, "signatur", str(text or "").strip()[:SIG_TEXT_MAX],\n'),
    ("Kartennummer ohne Luhn-Pruefung", S,
     "        if 13 <= len(ziffern) <= 19 and _luhn(ziffern):\n",
     "        if 13 <= len(ziffern) <= 19:\n"),
    ("IBAN wird nicht vor der Kartensuche herausgenommen", S,
     '    t = _IBAN.sub(" ", t)\n', ""),
    ("Kennwort-Angabe ohne Wertbedingung", S,
     '     r"(?=\\S{6,})(?=\\S*[0-9!#$%&*+/=?^_~@-])\\S+"),\n', '     r"\\S+"),\n'),
    ("Sperrbegriff ohne Wortgrenze", S,
     "        if re.search(vor + re.escape(b) + nach, t, re.IGNORECASE):\n",
     "        if b.lower() in t.lower():\n"),
]
DATEIEN = sorted({p[1] for p in PROBEN})
ORIG = {f: (W / f).read_bytes() for f in DATEIEN}
# Bytecode aus: Sabotage und Wiederherstellung in derselben Sekunde mit
# gleicher Groesse liessen sonst eine sabotierte .pyc stehen (Register).
UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def zurueck():
    for f, b in ORIG.items():
        if (W / f).read_bytes() != b:
            (W / f).write_bytes(b)


def lauf():
    r = subprocess.run([sys.executable, str(TEST)], capture_output=True, text=True,
                       timeout=180, env=UMG)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


rc, b, f = lauf()
if rc or not b or f:
    print(f"ABBRUCH: Basis nicht gruen (rc={rc} bilanz={b} fails={f})")
    sys.exit(2)
print("Basis gruen.\n")

gut = 0
try:
    for name, rel, a, n in PROBEN:
        zurueck()
        s = (W / rel).read_text(encoding="utf-8")
        if s.count(a) != 1:
            print(f"  ⚠ VERFEHLT  {name} (Anker {s.count(a)}x)")
            continue
        (W / rel).write_text(s.replace(a, n, 1), encoding="utf-8")
        rc, b, f = lauf()
        zurueck()
        ok = rc == 1 and b and f > 0
        gut += ok
        grund = "" if b else " (OHNE BILANZ – Abbruch, kein Biss)"
        print(f"  {'OK     ' if ok else 'ZAHNLOS'}  {name}: {f} FAIL, rc={rc}{grund}")
finally:
    zurueck()
    for fn, bts in ORIG.items():
        if hashlib.md5((W / fn).read_bytes()).digest() != hashlib.md5(bts).digest():
            print(f"  ⚠ RUECKSTAND in {fn}")
print(f"\n{gut} von {len(PROBEN)} beissen einzeln.")
sys.exit(0 if gut == len(PROBEN) else 1)
