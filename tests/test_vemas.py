#!/usr/bin/env python3
"""Waechter fuer den VEMAS.NET-Skill (Client, persoenliche Zugaenge, Katalog,
Rechte-Verdrahtung).

Laeuft OHNE fastapi: was in ``backend/main.py`` und ``backend/agent.py`` geprueft
wird, kommt per ``ast``/Quelltext – ein Import zoege den halben Server nach.
``backend.config`` wird als Stub gesetzt, BEVOR irgendetwas geladen wird: der
echte Import migriert Profile und schreibt die LIVE-``settings.json`` zurueck
(Register-Eintrag, im Projekt schon mehrfach passiert).

SANDKASTEN-SCHRANKE mit Exit 2: die Konten-Module schreiben ``data/
vemas_accounts.json`` und ``data/.vemaskey``. Zeigt einer der Pfade nach dem
Umbiegen noch in den echten Datenbestand, bricht der Lauf ab – "konnte nicht
laufen" muss von "bestanden" unterscheidbar sein.
"""
import ast
import json
import os
import re
import stat
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0
_abschnitt = ""


def abschnitt(t):
    global _abschnitt
    _abschnitt = t
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    """(Beschreibung, Bedingung) – NICHT umgekehrt.

    Der Waechter aus tests/test_jira_vorlagen.py hat genau daran 57 Aufrufe
    vertauscht durchlaufen lassen (eine nicht-leere Zeichenkette ist wahr) und
    "57 OK, 0 FAIL" gemeldet, ohne eine einzige Bedingung auszuwerten. Deshalb
    hier dieselbe harte Abbruchbedingung."""
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen "
              "(erst Beschreibung, dann Bedingung)\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


# ── Stub fuer backend.config (VOR jedem echten Import) ──────────────────────
_SKILL_CFG = {"vemas": {"config": {}}}


class _Cfg:
    def get_skill_states(self):
        return _SKILL_CFG

    def get_setting(self, k, d=""):
        return d

    def save_setting(self, k, v):
        pass


_mod = types.ModuleType("backend.config")
_mod.config = _Cfg()
sys.modules["backend.config"] = _mod

from backend import vemas_client as vc            # noqa: E402
from backend import vemas_analyses as va          # noqa: E402
from backend.vemas_client import VemasClient, VemasError  # noqa: E402

# ── Sandkasten fuer die Konten-Ablage ───────────────────────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="vemas-test-"))
from backend import vemas_accounts as vk          # noqa: E402

vk.DATA_DIR = _TMP
vk.KONTEN_DATEI = _TMP / "vemas_accounts.json"
vk.SCHLUESSEL_DATEI = _TMP / ".vemaskey"

for _n in ("DATA_DIR", "KONTEN_DATEI", "SCHLUESSEL_DATEI"):
    _p = Path(getattr(vk, _n)).resolve()
    if str(ROOT / "data") in str(_p):
        print("\033[31mABBRUCH: %s zeigt in den echten Datenbestand (%s)\033[0m"
              % (_n, _p))
        sys.exit(2)


def _cfg(**kw):
    """Skill-Config setzen (wirkt auf get_vemas_config und vk.skill_config)."""
    _SKILL_CFG["vemas"]["config"] = dict(kw)


# ═══════════════════════════════════════════════════════════════════════════
abschnitt("1. Nur-Lesen: die Wache im Client")
# ═══════════════════════════════════════════════════════════════════════════
for m in ("GET", "get", "HEAD", "OPTIONS"):
    check("%s ist lesend und immer erlaubt" % m,
          vc.assert_read_only(m, read_only=True) == m.upper())

for m in ("POST", "PUT", "PATCH"):
    try:
        vc.assert_read_only(m, read_only=True)
        check("%s wird bei Nur-Lesen abgewiesen" % m, False, "kein Fehler")
    except VemasError as e:
        check("%s wird bei Nur-Lesen abgewiesen" % m, "Nur-Lesen" in str(e))
    try:
        check("%s ist nach Freigabe erlaubt" % m,
              vc.assert_read_only(m, read_only=False) == m)
    except VemasError as e:
        check("%s ist nach Freigabe erlaubt" % m, False, str(e))

# DELETE ist NIE erlaubt – auch nicht nach Freigabe. Ein Loeschvorgang ist
# nicht rueckholbar, und der Agent verarbeitet Fremdtext.
for ro in (True, False):
    try:
        vc.assert_read_only("DELETE", read_only=ro)
        check("DELETE bleibt gesperrt (read_only=%s)" % ro, False, "durchgelassen")
    except VemasError:
        check("DELETE bleibt gesperrt (read_only=%s)" % ro, True)

# Unbekanntes Verb: fail-closed, nicht durchreichen.
try:
    vc.assert_read_only("TRACE", read_only=False)
    check("unbekannte Methode wird abgewiesen", False, "durchgelassen")
except VemasError:
    check("unbekannte Methode wird abgewiesen", True)

check("read_only fehlt in der Config => Vorgabe AN (fail-safe)",
      VemasClient({"base_url": "https://h/api"}).read_only is True)
check("read_only=False schaltet Schreiben frei",
      VemasClient({"base_url": "https://h/api", "read_only": False}).darf_schreiben())
check("read_only='nein' (kein echtes False) bleibt bei Nur-Lesen",
      VemasClient({"base_url": "https://h/api", "read_only": "nein"}).read_only is True)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("2. Pfade: das Modell bestimmt den Pfad, nie den Server")
