#!/usr/bin/env python3
"""Belastbarkeit der Telemetrie: Alterung, vollstaendige Prompts, Leeren je Bereich.

Deckt die drei Zusagen ab, die am 2026-08-04 hinzukamen:
  a) Selbstbereinigung nach 90 Tagen (conv_log, Telemetrie-Fehler, Audit-Log)
  b) LLM-Verlauf ohne Kuerzung – der Prompt ist vollstaendig
  c) Jede der fuenf Statistiken/Logs ist einzeln leerbar

Laeuft OHNE fastapi (die Endpunkt-Verdrahtung wird per Quelltext geprueft), damit
der Test auch auf einer Maschine ohne installierte Web-Abhaengigkeiten durchlaeuft.

    python3 tests/test_log_retention.py
"""

import importlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail: list[str] = []


def check(name: str, cond, detail: str = ""):
    global _ok
    if cond:
        _ok += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        _fail.append(name + (f" – {detail}" if detail else ""))
        print(f"  \033[31m✗\033[0m {name}" + (f" – {detail}" if detail else ""))


def section(title: str):
    print(f"\n\033[1m{title}\033[0m")


# ─── Sandkasten: Module auf ein Wegwerf-Datenverzeichnis umbiegen ─────────────

_tmp = tempfile.TemporaryDirectory()
TMP = Path(_tmp.name)

import backend.conv_log as conv_log          # noqa: E402
import backend.audit_log as audit_log        # noqa: E402
import backend.telemetry as telemetry        # noqa: E402
import backend.log_retention as log_retention  # noqa: E402

conv_log._DATA_DIR = TMP / "data"
conv_log._CONV_DIR = TMP / "data" / "logs" / "conv"
conv_log._INDEX = conv_log._CONV_DIR / "index.jsonl"
conv_log._OLD_FILE = TMP / "data" / "conv_log.json"
conv_log._migrated = True                     # Migration separat testen

audit_log.AUDIT_FILE = TMP / "data" / "logs" / "audit.jsonl"

telemetry._STATS_FILE = TMP / "data" / "telemetry_stats.json"
telemetry._ERRORS_FILE = TMP / "data" / "telemetry_errors.json"
tracer = telemetry.JarvisTracer()

# SCHUTZ: Beim Gegenprobe-Lauf gegen einen ALTEN Modulstand (git stash) heissen
# die Modulvariablen anders – die Umbiegung oben greift dann nicht und der Test
# schreibt in das ECHTE data/-Verzeichnis. Genau das ist am 2026-08-04 passiert
# (eine Streudatei data/conv_log.json mit Testinhalten). Deshalb: JEDES
# Path-Attribut der drei Module muss im Sandkasten liegen, sonst Abbruch.
_leaks = []
for mod in (conv_log, audit_log, telemetry):
    for attr in dir(mod):
        if attr.startswith("__"):
            continue
        val = getattr(mod, attr, None)
        if isinstance(val, Path) and TMP not in val.parents and val != TMP:
            _leaks.append(f"{mod.__name__}.{attr} = {val}")
if _leaks:
    print("\033[31mABBRUCH – Pfad zeigt nicht in den Sandkasten:\033[0m")
    for l in _leaks:
        print("  -", l)
    print("Der Test wuerde in das echte data/-Verzeichnis schreiben.")
    sys.exit(2)

DAY = 86400
NOW = time.time()


# ═══ b) Vollstaendigkeit ══════════════════════════════════════════════════════

section("b) LLM-Verlauf: nichts wird gekuerzt")

LONG_TASK = "Analysiere folgende Tabelle: " + ("SPALTE;WERT\n" * 3000)   # ~36 KB
LONG_SYS = "Du bist Jarvis. " + ("Regel. " * 8000)                       # ~56 KB
LONG_TOOL = "Z" * 5000

conv_log.log_conversation(
    task=LONG_TASK, model="gemini-x", client_ip="10.0.0.9", client_type="browser",
    system_prompt=LONG_SYS,
    messages=[{"role": "user", "content": LONG_TASK},
              {"role": "tool", "tool": "shell_execute", "content": LONG_TOOL},
              {"role": "assistant", "content": "Fertig."}],
    steps=2, duration_ms=1234, username="andrea.ladd")

entries = conv_log.get_conversations(limit=10)
check("Eintrag angelegt", len(entries) == 1, str(len(entries)))
e0 = entries[0]
check("Aufgabe im Index VOLLSTAENDIG (kein [:200])",
      e0["task"] == LONG_TASK, f"{len(e0['task'])} von {len(LONG_TASK)}")
check("Index traegt KEINE Nachrichten (Rumpf getrennt)",
      "messages" not in e0, str(list(e0.keys())))
