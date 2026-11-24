#!/usr/bin/env python3
"""Waechter: Schalter "sensible Daten" (backend/sensibel.py, 2026-11-24).

ZUSAGE an den Betreiber: ein sensibler Lauf (Chat oder Short Track)
hinterlaesst KEINE Inhalte in Protokollen, und erzeugte Dateien – auch
temporaere – werden sofort geloescht; Ergebnisse nach dem ersten Download,
spaetestens nach 15 Minuten. Metadaten (wer, wann, Kanal, Werkzeugname,
Dauer) bleiben.

Gemessen wird die WIRKUNG an jeder SENKE, nicht ein Vorkommen im Quelltext:
jede Senke bekommt einen Inhalt mit einer Marke (``GEHEIMWORT``) und muss ihn
ausserhalb des sensiblen Laufs SCHREIBEN (Positivkontrolle – sonst ist das
Fehlen trivial wahr) und innerhalb VERSCHLUCKEN.

Senken (je eine Positivkontrolle + eine Pruefung im sensiblen Lauf):
  Journal stdout/stderr, Logger · LLM-Verlauf (conv_log) · Audit-Log ·
  Sitzungsablage (chat_sessions) · Lernen · Gedaechtnis-Schreibsperre ·
  Telemetrie-Spans · Sicherheitsprotokoll · Short-Tracks-Protokoll ·
  Broker-Journal/Audit · Dokumentablage (Loeschen, Ergebnisfrist,
  Access-Log-Schwaerzung) · privates /tmp (eigene Kennung je Lauf).
Dazu die Verdrahtung in main.py, short_tracks_runner.py und chat.js als
REGEL am Syntaxbaum (main.py laesst sich ohne den ganzen Dienst nicht laden).

Exit 0 = bestanden, 1 = Pruefung fehlgeschlagen, 2 = konnte nicht laufen.

    python3 tests/test_sensibel.py
"""
from __future__ import annotations

import ast
import asyncio
import io
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GEHEIM = "GEHEIMWORT-7f3a"
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


def abbruch(grund):
    print(f"\nABBRUCH (konnte nicht laufen): {grund}")
    sys.exit(2)


# ── Sandkasten und Attrappe fuer backend.config VOR jedem Import ───────────
TMP = Path(tempfile.mkdtemp(prefix="test_sensibel_"))


class _Cfg:
    def get_setting(self, key, default=None):
        return default

    def get_skill_states(self):
        return {}

    def __getattr__(self, name):
        return None


_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = _Cfg()
sys.modules["backend.config"] = _cfg_mod

from backend import sensibel  # noqa: E402
from backend import documents  # noqa: E402
from backend import log_kontext  # noqa: E402
from backend import conv_log  # noqa: E402
from backend import audit_log  # noqa: E402
from backend import chat_sessions  # noqa: E402
from backend import telemetry  # noqa: E402
from backend import short_tracks  # noqa: E402
from backend import url_geheimnis  # noqa: E402
from backend import lauf_tmp  # noqa: E402

# Ablagen in den Sandkasten
documents.DOCS_DIR = TMP / "documents"
documents._REGISTRY = documents.DOCS_DIR / ".owners.json"
conv_log._DATA_DIR = TMP
conv_log._CONV_DIR = TMP / "conv"
conv_log._INDEX = conv_log._CONV_DIR / "index.jsonl"
conv_log._OLD_FILE = TMP / "conv_log_alt.json"
audit_log.AUDIT_FILE = TMP / "audit.jsonl"
chat_sessions._ROOT = TMP / "chats"
short_tracks.DATA_DIR = TMP
short_tracks.PROTOKOLL_DATEI = TMP / "short_tracks_log.jsonl"
telemetry._ERRORS_FILE = TMP / "telemetry_errors.json"

for _p in (documents.DOCS_DIR, conv_log._CONV_DIR, audit_log.AUDIT_FILE,
           chat_sessions._ROOT, short_tracks.PROTOKOLL_DATEI, telemetry._ERRORS_FILE):
    if TMP not in Path(_p).parents:
        abbruch(f"{_p} liegt nicht im Sandkasten")