# ═══════════════════════════════════════════════════════════════════════════
check("normaler Pfad bleibt", vc._pfad_sauber("/projekte") == "projekte")
for boese, wort in (("https://fremd.de/x", "URL"), ("http://fremd.de", "URL"),
                    ("//fremd.de/x", "//"), ("a/../../etc/passwd", "..")):
    try:
        vc._pfad_sauber(boese)
        check("abgewiesen: %s" % boese, False, "durchgelassen")
    except VemasError:
        check("abgewiesen: %s" % boese, True)
try:
    vc._pfad_sauber("")
    check("leerer Pfad abgewiesen", False)
except VemasError:
    check("leerer Pfad abgewiesen", True)

c = VemasClient({"base_url": "https://h/api"})
check("Basis-Pfad bleibt beim Zusammensetzen erhalten",
      c._url("projekte") == "https://h/api/projekte", c._url("projekte"))
check("auch mit fuehrendem Schraegstrich",
      c._url("/projekte") == "https://h/api/projekte", c._url("/projekte"))

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("3. Antworten auspacken (die API ist nicht dokumentiert)")
# ═══════════════════════════════════════════════════════════════════════════
Z = VemasClient.zeilen_aus
check("Liste an der Wurzel", Z([{"a": 1}, {"a": 2}]) == [{"a": 1}, {"a": 2}])
check("value (OData-Stil)", Z({"value": [{"a": 1}]}) == [{"a": 1}])
check("items", Z({"items": [{"a": 1}]}) == [{"a": 1}])
check("data.items (eine Ebene tiefer)", Z({"data": {"items": [{"a": 1}]}}) == [{"a": 1}])
check("records", Z({"records": [{"a": 1}]}) == [{"a": 1}])
# Einzelobjekt als EINE Zeile: ein leeres Ergebnis waere hier die schlechtere
# Antwort, weil das Modell daraus "keine Daten vorhanden" schliesst.
check("Einzelobjekt wird zu einer Zeile", Z({"id": 7, "name": "x"}) == [{"id": 7, "name": "x"}])
check("Unfug ergibt keine Zeilen", Z("text") == [] and Z(None) == [])

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("4. Ressourcen-Zuordnung (die wichtigste Einstellung)")
# ═══════════════════════════════════════════════════════════════════════════
c = VemasClient({"base_url": "https://h/api",
                 "resources": "Projekte = projects\n# Kommentar\nKunden=customers\n\ntimeentries\n"})
r = c.ressourcen()
check("drei Eintraege gelesen, Kommentar und Leerzeile ignoriert", len(r) == 3, r)
check("Name = Pfad wird getrennt",
      {"name": "Projekte", "pfad": "projects"} in r, r)
check("Zeile ohne '=' wird Name und Pfad zugleich",
      {"name": "timeentries", "pfad": "timeentries"} in r, r)
check("Name wird aufgeloest", c.ressource_pfad("Projekte") == "projects")
check("Aufloesung ist gross-/kleinschreibungsblind",
      c.ressource_pfad("projekte") == "projects")
check("ein Pfad bleibt ein Pfad", c.ressource_pfad("customers") == "customers")
check("Unbekanntes wird durchgereicht (der Server entscheidet)",
      c.ressource_pfad("irgendwas") == "irgendwas")
try:
    c.ressource_pfad("")
    check("leere Ressource abgewiesen", False)
except VemasError:
    check("leere Ressource abgewiesen", True)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("5. Anmelde-Token: Speicher, Ablauf, Kennwortwechsel")
# ═══════════════════════════════════════════════════════════════════════════
_ANFRAGEN = []


class _Antwort:
    def __init__(self, status=200, daten=None, text=None, ctype="application/json"):
        self.status_code = status
        self._daten = daten
        self.text = text if text is not None else json.dumps(daten or {})
        self.headers = {"Content-Type": ctype}

    def json(self):
        if self._daten is None:
            raise ValueError("kein JSON")
        return self._daten


def _fake_post(url, **kw):
    _ANFRAGEN.append(("POST", url, kw))
    return _Antwort(200, {"token": "T-123", "expires_in": 3600})


_echt_post, _echt_req = vc.requests.post, vc.requests.request
vc.requests.post = _fake_post
vc.token_cache_leeren()

lc = VemasClient({"base_url": "https://h/api", "auth_kind": "login",
                  "login_path": "auth/login", "username": "u", "password": "p1"})
check("Token wird geholt", lc._login_token() == "T-123")
n1 = len(_ANFRAGEN)
lc._login_token(); lc._login_token()
check("zweiter Aufruf kommt aus dem Speicher (keine neue Anmeldung)",
      len(_ANFRAGEN) == n1, "%d Anmeldungen" % (len(_ANFRAGEN) - n1))

lc2 = VemasClient({"base_url": "https://h/api", "auth_kind": "login",
                   "login_path": "auth/login", "username": "u", "password": "p2"})
lc2._login_token()
check("geaendertes Kennwort erzwingt eine neue Anmeldung", len(_ANFRAGEN) == n1 + 1)

check("im Speicher steht kein Klartext-Kennwort",
      not any("p1" in k or "p2" in k for k in vc._TOKEN_CACHE))

# Der Header traegt Praefix + Token.
h = lc._headers()
check("Authorization-Header gesetzt", h.get("Authorization") == "Bearer T-123", h)

# Token an anderer Stelle im JSON
vc.token_cache_leeren()
vc.requests.post = lambda url, **kw: _Antwort(200, {"data": {"accessToken": "X9"}})
lc3 = VemasClient({"base_url": "https://h/api", "auth_kind": "login",
                   "login_path": "auth/login", "username": "u", "password": "p",
                   "token_json_path": "data.accessToken"})
