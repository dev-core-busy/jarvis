#!/usr/bin/env python3
"""Login-Caches ueberdauern einen Dienst-Neustart (Fix 2026-08-10).

DER GEMELDETE FEHLER
--------------------
"warum kann ich auf dev nach einer Bild Generierung kein LLM Profil mehr
auswaehlen?" – gemessen lieferte ``GET /api/llm/profiles`` fuer den angemeldeten
Benutzer ``profiles: []`` bei gesetztem ``active_id``. Nicht die Bildgenerierung
war die Ursache, sondern die Dienst-Neustarts danach.

DIE URSACHE
-----------
Vier Berechtigungs-Caches in ``main.py`` werden AUSSCHLIESSLICH beim AD-Login
gefuellt – die Tokens sind dagegen zustandslose HMAC-Zeichenketten und
ueberleben jeden Neustart:

| Cache                      | Was ohne ihn verloren geht                        |
|----------------------------|---------------------------------------------------|
| ``_user_group_dns_cache``  | LLM-Profile mit ``allowed_group``, SAP-Zugriff per Gruppe, gruppenspezifische Wissens-Editoren |
| ``_admin_access_cache``    | **Administrator-Status per AD-Gruppe** (Umleitung von /settings aufs Portal) |
| ``_internet_access_cache`` | Internet-Zugriff (curl/wget "Zugriff verweigert") |
| ``_knowledge_editor_cache``| Wissens-Editor-Rechte                             |

Nach ``systemctl restart`` (jeder Deploy, das Auto-Update um 03:00) ist der
Prozess neu, die dicts sind leer, der Benutzer aber weiter angemeldet. Die
Fehlermeldungen behaupten dabei eine fehlende Berechtigung, die es gibt.
Selbstheilung nur bedingt: ``_revalidate_ad_groups_once`` braucht ein
Service-Konto, und der Loop schlief ZUERST (Standard 10 Minuten).

    python3 tests/test_ad_cache.py
"""

import ast
import json
import os
import re
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  ✓ {text}")
    else:
        _fail += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n=== {t} ===")


MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SANDBOX_SRC = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
MAIN_LINES = MAIN_SRC.splitlines(keepends=True)

# ─── Die beiden Funktionen per Quelltext holen ───────────────────────────────
# `backend.main` importieren hiesse fastapi + den halben Kern laden (und
# backend.config schreibt die Live-settings.json zurueck).
_baum = ast.parse(MAIN_SRC)
_holen = {}
for n in _baum.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in (
            "_load_ad_caches", "_save_ad_caches", "_norm_login", "_touch_ad_caches",
            "_ldap_escape", "_ad_rollen_aktualisieren", "_ad_cache_fehlt",
            "_ad_cache_nachladen", "_ad_cache_nachladen_falls_noetig",
            "_revalidate_ad_groups_once", "_member_of_any_group", "_group_cn_prefix"):
        _holen[n.name] = "".join(MAIN_LINES[n.lineno - 1:n.end_lineno])

for _p in ("_load_ad_caches", "_save_ad_caches", "_norm_login", "_touch_ad_caches",
           "_ad_rollen_aktualisieren", "_ad_cache_nachladen_falls_noetig",
           "_revalidate_ad_groups_once"):
    if _p not in _holen:
        print(f"ABBRUCH: {_p} nicht in main.py gefunden")
        sys.exit(2)

_TMP = Path(tempfile.mkdtemp(prefix="jarvis-adcache-"))


def _mit_suche(ergebnis):
    """Attrappe einer _check_*_with_conn: sie stellt – wie das Original – eine
    EIGENE LDAP-Suche und setzt damit conn.entries neu."""
    def _f(user, conn, base_dn):
        try:
            conn.search(search_base=base_dn,
                        search_filter=f"(sAMAccountName={user})",
                        attributes=["memberOf"])
        except Exception:  # noqa: BLE001
            pass
        return ergebnis
    return _f