def lesen(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def baum_text(wurzel: Path) -> str:
    """Alle Dateien unter ``wurzel`` als ein Text (fuer "steht das Wort IRGENDWO?")."""
    if not wurzel.exists():
        return ""
    return "\n".join(lesen(f) for f in wurzel.rglob("*") if f.is_file())


async def im_lauf(fn):
    """``fn()`` in einem sensiblen Lauf (wie der Chat ihn oeffnet)."""
    async with sensibel.anfrage(True):
        return fn()


def sync_im_lauf(fn):
    with sensibel.scope(True):
        return fn()


# ══════════════════════════════════════════════════════════════════════════
section("1. Grundlagen: Merkmal, Vererbung, ausdrueckliches Setzen")
check(not sensibel.aktiv(), "ausserhalb eines Laufs: nicht sensibel")
with sensibel.scope(True):
    check(sensibel.aktiv(), "im Lauf: sensibel")
    d_aussen = sensibel._lauf()
    with sensibel.scope(True):
        check(sensibel._lauf() is d_aussen, "verschachtelter Lauf ERBT (ein Aufraeumen sieht alles)")
check(not sensibel.aktiv(), "nach dem Lauf: nicht sensibel")
with sensibel.scope(False):
    check(not sensibel.aktiv(), "scope(False) ist ein Leerlauf")


async def _erbt_task():
    async with sensibel.anfrage(True):
        t = asyncio.create_task(asyncio.sleep(0, result=sensibel.aktiv()))
        return await t
check(asyncio.run(_erbt_task()), "create_task erbt das Merkmal (Hintergrundlauf, Lernen)")


async def _fortsetzen_none():
    async with sensibel.anfrage(True):
        async with sensibel.fortsetzen(None):
            return sensibel.aktiv()
check(asyncio.run(_fortsetzen_none()) is False,
      "fortsetzen(None) setzt AUSDRUECKLICH 'nicht sensibel' (Warteschlange erbt sonst)")


# ══════════════════════════════════════════════════════════════════════════
section("2. Journal: stdout, stderr, Logger")
ziel = io.StringIO()
strom = log_kontext._KontextStrom(ziel)
strom.write("normal " + GEHEIM + "\n")
check(GEHEIM in ziel.getvalue(), "Positivkontrolle: ausserhalb erscheint der Inhalt")
ziel2 = io.StringIO()
strom2 = log_kontext._KontextStrom(ziel2)
with sensibel.scope(True):
    with log_kontext.lauf(wer="max.muster", kanal="browser"):
        # print(a, b) schreibt mehrfach – jede Teilausgabe muss verschwinden
        strom2.write("Auftrag:"); strom2.write(" "); strom2.write(GEHEIM); strom2.write("\n")
        strom2.write("Zeile1 " + GEHEIM + "\nZeile2 " + GEHEIM + "\n")
out = ziel2.getvalue()
check(GEHEIM not in out, "im Lauf: kein Inhalt auf stdout", repr(out[:200]))
check(log_kontext.UNTERDRUECKT in out, "im Lauf: Marke statt Inhalt")
check("wer=max.muster" in out, "Metadatum (wer) bleibt an der Zeile")
ziel3 = io.StringIO()
strom3 = log_kontext._KontextStrom(ziel3, kennzeichnen=False)
with sensibel.scope(True):
    strom3.write("Traceback ... " + GEHEIM + "\n")
check(GEHEIM not in ziel3.getvalue(), "stderr-Huelle verschluckt ebenfalls")

rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "Fehler %s", (GEHEIM,), None)
log_kontext.KontextFilter().filter(rec)
check(GEHEIM in rec.getMessage(), "Positivkontrolle: Logger ausserhalb unveraendert")
try:
    raise ValueError(GEHEIM)
except ValueError:
    exc = sys.exc_info()
rec2 = logging.LogRecord("x", logging.ERROR, __file__, 1, "Fehler %s", (GEHEIM,), exc)
with sensibel.scope(True):
    log_kontext.KontextFilter().filter(rec2)
check(GEHEIM not in rec2.getMessage() and rec2.exc_info is None,
      "Logger im Lauf: Text, Argumente und Traceback weg")
check(rec2.levelname == "ERROR" and rec2.name == "x", "Stufe und Logger-Name bleiben")


# ══════════════════════════════════════════════════════════════════════════
section("3. LLM-Verlauf (conv_log)")


