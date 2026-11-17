#!/usr/bin/env python3
"""Waechter: eigener Zugang (PAT) fuer Loesungsarchiv und Confluence-Einbindung.

Vorgabe des Betreibers (2026-11-17): beide Dienste bekommen im Admin-Bereich
einen eigenen PAT, der "dediziert und unabhaengig von den Einstellungen
'gemeinsamer Jira/Confluence Zugang'" benutzt wird (``backend/dienst_zugang``).

Gemessen wird AUSGEFUEHRT, nicht am Quelltext:
  1. ``dienst_client`` beider Konten-Module: mit Dienst-Token wird GENAU er
     gesendet, ohne ihn der gemeinsame; die Adresse kommt immer aus der
     Skill-Config; der Jira-Client bleibt Nur-Lesen.
  2. ``zustand`` nennt den geltenden Zugang und gibt keinen Token heraus.
  3. ``speichern``/``loeschen`` schreiben NUR das eine Feld.
  4. Adresswechsel: ohne ``bei_adresswechsel`` sperrt die Umleitungs-Pruefung
     das Verbindungsformular dauerhaft (Positivkontrolle der Sperre), mit ihm
     nicht – und der Dienst-Token geht dabei NICHT an die neue Adresse.
  5. Der Lauf des Loesungsarchivs holt die Tickets mit DEMSELBEN Client wie die
     Liste (``ticket_laden(client=…)`` ausgefuehrt), der Confluence-Abgleich
     nimmt den Dienstzugang (AST, weil ``_lauf`` den ganzen Bestand braucht).

``backend.config`` nur als Attrappe (der echte Import schreibt settings.json).
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if not isinstance(name, str):
        print("ABBRUCH: check(name, bedingung) mit vertauschten Argumenten")
        sys.exit(2)
    if bed:
        OK += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} – {info}")


# ── Attrappe fuer backend.config (VOR jedem backend-Import) ──
STATES: dict = {}
_cfg = types.ModuleType("backend.config")


class _Config:
    def get_skill_states(self):
        return STATES

    def get_setting(self, *_a, **_k):
        return None


_cfg.config = _Config()
sys.modules["backend.config"] = _cfg

try:
    from backend import dienst_zugang as dz
    from backend import jira_accounts as ja
    from backend import confluence_accounts as ca
    from backend import secret_reveal as sr
    from backend import jira_assist
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Import gescheitert: {type(e).__name__}: {e}")
    sys.exit(2)

if sys.modules.get("backend.config") is not _cfg:
    print("ABBRUCH: backend.config ist nicht die Attrappe – der Test wuerde echte Einstellungen lesen")
    sys.exit(2)


class SM:
    """Wie ``SkillManager.update_skill_config``: flacher Merge in den Bestand."""
    def __init__(self):
        self.aufrufe = []

    def update_skill_config(self, name, data):
        self.aufrufe.append((name, dict(data)))
        STATES.setdefault(name, {}).setdefault("config", {}).update(data)
        return True


def setze(jira=None, confluence=None):
    STATES.clear()
    if jira is not None:
        STATES["jira"] = {"enabled": True, "config": dict(jira)}
    if confluence is not None:
        STATES["confluence"] = {"enabled": True, "config": dict(confluence)}


print("\n1. Clients der Konten-Module")
setze(jira={"base_url": "https://jira.beispiel.de/", "api_token": "GEMEINSAM"},
      confluence={"base_url": "https://cf.beispiel.de", "api_token": "CF-GEMEINSAM"})
c = dz.client("loesungsarchiv")
check("Positivkontrolle: ohne Dienst-Token ein konfigurierter Client", c.configured, vars(c))
check("ohne Dienst-Token: gemeinsamer Token, quelle sammel",
      c.token == "GEMEINSAM" and c.zugang["quelle"] == "sammel", (c.token, getattr(c, "zugang", None)))
STATES["jira"]["config"]["loesungsarchiv_api_token"] = "  DIENST-JIRA  "
c = dz.client("loesungsarchiv")
check("⚠ mit Dienst-Token: GENAU er wird gesendet (getrimmt)",
      c.token == "DIENST-JIRA" and c._headers()["Authorization"] == "Bearer DIENST-JIRA", c.token)
check("mit Dienst-Token: quelle dienst", c.zugang["quelle"] == "dienst", c.zugang)
check("Adresse kommt aus der Skill-Config (ohne Schraegstrich am Ende)",
      c.base == "https://jira.beispiel.de", c.base)
check("⚠ Jira-Dienstclient ist Nur-Lesen", c.schreiben is False, c.schreiben)
STATES["jira"]["config"]["api_token"] = ""
check("⚠ unabhaengig vom gemeinsamen Zugang: geht auch ohne ihn",
      dz.client("loesungsarchiv").configured and dz.client("loesungsarchiv").token == "DIENST-JIRA")
STATES["jira"]["config"]["loesungsarchiv_api_token"] = None
check("Feld None (nach Adresswechsel) zaehlt als nicht gesetzt",
      dz.client("loesungsarchiv").zugang["quelle"] == "sammel")

cc = dz.client("confluence_einbindung")
check("Confluence ohne Dienst-Token: gemeinsamer", cc.token == "CF-GEMEINSAM" and cc.zugang["quelle"] == "sammel",
      cc.token)
STATES["confluence"]["config"]["einbindung_api_token"] = "DIENST-CF"
cc = dz.client("confluence_einbindung")
check("⚠ Confluence mit Dienst-Token: GENAU er",
      cc.token == "DIENST-CF" and cc._headers()["Authorization"] == "Bearer DIENST-CF"
      and cc.zugang["quelle"] == "dienst", cc.token)
check("Confluence-Adresse aus der Skill-Config", cc.base == "https://cf.beispiel.de", cc.base)
check("⚠ Dienst-Token des einen Dienstes wirkt nicht im anderen",
      dz.client("loesungsarchiv").token != "DIENST-CF")

print("\n2. Zustand fuer die Oberflaeche")
setze(jira={"base_url": "https://jira.beispiel.de", "api_token": "GEMEINSAM",
            "loesungsarchiv_api_token": "GEHEIM-123"})
z = dz.zustand("loesungsarchiv")
check("quelle dienst, token_gesetzt", z["quelle"] == "dienst" and z["token_gesetzt"], z)
check("⚠ kein Token in der Antwort", "GEHEIM-123" not in json.dumps(z) and "GEMEINSAM" not in json.dumps(z), z)
check("Kennung fuer das Auge = skill:feld", z["kennung"] == "jira:loesungsarchiv_api_token", z["kennung"])
check("das Feld ist ein Geheimfeld (Maskierung, Tresor, Auge)",
      sr._geheimfeld_name("loesungsarchiv_api_token") and sr._geheimfeld_name("einbindung_api_token"))
masken, gesetzt = sr.skill_config_maskiert(STATES["jira"]["config"])
check("⚠ GET /api/skills/jira/config maskiert den Dienst-Token",
      masken.get("loesungsarchiv_api_token") == "" and "loesungsarchiv_api_token" in gesetzt, (masken, gesetzt))
setze(jira={"base_url": "https://jira.beispiel.de", "api_token": "GEMEINSAM"})
check("ohne eigenen: quelle sammel", dz.zustand("loesungsarchiv")["quelle"] == "sammel")
setze(jira={"base_url": "https://jira.beispiel.de"})
check("ohne jeden Token: quelle leer", dz.zustand("loesungsarchiv")["quelle"] == "")
setze(jira={})
check("ohne Adresse: adresse_gesetzt False", dz.zustand("loesungsarchiv")["adresse_gesetzt"] is False)
try:
    dz.zustand("fremd")
    check("unbekannter Dienst wird abgewiesen", False, "kein Fehler")
except dz.DienstFehler:
    check("unbekannter Dienst wird abgewiesen", True)

print("\n3. Speichern und Entfernen")
setze(jira={"base_url": "https://jira.beispiel.de", "api_token": "GEMEINSAM", "max_results": 50})
sm = SM()
for wert, was in (("", "leer"), ("   ", "nur Leerraum"), ("kurz", "zu kurz"),
                  ("mit leerzeichen drin", "Leerzeichen"), ("x" * 600, "zu lang"), (None, "None")):
    try:
        dz.speichern("loesungsarchiv", wert, sm)
        check(f"Token {was} wird abgewiesen", False, "angenommen")
    except dz.DienstFehler:
        check(f"Token {was} wird abgewiesen", True)
check("abgewiesene Eingaben schreiben nichts", sm.aufrufe == [], sm.aufrufe)
z = dz.speichern("loesungsarchiv", "  NeuerToken_ABC123  ", sm)
check("⚠ gespeichert wird NUR das eine Feld",
      sm.aufrufe == [("jira", {"loesungsarchiv_api_token": "NeuerToken_ABC123"})], sm.aufrufe)
check("gemeinsamer Token und uebrige Felder unberuehrt",
      STATES["jira"]["config"]["api_token"] == "GEMEINSAM" and STATES["jira"]["config"]["max_results"] == 50)
check("Rueckgabe nennt den neuen Zustand", z["quelle"] == "dienst", z)
sm2 = SM()
dz.loeschen("loesungsarchiv", sm2)
check("Entfernen schreibt nur das Feld (leer)",
      sm2.aufrufe == [("jira", {"loesungsarchiv_api_token": ""})], sm2.aufrufe)
check("danach gilt der gemeinsame Zugang", dz.zustand("loesungsarchiv")["quelle"] == "sammel")
setze(confluence={"api_token": "CF"})
try:
    dz.speichern("confluence_einbindung", "Token_ohne_Adresse", SM())
    check("ohne Adresse wird abgewiesen (keine Skill-Anlage nebenbei)", False, "angenommen")
except dz.DienstFehler:
    check("ohne Adresse wird abgewiesen (keine Skill-Anlage nebenbei)", True)

print("\n4. Adresswechsel")
alt = {"base_url": "https://jira.beispiel.de", "api_token": "GEMEINSAM",
       "loesungsarchiv_api_token": "DIENST"}
rumpf = {"base_url": "https://jira-neu.beispiel.de", "api_token": "NEU"}
# Positivkontrolle: OHNE den Schritt sperrt die Umleitungs-Pruefung – genau die
# Sackgasse, die bei_adresswechsel aufloest. Ohne diese Kontrolle waere die
# Pruefung unten trivial.
check("Positivkontrolle: ohne den Schritt sperrt die Umleitungs-Pruefung den Umzug",
      bool(sr.umgeleitete_geheimnisse(dict(rumpf), dict(alt))), "keine Sperre – Pruefung trivial")
b = dict(rumpf)
weg = dz.bei_adresswechsel("jira", b, dict(alt))
check("⚠ Umzug entfernt den Dienst-Token", weg == ["loesungsarchiv"] and b.get("loesungsarchiv_api_token") is None
      and "loesungsarchiv_api_token" in b, (weg, b))
check("⚠ danach sperrt die Umleitungs-Pruefung NICHT mehr",
      sr.umgeleitete_geheimnisse(b, dict(alt)) == [], sr.umgeleitete_geheimnisse(b, dict(alt)))
behalten = sr.leere_geheimfelder_behalten(b, dict(alt))
check("⚠ der alte Dienst-Token geht NICHT an die neue Adresse",
      behalten.get("loesungsarchiv_api_token") is None, behalten)
b2 = dict(rumpf, base_url="https://jira.beispiel.de/")
check("gleiche Adresse (nur Schraegstrich): nichts entfernt",
      dz.bei_adresswechsel("jira", b2, dict(alt)) == [] and "loesungsarchiv_api_token" not in b2, b2)
b3 = {"api_token": "NEU"}
check("Rumpf ohne Adresse: nichts entfernt", dz.bei_adresswechsel("jira", b3, dict(alt)) == [], b3)
b4 = dict(rumpf, loesungsarchiv_api_token="NEUER-DIENST")
check("im selben Rumpf neu eingegeben: bleibt", dz.bei_adresswechsel("jira", b4, dict(alt)) == []
      and b4["loesungsarchiv_api_token"] == "NEUER-DIENST", b4)
b5 = dict(rumpf)
check("ohne gespeicherten Dienst-Token: nichts zu tun",
      dz.bei_adresswechsel("jira", b5, {"base_url": "https://jira.beispiel.de"}) == [], b5)
b6 = {"base_url": "https://cf-neu.beispiel.de", "api_token": "N"}
check("anderer Skill wird nicht angefasst",
      dz.bei_adresswechsel("confluence", b6, dict(alt)) == [] and len(b6) == 2, b6)
b7 = {"base_url": "https://cf-neu.beispiel.de", "api_token": "N"}
check("Confluence: Umzug entfernt den Einbindungs-Token",
      dz.bei_adresswechsel("confluence", b7, {"base_url": "https://cf.beispiel.de",
                                               "einbindung_api_token": "D"}) == ["confluence_einbindung"]
      and b7.get("einbindung_api_token", "x") is None, b7)

# Der Schritt muss in update_skill_config VOR der Umleitungs-Pruefung stehen –
# danach waere die Sperre schon gefallen (AST, Aufruf-Reihenfolge).
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(MAIN)
usc = next((n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "update_skill_config"), None)
if usc is None:
    print("ABBRUCH: update_skill_config nicht gefunden")
    sys.exit(2)


def _zeilen(knoten, attr):
    return sorted(n.lineno for n in ast.walk(knoten) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == attr)


z_aw, z_um = _zeilen(usc, "bei_adresswechsel"), _zeilen(usc, "umgeleitete_geheimnisse")
check("update_skill_config ruft bei_adresswechsel VOR der Umleitungs-Pruefung",
      bool(z_aw) and bool(z_um) and z_aw[0] < z_um[0], (z_aw, z_um))

print("\n5. Die Dienste benutzen den Zugang")


class FakeJira:
    base = "https://jira.beispiel.de"
    zugang = {"quelle": "dienst"}

    def __init__(self):
        self.geholt = []

    def get_issue(self, key, *a, **k):
        self.geholt.append(key)
        return {"key": key, "fields": {"summary": "S", "comment": {"comments": []}}}


def _verboten(*_a, **_k):
    raise AssertionError("gemeinsamer Zugang benutzt")


_alt_client = jira_assist._client
jira_assist._client = _verboten
try:
    fj = FakeJira()
    t = asyncio.run(jira_assist.ticket_laden("PRJA-1", "", client=fj))
    check("⚠ ticket_laden(client=…) benutzt GENAU den uebergebenen Client",
          fj.geholt == ["PRJA-1"] and t.get("key") == "PRJA-1", (fj.geholt, t))
except AssertionError as e:
    check("⚠ ticket_laden(client=…) benutzt GENAU den uebergebenen Client", False, str(e))
except Exception as e:  # noqa: BLE001
    check("⚠ ticket_laden(client=…) benutzt GENAU den uebergebenen Client", False, f"{type(e).__name__}: {e}")
finally:
    jira_assist._client = _alt_client

LA = ast.parse((ROOT / "backend" / "loesungsarchiv.py").read_text(encoding="utf-8"))
f_client = next((n for n in LA.body if isinstance(n, ast.FunctionDef) and n.name == "_client"), None)
f_lauf = next((n for n in LA.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_lauf"), None)
if f_client is None or f_lauf is None:
    print("ABBRUCH: loesungsarchiv._client/_lauf nicht gefunden")
    sys.exit(2)


def _ruft(knoten, attr, wert=None):
    for n in ast.walk(knoten):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
                and (wert is None or (n.args and isinstance(n.args[0], ast.Constant)
                                      and n.args[0].value == wert))):
            return n
    return None


check("⚠ loesungsarchiv._client nimmt den Dienstzugang",
      _ruft(f_client, "client", "loesungsarchiv") is not None
      and not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "JiraClient"
                  for n in ast.walk(f_client)))
tl = _ruft(f_lauf, "ticket_laden")
check("⚠ _lauf reicht den Client an ticket_laden durch",
      tl is not None and any(k.arg == "client" for k in tl.keywords), ast.dump(tl) if tl else "kein Aufruf")

CFA = ast.parse((ROOT / "backend" / "confluence_abgleich.py").read_text(encoding="utf-8"))
f_cl = next((n for n in CFA.body if isinstance(n, ast.FunctionDef) and n.name == "_lauf"), None)
check("⚠ Confluence-Abgleich nimmt den Dienstzugang der Einbindung",
      f_cl is not None and _ruft(f_cl, "client", "confluence_einbindung") is not None)
f_akt = next((n for n in baum.body if isinstance(n, ast.FunctionDef) and n.name == "_cfb_aktiv"), None)
check("_cfb_aktiv misst 'konfiguriert' am Dienstzugang (sonst fehlt der Container ohne Sammelzugang)",
      f_akt is not None and _ruft(f_akt, "client", "confluence_einbindung") is not None)

print(f"\nErgebnis: {OK} OK, {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
