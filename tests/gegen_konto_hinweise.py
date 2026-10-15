#!/usr/bin/env python3
"""Gegenprobe zu ``test_konto_hinweise.py`` und ``test_konto_hinweise_ui.js``: beissen sie?

Je Probe wird EINE Zusage des Hinweises "deine 2FA wurde zurueckgesetzt"
zurueckgedreht (Schreibweisen-Falle, Hinweis trotz wieder eingeschalteter 2FA,
Name als Markup, Karte verschwindet bei Fehler, …) und Exit 1 verlangt.
Ablauf wie gegen_totp_admin.py (gruene Basis, Sicherung im HOME, Laufmarke, md5).
NICHT in einem Sammellauf ueber ``tests/*`` mitlaufen lassen – patcht den Baum.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
PY_W = [sys.executable, str(WURZEL / "tests" / "test_konto_hinweise.py")]
JS_W = ["node", str(WURZEL / "tests" / "test_konto_hinweise_ui.js")]
SICHERUNG = Path.home() / ".gegen_konto_hinweise"
MARKE = SICHERUNG / "laeuft"

MAIN = "backend/main.py"
MODUL = "frontend/js/konto_hinweise.js"
CHAT = "frontend/chat.html"

PROBEN = [
    ("Hinweis nur unter der Schreibweise der Ruecksetzung", MAIN,
     "    eigene = [st for k, st in (_load_auth_state().get(\"users\") or {}).items()\n              if isinstance(st, dict) and _norm_login(k) == norm]",
     "    eigene = [st for k, st in (_load_auth_state().get(\"users\") or {}).items()\n              if isinstance(st, dict) and k == username]", PY_W),
    ("Hinweis trotz wieder eingeschalteter 2FA", MAIN,
     "    if any(st.get(\"totp_enabled\") and st.get(\"totp_secret\") for st in eigene):\n        return []\n",
     "", PY_W),
    ("Quittieren raeumt nur die eigene Schreibweise ab", MAIN,
     "if isinstance(st, dict) and _norm_login(k) == norm and st.get(\"totp_zurueckgesetzt\"):",
     "if isinstance(st, dict) and k == user and st.get(\"totp_zurueckgesetzt\"):", PY_W),
    ("verify laesst den Vermerk stehen", MAIN,
     "    _konto_hinweis_abraeumen(username)\n", "", PY_W),
    ("Ruecksetzung vermerkt nichts", MAIN,
     "                                \"totp_pending_secret\": None,\n                                \"totp_zurueckgesetzt\": {\"von\": _display_name(user),\n                                                        \"am\": int(time.time())}})",
     "                                \"totp_pending_secret\": None})", PY_W),
    ("beliebige Hinweis-Art wird angenommen", MAIN,
     "    if art != \"totp_zurueckgesetzt\":\n        return JSONResponse({\"ok\": False, \"error\": \"Unbekannter Hinweis.\"}",
     "    if False:\n        return JSONResponse({\"ok\": False, \"error\": \"Unbekannter Hinweis.\"}", PY_W),
    ("Name des Admins als Markup", MODUL,
     "        text.textContent = T('konto.totp_reset_text',",
     "        text.innerHTML = T('konto.totp_reset_text',", JS_W),
    ("offener Hinweis wird als erledigt gemerkt", MODUL,
     "                if (!h) { merken(tok); return; }",
     "                merken(tok); if (!h) { return; }", JS_W),
    ("Karte verschwindet, wenn Quittieren scheitert", MODUL,
     "                spaeter.disabled = false;\n",
     "                spaeter.disabled = false; karte.remove();\n", JS_W),
    ("kein Warten auf eine spaetere Anmeldung", MODUL,
     "        }, 2000);\n",
     "        }, 2000); clearInterval(warten);\n", JS_W),
    ("Chat-Seite laedt das Modul nicht", CHAT,
     "<script src=\"/static/js/konto_hinweise.js?v=", "<script data-x=\"/static/js/konto_hinweise.js?v=", JS_W),
]
DATEIEN = sorted({p[1] for p in PROBEN})

_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  ok   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  -> " + detail) if detail else ""))


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf(cmd):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    e = subprocess.run(cmd, cwd=WURZEL, capture_output=True, text=True, timeout=300, env=env)
    return e.returncode, e.stdout + e.stderr


def zurueck():
    for rel in DATEIEN:
        s = SICHERUNG / rel.replace("/", "__")
        if s.is_file():
            shutil.copyfile(s, WURZEL / rel)


if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

for cmd in (PY_W, JS_W):
    rc, aus = lauf(cmd)
    if rc != 0:
        print("ABBRUCH (Exit 2): Basislauf %s nicht gruen (Exit %d)." % (Path(cmd[-1]).name, rc))
        print(aus[-1500:])
        sys.exit(2)
print("Basislauf beider Waechter gruen.\n")

SICHERUNG.mkdir(mode=0o700, exist_ok=True)
for rel in DATEIEN:
    shutil.copyfile(WURZEL / rel, SICHERUNG / rel.replace("/", "__"))
soll = {rel: md5(WURZEL / rel) for rel in DATEIEN}
MARKE.write_text("laeuft", encoding="utf-8")
try:
    for name, rel, alt, neu, waechter in PROBEN:
        pfad = WURZEL / rel
        quelle = pfad.read_text(encoding="utf-8")
        n = quelle.count(alt)
        if n != 1:
            pruefe(False, "%s -> Anker eindeutig" % name, "%d Treffer" % n)
            continue
        pfad.write_text(quelle.replace(alt, neu), encoding="utf-8")
        rc, _aus = lauf(waechter)
        pruefe(rc == 1, "%s -> %s meldet (Exit 1)" % (name, Path(waechter[-1]).name), "Exit %d" % rc)
        zurueck()
        pruefe(md5(pfad) == soll[rel], "%s -> Datei byte-gleich zurueck" % name)
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

for rel in DATEIEN:
    pruefe(md5(WURZEL / rel) == soll[rel], "%s unveraendert" % rel)
for cmd in (PY_W, JS_W):
    rc, _ = lauf(cmd)
    pruefe(rc == 0, "Abschlusslauf %s gruen" % Path(cmd[-1]).name, "Exit %d" % rc)
shutil.rmtree(SICHERUNG, ignore_errors=True)

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