check("verschachtelter Token-Pfad wird gefunden", lc3._login_token() == "X9")

# Falscher Pfad: die Meldung nennt die TATSAECHLICH vorhandenen Felder – sonst
# muss der Administrator raten.
vc.token_cache_leeren()
vc.requests.post = lambda url, **kw: _Antwort(200, {"jwt": "A", "ablauf": 1})
lc4 = VemasClient({"base_url": "https://h/api", "auth_kind": "login",
                   "login_path": "auth/login", "username": "u", "password": "p",
                   "token_json_path": "token"})
try:
    lc4._login_token()
    check("falscher Token-Pfad meldet die vorhandenen Felder", False, "kein Fehler")
except VemasError as e:
    check("falscher Token-Pfad meldet die vorhandenen Felder",
          "jwt" in str(e) and "ablauf" in str(e), str(e))

# 401 der Anmeldung behaelt den Status – nur so zaehlt der Aussetzer richtig.
vc.token_cache_leeren()
vc.requests.post = lambda url, **kw: _Antwort(401, None, text="nope")
lc5 = VemasClient({"base_url": "https://h/api", "auth_kind": "login",
                   "login_path": "auth/login", "username": "u", "password": "p"})
try:
    lc5._login_token()
    check("401 der Anmeldung wird als Anmeldefehler gemeldet", False)
except VemasError as e:
    check("401 der Anmeldung wird als Anmeldefehler gemeldet", e.status == 401, e.status)

# Anmeldeart login ohne Pfad: Klartext statt Netzwerkfehler
try:
    VemasClient({"base_url": "https://h/api", "auth_kind": "login",
                 "username": "u"})._login_token()
    check("Anmeldeart 'login' ohne Pfad meldet Klartext", False)
except VemasError as e:
    check("Anmeldeart 'login' ohne Pfad meldet Klartext", "login_path" in str(e), str(e))

vc.requests.post = _echt_post

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("6. Anfragen: HTML statt JSON, Fehlertexte, lokale Begrenzung")
# ═══════════════════════════════════════════════════════════════════════════


def _mit_antwort(antwort):
    def f(method, url, **kw):
        _mit_antwort.letzte = (method, url, kw)
        return antwort
    vc.requests.request = f


c = VemasClient({"base_url": "https://h/api"})

# Eine Anmeldeseite als "Ergebnis" durchzureichen waere schlimmer als ein
# Fehler: das Modell wuerde daraus Zahlen erfinden.
_mit_antwort(_Antwort(200, None, text="<html><body>Login</body></html>", ctype="text/html"))
try:
    c.get("projekte")
    check("HTML-Antwort wird als Fehler gemeldet", False, "durchgelassen")
except VemasError as e:
    check("HTML-Antwort wird als Fehler gemeldet", "HTML" in str(e), str(e))

for feld in ("message", "error", "detail", "Message"):
    _mit_antwort(_Antwort(400, {feld: "So nicht"}))
    try:
        c.get("x")
        check("Fehlertext aus '%s'" % feld, False)
    except VemasError as e:
        check("Fehlertext aus '%s'" % feld, "So nicht" in str(e), str(e))

_mit_antwort(_Antwort(200, {"value": [{"i": i} for i in range(500)]}))
check("Rueckgabe wird lokal begrenzt (der Server muss $top nicht kennen)",
      len(c.abfragen("projekte", None, 5)) == 5)
check("beide Begrenzungs-Parameter gehen mit",
      _mit_antwort.letzte[2]["params"].get("$top") == 5
      and _mit_antwort.letzte[2]["params"].get("limit") == 5,
      _mit_antwort.letzte[2]["params"])

# Mandant nur, wenn BEIDE Felder gesetzt sind.
c2 = VemasClient({"base_url": "https://h/api", "mandant": "7", "mandant_param": "m"})
_mit_antwort(_Antwort(200, {"value": []}))
c2.get("x")
check("Mandant wird angehaengt", _mit_antwort.letzte[2]["params"].get("m") == "7")
c3 = VemasClient({"base_url": "https://h/api", "mandant": "7"})
c3.get("x")
check("Mandant ohne Parametername wird NICHT geraten",
      "7" not in str(_mit_antwort.letzte[2]["params"]))

# Die Nur-Lesen-Wache sitzt IM Client, nicht beim Aufrufer.
try:
    c.anfrage("POST", "projekte", None, {"a": 1})
    check("anfrage() setzt Nur-Lesen selbst durch", False, "durchgelassen")
except VemasError as e:
    check("anfrage() setzt Nur-Lesen selbst durch", "Nur-Lesen" in str(e))

vc.requests.request = _echt_req

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("7. Persoenlicher Zugang: Feld-Whitelist und Kennwoerter")
# ═══════════════════════════════════════════════════════════════════════════
_cfg(base_url="https://vemas.firma.de/api", read_only=True)

check("norm_user vereinheitlicht die Tippformen",
      vk.norm_user("NEXUS\\A.Bender") == "a.bender" == vk.norm_user("a.bender@nexus.int"))

info = vk.speichern("nexus\\a.bender",
                    {"auth_kind": "basic", "username": "vuser", "password": "geheim"})
check("Zugang angelegt", info["vorhanden"] is True, info)
check("Kennwort ist gesetzt, wird aber nicht herausgegeben",
      info["passwort_gesetzt"] is True and "password" not in info
      and not any("geheim" in str(v) for v in info.values()), info)

