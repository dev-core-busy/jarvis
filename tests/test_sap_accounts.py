#!/usr/bin/env python3
"""Tests fuer den persoenlichen SAP-Zugang (backend/sap_accounts.py).

Laeuft ohne fastapi und ohne SAP-System:

* ``backend.config`` wird als Attrappe in ``sys.modules`` gelegt. Der ECHTE
  Import wuerde beim Laden die LIVE-``settings.json`` migrieren und
  zurueckschreiben (dieselbe Falle wie in test_email_rules.py und
  test_shell_redirects.py).
* Alle Dateipfade werden auf ein Wegwerf-Verzeichnis umgebogen; ein
  SANDKASTEN-WAECHTER bricht mit Exit 2 ab, wenn danach noch ein Pfad auf
  ``data/`` des Repos zeigt.
* Die Verbindungslogik selbst wird NICHT geprueft (das ist ``sap_client``,
  dafuer braucht es ein SAP-System) – geprueft wird die Aufloesung: WELCHE
  Zugangsdaten in welchem Fall gelten und was dabei protokolliert/vermerkt wird.

Exit 2 heisst "konnte nicht laufen" (Sandkasten/Import), 1 heisst "Pruefung
fehlgeschlagen", 0 heisst bestanden.

    python3 tests/test_sap_accounts.py
"""
import asyncio
import json
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


# ── Attrappe fuer backend.config VOR dem Import ─────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="sapacc_test_"))
(TMP / "data").mkdir(parents=True)

_skill_states = {"sap": {"enabled": True, "config": {}}}

_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return _skill_states

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        pass


_cfg_mod.config = _Cfg()
sys.modules.setdefault("backend.config", _cfg_mod)

from backend import sap_accounts as sa       # noqa: E402
from backend.sap_client import SapError      # noqa: E402

sa.DATA_DIR = TMP / "data"
sa.KONTEN_DATEI = TMP / "data" / "sap_accounts.json"
sa.SCHLUESSEL_DATEI = TMP / "data" / ".sapkey"

_ECHTES_DATA = ROOT / "data"
for name in dir(sa):
    wert = getattr(sa, name)
    if isinstance(wert, Path) and name.isupper() and name != "PROJECT_ROOT":
        try:
            drin = wert == _ECHTES_DATA or _ECHTES_DATA in wert.parents
        except Exception:  # noqa: BLE001
            drin = False
        if drin:
            print(f"SANDKASTEN VERLETZT: sap_accounts.{name} = {wert}")
            sys.exit(2)
for pfad in (sa.KONTEN_DATEI, sa.SCHLUESSEL_DATEI):
    if not str(pfad).startswith(str(TMP)):
        print(f"SANDKASTEN VERLETZT: {pfad} liegt nicht im Wegwerf-Verzeichnis")
        sys.exit(2)


def admin_config(**felder):
    """Setzt die SAP-Skill-Config (Sammelzugang + Freigabeliste)."""
    _skill_states["sap"]["config"] = dict(felder)