def _conv(task):
    conv_log.log_conversation(task=task, model="m1", client_ip="192.0.2.1",
                              client_type="browser", system_prompt="SP " + GEHEIM,
                              messages=[{"role": "user", "content": GEHEIM}],
                              steps=2, duration_ms=10, error="E " + GEHEIM,
                              username="max.muster")


_conv("normal " + GEHEIM)
check(GEHEIM in baum_text(conv_log._CONV_DIR), "Positivkontrolle: ausserhalb steht der Inhalt im Verlauf")
shutil.rmtree(conv_log._CONV_DIR)
sync_im_lauf(lambda: _conv("sensibel " + GEHEIM))
txt = baum_text(conv_log._CONV_DIR)
check(txt and GEHEIM not in txt, "im Lauf: kein Inhalt in Index oder Rumpf", txt[:200])
idx = [json.loads(z) for z in lesen(conv_log._INDEX).splitlines() if z.strip()]
check(len(idx) == 1 and idx[0].get("username") == "max.muster" and idx[0].get("steps") == 2
      and idx[0].get("sensibel") is True,
      "Eintrag bleibt mit Metadaten (wer, Schritte) und Merkmal")


# ══════════════════════════════════════════════════════════════════════════
section("4. Audit-Log")
audit_log.log_task("max.muster", "Auftrag " + GEHEIM, "browser", "192.0.2.1")
audit_log.log_tool("max.muster", "shell_execute", {"command": "cat " + GEHEIM}, 5, 7)
check(GEHEIM in lesen(audit_log.AUDIT_FILE), "Positivkontrolle: ausserhalb stehen Auftrag/Argumente da")
audit_log.AUDIT_FILE.unlink()
sync_im_lauf(lambda: (audit_log.log_task("max.muster", "Auftrag " + GEHEIM, "browser", "192.0.2.1"),
                      audit_log.log_tool("max.muster", "shell_execute",
                                         {"command": "cat " + GEHEIM}, 5, 7)))
a = lesen(audit_log.AUDIT_FILE)
zeilen = [json.loads(z) for z in a.splitlines() if z.strip()]
check(a and GEHEIM not in a, "im Lauf: kein Inhalt im Audit-Log", a[:200])
check(len(zeilen) == 2 and zeilen[1].get("tool") == "shell_execute"
      and "command" in (zeilen[1].get("args") or {}),
      "Werkzeugname und Argument-NAMEN bleiben (Nachweis)")


# ══════════════════════════════════════════════════════════════════════════
section("5. Sitzungsablage (chat_sessions)")
(chat_sessions._user_dir("max.muster") / "s1").mkdir(parents=True)
chat_sessions.save_context("max.muster", "s1", [{"t": GEHEIM}])
check(GEHEIM in baum_text(chat_sessions._ROOT), "Positivkontrolle: save_context schreibt ausserhalb")
shutil.rmtree(chat_sessions._ROOT)
(chat_sessions._user_dir("max.muster") / "s1").mkdir(parents=True)
(chat_sessions._user_dir("max.muster") / "s1" / "meta.json").write_text(
    json.dumps({"title": chat_sessions._DEFAULT_TITLE}), encoding="utf-8")
sync_im_lauf(lambda: (chat_sessions.save_context("max.muster", "s1", [{"t": GEHEIM}]),
                      chat_sessions.save_transcript("max.muster", "s1", [{"t": GEHEIM}]),
                      chat_sessions.touch("max.muster", "s1", auto_title=GEHEIM)))
check(GEHEIM not in baum_text(chat_sessions._ROOT),
      "im Lauf: weder Kontext noch Transkript noch Titel aus dem Inhalt")


# ══════════════════════════════════════════════════════════════════════════
section("6. Lernen und Gedaechtnis")
from backend import learning  # noqa: E402
_aufgerufen = []
_orig = learning._collect_tool_results
learning._collect_tool_results = lambda m: _aufgerufen.append(1) or []
asyncio.run(learning.learn_from_conversation("t", [], None, "m"))
check(_aufgerufen, "Positivkontrolle: ausserhalb laeuft das Lernen an")
_aufgerufen.clear()


async def _lern_im_lauf():
    async with sensibel.anfrage(True):
        await learning.learn_from_conversation("t " + GEHEIM, [], None, "m")
asyncio.run(_lern_im_lauf())
check(not _aufgerufen, "im Lauf: Lernen kehrt sofort zurueck (kein LLM-Aufruf, keine Notiz)")
learning._collect_tool_results = _orig