roh = vk.KONTEN_DATEI.read_text(encoding="utf-8")
check("kein Klartext-Kennwort in der Datei", "geheim" not in roh)
check("Datei ist 0640",
      stat.S_IMODE(os.stat(vk.KONTEN_DATEI).st_mode) == 0o640,
      oct(stat.S_IMODE(os.stat(vk.KONTEN_DATEI).st_mode)))
check("Schluesseldatei ist 0600",
      stat.S_IMODE(os.stat(vk.SCHLUESSEL_DATEI).st_mode) == 0o600,
      oct(stat.S_IMODE(os.stat(vk.SCHLUESSEL_DATEI).st_mode)))

# DER KERN: was der Benutzer NICHT setzen darf.
for feld, wert in (("base_url", "https://boese.de"), ("read_only", False),
                   ("verify_ssl", False), ("login_path", "x"),
                   ("token_json_path", "x"), ("hidden_analyses", [])):
    try:
        vk.speichern("a.bender", {feld: wert})
        check("'%s' wird abgewiesen" % feld, False, "angenommen!")
    except vk.VemasKontoFehler as e:
        check("'%s' wird abgewiesen" % feld, feld in str(e), str(e))

# Leeres Kennwortfeld = UNVERAENDERT, nicht loeschen.
vk.speichern("a.bender", {"username": "vuser2", "password": ""})
i2 = vk.zugang_info("a.bender")
check("leeres Kennwortfeld laesst das Kennwort stehen",
      i2["passwort_gesetzt"] is True and i2["username"] == "vuser2", i2)

try:
    vk.speichern("a.bender", {"auth_kind": "kerberos"})
    check("unbekannte Anmeldeart wird abgewiesen", False, "angenommen")
except vk.VemasKontoFehler:
    check("unbekannte Anmeldeart wird abgewiesen", True)

# Kanal-Kennungen sind keine Personen.
for kennung in ("wa:+4915112345", "tg:4711", "api:Kamera"):
    try:
        vk.speichern(kennung, {"auth_kind": "basic", "username": "x", "password": "y"})
        check("kein Zugang fuer '%s'" % kennung, False, "angenommen")
    except vk.VemasKontoFehler:
        check("kein Zugang fuer '%s'" % kennung, True)

# Vollstaendigkeit je Anmeldeart
check("bearer ohne Token ist unvollstaendig",
      vk._vollstaendig({"auth_kind": "bearer"}) is False)
check("bearer mit Token ist vollstaendig",
      vk._vollstaendig({"auth_kind": "bearer", "api_token_enc": "x"}) is True)
check("basic ohne Kennwort ist unvollstaendig",
      vk._vollstaendig({"auth_kind": "basic", "username": "u"}) is False)

# Ohne Serveradresse ist ein eigener Zugang wirkungslos – 400 mit Klartext.
_cfg()
try:
    vk.speichern("neu.person", {"auth_kind": "basic", "username": "u", "password": "p"})
    check("ohne Serveradresse wird abgelehnt", False, "angenommen")
except vk.VemasKontoFehler as e:
    check("ohne Serveradresse wird abgelehnt", "Serveradresse" in str(e), str(e))
_cfg(base_url="https://vemas.firma.de/api", read_only=True)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("8. Anmeldefehler zaehlen – Berechtigungsfehler NICHT")
# ═══════════════════════════════════════════════════════════════════════════
check("HTTP 401 ist ein Anmeldefehler",
      vk.ist_anmeldefehler(VemasError(401, "nope")) is True)
check("HTTP 403 ist KEINER (Logon lief durch, Berechtigung fehlt)",
      vk.ist_anmeldefehler(VemasError(403, "Forbidden")) is False)
check("'not authorized' ist KEINER",
      vk.ist_anmeldefehler(VemasError(0, "insufficient privilege: Not authorized")) is False)
check("'authentication failed' ist einer",
      vk.ist_anmeldefehler(VemasError(0, "authentication failed")) is True)
check("Netzwerkfehler ist KEINER",
      vk.ist_anmeldefehler(VemasError(0, "Netzwerkfehler: timeout")) is False)

for i in range(vk.max_anmeldefehler()):
    vk.merke_ergebnis("a.bender", False, "401", anmeldefehler=True)
i3 = vk.zugang_info("a.bender")
check("nach %d Anmeldefehlern ausgesetzt" % vk.max_anmeldefehler(),
      i3["ausgesetzt"] is True, i3)
check("der Grund wird festgehalten", bool(i3["ausgesetzt_grund"]))

z = vk.aufloesen("a.bender")
check("ausgesetzt => Rueckfall auf den Sammelzugang",
      z["quelle"] == vk.QUELLE_SAMMEL, z["quelle"])
check("... und der Rueckfall wird BEGRUENDET (nicht still)",
      "ausgesetzt" in z["hinweis"], z["hinweis"])
check("der Verbindungstest darf den Aussetzer uebergehen (einziger Rueckweg)",
      vk.aufloesen("a.bender", trotz_aussetzer=True)["quelle"] == vk.QUELLE_PERSOENLICH)

vk.merke_ergebnis("a.bender", True)
check("ein Erfolg loest den Aussetzer auf",
      vk.zugang_info("a.bender")["ausgesetzt"] is False)
check("... und der eigene Zugang gilt wieder",
      vk.aufloesen("a.bender")["quelle"] == vk.QUELLE_PERSOENLICH)

# merke_ergebnis OHNE das Flag zaehlt NICHTS (fail-safe).
vor = vk.zugang_info("a.bender")["anmeldefehler"]
vk.merke_ergebnis("a.bender", False, "irgendein Fehler")
check("Fehler ohne anmeldefehler=True zaehlt nicht mit",
      vk.zugang_info("a.bender")["anmeldefehler"] == vor)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("9. DIE KERNREGEL: geschrieben wird nur mit eigenem Zugang")