_ns = {
    "json": json, "os": os, "time": time, "Path": Path,
    "_AD_CACHE_FILE": _TMP / "ad_cache.json",
    "_AD_CACHE_TTL": 86400.0,
    "_AD_CACHE_MIN_INTERVAL": 5.0,
    "_ad_cache_last_write": 0.0,
    "_AD_CACHE_TOUCH_INTERVAL": 300.0,
    "_ad_cache_last_touch": 0.0,
    "_user_group_dns_cache": {}, "_knowledge_editor_cache": {},
    "_internet_access_cache": {}, "_admin_access_cache": {},
    "_ad_seen_users": {},
    # --- fuer Abschnitt 8 (Nachladen) --------------------------------------
    "asyncio": __import__("asyncio"),
    "sys": sys,
    "ALLOWED_USERS": {"jarvis"},
    "_revoked_logins": {},
    "_AD_NACHLADE_SPERRE": 60.0,
    "_ad_nachlade_versuch": {},
    "_save_revocations": lambda: None,
    # Die drei Rechte-Pruefungen sind hier Attrappen: sie gehoeren einer anderen
    # Ebene (LDAP-Filter gegen die konfigurierten Listen) und haben ihre eigenen
    # Tests. WICHTIG: sie SUCHEN, so wie die echten – sonst waere die Pruefung
    # "memberOf stammt aus der eigenen Suche" trivial wahr, weil conn.entries
    # gar nicht mehr angefasst wuerde. Genau darin besteht der Fallstrick.
    "_check_knowledge_edit_permission_with_conn": _mit_suche(True),
    "_check_internet_access_with_conn": _mit_suche(True),
    "_check_admin_with_conn": _mit_suche(False),
}
exec(compile("".join(_holen.values()), "<main-teile>", "exec"), _ns)  # noqa: S102

# SANDKASTEN-SCHRANKE: schreibt der Test versehentlich in die echte Ablage, waere
# das ein Datenverlust an Rechte-Informationen. (Lehre aus test_log_retention.py,
# wo genau das bei einer Gegenprobe passiert ist.)
if not str(_ns["_AD_CACHE_FILE"]).startswith(str(_TMP)):
    print("ABBRUCH: Cache-Pfad zeigt nicht ins Wegwerf-Verzeichnis")
    sys.exit(2)

laden = _ns["_load_ad_caches"]
speichern = _ns["_save_ad_caches"]


def leeren():
    for k in ("_user_group_dns_cache", "_knowledge_editor_cache",
              "_internet_access_cache", "_admin_access_cache", "_ad_seen_users"):
        _ns[k].clear()
    _ns["_ad_cache_last_write"] = 0.0
    _ns["_ad_cache_last_touch"] = 0.0


DN = "CN=DP-AI,OU=Gruppen,DC=nexus,DC=int"


def befuellen(ts=None):
    ts = time.time() if ts is None else ts
    _ns["_user_group_dns_cache"]["andreas.bender"] = [DN]
    _ns["_knowledge_editor_cache"]["andreas.bender"] = True
    _ns["_internet_access_cache"]["andreas.bender"] = True
    _ns["_admin_access_cache"]["andreas.bender"] = False
    _ns["_ad_seen_users"]["andreas.bender"] = ts


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("1. Round-Trip: ein Neustart verliert die Rechte nicht mehr")

leeren()
befuellen()
speichern(force=True)
pruefe(_ns["_AD_CACHE_FILE"].exists(), "Datei wird geschrieben")

leeren()   # = Prozess-Neustart
pruefe(_ns["_user_group_dns_cache"] == {}, "nach dem 'Neustart' sind die Caches leer")
laden()
pruefe(_ns["_user_group_dns_cache"].get("andreas.bender") == [DN],
       "Gruppen-DNs wiederhergestellt (LLM-Profile/SAP/Wissensgruppen)")
pruefe(_ns["_knowledge_editor_cache"].get("andreas.bender") is True,
       "Wissens-Editor-Recht wiederhergestellt")
pruefe(_ns["_internet_access_cache"].get("andreas.bender") is True,
       "Internet-Zugriff wiederhergestellt")
pruefe(_ns["_admin_access_cache"].get("andreas.bender") is False,
       "Admin-Flag wiederhergestellt – auch der Wert False (kein Falsyness-Fehler)")
pruefe("andreas.bender" in _ns["_ad_seen_users"],
       "Aktivitaets-Zeitstempel mit – die Revalidierung sieht den Benutzer wieder")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("2. Grenzen: was NICHT wiederhergestellt wird (fail-closed)")