try:
    from backend.tools import memory as _mem
except Exception as e:  # noqa: BLE001
    abbruch(f"backend.tools.memory nicht ladbar: {e}")
# Ein Lauf MIT Kanal (Chat): ohne Kanal ist das Gedaechtnis ohnehin gesperrt
# (Lauf ohne Oberflaeche) – die Pruefung waere dann trivial wahr (Gegenprobe).
from backend import wirkung as _wk  # noqa: E402
_kmarke = _wk.kanal_cv.set(_wk.Kanal(ws=None, username="max.muster", kann_bestaetigen=True))
check(_mem.schreiben_gesperrt() is False,
      "Positivkontrolle: im Chat-Lauf (mit Kanal) ist das Gedaechtnis schreibbar")
with sensibel.scope(True):
    check(_mem.schreiben_gesperrt() is True, "im Lauf: Gedaechtnis-Schreibsperre greift")
    antwort = _mem.MemoryTool()._execute_inner(action="save", key="k", value=GEHEIM,
                                               _username="max.muster") \
        if hasattr(_mem, "MemoryTool") else _mem.HINWEIS_SENSIBEL
check(antwort == _mem.HINWEIS_SENSIBEL, "memory_manage(save) meldet den sensiblen Grund", str(antwort)[:120])
_wk.kanal_cv.reset(_kmarke)


# ══════════════════════════════════════════════════════════════════════════
section("7. Telemetrie-Spans (Anzeige und Fehlerlog)")
sp = telemetry.TraceSpan("agent:x", "agent")
sp.attributes.update({"task": GEHEIM, "agent.id": "a1"})
sp.end("error", "Fehler " + GEHEIM)
check(GEHEIM in json.dumps(sp.to_dict()), "Positivkontrolle: ausserhalb steht der Auftrag im Span")
with sensibel.scope(True):
    sp2 = telemetry.TraceSpan("agent:x", "agent")
sp2.attributes.update({"task": GEHEIM, "agent.id": "a1", "error.traceback": GEHEIM})
sp2.end("error", "Fehler " + GEHEIM)
d2 = sp2.to_dict()
check(GEHEIM not in json.dumps(d2), "im Lauf gestarteter Span gibt keinen Inhalt heraus")
check(d2["attributes"].get("agent.id") == "a1" and d2["status"] == "error",
      "Kennung und Status bleiben")


# ══════════════════════════════════════════════════════════════════════════
section("8. Sicherheitsprotokoll")
try:
    from backend import security_guard as _sg
except Exception as e:  # noqa: BLE001
    abbruch(f"security_guard nicht ladbar: {e}")
check(_sg._inhalt(GEHEIM) == GEHEIM, "Positivkontrolle: ausserhalb bleibt der Auszug")
with sensibel.scope(True):
    check(_sg._inhalt(GEHEIM) == sensibel.MARKE, "im Lauf: Auszug/Auftrag/Detail werden zur Marke")
quelle_sg = (ROOT / "backend" / "security_guard.py").read_text(encoding="utf-8")
baum = ast.parse(quelle_sg)
# Jedes Inhaltsfeld (snippet/task/detail), dessen Wert aus einem LAUF stammt –
# erkennbar an den Parametern text/snippet/task/detail –, laeuft durch _inhalt.
# Nicht gemeint: der Text einer manuellen Admin-Sperre und das LESEN fuer die
# Anzeige (dort steht schon die Marke).
_LAUF_NAMEN = {"text", "snippet", "task", "detail"}
fehl, gesehen = [], 0
for knoten in ast.walk(baum):
    if isinstance(knoten, ast.Dict):
        for k, v in zip(knoten.keys, knoten.values):
            if isinstance(k, ast.Constant) and k.value in ("snippet", "task", "detail"):
                namen = {n.id for n in ast.walk(v) if isinstance(n, ast.Name)}
                if not (namen & _LAUF_NAMEN):
                    continue
                gesehen += 1
                ok = (isinstance(v, ast.Call) and getattr(v.func, "id", "") == "_inhalt")
                if not ok:
                    fehl.append(f"{k.value}@{knoten.lineno}")