# ═══════════════════════════════════════════════════════════════════════════
_cfg(base_url="https://vemas.firma.de/api", read_only=False,
     auth_kind="basic", username="sammel", password="sp")

check("der Sammelzugang bleibt trotz Freigabe nur lesend",
      vk.sammel_client().read_only is True)
check("... auch ueber aufloesen() ohne Benutzer",
      vk.aufloesen("")["client"].read_only is True)

vk.merke_ergebnis("a.bender", True)
zp = vk.aufloesen("a.bender")
check("mit eigenem Zugang gilt die Freigabe",
      zp["quelle"] == vk.QUELLE_PERSOENLICH and zp["client"].darf_schreiben(),
      "%s / read_only=%s" % (zp["quelle"], zp["client"].read_only))
check("der eigene Zugang benutzt die EIGENEN Anmeldedaten",
      zp["client"].user == "vuser2", zp["client"].user)
check("... aber die Adresse des Administrators",
      zp["client"].base == "https://vemas.firma.de/api", zp["client"].base)

_cfg(base_url="https://vemas.firma.de/api", read_only=True)
check("ohne Freigabe darf auch der eigene Zugang nicht schreiben",
      vk.aufloesen("a.bender")["client"].darf_schreiben() is False)

# Inaktiv gesetzt => Rueckfall MIT Hinweis
_cfg(base_url="https://vemas.firma.de/api", read_only=True)
vk.speichern("a.bender", {"aktiv": False})
zi = vk.aufloesen("a.bender")
check("inaktiver Zugang faellt zurueck", zi["quelle"] == vk.QUELLE_SAMMEL)
check("... mit Begruendung", "inaktiv" in zi["hinweis"], zi["hinweis"])
vk.speichern("a.bender", {"aktiv": True})

# Der Benutzer kommt aus dem ContextVar, nie aus einem Argument.
tok = vk.current_vemas_user.set("a.bender")
try:
    check("aufloesen() ohne Argument nimmt den ContextVar",
          vk.aufloesen()["quelle"] == vk.QUELLE_PERSOENLICH)
finally:
    vk.current_vemas_user.reset(tok)
check("ohne ContextVar gilt der Sammelzugang",
      vk.aufloesen()["quelle"] == vk.QUELLE_SAMMEL)

check("loeschen entfernt den Zugang", vk.loeschen("a.bender") is True)
check("... und danach gilt wieder der Sammelzugang",
      vk.aufloesen("a.bender")["quelle"] == vk.QUELLE_SAMMEL)
check("zweites Loeschen meldet 'nichts da'", vk.loeschen("a.bender") is False)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("10. Katalog der Abfragen")
# ═══════════════════════════════════════════════════════════════════════════
check("Kategorien und Abfragen vorhanden",
      len(va.CATEGORIES) >= 5 and len(va.ANALYSES) >= 15,
      "%d/%d" % (len(va.CATEGORIES), len(va.ANALYSES)))
ids = [a["id"] for a in va.ANALYSES]
check("keine doppelte Id", len(ids) == len(set(ids)))
katids = {c["id"] for c in va.CATEGORIES}
check("jede Abfrage haengt an einer bekannten Kategorie",
      all(a["cat"] in katids for a in va.ANALYSES))
fehlend = [(a["id"], lg, f) for a in va.ANALYSES for lg in ("de", "en")
           for f in ("title", "desc", "kpis", "task") if not a[lg].get(f)]
check("alle Felder in DE und EN gefuellt", not fehlend, fehlend[:3])

# Kein Katalogeintrag darf einen SCHREIBENDEN Vorgang beschreiben – er laeuft
# auf Knopfdruck und ohne Rueckfrage.
SCHREIBWORT = re.compile(
    r"\b(lege an|anlegen|erstelle|erzeuge|aendere|ändere|buche|loesche|lösche|"
    r"speichere in vemas|schreibe in vemas|create|update|delete|book)\b", re.I)
treffer = [(a["id"], lg) for a in va.ANALYSES for lg in ("de", "en")
           if SCHREIBWORT.search(a[lg]["task"])]
check("kein Auftrag beschreibt einen Schreibvorgang", not treffer, treffer)

kat = va.catalog("de")
check("Katalog liefert eine Sprache", kat["lang"] == "de" and kat["analyses"])
check("Katalog auf Englisch", va.catalog("en")["lang"] == "en")
check("unbekanntes Kuerzel faellt auf Deutsch zurueck", va.catalog("xx")["lang"] == "de")

erste = va.ANALYSES[0]["id"]
k2 = va.catalog("de", hidden=[erste])
check("ausgeblendete Abfrage fehlt im Katalog",
      erste not in [a["id"] for a in k2["analyses"]])
check("is_hidden erkennt sie", va.is_hidden(erste, [erste]) is True)
check("admin_catalog zeigt sie WEITERHIN (sonst nie wieder einblendbar)",
      erste in [a["id"] for a in va.admin_catalog("de", hidden=[erste])["analyses"]])
check("hidden=None heisst 'nichts ausgeblendet', nicht 'nichts sichtbar'",
      len(va.catalog("de")["analyses"]) == len(va.ANALYSES))
check("unbekannte Id wird verworfen statt geraten",
      va.normalize_hidden(["gibtsnicht", erste]) == [erste])
check("kommagetrennter Text wird angenommen",
      va.normalize_hidden("%s,gibtsnicht" % erste) == [erste])

