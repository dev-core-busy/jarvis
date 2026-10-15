#!/usr/bin/env python3
"""Live auf DEV: loescht POST /api/chat/sessions/delete wirklich MEHRERE Chats?

Gefahren wird ueber den ECHTEN HTTPS-Endpunkt gegen den laufenden Dienst. Der
AST-Waechter (tests/test_chat_sammel_loeschen.py) kann sagen, dass die
Schranken im Code stehen – nicht, dass der Endpunkt antwortet, dass genau die
gewuenschten Ordner verschwinden und dass der uebrige Bestand stehen bleibt.

⚠ NUR EIGENES MATERIAL. Ein erfundenes Pruefkonto geht nicht: `require_auth`
weist es mit 403 ab, und eine Freigabe umzustellen, nur damit eine Messung
laeuft, ist der schlechtere Weg (Register). Gemessen wird deshalb unter dem
freigegebenen Konto – aber ausschliesslich an drei Chats, die dieser Lauf
SELBST anlegt. Der vorgefundene Bestand wird vorher gezaehlt und hinterher
verglichen; weicht er ab, ist das ein FAIL und kein Nebengeraeusch. Das
`finally` raeumt die eigenen Chats auch nach einem Abbruch weg.

⚠ DREI Chats, nicht einer: mit einem einzigen waere "eines von mehreren bleibt
stehen" gar nicht messbar (Register: der Loeschfall wird nicht hergestellt).

    python3 tests/live_chat_sammel_loeschen_dev.py
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)
BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def abschnitt(t):
    print("\n== %s" % t)


def abbruch(grund):
    print("\nABBRUCH: %s" % grund)
    sys.exit(2)


def ruf(pfad, token, methode="GET", rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                        # noqa: BLE001
            return e.code, {}


from backend import chat_sessions as cs                          # noqa: E402
from backend import main as M                                    # noqa: E402

BENUTZER = os.environ.get("CHAT_TESTUSER") or ziele.wert("JARVIS_DEV_TESTUSER")
tok = M.generate_token(BENUTZER)
TITEL = "ZZ Sammelprobe"      # eigenes Material, im Verlauf erkennbar


def liste():
    s, d = ruf("/api/chat/sessions", tok)
    return s, [x["id"] for x in (d.get("sessions") or [])]


meine = []


def aufraeumen():
    """NUR die selbst angelegten Chats entfernen – nichts Vorgefundenes."""
    for sid in list(meine):
        ruf("/api/chat/sessions/" + sid, tok, "DELETE")


# ── 0. Positivkontrolle ─────────────────────────────────────────────────────
abschnitt("0. Positivkontrolle")
st, vorher = liste()
if st != 200:
    abbruch("Sitzungsliste nicht erreichbar (Status %s) – ohne sie ist jede "
            "Messung darunter trivial wahr" % st)
check(True, "Dienst antwortet auf /api/chat/sessions (%d Chats vorgefunden)" % len(vorher))

try:
    # ── 1. Material anlegen ─────────────────────────────────────────────────
    abschnitt("1. Drei eigene Chats anlegen")
    for i in range(3):
        s, d = ruf("/api/chat/sessions", tok, "POST", {"title": "%s %d" % (TITEL, i + 1)})
        if s != 200 or not (d.get("session") or {}).get("id"):
            abbruch("Chat %d liess sich nicht anlegen (Status %s)" % (i + 1, s))
        meine.append(d["session"]["id"])
    check(len(set(meine)) == 3, "drei verschiedene Chats angelegt", str(meine))
    s, da = liste()
    check(all(i in da for i in meine), "alle drei stehen in der Liste")
    check(all(cs._valid(BENUTZER, i) for i in meine),
          "und jeder hat einen Ordner auf der Platte")

    # ── 2. Zwei von drei in EINEM Aufruf loeschen ───────────────────────────
    abschnitt("2. Zwei von drei loeschen")
    weg1, weg2, bleibt = meine[0], meine[1], meine[2]
    s, d = ruf("/api/chat/sessions/delete", tok, "POST", {"ids": [weg1, weg2]})
    check(s == 200, "Endpunkt antwortet mit 200", str(s))
    check(d.get("ok") is True, "ok=True", json.dumps(d))
    check(sorted(d.get("deleted") or []) == sorted([weg1, weg2]),
          "die geloeschten Ids werden BENANNT", json.dumps(d.get("deleted")))
    check((d.get("failed") or []) == [], "kein Fehlschlag gemeldet",
          json.dumps(d.get("failed")))
    for x in (weg1, weg2):
        meine.remove(x)

    check(not cs._valid(BENUTZER, weg1) and not cs._valid(BENUTZER, weg2),
          "⚠ die Ordner der beiden sind von der Platte weg")
    check(cs._valid(BENUTZER, bleibt), "⚠ der Ordner des dritten ist UNANGETASTET")
    s, da = liste()
    check(weg1 not in da and weg2 not in da and bleibt in da,
          "die Liste zeigt genau das", str(len(da)) + " Chats")

    # ── 3. Schranken ────────────────────────────────────────────────────────
    abschnitt("3. Schranken")
    s, d = ruf("/api/chat/sessions/delete", tok, "POST", {"ids": "abc"})
    check(s == 400, "eine Zeichenkette statt einer Liste wird abgewiesen (400)", str(s))
    check(cs._valid(BENUTZER, bleibt),
          "⚠ und dabei wurde NICHTS geloescht (keine Loeschung je Zeichen)")

    s, d = ruf("/api/chat/sessions/delete", tok, "POST", {"ids": []})
    check(s == 400, "eine leere Liste wird abgewiesen (400)", str(s))

    s, d = ruf("/api/chat/sessions/delete", tok, "POST", {})
    check(s == 400, "ein Rumpf ohne ids wird abgewiesen (400)", str(s))

    s, d = ruf("/api/chat/sessions/delete", tok, "POST",
               {"ids": ["x%d" % i for i in range(M._CHAT_DELETE_MAX + 1)]})
    check(s == 400, "mehr als der Deckel (%d) wird abgewiesen (400)" % M._CHAT_DELETE_MAX, str(s))

    # ── 4. Unbekannte Ids: Teilerfolg ───────────────────────────────────────
    abschnitt("4. Unbekannte Id neben einer echten")
    s, d = ruf("/api/chat/sessions/delete", tok, "POST", {"ids": ["gibtsnicht123", bleibt]})
    check(s == 200, "Antwort 200 auch bei Teilfehlschlag", str(s))
    check((d.get("failed") or []) == ["gibtsnicht123"],
          "die unbekannte Id steht in failed", json.dumps(d.get("failed")))
    check((d.get("deleted") or []) == [bleibt],
          "die echte wurde geloescht und benannt", json.dumps(d.get("deleted")))
    check(d.get("ok") is False, "ok=False, weil nicht alles gelang", json.dumps(d))
    if bleibt in meine:
        meine.remove(bleibt)

    # ── 5. Fremdes Material ─────────────────────────────────────────────────
    abschnitt("5. Nichts Vorgefundenes angefasst")
    s, nachher = liste()
    check(sorted(nachher) == sorted(vorher),
          "⚠ der vorgefundene Bestand ist unveraendert (%d Chats)" % len(vorher),
          "vorher %d / nachher %d" % (len(vorher), len(nachher)))
finally:
    aufraeumen()
    print("  (eigene Chats abgeraeumt: %d Rest)" % len(meine))

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
