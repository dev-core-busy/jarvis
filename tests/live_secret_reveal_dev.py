#!/usr/bin/env python3
"""LIVE auf DEV: das Auge holt den gespeicherten Wert wirklich.

Laeuft AUF dem Server im Produktiv-venv als DIENSTBENUTZER:
    runuser -u jarvis -- venv/bin/python tests/live_secret_reveal_dev.py

⚠ ALS DIENSTBENUTZER, NICHT ALS ROOT: eine Probe, die als root eine Datendatei
anfasst, hinterlaesst sie root-eigen, und der Dienst meldet danach fuer JEDEN
Benutzer "nichts hinterlegt" (im Projekt zweimal am selben Tag bezahlt).

Der Wert selbst wird NIE ausgegeben – verglichen wird gegen den auf der Platte
gespeicherten Klartext, gemeldet werden nur Laenge und Gleichheit.
"""
import json
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
BASIS = "https://127.0.0.1"


def ruf(bereich, kennung, token=None, extra=None):
    rumpf = {"bereich": bereich, "kennung": kennung}
    if extra:
        rumpf.update(extra)
    req = urllib.request.Request(
        BASIS + "/api/secret/reveal",
        data=json.dumps(rumpf).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": "Bearer " + token} if token else {})},
        method="POST")
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:  # noqa: BLE001
            return e.code, {}


print("\033[1m1 – Sitzungstoken (der Weg, den /api/login nach der Anmeldung geht)\033[0m")
from backend import main as M  # noqa: E402

token = M.generate_token("jarvis")
check("Token fuer den lokalen Administrator erzeugt", bool(token))

print("\n\033[1m2 – Der gespeicherte Wert kommt wirklich heraus\033[0m")
from backend.config import config  # noqa: E402

mounts = ((config.get_skill_states().get("knowledge", {}) or {})
          .get("config", {}) or {}).get("mounts") or []
idx = next((i for i, m in enumerate(mounts) if (m or {}).get("password")), None)
check("Positivkontrolle: auf DEV liegt mindestens eine Freigabe MIT Kennwort",
      idx is not None, "%d Freigaben" % len(mounts))
if idx is None:
    print("\033[31mABBRUCH: ohne hinterlegtes Kennwort ist nichts zu messen\033[0m")
    sys.exit(2)
erwartet = str(mounts[idx]["password"])

s, r = ruf("mount", str(idx), token)
check("HTTP 200", s == 200, "%s %s" % (s, r.get("error")))
check("⚠ der Wert ist BYTE-GLEICH mit dem gespeicherten (Laenge %d)"
      % len(erwartet), r.get("wert") == erwartet,
      "geliefert %d Zeichen" % len(str(r.get("wert") or "")))

print("\n\033[1m3 – Das Audit-Log hat den Abruf, aber nicht den Wert\033[0m")
from backend import audit_log  # noqa: E402

eintraege = [e for e in audit_log.read_log(limit=40)
             if e.get("tool") == "secret_reveal"]
check("der Abruf steht im Audit-Log", bool(eintraege),
      "%d Eintraege" % len(eintraege))
letzt = eintraege[0] if eintraege else {}
check("… mit Bereich 'mount'",
      json.dumps(letzt, ensure_ascii=False).find('"mount"') >= 0,
      json.dumps(letzt, ensure_ascii=False)[:160])
check("⚠⚠ DER WERT STEHT NICHT IM AUDIT-LOG",
      erwartet not in json.dumps(eintraege, ensure_ascii=False))

print("\n\033[1m4 – Was NICHT herauskommt\033[0m")
s, r = ruf("einstellung", "jwt_secret", token)
check("⚠ der Signierschluessel der Sitzungstoken: abgewiesen",
      s != 200 and not r.get("wert"), "%s %s" % (s, str(r)[:80]))
check("… und die Meldung nennt den Grund",
      "freigegeben" in str(r.get("error") or ""), str(r.get("error"))[:90])

s, r = ruf("mount", str(idx))
check("⚠ ohne Sitzungstoken: 401", s == 401, "%s %s" % (s, str(r)[:80]))

s, r = ruf("wolke", "x", token)
check("ein unbekannter Bereich: 400", s == 400, "%s %s" % (s, str(r)[:80]))

s, r = ruf("profil", "irgendwas", token)
check("⚠ 'profil' gibt es nicht (kein toter Zweig): 400", s == 400,
      "%s %s" % (s, str(r)[:80]))

s, r = ruf("mount", "999", token)
check("eine Freigabe, die es nicht gibt: 404", s == 404, "%s %s" % (s, str(r)[:80]))

print("\n\033[1m5 – Die Drossel greift (ZULETZT: sie verbraucht das Stundenkontingent)\033[0m")
from backend import secret_reveal as sr  # noqa: E402

# ⚠ SIE STEHT AM ENDE, UND DAS IST PFLICHT: der Zaehler liegt im SPEICHER DES
# DIENSTES. Er ist von hier aus nicht zurueckzusetzen – ein
# `sr._reset_fuer_tests()` in diesem Prozess raeumt einen ANDEREN Zaehler auf
# und ist eine Selbsttaeuschung (beim ersten Lauf genau so passiert: die
# darauffolgende Browser-Probe lief in 429 und meldete einen Fehler, den es
# nicht gab). Wer danach messen will, startet den Dienst neu.
# Bewusst mit einem Bereich, der ohnehin abgewiesen wird – die Drossel greift
# VOR der Bereichspruefung, es wird also kein Geheimnis 60-mal geholt.
letzter = (0, {})
for _ in range(sr.MAX_JE_STUNDE + 2):
    letzter = ruf("wolke", "x", token)
check("⚠ nach %d Abrufen: 429" % sr.MAX_JE_STUNDE, letzter[0] == 429,
      "%s %s" % (letzter[0], str(letzter[1])[:80]))
check("… und der Grund sagt, dass es keine Aussage ueber die Berechtigung ist",
      "Berechtigung" in str(letzter[1].get("error") or ""),
      str(letzter[1].get("error"))[:90])
print("  \033[33m! das Kontingent von 'jarvis' ist jetzt verbraucht "
      "(1 Stunde, oder Dienst neu starten)\033[0m")

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