# Kategorien ohne sichtbare Abfrage verschwinden mit.
alle_ids = [a["id"] for a in va.ANALYSES]
leer = va.catalog("de", hidden=alle_ids)
check("alles ausgeblendet => keine Kategorie mehr",
      leer["categories"] == [] and leer["analyses"] == [])

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("11. build_task: Reihenfolge IST die Semantik")
# ═══════════════════════════════════════════════════════════════════════════
t = va.build_task(analysis_id=erste, question="Nur Standort Krefeld",
                  tool_id="excel", instructions="Immer Euro", lang="de")
check("Vorspann steht vorn", t.startswith("Du wertest ein VEMAS.NET-System"))
p_vorl = t.index("AUSWERTUNG:")
p_frage = t.index("Zusaetzliche Frage")
p_werk = t.index("Zielwerkzeug:")
p_anw = t.index("Persoenliche Anweisungen")
check("Vorlage vor Frage vor Zielwerkzeug vor Anweisungen",
      p_vorl < p_frage < p_werk < p_anw,
      (p_vorl, p_frage, p_werk, p_anw))
check("der Vorspann verlangt zuerst die Ressourcen-Ermittlung",
      "vemas_resources" in t and t.index("vemas_resources") < p_vorl)
check("... und verbietet ausdruecklich das Raten von Pfaden",
      "RATE KEINE PFADE" in t)
check("die Quellenangabe ist als HINWEIS gekennzeichnet",
      "nicht garantiert" in t)
check("weder Vorlage noch Frage => leerer Auftrag", va.build_task() == "")
check("Frage allein genuegt", va.build_task(question="Wie viele Projekte?") != "")
check("englischer Auftrag ist englisch",
      va.build_task(analysis_id=erste, lang="en").startswith("You are analysing"))
check("lange Anweisungen werden gedeckelt",
      len(va.build_task(question="x", instructions="A" * 9000)) < 9000)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("12. Rechte-Verdrahtung in main.py (per Quelltext)")
# ═══════════════════════════════════════════════════════════════════════════
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(MAIN)


def _funktion(name):
    for n in ast.walk(baum):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(MAIN, n) or ""
    return ""


f = _funktion("_user_may_use_vemas")
check("_user_may_use_vemas existiert", bool(f))
check("leer = niemand (auch keine lokalen Admins)",
      "if not users_raw and not grp:" in f and "return False" in f, f[:200])
check("kein Admin-Bypass", "_is_admin_user" not in f and "ALLOWED_USERS" not in f)
check("Benutzerliste ODER Gruppe (beide Wege getrennt geprueft)",
      "users_raw and plain in" in f and "grp and _member_of_any_group" in f)

g = _funktion("require_vemas_access")
check("require_vemas_access existiert und antwortet 403",
      "status_code=403" in g and "_user_may_use_vemas" in g)

# Jeder /api/vemas-Endpunkt haengt an einer der beiden richtigen Schranken.
routen = []
for n in ast.walk(baum):
    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for d in n.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
            continue
        if d.func.attr not in ("get", "post", "put", "delete", "patch"):
            continue
        pfad = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else ""
        if not str(pfad).startswith("/api/vemas"):
            continue
        quelle = ast.get_source_segment(MAIN, n) or ""
        deps = set(re.findall(r"Depends\((\w+)\)", quelle.split("\n\n")[0] or quelle))
        routen.append((d.func.attr, pfad, deps))

check("VEMAS-Endpunkte gefunden", len(routen) >= 12, len(routen))
ohne = [(m, p) for m, p, d in routen
        if not (d & {"require_vemas_access", "require_local_auth"})]
check("jeder VEMAS-Endpunkt haengt an einer Schranke", not ohne, ohne)

admin_pflicht = {"/api/vemas/admin/accounts", "/api/vemas/analyses/catalog"}
falsch = [(m, p) for m, p, d in routen
          if p in admin_pflicht and "require_local_auth" not in d]
check("Admin-Endpunkte haengen an require_local_auth", not falsch, falsch)
# Und die Gegenrichtung: der Benutzer-Bereich darf NICHT auf Admin gehoben
# werden – sonst kaeme kein Benutzer mehr an seinen eigenen Zugang.
zu_eng = [(m, p) for m, p, d in routen
          if p in ("/api/vemas/account", "/api/vemas/ask", "/api/vemas/status")
          and "require_vemas_access" not in d]
check("der Benutzer-Bereich bleibt bei require_vemas_access", not zu_eng, zu_eng)

check("permissions.vemas prueft Freigabe UND aktiven Skill",
      '"vemas": _user_may_use_vemas(user) and _skill_active("vemas")' in MAIN)
check("/vemas antwortet ohne aktiven Skill mit 404",
      'if not _skill_active("vemas"):' in MAIN and "status_code=404" in MAIN)
check("der Bereichs-Lauf ist unprivilegiert und traegt vemas=True",
      '"privileged": False,' in MAIN and '"vemas": True}' in MAIN)
check("Freitext geht durch die Jailbreak-Pruefung",
      '_sec_inspect_user(question, user, "vemas")' in MAIN)
check("die Freigabefelder werden gespeichert",
      'config.save_setting("vemas_allowed_users"' in MAIN
      and 'config.save_setting("vemas_allowed_group"' in MAIN)
check("... und gelesen", '"vemas_users": config.get_setting' in MAIN)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("13. Rechte-Verdrahtung in agent.py")
# ═══════════════════════════════════════════════════════════════════════════
AG = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
check("Gate auf das Praefix vemas_",
      'name.startswith("vemas_")' in AG
      and "getattr(self, '_current_user_vemas', True)" in AG)
