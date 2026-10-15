#!/usr/bin/env python3
"""Waechter BSI M5: Geheimnisse – Schluessel ausserhalb data/, settings.json
verpackt, Anzeige nur nach erneuter Anmeldung.

BEFUND M5 (BSI-Abgleich 2026-09-29): "Sammelgeheimnisse im Klartext in
settings.json (0600); Fernet-Schluessel neben Chiffrat; Geheimnis-Anzeige ohne
erneute Anmeldung." Massnahme: Verschluesselung mit Schluessel ausserhalb data/,
Re-Auth fuer die Anzeige. Entscheidungen des Betreibers 2026-10-05: Root-Datei
/etc/jarvis/geheimnis.key (per LoadCredential an den Dienst), Kennwort mit
5-Minuten-Fenster, alle Formulare maskiert.

GEMESSEN WIRD AUSGEFUEHRT, wo es geht:
  1-2  Tresor: Hauptschluessel, Modulschluessel verpacken (nie verlieren)
  3    die sieben Konten-Module gehen ueber den Tresor – und ihr ALTES Chiffrat
       bleibt lesbar (es wird nicht umgeschluesselt)
  4    Felder in settings.json: Regel, Hin- und Rueckweg, ohne Schluessel
  5    config.py gegen eine Wegwerf-settings.json (Unterprozess, DATA_DIR) –
       Migration, fremde Schluessel bleiben, ohne Schluessel geht nichts verloren
  6    Bestaetigungsfenster (Token-gebunden, laeuft ab)
  7    main.py: Endpunkte geschnitten und ausgefuehrt (Bestaetigung vor jedem
       Klartext, Maskierung, leer = unveraendert, Schluessel nur an die
       gespeicherte Adresse)
  8    haertung_installieren.sh im Testmodus (Schluessel, Drop-in, HAERTUNG=aus)
  9    Sandbox-Sperren fuer Hauptschluessel und Credential-Verzeichnis

Lauf:  timeout 300 python3 tests/test_bsi_m5.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import importlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def abbruch(text):
    print("\033[31mABBRUCH: %s\033[0m" % text)
    sys.exit(2)


try:
    from cryptography.fernet import Fernet
except Exception as e:  # noqa: BLE001
    abbruch("cryptography fehlt: %s" % e)

TMP = Path(tempfile.mkdtemp(prefix="bsi_m5_"))
HAUPT = TMP / "geheimnis.key"
HAUPT.write_bytes(Fernet.generate_key())
os.environ["JARVIS_GEHEIMNIS_DATEI"] = str(HAUPT)
os.environ.pop("CREDENTIALS_DIRECTORY", None)

# Sandkasten-Waechter: der echte data/-Baum darf sich durch diesen Lauf nicht aendern.
def _stand(wurzel: Path) -> dict:
    aus = {}
    if wurzel.exists():
        for p in wurzel.rglob("*"):
            try:
                if p.is_file():
                    st = p.stat()
                    aus[str(p)] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
    return aus


DATA_VORHER = _stand(ROOT / "data")

from backend import geheimnis_tresor as T  # noqa: E402

T._zuruecksetzen_fuer_test()

# ══ 1. Hauptschluessel ═════════════════════════════════════════════════════
abschnitt("1 – Hauptschluessel ausserhalb data/")

f = T.hauptfernet()
if f is None:
    abbruch("Positivkontrolle: Hauptschluessel aus JARVIS_GEHEIMNIS_DATEI nicht geladen")
check("Positivkontrolle: Hauptschluessel geladen", f is not None)
check("status() meldet aktiv + Quelle", T.status()["aktiv"] and str(HAUPT) in T.status()["quelle"],
      str(T.status()))
check("⚠ Vorgabeort liegt AUSSERHALB von data/ (/etc/jarvis)",
      "/etc/jarvis/" in Path(T.__file__).read_text() and "data" not in str(T.ROOT_DATEI.parent),
      str(T.ROOT_DATEI))

# Credential-Verzeichnis hat Vorrang vor der Datei
CRED = TMP / "cred"
CRED.mkdir()
cred_key = Fernet.generate_key()
(CRED / T.CREDENTIAL_NAME).write_bytes(cred_key)
os.environ["CREDENTIALS_DIRECTORY"] = str(CRED)
T._zuruecksetzen_fuer_test()
check("⚠ $CREDENTIALS_DIRECTORY/geheimnis hat Vorrang (systemd LoadCredential)",
      T.status()["quelle"] == "systemd-Credential", T.status())
os.environ.pop("CREDENTIALS_DIRECTORY")

KAPUTT = TMP / "kaputt.key"
KAPUTT.write_text("das-ist-kein-schluessel")
os.environ["JARVIS_GEHEIMNIS_DATEI"] = str(KAPUTT)
T._zuruecksetzen_fuer_test()
check("⚠ ein kaputter Hauptschluessel gilt als KEINER (und sagt warum)",
      T.hauptfernet() is None and "kein gueltiger" in T.status()["fehler"], T.status())
os.environ["JARVIS_GEHEIMNIS_DATEI"] = str(TMP / "fehlt.key")
T._zuruecksetzen_fuer_test()
check("ohne Datei: kein Hauptschluessel, kein Fehler", T.hauptfernet() is None and not T.status()["fehler"])
os.environ["JARVIS_GEHEIMNIS_DATEI"] = str(HAUPT)
T._zuruecksetzen_fuer_test()
HF = T.hauptfernet()


def ohne_haupt():
    os.environ["JARVIS_GEHEIMNIS_DATEI"] = str(TMP / "fehlt.key")
    T._zuruecksetzen_fuer_test()


def mit_haupt(datei=HAUPT):
    os.environ["JARVIS_GEHEIMNIS_DATEI"] = str(datei)
    T._zuruecksetzen_fuer_test()


# ══ 2. Modulschluessel ═════════════════════════════════════════════════════
abschnitt("2 – Modulschluessel: verpacken, nie verlieren")

alt = Fernet.generate_key()
kd = TMP / ".testkey"
kd.write_bytes(alt)
os.chmod(kd, 0o600)
chiffrat_alt = Fernet(alt).encrypt(b"Kennwort!1")
roh = T.modul_schluessel(kd)
check("Altbestand: derselbe Schluessel kommt zurueck", roh == alt)
inhalt = kd.read_bytes()
check("⚠ … und die Datei ist danach VERPACKT (JGK1:)", inhalt.startswith(T.PRAEFIX_SCHLUESSEL),
      inhalt[:12])
check("⚠ … der rohe Schluessel steht NICHT mehr in data/", alt not in inhalt)
check("… Modus 0600", stat.S_IMODE(kd.stat().st_mode) == 0o600, oct(kd.stat().st_mode))
check("⚠ das ALTE Chiffrat bleibt lesbar (nichts umgeschluesselt)",
      Fernet(T.modul_schluessel(kd)).decrypt(chiffrat_alt) == b"Kennwort!1")
check("kein .tmp-Rest", not (TMP / ".testkey.tmp").exists())

ohne_haupt()
vorher = kd.read_bytes()
try:
    T.modul_schluessel(kd)
    geworfen = ""
except T.TresorFehler as e:
    geworfen = str(e)
check("⚠ verpackt + kein Hauptschluessel: sprechender Fehler (nennt das FEHLEN)",
      "fehlt" in geworfen and "Hauptschluessel" in geworfen, geworfen)
check("⚠⚠ … und die Datei wird NICHT durch einen neuen Schluessel ersetzt",
      kd.read_bytes() == vorher)
mit_haupt(KAPUTT)
mit_haupt(TMP / "anderer.key") if (TMP / "anderer.key").write_bytes(Fernet.generate_key()) else None
try:
    T.modul_schluessel(kd)
    geworfen = ""
except T.TresorFehler as e:
    geworfen = str(e)
check("⚠ falscher Hauptschluessel: Fehler statt Unsinn", "passt nicht" in geworfen, geworfen)
check("… Datei unveraendert", kd.read_bytes() == vorher)
mit_haupt()

kd2 = TMP / "sub" / ".neukey"
neu = T.modul_schluessel(kd2)
check("fehlt: neu angelegt, verpackt, 0600",
      kd2.read_bytes().startswith(T.PRAEFIX_SCHLUESSEL)
      and stat.S_IMODE(kd2.stat().st_mode) == 0o600 and len(neu) == 44)
check("… und beim naechsten Mal derselbe", T.modul_schluessel(kd2) == neu)

ohne_haupt()
kd3 = TMP / ".rohkey"
kd3.write_bytes(alt)
check("ohne Hauptschluessel: Altbestand roh zurueck (Verhalten wie vor M5)",
      T.modul_schluessel(kd3) == alt and kd3.read_bytes() == alt)
mit_haupt()

# Beim Dienststart: alle vorhandenen rohen Modulschluessel verpacken
DD0 = TMP / "start_data"
DD0.mkdir()
(DD0 / ".mailkey").write_bytes(Fernet.generate_key())
(DD0 / ".jirakey").write_bytes(Fernet.generate_key())
erg = T.alle_modulschluessel_verpacken(DD0)
check("⚠ Start: rohe Modulschluessel werden verpackt (nicht erst beim ersten Zugriff)",
      erg.get(".mailkey") == "verpackt" and erg.get(".jirakey") == "verpackt"
      and T.ist_verpackt(DD0 / ".mailkey") and T.ist_verpackt(DD0 / ".jirakey"), erg)
check("… fehlende werden NICHT angelegt", not (DD0 / ".sapkey").exists() and erg.get(".sapkey") == "fehlt")
check("… zweiter Lauf: nichts mehr zu tun", T.alle_modulschluessel_verpacken(DD0).get(".mailkey") == "war verpackt")
check("die Liste deckt alle sieben Module", len(T.MODUL_SCHLUESSEL) == 7)

# ══ 3. Die sieben Module ═══════════════════════════════════════════════════
abschnitt("3 – Die sieben Konten-Module gehen ueber den Tresor")

MODULE = ["mail_accounts", "sap_accounts", "vemas_accounts", "jira_accounts",
          "confluence_accounts", "mount_credentials", "ai_mouse_signatur"]
for name in MODULE:
    baum = ast.parse((ROOT / "backend" / (name + ".py")).read_text())
    fn = next((n for n in baum.body if isinstance(n, ast.FunctionDef) and n.name == "_fernet"), None)
    if fn is None:
        check("%s: _fernet gefunden" % name, False)
        continue
    rufe = {ast.unparse(k.func) for k in ast.walk(fn) if isinstance(k, ast.Call)}
    check("%s: _fernet ruft geheimnis_tresor.modul_schluessel" % name,
          any(r.endswith("modul_schluessel") for r in rufe), sorted(rufe))
    check("⚠ %s: _fernet liest/erzeugt den Schluessel NICHT mehr selbst" % name,
          not any(r.endswith(("read_bytes", "generate_key")) or r == "os.open" for r in rufe),
          sorted(rufe))

for name in MODULE:
    try:
        mod = importlib.import_module("backend." + name)
    except Exception as e:  # noqa: BLE001
        check("%s importierbar" % name, False, e)
        continue
    datei = TMP / ("m_" + name)
    altk = Fernet.generate_key()
    datei.write_bytes(altk)
    os.chmod(datei, 0o600)
    altes_chiffrat = Fernet(altk).encrypt(b"Bestand")
    vorher_datei = mod.SCHLUESSEL_DATEI
    mod.SCHLUESSEL_DATEI = datei
    try:
        fern = mod._fernet()
        lesbar = fern.decrypt(altes_chiffrat) == b"Bestand"
    except Exception as e:  # noqa: BLE001
        lesbar = "Fehler: %s" % e
    finally:
        mod.SCHLUESSEL_DATEI = vorher_datei
    check("⚠ %s: Altschluessel verpackt, altes Chiffrat lesbar" % name,
          lesbar is True and datei.read_bytes().startswith(T.PRAEFIX_SCHLUESSEL), lesbar)

# ══ 4. Felder in settings.json ═════════════════════════════════════════════
abschnitt("4 – Geheimfelder in settings.json")

BAUM = {
    "version": 2,
    "agent_api_key": "AgentKey123",
    # temperature gesetzt: sonst schreibt die (vorbestehende) temperature-Migration
    # ueber _save_to_file, das nur bekannte Schluessel kennt – das waere eine
    # Messung von etwas anderem als M5.
    "profiles": [{"id": "p", "api_key": "sk-123", "session_key": "", "model": "m",
                  "auth_method": "api_key", "temperature": "auto"}],
    "skills": {
        "jira": {"enabled": True, "config": {"api_token": "JiraTok", "ibs_api_key": "Ibs",
                                             "base_url": "https://j"}},
        "vemas": {"config": {"password": "VemPw", "token_json_path": "data.token",
                             "login_pass_field": "password", "token_header": "Authorization",
                             "auth_kind": "basic"}},
        "google": {"config": {"client_secret": "GSec", "client_id": "cid"}},
        "knowledge": {"config": {"webdav": {"password": "Dav", "username": "u"},
                                 "mounts": [{"password_enc": "gAAAA-chiffrat", "username": "x"}]}},
        "telegram": {"config": {"bot_token": "Bot"}},
    },
    "mcp_servers": [{"name": "gh", "env": {"GITHUB_TOKEN": "ghp_x", "LOG_LEVEL": "info"}}],
    "extra": {"ad_bind_password": "Bind", "ad_domain": "firma.local",
              "agent_api_keys": [{"id": "k", "name": "n", "key": "Named1"}],
              "sitzung_token_max_h": 12},
}
ERWARTET_GEHEIM = {
    "agent_api_key", "profiles[0].api_key", "skills.jira.config.api_token",
    "skills.jira.config.ibs_api_key", "skills.vemas.config.password",
    "skills.google.config.client_secret", "skills.knowledge.config.webdav.password",
    "skills.telegram.config.bot_token", "mcp_servers[0].env.GITHUB_TOKEN",
    "extra.ad_bind_password", "extra.agent_api_keys[0].key",
}
gefunden = set(T.klartext_felder(BAUM))
check("Positivkontrolle: die Regel findet alle erwarteten Geheimfelder",
      gefunden == ERWARTET_GEHEIM,
      "zu viel: %s | fehlt: %s" % (sorted(gefunden - ERWARTET_GEHEIM), sorted(ERWARTET_GEHEIM - gefunden)))
for nicht in ("token_json_path", "login_pass_field", "token_header", "auth_kind",
              "password_enc", "ad_domain", "base_url", "llm_max_tokens", "token_prefix",
              "max_tokens", "key_ende"):
    check("kein Geheimfeld: %s" % nicht, not T.ist_geheimer_name(nicht))

enc = T.verschluessele_baum(BAUM)
check("⚠ verpackt: kein Geheimfeld mehr im Klartext", T.klartext_felder(enc) == [],
      T.klartext_felder(enc))
roh_text = json.dumps(enc)
for w in ("AgentKey123", "sk-123", "JiraTok", "VemPw", "GSec", "Dav", "Bot", "ghp_x", "Bind", "Named1"):
    check("… '%s' steht nicht im Text" % w, ('"%s"' % w) not in roh_text)
check("nicht-geheime Werte bleiben lesbar",
      enc["skills"]["vemas"]["config"]["token_json_path"] == "data.token"
      and enc["extra"]["ad_domain"] == "firma.local"
      and enc["skills"]["knowledge"]["config"]["mounts"][0]["password_enc"] == "gAAAA-chiffrat")
check("leere Werte bleiben leer", enc["profiles"][0]["session_key"] == "")
check("⚠ Rueckweg ergibt exakt das Original", T.entschluessele_baum(enc) == BAUM)
check("das Original wurde nicht veraendert (Kopie)", BAUM["agent_api_key"] == "AgentKey123")
check("doppelt verpacken verpackt nicht doppelt",
      T.verschluessele_baum(enc)["agent_api_key"] == enc["agent_api_key"])

ohne_haupt()
check("ohne Hauptschluessel: verschluessele_baum aendert nichts", T.verschluessele_baum(BAUM) == BAUM)
check("⚠ ohne Hauptschluessel: verpackte Werte bleiben VERPACKT stehen (nichts verloren)",
      T.entschluessele_baum(enc) == enc)
mit_haupt(TMP / "anderer.key")
check("⚠ falscher Hauptschluessel: Werte bleiben verpackt (nicht leer)",
      T.entschluessele_baum(enc)["agent_api_key"] == enc["agent_api_key"])
mit_haupt()

# ══ 5. config.py gegen eine Wegwerf-settings.json ══════════════════════════
abschnitt("5 – config.py: Migration, Speichern, ohne Schluessel nichts verloren")

DD = TMP / "data"
DD.mkdir()
SF = DD / "settings.json"
anfang = json.loads(json.dumps(BAUM))
anfang["fremd_oben"] = {"bleibt": True}
SF.write_text(json.dumps(anfang, indent=4))

SKRIPT = TMP / "cfg_probe.py"
SKRIPT.write_text(r'''
import json, sys
sys.path.insert(0, sys.argv[1])
from backend.config import config
aktion = sys.argv[2]
aus = {
  "api_key": config.profiles[0].get("api_key") if config.profiles else None,
  "agent": config.AGENT_API_KEY,
  "bind": config.get_setting("ad_bind_password"),
  "named": (config.get_setting("agent_api_keys") or [{}])[0].get("key"),
  "jira": config.get_skill_states()["jira"]["config"]["api_token"],
}
if aktion == "speichern":
    config.save_setting("probe_wert", 1)
    config.save_skill_state("jira", config.get_skill_states()["jira"])
print("ERGEBNIS=" + json.dumps(aus))
''')


def probe(aktion, haupt):
    env = dict(os.environ, DATA_DIR=str(DD), SECRET_KEY="t" * 64,
               JARVIS_GEHEIMNIS_DATEI=str(haupt), PYTHONDONTWRITEBYTECODE="1")
    env.pop("CREDENTIALS_DIRECTORY", None)
    env.pop("AGENT_API_KEY", None)
    r = subprocess.run([sys.executable, str(SKRIPT), str(ROOT), aktion], env=env,
                       capture_output=True, text=True, timeout=120, cwd=str(TMP))
    zeile = [z for z in r.stdout.splitlines() if z.startswith("ERGEBNIS=")]
    if not zeile:
        abbruch("config-Probe lief nicht (rc=%s): %s" % (r.returncode, (r.stderr or r.stdout)[-600:]))
    return json.loads(zeile[0][len("ERGEBNIS="):])


a = probe("lesen", HAUPT)
check("Positivkontrolle: config liest die Wegwerf-Datei", a["bind"] == "Bind", a)
platte = json.loads(SF.read_text())
check("⚠ der Start mit Hauptschluessel verpackt den Altbestand auf der Platte",
      T.klartext_felder(platte) == [], T.klartext_felder(platte))
check("⚠ … fremde Schluessel der obersten Ebene bleiben erhalten",
      platte.get("fremd_oben") == {"bleibt": True}, list(platte))
check("im Speicher steht der Klartext",
      a == {"api_key": "sk-123", "agent": "AgentKey123", "bind": "Bind", "named": "Named1",
            "jira": "JiraTok"}, a)
a = probe("speichern", HAUPT)
platte = json.loads(SF.read_text())
check("⚠ nach save_setting/save_skill_state: weiter nichts im Klartext",
      T.klartext_felder(platte) == [] and platte["extra"].get("probe_wert") == 1,
      T.klartext_felder(platte))
verpackt_vorher = platte["skills"]["jira"]["config"]["api_token"]

b = probe("speichern", TMP / "fehlt.key")
platte = json.loads(SF.read_text())
check("ohne Hauptschluessel: der Dienst sieht den verpackten Wert (kann ihn nicht nutzen)",
      str(b["jira"]).startswith(T.PRAEFIX_WERT), b["jira"])
check("⚠⚠ … und SPEICHERN ohne Schluessel verliert nichts (Wert bleibt verpackt)",
      platte["skills"]["jira"]["config"]["api_token"] == verpackt_vorher)
c = probe("lesen", HAUPT)
check("⚠ mit Schluessel ist danach alles wieder da",
      c == {"api_key": "sk-123", "agent": "AgentKey123", "bind": "Bind", "named": "Named1",
            "jira": "JiraTok"}, c)

CFG = (ROOT / "backend" / "config.py").read_text()
cfg_baum = ast.parse(CFG)
roh_lesen = [n.lineno for n in ast.walk(cfg_baum) if isinstance(n, ast.Call)
             and ast.unparse(n).startswith("json.loads(self.SETTINGS_FILE.read_text")]
check("⚠ config.py liest settings.json nur noch ueber _lies_settings_datei "
      "(einzige Ausnahme: das rohe Verpacken)", len(roh_lesen) == 1, roh_lesen)
schreib = [n.lineno for n in ast.walk(cfg_baum) if isinstance(n, ast.Call)
           and ast.unparse(n.func) == "_write_preserve_owner"
           and "SETTINGS_FILE" in ast.unparse(n)]
check("⚠ … und schreibt sie nur ueber _schreibe_settings_datei", not schreib, schreib)

# ══ 6. Bestaetigungsfenster ════════════════════════════════════════════════
abschnitt("6 – Erneute Anmeldung: Fenster je Sitzung")

from backend import geheimnis_bestaetigung as GB  # noqa: E402
# ⚠ backend.config NUR ALS STUB - und zwar VOR jedem Aufruf, der es
# erreichen kann. Der echte Import loest in config.py:212 den SECRET_KEY auf
# (`_secret_aufloesen`), und das SCHREIBT data/.secret_key in der verpackten
# Form zurueck (JGK1:, 64 -> 189 Byte). Das Register sagt es seit langem:
# "backend.config in Tests nur als Stub - der echte Import schreibt die Live-
# settings.json zurueck".
#
# WARUM ES HIER AUFFIEL (2026-10-12): der Schnitt `agent_keys_list` ruft seit
# f41d3401 `_wirkung_h9.agent_api_freigabe()`. Ich habe dafuer das ECHTE
# wirkung-Modul gestellt - richtig, aber agent_api_freigabe() macht ein
# `from backend.config import config` IM AUFRUF, nicht beim Import. Meine
# Pruefung "fasst der Import data/ an?" war deshalb wahr und unschluessig:
# der Zugriff haengt am Aufruf. Die Sandkasten-Wache am Ende dieses Waechters
# hat es gefangen, in der CI (frischer Checkout, Schluessel noch unverpackt);
# lokal blieb es unsichtbar, weil die Datei hier laengst verpackt ist.
#
# Der Stub liefert nur, was agent_api_freigabe() braucht: get_setting mit dem
# Vorgabewert. Die ECHTE wirkung-Logik laeuft damit weiter - nur der Weg zum
# Hauptschluessel ist gekappt.
_cfg_stub = types.ModuleType("backend.config")
_cfg_stub.config = types.SimpleNamespace(
    get_setting=lambda _schluessel, vorgabe=None: vorgabe,
    save_setting=lambda *a, **k: None)
sys.modules["backend.config"] = _cfg_stub

from backend import totp_schutz as _totp_schutz  # noqa: E402
from backend import wirkung as _wirkung_h9  # noqa: E402

GB._reset_fuer_tests()
check("Vorgabe: 5 Minuten (Betreiberentscheid)", GB.FENSTER_S == 300)
check("unbestaetigt: nicht frisch", not GB.ist_frisch("tokA", "anna"))
GB.vermerken("tokA", "anna", jetzt=1000.0)
check("Positivkontrolle: nach dem Vermerk frisch", GB.ist_frisch("tokA", "anna", jetzt=1001.0))
check("⚠ eine ANDERE Sitzung desselben Benutzers ist nicht mitbestaetigt",
      not GB.ist_frisch("tokB", "anna", jetzt=1001.0))
check("⚠ falscher Benutzer zum Token: nicht frisch (fail-closed)",
      not GB.ist_frisch("tokA", "bert", jetzt=1001.0))
check("⚠ nach Ablauf nicht mehr frisch", not GB.ist_frisch("tokA", "anna", jetzt=1000.0 + 300))
check("Restzeit wird gemeldet", GB.restzeit("tokA", "anna", jetzt=1100.0) == 200)
check("das Token selbst wird nicht gespeichert (nur sein Hash)",
      "tokA" not in json.dumps(list(GB._frisch.keys())))
GB.verwerfen("tokA")
check("verwerfen beendet das Fenster", not GB.ist_frisch("tokA", "anna", jetzt=1001.0))

# ══ 7. main.py ═════════════════════════════════════════════════════════════
abschnitt("7 – main.py: Bestaetigung vor jedem Klartext, Maskierung")

MAIN = (ROOT / "backend" / "main.py").read_text()
MB = ast.parse(MAIN)
FN = {n.name: n for n in MB.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for noetig in ("_geheimnis_modulschluessel_verpacken",
               "secret_reveal", "get_agent_key", "get_profile_key", "_bestaetigung_fehlt",
               "geheimnis_bestaetigen", "get_skill_config", "update_skill_config",
               "agent_keys_list", "webdav_status", "_caps_gespeichertes_profil",
               "test_profile_connection", "list_profile_models", "_login_ablauf"):
    if noetig not in FN:
        abbruch("main.py: Funktion %s fehlt" % noetig)


_hook = FN["_geheimnis_modulschluessel_verpacken"]
check("⚠ main.py verpackt die Modulschluessel beim START (startup-Hook)",
      any(ast.unparse(dk) == "app.on_event('startup')" for dk in _hook.decorator_list)
      and "alle_modulschluessel_verpacken" in ast.unparse(_hook)
      and "_load_auth_state" in ast.unparse(_hook) and "knowledge_sync" in ast.unparse(_hook),
      [ast.unparse(dk) for dk in _hook.decorator_list])
# Die Modul-Schluessel stehen im Tresor UND in den Modulen – gleiche Namen
for name, datei in (("mail_accounts", ".mailkey"), ("sap_accounts", ".sapkey"),
                    ("vemas_accounts", ".vemaskey"), ("jira_accounts", ".jirakey"),
                    ("confluence_accounts", ".confluencekey"),
                    ("mount_credentials", ".mountkey"), ("ai_mouse_signatur", ".aimousesignkey")):
    mod = sys.modules.get("backend." + name)
    check("%s: Schluesseldatei %s steht in MODUL_SCHLUESSEL" % (name, datei),
          mod is not None and Path(mod.SCHLUESSEL_DATEI).name == datei and datei in T.MODUL_SCHLUESSEL,
          mod and Path(mod.SCHLUESSEL_DATEI).name)


def erste_zeile(fn, muster):
    z = [k.lineno for k in ast.walk(fn) if isinstance(k, ast.Call) and muster(ast.unparse(k))]
    return min(z) if z else None


for name, danach in (("secret_reveal", lambda s: s.startswith("_sr.drossel_ok")),
                     ("get_agent_key", lambda s: s.startswith("JSONResponse({'agent_api_key'")),
                     ("get_profile_key", lambda s: s.startswith("JSONResponse({'api_key'"))):
    zb = erste_zeile(FN[name], lambda s: s.startswith("_bestaetigung_fehlt("))
    zd = erste_zeile(FN[name], danach)
    check("⚠ %s prueft die Bestaetigung VOR der Herausgabe" % name,
          zb is not None and zd is not None and zb < zd, "%s / %s" % (zb, zd))


class Antwort:
    def __init__(self, content, status_code=200, headers=None):
        self.content, self.status_code = content, status_code


class Anfrage:
    def __init__(self, body=None, token="tokA", ip="192.0.2.5"):
        self._body = body
        self.headers = {"Authorization": "Bearer " + token}
        self.client = types.SimpleNamespace(host=ip)

    async def json(self):
        return self._body


def schneide(name, ns):
    k = ast.parse(ast.unparse(FN[name])).body[0]
    k.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[k], type_ignores=[])),
                 "<main:%s>" % name, "exec"), ns)
    return ns[name]


LOOP = asyncio.new_event_loop()
GB._reset_fuer_tests()
ns = {"JSONResponse": Antwort, "Request": Anfrage, "_geheimnis_best": GB,
      "_anfrage_token": lambda r: r.headers.get("Authorization", "").replace("Bearer ", "")}
bf = schneide("_bestaetigung_fehlt", ns)
r = bf(Anfrage(), "anna")
check("_bestaetigung_fehlt: unbestaetigt → 403 mit reauth",
      r is not None and r.status_code == 403 and r.content.get("reauth") is True)
check("⚠ … NICHT 401 (die Seiten werten 401 als 'abgemeldet')", r is not None and r.status_code != 401)
GB.vermerken("tokA", "anna")
check("… bestaetigt → None", bf(Anfrage(), "anna") is None)
GB._reset_fuer_tests()

# Die beiden GET-Wege zum Klartext AUSGEFUEHRT (die Reihenfolge allein misst
# keine Wirkung – von der Gegenprobe gezeigt)
ABRUFE = []
ns_g = {"JSONResponse": Antwort, "Request": Anfrage, "Depends": lambda x: None,
        "require_local_auth": None, "_bestaetigung_fehlt": bf,
        "_klartext_abruf_protokollieren": lambda u, w, e: ABRUFE.append((u, w, e)),
        "config": types.SimpleNamespace(
            AGENT_API_KEY="AgentAlt!9",
            profiles=[{"id": "p1", "api_key": "sk-echt", "session_key": "sess"}])}
gak = schneide("get_agent_key", ns_g)
gpk = schneide("get_profile_key", ns_g)
GB._reset_fuer_tests()
for name, aufruf, geheim in (("agentkey", lambda: gak(Anfrage(), user="chef"), "AgentAlt!9"),
                             ("profil", lambda: gpk("p1", Anfrage(), user="chef"), "sk-echt")):
    ABRUFE.clear()
    r = LOOP.run_until_complete(aufruf())
    check("⚠ GET %s ohne Bestaetigung: 403 ohne Wert" % name,
          r.status_code == 403 and geheim not in json.dumps(r.content), (r.status_code, r.content))
    check("… und protokolliert", ABRUFE and ABRUFE[-1][2] == "bestaetigung fehlt", ABRUFE)
    GB.vermerken("tokA", "chef")
    r = LOOP.run_until_complete(aufruf())
    check("Positivkontrolle: bestaetigt kommt der Wert (%s)" % name,
          r.status_code == 200 and geheim in json.dumps(r.content), (r.status_code, r.content))
    GB._reset_fuer_tests()

# Bestaetigungs-Endpunkt ausgefuehrt
PROT = {"fehl": [], "erfolg": [], "auth": [], "sperre": None, "log": []}


def _auth(user, pw):
    PROT["auth"].append(user)
    return pw == "Richtig!1"


ns = {
    "JSONResponse": Antwort, "Request": Anfrage, "Depends": lambda x: None, "require_auth": None,
    "asyncio": asyncio, "_geheimnis_best": GB,
    "_anfrage_token": lambda r: r.headers.get("Authorization", "").replace("Bearer ", ""),
    "_konto_sperre_antwort": lambda u: PROT["sperre"],
    "_check_rate_limit": lambda ip: True,
    "_get_user_auth_state": lambda u: {},
    "authenticate_linux_user": _auth,
    "_record_login_attempt": lambda ip, u: PROT["fehl"].append((ip, u)),
    "_anmelde_schutz": types.SimpleNamespace(erfolg=lambda k: PROT["erfolg"].append(k)),
    "_norm_login": lambda u: u.lower(),
    "_sicherheits_log": types.SimpleNamespace(
        ereignis=lambda art, **kw: PROT["log"].append((art, kw))),
}
# ⚠ LATENTE LUECKE, gemessen am 2026-10-12 statt abgewartet.
# `geheimnis_bestaetigen` referenziert `_totp_schutz.pruefen(...)` in einem
# Zweig, den die hiesigen Faelle nicht betreten - der NameError waere erst
# aufgetreten, wenn jemand einen TOTP-Fall ergaenzt, und haette dann wie ein
# Produktfehler ausgesehen. Auch hier das ECHTE Modul: eine Attrappe, die OK
# zurueckgibt, machte genau die Pruefung trivial wahr, fuer die man den Zweig
# ergaenzt.
ns["_totp_schutz"] = _totp_schutz
best = schneide("geheimnis_bestaetigen", ns)
r = LOOP.run_until_complete(best(Anfrage({"password": "falsch"}), user="anna"))
check("falsches Kennwort: 403", r.status_code == 403, r.status_code)
check("⚠ … zaehlt beim Anmeldeschutz als Fehlversuch (je IP und Konto)",
      PROT["fehl"] == [("192.0.2.5", "anna")], PROT["fehl"])
check("⚠ … und die Sitzung ist NICHT frei", not GB.ist_frisch("tokA", "anna"))
check("… ins Sicherheitsprotokoll, ohne Kennwort",
      PROT["log"] and PROT["log"][-1][1].get("ergebnis") == "fehlgeschlagen"
      and "falsch" not in json.dumps(PROT["log"]), PROT["log"])
r = LOOP.run_until_complete(best(Anfrage({"password": "Richtig!1"}), user="anna"))
check("Positivkontrolle: richtiges Kennwort → frei", r.status_code == 200 and GB.ist_frisch("tokA", "anna"),
      r.content)
check("… Konto-Zaehler zurueckgesetzt", PROT["erfolg"] == ["anna"])
GB._reset_fuer_tests()
PROT["auth"].clear()
PROT["sperre"] = Antwort({"error": "gesperrt"}, 429)
r = LOOP.run_until_complete(best(Anfrage({"password": "Richtig!1"}), user="anna"))
check("⚠ Konto gesperrt: 429 und KEIN Kennwort geht an PAM/AD",
      r.status_code == 429 and PROT["auth"] == [], (r.status_code, PROT["auth"]))
PROT["sperre"] = None
r = LOOP.run_until_complete(best(Anfrage({"code": "123456"}), user="anna"))
check("⚠ ein Code ohne eingerichtete 2FA gibt nichts frei",
      r.status_code == 403 and not GB.ist_frisch("tokA", "anna"), r.status_code)
r = LOOP.run_until_complete(best(Anfrage({}), user="anna"))
check("leerer Rumpf: 400", r.status_code == 400)
GB._reset_fuer_tests()

# Skill-Konfiguration: maskiert lesen, leer = unveraendert
SPEICHER = {"jira": {"api_token": "JiraTok", "base_url": "https://j", "max_results": 50,
                     "webdav": {"url": "https://dav", "password": "Dav"}}}


class _SM:
    def get_skill_config(self, name):
        return json.loads(json.dumps(SPEICHER.get(name, {})))

    def update_skill_config(self, name, data):
        SPEICHER.setdefault(name, {}).update(data)
        return True


ns = {"JSONResponse": Antwort, "Request": Anfrage, "Depends": lambda x: None,
      "require_local_auth": None, "_get_skill_manager": lambda: _SM(), "os": os,
      "_update_env_google": lambda a, b: None}
gsc = schneide("get_skill_config", ns)
usc = schneide("update_skill_config", ns)
r = LOOP.run_until_complete(gsc("jira", user="chef"))
check("Positivkontrolle: Skill-Config kommt", r.content["config"].get("base_url") == "https://j")
check("⚠ GET /api/skills/{name}/config gibt kein Geheimfeld heraus",
      "JiraTok" not in json.dumps(r.content) and "Dav" not in json.dumps(r.content), r.content)
check("… und sagt, welche gesetzt sind",
      sorted(r.content.get("geheim_gesetzt") or []) == ["api_token", "webdav.password"],
      r.content.get("geheim_gesetzt"))
LOOP.run_until_complete(usc("jira", Anfrage({"api_token": "", "base_url": "https://j/",
                                              "max_results": 70,
                                              "webdav": {"url": "https://dav", "password": ""}}),
                            user="chef"))
check("⚠ leer gespeichert = unveraendert (auch verschachtelt)",
      SPEICHER["jira"]["api_token"] == "JiraTok" and SPEICHER["jira"]["webdav"]["password"] == "Dav"
      and SPEICHER["jira"]["max_results"] == 70, SPEICHER["jira"])

# ⚠ Code-Review 2026-10-07: neue Adresse + "unveraendertes" Geheimnis schickte
# den gespeicherten Wert an die neue Adresse – ohne Eingabe, ohne Auge.
for rumpf, was in (({"api_token": "", "base_url": "https://angreifer.example"}, "Token leer"),
                   ({"base_url": "https://angreifer.example"}, "Token weggelassen"),
                   ({"base_url": "https://angreifer.example", "ibs_api_key": "x"},
                    "nur ein FREMDES Geheimnis neu")):
    vorher = json.dumps(SPEICHER["jira"], sort_keys=True)
    r = LOOP.run_until_complete(usc("jira", Anfrage(rumpf), user="chef"))
    check("⚠ Adresse neu, %s → 400, nichts gespeichert" % was,
          r.status_code == 400 and r.content.get("code") == "geheimnis_neu_eingeben"
          and json.dumps(SPEICHER["jira"], sort_keys=True) == vorher, (r.status_code, SPEICHER["jira"]))
r = LOOP.run_until_complete(usc("jira", Anfrage({"webdav": {"url": "https://angreifer.example",
                                                            "password": ""}}), user="chef"))
check("⚠ verschachtelt: webdav.url neu, webdav.password leer → 400", r.status_code == 400,
      r.status_code)
r = LOOP.run_until_complete(usc("jira", Anfrage({"base_url": "https://neu", "api_token": "NeuTok"}),
                                user="chef"))
check("Positivkontrolle: Adresse neu MIT neuem Token → gespeichert",
      getattr(r, "status_code", 200) == 200 and SPEICHER["jira"]["base_url"] == "https://neu"
      and SPEICHER["jira"]["api_token"] == "NeuTok", SPEICHER["jira"])
SPEICHER["jira"].update({"ibs_api_url": "https://ibs", "ibs_api_key": "IbsKey"})
r = LOOP.run_until_complete(usc("jira", Anfrage({"ibs_api_url": "https://ibs-neu", "ibs_api_key": "K2"}),
                                user="chef"))
check("Positivkontrolle: zweiter Zugang im selben Objekt zieht um, ohne das Jira-Token",
      getattr(r, "status_code", 200) == 200 and SPEICHER["jira"]["ibs_api_url"] == "https://ibs-neu",
      getattr(r, "content", r))
r = LOOP.run_until_complete(usc("jira", Anfrage({"ibs_api_url": "https://angreifer.example"}),
                                user="chef"))
check("⚠ … aber nicht ohne SEINEN Schluessel", r.status_code == 400, r.status_code)
LOOP.run_until_complete(usc("jira", Anfrage({"api_token": "NeuTok2"}), user="chef"))
check("ein neuer Wert ersetzt den alten", SPEICHER["jira"]["api_token"] == "NeuTok2")

# Agent-Keys: Liste ohne Schluessel
KEYS = [{"id": "k1", "name": "n", "key": "AgentGeheim123456", "created": 1}]
# ⚠ DAS ECHTE MODUL, KEINE ATTRAPPE. `agent_keys_list` ruft seit f41d3401
# `_wirkung_h9.agent_api_freigabe()`; main.py importiert das auf Modulebene,
# der Schnitt sieht es nicht - der Lauf starb mit "NameError: name
# '_wirkung_h9' is not defined" (CI 38219452485/38220512404). Register: "ein
# neu aufgerufener HELFER gehoert ebenfalls in den Prolog", und ausdruecklich
# das ECHTE Modul: eine Attrappe, die die Freigabe frei erfindet, laesst jede
# kuenftige Pruefung darauf trivial gruen werden. backend/wirkung.py ist
# gefahrlos importierbar (nur Standardbibliothek, keine Seiteneffekte).
ns = {"JSONResponse": Antwort, "Depends": lambda x: None, "require_local_auth": None,
      "_load_agent_keys": lambda: json.loads(json.dumps(KEYS)),
      "_wirkung_h9": _wirkung_h9,
      "config": types.SimpleNamespace(AGENT_API_KEY="")}
schneide("_agent_key_maskiert", ns)
akl = schneide("agent_keys_list", ns)
r = LOOP.run_until_complete(akl(user="chef"))
check("⚠ GET /api/agent/keys gibt keinen Schluessel heraus",
      "AgentGeheim123456" not in json.dumps(r.content), r.content)
check("… aber 'gesetzt' und die letzten Zeichen zum Wiedererkennen",
      r.content["keys"][0].get("key_gesetzt") is True and r.content["keys"][0].get("key_ende") == "3456",
      r.content)

# WebDAV-Status: kein Kennwort
pw_werte = [ast.unparse(v) for k in ast.walk(FN["webdav_status"]) if isinstance(k, ast.Dict)
            for kk, v in zip(k.keys, k.values) if isinstance(kk, ast.Constant) and kk.value == "password"]
check("⚠ GET /api/knowledge/webdav/status: 'password' ist leer", pw_werte == ["''"], pw_werte)

# Gespeicherter LLM-Schluessel nur an die gespeicherte Adresse
PROFILE = [{"id": "p1", "provider": "openai", "api_url": "https://api.anbieter.example/v1/",
            "api_key": "sk-echt", "session_key": ""}]
ns = {"config": types.SimpleNamespace(profiles=PROFILE)}
gp = schneide("_caps_gespeichertes_profil", ns)
schneide("_caps_key", ns)
ck = ns["_caps_key"]
basis = {"profile_id": "p1", "provider": "openai", "api_url": "https://api.anbieter.example/v1"}
check("Positivkontrolle: gleiche Adresse (ohne / am Ende) → gespeicherter Key",
      ck(dict(basis, api_key="")) == "sk-echt")
check("⚠ fremde Adresse → der gespeicherte Key springt NICHT ein",
      ck(dict(basis, api_url="https://angreifer.example/v1", api_key="")) == "")
check("⚠ leere Adresse bei gespeicherter → nicht (Standard-Endpunkt waere woanders)",
      ck(dict(basis, api_url="", api_key="")) == "")
check("⚠ anderer Anbieter → nicht", ck(dict(basis, provider="anthropic", api_key="")) == "")
check("ein eingegebener Key wird unveraendert benutzt",
      ck(dict(basis, api_url="https://x", api_key="sk-neu")) == "sk-neu")
for name in ("test_profile_connection", "list_profile_models"):
    rufe = {ast.unparse(k.func) for k in ast.walk(FN[name]) if isinstance(k, ast.Call)}
    check("%s nimmt den Key ueber _caps_key/_caps_session" % name,
          {"_caps_key", "_caps_session"} <= rufe, sorted(rufe))

# ⚠ Code-Review 2026-10-07: PUT /api/profiles/{id} mit neuer api_url und
# leerem Schluessel behielt den Schluessel – der naechste Chat schickte ihn
# an die neue Adresse. Gemessen am echten Endpunkt mit einem Attrappen-config,
# das wie config.update_profile ein leeres/maskiertes Feld behaelt.
class _Cfg:
    def __init__(self):
        self.profiles = [{"id": "p1", "provider": "openai", "api_url": "https://api.anbieter.example/v1",
                          "api_key": "sk-echt", "session_key": ""},
                         {"id": "p2", "provider": "ollama", "api_url": "http://lokal:11434",
                          "api_key": "", "session_key": ""}]

    def update_profile(self, pid, data):
        for p in self.profiles:
            if p["id"] == pid:
                for k, v in data.items():
                    if k in ("api_key", "session_key") and isinstance(v, str) \
                            and (v.startswith("***") or not v.strip()):
                        continue
                    p[k] = v
                return p
        return None


CF = _Cfg()
ns = {"config": CF, "JSONResponse": Antwort, "Request": Anfrage, "Depends": lambda x: None,
      "require_local_auth": None}
schneide("_profil_umleitung", ns)
upd = schneide("update_profile", ns)
for rumpf, was in (({"api_url": "https://angreifer.example/v1", "api_key": ""}, "Schluessel leer"),
                   ({"api_url": "https://angreifer.example/v1", "api_key": "***echt"}, "maskiert"),
                   ({"api_url": "https://angreifer.example/v1"}, "weggelassen"),
                   ({"provider": "anthropic", "api_key": ""}, "nur der Anbieter neu")):
    r = LOOP.run_until_complete(upd("p1", Anfrage(rumpf), user="chef"))
    check("⚠ Profil: %s → 400, Ziel bleibt" % was,
          r.status_code == 400 and r.content.get("code") == "geheimnis_neu_eingeben"
          and CF.profiles[0]["api_url"] == "https://api.anbieter.example/v1"
          and CF.profiles[0]["provider"] == "openai", (r.status_code, CF.profiles[0]))
r = LOOP.run_until_complete(upd("p1", Anfrage({"api_url": "https://api.anbieter.example/v1/",
                                               "api_key": "", "model": "m2"}), user="chef"))
check("Positivkontrolle: gleiche Adresse (mit /), Schluessel leer → gespeichert, Key bleibt",
      r.status_code == 200 and CF.profiles[0]["model"] == "m2" and CF.profiles[0]["api_key"] == "sk-echt",
      (r.status_code, CF.profiles[0]))
r = LOOP.run_until_complete(upd("p1", Anfrage({"api_url": "https://neu.example/v1", "api_key": "sk-neu"}),
                                user="chef"))
check("Positivkontrolle: neue Adresse MIT neuem Schluessel → gespeichert",
      r.status_code == 200 and CF.profiles[0]["api_url"] == "https://neu.example/v1"
      and CF.profiles[0]["api_key"] == "sk-neu", (r.status_code, CF.profiles[0]))
r = LOOP.run_until_complete(upd("p2", Anfrage({"api_url": "http://anderswo:11434", "api_key": ""}),
                                user="chef"))
check("Positivkontrolle: ohne gespeicherten Schluessel darf die Adresse frei wechseln",
      r.status_code == 200 and CF.profiles[1]["api_url"] == "http://anderswo:11434", r.status_code)

CFGM = ast.parse(CFG)
up = next(n for n in ast.walk(CFGM) if isinstance(n, ast.FunctionDef) and n.name == "update_profile")
check("config.update_profile: leerer Schluessel = unveraendert",
      "not val.strip()" in ast.unparse(up))

# ══ 8. haertung_installieren.sh ════════════════════════════════════════════
abschnitt("8 – Server: Hauptschluessel + LoadCredential (Testmodus)")

SK = ROOT / "deploy" / "security" / "haertung_installieren.sh"


def installieren(conf=""):
    d = TMP / ("inst" + ("_aus" if conf else ""))
    shutil.rmtree(d, ignore_errors=True)
    (d / "units").mkdir(parents=True)
    (d / "logrotate").mkdir()
    (d / "units" / "jarvis.service").write_text("[Service]\nUser=jarvis\n")
    if conf:
        (d / "broker.conf").write_text(conf)
    env = dict(os.environ, JARVIS_HAERTUNG_TEST="1", JARVIS_UNIT_DIR=str(d / "units"),
               JARVIS_LOGROTATE_DIR=str(d / "logrotate"), JARVIS_BROKER_CONF=str(d / "broker.conf"),
               JARVIS_BROKER_AUDIT=str(d / "audit.jsonl"))
    env.pop("JARVIS_GEHEIMNIS_DATEI", None)
    r = subprocess.run(["bash", str(SK), "/opt/jarvis"], env=env, capture_output=True, text=True,
                       timeout=60)
    return d, r


d, r = installieren()
key = d / "geheimnis.key"
dropin = d / "units" / "jarvis.service.d" / "40-geheimnis.conf"
if r.returncode != 0 or not key.exists():
    abbruch("Positivkontrolle: Skript lief nicht / legte keinen Schluessel an (rc=%s): %s"
            % (r.returncode, (r.stderr or r.stdout)[-400:]))
check("⚠ Testlauf legt den Schluessel NEBEN die Test-Units (nie /etc/jarvis)",
      key.exists(), str(key))
try:
    Fernet(key.read_bytes().strip())
    gueltig = True
except Exception as e:  # noqa: BLE001
    gueltig = str(e)
check("der Schluessel ist ein gueltiger Fernet-Schluessel", gueltig is True, gueltig)
check("… Modus 0600", stat.S_IMODE(key.stat().st_mode) == 0o600, oct(key.stat().st_mode))
check("⚠ Drop-in reicht ihn per LoadCredential an jarvis.service",
      dropin.exists() and ("LoadCredential=geheimnis:%s" % key) in dropin.read_text(),
      dropin.read_text() if dropin.exists() else "fehlt")
vorher = key.read_bytes()
# ⚠ DIESELBE Umgebung wie der erste Lauf – ohne JARVIS_GEHEIMNIS_DATEI aus dem
# Test (die erste Fassung erbte sie, schrieb woanders hin und mass damit nichts:
# von der Gegenprobe gefunden).
env2 = dict(os.environ, JARVIS_HAERTUNG_TEST="1", JARVIS_UNIT_DIR=str(d / "units"),
            JARVIS_LOGROTATE_DIR=str(d / "logrotate"), JARVIS_BROKER_CONF=str(d / "broker.conf"),
            JARVIS_BROKER_AUDIT=str(d / "audit.jsonl"))
env2.pop("JARVIS_GEHEIMNIS_DATEI", None)
r2 = subprocess.run(["bash", str(SK), "/opt/jarvis"], capture_output=True, text=True, timeout=60,
                    env=env2)
check("Positivkontrolle: der zweite Lauf lief", r2.returncode == 0, r2.stderr[-200:])
check("⚠⚠ ein zweiter Lauf ERSETZT den Schluessel nicht", key.read_bytes() == vorher)
d2, r2 = installieren(conf="HAERTUNG=aus\n")
check("⚠ HAERTUNG=aus nimmt die Haertung zurueck, NICHT den Zugang zu den Geheimnissen",
      (d2 / "units" / "jarvis.service.d" / "40-geheimnis.conf").exists()
      and not (d2 / "units" / "jarvis.service.d" / "50-haertung.conf").exists())

# ══ 9. Sandbox ═════════════════════════════════════════════════════════════
abschnitt("9 – Werkzeuge kommen nicht an den Hauptschluessel")

try:
    from backend import sandbox as SB
except Exception as e:  # noqa: BLE001
    abbruch("backend.sandbox nicht importierbar: %s" % e)
for p in ("/etc/jarvis/geheimnis.key", "/run/credentials/jarvis.service/geheimnis"):
    check("Dateizugriff gesperrt: %s" % p, SB.is_sensitive(Path(p)))
for cmd in ("cat /etc/jarvis/geheimnis.key", "cat $CREDENTIALS_DIRECTORY/geheimnis",
            "ls /run/credentials/jarvis.service"):
    check("Shell gesperrt: %s" % cmd, bool(SB.SHELL_SECRET_PATHS.search(cmd)))

# ══ 10. Weitere Klartext-Reste: .secret_key, auth_state, knowledge_sync ════
abschnitt("10 – Signierschluessel, 2FA-Secrets, Sync-Token")

from backend import secret_key as SKM  # noqa: E402

mit_haupt()
sk = TMP / "sk" / ".secret_key"
sk.parent.mkdir()
sk.write_text("a" * 64)
w = SKM.aufloesen("", sk)
check("Altbestand: derselbe Signierschluessel", w == "a" * 64, w[:8])
check("⚠ … und die Datei ist danach verpackt", sk.read_text().startswith("JGK1:"))
check("… 0600", stat.S_IMODE(sk.stat().st_mode) == 0o600)
check("⚠ der verpackte wird wieder zum selben Schluessel", SKM.aufloesen("", sk) == "a" * 64)
ohne_haupt()
vorher = sk.read_text()
w2 = SKM.aufloesen("", sk)
check("⚠⚠ ohne Hauptschluessel wird KEIN neuer erzeugt (Datei unveraendert)",
      sk.read_text() == vorher)
# Code-Review 2026-10-07: frueher galt hier das CHIFFRAT als Signierschluessel –
# lesbar fuer jedes Werkzeug unter dem Dienstbenutzer, also Tokens faelschbar.
check("⚠⚠ … und der Schluessel ist NICHT der Dateiinhalt (nicht faelschbar)",
      w2 != vorher and vorher not in w2 and w2 != "a" * 64, w2[:12])
check("… sondern fluechtig: zwei Prozesse bekommen verschiedene",
      len(w2) == 64 and SKM.aufloesen("", sk) != w2)
sk_fremd = TMP / "sk" / ".fremd"
sk_fremd.write_text(vorher[:-8] + "AAAAAAAA")
mit_haupt()
w_fremd = SKM.aufloesen("", sk_fremd)
check("⚠ unpassender Hauptschluessel: ebenfalls nicht der Dateiinhalt",
      w_fremd != sk_fremd.read_text() and len(w_fremd) == 64, w_fremd[:12])

sk2 = TMP / "sk" / ".neu"
w3 = SKM.aufloesen("", sk2)
check("neu erzeugt: 64 Hex-Zeichen, gleich verpackt abgelegt",
      len(w3) == 64 and sk2.read_text().startswith("JGK1:") and SKM.aufloesen("", sk2) == w3)
check("ein Wert aus der Umgebung gilt unveraendert (nichts geschrieben)",
      SKM.aufloesen("x" * 40, TMP / "sk" / ".nie") == "x" * 40 and not (TMP / "sk" / ".nie").exists())

# auth_state: Laden/Speichern aus main.py geschnitten und AUSGEFUEHRT
AS = TMP / "auth_state.json"
AS.write_text(json.dumps({"users": {"jarvis": {"must_change_password": False, "totp_enabled": True,
                                               "totp_secret": "JBSWY3DPEHPK3PXP"},
                                    "anna": {"totp_enabled": False, "totp_secret": None,
                                             "totp_pending_secret": "KRSXG5CTMVRXEZLU"}}}))
ns_a = {"json": json, "os": os, "_AUTH_STATE_FILE": AS, "print": lambda *a, **k: None}
for fn in ("_save_auth_state", "_load_auth_state", "_totp_secret_lesbar"):
    if fn not in FN:
        abbruch("main.py: %s fehlt" % fn)
    schneide(fn, ns_a)
st_a = ns_a["_load_auth_state"]()
check("auth_state: im Speicher stehen die Secrets im Klartext",
      st_a["users"]["jarvis"]["totp_secret"] == "JBSWY3DPEHPK3PXP"
      and st_a["users"]["anna"]["totp_pending_secret"] == "KRSXG5CTMVRXEZLU")
platte = json.loads(AS.read_text())
check("⚠ … auf der Platte verpackt (Altbestand beim Laden umgestellt)",
      T.klartext_felder(platte) == [] and "JBSWY3DPEHPK3PXP" not in AS.read_text(),
      T.klartext_felder(platte))
check("… Merker bleiben lesbar", platte["users"]["jarvis"]["totp_enabled"] is True
      and platte["users"]["anna"]["totp_secret"] is None)
ns_a["_save_auth_state"](st_a)
check("⚠ Speichern verpackt wieder", "JBSWY3DPEHPK3PXP" not in AS.read_text())
ohne_haupt()
st_b = ns_a["_load_auth_state"]()
check("ohne Hauptschluessel: das Secret bleibt verpackt (nicht leer)",
      str(st_b["users"]["jarvis"]["totp_secret"]).startswith(T.PRAEFIX_WERT))
check("⚠ … und gilt als NICHT lesbar (Anmeldung meldet es statt eines 500)",
      ns_a["_totp_secret_lesbar"](st_b["users"]["jarvis"]["totp_secret"]) is False)
mit_haupt()
check("lesbar mit Hauptschluessel",
      ns_a["_totp_secret_lesbar"](ns_a["_load_auth_state"]()["users"]["jarvis"]["totp_secret"]))
lg = FN["_login_ablauf"]
z_guard = erste_zeile(lg, lambda s: s.startswith("_totp_secret_lesbar("))
# seit BSI N3 prueft _totp_schutz.pruefen den Code (pyotp liegt dahinter)
z_totp = erste_zeile(lg, lambda s: s.startswith("_totp_schutz.pruefen(") and "user_state" in s)
check("⚠ Anmeldung prueft die Lesbarkeit VOR pyotp", z_guard and z_totp and z_guard < z_totp,
      (z_guard, z_totp))

# knowledge_sync: Token verpackt auf der Platte, Klartext im Speicher
import backend.knowledge_sync as KS  # noqa: E402
KS_ALT = KS.STATE_PATH
KS.STATE_PATH = TMP / "knowledge_sync.json"
try:
    KS.STATE_PATH.write_text(json.dumps({"site_name": "x", "shares": [
        {"id": "s1", "folder": "f", "token": "jks_s1.GEHEIMtoken", "enabled": True}],
        "peers": [{"id": "p1", "url": "https://peer.beispiel.de", "token": "jks_p1.PEERtoken"}]}))
    KS._reset_fuer_tests()
    zst = KS._laden()
    check("knowledge_sync: Token im Speicher im Klartext",
          zst["shares"][0]["token"] == "jks_s1.GEHEIMtoken" and zst["peers"][0]["token"] == "jks_p1.PEERtoken")
    txt = KS.STATE_PATH.read_text()
    check("⚠ … auf der Platte verpackt (Altbestand beim Laden umgestellt)",
          "GEHEIMtoken" not in txt and "PEERtoken" not in txt and T.PRAEFIX_WERT in txt)
    KS._speichern()
    check("⚠ Speichern verpackt wieder", "GEHEIMtoken" not in KS.STATE_PATH.read_text())
    KS._reset_fuer_tests()
    check("neu geladen: wieder Klartext", KS._laden()["shares"][0]["token"] == "jks_s1.GEHEIMtoken")
finally:
    KS.STATE_PATH = KS_ALT
    KS._reset_fuer_tests()

# ══ 11. Vorfall ECHT 2026-10-05: Backend lief ohne Hauptschluessel ══════════
abschnitt("11 – Backend ohne Hauptschluessel: melden und nachstarten")

VD = TMP / "vd"
VD.mkdir()
(VD / ".mailkey").write_bytes(Fernet.generate_key())
(VD / "settings.json").write_text(json.dumps({"agent_api_key": "klar"}))
ohne_haupt()
check("Positivkontrolle: nur Rohes, kein Hauptschluessel → nichts zu melden",
      T.verpackt_ohne_schluessel(VD) == [])
mit_haupt()
T.modul_schluessel(VD / ".mailkey")
(VD / "settings.json").write_text(json.dumps(T.verschluessele_baum({"agent_api_key": "klar"})))
check("mit Hauptschluessel: nichts zu melden", T.verpackt_ohne_schluessel(VD) == [])
ohne_haupt()
gem = T.verpackt_ohne_schluessel(VD)
check("⚠ verpackt + KEIN Hauptschluessel: wird gemeldet (mit Dateinamen)",
      ".mailkey" in gem and "settings.json" in gem, gem)
mit_haupt()
_hk = ast.unparse(FN["_geheimnis_modulschluessel_verpacken"])
check("⚠ der Start-Hook meldet es (Journal + Sicherheitsprotokoll)",
      "verpackt_ohne_schluessel" in _hk and "geheimnis_schluessel_fehlt" in _hk)

FAKE = TMP / "fake_systemctl.sh"
LOG = TMP / "systemctl.log"
FAKE.write_text('#!/bin/bash\necho "$*" >> "%s"\n'
                'if [ "$1" = "is-active" ]; then [ "${FAKE_AKTIV:-1}" = "1" ]; exit $?; fi\nexit 0\n' % LOG)
FAKE.chmod(0o755)


def nachstart(aktiv, cred, conf=""):
    d = TMP / ("ns_%s_%s_%s" % (aktiv, cred, bool(conf)))
    shutil.rmtree(d, ignore_errors=True)
    (d / "units").mkdir(parents=True)
    (d / "logrotate").mkdir()
    (d / "units" / "jarvis.service").write_text("[Service]\nUser=jarvis\n")
    if conf:
        (d / "broker.conf").write_text(conf)
    cr = d / "cred"
    if cred:
        (cr / "jarvis.service").mkdir(parents=True)
        (cr / "jarvis.service" / "geheimnis").write_text("x")
    if LOG.exists():
        LOG.unlink()
    env = dict(os.environ, JARVIS_HAERTUNG_TEST="1", JARVIS_UNIT_DIR=str(d / "units"),
               JARVIS_LOGROTATE_DIR=str(d / "logrotate"), JARVIS_BROKER_CONF=str(d / "broker.conf"),
               JARVIS_BROKER_AUDIT=str(d / "audit.jsonl"), JARVIS_SYSTEMCTL=str(FAKE),
               JARVIS_CRED_ROOT=str(cr), FAKE_AKTIV="1" if aktiv else "0")
    env.pop("JARVIS_GEHEIMNIS_DATEI", None)
    r = subprocess.run(["bash", str(SK), "/opt/jarvis"], env=env, capture_output=True, text=True, timeout=60)
    return r, (LOG.read_text() if LOG.exists() else "")


r, log = nachstart(True, False)
check("Positivkontrolle: das nachgebaute systemctl wurde gefragt", "is-active" in log, (r.returncode, log, r.stderr[-200:]))
check("⚠ Backend laeuft OHNE Credential → wird nachgestartet (--no-block)",
      "try-restart --no-block jarvis.service" in log, log)
r, log = nachstart(True, True)
check("⚠ Backend MIT Credential → kein Neustart", "restart" not in log, log)
r, log = nachstart(False, False)
check("Backend laeuft nicht → kein Neustart", "restart" not in log, log)
r, log = nachstart(True, False, conf="HAERTUNG=aus\n")
check("auch bei HAERTUNG=aus (der Zugang zu den Geheimnissen haengt nicht daran)",
      "try-restart --no-block jarvis.service" in log, log)

# ══ Abschluss ══════════════════════════════════════════════════════════════
LOOP.close()
shutil.rmtree(TMP, ignore_errors=True)
# ⚠ DER ABBRUCHGRUND MUSS SAGEN, WAS SICH GEAENDERT HAT.
# Bis 2026-10-12 stand hier nur "der echte data/-Baum hat sich waehrend des
# Laufs geaendert" - richtig und nicht zu gebrauchen: welche Datei, neu oder
# geaendert, von wem? In der CI war der Abbruch ausserdem lange VERDECKT, weil
# der Lauf vorher an einem NameError starb und diese Zeile nie erreichte; als
# er sie erreichte, war die Meldung nicht diagnostizierbar und lokal nicht
# reproduzierbar (dreimal gelaufen, zweimal gruen). Dieselbe Klasse wie
# "node lieferte nichts Lesbares" und "FEHLER - <die SHA>": ein wahrer Grund,
# der den naechsten Schritt nicht nennt.
_nach = _stand(ROOT / "data")
if _nach != DATA_VORHER:
    _neu = sorted(set(_nach) - set(DATA_VORHER))
    _weg = sorted(set(DATA_VORHER) - set(_nach))
    # Gleiche Groesse, andere mtime = ueberschrieben/angetastet; andere
    # Groesse = Inhalt gewachsen. Die Unterscheidung spart beim Suchen eine
    # Runde.
    _geaendert = sorted(k for k in set(DATA_VORHER) & set(_nach) if DATA_VORHER[k] != _nach[k])
    print("  Sandkasten-Diagnose: %d neu, %d weg, %d geaendert"
          % (len(_neu), len(_weg), len(_geaendert)))
    for _art, _liste in (("NEU", _neu), ("WEG", _weg), ("GEAENDERT", _geaendert)):
        for _x in _liste[:8]:
            _zusatz = ""
            if _art == "GEAENDERT":
                _a, _b = DATA_VORHER[_x], _nach[_x]
                _zusatz = ("  (Groesse %d -> %d)" % (_a[1], _b[1])) if _a[1] != _b[1] \
                          else "  (nur mtime - ueberschrieben, Groesse %d)" % _b[1]
            print("    %-9s %s%s" % (_art, _x, _zusatz))
        if len(_liste) > 8:
            print("    %-9s ... und %d weitere" % (_art, len(_liste) - 8))
    abbruch("Sandkasten verletzt: der echte data/-Baum hat sich waehrend des Laufs"
            " geaendert (%d neu, %d weg, %d geaendert - Pfade siehe oben)"
            % (len(_neu), len(_weg), len(_geaendert)))
print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