check("Index nennt die Nachrichtenzahl", e0.get("msg_count") == 3)

body = conv_log.get_body(e0["id"])
check("Rumpf abrufbar", body is not None)
check("System-Prompt VOLLSTAENDIG (kein [:500])",
      body["system_prompt"] == LONG_SYS,
      f"{len(body['system_prompt'])} von {len(LONG_SYS)}")
check("Aufgabe im Rumpf vollstaendig", body["task"] == LONG_TASK)
msgs = body["messages"]
check("user-Nachricht vollstaendig (kein [:300])",
      msgs[0]["content"] == LONG_TASK, f"{len(msgs[0]['content'])}")
check("Tool-Ergebnis vollstaendig", msgs[1]["content"] == LONG_TOOL)
check("assistant-Nachricht vollstaendig", msgs[2]["content"] == "Fertig.")
check("Nichts als gekuerzt markiert",
      not any(m.get("truncated") for m in msgs))
check("Tool-Name erhalten", msgs[1].get("tool") == "shell_execute")

section("b2) Notbremse greift nur oberhalb der Grenzen – und sagt es dann")

_msg_max = conv_log._MAX_MSG_CHARS
conv_log._MAX_MSG_CHARS = 100          # kuenstlich klein, um die Bremse zu sehen
try:
    huge_prompt = "F" * 5000
    conv_log.log_conversation(
        task=huge_prompt, model="m", client_ip="", client_type="", system_prompt="S",
        messages=[{"role": "user", "content": huge_prompt},
                  {"role": "tool", "tool": "t", "content": "R" * 5000}],
        steps=1, duration_ms=1, username="u")
    b = conv_log.get_body(conv_log.get_conversations(limit=1)[0]["id"])
    check("Prompt bleibt trotz Notbremse UNGEKUERZT",
          b["messages"][0]["content"] == huge_prompt,
          f"{len(b['messages'][0]['content'])}")
    check("Prompt nicht als gekuerzt markiert",
          not b["messages"][0].get("truncated"))
    tm = b["messages"][1]
    check("Tool-Ergebnis wird gekuerzt", len(tm["content"]) == 100, str(len(tm["content"])))
    check("Kuerzung ist AUSGEWIESEN", tm.get("truncated") is True)
    check("Originallaenge steht dabei", tm.get("full_len") == 5000, str(tm.get("full_len")))
    idx = conv_log.get_conversations(limit=1)[0]
    check("Index nennt Anzahl gekuerzter Nachrichten",
          idx.get("truncated_msgs") == 1, str(idx.get("truncated_msgs")))
finally:
    conv_log._MAX_MSG_CHARS = _msg_max

section("b3) Rumpf-Budget geht nie auf Kosten der Prompts")

_body_max = conv_log._MAX_BODY_CHARS
conv_log._MAX_BODY_CHARS = 1000
try:
    # Ein Tool-Ergebnis VOR dem Prompt darf das Budget nicht so aufbrauchen,
    # dass der Prompt dahinter leer bleibt.
    msgs_in = [{"role": "tool", "tool": "t", "content": "X" * 5000},
               {"role": "user", "content": "WICHTIGE FRAGE " * 100}]
    out, cut = conv_log._prepare_messages(msgs_in)
    check("Prompt nach grossem Tool-Ergebnis vollstaendig",
          out[1]["content"] == msgs_in[1]["content"], f"{len(out[1]['content'])}")
    check("Tool-Ergebnis stattdessen gekuerzt", out[0].get("truncated") is True)
finally:
    conv_log._MAX_BODY_CHARS = _body_max

section("b4) Getrennte Ids auch bei gleicher Millisekunde")

ids = {conv_log._new_id() for _ in range(500)}
check("500 Ids sind eindeutig", len(ids) == 500, str(len(ids)))

section("b5) Rumpf-Pfad ist gegen Pfadwechsel entschaerft")

check("../ in der Id fuehrt nicht aus dem Ordner",
      conv_log._body_path("../../etc/passwd").parent == conv_log._CONV_DIR,
      str(conv_log._body_path("../../etc/passwd")))
check("Unbekannte Id liefert None, nicht Fehler",
      conv_log.get_body("gibtsnicht") is None)


# ═══ a) Selbstbereinigung ═════════════════════════════════════════════════════

section("a) Alterung: conv_log")