check("Gate meldet Klartext statt eines leeren Ergebnisses",
      "VEMAS-Zugriff ist fuer deinen Benutzer nicht freigeschaltet" in AG)
check("actor_scope nimmt vemas entgegen und stellt es zurueck",
      "vemas: bool = False" in AG and '"_current_user_vemas"' in AG)
check("run_task_headless reicht actor['vemas'] durch",
      'vemas=bool(actor.get("vemas", False))' in AG)
check("Sub-Agenten erben die Freigabe (sonst waere spawn ein Umweg)",
      AG.count("_current_user_vemas = getattr(") >= 3,
      AG.count("_current_user_vemas = getattr("))
check("ContextVar wird je Werkzeug-Aufruf gesetzt",
      "from backend.vemas_accounts import current_vemas_user" in AG)
check("... und im finally zurueckgenommen",
      "_vcv.reset(_v_token)" in AG)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("14. Skill: Manifest, Werkzeuge, Schutz der Identitaet")
# ═══════════════════════════════════════════════════════════════════════════
SK = json.loads((ROOT / "skills" / "vemas" / "skill.json").read_text(encoding="utf-8"))
SRC = (ROOT / "skills" / "vemas" / "main.py").read_text(encoding="utf-8")
namen = re.findall(r'return "(vemas_[a-z_]+)"', SRC)
check("Manifest und Code nennen dieselben Werkzeuge",
      set(namen) == set(SK["tools"]), set(namen) ^ set(SK["tools"]))
check("alle Werkzeuge tragen das Praefix (sonst greift das Gate nicht)",
      all(n.startswith("vemas_") for n in SK["tools"]))
check("Skill ist per Vorgabe AUS", SK.get("enabled") is False)
check("Nur-Lesen ist die Vorgabe im Manifest",
      SK["config_schema"]["read_only"]["default"] is True)
check("die Hilfe nennt nur vorhandene Werkzeuge",
      {t["name"] for t in SK["help"]["tools"]} <= set(SK["tools"]))

# DER BENUTZER DARF NIE EIN WERKZEUG-ARGUMENT SEIN – sonst koennte das Modell
# waehlen, mit wessen Zugangsdaten es arbeitet (und bei freigeschaltetem
# Schreiben, in wessen Namen es bucht).
verboten = re.findall(r'"(benutzer|user|username|zugang|account|password|kennwort|token)"\s*:\s*\{',
                      SRC)
check("kein Werkzeug nimmt Benutzer/Zugangsdaten als Parameter",
      not verboten, verboten)
check("... und auch keine Serveradresse",
      not re.findall(r'"(base_url|server|host|url)"\s*:\s*\{', SRC))

# Die Schreibregel steht im Werkzeug, nicht nur im Modul-Docstring.
w = SRC[SRC.index("class VemasWriteTool"):]
check("vemas_write verlangt den persoenlichen Zugang",
      "QUELLE_PERSOENLICH" in w and "darf_schreiben()" in w)
check("... und begruendet die Absage im Klartext",
      "Mein VEMAS-Zugang" in w)
check("get_tools liefert vemas_write IMMER (Freigabe wird zur Laufzeit geprueft)",
      "VemasWriteTool()," in SRC)

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("15. Ablage: die Dateien sind fuer die Shell zu")
# ═══════════════════════════════════════════════════════════════════════════
SB = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
for datei in ("data/vemas_accounts.json", "data/.vemaskey"):
    check("%s steht in _APP_DENY_REL" % datei, '"%s"' % datei in SB)
check("beide Dateien in PRIVATE_FILES bzw. -_STRENG",
      "data/vemas_accounts.json" in SB.split("PRIVATE_FILES =")[1].split("PRIVATE_FILE_MODE")[0]
      and "data/.vemaskey" in SB.split("PRIVATE_FILES_STRENG =")[1].split(")")[0])
check("das Shell-Muster trifft beide",
      re.search(r"vemas_accounts\\\.json", SB) and re.search(r"\\\.vemaskey", SB))

# ═══════════════════════════════════════════════════════════════════════════
abschnitt("16. Oberflaeche: Freigabe, Kachel, Reiter")
# ═══════════════════════════════════════════════════════════════════════════
PORTAL = (ROOT / "frontend" / "portal.html").read_text(encoding="utf-8")
check("Portal-Kachel ist per Vorgabe versteckt",
      'class="pt-card hidden" id="pt-card-vemas"' in PORTAL)
check("... und wird nur bei permissions.vemas eingeblendet",
      "d.permissions && d.permissions.vemas" in PORTAL)

SET = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
check("Reiter-Knopf startet versteckt (Skill-abhaengig)",
      'id="settings-tab-btn-vemas" style="display:none;"' in SET)
check("Berechtigungsblock startet versteckt",
      'id="sec-sub-vemas" style="display:none;"' in SET)
check("beide Freigabefelder sagen 'leer = niemand'",
      SET.count("Leer = niemand") >= 2
      and 'id="vemas-allowed-users"' in SET and 'id="vemas-allowed-group"' in SET)
check("Reiter-Panel vorhanden", 'id="settings-tab-vemas"' in SET)
check("vemas.js wird eingebunden", "/static/js/vemas.js?v=" in SET)

APP = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
check("Reiter-Sichtbarkeit haengt am Skill-Zustand",
      "updateVemasTabVisibility" in APP and "s.dir_name === 'vemas'" in APP)
check("... und wird beim Oeffnen der Einstellungen gerufen",
      "await updateVemasTabVisibility();" in APP)
check("Klick auf den Reiter ruft den Manager",
      "window.VemasManager.onShow()" in APP)