def datei() -> dict:
    return json.loads(sa.KONTEN_DATEI.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════
section("1. Normalisierung und Kanal-Kennungen")
# ═══════════════════════════════════════════════════════════════════════════

check(sa.norm_user("NEXUS\\Andreas.Bender") == "andreas.bender",
      "Domaenen-Praefix wird entfernt", sa.norm_user("NEXUS\\Andreas.Bender"))
check(sa.norm_user("a.bender@nexus.int") == "a.bender", "UPN-Suffix wird entfernt")
check(sa.norm_user("wa:+4917012345") == "wa:+4917012345",
      "Kanal-Kennung bleibt unangetastet")

admin_config(allowed_hosts="s4.firma.de")
try:
    sa.speichern("wa:+4917012345", {"connection_type": "odata",
                                    "odata_base_url": "https://s4.firma.de/x"})
    check(False, "Kanal-Kennung bekommt keinen Zugang")
except sa.SapKontoFehler:
    check(True, "Kanal-Kennung bekommt keinen Zugang (wa:/tg:/api: sind keine Personen)")
try:
    sa.speichern("", {"connection_type": "odata"})
    check(False, "leerer Benutzer wird abgelehnt")
except sa.SapKontoFehler:
    check(True, "leerer Benutzer wird abgelehnt")


# ═══════════════════════════════════════════════════════════════════════════
section("2. Host-Freigabeliste: leer = niemand, Admin-Host implizit")
# ═══════════════════════════════════════════════════════════════════════════

admin_config()                      # nichts freigegeben, kein Sammelzugang
check(sa.hosts_erlaubt() == [], "ohne Eintrag und ohne Sammelzugang: NIEMAND")
try:
    sa.speichern("alice", {"connection_type": "odata",
                           "odata_base_url": "https://s4.firma.de/sap/opu/odata"})
    check(False, "leere Freigabeliste verhindert das Speichern")
except sa.SapKontoFehler as e:
    check("nicht freigegeben" in str(e) and "KEIN Server" in str(e).replace("kein", "KEIN"),
          "leere Freigabeliste verhindert das Speichern (mit Klartext-Grund)", str(e))

# Der Sammelzugang des Administrators gilt IMPLIZIT – sonst muesste er seinen
# eigenen Server doppelt eintragen.
admin_config(connection_type="odata", odata_base_url="https://s4.firma.de/sap/opu/odata")
check(sa.hosts_implizit() == ["s4.firma.de"], "Host des Sammelzugangs implizit erlaubt",
      str(sa.hosts_implizit()))
check(sa.host_ok("https://s4.firma.de/anders"), "derselbe Host mit anderem Pfad ist erlaubt")
check(not sa.host_ok("boese.example"), "fremder Host ist nicht erlaubt")

admin_config(allowed_hosts="firma.de, hana.extern.de")
check(sa.host_ok("s4.firma.de"), "Eintrag deckt Unterdomaenen ab")
check(sa.host_ok("hana.extern.de"), "zweiter Eintrag wirkt")
check(not sa.host_ok("firma.de.boese.example"), "Suffix-Trick greift nicht")
check(not sa.host_ok(""), "leerer Host ist nie erlaubt")
admin_config(allowed_hosts="https://s4.firma.de:44300/sap")
check(sa.hosts_admin() == ["s4.firma.de"], "URL in der Freigabeliste wird auf den Host reduziert",
      str(sa.hosts_admin()))
admin_config(allowed_hosts="*.firma.de")
check(sa.host_ok("s4.firma.de"), "Schreibweise *.firma.de wird verstanden")

check(sa._host_von("[::1]:30015") == "::1", "IPv6 in Klammern wird erkannt",
      sa._host_von("[::1]:30015"))
check(sa._host_von("hana.firma.de:30015") == "hana.firma.de", "Host:Port wird zerlegt")


# ═══════════════════════════════════════════════════════════════════════════
section("3. Verschluesselung und 'leeres Kennwort = unveraendert'")
# ═══════════════════════════════════════════════════════════════════════════

admin_config(allowed_hosts="firma.de")
info = sa.speichern("alice", {
    "connection_type": "odata",
    "odata_base_url": "https://s4.firma.de/sap/opu/odata",
    "username": "ALICE", "password": "geheim123", "sap_client": "100"})
check(info["vorhanden"] and info["passwort_gesetzt"], "Zugang angelegt")
roh = sa.KONTEN_DATEI.read_text(encoding="utf-8")
check("geheim123" not in roh, "Kennwort steht NICHT im Klartext in der Datei")
check(datei()["alice"].get("password_enc"), "Kennwort liegt verschluesselt vor")
check(sa.entschluesseln(datei()["alice"]["password_enc"]) == "geheim123",
      "Kennwort laesst sich wieder entschluesseln")

# Erneut speichern OHNE Kennwortfeld -> unveraendert
sa.speichern("alice", {"sap_client": "200"})
check(sa.entschluesseln(datei()["alice"]["password_enc"]) == "geheim123",
      "Speichern ohne Kennwortfeld laesst das Kennwort stehen")
# Leeres Kennwortfeld -> ebenfalls unveraendert (NICHT loeschen)
sa.speichern("alice", {"password": ""})
check(sa.entschluesseln(datei()["alice"]["password_enc"]) == "geheim123",
      "LEERES Kennwortfeld heisst 'unveraendert', nicht 'loeschen'")

i = sa.zugang_info("alice")
check("password" not in i and "password_enc" not in i and "pw" not in i,
      "zugang_info gibt kein Kennwort heraus")
check(i["passwort_gesetzt"] is True, "nur das Ja/Nein-Flag verlaesst den Server")
check(not any("geheim" in str(v) for v in i.values()), "auch nicht maskiert")

modus = sa.KONTEN_DATEI.stat().st_mode & 0o777
check(modus == 0o640, "Kontendatei ist 0640", oct(modus))
kmodus = sa.SCHLUESSEL_DATEI.stat().st_mode & 0o777
check(kmodus == 0o600, "Schluesseldatei ist 0600 (strenger als 0640)", oct(kmodus))


# ═══════════════════════════════════════════════════════════════════════════
section("4. Feld-Whitelist: was der Benutzer NICHT setzen darf")
# ═══════════════════════════════════════════════════════════════════════════

for feld, wert in (("verify_ssl", False), ("hana_ssl_validate", False),
                   ("read_only", False), ("hana_encrypt", False),
                   ("benutzer_norm", "root"), ("ausgesetzt", False),
                   ("anmeldefehler", 0)):
    try:
        sa.speichern("alice", {feld: wert})
        check(False, f"Feld '{feld}' wird abgelehnt")
    except sa.SapKontoFehler:
        check(True, f"Feld '{feld}' wird abgelehnt")

check("verify_ssl" not in sa.AENDERBAR and "read_only" not in sa.AENDERBAR,
      "TLS-Pruefung und read_only stehen NICHT in AENDERBAR")

try:
    sa.speichern("alice", {"connection_type": "smb"})
    check(False, "unbekannte Zugangsart wird abgelehnt")
except sa.SapKontoFehler:
    check(True, "unbekannte Zugangsart wird abgelehnt")
try:
    sa.speichern("alice", {"auth_kind": "ntlm"})
    check(False, "unbekannte Anmeldeart wird abgelehnt")
except sa.SapKontoFehler:
    check(True, "unbekannte Anmeldeart wird abgelehnt")
try:
    sa.speichern("alice", {"hana_port": "abc"})
    check(False, "unsinniger Port wird abgelehnt")
except sa.SapKontoFehler:
    check(True, "unsinniger Port wird abgelehnt")
try:
    sa.speichern("alice", {"hana_port": 99999})
    check(False, "Port ausserhalb 1..65535 wird abgelehnt")
except sa.SapKontoFehler:
    check(True, "Port ausserhalb 1..65535 wird abgelehnt")

# Fremder Server -> abgelehnt (SSRF-Schranke)
try:
    sa.speichern("alice", {"odata_base_url": "https://boese.example/x"})
    check(False, "fremder Server wird abgelehnt")
except sa.SapKontoFehler as e:
    check("boese.example" in str(e), "fremder Server wird abgelehnt und BENANNT", str(e))


# ═══════════════════════════════════════════════════════════════════════════
section("5. Vorrang: persoenlich schlaegt Sammelzugang")
# ═══════════════════════════════════════════════════════════════════════════

admin_config(allowed_hosts="firma.de", connection_type="hana",
             hana_host="sammel.firma.de", hana_user="RAG_READER",
             hana_password="x", verify_ssl=True)

z = sa.aufloesen("bob")
check(z["quelle"] == sa.QUELLE_SAMMEL and not z["hinweis"],
      "ohne eigenen Zugang gilt der Sammelzugang – ohne Hinweis")
check(z["client"].hana.host == "sammel.firma.de", "Sammelzugang zeigt auf den Admin-Host")

z = sa.aufloesen("alice")
check(z["quelle"] == sa.QUELLE_PERSOENLICH, "mit eigenem Zugang gilt der eigene")
check(z["client"].connection_type == "odata",
      "der eigene Kanal gewinnt gegen den Kanal des Sammelzugangs")
check(z["client"].odata.user == "ALICE", "eigener SAP-Benutzer wird benutzt")
check(z["client"].odata.password == "geheim123", "eigenes Kennwort wird entschluesselt")

# TLS-Vorgabe kommt vom Administrator, nicht vom Benutzer
admin_config(allowed_hosts="firma.de", verify_ssl=False)
z = sa.aufloesen("alice")
check(z["client"].odata.verify is False,
      "verify_ssl kommt aus der Admin-Konfiguration (Benutzer kann es nicht setzen)")
admin_config(allowed_hosts="firma.de", connection_type="hana",
             hana_host="sammel.firma.de", hana_user="RAG_READER", hana_password="x")

# Inaktiv -> Rueckfall MIT Hinweis
sa.speichern("alice", {"aktiv": False})
z = sa.aufloesen("alice")
check(z["quelle"] == sa.QUELLE_SAMMEL and "inaktiv" in z["hinweis"],
      "auf inaktiv gestellt: Rueckfall mit Hinweis", z["hinweis"])
sa.speichern("alice", {"aktiv": True})

# ContextVar statt Parameter
tok = sa.current_sap_user.set("nexus\\Alice")
try:
    z = sa.aufloesen()
    check(z["quelle"] == sa.QUELLE_PERSOENLICH,
          "aufloesen() ohne Argument nimmt den ContextVar (und normalisiert)")
finally:
    sa.current_sap_user.reset(tok)
z = sa.aufloesen()
check(z["quelle"] == sa.QUELLE_SAMMEL, "nach reset() wirkt der Zugang nicht mehr nach")

# Host nachtraeglich aus der Freigabeliste entfernt -> Rueckfall mit Hinweis
admin_config(allowed_hosts="andere.de")
z = sa.aufloesen("alice")
check(z["quelle"] == sa.QUELLE_SAMMEL and "nicht mehr freigegeben" in z["hinweis"],
      "entzogene Freigabe: Rueckfall mit Hinweis (kein stiller Weiterbetrieb)", z["hinweis"])
admin_config(allowed_hosts="firma.de", connection_type="hana",
             hana_host="sammel.firma.de", hana_user="RAG_READER", hana_password="x")

# Unvollstaendiger Zugang zaehlt nicht
sa.speichern("carol", {"connection_type": "hana", "hana_host": "hana.firma.de"})
check(not sa.hat_zugang("carol"), "HANA ohne Benutzer ist unvollstaendig")
check(sa.aufloesen("carol")["quelle"] == sa.QUELLE_SAMMEL,
      "unvollstaendiger Zugang faellt auf den Sammelzugang")
sa.speichern("carol", {"hana_user": "CAROL", "hana_password": "pw"})
check(sa.hat_zugang("carol") and sa.aufloesen("carol")["quelle"] == sa.QUELLE_PERSOENLICH,
      "nach Ergaenzen des Benutzers gilt der eigene Zugang")


# ═══════════════════════════════════════════════════════════════════════════
section("6. Aussetzer nach Anmeldefehlern (Schutz des SAP-Benutzers)")
# ═══════════════════════════════════════════════════════════════════════════

check(sa.ist_anmeldefehler(SapError(401, "Unauthorized")), "HTTP 401 ist ein Anmeldefehler")
check(sa.ist_anmeldefehler(SapError(403, "Forbidden")), "HTTP 403 ist ein Anmeldefehler")
check(sa.ist_anmeldefehler(SapError(0, "HANA-Verbindung fehlgeschlagen: authentication failed")),
      "hdbcli 'authentication failed' ist ein Anmeldefehler")
check(sa.ist_anmeldefehler(SapError(0, "RFC_LOGON_FAILURE: Name or password is incorrect")),
      "RFC 'Name or password is incorrect' ist ein Anmeldefehler")
check(not sa.ist_anmeldefehler(SapError(0, "Netzwerkfehler: Connection refused")),
      "Netzfehler ist KEIN Anmeldefehler")
check(not sa.ist_anmeldefehler(SapError(500, "Internal Server Error")),
      "HTTP 500 ist KEIN Anmeldefehler")
check(not sa.ist_anmeldefehler(SapError(0, "certificate verify failed")),
      "Zertifikatsfehler ist KEIN Anmeldefehler")

# Netzfehler zaehlen nicht
for _ in range(5):
    sa.melde_fehler("carol", SapError(0, "Netzwerkfehler: timed out"))
check(sa.zugang_info("carol")["anmeldefehler"] == 0,
      "fuenf Netzfehler setzen den Zugang NICHT aus")
check(not sa.zugang_info("carol")["ausgesetzt"], "und er bleibt in Betrieb")

# Drei Anmeldefehler -> ausgesetzt
for _ in range(2):
    sa.melde_fehler("carol", SapError(401, "Unauthorized"))
check(not sa.zugang_info("carol")["ausgesetzt"], "zwei Anmeldefehler setzen noch nicht aus")
sa.melde_fehler("carol", SapError(401, "Unauthorized"))
i = sa.zugang_info("carol")
check(i["ausgesetzt"] and i["anmeldefehler"] == 3,
      "der dritte Anmeldefehler setzt den Zugang aus")

z = sa.aufloesen("carol")
check(z["quelle"] == sa.QUELLE_SAMMEL and "ausgesetzt" in z["hinweis"],
      "ausgesetzt: Rueckfall auf den Sammelzugang MIT Hinweis", z["hinweis"])
z = sa.aufloesen("carol", trotz_aussetzer=True)
check(z["quelle"] == sa.QUELLE_PERSOENLICH,
      "trotz_aussetzer=True testet den eigenen Zugang (sonst gaebe es keinen Rueckweg)")

# Erfolg hebt auf
sa.merke_ergebnis("carol", True)
i = sa.zugang_info("carol")
check(not i["ausgesetzt"] and i["anmeldefehler"] == 0, "ein Erfolg hebt den Aussetzer auf")

# Neues Kennwort hebt auf, leeres Feld nicht
for _ in range(3):
    sa.melde_fehler("carol", SapError(401, "Unauthorized"))
check(sa.zugang_info("carol")["ausgesetzt"], "erneut ausgesetzt")
sa.speichern("carol", {"hana_password": ""})
check(sa.zugang_info("carol")["ausgesetzt"],
      "LEERES Kennwortfeld hebt den Aussetzer NICHT auf")
sa.speichern("carol", {"hana_password": "neu"})
check(not sa.zugang_info("carol")["ausgesetzt"], "ein NEUES Kennwort hebt den Aussetzer auf")

# merke_ergebnis ohne 'anmeldefehler' zaehlt nichts (fail-safe)
sa.merke_ergebnis("carol", False, "irgendein Fehler")
check(sa.zugang_info("carol")["anmeldefehler"] == 0,
      "merke_ergebnis ohne anmeldefehler=True zaehlt NICHTS (fail-safe)")

# Ein Fehler des SAMMELZUGANGS darf dem Benutzer nicht angerechnet werden
sa.melde_fehler("dave", SapError(401, "Unauthorized"))
check("dave" not in datei(), "ohne eigenen Zugang wird nichts vermerkt")

check(sa.max_anmeldefehler() == 3, "Schwelle ist 3")
import os as _os                              # noqa: E402
_os.environ["JARVIS_SAP_MAX_AUTHFEHLER"] = "0"
check(sa.max_anmeldefehler() == 0, "0 schaltet den Aussetzer ab (Funktion, nicht Konstante)")
_os.environ["JARVIS_SAP_MAX_AUTHFEHLER"] = "quatsch"
check(sa.max_anmeldefehler() == 3, "Tippfehler faellt auf die Vorgabe zurueck")
del _os.environ["JARVIS_SAP_MAX_AUTHFEHLER"]


# ═══════════════════════════════════════════════════════════════════════════
section("7. Loeschen und beschaedigte Datei")
# ═══════════════════════════════════════════════════════════════════════════

check(sa.loeschen("carol") is True, "Loeschen entfernt den Zugang")
check(sa.aufloesen("carol")["quelle"] == sa.QUELLE_SAMMEL,
      "danach gilt wieder der Sammelzugang")
check(sa.loeschen("carol") is False, "zweites Loeschen meldet 'nichts da'")

sicherung = sa.KONTEN_DATEI.read_text(encoding="utf-8")
sa.KONTEN_DATEI.write_text("{kaputt", encoding="utf-8")
check(sa.aufloesen("alice")["quelle"] == sa.QUELLE_SAMMEL,
      "beschaedigte Datei kippt den Dienst nicht (Rueckfall)")
check(sa.KONTEN_DATEI.read_text(encoding="utf-8") == "{kaputt",
      "und wird NICHT ueberschrieben (kein Datenverlust ohne Not)")
sa.KONTEN_DATEI.write_text(sicherung, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
section("8. Quelltext: Sandbox-Listen, Endpunkte, ContextVar, Skill")
# ═══════════════════════════════════════════════════════════════════════════

sbx = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
for muster, label in (
        ('"data/sap_accounts.json", "data/.sapkey"', "beide Dateien in _APP_DENY_REL"),
        ('"data/sap_accounts.json")', "sap_accounts.json in PRIVATE_FILES"),
        ('"data/.mailkey", "data/.sapkey"', ".sapkey in PRIVATE_FILES_STRENG (0600)"),
        (r"sap_accounts\.json\b|\.sapkey\b", "beide in SHELL_SECRET_PATHS")):
    check(muster in sbx, label)

mainpy = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
check('def _sap_client(user: str = "")' in mainpy, "_sap_client nimmt den Benutzer")
check(mainpy.count("    c = _sap_client()") == 0,
      "kein Aufruf von _sap_client() OHNE Benutzer (sonst liest der Endpunkt mit "
      "fremden SAP-Berechtigungen)")
# Fuenf Endpunkte holen nur den Client, drei brauchen zusaetzlich Quelle+Hinweis
# fuer die Anzeige (Test, Status, ask) und gehen ueber _sap_zugang.
check(mainpy.count("_sap_client(user)") == 5,
      "die fuenf reinen Abfrage-Endpunkte uebergeben den Benutzer",
      str(mainpy.count("_sap_client(user)")))
check(mainpy.count("z = _sap_zugang(user") == 3,
      "Test, Status und ask holen zusaetzlich Quelle und Hinweis",
      str(mainpy.count("z = _sap_zugang(user")))

# Rechte der neuen Endpunkte: Konto = require_sap_access, Admin-Sicht = Admin.
for pfad, dep in (('@app.get("/api/sap/account")', "require_sap_access"),
                  ('@app.post("/api/sap/account")', "require_sap_access"),
                  ('@app.delete("/api/sap/account")', "require_sap_access"),
                  ('@app.get("/api/sap/admin/accounts")', "require_local_auth")):
    i = mainpy.find(pfad)
    block = mainpy[i:i + 400] if i >= 0 else ""
    check(i >= 0 and dep in block, f"{pfad} haengt an {dep}",
          block.split("\n")[1] if block else "Route fehlt")

# Der Rumpf darf NICHT vorgefiltert werden – die Whitelist in speichern() ist die
# einzige Instanz (ein still verworfenes Feld meldete sonst "gespeichert").
i = mainpy.find('@app.post("/api/sap/account")')
rumpf = mainpy[i:i + 1600]
check("sap_accounts.speichern(user, body)" in rumpf,
      "der Rumpf geht unveraendert an speichern() (keine zweite Filterschicht)")
check("SapKontoFehler" in rumpf and "status_code=400" in rumpf,
      "Eingabefehler werden als 400 mit Grund gemeldet")

# Die Admin-Sicht darf keine Zugangsdaten herausgeben.
i = mainpy.find('@app.get("/api/sap/admin/accounts")')
adminblock = mainpy[i:i + 1800]
for feld in ("password", "hana_password", "rfc_password", "bearer_token",
             "odata_base_url", "hana_host", "rfc_ashost"):
    check(feld not in adminblock, f"Admin-Sicht nennt '{feld}' nicht")

# Ergebniskopf: mit welchem Zugang gelesen wurde.
i = mainpy.find('@app.post("/api/sap/ask")')
askblock = mainpy[i:i + 7000]
check('"quelle"' in askblock and '"hinweis"' in askblock,
      "/api/sap/ask liefert Quelle und Hinweis (Ergebniskopf)")

agentpy = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
check("from backend.sap_accounts import current_sap_user" in agentpy,
      "agent.py setzt den SAP-ContextVar")
check("_scv.reset(_s_token)" in agentpy,
      "und nimmt ihn im finally zurueck (sonst regiert er den naechsten Lauf mit)")

skill = (ROOT / "skills" / "sap" / "main.py").read_text(encoding="utf-8")
# 9 Werkzeuge + die NotImplementedError-Fassung in _Base = 10.
check(skill.count("async def _run(self, **kwargs):") == 10,
      "alle neun Werkzeuge implementieren _run (plus die Basisfassung)",
      str(skill.count("async def _run(self, **kwargs):")))
check("raise NotImplementedError" in skill,
      "_Base._run ist nicht implementiert (wer execute ueberschreibt, faellt auf)")
check(skill.count("async def execute(self, **kwargs):") == 1,
      "execute steht genau EINMAL (zentral in _Base)")
check("sa.aufloesen()" in skill, "_Base.execute loest den Zugang auf")
# NIEMALS ein Benutzer-/Zugangs-Argument an einem SAP-Werkzeug: sonst koennte das
# Modell (oder eine Prompt-Injektion) waehlen, mit wessen Zugangsdaten es
# arbeitet. Geprueft werden die echten Schemata, nicht der ganze Quelltext –
# sonst schlaegt die Pruefung an einem Kommentar an (dieselbe Falle wie beim
# Prompt-Waechter am 2026-08-10).
schemas = re.findall(r"def parameters_schema\(self\):(.*?)(?=\n    (?:async |def |@))",
                     skill, re.S)
verbotene = [f for f in ("benutzer", "sap_user", "zugang", "account", "credential")
             if any(f in s for s in schemas)]
check(not verbotene, "kein Werkzeug hat einen Benutzer-/Zugangs-Parameter", str(verbotene))
check(len(schemas) == 9, "neun Werkzeug-Schemata gefunden", str(len(schemas)))

sk = (ROOT / "skills" / "sap" / "skill.json").read_text(encoding="utf-8")
check('"allowed_hosts"' in sk, "Freigabeliste steht im Manifest")
check("LEER = NIEMAND" in sk, "und das Manifest sagt 'leer = niemand'")


print(f"\n{'='*60}\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
