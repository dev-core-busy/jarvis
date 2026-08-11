#!/usr/bin/env python3
"""Tests fuer die Pull-Synchronisation von Wissensordnern (backend/knowledge_sync.py).

Laeuft ohne fastapi und ohne httpx-Netzzugriff:

* ``backend.config``, ``backend.tools.knowledge``, ``backend.knowledge_groups``
  und ``backend.license`` werden als Attrappen in ``sys.modules`` gelegt. Der
  ECHTE ``backend.config``-Import wuerde beim Laden die LIVE-``settings.json``
  migrieren und zurueckschreiben (dieselbe Falle wie in test_shell_redirects.py).
* ``httpx`` wird durch einen Client ersetzt, der die beiden Pull-Endpunkte
  DIREKT gegen ``build_manifest``/``resolve_share_file`` derselben Instanz
  bedient. Damit laeuft der echte Sync-Code (Differenz, Pruefsumme, atomares
  Schreiben, Loeschen) gegen einen echten Ordner – nur ohne Netz.

    python3 tests/test_knowledge_sync.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
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


# ── Attrappen VOR dem Import von knowledge_sync ─────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="kbsync_test_"))
WISSEN = TMP / "data" / "knowledge"
FERN = WISSEN / "technik"                 # freigegebener Ordner (Rolle Geber)
FERN.mkdir(parents=True)

_ext = {".txt", ".md", ".pdf", ".csv", ".docx", ".xlsx", ".pptx", ".png"}

_kn = types.ModuleType("backend.tools.knowledge")
_kn.PROJECT_ROOT = TMP
_kn._get_folders = lambda: [WISSEN] + [TMP / f for f in _kn._extra_folders]
_kn._extra_folders = []
_kn.EXTENSIONS_TEXT = {".txt", ".md", ".csv"}
_kn.EXTENSIONS_PDF = {".pdf"}
_kn.EXTENSIONS_DOCX = {".docx"}
_kn.EXTENSIONS_XLSX = {".xlsx"}
_kn.EXTENSIONS_PPTX = {".pptx"}
_kn.EXTENSIONS_VIDEO = set()
_kn.EXTENSIONS_AUDIO = set()
_kn.EXTENSIONS_IMAGE = {".png"}
_kn._reindex_calls = []
_kn.force_reindex = lambda **kw: _kn._reindex_calls.append(kw)
_kn.invalidate_files_cache = lambda: None
_kn._purged = []
_kn.purge_file_index = lambda p: _kn._purged.append(str(p))
_kn.purge_folder_index = lambda p: _kn._purged.append("dir:" + str(p))
_kn.get_disk_file_count = lambda: 0

_kg = types.ModuleType("backend.knowledge_groups")
_kg._groups = [{"id": "ibs", "name": "IBS"}]
_kg._assign = {}
_kg._folder_calls = []
_kg.list_groups = lambda *a, **k: {"groups": list(_kg._groups)}
_kg.get_group = lambda gid: next((g for g in _kg._groups if g["id"] == gid), None)
_kg.set_assignment = lambda rel, gids: _kg._assign.__setitem__(rel, list(gids))
_kg.add_folder_to_groups = lambda rel, gids: _kg._folder_calls.append((rel, list(gids)))

_cfg_state = {"skills": {"knowledge": {"enabled": True, "config": {"folders": "data/knowledge"}}}}
_config = types.SimpleNamespace(
    get_skill_states=lambda: _cfg_state["skills"],
    save_skill_state=lambda name, state: _cfg_state["skills"].__setitem__(name, state),
)
_cfgmod = types.ModuleType("backend.config")
_cfgmod.config = _config
_cfgmod.PROJECT_ROOT = TMP

_lic = types.ModuleType("backend.license")
_lic._erlaubt = True
_lic.standort_sync_erlaubt = lambda: ((True, "") if _lic._erlaubt
                                      else (False, "ENTERPRISE erforderlich"))

import backend  # noqa: E402  (leichtes Paket-Init)
sys.modules["backend.tools.knowledge"] = _kn
sys.modules["backend.knowledge_groups"] = _kg
sys.modules["backend.config"] = _cfgmod
sys.modules["backend.license"] = _lic

from backend import knowledge_sync as ks  # noqa: E402

# Sandkasten-Schranke: zeigt eine Pfadvariable noch ins echte Projekt, bricht
# der Test ab. Ohne das schreibt ein Fehlgriff Testdaten in die Live-Ablage –
# genau das ist am 2026-08-04 beim Retention-Test passiert.
ks.PROJECT_ROOT = TMP
ks.STATE_PATH = TMP / "data" / "knowledge_sync.json"
for _name in ("PROJECT_ROOT", "STATE_PATH"):
    _wert = getattr(ks, _name)
    if not str(_wert).startswith(str(TMP)):
        print(f"ABBRUCH: knowledge_sync.{_name} zeigt auf {_wert}")
        sys.exit(2)
ks._reset_fuer_tests()


def schreibe(pfad: Path, text: str, mtime: float | None = None):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(text, encoding="utf-8")
    if mtime:
        os.utime(pfad, (mtime, mtime))
    return pfad


# ── 1. Token ────────────────────────────────────────────────────────────────
section("1. Token und Freigabe-Auth")
schreibe(FERN / "handbuch.md", "# Handbuch\ninhalt")
share = ks.create_share("data/knowledge/technik", "Technik", "admin")
token = share["token"]
check(token.startswith(ks.TOKEN_PREFIX), "Token traegt das Praefix")
check(token.split(".")[1] == share["id"], "Freigabe-Kennung steckt im Token")
check(len(token.split(".")[2]) >= 40, "Geheimnis ist ausreichend lang")
check(ks.share_by_token(token)["id"] == share["id"], "gueltiges Token findet die Freigabe")
check(ks.share_by_token(token + "x") is None, "veraendertes Token wird abgelehnt")
check(ks.share_by_token("") is None, "leeres Token wird abgelehnt")
check(ks.share_by_token("JARVIS-LIC-1.a.b") is None, "fremdes Praefix wird abgelehnt")
check(ks.share_by_token(ks.TOKEN_PREFIX + "unbekannt.geheim") is None,
      "unbekannte Kennung wird abgelehnt")
check(ks.share_by_token(ks.TOKEN_PREFIX + share["id"]) is None, "Token ohne Geheimnis abgelehnt")

ks.update_share(share["id"], enabled=False)
check(ks.share_by_token(token) is None, "pausierte Freigabe liefert nichts")
ks.update_share(share["id"], enabled=True)
check(ks.share_by_token(token) is not None, "wieder aktiv: Token gilt erneut")

neu = ks.rotate_token(share["id"])
check(ks.share_by_token(token) is None, "altes Token nach Rotation wertlos")
check(ks.share_by_token(neu["token"]) is not None, "neues Token nach Rotation gueltig")
token = neu["token"]

# ── 2. Freigabe-Verwaltung ──────────────────────────────────────────────────
section("2. Freigabe-Verwaltung")
try:
    ks.create_share("data/knowledge/technik")
    check(False, "zweite Freigabe auf denselben Ordner wird abgelehnt")
except ValueError:
    check(True, "zweite Freigabe auf denselben Ordner wird abgelehnt")
for pfad in ("/etc", "data", "../etc", "data/documents"):
    try:
        ks.create_share(pfad)
        check(False, f"Freigabe ausserhalb der Wissensordner abgelehnt ({pfad})")
    except ValueError:
        check(True, f"Freigabe ausserhalb der Wissensordner abgelehnt ({pfad})")

geaendert = ks.update_share(share["id"], label="Neu", folder="data/documents",
                            token="JARVIS-KBS-1.x.y", id="fremd")
check(geaendert["label"] == "Neu", "Beschriftung ist aenderbar")
check(ks.get_share(share["id"])["folder"] == "data/knowledge/technik",
      "folder ist NICHT ueber PATCH aenderbar")
check(ks.share_by_token(token) is not None, "token ist NICHT ueber PATCH aenderbar")
check("token" not in ks.list_shares()[0], "Liste ohne mit_token enthaelt kein Token")
check("token" in ks.list_shares(mit_token=True)[0], "Liste mit_token enthaelt das Token")

ks.record_pull(share["id"], "standort3", "10.0.0.9", 5, 500, art="manifest")
ks.record_pull(share["id"], "standort3", "10.0.0.9", 1, 10, art="datei")
protokoll = ks.get_share(share["id"])["pulls"]
check(len(protokoll) == 1, "nur Manifest-Abrufe landen im Protokoll", str(len(protokoll)))
check(protokoll[0]["site"] == "standort3", "Protokoll nennt den ziehenden Standort")

# ── 3. Manifest ─────────────────────────────────────────────────────────────
section("3. Manifest")
schreibe(FERN / "unter" / "preise.csv", "a;b\n1;2")
schreibe(FERN / "notiz.tmp", "kein Wissensformat")
schreibe(FERN / ".versteckt.md", "versteckt")
schreibe(FERN / ".intern" / "geheim.md", "in verstecktem Ordner")
try:
    (FERN / "ausbruch.md").symlink_to(TMP / "geheim.env")
    schreibe(TMP / "geheim.env", "SECRET=1")
    symlink_moeglich = True
except OSError:
    symlink_moeglich = False

m = ks.build_manifest(ks.get_share(share["id"]))
pfade = {f["path"] for f in m["files"]}
check(m["schema"] == "jarvis-kb-sync/v1", "Manifest traegt das Schema")
check("handbuch.md" in pfade, "Datei im Wurzelordner ist enthalten")
check("unter/preise.csv" in pfade, "Unterordner wird rekursiv erfasst")
check("notiz.tmp" not in pfade, "nicht indizierbare Endung fehlt")
check(".versteckt.md" not in pfade, "versteckte Datei fehlt")
check(not any(p.startswith(".intern") for p in pfade), "versteckter Ordner fehlt")
if symlink_moeglich:
    check("ausbruch.md" not in pfade, "Symlink wird nicht ausgeliefert")
erwartet = hashlib.sha256((FERN / "handbuch.md").read_bytes()).hexdigest()
check(next(f for f in m["files"] if f["path"] == "handbuch.md")["sha256"] == erwartet,
      "SHA-256 stimmt")
check(m["file_count"] == len(m["files"]) == 2, "Dateizahl stimmt", str(m["file_count"]))
check(m["total_bytes"] > 0, "Gesamtgroesse gefuellt")
check(ks.get_share(share["id"]).get("hash_cache"), "Hash-Zwischenspeicher wird gefuellt")

# Hash-Zwischenspeicher: unveraenderte Datei wird nicht neu gehasht
_orig = ks.sha256_datei
_gehasht = []
ks.sha256_datei = lambda p, **kw: (_gehasht.append(str(p)), _orig(p, **kw))[1]
ks.build_manifest(ks.get_share(share["id"]))
check(not _gehasht, "unveraenderte Dateien werden nicht erneut gehasht", str(_gehasht))
schreibe(FERN / "handbuch.md", "# Handbuch\ngeaendert")
ks.build_manifest(ks.get_share(share["id"]))
check(any("handbuch.md" in g for g in _gehasht), "geaenderte Datei wird neu gehasht")
ks.sha256_datei = _orig

# Deckel
_alt_max = ks.MAX_DATEIEN
ks.MAX_DATEIEN = 1
m1 = ks.build_manifest(ks.get_share(share["id"]))
check(m1["file_count"] == 1 and m1["skipped"] >= 1,
      "Deckel greift UND weist die Kuerzung aus", json.dumps(m1["skipped"]))
ks.MAX_DATEIEN = _alt_max

# ── 4. Dateiausgabe der Freigabe ────────────────────────────────────────────
section("4. resolve_share_file (Geber-Seite)")
sh = ks.get_share(share["id"])
check(ks.resolve_share_file(sh, "handbuch.md") is not None, "gueltige Datei wird aufgeloest")
for boese in ("../../.env", "/etc/passwd", "..%2f.env", "unter/../../geheim.env",
              ".versteckt.md", "notiz.tmp", "", "handbuch.md\x00.txt", "nichtda.md"):
    check(ks.resolve_share_file(sh, boese) is None, f"abgewiesen: {boese!r}")
if symlink_moeglich:
    check(ks.resolve_share_file(sh, "ausbruch.md") is None, "Symlink wird nicht ausgeliefert")

# ── 5. Standort-Eintraege (Nehmer) ──────────────────────────────────────────
section("5. Standort-Eintraege")
check(ks.normalisiere_url("https://host:8443/api/x") == "https://host:8443",
      "URL wird auf Schema+Host+Port gekuerzt")
check(ks.normalisiere_url("host") == "https://host", "fehlendes Schema wird ergaenzt")
check(ks.normalisiere_url("HTTPS://Host.Example") == "https://host.example",
      "Schema in Grossbuchstaben wird angenommen")
for schlecht in ("http://host", "", "https://", "ftp://host", "https:///pfad"):
    try:
        ks.normalisiere_url(schlecht)
        check(False, f"URL abgelehnt: {schlecht!r}")
    except ValueError:
        check(True, f"URL abgelehnt: {schlecht!r}")

for ziel in ("knowledge/x", "data/", "data/../etc", "data/a/b", "data/.geheim",
             "data/mit leerzeichen"):
    try:
        ks._pruefe_ziel(ziel)
        check(False, f"Zielordner abgelehnt: {ziel!r}")
    except ValueError:
        check(True, f"Zielordner abgelehnt: {ziel!r}")
try:
    ks._pruefe_ziel("data/knowledge")
    check(False, "bestehender Wissensordner als Ziel abgelehnt")
except ValueError:
    check(True, "bestehender Wissensordner als Ziel abgelehnt")

try:
    ks.create_peer("Standort 1", "https://s1", "falsches-token", "data/s1_technik")
    check(False, "Token ohne Praefix wird abgelehnt")
except ValueError:
    check(True, "Token ohne Praefix wird abgelehnt")

peer = ks.create_peer("Standort 1", "https://s1.example", token, "data/s1_technik",
                      group_id="ibs", fingerprint="sha256:aa", auto=False,
                      interval=30, unit="minutes")
check(peer["target_folder"] == "data/s1_technik", "Zielordner gespeichert")
check("token" not in peer and peer["token_set"] is True,
      "Token geht nicht an die Oberflaeche, nur die Tatsache")
try:
    ks.create_peer("Standort 2", "https://s2.example", token, "data/s1_technik")
    check(False, "zweiter Standort auf dasselbe Ziel abgelehnt")
except ValueError:
    check(True, "zweiter Standort auf dasselbe Ziel abgelehnt")

check(ks._intervall_sek({"interval": 1, "unit": "minutes"}) == ks.MIN_INTERVALL_SEK,
      "Intervall-Untergrenze greift")
check(ks._intervall_sek({"interval": 2, "unit": "hours"}) == 7200, "Stunden werden gerechnet")
check(ks._intervall_sek({"interval": 1, "unit": "days"}) == 86400, "Tage werden gerechnet")
check(ks.naechster_lauf(ks.get_peer(peer["id"])) is None, "ohne Automatik kein naechster Lauf")
ks.update_peer(peer["id"], auto=True)
check(ks.naechster_lauf(ks.get_peer(peer["id"])) is not None, "mit Automatik ein naechster Lauf")
check(peer["id"] in ks.faellige_standorte(), "nie gelaufener Standort ist sofort faellig")
ks.update_peer(peer["id"], state="paused")
check(peer["id"] not in ks.faellige_standorte(), "pausierter Standort ist nicht faellig")
ks.update_peer(peer["id"], state="active")

geaendert = ks.update_peer(peer["id"], name="S1", target_folder="data/woanders",
                           interval=6, unit="hours", token="")
check(geaendert["target_folder"] == "data/s1_technik",
      "target_folder ist NICHT ueber PATCH aenderbar")
check(ks.get_peer(peer["id"])["token"] == token, "leeres Token laesst das alte stehen")
check(geaendert["interval"] == 6 and geaendert["unit"] == "hours", "Intervall aenderbar")
check(ks.ziel_vorschlag("Standort 1", "Technik Süd") == "data/standort_1_technik_sued",
      "Zielvorschlag wird entschaerft", ks.ziel_vorschlag("Standort 1", "Technik Süd"))

# ── 6. Spiegel-Schutz ───────────────────────────────────────────────────────
section("6. Spiegel-Schutz")
check(ks.ist_spiegel("data/s1_technik") is True, "der Zielordner selbst ist Spiegel")
check(ks.ist_spiegel("data/s1_technik/unter/a.md") is True, "Pfad darunter ist Spiegel")
check(ks.ist_spiegel("data/s1_technikaehnlich") is False,
      "aehnlich benannter Nachbarordner ist KEIN Spiegel")
check(ks.ist_spiegel("data/knowledge") is False, "eigener Wissensordner ist kein Spiegel")
check(ks.ist_spiegel("") is False, "leerer Pfad ist kein Spiegel")
grund = ks.schreibsperre("data/s1_technik/a.md")
check("S1" in grund and "s1_technik" in grund,
      "Sperrmeldung nennt Standort und Ordner", grund)
check(ks.schreibsperre("data/knowledge/a.md") == "", "kein Grund fuer normale Ordner")

# ── 7. _sicheres_ziel (Schreiben beim Nehmer) ───────────────────────────────
section("7. Zielpfade beim Nehmer")
wurzel = TMP / "data" / "s1_technik"
wurzel.mkdir(parents=True, exist_ok=True)
check(ks._sicheres_ziel(wurzel, "a/b/c.md") is not None, "normaler Unterpfad erlaubt")
for boese in ("../ausbruch.md", "/etc/passwd", "..\\a.md", "C:/a.md", "", ".geheim.md",
              "a/../../b.md", "unter/.punkt/c.md", "datei.exe", "a\x00b.md"):
    check(ks._sicheres_ziel(wurzel, boese) is None, f"abgewiesen: {boese!r}")
if symlink_moeglich:
    (wurzel / "link.md").symlink_to(TMP / "geheim.env")
    check(ks._sicheres_ziel(wurzel, "link.md") is None,
          "vorhandener Symlink wird nicht beschrieben")
    (wurzel / "link.md").unlink()

# ── 8. Lizenz ───────────────────────────────────────────────────────────────
section("8. Lizenz-Gate")
_lic._erlaubt = False
ok, grund = ks.erlaubt()
check(ok is False and "ENTERPRISE" in grund, "ohne Merkmal gesperrt")
bericht = ks.sync_peer(peer["id"])
check(bericht["ok"] is False and bericht.get("license"), "Sync laeuft nicht ohne Lizenz")
check(ks.automatik_lauf().get("skipped") == "license", "Automatik laeuft nicht ohne Lizenz")
_lic._erlaubt = True

# ── 9. Sync gegen die echten Geber-Funktionen ───────────────────────────────
section("9. Sync (echte Differenz, Pruefsumme, Loeschung)")


class _Antwort:
    def __init__(self, code, daten=None, inhalt=b"", fp="sha256:aa"):
        self.status_code = code
        self._daten = daten if daten is not None else {}
        self._inhalt = inhalt
        self.headers = {"content-type": "application/json"}
        stream = types.SimpleNamespace(get_extra_info=lambda k: (
            types.SimpleNamespace(getpeercert=lambda binary_form=False: _FP_DER[0])
            if k == "ssl_object" else None))
        self.extensions = {"network_stream": stream}

    def json(self):
        return self._daten

    def iter_bytes(self, n=65536):
        for i in range(0, len(self._inhalt), n):
            yield self._inhalt[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_FP_DER = [b"zertifikat-A"]          # was der "Server" praesentiert
_FP_A = "sha256:" + hashlib.sha256(b"zertifikat-A").hexdigest()

# Die Zertifikats-Bindung laeuft ueber die TLS-Schicht (ssl-Vertrauensspeicher).
# Im Test gibt es keinen echten Socket, deshalb wird das Holen des Zertifikats
# ersetzt – der Fake-Client prueft danach selbst, ob das gebundene Zertifikat zu
# dem passt, das der "Server" gerade zeigt (genau das macht sonst OpenSSL).
def _zert_stub(url):
    der = _FP_DER[0]
    return {"url": ks.normalisiere_url(url), "host": "x", "port": 443,
            "fingerprint": "sha256:" + hashlib.sha256(der).hexdigest(),
            "cert_pem": "-----PEM-" + der.decode() + "-----"}


ks.zertifikat_abfragen = _zert_stub
_MANIFEST_CODE = [200]
_VERFAELSCHEN = [False]
_EXTRA = [None]                      # zusaetzlicher Manifest-Eintrag (Traversal-Test)


class _TlsFehler(Exception):
    pass


class _FakeClient:
    """Bedient die beiden Pull-Routen direkt aus build_manifest/resolve_share_file.

    ``verify`` ist im echten Betrieb ein SSLContext mit dem gebundenen
    Zertifikat. Hier steht darin das PEM (siehe _ssl_kontext_stub) – passt es
    nicht zu dem, was der "Server" gerade zeigt, wird der Verbindungsaufbau mit
    demselben Text wie von OpenSSL abgelehnt.
    """

    def __init__(self, *a, **kw):
        self.headers = kw.get("headers", {})
        self._gebunden = kw.get("verify")

    def _tls(self):
        """Wie in der Wirklichkeit: der Handschlag scheitert beim ERSTEN Aufruf,
        nicht beim Anlegen des Clients (httpx verbindet erst dann)."""
        gezeigt = "-----PEM-" + _FP_DER[0].decode() + "-----"
        if isinstance(self._gebunden, str) and self._gebunden and self._gebunden != gezeigt:
            raise _TlsFehler("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _share(self):
        return ks.share_by_token(self.headers.get("X-Jarvis-Share-Token", ""))

    def get(self, url, **kw):
        self._tls()
        if _MANIFEST_CODE[0] != 200:
            return _Antwort(_MANIFEST_CODE[0], {"error": "abgelehnt"})
        sh = self._share()
        if sh is None:
            return _Antwort(403, {"error": "Token unbekannt"})
        m = ks.build_manifest(sh)
        if _EXTRA[0]:
            m["files"] = list(m["files"]) + [_EXTRA[0]]
            m["file_count"] = len(m["files"])
        return _Antwort(200, m)

    def stream(self, method, url, **kw):
        self._tls()
        from urllib.parse import parse_qs, urlparse, unquote
        sh = self._share()
        if sh is None:
            return _Antwort(403, {"error": "Token unbekannt"})
        rel = unquote(parse_qs(urlparse(url).query).get("path", [""])[0])
        pfad = ks.resolve_share_file(sh, rel)
        if pfad is None:
            return _Antwort(404, {"error": "nicht gefunden"})
        roh = pfad.read_bytes()
        if _VERFAELSCHEN[0]:
            roh = roh + b"manipuliert"
        return _Antwort(200, {}, roh)


_httpx = types.ModuleType("httpx")
_httpx.Client = _FakeClient
sys.modules["httpx"] = _httpx
ks._ssl_kontext = lambda peer=None: ((peer or {}).get("cert_pem") or "")

ks.update_peer(peer["id"], fingerprint=_FP_A)
_kn._reindex_calls.clear()
b = ks.sync_peer(peer["id"])
check(b["ok"] is True, "erster Lauf erfolgreich", json.dumps(b)[:300])
check(b["added"] == 2 and b["updated"] == 0, f"zwei neue Dateien ({b['added']})")
check((wurzel / "handbuch.md").read_text() == (FERN / "handbuch.md").read_text(),
      "Inhalt stimmt mit dem Geber ueberein")
check((wurzel / "unter" / "preise.csv").is_file(), "Unterordner wurde angelegt")
check(not list(wurzel.rglob("*.kbsync.tmp")), "keine Nebendateien uebrig")
check(_kn._reindex_calls == [{"incremental": True}],
      "Index wird INKREMENTELL nachgezogen", str(_kn._reindex_calls))
check(_kg._assign.get("data/s1_technik/handbuch.md") == ["ibs"],
      "Datei ist der gewaehlten Wissensgruppe zugeordnet")
check(not _kg._folder_calls,
      "Spiegel wird NICHT Ablageziel der Gruppe", str(_kg._folder_calls))
check("data/s1_technik" in _cfg_state["skills"]["knowledge"]["config"]["folders"],
      "Zielordner ist als Wissensordner registriert")
check(ks.gespiegelte_dateien() == 2, "gespiegelte Dateien werden gezaehlt")

b = ks.sync_peer(peer["id"])
check(b["added"] == 0 and b["updated"] == 0 and b["removed"] == 0,
      "zweiter Lauf uebertraegt nichts (inkrementell)", json.dumps(b)[:200])

schreibe(FERN / "handbuch.md", "# Handbuch\nversion 3")
b = ks.sync_peer(peer["id"])
check(b["updated"] == 1 and b["added"] == 0, "geaenderte Datei wird ersetzt")
check("version 3" in (wurzel / "handbuch.md").read_text(), "entfernter Stand gewinnt")

(wurzel / "handbuch.md").unlink()
b = ks.sync_peer(peer["id"])
check(b["added"] == 1, "lokal geloeschte Datei wird wiederhergestellt")

lokal_extra = schreibe(wurzel / "eigene_notiz.md", "lokal angelegt")
b = ks.sync_peer(peer["id"])
check(not lokal_extra.exists() and b["removed"] == 1,
      "lokal zusaetzlich angelegte Datei wird entfernt (Spiegel)")

(FERN / "unter" / "preise.csv").unlink()
b = ks.sync_peer(peer["id"])
check(b["removed"] == 1 and not (wurzel / "unter" / "preise.csv").exists(),
      "entfernt geloeschte Datei verschwindet lokal")
check(not (wurzel / "unter").exists(), "leerer Unterordner wird abgeraeumt")
check(any("preise.csv" in p for p in _kn._purged), "Datei wird aus dem Index genommen")

# Pruefsumme
_VERFAELSCHEN[0] = True
schreibe(FERN / "neu.md", "frischer Inhalt")
b = ks.sync_peer(peer["id"])
check(b["ok"] is True and b["error_count"] == 1, "verfaelschte Datei erzeugt einen Fehler")
check(not (wurzel / "neu.md").exists(), "verfaelschte Datei wird NICHT abgelegt")
check(any("Prüfsumme" in f or "Größe" in f for f in b["errors"]),
      "Fehlermeldung nennt den Grund", json.dumps(b["errors"]))
_VERFAELSCHEN[0] = False
b = ks.sync_peer(peer["id"])
check((wurzel / "neu.md").is_file(), "nach dem Fix wird die Datei geholt")

# Traversal im Manifest
_EXTRA[0] = {"path": "../../ausbruch.md", "size": 5, "mtime": 1, "sha256": "x" * 64}
b = ks.sync_peer(peer["id"])
check(not (TMP / "data" / "ausbruch.md").exists() and not (TMP / "ausbruch.md").exists(),
      "Traversal-Pfad aus dem Manifest schreibt nichts")
check(any("unzul" in f for f in b["errors"]), "Traversal wird als Fehler gemeldet",
      json.dumps(b["errors"]))
_EXTRA[0] = None

# Fingerabdruck
_FP_DER[0] = b"zertifikat-B"
bestand = (wurzel / "handbuch.md").read_text()
b = ks.sync_peer(peer["id"])
check(b["ok"] is False and b.get("fingerprint"), "geaendertes Zertifikat bricht den Lauf ab")
check("erwartet" in b["error"] and "gefunden" in b["error"],
      "Meldung zeigt beide Fingerabdruecke")
check((wurzel / "handbuch.md").read_text() == bestand, "lokale Kopie bleibt unangetastet")
check(ks.get_peer(peer["id"])["last_error"], "Fehler wird am Standort festgehalten")
_FP_DER[0] = b"zertifikat-A"

# Bindung: PEM liegt vor, Uebernahme eines neuen Fingerabdrucks loest sie
check(bool(ks.get_peer(peer["id"]).get("cert_pem")),
      "das Zertifikat selbst ist gebunden (nicht nur der Fingerabdruck)")
_FP_DER[0] = b"zertifikat-C"
_FP_C = "sha256:" + hashlib.sha256(b"zertifikat-C").hexdigest()
ks.update_peer(peer["id"], fingerprint=_FP_C)
check(ks.get_peer(peer["id"]).get("cert_pem") == "",
      "bewusste Uebernahme eines neuen Fingerabdrucks loest die alte Bindung")
b = ks.sync_peer(peer["id"])
check(b["ok"] is True, "danach laeuft der Lauf mit dem neuen Zertifikat", json.dumps(b)[:200])
check(ks.get_peer(peer["id"])["cert_pem"].find("zertifikat-C") > 0,
      "das neue Zertifikat wird gebunden")
ks.update_peer(peer["id"], fingerprint=_FP_A)      # Fingerabdruck A, Server zeigt C
b = ks.sync_peer(peer["id"])
check(b["ok"] is False and b.get("fingerprint"),
      "Fingerabdruck A eingetragen, aber Zertifikat C gezeigt -> abgelehnt", json.dumps(b)[:200])
check(ks.get_peer(peer["id"]).get("cert_pem") == "",
      "und es wird KEIN falsches Zertifikat gebunden")
_FP_DER[0] = b"zertifikat-A"
b = ks.sync_peer(peer["id"])
check(b["ok"] is True, "mit dem passenden Zertifikat laeuft es wieder")

# Widerruf
_MANIFEST_CODE[0] = 403
b = ks.sync_peer(peer["id"])
check(b["ok"] is False and "entzogen" in b["error"], "Widerruf wird als Grund gemeldet")
check((wurzel / "handbuch.md").is_file(), "Kopie bleibt nach Widerruf erhalten")
_MANIFEST_CODE[0] = 200
b = ks.sync_peer(peer["id"])
check(b["ok"] is True, "nach Wiederfreigabe laeuft es weiter")
check(ks.get_peer(peer["id"])["last_error"] == "", "Fehlermeldung wird zurueckgesetzt")

# Pausiert
ks.update_peer(peer["id"], state="paused")
b = ks.sync_peer(peer["id"])
check(b["ok"] is False and "pausiert" in b["error"], "pausierter Standort synchronisiert nicht")
ks.update_peer(peer["id"], state="active")

# ── 10. Persistenz ──────────────────────────────────────────────────────────
section("10. Persistenz und Rechte")
check(ks.STATE_PATH.is_file(), "Zustandsdatei wurde geschrieben")
check(oct(ks.STATE_PATH.stat().st_mode)[-3:] == "640", "Zustandsdatei ist 0640",
      oct(ks.STATE_PATH.stat().st_mode))
roh = json.loads(ks.STATE_PATH.read_text())
check(roh["peers"][0]["target_folder"] == "data/s1_technik", "Standort ist gespeichert")
ks._reset_fuer_tests()
check(len(ks.list_peers()) == 1 and len(ks.list_shares()) == 1,
      "Zustand ueberlebt einen Neustart")
check(ks.get_peer(peer["id"])["manifest"], "Manifest ueberlebt (Grundlage der Differenz)")

ks.STATE_PATH.write_text("{kaputt")
ks._reset_fuer_tests()
check(ks.list_peers() == [] and ks.list_shares() == [],
      "beschaedigte Datei fuehrt zu leerem Zustand statt Absturz")

# ── 11. Standort loeschen ───────────────────────────────────────────────────
section("11. Standort loeschen")
ks._reset_fuer_tests()
ks.STATE_PATH.unlink(missing_ok=True)
ks._reset_fuer_tests()
sh2 = ks.create_share("data/knowledge/technik", "Technik", "admin")
p2 = ks.create_peer("Standort 1", "https://s1.example", sh2["token"], "data/s1_technik",
                    group_id="ibs", fingerprint=_FP_A)
res = ks.delete_peer(p2["id"], daten_entfernen=False)
check(res["ok"] and res["folder_kept"], "Loeschen ohne Daten laesst die Kopie liegen")
check(wurzel.is_dir(), "Ordner ist noch da")
check("data/s1_technik" in _cfg_state["skills"]["knowledge"]["config"]["folders"],
      "Ordner bleibt Wissensordner (weiter durchsuchbar)")
check(ks.ist_spiegel("data/s1_technik") is False,
      "nach dem Loeschen ist der Ordner kein Spiegel mehr (wieder beschreibbar)")

p3 = ks.create_peer("Standort 1", "https://s1.example", sh2["token"], "data/s1_technik",
                    group_id="ibs", fingerprint=_FP_A)
res = ks.delete_peer(p3["id"], daten_entfernen=True)
check(res["ok"] and res["removed_files"] >= 1, "Loeschen mit Daten entfernt Dateien",
      json.dumps(res))
check(not wurzel.exists(), "Ordner ist weg")
check("data/s1_technik" not in _cfg_state["skills"]["knowledge"]["config"]["folders"],
      "Ordner ist als Wissensordner abgemeldet")
check(ks.delete_peer("gibtsnicht")["ok"] is False, "unbekannter Standort -> ok:false")

# ── 12. Quelltext-Waechter ──────────────────────────────────────────────────
section("12. Waechter am Quelltext")
src_main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
for route, dep in (
    ('@app.get("/api/knowledge/shares")', "require_local_auth"),
    ('@app.post("/api/knowledge/shares")', "require_local_auth"),
    ('@app.delete("/api/knowledge/shares/{share_id}")', "require_local_auth"),
    ('@app.get("/api/knowledge/sync")', "require_local_auth"),
    ('@app.post("/api/knowledge/sync/peers")', "require_local_auth"),
    ('@app.post("/api/knowledge/sync/peers/{peer_id}/run")', "require_local_auth"),
    ('@app.post("/api/knowledge/sync/probe")', "require_local_auth"),
):
    i = src_main.find(route)
    check(i > 0 and dep in src_main[i:i + 600], f"{route} haengt an {dep}")
for route in ('@app.get("/api/knowledge/pull/manifest")',
              '@app.get("/api/knowledge/pull/file")'):
    i = src_main.find(route)
    block = src_main[i:i + 900]
    check(i > 0 and "Depends(" not in block.split("async def")[1].split(")")[0],
          f"{route} nutzt Token-Auth statt Sitzung")
    check("_pull_share(request)" in block, f"{route} prueft das Freigabe-Token")
    check("status_code=403" in block, f"{route} antwortet 403 auf ein ungueltiges Token")

check(src_main.count("_kb_mirror_guard(") >= 10,
      "Spiegel-Sperre sitzt an allen Schreibpfaden",
      str(src_main.count("_kb_mirror_guard(")))
for stelle in ('folder: str = Form("data/knowledge")',):
    check(src_main.count(stelle) == 2, "beide Upload-Endpunkte haben einen Zielordner")
check("_kb_mirror_guard(folder)" in src_main, "Upload prueft den Zielordner")

src_sb = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
for liste in ("_APP_DENY_REL", "PRIVATE_FILES"):
    i = src_sb.find(liste)
    check("knowledge_sync.json" in src_sb[i:i + 2500], f"{liste} enthaelt knowledge_sync.json")
check("knowledge_sync\\.json" in src_sb, "SHELL_SECRET_PATHS kennt knowledge_sync.json")

src_lic = (ROOT / "backend" / "license.py").read_text(encoding="utf-8")
check(src_lic.count('"standort_sync": False') == 2
      and '"standort_sync": True' in src_lic,
      "standort_sync nur in ENTERPRISE")
check("def standort_sync_erlaubt" in src_lic, "Lizenz-Gate vorhanden")
src_enf = (ROOT / "backend" / "license_enforce.py").read_text(encoding="utf-8")
check("gespiegelte_dateien" in src_enf, "anzahl_rag zieht gespiegelte Dateien ab")

src_we = (ROOT / "backend" / "web_extractor.py").read_text(encoding="utf-8")
check("_ist_spiegel(rel)" in src_we, "Extraktor legt keine Extrakte in einen Spiegel")

# ── Ende ────────────────────────────────────────────────────────────────────
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
