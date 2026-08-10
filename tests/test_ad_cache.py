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
            "_load_ad_caches", "_save_ad_caches", "_norm_login"):
        _holen[n.name] = "".join(MAIN_LINES[n.lineno - 1:n.end_lineno])

for _p in ("_load_ad_caches", "_save_ad_caches", "_norm_login"):
    if _p not in _holen:
        print(f"ABBRUCH: {_p} nicht in main.py gefunden")
        sys.exit(2)

_TMP = Path(tempfile.mkdtemp(prefix="jarvis-adcache-"))
_ns = {
    "json": json, "os": os, "time": time, "Path": Path,
    "_AD_CACHE_FILE": _TMP / "ad_cache.json",
    "_AD_CACHE_TTL": 86400.0,
    "_AD_CACHE_MIN_INTERVAL": 5.0,
    "_ad_cache_last_write": 0.0,
    "_user_group_dns_cache": {}, "_knowledge_editor_cache": {},
    "_internet_access_cache": {}, "_admin_access_cache": {},
    "_ad_seen_users": {},
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
try:
    for f in _TMP.iterdir():
        f.unlink()
    _TMP.rmdir()
except Exception:  # noqa: BLE001
    pass

print(f"\n{'='*70}\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