check(gesehen >= 5, "Positivkontrolle: Regel findet die Inhaltsfelder (%d)" % gesehen)
check(not fehl, "Regel: jedes Inhaltsfeld aus einem Lauf geht durch _inhalt()", ", ".join(fehl))


# ══════════════════════════════════════════════════════════════════════════
section("9. Short-Tracks-Protokoll")
eintrag = {"owner": "max.muster", "dump_id": "d1", "dump": "Ablage", "titel": GEHEIM + ".pdf",
           "ok": True, "ergebnis": "Ergebnis " + GEHEIM,
           "dateien": [{"name": GEHEIM + ".xlsx", "url": "/api/documents/x"}],
           "schritte": ["xlsx_read_range"], "dauer_s": 1.0}
short_tracks.protokoll_schreiben(dict(eintrag))
check(GEHEIM in lesen(short_tracks.PROTOKOLL_DATEI), "Positivkontrolle: ausserhalb steht der Inhalt im Protokoll")
short_tracks.PROTOKOLL_DATEI.unlink()
sync_im_lauf(lambda: short_tracks.protokoll_schreiben(dict(eintrag)))
pr = lesen(short_tracks.PROTOKOLL_DATEI)
pz = json.loads(pr.splitlines()[0]) if pr.strip() else {}
check(pr and GEHEIM not in pr, "im Lauf: weder Titel noch Ergebnis noch Dateinamen", pr[:200])
check(pz.get("owner") == "max.muster" and pz.get("schritte") == ["xlsx_read_range"]
      and pz.get("dateien_anzahl") == 1 and isinstance(pz.get("dateien"), list),
      "wer/Werkzeuge/Anzahl bleiben, 'dateien' bleibt eine LISTE (Anzeige ruft .map)")
try:
    _pr_an = short_tracks._pruefe({"name": "n", "prompt": "p", "sensibel": True}, None).get("sensibel")
    _pr_aus = short_tracks._pruefe({"name": "n", "prompt": "p"}, None).get("sensibel")
    _pr_str = short_tracks._pruefe({"name": "n", "prompt": "p", "sensibel": "ja"}, None).get("sensibel")
    _pr_fehler = ""
except Exception as e:  # noqa: BLE001
    _pr_an = _pr_aus = _pr_str = None
    _pr_fehler = repr(e)
check(_pr_an is True and _pr_aus is False and _pr_str is False,
      "Ablage-Feld 'sensibel': nur echtes true, Vorgabe AUS", _pr_fehler)
check("sensibel" in short_tracks.AENDERBAR, "'sensibel' ist aenderbar (PUT-Whitelist)")


# ══════════════════════════════════════════════════════════════════════════
section("10. Broker: Journal/Audit und Weitergabe des Merkmals")
_bc_mod = types.ModuleType("backend.broker")
try:
    from backend.broker import ops as _ops
except Exception as e:  # noqa: BLE001
    _ops = None
    print(f"  (Hinweis: broker.ops nicht ladbar: {e})")
if _ops is None:
    abbruch("backend.broker.ops nicht ladbar")
roh = {"user": "jarvis_sandbox", "command": "cat " + GEHEIM, "arbeit": "0123abcd",
       "_context": "Auftrag " + GEHEIM}
check(GEHEIM in json.dumps(_ops.redact_args("sandbox_lauf", roh)),
      "Positivkontrolle: ohne Merkmal steht der Befehl in der Broker-Zeile")
red = _ops.redact_args("sandbox_lauf", {**roh, "sensibel": True})
check(GEHEIM not in json.dumps(red) and red.get("user") == "jarvis_sandbox"
      and red.get("arbeit") == "0123abcd",
      "mit Merkmal: Befehl/Kontext geschwaerzt, Benutzer und Verzeichnis bleiben")
check(GEHEIM not in _ops._args_info("sandbox_lauf", {**roh, "sensibel": True}),
      "Broker-Audit (_args_info) ebenso")

from backend import broker_client as _bcl  # noqa: E402
_gesendet = []


class _Sock:
    def __init__(self, *a, **k): pass
    def settimeout(self, t): pass
    def connect(self, p): pass
    def sendall(self, b): _gesendet.append(json.loads(b.decode()))
    def makefile(self, m): return io.BytesIO(b'{"type":"result","ok":true}\n')
    def close(self): pass


_bcl.os = types.SimpleNamespace(path=types.SimpleNamespace(exists=lambda p: True),
                                geteuid=lambda: 1000)
