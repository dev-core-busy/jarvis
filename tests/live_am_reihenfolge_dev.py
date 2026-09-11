#!/usr/bin/env python3
"""Live auf DEV: Reihenfolge der AI-Maus-Fragen über den ECHTEN Endpunkt.

⚠ SIE ÄNDERT DIE REIHENFOLGE – ALSO STELLT SIE SIE ZURÜCK. Die erste Fassung
prüfte am Ende nur die MENGE (`sorted(...)`) und hat die vorgefundene Folge der
sechs echten Fragen umgedreht liegen lassen: genau den Zustand, den diese
Änderung überhaupt erst pflegbar macht. Eine Messung, die ihren Gegenstand
verstellt und dann etwas ANDERES zurückprüft, ist keine Wiederherstellung
(Register 2026-09-09). Die Probe-Fragen (Präfix ``ZZ-``) werden namentlich
entfernt; Skill-Schalter und Freigabe werden nicht angefasst.

⚠ DER BENUTZER MUSS FÜR AI-MAUS FREIGEGEBEN SEIN, sonst antwortet der Endpunkt
403 und jede Prüfung darunter wird übersprungen – also trivial wahr. Ohne
Freigabe endet die Probe mit Exit 2.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


from backend import main as M                                     # noqa: E402

BENUTZER = next((u for u in (os.environ.get("AIMOUSE_TESTUSER") or "",
                             "andreas.bender", "jarvis") if u), "jarvis")
TOKEN = M.generate_token(BENUTZER)
if not M._user_may_use_aimouse(BENUTZER):
    print("ABBRUCH: %r ist nicht fuer AI-Maus freigegeben – der Endpunkt\n"
          "         antwortet 403 und die Messung waere trivial wahr." % BENUTZER)
    sys.exit(2)
print("Benutzer: %s" % BENUTZER)


def ruf(pfad, methode="GET", rumpf=None, token=TOKEN):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                         # noqa: BLE001
            return e.code, {}
    except Exception as e:                                        # noqa: BLE001
        return 0, {"_fehler": str(e)}


NAMEN = ["ZZ-Eins", "ZZ-Zwei", "ZZ-Drei"]
angelegt = []
try:
    # Ausgangsbestand LESEN (nicht anfassen).
    st, d = ruf("/api/ai-mouse/fragen")
    check("Fragenliste erreichbar", st == 200, "HTTP %s" % st)
    vorher = [e.get("id") for e in (d.get("fragen") or [])]
    print("     vorgefunden: %d Fragen in dieser Folge:" % len(vorher))
    for e in (d.get("fragen") or []):
        print("       %s  %s" % (e.get("id"), str(e.get("titel"))[:34]))

    for n in NAMEN:
        st, d = ruf("/api/ai-mouse/fragen", "POST",
                    {"id": "", "titel": n, "prompt": "Probe " + n})
        if st == 200 and (d.get("frage") or {}).get("id"):
            angelegt.append(d["frage"]["id"])
    check("drei Probe-Fragen angelegt (Positivkontrolle)",
          len(angelegt) == 3, str(angelegt))
    if len(angelegt) != 3:
        raise SystemExit(1)

    st, d = ruf("/api/ai-mouse/fragen")
    jetzt = [e.get("id") for e in (d.get("fragen") or [])]
    check("sie stehen am Ende der Liste",
          jetzt[-3:] == angelegt, str(jetzt[-3:]))

    # ── Die Messung: umdrehen ──────────────────────────────────────────────
    wunsch = list(reversed(jetzt))
    st, d = ruf("/api/ai-mouse/fragen/reihenfolge", "POST", {"ids": wunsch})
    check("der Endpunkt antwortet 200", st == 200, "HTTP %s %s" % (st, d))
    check("er liefert die neue Liste mit", isinstance(d.get("fragen"), list))
    neu = [e.get("id") for e in (d.get("fragen") or [])]

    # ⚠ NUR JE TOPF: gemeinsame bleiben vorn. Geprueft wird deshalb die
    # Reihenfolge der EIGENEN – nicht die der ganzen Liste.
    eigen_vor = [e.get("id") for e in (ruf("/api/ai-mouse/fragen")[1].get("fragen") or [])
                 if not e.get("gemeinsam")]
    check("die eigenen Fragen sind umgedreht",
          eigen_vor == [i for i in wunsch if i in eigen_vor],
          str(eigen_vor[:5]))

    # Ein zweiter Abruf muss dasselbe liefern – die Reihenfolge ist GESPEICHERT,
    # nicht nur in der Antwort.
    st, d2 = ruf("/api/ai-mouse/fragen")
    check("ein neuer Abruf liefert dieselbe Reihenfolge (gespeichert)",
          [e.get("id") for e in (d2.get("fragen") or [])] == neu)

    # ── Toleranz und Schranken ────────────────────────────────────────────
    st, d = ruf("/api/ai-mouse/fragen/reihenfolge", "POST",
                {"ids": [angelegt[0], "gibtsnicht"]})
    check("unbekannte Kennung: 200, nichts kaputt", st == 200, "HTTP %s" % st)
    st, d3 = ruf("/api/ai-mouse/fragen")
    check("keine Frage verloren",
          len(d3.get("fragen") or []) == len(neu),
          "%d != %d" % (len(d3.get("fragen") or []), len(neu)))

    st, _ = ruf("/api/ai-mouse/fragen/reihenfolge", "POST", {"ids": "keineliste"})
    check("`ids` als Zeichenkette: 400", st == 400, "HTTP %s" % st)
    st, _ = ruf("/api/ai-mouse/fragen/reihenfolge", "POST", {})
    check("ohne `ids`: 400", st == 400, "HTTP %s" % st)
    st, _ = ruf("/api/ai-mouse/fragen/reihenfolge", "POST",
                {"ids": ["x"] * 200})
    check("zu viele Kennungen: 400", st == 400, "HTTP %s" % st)
    st, _ = ruf("/api/ai-mouse/fragen/reihenfolge", "POST",
                {"ids": angelegt}, token="")
    check("ohne Token: 401", st == 401, "HTTP %s" % st)

    # ⚠ DER BENUTZER AUS DEM RUMPF DARF NICHTS BEWIRKEN.
    st, _ = ruf("/api/ai-mouse/fragen/reihenfolge", "POST",
                {"ids": list(reversed(angelegt)), "user": "jemand.anders"})
    st2, d4 = ruf("/api/ai-mouse/fragen")
    check("ein `user` im Rumpf aendert nichts an der Zuordnung",
          st == 200 and len(d4.get("fragen") or []) == len(neu))
finally:
    for fid in angelegt:
        ruf("/api/ai-mouse/fragen/" + fid, "DELETE")
    # ⚠ DIE FOLGE ZURUECKSTELLEN, nicht nur die Menge pruefen: die Messung hat
    # sie absichtlich umgedreht.
    if vorher:
        ruf("/api/ai-mouse/fragen/reihenfolge", "POST", {"ids": vorher})
    st, d = ruf("/api/ai-mouse/fragen")
    rest = [e.get("titel") for e in (d.get("fragen") or [])
            if str(e.get("titel") or "").startswith("ZZ-")]
    check("Probe-Fragen restlos entfernt", not rest, str(rest))
    nach = [e.get("id") for e in (d.get("fragen") or [])]
    check("der vorgefundene Bestand ist vollstaendig da",
          sorted(nach) == sorted(vorher),
          "%d von %d" % (len(nach), len(vorher)))
    check("und er steht in der VORGEFUNDENEN Reihenfolge", nach == vorher,
          "%s != %s" % (str(nach)[:60], str(vorher)[:60]))

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 64, _ok, _fail, "=" * 64))
sys.exit(1 if _fail else 0)