# Zu alt
leeren()
befuellen(ts=time.time() - 86400 - 60)
speichern(force=True)
leeren()
laden()
pruefe(_ns["_user_group_dns_cache"] == {} and _ns["_admin_access_cache"] == {},
       "Eintrag aelter als 24 h wird verworfen (Obergrenze fuer alte Rechte)")

# Kein Zeitstempel = kein Altersbeweis
_ns["_AD_CACHE_FILE"].write_text(json.dumps({"users": {
    "boeser.nutzer": {"admin": True, "group_dns": [DN]}}}), encoding="utf-8")
leeren()
laden()
pruefe(_ns["_admin_access_cache"] == {},
       "Eintrag OHNE Zeitstempel wird verworfen, nicht geraten")

# Falsche Typen werden ignoriert, nicht uebernommen
_ns["_AD_CACHE_FILE"].write_text(json.dumps({"users": {
    "x.y": {"ts": time.time(), "admin": "ja", "internet": 1,
            "group_dns": "CN=alles"}}}), encoding="utf-8")
leeren()
laden()
pruefe("x.y" not in _ns["_admin_access_cache"],
       "admin: 'ja' (String) wird NICHT als True uebernommen")
pruefe("x.y" not in _ns["_internet_access_cache"],
       "internet: 1 (int) wird NICHT als True uebernommen")
pruefe("x.y" not in _ns["_user_group_dns_cache"],
       "group_dns als String wird verworfen (Liste erwartet)")

# Beschaedigte Datei darf den Start nicht verhindern
_ns["_AD_CACHE_FILE"].write_text("{kaputt", encoding="utf-8")
leeren()
try:
    laden()
    pruefe(True, "beschaedigte Datei: kein Absturz")
except Exception as e:  # noqa: BLE001
    pruefe(False, "beschaedigte Datei: kein Absturz", str(e))
pruefe(_ns["_admin_access_cache"] == {},
       "beschaedigte Datei → leere Caches (Verhalten wie vor dem Fix)")

# Fehlende Datei ist der Normalfall beim ersten Start
_ns["_AD_CACHE_FILE"].unlink(missing_ok=True)
leeren()
laden()
pruefe(_ns["_admin_access_cache"] == {}, "fehlende Datei: still und leer")

# Namen werden normalisiert – sonst haette derselbe Mensch je Tippform einen
# eigenen Eintrag (dieselbe Klasse wie die Anzeige-/Vergleichsfehler vom 10.08.).
_ns["_AD_CACHE_FILE"].write_text(json.dumps({"users": {
    "NEXUS\\\\Andreas.Bender": {"ts": time.time(), "admin": True}}}), encoding="utf-8")
leeren()
laden()
pruefe(_ns["_admin_access_cache"].get("andreas.bender") is True,
       "Schluessel werden ueber _norm_login normalisiert")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("3. Schreiben: Modus, Atomarität, Drosselung")

leeren()
befuellen()
speichern(force=True)
modus = oct(os.stat(_ns["_AD_CACHE_FILE"]).st_mode & 0o777)
pruefe(modus == "0o640", f"Dateimodus 0640 (ist {modus})")

pruefe("os.replace" in _holen["_save_ad_caches"],
       "atomar geschrieben (os.replace) – kein halber Stand bei Absturz")
pruefe(not list(_TMP.glob("*.tmp")), "keine .tmp-Datei bleibt liegen")

# Drosselung: ein zweiter Aufruf ohne force darf nicht schreiben
_ns["_admin_access_cache"]["neu.person"] = True
_ns["_ad_seen_users"]["neu.person"] = time.time()
speichern()                      # gedrosselt (< 5 s seit dem letzten Schreiben)
inhalt = json.loads(_ns["_AD_CACHE_FILE"].read_text())
pruefe("neu.person" not in inhalt["users"],
       "Schreib-Drosselung greift (Login-Bursts)")
speichern(force=True)
inhalt = json.loads(_ns["_AD_CACHE_FILE"].read_text())
pruefe("neu.person" in inhalt["users"], "force=True schreibt sofort")

# Alte Eintraege wandern nicht mit in die Datei
_ns["_ad_seen_users"]["alt.person"] = time.time() - 86400 - 10
_ns["_admin_access_cache"]["alt.person"] = True
speichern(force=True)
inhalt = json.loads(_ns["_AD_CACHE_FILE"].read_text())
pruefe("alt.person" not in inhalt["users"],
       "abgelaufene Eintraege werden beim Schreiben nicht mitgenommen")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("4. Die Datei ist gegen Shell und filesystem gesperrt")