_bcl.socket = types.SimpleNamespace(socket=_Sock, AF_UNIX=1, SOCK_STREAM=1)
_bcl.call_sync("sandbox_lauf", {"command": "x"})
check(_gesendet and "sensibel" not in _gesendet[-1]["args"], "Positivkontrolle: ohne Lauf kein Merkmal")
sync_im_lauf(lambda: _bcl.call_sync("sandbox_lauf", {"command": "x"}))
check(_gesendet and _gesendet[-1]["args"].get("sensibel") is True,
      "im Lauf: broker_client gibt 'sensibel' mit (Broker sieht die ContextVar nicht)")


# ══════════════════════════════════════════════════════════════════════════
section("11. Dokumentablage: Loeschen am Laufende, Ergebnisfrist, Download")
documents.DOCS_DIR.mkdir(parents=True, exist_ok=True)


def _datei(name):
    (documents.DOCS_DIR / name).write_text(GEHEIM, encoding="utf-8")
    return name


normal = _datei("0" * 32 + "__normal.xlsx")
documents.register(normal, "max.muster")
check(not documents.ist_sensibel(normal), "Positivkontrolle: Ablage ausserhalb ist nicht sensibel")


async def _lauf_mit_dateien():
    async with sensibel.anfrage(True):
        zw = _datei("1" * 32 + "__zwischen.xlsx")
        er = _datei("2" * 32 + "__ergebnis.xlsx")
        up = _datei("Upload_" + GEHEIM + ".pdf")
        documents.register(zw, "max.muster")
        documents.register(er, "max.muster")
        documents.register_upload(up, "max.muster")
        # schon vorhandene, NICHT sensible Datei nur ansprechen: bleibt
        documents.register(normal, "max.muster")
        kopie = TMP / ("anhang_" + GEHEIM)
        kopie.write_text("x")
        sensibel.datei_merken(kopie)
        sensibel.ergebnis_merken(er)
        drin = sensibel.aktiv() and documents.ist_sensibel(zw) and documents.ist_sensibel(up)
        return zw, er, up, kopie, drin


zw, er, up, kopie, drin = asyncio.run(_lauf_mit_dateien())
check(drin, "im Lauf angelegte Ablagen tragen das Merkmal in der Registry")
check(not (documents.DOCS_DIR / zw).exists() and not (documents.DOCS_DIR / up).exists(),
      "am Laufende: Zwischenablage und Upload geloescht")
check(not kopie.exists(), "am Laufende: Arbeitskopie (Host-Pfad) geloescht")
check((documents.DOCS_DIR / normal).exists() and not documents.ist_sensibel(normal),
      "eine vorher vorhandene, normale Datei bleibt unberuehrt")
reg = documents._load()
check((documents.DOCS_DIR / er).exists() and isinstance(reg.get(er), dict)
      # 15 * 60 ist die ZUSAGE an den Betreiber (nicht die Konstante): wer die
      # Konstante hochsetzt, bricht die Zusage – das muss hier rot werden.
      and 0 < reg[er].get("sensibel_bis", 0) - time.time() <= 15 * 60 + 2,
      "Ergebnis bleibt mit Frist <= 15 min")
check(documents.sensible_abraeumen(time.time(), sensibel.WAISEN_FRIST_S) == 0
      and (documents.DOCS_DIR / er).exists(), "vor Fristablauf: Ergebnis bleibt")
check(documents.sensible_abraeumen(time.time() + sensibel.ERGEBNIS_FRIST_S + 5,
                                   sensibel.WAISEN_FRIST_S) == 1
      and not (documents.DOCS_DIR / er).exists() and er not in documents._load(),
      "nach Fristablauf: Ergebnis und Registry-Eintrag geloescht")
# Waise (Absturz ohne Aufraeumen)
with sensibel.scope(True):
    wa = _datei("3" * 32 + "__waise.xlsx")
    documents.register(wa, "max.muster")
check(documents.sensible_abraeumen(time.time() + sensibel.WAISEN_FRIST_S + 5,
                                   sensibel.WAISEN_FRIST_S) >= 1
      and not (documents.DOCS_DIR / wa).exists(), "Waise nach Frist geloescht")
