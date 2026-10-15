#!/usr/bin/env python3
"""LIVE: der ECHTE Vorfall auf einer ECHTEN Sitzung, mit dem deployten Code.

Legt eine Wegwerf-Sitzung an, schreibt den beschaedigten Kontext hinein
(genau die Struktur von ECHT: unbeantwortete Maus-Frage am Ende) und laesst
`geheilter_sitzungskontext` darauf los - die echte Funktion, echte Dateien.

Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.
"""
import shutil, sys, uuid
from pathlib import Path
sys.path.insert(0, "/opt/jarvis")

from backend import chat_sessions as cs          # noqa: E402
from backend.agent import (geheilter_sitzungskontext, serialize_history,   # noqa: E402
                           ist_benutzerfrage)
from google.genai import types                    # noqa: E402

ok = fail = 0
def pruef(b, t):
    global ok, fail
    if b: ok += 1
    else: fail += 1; print(f"  FAIL: {t}")

USER = f"__test_heilung_{uuid.uuid4().hex[:8]}"
MAUS = "generiere ein 300 auf 300 Pixel Comic Bild einer schnell rennenden Maus"
KUH = "generiere ein kleines, fotorealistisches Bild einer gruenen Kuh"

def t(rolle, text): return types.Content(role=rolle, parts=[types.Part.from_text(text=text)])

# Die Sitzung MUSS ueber create_session entstehen: save_context prueft mit
# _valid(), ob es sie gibt, und schreibt sonst still nichts. Eine erfundene
# Kennung laesst den Test 0 Eintraege messen und wie ein Codefehler aussehen.
_sess = cs.create_session(USER, "Heilungstest")
SID = _sess["id"]
print(f"  Sitzung angelegt: {SID}")

# Beschaedigter Kontext: Frage ohne Antwort am Ende - der Zustand von ECHT.
kaputt = [t("user", "Zeichne einen Drachen"), t("model", "Hier ist das Bild"),
          t("user", MAUS)]
cs.save_context(USER, SID, serialize_history(kaputt))
roh = cs.load_context(USER, SID)
print(f"  geschrieben: {len(roh)} Eintraege, letzter = unbeantwortete Maus-Frage")
pruef(len(roh) == 3, "Ausgangszustand nicht geschrieben")

# ── DIE MESSUNG ────────────────────────────────────────────────────────────
geheilt = geheilter_sitzungskontext(USER, SID)
maus_drin = any(ist_benutzerfrage(e) and MAUS[:25] in (e.parts[0].text or "")
                for e in geheilt)
print(f"  nach der Heilung: {len(geheilt)} Eintraege")
pruef(not maus_drin, "die unbeantwortete Maus-Frage ist NOCH im Kontext")
pruef(len(geheilt) == 2, f"erwartet 2 Eintraege, sind {len(geheilt)}")

# Heilung muss auf PLATTE stehen, nicht nur im Speicher.
platte = cs.load_context(USER, SID)
pruef(len(platte) == 2, f"Heilung nicht gespeichert - auf Platte stehen {len(platte)}")

# Zweiter Aufruf: idempotent, nichts weiter entfernt.
nochmal = geheilter_sitzungskontext(USER, SID)
pruef(len(nochmal) == 2, f"zweiter Aufruf entfernt weiter (jetzt {len(nochmal)})")

# Gegenrichtung: ein GESUNDER Kontext bleibt unangetastet.
gesund = [t("user", "Frage A"), t("model", "Antwort A"),
          t("user", KUH), t("model", "Hier ist die Kuh")]
cs.save_context(USER, SID, serialize_history(gesund))
raus = geheilter_sitzungskontext(USER, SID)
pruef(len(raus) == 4, f"gesunder Kontext beschaedigt: {len(raus)} statt 4")
pruef(any(ist_benutzerfrage(e) and KUH[:20] in (e.parts[0].text or "") for e in raus),
      "die Kuh-Frage wurde faelschlich entfernt")

# Aufraeumen
try:
    shutil.rmtree(Path("/opt/jarvis/data/chats") / USER, ignore_errors=True)
    print(f"  Wegwerf-Sitzung entfernt: {USER}")
except Exception as e:
    print(f"  WARNUNG: Aufraeumen fehlgeschlagen: {e}")

print(f"\n{ok} bestanden, {fail} fehlgeschlagen")
sys.exit(1 if fail else 0)