# SCHREIBBAR waere der eigentliche Gau: {"admin": true} = Administratorrechte.
_deny = re.search(r"_APP_DENY_REL = \((.*?)\n\)", SANDBOX_SRC, re.S)
pruefe(_deny is not None and '"data/ad_cache.json"' in _deny.group(1),
       "data/ad_cache.json steht in _APP_DENY_REL (filesystem-Tool)")
_pf = re.search(r"PRIVATE_FILES = \((.*?)\)", SANDBOX_SRC, re.S)
pruefe(_pf is not None and "data/ad_cache.json" in _pf.group(1),
       "steht in PRIVATE_FILES → harden_data_dirs setzt 0640")
_ss = re.search(r"SHELL_SECRET_PATHS = re\.compile\((.*?)\n\)", SANDBOX_SRC, re.S)
pruefe(_ss is not None and "ad_cache" in _ss.group(1),
       "steht in SHELL_SECRET_PATHS → Shell-Zugriff gesperrt")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("5. Verdrahtung in main.py")

pruefe("async def startup_ad_caches" in MAIN_SRC and "_load_ad_caches()" in MAIN_SRC,
       "Startup-Hook laedt die Caches")
# Synchron im Hook, NICHT als Task: ein Request eine Zehntelsekunde zu frueh
# saehe leere Caches und bekaeme eine falsche Absage.
_hook = MAIN_SRC[MAIN_SRC.index("async def startup_ad_caches"):]
_hook = _hook[:_hook.index("@app.on_event", 10)]
pruefe("create_task" not in _hook, "der Hook laedt synchron (kein create_task)")

# Beide Fuellstellen sichern
_i_login = MAIN_SRC.index("_user_group_dns_cache[plain_key] = _fetch_user_group_dns(")
_login = MAIN_SRC[_i_login:_i_login + 1200]
pruefe("_save_ad_caches(force=True)" in _login,
       "nach dem AD-Login wird gespeichert")
_reval = MAIN_SRC[MAIN_SRC.index("def _revalidate_ad_groups_once"):]
_reval = _reval[:_reval.index("async def _ad_revalidation_loop")]
pruefe("_save_ad_caches(force=True)" in _reval,
       "nach der Revalidierung wird gespeichert")

# Erster Revalidierungslauf frueh, nicht erst nach dem Intervall
_loop = MAIN_SRC[MAIN_SRC.index("async def _ad_revalidation_loop"):]
_loop = _loop[:_loop.index("@app.on_event")]
pruefe("erster" in _loop and "asyncio.sleep(45)" in _loop,
       "der erste Revalidierungslauf kommt nach 45 s statt nach 10 Minuten")
pruefe(_loop.count("await asyncio.sleep") == 2,
       "der regulaere Intervall-Schlaf bleibt daneben bestehen")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("6. Das aktive LLM-Profil verschwindet nicht mehr aus dem Umschalter")

_ep = MAIN_SRC[MAIN_SRC.index('@app.get("/api/llm/profiles")'):]
_ep = _ep[:_ep.index('@app.post("/api/llm/profiles/{profile_id}/activate")')]
pruefe("aktiv_id" in _ep and 'p.get("id") != aktiv_id' in _ep,
       "das aktive Profil wird nicht herausgefiltert")
pruefe('eintrag["locked"] = True' in _ep,
       "ein nicht waehlbares Profil wird als locked gekennzeichnet")
pruefe("api_key" not in _ep and "session_key" not in _ep,
       "die Antwort enthaelt keine Zugangsdaten")
# Die Berechtigung selbst bleibt unangetastet
_act = MAIN_SRC[MAIN_SRC.index('@app.post("/api/llm/profiles/{profile_id}/activate")'):]
pruefe("_may_use_profile" in _act[:900],
       "activate prueft weiter _may_use_profile (gezeigt wird mehr, erlaubt nicht)")

PS = (ROOT / "frontend" / "js" / "profile_switcher.js").read_text(encoding="utf-8")
pruefe("p.locked" in PS, "das Frontend kennt das locked-Feld")
pruefe("waehlbar < 2" in PS,
       "bedienbar erst ab zwei WAEHLBAREN Profilen (ein gesperrtes zaehlt nicht)")