conv_log.clear()
for age_days, uid in ((200, "alt1"), (120, "alt2"), (91, "alt3"),
                      (89, "neu1"), (1, "neu2")):
    conv_log.log_conversation(
        task=f"Aufgabe {uid}", model="m", client_ip="1.2.3.4", client_type="browser",
        system_prompt="S", messages=[{"role": "user", "content": "x"}],
        steps=1, duration_ms=1, username=uid)
    # Zeitstempel nachtraeglich zuruecksetzen (die Uhr laesst sich nicht stellen)
    idx = conv_log._read_index()
    idx[-1]["ts"] = NOW - age_days * DAY
    conv_log._write_index(idx)

before = conv_log._read_index()
bodies_before = len(list(conv_log._CONV_DIR.glob("*.json")))
check("5 Eintraege vorbereitet", len(before) == 5, str(len(before)))
check("5 Rumpfdateien vorbereitet", bodies_before == 5, str(bodies_before))

removed = conv_log.prune_older_than(NOW - 90 * DAY)
after = conv_log._read_index()
check("3 Eintraege ueber 90 Tage entfernt", removed == 3, str(removed))
check("2 Eintraege bleiben", len(after) == 2, str(len(after)))
check("nur die jungen bleiben",
      {e["username"] for e in after} == {"neu1", "neu2"},
      str([e["username"] for e in after]))
check("Rumpfdateien der Alten sind mit weg",
      len(list(conv_log._CONV_DIR.glob("*.json"))) == 2,
      str(len(list(conv_log._CONV_DIR.glob("*.json")))))
check("zweiter Lauf entfernt nichts mehr (idempotent)",
      conv_log.prune_older_than(NOW - 90 * DAY) == 0)

section("a2) Verwaiste Rumpfdatei wird eingesammelt")

orphan = conv_log._CONV_DIR / "999999999999.json"
orphan.write_text('{"id":"999999999999"}', encoding="utf-8")
os.utime(orphan, (NOW - 200 * DAY, NOW - 200 * DAY))
young_orphan = conv_log._CONV_DIR / "888888888888.json"
young_orphan.write_text('{"id":"888888888888"}', encoding="utf-8")
conv_log.prune_older_than(NOW - 90 * DAY)
check("alte verwaiste Rumpfdatei entfernt", not orphan.exists())
check("junge verwaiste Rumpfdatei bleibt (evtl. gerade entstanden)",
      young_orphan.exists())
young_orphan.unlink()

section("a3) Beschaedigte Index-Zeile macht den Verlauf nicht unlesbar")

with conv_log._INDEX.open("a", encoding="utf-8") as f:
    f.write('{"id": "kaputt", "ts": \n')
check("Index weiterhin lesbar", len(conv_log._read_index()) == 2,
      str(len(conv_log._read_index())))

section("a4) Alterung: Telemetrie-Fehler")

telemetry._ERRORS_FILE.parent.mkdir(parents=True, exist_ok=True)
telemetry._ERRORS_FILE.write_text(json.dumps([
    {"name": "a", "ts": NOW - 200 * DAY},
    {"name": "b", "ts": NOW - 91 * DAY},
    {"name": "c", "ts": NOW - 10 * DAY},
    {"name": "d"},                       # ohne ts – muss bleiben
]))
rem = tracer.prune_errors_older_than(NOW - 90 * DAY)
left = json.loads(telemetry._ERRORS_FILE.read_text())
check("2 alte Fehler entfernt", rem == 2, str(rem))
check("junger Fehler bleibt", any(e["name"] == "c" for e in left))
check("Fehler OHNE Zeitstempel bleibt (Alter nicht geraten)",
      any(e["name"] == "d" for e in left), str(left))

section("a5) Alterung: Audit-Log inkl. Rotations-Sicherung")

audit_log.AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
audit_log.AUDIT_FILE.write_text("\n".join([
    json.dumps({"ts": int(NOW - 200 * DAY), "user": "u", "tool": "alt"}),
    json.dumps({"ts": int(NOW - 5 * DAY), "user": "u", "tool": "neu"}),
    json.dumps({"user": "u", "tool": "ohne_ts"}),
    "{kaputt",
]) + "\n", encoding="utf-8")
bak = audit_log.AUDIT_FILE.with_suffix(".jsonl.bak")
bak.write_text(json.dumps({"ts": int(NOW - 300 * DAY), "tool": "uralt"}) + "\n",
               encoding="utf-8")

rem = audit_log.prune_older_than(NOW - 90 * DAY)
tools = [e["tool"] for e in audit_log.read_log(limit=50)]
check("alte + kaputte Zeilen entfernt (2 aktiv + 1 Sicherung)", rem == 3, str(rem))
check("junge Zeile bleibt", "neu" in tools, str(tools))
check("Zeile ohne Zeitstempel bleibt", "ohne_ts" in tools, str(tools))
check("alte Zeile ist weg", "alt" not in tools, str(tools))
check("leer gewordene Rotations-Sicherung geloescht", not bak.exists())
st = audit_log.stats()
check("stats() zaehlt die verbleibenden Zeilen", st["lines"] == 2, str(st))

