#!/usr/bin/env python3
"""Gegenprobe zu ``test_totp_admin_reset.py`` und ``test_totp_admin_ui.js``: beissen sie?

Je Probe wird EINE Zusage der Admin-Ruecksetzung zurueckgedreht (kein Kennwort
geprueft, Kennwort des falschen Kontos, eigenes Konto erlaubt, Secret in der
Liste, Kontoname als Markup, Fehler verschwindet von selbst, …) und vom
zustaendigen Waechter Exit 1 verlangt.

Vorgehen wie bei gegen_stt_lokal.py: gruener Basislauf, Sicherung im HOME
(0700), Laufmarke gegen Abbruch-Rueckstand, md5-Nachweis, ohne Bytecode.
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
PY_W = [sys.executable, str(WURZEL / "tests" / "test_totp_admin_reset.py")]
JS_W = ["node", str(WURZEL / "tests" / "test_totp_admin_ui.js")]
SICHERUNG = Path.home() / ".gegen_totp_admin"
MARKE = SICHERUNG / "laeuft"

MAIN = "backend/main.py"
MODUL = "frontend/js/totp_admin.js"
APP = "frontend/js/app.js"
SETTINGS = "frontend/settings.html"

PROBEN = [
    # ── Backend ──
    ("Admin-Kennwort wird nicht geprueft", MAIN,
     "    if not await asyncio.to_thread(authenticate_linux_user, user, kennwort):\n        _totp_protokoll(user, ziel, \"kennwort_falsch\")",
     "    if False:\n        _totp_protokoll(user, ziel, \"kennwort_falsch\")", PY_W),
    ("Kennwort des ZIELKONTOS statt des Admins", MAIN,
     "    if not await asyncio.to_thread(authenticate_linux_user, user, kennwort):",
     "    if not await asyncio.to_thread(authenticate_linux_user, ziel, kennwort):", PY_W),
    ("eigenes Konto erlaubt", MAIN,
     "    if _norm_login(ziel) == _norm_login(user):\n        return JSONResponse({\"ok\": False, \"error\": \"SELF\",\n                             \"detail\": \"Die eigene Zwei-Faktor",
     "    if False:\n        return JSONResponse({\"ok\": False, \"error\": \"SELF\",\n                             \"detail\": \"Die eigene Zwei-Faktor", PY_W),
    ("vorgemerktes Secret bleibt stehen", MAIN,
     "    _set_user_auth_state(ziel, {\"totp_enabled\": False, \"totp_secret\": None,\n                                \"totp_pending_secret\": None,\n",
     "    _set_user_auth_state(ziel, {\"totp_enabled\": False, \"totp_secret\": None,\n", PY_W),
    ("Liste verraet den Zustand samt Secret", MAIN,
     "{\"user\": u, \"display\": _display_name(u), \"self\": _norm_login(u) == _norm_login(user)}",
     "{\"user\": u, \"display\": _display_name(u), \"self\": _norm_login(u) == _norm_login(user), \"st\": _load_auth_state()[\"users\"][u]}", PY_W),
    ("Ruecksetzung fuer jeden Angemeldeten", MAIN,
     "async def totp_admin_reset(request: Request, user: str = Depends(require_local_auth)):",
     "async def totp_admin_reset(request: Request, user: str = Depends(require_auth)):", PY_W),
    ("Handlung nicht verbucht", MAIN,
     "    _note_activity(user, request)\n    try:\n        body = await request.json()\n    except Exception:  # noqa: BLE001\n        body = {}\n    if not isinstance(body, dict):",
     "    try:\n        body = await request.json()\n    except Exception:  # noqa: BLE001\n        body = {}\n    if not isinstance(body, dict):", PY_W),
    # ── Oberflaeche ──
    ("Kontoname als Markup", MODUL,
     "        kopf.appendChild(el('strong', { 'style': 'color:var(--text-primary);' }, u.display || u.user));",
     "        var _s = el('strong', { 'style': 'color:var(--text-primary);' }); _s.innerHTML = u.display || u.user; kopf.appendChild(_s);", JS_W),
    ("Fehlermeldung verschwindet von selbst", MODUL,
     "                meldung.textContent = text;   // bleibt stehen, bis der Admin handelt",
     "                meldung.textContent = text; setTimeout(function () { meldung.textContent = ''; }, 3000);", JS_W),
    ("Kennwort bleibt nach Fehlversuch im Feld", MODUL,
     "            }).then(function (res) {\n                pw.value = '';\n",
     "            }).then(function (res) {\n", JS_W),
    ("app.js ruft das Modul nicht auf", APP,
     "                    if (window.TotpAdmin) window.TotpAdmin.onShow();\n", "", JS_W),
    ("Modul nicht eingebunden", SETTINGS,
     "    <script src=\"/static/js/totp_admin.js?v=", "    <script data-x=\"/static/js/totp_admin.js?v=", JS_W),
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