pruefe("profile.pulldown_locked" in PS, "eigener Tooltip fuer den gesperrten Fall")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
pruefe(I18N.count("'profile.pulldown_locked'") == 2,
       "i18n-Schluessel in DE und EN vorhanden")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("7. Der Zeitstempel altert nicht mehr im laufenden Betrieb (2026-08-25)")

# GEMELDET: "die Kachel Wissen wird oft nicht angezeigt, dann hilft nur logout
# und wieder login". Ursache dahinter: `_save_ad_caches` wurde AUSSCHLIESSLICH
# beim Login und bei der Revalidierung gerufen. Ein Benutzer bleibt aber bis zu
# 30 Tage angemeldet (Token-Lebensdauer) – `_ad_seen_users` wird pro Request im
# RAM aufgefrischt, die DATEI nie. Ihr Eintrag altert, `_load_ad_caches`
# verwirft ihn nach 24 h, und weil nur der Login die Caches fuellt, ist er der
# einzige Ausweg.
touch = _ns["_touch_ad_caches"]


def datei_ts():
    """Zeitstempel des Eintrags, wie er auf Platte steht (nicht die mtime:
    zwei Schreibvorgaenge im selben Millisekunden-Tick sind daran nicht zu
    unterscheiden – Lehre aus tests/test_user_sessions.py)."""
    roh = json.loads(_ns["_AD_CACHE_FILE"].read_text(encoding="utf-8"))
    return roh["users"]["andreas.bender"]["ts"]


# ── Der gemeldete Fall, Ende zu Ende ─────────────────────────────────────────
# OHNE Auffrischung: Login vor 25 h, seitdem durchgehend gearbeitet, kein
# Neu-Login. Die Datei traegt den alten Zeitstempel.
leeren()
_alt = time.time() - 25 * 3600
_ns["_AD_CACHE_FILE"].write_text(json.dumps({"users": {"andreas.bender": {
    "ts": _alt, "group_dns": [DN], "kb_editor": True,
    "internet": True, "admin": False}}}), encoding="utf-8")
laden()   # = Dienst-Neustart
pruefe(_ns["_knowledge_editor_cache"] == {},
       "ALT: nach 25 h ohne Neu-Login ist das Wissens-Recht beim Neustart weg "
       "(genau das gemeldete Bild)")

# MIT Auffrischung: derselbe Verlauf, aber ein Request unterwegs hat den
# Zeitstempel durchgereicht.
leeren()
befuellen(ts=_alt)                       # Rechte stammen vom Login vor 25 h
_ns["_ad_seen_users"]["andreas.bender"] = time.time()   # ... aber er arbeitet JETZT
touch("andreas.bender")
pruefe(_ns["_AD_CACHE_FILE"].exists() and (time.time() - datei_ts()) < 5,
       "NEU: ein Request unterwegs frischt den Zeitstempel auf")
leeren()
laden()   # = Dienst-Neustart
pruefe(_ns["_knowledge_editor_cache"].get("andreas.bender") is True,
       "NEU: dieselbe Sitzung ueberlebt den Neustart – kein Logout/Login noetig")
pruefe(_ns["_user_group_dns_cache"].get("andreas.bender") == [DN],
       "NEU: auch die Gruppen-DNs (gruppenspezifische Wissens-Editoren) sind da")

# ── Drosselung: der Aufruf liegt auf dem heissen Pfad ────────────────────────
leeren()
befuellen()
touch("andreas.bender")
_erster = datei_ts()
_ns["_ad_seen_users"]["andreas.bender"] = time.time() + 999   # naechster Request
touch("andreas.bender")
pruefe(datei_ts() == _erster,
       "innerhalb der Frist wird NICHT erneut geschrieben (jeder Request wuerde sonst schreiben)")
_ns["_ad_cache_last_touch"] = time.time() - 301               # Frist abgelaufen
touch("andreas.bender")
pruefe(datei_ts() != _erster, "nach Ablauf der Frist wird wieder geschrieben")

# ── Wer in keinem Cache steht, loest keinen Schreibvorgang aus ───────────────
leeren()
_ns["_AD_CACHE_FILE"].unlink(missing_ok=True)
touch("fremder.benutzer")
pruefe(not _ns["_AD_CACHE_FILE"].exists(),
       "ein Benutzer ohne Cache-Eintrag schreibt nichts (es gaebe nichts zu sichern)")