section("a6) Frist: Vorgabe, Umgebungsvariable, Abschaltung")

for env, expect in ((None, 90), ("", 90), ("30", 30), ("0", 0), ("-5", 0),
                    ("abc", 90), ("99999", 3650), ("45,0", 45)):
    if env is None:
        os.environ.pop("JARVIS_LOG_RETENTION_DAYS", None)
    else:
        os.environ["JARVIS_LOG_RETENTION_DAYS"] = env
    got = log_retention.retention_days()
    check(f"Frist bei {env!r} = {expect}", got == expect, str(got))
os.environ.pop("JARVIS_LOG_RETENTION_DAYS", None)

check("cutoff_ts liegt 90 Tage zurueck",
      abs((time.time() - log_retention.cutoff_ts()) - 90 * DAY) < 5,
      str(log_retention.cutoff_ts()))
os.environ["JARVIS_LOG_RETENTION_DAYS"] = "0"
check("cutoff_ts ist None bei dauerhaft", log_retention.cutoff_ts() is None)
res = log_retention.run_all()
check("run_all() ueberspringt bei dauerhaft und loescht NICHTS",
      res.get("skipped") is True and res.get("removed") == {}, str(res))
os.environ.pop("JARVIS_LOG_RETENTION_DAYS", None)

section("a7) run_all(): ein defekter Speicher stoppt die anderen nicht")

_orig = log_retention._prune_conv_log
log_retention._prune_conv_log = lambda cut: (_ for _ in ()).throw(OSError("Platte voll"))
try:
    res = log_retention.run_all()
    check("Fehler wird gemeldet, nicht verschluckt",
          res["ok"] is False and "conv_log" in (res["error"] or ""), str(res))
    check("die anderen Speicher liefen trotzdem",
          "audit_log" in res["removed"] and "telemetry_errors" in res["removed"],
          str(res["removed"]))
finally:
    log_retention._prune_conv_log = _orig
check("last_run() nennt Frist und Zeitpunkt",
      log_retention.last_run()["days"] == 90
      and log_retention.last_run()["last_run_ts"] is not None)


# ═══ c) Leeren je Bereich ═════════════════════════════════════════════════════

section("c) Fuenf Statistiken/Logs einzeln leerbar")

def _seed_tracer():
    tracer.clear(by="test")
    for tool in ("shell_execute", "filesystem"):
        for _ in range(3):
            sp = tracer.start_span(tool, kind="tool")
            sp.attributes["tool.name"] = tool
            tracer.end_span(sp)
    for _ in range(4):
        tracer.end_span(tracer.start_span("llm", kind="llm"))
    tracer.end_span(tracer.start_span("agent:Hauptagent", kind="agent"))
    bad = tracer.start_span("agent:Fehler", kind="agent")
    tracer.end_span(bad, status="error", error="kaputt")

_seed_tracer()
s = tracer.get_stats()
check("Ausgangslage: Tool-, LLM-, Fehler- und Span-Daten vorhanden",
      len(s["tool_stats"]) == 2 and s["llm_stats"]["calls"] == 4
      and s["errors"] == 1 and s["span_count"] == 12, str(s["span_count"]))

# 1) Tool-Statistiken
r = tracer.clear_tool_stats(by="admin1")
s = tracer.get_stats()
check("Tool-Statistiken leer", s["tool_stats"] == {} and s["tool_calls"] == 0)
check("Tool-Leeren laesst LLM-Statistik stehen", s["llm_stats"]["calls"] == 4)
check("Tool-Leeren laesst Fehler stehen", s["errors"] == 1)
check("Tool-Leeren laesst agent_runs stehen", s["agent_runs"] == 2, str(s["agent_runs"]))
check("Nachweis je Bereich gesetzt",
      s["area_resets"]["tools"]["by"] == "admin1", str(s.get("area_resets")))
check("Rueckmeldung nennt die Anzahl", r["removed"] == 2, str(r))

# 2) LLM-Statistiken
_seed_tracer()
tracer.clear_llm_stats(by="admin2")
s = tracer.get_stats()
check("LLM-Statistiken leer", s["llm_stats"] == {} and s["llm_calls"] == 0)
check("LLM-Leeren laesst Tool-Statistik stehen", len(s["tool_stats"]) == 2)