check(documents.entfernen("../" + normal) is False and (documents.DOCS_DIR / normal).exists(),
      "entfernen nimmt nur einfache Namen (kein Pfad aus einem Argument)")
# Access-Log-Schwaerzung
with sensibel.scope(True):
    nm = _datei("4" * 32 + "__Gehalt_" + "Mustermann.xlsx")
    documents.register(nm, "max.muster")
zeile = f'192.0.2.1 - "GET /api/documents/{nm}?token=abc HTTP/1.1" 200'
check(nm not in url_geheimnis.schwaerzen(zeile), "Access-Log: Name einer sensiblen Ablage geschwaerzt")
z2 = f'"GET /api/documents/{normal} HTTP/1.1"'
check(normal in url_geheimnis.schwaerzen(z2), "Positivkontrolle: normaler Name bleibt im Access-Log")


# ══════════════════════════════════════════════════════════════════════════
section("12. Privates /tmp: eigene Kennung je sensiblem Lauf")
lauf_tmp.ausfuehrung_unwirksam = lambda: False
lauf_tmp.bwrap_verfuegbar = lambda *a, **k: True
with lauf_tmp.lauf_scope("max.muster", False) as l1:
    normal_kennung = l1.kennung if l1 else ""
check(normal_kennung == lauf_tmp.benutzer_kennung("max.muster"),
      "Positivkontrolle: normaler Lauf nutzt die Benutzer-Kennung")
with sensibel.scope(True):
    with lauf_tmp.lauf_scope("max.muster", False) as l2:
        sk = l2.kennung if l2 else ""
        eigen = sk and sk != normal_kennung and sk == sensibel.vorhandene_kennung()
        pfad = lauf_tmp.ARBEIT_ROOT / sk / "x.xlsx"
        gehoert = lauf_tmp.gehoert_arbeitsbereich(pfad, "max.muster")
        fremd = lauf_tmp.gehoert_arbeitsbereich(pfad, "erika.muster")
        anh = lauf_tmp.ANH_ROOT / sk / "anhang_x"
        anh_eigen = lauf_tmp.gehoert_anhang(anh, "max.muster")
check(bool(eigen), "sensibler Lauf: eigene Kennung (nicht die geteilte des Benutzers)")
check(gehoert is True and fremd is False, "Zugehoerigkeit im Lauf: eigener ja, fremder nein")
check(anh_eigen is True, "Anhang-Verzeichnis derselben Kennung gehoert dem Benutzer im Lauf")
check(lauf_tmp.gehoert_arbeitsbereich(pfad, "max.muster") is False,
      "nach dem Lauf gehoert das Verzeichnis niemandem mehr")