touch("")
pruefe(not _ns["_AD_CACHE_FILE"].exists(), "leerer Name schreibt nichts")

# ── Verdrahtung: ohne Aufruf im Request-Pfad ist die Funktion toter Code ─────
_lsa = _holen_quelle = None
for n in ast.parse(MAIN_SRC).body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_login_still_allowed":
        _lsa = "".join(MAIN_LINES[n.lineno - 1:n.end_lineno])
pruefe(_lsa is not None and "_touch_ad_caches(" in _lsa,
       "_login_still_allowed ruft _touch_ad_caches – die Funktion haengt am Request-Pfad")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("8. Rechte werden beim ERSTEN Request nachgeladen (2026-08-25)")

# GEMESSEN auf einem Produktivsystem: nach einem Neustart erfasst die
# periodische Revalidierung einen Benutzer fruehestens nach 45 s – und NUR,
# wenn der frische Prozess ihn ueberhaupt kennt. Bei drei von achtzehn
# Neustarts wurde der betroffene Benutzer bis zum naechsten Neustart GAR NICHT
# erfasst, einmal dauerte es 1194 s. So lange fehlte ihm die Wissen-Kachel,
# und weil sonst nur der Login die Caches fuellt, blieb ihm nur logout+login.
rollen = _ns["_ad_rollen_aktualisieren"]
fehlt = _ns["_ad_cache_fehlt"]
nachladen_wenn = _ns["_ad_cache_nachladen_falls_noetig"]
import asyncio as _aio


class ConnAttrappe:
    """Minimale ldap3-Verbindung. `folge` legt fest, was jede Suche liefert:
    eine Liste von Eintraegen oder eine Exception, die geworfen wird."""

    def __init__(self, folge):
        self.folge = list(folge)
        self.suchen = 0
        self.entries = []
        self.unbound = False

    def search(self, **kw):
        self.suchen += 1
        naechste = self.folge.pop(0) if self.folge else []
        if isinstance(naechste, Exception):
            raise naechste
        self.entries = naechste

    def unbind(self):
        self.unbound = True


class EintragAttrappe:
    """Ein LDAP-Eintrag mit memberOf (ldap3-Zugriffsform: e["memberOf"].values)."""

    def __init__(self, dns):
        self._dns = list(dns)

    def __contains__(self, k):
        return k == "memberOf"

    def __getitem__(self, k):
        return type("W", (), {"values": list(self._dns)})()


DN2 = "CN=DP-ALLE,OU=Global,DC=nexus,DC=int"

# ── Erfolgsfall: alle vier Caches werden gesetzt ─────────────────────────────
leeren()
c = ConnAttrappe([[EintragAttrappe([DN, DN2])], [], [], []])
status, dns = rollen(c, "DC=nexus,DC=int", "andreas.bender")
pruefe(status == "ok", "gefundener Benutzer -> status 'ok'", str(status))
pruefe(dns == [DN, DN2], "die Gruppen-DNs kommen zurueck")
pruefe(_ns["_user_group_dns_cache"].get("andreas.bender") == [DN, DN2],
       "Gruppen-DNs im Cache")
pruefe(_ns["_knowledge_editor_cache"].get("andreas.bender") is True,
       "Wissens-Editor-Recht im Cache (das ist die Wissen-Kachel)")
pruefe(_ns["_admin_access_cache"].get("andreas.bender") is False,
       "auch der Wert False wird gesetzt (kein Falsyness-Fehler)")

# ── DER FALLSTRICK: memberOf muss VOR den drei Pruefungen gelesen werden ─────
# Jede _check_*_with_conn macht ihre EIGENE conn.search() und setzt damit
# conn.entries neu. Wer danach noch daraus liest, bekommt eine fremde Suche.
leeren()
c = ConnAttrappe([[EintragAttrappe([DN])],          # unsere Suche
                  [EintragAttrappe(["CN=FALSCH"])], # die der Editor-Pruefung
                  [EintragAttrappe(["CN=FALSCH"])],
                  [EintragAttrappe(["CN=FALSCH"])]])
status, dns = rollen(c, "DC=nexus,DC=int", "andreas.bender")
pruefe(dns == [DN] and _ns["_user_group_dns_cache"]["andreas.bender"] == [DN],
       "memberOf stammt aus der EIGENEN Suche, nicht aus einer der Pruefungen", str(dns))