# 3) Fehler-Log
_seed_tracer()
r = tracer.clear_errors(by="admin3")
s = tracer.get_stats()
check("Fehler-Log leer", tracer.get_errors() == [])
check("Fehler-ZAEHLER der Karten mitgenullt", s["errors"] == 0, str(s["errors"]))
check("Fehler-Leeren laesst Tool-Statistik stehen", len(s["tool_stats"]) == 2)
check("Fehler-Rueckmeldung nennt die Anzahl", r["removed"] == 1, str(r))

# 4) Spans
_seed_tracer()
r = tracer.clear_spans(by="admin4")
s = tracer.get_stats()
check("Spans leer", s["span_count"] == 0 and tracer.get_recent_spans(50) == [])
check("Span-Leeren laesst Zaehler stehen",
      s["tool_calls"] == 6 and s["llm_calls"] == 4, str((s["tool_calls"], s["llm_calls"])))
check("Span-Rueckmeldung nennt die Anzahl", r["removed"] == 12, str(r))

# 5) LLM-Verlauf
conv_log.log_conversation(task="T", model="m", client_ip="", client_type="",
                          system_prompt="S", messages=[{"role": "user", "content": "x"}],
                          steps=1, duration_ms=1, username="u")
check("Verlauf vor dem Leeren gefuellt", len(conv_log.get_conversations()) > 0)
conv_log.clear()
check("Verlauf leer", conv_log.get_conversations() == [])
check("Rumpfdateien mitgeloescht",
      list(conv_log._CONV_DIR.glob("*.json")) == [],
      str(list(conv_log._CONV_DIR.glob("*.json"))))
check("Filterlisten leer", conv_log.get_known_ips() == []
      and conv_log.get_known_users() == [])

section("c2) Nachweise ueberleben den Neustart, vollstaendiges Leeren raeumt sie ab")

_seed_tracer()
tracer.clear_tool_stats(by="dauerhaft")
t2 = telemetry.JarvisTracer()
check("Bereichs-Nachweis aus der Datei geladen",
      t2.get_stats()["area_resets"].get("tools", {}).get("by") == "dauerhaft",
      str(t2.get_stats().get("area_resets")))
t2.clear(by="alles")
check("vollstaendiges Zuruecksetzen verwirft Bereichs-Nachweise",
      t2.get_stats()["area_resets"] == {})
check("und setzt den globalen Nachweis",
      t2.get_stats()["last_reset_by"] == "alles")


# ═══ Migration des Altbestands ════════════════════════════════════════════════

section("Migration: data/conv_log.json wird uebernommen und als gekuerzt markiert")

conv_log.clear()
conv_log._migrated = False
old = [{
    "id": "1700000000000", "ts": NOW - 3 * DAY,
    "task": "A" * 200, "model": "gemini", "username": "sven.sander",
    "client_ip": "10.0.0.1", "client_type": "browser", "steps": 2,
    "duration_ms": 500, "error": None,
    "system_prompt_preview": "S" * 500,
    "messages": [{"role": "user", "preview": "F" * 300 + "…"},
                 {"role": "tool", "tool": "shell_execute", "preview": "R"}],
}]
conv_log._OLD_FILE.parent.mkdir(parents=True, exist_ok=True)
conv_log._OLD_FILE.write_text(json.dumps(old), encoding="utf-8")

got = conv_log.get_conversations(limit=10)
check("Alt-Eintrag uebernommen", len(got) == 1, str(len(got)))
check("Benutzer erhalten", got[0]["username"] == "sven.sander")
check("Alt-Eintrag ist als solcher markiert", got[0].get("legacy") is True)
check("Alt-Aufgabe als gekuerzt markiert", got[0].get("task_truncated") is True)
b = conv_log.get_body("1700000000000")
check("Alt-Rumpf angelegt", b is not None and b.get("legacy") is True)
check("Alt-Nachrichten als gekuerzt markiert",
      all(m.get("truncated") for m in b["messages"]))
check("Quelldatei umbenannt statt geloescht",
      not conv_log._OLD_FILE.exists()
      and conv_log._OLD_FILE.with_suffix(".json.migrated").exists())
conv_log._migrated = False
check("zweiter Lauf legt keine Duplikate an (Datei ist weg)",
      len(conv_log.get_conversations(limit=10)) == 1)


# ═══ Stueckzahl-Schranke ══════════════════════════════════════════════════════

section("EINZIG das Alter zaehlt – keine Stueckzahl-Schranke")

# Vorgabe 2026-08-04: eine Stueckzahl-Schranke hebelt die Zusage "90 Tage" aus.
# Diese Pruefungen halten fest, dass es sie NICHT MEHR gibt – in keinem der drei
# Speicher, und auch nicht als Groessen-Rotation in Verkleidung.
check("conv_log hat keine Stueckzahl-Konstante mehr",
      not hasattr(conv_log, "_MAX_ENTRIES"))