# ══════════════════════════════════════════════════════════════════════════
section("13. Verdrahtung (Regeln am Syntaxbaum)")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
mbaum = ast.parse(MAIN)
funks = {n.name: n for n in ast.walk(mbaum) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def ruft(fn_knoten, name) -> bool:
    for k in ast.walk(fn_knoten):
        if isinstance(k, ast.Call):
            f = k.func
            if (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name):
                return True
    return False


def with_anfrage(fn_knoten) -> bool:
    for k in ast.walk(fn_knoten):
        if isinstance(k, ast.AsyncWith):
            for it in k.items:
                c = it.context_expr
                if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "anfrage":
                    return True
    return False


we = funks.get("websocket_endpoint")
check(we is not None and ruft(we, "_ws_nachricht_behandeln") and not ruft(we, "handle_ws_message"),
      "websocket_endpoint geht ueber _ws_nachricht_behandeln (nicht direkt)")
wn = funks.get("_ws_nachricht_behandeln")
check(wn is not None and with_anfrage(wn) and ruft(wn, "handle_ws_message"),
      "_ws_nachricht_behandeln setzt die Behandlung in sensibel.anfrage")
iss = funks.get("_ist_sensibler_auftrag")
check(iss is not None and "is True" in ast.unparse(iss), "nur ein ausdrueckliches true zaehlt")
hw = funks.get("handle_ws_message")
_hg = [k for k in ast.walk(hw) if isinstance(k, ast.Call) and getattr(k.func, "id", "") == "_hintergrund"] if hw else []
_hg_lauf = [k for k in _hg if k.args and isinstance(k.args[0], ast.Call)
            and ast.unparse(k.args[0].func).endswith("run_task")
            or (k.args and "_run_main_agent_and_notify" in ast.unparse(k.args[0]))]
check(_hg_lauf and all(ast.unparse(k.args[0].func).endswith("uebergeben") for k in _hg_lauf),
      "Haupt- und Folgelauf gehen durch sensibel.uebergeben (Aufraeumen nach dem Lauf)",
      ", ".join(ast.unparse(k.args[0])[:60] for k in _hg_lauf))
for ep in ("tracks_drop", "tracks_drop_url", "tracks_ask"):
    check(funks.get(ep) is not None and with_anfrage(funks[ep]), f"{ep} in sensibel.anfrage")
gd = funks.get("get_document")
check(gd is not None and ruft(gd, "ist_sensibel") and "no-store" in ast.unparse(gd)
      and "entfernen" in ast.unparse(gd), "Download: sensibel -> no-store und Loeschen nach Download")
st = funks.get("startup_sensibel_fristen")
check(st is not None and "fristen_abraeumen" in ast.unparse(st), "Fristen-Wecker beim Start")
am = funks.get("_anhang_merken")
check(am is not None and ruft(am, "aktiv"), "Anhang-Merkliste im sensiblen Lauf uebersprungen")

AG = ast.parse((ROOT / "backend" / "agent.py").read_text(encoding="utf-8"))
emit = [n for n in ast.walk(AG) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_emit"]
check(emit and ruft(emit[0], "ergebnis_merken"), "_emit vermerkt ausgelieferte Ergebnisse")

RU = ast.parse((ROOT / "backend" / "short_tracks_runner.py").read_text(encoding="utf-8"))
rf = {n.name: n for n in ast.walk(RU) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
fa = rf.get("_fuehre_aus")
_fort = fa and any(isinstance(k, ast.AsyncWith) and any(
    getattr(getattr(i.context_expr, "func", None), "attr", "") == "fortsetzen" for i in k.items)
    for k in ast.walk(fa))
check(bool(_fort) and ruft(fa, "_fuehre_aus_im_lauf"), "Track-Lauf in sensibel.fortsetzen")
check(fa is not None and ruft(fa, "_pumpe") and not ruft(rf.get("_fuehre_aus_im_lauf"), "_pumpe"),
      "Warteschlange wird AUSSERHALB des Laufs nachgezogen")
check(ruft(rf.get("einreihen"), "_sensibel_abzweigen") and ruft(rf.get("einreihen_frage"), "_sensibel_abzweigen"),
      "jeder Auftrag zweigt seinen eigenen Lauf ab")

# verlauf_fuer: sensible Vorgaenger nur in sensible Laeufe
from backend import short_tracks_runner as _str  # noqa: E402
_str._jobs.clear()
v = {"id": "a", "art": "frage", "dump_id": "d", "owner": "m", "_nr": 1, "status": "fertig",
     "ergebnis": "Antwort " + GEHEIM, "_frage": "f", "beendet": time.time(), "sensibel": True}
j_norm = {"id": "b", "art": "frage", "dump_id": "d", "owner": "m", "_nr": 2, "sensibel": False}
j_sens = dict(j_norm, id="c", sensibel=True)
_str._jobs.update({"a": v, "b": j_norm, "c": j_sens})
check(GEHEIM in json.dumps(_str.verlauf_fuer(j_sens)[0]), "Positivkontrolle: sensibler Folgelauf sieht den Verlauf")
check(GEHEIM not in json.dumps(_str.verlauf_fuer(j_norm)[0]),
      "normaler Folgelauf bekommt keinen sensiblen Vorgaenger")
_str._jobs.clear()

# Frontend: chat.js – jeder Speicherweg prueft zuerst den sensiblen Chat
_acorn_test = ROOT / "tests" / "test_sensibel_chat.js"
if _acorn_test.exists():
    r = subprocess.run(["node", str(_acorn_test)], capture_output=True, text=True, timeout=120)
    print("\n".join("    " + z for z in r.stdout.strip().splitlines()[-12:]))
    if r.returncode == 2:
        abbruch("test_sensibel_chat.js konnte nicht laufen: " + r.stdout[-300:] + r.stderr[-300:])
    check(r.returncode == 0, "chat.js: Regeln fuer den sensiblen Chat (test_sensibel_chat.js)")
else:
    check(False, "tests/test_sensibel_chat.js fehlt")

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