pruefe(c.suchen == 4,
       "... obwohl die Rechte-Pruefungen danach dreimal SELBST gesucht und "
       "conn.entries ueberschrieben haben", "Suchen: %d" % c.suchen)
pruefe(c.entries and c.entries[0]["memberOf"].values == ["CN=FALSCH"],
       "... conn.entries traegt am Ende wirklich das Ergebnis der LETZTEN Suche "
       "(waere memberOf spaeter gelesen worden, stuende CN=FALSCH im Cache)")

# ── Fehlerfall: NICHTS wird angetastet ──────────────────────────────────────
leeren()
befuellen()
c = ConnAttrappe([RuntimeError("LDAP weg")])
status, dns = rollen(c, "DC=nexus,DC=int", "andreas.bender")
pruefe(status == "fehler", "Suchfehler -> status 'fehler'", str(status))
pruefe(_ns["_knowledge_editor_cache"].get("andreas.bender") is True,
       "der bestehende Cache bleibt UNANGETASTET (kein Recht wegschreiben)")

leeren()
befuellen()
c = ConnAttrappe([[]])
status, dns = rollen(c, "DC=nexus,DC=int", "andreas.bender")
pruefe(status == "nicht_gefunden", "leeres Ergebnis -> status 'nicht_gefunden'", str(status))
pruefe(_ns["_knowledge_editor_cache"].get("andreas.bender") is True,
       "auch dann bleibt der Cache unangetastet")
pruefe(status != "fehler",
       "'nicht gefunden' und 'Fehler' sind UNTERSCHIEDLICH – nur aus dem ersten "
       "darf ein Aufrufer eine Sitzung widerrufen")

# ── _ad_cache_fehlt ─────────────────────────────────────────────────────────
leeren()
pruefe(fehlt("andreas.bender") is True, "leerer Cache -> Rollen fehlen")
befuellen()
pruefe(fehlt("andreas.bender") is False, "gefuellter Cache -> nichts nachzuladen")
leeren()
_ns["_admin_access_cache"]["andreas.bender"] = False
pruefe(fehlt("andreas.bender") is False,
       "EIN Eintrag genuegt – auch wenn er False ist (Falsyness-Falle)")

# ── Das Nachladen: wann laeuft es, wann nicht ───────────────────────────────
_geladen = []
_ns["_ad_cache_nachladen"] = lambda plain: (_geladen.append(plain), True)[1]


def cfg(bind_user="nexus\\dienst", server="ldaps://dc", domain="nexus.int"):
    _ns["config"] = type("C", (), {"get_setting": staticmethod(
        lambda k, d=None: {"ad_server": server, "ad_domain": domain,
                           "ad_bind_user": bind_user}.get(k, d))})()


cfg()
leeren(); _geladen.clear(); _ns["_ad_nachlade_versuch"].clear()
_aio.run(nachladen_wenn("nexus\\andreas.bender"))
pruefe(_geladen == ["andreas.bender"],
       "fehlende Rollen -> es wird nachgeladen (der gemeldete Fall)", str(_geladen))

_geladen.clear()
_aio.run(nachladen_wenn("nexus\\andreas.bender"))
pruefe(_geladen == [],
       "zweiter Request kurz danach loest KEINEN zweiten LDAP-Bind aus (Drosselung)")

_ns["_ad_nachlade_versuch"]["andreas.bender"] = time.time() - 61
_geladen.clear()
_aio.run(nachladen_wenn("nexus\\andreas.bender"))
pruefe(_geladen == ["andreas.bender"], "nach Ablauf der Sperre wird erneut versucht")

leeren(); befuellen(); _geladen.clear(); _ns["_ad_nachlade_versuch"].clear()
_aio.run(nachladen_wenn("nexus\\andreas.bender"))
pruefe(_geladen == [],
       "im Normalfall (Cache vorhanden) passiert NICHTS – kein Preis pro Request")

leeren(); _geladen.clear(); _ns["_ad_nachlade_versuch"].clear()
_aio.run(nachladen_wenn("jarvis"))
pruefe(_geladen == [], "lokale Konten werden nicht im Verzeichnis gesucht")