check("telemetry hat keine Fehler-Stueckzahl mehr",
      not hasattr(telemetry, "_MAX_ERRORS"))
check("audit_log hat keine Groessen-Rotation mehr",
      not hasattr(audit_log, "_MAX_BYTES"))

conv_log.clear()
conv_log._migrated = True
N = 250
for i in range(N):
    conv_log.log_conversation(task=f"T{i}", model="m", client_ip="", client_type="",
                              system_prompt="S",
                              messages=[{"role": "user", "content": "x"}],
                              steps=1, duration_ms=1, username="u")
idx = conv_log._read_index()
check(f"alle {N} Eintraege bleiben (nichts verdraengt)", len(idx) == N, str(len(idx)))
check("alle Rumpfdateien bleiben",
      len(list(conv_log._CONV_DIR.glob("*.json"))) == N,
      str(len(list(conv_log._CONV_DIR.glob("*.json")))))
check("der AELTESTE ist noch da", idx[0]["task"] == "T0", idx[0]["task"])

# Rueckwaerts-Lesen: liefert die jueng<sten zuerst und ueber Blockgrenzen hinweg
# vollstaendig (der Fallstrick sind angeschnittene Zeilen je Block).
rev = [e["task"] for e in conv_log._iter_index_reversed()]
check("Rueckwaerts-Lesen liefert alle Zeilen", len(rev) == N, str(len(rev)))
check("Rueckwaerts-Lesen beginnt beim jueng<sten", rev[0] == f"T{N-1}", rev[0])
check("Rueckwaerts-Lesen endet beim aeltesten", rev[-1] == "T0", rev[-1])
rev_small = [e["task"] for e in conv_log._iter_index_reversed(chunk=64)]
check("winzige Blockgroesse liefert dasselbe (keine verlorenen Zeilen)",
      rev_small == rev, f"{len(rev_small)} vs {len(rev)}")

top = conv_log.get_conversations(limit=10)
check("get_conversations liefert die 10 jueng<sten",
      [e["task"] for e in top] == [f"T{i}" for i in range(N - 1, N - 11, -1)],
      str([e["task"] for e in top]))

# Filter WAEHREND des Lesens: ein seltener Benutzer weit hinten muss gefunden
# werden – ein Nachfilter auf den letzten n Zeilen wuerde ihn verlieren.
conv_log.log_conversation(task="NADEL", model="m", client_ip="9.9.9.9",
                          client_type="", system_prompt="S",
                          messages=[{"role": "user", "content": "x"}],
                          steps=1, duration_ms=1, username="selten")
for i in range(120):
    conv_log.log_conversation(task=f"RAUSCHEN{i}", model="m", client_ip="1.1.1.1",
                              client_type="", system_prompt="S",
                              messages=[{"role": "user", "content": "x"}],
                              steps=1, duration_ms=1, username="viel")
hit = conv_log.get_conversations(limit=5, user_filter="selten")
check("seltener Benutzer wird trotz 120 neuerer Eintraege gefunden",
      len(hit) == 1 and hit[0]["task"] == "NADEL", str(hit))
hit_ip = conv_log.get_conversations(limit=5, ip_filter="9.9.9.9")
check("IP-Filter findet den Eintrag ebenfalls",
      len(hit_ip) == 1 and hit_ip[0]["task"] == "NADEL", str(hit_ip))

st = conv_log.get_stats()
check("get_stats zaehlt alle Eintraege", st["count"] == N + 121, str(st["count"]))
check("get_stats nennt aeltesten und neuesten Zeitpunkt",
      st["oldest_ts"] and st["newest_ts"] and st["oldest_ts"] <= st["newest_ts"], str(st))
check("get_stats nennt den Plattenbedarf", st["bytes"] > 0, str(st["bytes"]))

section("Fehler-Log: unbegrenzt viele, nur das Alter entfernt")

tracer.clear(by="t")
for i in range(300):
    sp = tracer.start_span(f"err{i}", kind="agent")
    tracer.end_span(sp, status="error", error="x")
check("300 Fehler alle gespeichert (frueher bei 200 gedeckelt)",
      len(tracer.get_errors(limit=999)) == 300,
      str(len(tracer.get_errors(limit=999))))

section("Audit-Log: keine Rotation, alte Sicherung bleibt sichtbar")

audit_log.AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
audit_log.AUDIT_FILE.write_text("", encoding="utf-8")
audit_log._bak().unlink(missing_ok=True)
for i in range(400):
    audit_log.log_tool("u", f"tool{i}", {"a": "X" * 200}, 10, 5)