SKJS = (ROOT / "frontend" / "js" / "skills.js").read_text(encoding="utf-8")
check("Zahnrad des Skills springt in den Reiter", "vemas:             'vemas'," in SKJS)
check("Skill-Toggle zieht die Reiter-Sichtbarkeit nach",
      SKJS.count("window.updateVemasTabVisibility()") >= 3)

LP = (ROOT / "frontend" / "js" / "ldap_picker.js").read_text(encoding="utf-8")
check("AD-Picker kennt beide Freigabefelder",
      "'vemas-allowed-users'" in LP and "'vemas-allowed-group'" in LP)

# i18n: beide Sprachen, keine Luecke.
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
de_teil, en_teil = I18N.split("    en: {", 1)
de_keys = set(re.findall(r"'(vemas\.[^']*)':", de_teil))
en_keys = set(re.findall(r"'(vemas\.[^']*)':", en_teil))
check("VEMAS-Schluessel in DE und EN vollstaendig",
      de_keys == en_keys and len(de_keys) > 60,
      "DE %d / EN %d, Differenz %s" % (len(de_keys), len(en_keys),
                                       sorted(de_keys ^ en_keys)[:5]))

gebraucht = set()
for datei in ("frontend/vemas.html", "frontend/js/vemas_portal.js", "frontend/js/vemas.js"):
    t = (ROOT / datei).read_text(encoding="utf-8")
    gebraucht |= set(re.findall(
        r'data-i18n(?:-html|-title|-placeholder|-tabfill)?="(vemas\.[^"]*)"', t))
    gebraucht |= set(re.findall(r"T\('(vemas\.[^']*)'", t))
check("jeder benutzte Schluessel ist hinterlegt",
      gebraucht <= de_keys, sorted(gebraucht - de_keys)[:5])

# Die Seite selbst: Titelleiste und Symbole.
SEITE = (ROOT / "frontend" / "vemas.html").read_text(encoding="utf-8")
check("Seite bindet icons.js als erstes Skript ein",
      SEITE.index("icons.js") < SEITE.index("i18n.js"))
check("Loeschknopf fuehrt KEIN × (Muelleimer kommt aus icons.js)",
      "×" not in SEITE.split('id="vm-acc-del"')[1][:400]
      and "&#10005;" not in SEITE.split('id="vm-acc-del"')[1][:400])
VP = (ROOT / "frontend" / "js" / "vemas_portal.js").read_text(encoding="utf-8")
check("... und bekommt ihn zur Laufzeit gesetzt",
      "JarvisIcons.trash()" in VP)
check("Schliessen-Knopf des Dialogs fuehrt ein × (kein Muelleimer)",
      "&#10005;" in SEITE and "jv-ico-trash" not in SEITE)
check("die Seite prueft die Freigabe clientseitig (fail-closed)",
      "me.permissions && me.permissions.vemas" in VP and "toPortal()" in VP)
check("die Serveradresse ist in der Kachel nur ANSICHT",
      'id="vm-acc-server" type="text" readonly' in SEITE)
check("... und wird nicht mitgesendet",
      "base_url" not in VP.split("function accCollect")[1].split("}")[0])

# ═══════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════
# Der VORGABE-Produktname darf nicht im Pulldown stehen (2026-08-31)
# ══════════════════════════════════════════════════════════════════════════
# Im Eintrag ``inline`` stand "Jarvis (direkt hier)" – auf einer weiss
# gelabelten Installation also ein Name, den das Branding nicht erreicht.
# Gemessen auf ECHT: der Assistent heisst dort `Nexerius`, im Pulldown stand
# `Jarvis`. Geprueft wird die REGEL ueber ALLE Werkzeuge und beide Sprachen –
# ein kuenftiger Eintrag mit Produktnamen faellt damit von selbst auf.
print("\n── Kein Vorgabe-Produktname in den Zielwerkzeugen ──")
for _lg in ("de", "en"):
    _namen = [b["name"] for b in va.catalog(_lg)["tools"]]
    check(f"catalog({_lg}) nennt nirgends den Vorgabenamen",
          not any("jarvis" in n.lower() for n in _namen), str(_namen))
    check(f"catalog({_lg}) liefert fuer jedes Werkzeug einen Namen",
          all(n.strip() for n in _namen), str(_namen))
check("und der Auftragstext ebenfalls nicht (de)",
      "Jarvis" not in va.build_task(analysis_id=None, question="x", tool_id="inline"))
check("und der Auftragstext ebenfalls nicht (en)",
      "Jarvis" not in va.build_task(analysis_id=None, question="x", tool_id="inline",
                                    lang="en"))
# Positivkontrolle: die Namen unterscheiden sich je Sprache, der Helfer wirkt
# also wirklich (sonst waere die Null oben aus dem falschen Grund gruen).
check("der Name des Inline-Eintrags ist uebersetzt",
      va.catalog("de")["tools"][0]["name"] != va.catalog("en")["tools"][0]["name"],
      va.catalog("en")["tools"][0]["name"])
# Eigennamen bleiben in beiden Sprachen gleich – sonst waere aus dem Helfer
# eine Uebersetzungspflicht fuer Power BI und Excel geworden.
check("Eigennamen bleiben unveraendert",
      va.catalog("de")["tools"][1]["name"] == va.catalog("en")["tools"][1]["name"])

print()
print("=" * 62)
farbe = "\033[32m" if fail == 0 else "\033[31m"
print("%s%d OK, %d FAIL\033[0m" % (farbe, ok, fail))
print("=" * 62)
sys.exit(0 if fail == 0 else 1)