leeren(); _geladen.clear(); _ns["_ad_nachlade_versuch"].clear()
cfg(bind_user="")
_aio.run(nachladen_wenn("nexus\\andreas.bender"))
pruefe(_geladen == [],
       "ohne Service-Konto kein Versuch – eine Gruppenpruefung ohne Benutzerkennwort "
       "ist gar nicht moeglich")
cfg(server="", domain="")
leeren(); _geladen.clear(); _ns["_ad_nachlade_versuch"].clear()
_aio.run(nachladen_wenn("nexus\\andreas.bender"))
pruefe(_geladen == [], "ohne Verzeichnis-Konfiguration ebenfalls nicht")
cfg()

# ── Ein Netzhaenger darf KEINE Sitzung kosten ───────────────────────────────
# (die Revalidierung hat den Widerruf, das Nachladen nicht)
_ns["config"] = type("C", (), {"get_setting": staticmethod(
    lambda k, d=None: {"ad_allowed_users": "", "ad_allowed_group": DN2}.get(k, d))})()
_ns["ldap_directory_stub"] = None
_mod_backend = types.ModuleType("backend")
_mod_ld = types.ModuleType("backend.ldap_directory")
_conn_fuer_reval = ConnAttrappe([RuntimeError("LDAP weg"), RuntimeError("LDAP weg")])
_mod_ld._bind = lambda: (_conn_fuer_reval, "DC=nexus,DC=int")
_mod_backend.ldap_directory = _mod_ld
sys.modules["backend"] = _mod_backend
sys.modules["backend.ldap_directory"] = _mod_ld

leeren()
_ns["_ad_seen_users"]["andreas.bender"] = time.time()
_ns["_revoked_logins"].clear()
res = _ns["_revalidate_ad_groups_once"]()
pruefe("andreas.bender" not in res["revoked"],
       "Revalidierung: ein SUCHFEHLER widerruft die Sitzung NICHT (fail-open)",
       str(res))
pruefe(res["checked"] == 0, "... und zaehlt den Benutzer auch nicht als geprueft")

# Gegenprobe: wirklich nicht im Verzeichnis -> Widerruf ist richtig
_conn_leer = ConnAttrappe([[], []])
_mod_ld._bind = lambda: (_conn_leer, "DC=nexus,DC=int")
leeren()
_ns["_ad_seen_users"]["geloescht.konto"] = time.time()
_ns["_revoked_logins"].clear()
res = _ns["_revalidate_ad_groups_once"]()
pruefe("geloescht.konto" in res["revoked"],
       "... ein wirklich fehlendes Konto wird dagegen sehr wohl widerrufen", str(res))

# ── Verdrahtung: ohne Aufruf in require_auth ist alles wirkungslos ──────────
_ra = None
for n in ast.parse(MAIN_SRC).body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "require_auth":
        _ra = "".join(MAIN_LINES[n.lineno - 1:n.end_lineno])
pruefe(_ra is not None and "_ad_cache_nachladen_falls_noetig(" in _ra,
       "require_auth ruft das Nachladen – es haengt am Pfad JEDER Anfrage")
pruefe(_ra is not None and "await _ad_cache_nachladen_falls_noetig" in _ra,
       "... und zwar awaited (der LDAP-Bind laeuft im Thread, nicht im Event-Loop)")
_arq = _holen.get("_ad_cache_nachladen_falls_noetig", "")
pruefe("asyncio.to_thread" in _arq,
       "der Bind laeuft ueber asyncio.to_thread – sonst friert er alle Benutzer ein")

# ── Beide Wege nutzen DIESELBE Funktion ────────────────────────────────────
_rev = _holen.get("_revalidate_ad_groups_once", "")
_nl = _holen.get("_ad_cache_nachladen", "")
pruefe("_ad_rollen_aktualisieren(" in _rev and "_ad_rollen_aktualisieren(" in _nl,
       "Revalidierung und Nachladen teilen sich eine Fassung (kein Auseinanderlaufen)")
pruefe("_knowledge_editor_cache[plain] =" not in _rev,
       "... die Revalidierung setzt die Caches nicht mehr selbst")

# ═════════════════════════════════════════════════════════════════════════════
try:
    for f in _TMP.iterdir():
        f.unlink()
    _TMP.rmdir()
except Exception:  # noqa: BLE001
    pass

print(f"\n{'='*70}\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