size = audit_log.AUDIT_FILE.stat().st_size
check("alles in EINER Datei – keine .bak entstanden",
      not audit_log._bak().exists(), "bak existiert")
got = audit_log.read_log(limit=999)
check("alle 400 Zeilen lesbar", len(got) == 400, str(len(got)))
check("neueste zuerst", got[0]["tool"] == "tool399", got[0]["tool"])
check("limit bricht frueh ab", len(audit_log.read_log(limit=7)) == 7)
check("Filter wirkt beim Rueckwaerts-Lesen",
      [e["tool"] for e in audit_log.read_log(limit=5, tool_filter="tool12")][0].startswith("tool12"))
# Eine alte .bak aus der Rotations-Zeit muss weiterhin sichtbar sein
audit_log._bak().write_text(
    json.dumps({"ts": int(NOW), "user": "u", "tool": "aus_der_sicherung"}) + "\n",
    encoding="utf-8")
tools_all = [e["tool"] for e in audit_log.read_log(limit=9999)]
check("Eintrag aus der alten .bak erscheint in der Anzeige",
      "aus_der_sicherung" in tools_all, "fehlt")
check("_bak() folgt einer umgebogenen AUDIT_FILE (keine Modulkonstante)",
      TMP in audit_log._bak().parents, str(audit_log._bak()))
ast_ = audit_log.stats()
check("audit stats() zaehlt alle Zeilen beider Dateien",
      ast_["lines"] == 401, str(ast_))


# ═══ Verdrahtung: Endpunkte und Rechte (Quelltext) ════════════════════════════

section("Verdrahtung in main.py: Endpunkte, Rechte, Routen-Reihenfolge")

src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")

for route, method in (("/api/telemetry/tool_stats", "delete"),
                      ("/api/telemetry/llm_stats", "delete"),
                      ("/api/telemetry/errors", "delete"),
                      ("/api/telemetry/spans", "delete"),
                      ("/api/conv_log", "delete"),
                      ("/api/logs/retention", "get"),
                      ("/api/logs/retention/run", "post"),
                      ("/api/conv_log/{conv_id}", "get")):
    check(f"{method.upper()} {route} registriert",
          f'@app.{method}("{route}")' in src)

# Rechte: JEDER Telemetrie-/Verlaufs-/Audit-Endpunkt muss an require_local_auth
# haengen. Bis 2026-08-04 stand dort require_auth – jeder angemeldete Benutzer
# konnte damit die Prompts aller anderen lesen.
guarded = []
for m in re.finditer(r'@app\.(get|post|delete)\("(/api/(?:telemetry|conv_log|audit_log|logs/retention)[^"]*)"\)\s*\n'
                     r'async def (\w+)\(([^)]*)\)', src):
    guarded.append((m.group(2), m.group(3), m.group(4)))
check("alle betroffenen Endpunkte gefunden", len(guarded) >= 13, str(len(guarded)))
bad = [(r, f) for r, f, sig in guarded if "require_local_auth" not in sig]
check("KEIN Telemetrie-/Verlaufs-/Audit-Endpunkt an require_auth",
      not bad, str(bad))

# Routen-Reihenfolge: /api/conv_log/{conv_id} darf /ips und /users nicht abfangen
pos_body = src.index('@app.get("/api/conv_log/{conv_id}")')
for sub in ("/api/conv_log/ips", "/api/conv_log/users"):
    check(f"{sub} steht VOR der Sammelroute",
          src.index(f'@app.get("{sub}")') < pos_body)

check("Startup-Hook fuer die Bereinigung vorhanden",
      "async def startup_log_retention" in src and "log_retention" in src)


# ═══ Frontend-Verdrahtung ═════════════════════════════════════════════════════

section("Frontend: Knoepfe, Abruf des Rumpfes, i18n")

html = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
js = (ROOT / "frontend" / "js" / "telemetry.js").read_text(encoding="utf-8")
i18n = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")

# WARUM HIER NICHT MEHR `ctx-clear-btn` UND `context.js` STEHEN (Fix 2026-08-10):
# Der Abschnitt "Kontext / History" wurde am 2026-08-05 aus dem Telemetrie-Reiter
# entfernt und `frontend/js/context.js` dabei GELOESCHT (Commit 0b6a1cb). Dieser
# Test las die Datei aber weiter – `read_text()` warf `FileNotFoundError`, und
# zwar **bevor** irgendeine Pruefung lief: der komplette Waechter fuer
# Aufbewahrung-nach-Alter, vollstaendige Prompts und die fuenf granularen Clears
# war damit fuenf Tage lang stumm. Genau der Fall "ein Schutz, der still
# ausfaellt, ist kein Schutz".
#
# Konsequenz fuer kuenftige Aenderungen: eine Datei, die dieser Test liest, ist
# Teil seiner Voraussetzungen. Wer sie loescht, muss hier nachziehen – deshalb
# steht die Abwesenheit jetzt ausdruecklich als Pruefung darunter, statt sie
# stillschweigend zu unterlassen.
_JS_MODULE = {}
for _name in ("telemetry.js", "audit.js"):
    _pfad = ROOT / "frontend" / "js" / _name
    _JS_MODULE[_name] = _pfad.read_text(encoding="utf-8") if _pfad.exists() else ""
    check(f"{_name} vorhanden", bool(_JS_MODULE[_name]))

