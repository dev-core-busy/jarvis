#!/usr/bin/env python3
"""Live-Messung des Newsfeed-Skills auf DEV, gegen die ECHTEN Endpunkte des Dienstes.

⚠ DER VORGEFUNDENE ZUSTAND WIRD GEMERKT UND WIEDERHERGESTELLT: Skill-Schalter,
Einstellungen und vorhandene Meldungen gehoeren dem Betreiber. Angelegte
Meldungen werden am Ende geloescht, die Einstellungen auf den gelesenen Wert
gesetzt, und der Skill wird nur dann wieder ausgeschaltet, wenn er vorher aus
war (Register; test_messung_zustand prueft das als Regel).

Aufruf auf dem Server (Token braucht den Hauptschluessel, BSI M5):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_newsfeed_dev.py

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")

BASIS = "https://127.0.0.1"
CTX = ssl._create_unverified_context()
ok = fail = 0


def c(t, b, d=""):
    global ok, fail
    if b:
        ok += 1
        print("  OK   %s" % t)
    else:
        fail += 1
        print("  FAIL %s%s" % (t, ("  [" + str(d) + "]") if d != "" else ""))


def ruf(pfad, token=None, methode="GET", rumpf=None):
    req = urllib.request.Request(BASIS + pfad, method=methode)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if rumpf is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(rumpf).encode()
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
            roh = r.read()
            try:
                return r.status, json.loads(roh.decode())
            except Exception:  # noqa: BLE001
                return r.status, roh.decode(errors="replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:  # noqa: BLE001
            return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


from backend import main as M  # noqa: E402

TOKEN = M.generate_token("jarvis")
FREMD = M.generate_token("fremder.mensch")

# ── Positivkontrolle + vorgefundener Zustand ──────────────────────────────
s, adm = ruf("/api/newsfeed/admin", TOKEN)
if s != 200 or not isinstance(adm, dict) or not adm.get("ok"):
    print("NICHT PRUEFBAR: /api/newsfeed/admin -> %s %r" % (s, adm))
    sys.exit(2)
s, sk = ruf("/api/skills", TOKEN)
# Der Schluessel ist das VERZEICHNIS (name ist der Anzeigename "Newsfeed").
def _ist_nf(x):
    return str(x.get("path") or "").rstrip("/").split("/")[-1] == "newsfeed"


eintrag = [x for x in ((sk or {}).get("skills") or []) if _ist_nf(x)] if isinstance(sk, dict) else []
if not eintrag:
    print("NICHT PRUEFBAR: Skill 'newsfeed' in /api/skills nicht gefunden (%s)" % s)
    sys.exit(2)
VOR_AN = bool(eintrag[0].get("enabled"))
from backend.config import config  # noqa: E402
# Gab es VORHER gar keinen Eintrag in settings.json? Dann ist „aus" allein keine
# Wiederherstellung: Ein-/Ausschalten hinterliesse {'enabled': False,
# 'installed': True}, und der Skill stuende danach unter „Installierte".
VOR_EINTRAG = config.get_skill_states().get("newsfeed")
# Ausblend-Zustand des Messkontos: wird am Ende EXAKT zurueckgestellt (auch
# „kein Eintrag" ist ein Zustand). Der Dienst liest die Datei bei jedem Abruf
# neu, haelt sie also nicht im RAM.
from backend import newsfeed as NF  # noqa: E402
from backend import atomar as ATOMAR  # noqa: E402
_ausg = ATOMAR.lesen(NF.AUSGEBLENDET_DATEI, vorgabe=dict)
VOR_AUSGEBLENDET = _ausg.get("jarvis")
VOR_EINST = dict(adm.get("einstellungen") or {})
VOR_IDS = {e["id"] for e in adm.get("eintraege") or []}
print("vorgefunden: skill an=%r, einstellungen=%r, %d Meldungen" % (VOR_AN, VOR_EINST, len(VOR_IDS)))
angelegt = []

try:
    print("\n1. Rechte")
    c("ohne Token: /api/newsfeed -> 401", ruf("/api/newsfeed")[0] == 401)
    s, _ = ruf("/api/newsfeed/admin", FREMD)
    c("fremdes Konto: Admin-Lesen abgewiesen (401/403)", s in (401, 403), s)
    s, _ = ruf("/api/newsfeed/admin/eintraege", FREMD, "POST", {"titel": "x", "text": "y"})
    c("fremdes Konto: Anlegen abgewiesen (401/403)", s in (401, 403), s)

    print("\n2. Skill aus")
    if VOR_AN:
        ruf("/api/skills/newsfeed/disable", TOKEN, "POST", {})
    s, d = ruf("/api/newsfeed", TOKEN)
    c("Skill aus: /api/newsfeed -> 404 (nicht 403)", s == 404, s)
    s, _ = ruf("/api/newsfeed/ausblenden", TOKEN, "POST", {"stand": "2026-01-01T00:00:00"})
    c("Skill aus: Ausblenden -> 404 (nicht 403)", s == 404, s)
    s, me = ruf("/api/me", TOKEN)
    c("Skill aus: permissions.newsfeed == False",
      s == 200 and (me.get("permissions") or {}).get("newsfeed") is False, me and me.get("permissions"))
    s, d = ruf("/api/newsfeed/admin/eintraege", TOKEN, "POST",
               {"titel": "Probe A", "text": "Pflege geht auch bei ausgeschaltetem Skill."})
    c("Skill aus: Admin kann trotzdem anlegen", s == 200 and d.get("ok"), (s, d))
    if s == 200:
        angelegt.append(d["eintrag"]["id"])

    print("\n3. Anlegen, Reihenfolge, Anzeige")
    for buchst in "BCD":
        time.sleep(1.1)   # Erstellungsdatum hat Sekundenaufloesung
        s, d = ruf("/api/newsfeed/admin/eintraege", TOKEN, "POST",
                   {"titel": "Probe " + buchst, "text": "Satz eins. Satz zwei.",
                    "erstellt": "1999-01-01T00:00:00"})
        if s == 200:
            angelegt.append(d["eintrag"]["id"])
    c("vier Probemeldungen angelegt", len(angelegt) == 4, angelegt)
    s, d = ruf("/api/newsfeed/admin", TOKEN)
    neu = [e for e in d.get("eintraege", []) if e["id"] in angelegt]
    c("mitgeschicktes 'erstellt' NICHT uebernommen",
      all(not e["erstellt"].startswith("1999") for e in neu), [e["erstellt"] for e in neu])

    ruf("/api/skills/newsfeed/enable", TOKEN, "POST", {})
    s, me = ruf("/api/me", TOKEN)
    c("Skill an: permissions.newsfeed == True",
      s == 200 and (me.get("permissions") or {}).get("newsfeed") is True)
    s, d = ruf("/api/newsfeed", TOKEN)
    titel = [e["titel"] for e in (d or {}).get("eintraege", [])] if s == 200 else []
    c("Skill an: /api/newsfeed -> 200", s == 200, s)
    c("genau drei, neueste zuerst: D, C, B", titel[:3] == ["Probe D", "Probe C", "Probe B"] and len(titel) == 3, titel)
    c("Vorgabe/gespeicherte Verweilzeit geliefert", isinstance((d or {}).get("verweil_s"), (int, float)))

    print("\n4. Pruefungen der Eingaben")
    s, d = ruf("/api/newsfeed/admin/eintraege", TOKEN, "POST", {"titel": "", "text": "x"})
    c("leere Ueberschrift -> 400", s == 400, s)
    s, d = ruf("/api/newsfeed/admin/eintraege", TOKEN, "POST", {"titel": "T", "text": "x" * 401})
    c("Text ueber 400 Zeichen -> 400", s == 400, s)
    s, d = ruf("/api/newsfeed/admin/einstellungen", TOKEN, "POST", {"verweil_s": 0.5, "scroll_s": 1})
    c("Verweilzeit 0,5 s -> 400", s == 400, s)
    s, d = ruf("/api/newsfeed/admin/einstellungen", TOKEN, "POST", {"verweil_s": 4, "scroll_s": 1.2})
    c("gueltige Einstellungen -> 200", s == 200 and d.get("einstellungen") == {"verweil_s": 4.0, "scroll_s": 1.2}, d)
    s, d = ruf("/api/newsfeed", TOKEN)
    c("Anzeige liefert die neuen Werte", s == 200 and d.get("verweil_s") == 4.0 and d.get("scroll_s") == 1.2, d)

    print("\n5. Bearbeiten und Loeschen")
    s, d = ruf("/api/newsfeed/admin", TOKEN)
    b = next((e for e in d.get("eintraege", []) if e["titel"] == "Probe B"), None)
    if b:
        time.sleep(1.1)
        s2, d2 = ruf("/api/newsfeed/admin/eintraege", TOKEN, "POST",
                     {"id": b["id"], "titel": "Probe B2", "text": "Korrigiert."})
        c("Bearbeiten -> 200, Datum unveraendert",
          s2 == 200 and d2["eintrag"]["erstellt"] == b["erstellt"] and d2["eintrag"]["titel"] == "Probe B2", d2)
    else:
        c("Probe B auffindbar", False)
    if angelegt:
        s, _ = ruf("/api/newsfeed/admin/eintraege/" + angelegt[0], TOKEN, "DELETE")
        s2, _ = ruf("/api/newsfeed/admin/eintraege/" + angelegt[0], TOKEN, "DELETE")
        c("Loeschen -> 200, zweites Mal -> 404", s == 200 and s2 == 404, (s, s2))
        if s == 200:
            angelegt.pop(0)

    print("\n7. Deaktivieren und Ausblenden")
    time.sleep(1.1)
    s, d = ruf("/api/newsfeed/admin/eintraege", TOKEN, "POST", {"titel": "Probe E", "text": "Zum Deaktivieren."})
    pe = d["eintrag"]["id"] if s == 200 else ""
    if pe:
        angelegt.append(pe)
    s, d = ruf("/api/newsfeed", TOKEN)
    c("neue Meldung steht vorn", s == 200 and d["eintraege"][0]["id"] == pe, s)
    s, d = ruf("/api/newsfeed/admin/eintraege/%s/deaktivieren" % pe, TOKEN, "POST", {})
    c("Deaktivieren -> 200, aktiv=False", s == 200 and d["eintrag"].get("aktiv") is False, d)
    s, d = ruf("/api/newsfeed", TOKEN)
    c("deaktivierte fehlt im Portal", s == 200 and pe not in [e["id"] for e in d["eintraege"]])
    s, d = ruf("/api/newsfeed/admin", TOKEN)
    c("deaktivierte bleibt im Admin-Bereich",
      any(e["id"] == pe and e.get("aktiv") is False for e in d.get("eintraege", [])))
    c("Deaktivieren unbekannt -> 404", ruf("/api/newsfeed/admin/eintraege/gibtsnicht/deaktivieren", TOKEN, "POST", {})[0] == 404)
    s, _ = ruf("/api/newsfeed/admin/eintraege/%s/deaktivieren" % pe, FREMD, "POST", {})
    c("fremdes Konto: Deaktivieren abgewiesen (401/403)", s in (401, 403), s)
    s, d = ruf("/api/newsfeed", TOKEN)
    stand = d.get("stand", "")
    c("Anzeige liefert einen Stand", bool(stand), d.get("stand"))
    s, d = ruf("/api/newsfeed/ausblenden", TOKEN, "POST", {"stand": stand})
    c("Ausblenden -> 200", s == 200, (s, d))
    s, d = ruf("/api/newsfeed", TOKEN)
    c("danach ausgeblendet", s == 200 and d.get("ausgeblendet") is True, d.get("ausgeblendet"))
    c("Ausblenden mit Freitext-Stand -> 400",
      ruf("/api/newsfeed/ausblenden", TOKEN, "POST", {"stand": "morgen"})[0] == 400)
    time.sleep(1.1)
    s, d = ruf("/api/newsfeed/admin/eintraege", TOKEN, "POST", {"id": pe, "titel": "Probe E", "text": "Wieder aktiv."})
    c("Bearbeiten macht wieder aktiv", s == 200 and d["eintrag"].get("aktiv") is True, d)
    s, d = ruf("/api/newsfeed", TOKEN)
    c("nach Bearbeitung: wieder sichtbar und vorn",
      s == 200 and d.get("ausgeblendet") is False and d["eintraege"][0]["id"] == pe, (d.get("ausgeblendet"), [e["id"] for e in d.get("eintraege", [])]))

    print("\n6. Ausgelieferte Seiten")
    s, html = ruf("/portal")
    c("/portal enthaelt die Kachel und das Modul",
      s == 200 and 'id="pt-newsfeed"' in str(html) and "/static/js/newsfeed.js?v=" in str(html), s)
    for pfad in ("/static/js/newsfeed.js", "/static/js/newsfeed_admin.js", "/static/css/newsfeed.css"):
        c(pfad + " -> 200", ruf(pfad)[0] == 200)
    s, html = ruf("/settings")
    c("/settings enthaelt Reiter und Admin-Modul",
      s == 200 and 'id="settings-tab-newsfeed"' in str(html) and "newsfeed_admin.js?v=" in str(html), s)
finally:
    print("\nZuruecksetzen")
    for nid in angelegt:
        ruf("/api/newsfeed/admin/eintraege/" + nid, TOKEN, "DELETE")
    if VOR_EINST:
        ruf("/api/newsfeed/admin/einstellungen", TOKEN, "POST", VOR_EINST)
    _sk_jetzt = ruf("/api/skills", TOKEN)[1] or {}
    _jetzt_an = any(_ist_nf(x) and x.get("enabled") for x in _sk_jetzt.get("skills") or [])
    if _jetzt_an != VOR_AN:
        ruf("/api/skills/newsfeed/" + ("enable" if VOR_AN else "disable"), TOKEN, "POST", {})
    _ausg = ATOMAR.lesen(NF.AUSGEBLENDET_DATEI, vorgabe=dict)
    if VOR_AUSGEBLENDET is None:
        _ausg.pop("jarvis", None)
    else:
        _ausg["jarvis"] = VOR_AUSGEBLENDET
    if NF.AUSGEBLENDET_DATEI.exists() or _ausg:
        ATOMAR.schreiben(NF.AUSGEBLENDET_DATEI, _ausg, modus=0o640)
    c("Ausblend-Zustand des Messkontos wie vorgefunden",
      ATOMAR.lesen(NF.AUSGEBLENDET_DATEI, vorgabe=dict).get("jarvis") == VOR_AUSGEBLENDET)
    if VOR_EINTRAG is None:
        config.remove_skill_state("newsfeed")
        print("  Skill-Eintrag entfernt (vorgefunden: keiner). Der Dienst haelt ihn noch"
              " im RAM – danach als root: systemctl restart jarvis.service")
    s, d = ruf("/api/newsfeed/admin", TOKEN)
    nach_ids = {e["id"] for e in (d or {}).get("eintraege", [])}
    c("Meldungsbestand wie vorgefunden", nach_ids == VOR_IDS, (len(nach_ids), len(VOR_IDS)))
    c("Einstellungen wie vorgefunden", (d or {}).get("einstellungen") == VOR_EINST, (d or {}).get("einstellungen"))
    c("Skill-Schalter wie vorgefunden", bool((d or {}).get("skill_aktiv")) == VOR_AN, (d or {}).get("skill_aktiv"))

print("\nERGEBNIS: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