for bid in ("tele-tool-clear-btn", "tele-llm-clear-btn", "tele-errors-clear-btn",
            "tele-spans-clear-btn", "conv-log-clear-btn", "audit-clear-btn",
            "tele-retention-run"):
    check(f"{bid} im Markup", f'id="{bid}"' in html)
    check(f"{bid} in telemetry.js oder eigenem Modul verdrahtet",
          bid in js or any(bid in q for q in _JS_MODULE.values()))

# Das Kontext-Panel ist BEWUSST weg – die Kacheln zeigten den sitzungslosen
# Eimer des abfragenden Admins gegen die globale Schwelle, und "Jetzt
# komprimieren" wirkte auf den zuletzt geladenen (moeglicherweise fremden)
# Verlauf. Es darf nicht zurueckkommen.
check("Kontext-Panel bleibt entfernt (kein ctx-clear-btn)",
      'id="ctx-clear-btn"' not in html)
check("context.js bleibt geloescht",
      not (ROOT / "frontend" / "js" / "context.js").exists())
check("der Schwellwert steht stattdessen in den System-Einstellungen",
      'id="setting-compress-threshold"' in html)

check("Leeren-Knoepfe stoppen die Klapp-Aktion (event.stopPropagation)",
      html.count('onclick="event.stopPropagation()"') >= 6)
check("Rumpf wird beim Aufklappen geholt", "_loadConvBody" in js
      and "/api/conv_log/'" in js.replace('"', "'"))
check("Rumpf wird zwischengespeichert", "_convBodies" in js)
check("vollstaendige Aufgabe wird angezeigt", "telemetry.conv_task" in js)
check("System-Prompt wird angezeigt", "telemetry.conv_sysprompt" in js)
check("Kuerzungs-Hinweis vorhanden", "telemetry.truncated" in js)
check("Altbestands-Abzeichen vorhanden", "telemetry.legacy_badge" in js)

new_keys = ["telemetry.clear_tool_confirm", "telemetry.clear_llm_confirm",
            "telemetry.clear_errors_confirm", "telemetry.clear_spans_confirm",
            "telemetry.clear_tool_title", "telemetry.clear_llm_title",
            "telemetry.clear_errors_title", "telemetry.clear_spans_title",
            "telemetry.area_cleared", "telemetry.ret_days", "telemetry.ret_forever",
            "telemetry.ret_convs", "telemetry.ret_oldest", "telemetry.ret_audit",
            "telemetry.ret_last", "telemetry.ret_run", "telemetry.ret_running",
            "telemetry.ret_done", "telemetry.conv_task", "telemetry.conv_sysprompt",
            "telemetry.truncated", "telemetry.chars", "telemetry.legacy_badge",
            "telemetry.legacy_hint"]
for k in new_keys:
    check(f"i18n {k} in DE UND EN", i18n.count(f"'{k}'") >= 2,
          str(i18n.count(f"'{k}'")))

check("Cache-Buster von telemetry.js erhoeht",
      "telemetry.js?v=9" in html, "nicht v=9")

# Aufrufer der geaenderten Signaturen: nichts darf noch auf 'messages' oder
# 'system_prompt_preview' im Index bauen.
for name in ("telemetry.js", "chat.js", "app.js"):
    p = ROOT / "frontend" / "js" / name
    if p.exists():
        check(f"{name} nutzt kein system_prompt_preview mehr",
              "system_prompt_preview" not in p.read_text(encoding="utf-8"))

agent_src = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
check("agent.py ruft log_conversation unveraendert (Signatur kompatibel)",
      agent_src.count("conv_log.log_conversation(") == 2,
      str(agent_src.count("conv_log.log_conversation(")))


# ─── Ergebnis ─────────────────────────────────────────────────────────────────

_tmp.cleanup()
print(f"\n\033[1mErgebnis: {_ok}/{_ok + len(_fail)}\033[0m")
if _fail:
    print("\033[31mFehlgeschlagen:\033[0m")
    for f in _fail:
        print("  -", f)
sys.exit(1 if _fail else 0)
