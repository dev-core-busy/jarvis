#!/usr/bin/env python3
"""Tests: Benutzernamen einheitlich anzeigen UND einheitlich vergleichen.

DER GEMELDETE FEHLER (2026-08-10)
--------------------------------
Im LLM-Verlauf stand ``sven.sander`` statt ``nexus\\sven.sander``. Am 2026-08-02
war genau das schon einmal behoben worden – aber NUR fuer ``/api/sessions``.
Der Praefix haengt daran, was der Betroffene ins Anmeldefeld getippt hat; er
wird deshalb beim AUSLESEN aus dem abgeleitet, was das System weiss
(``main.py::_display_name``). Diese Aufbereitung fehlte im LLM-Verlauf, im
Tool-Audit-Log, bei den Zugriffs-Verstoessen, den gesperrten Konten, im
Broker-Audit, bei Cron-Besitzern, Issue-Meldern und in den Telemetrie-Statistiken.

DIE ZWEITE HAELFTE IST DIE WICHTIGERE
-------------------------------------
Eine Anzeige mit Praefix ist wertlos (schlimmer: irrefuehrend), wenn Filter und
Rechtepruefungen den ROHEN Wert vergleichen:
* ``security_guard``: Sperre und Verstoss-Zaehler lagen unter dem Rohnamen –
  derselbe Mensch hatte je Tippform einen EIGENEN Zaehler (Auto-Sperre
  verzoegerbar), und eine Sperre griff nur fuer die Variante, unter der sie
  entstand. Nach der Anzeige-Aenderung haette zusaetzlich das Entsperren
  fehlgeschlagen, weil die Oberflaeche den ANGEZEIGTEN Namen sendet.
* ``_cron_visible``: roher Vergleich – der Benutzer sah seinen EIGENEN Auftrag
  nicht mehr (404), wenn er sich anders anmeldete als beim Anlegen.
* Filter im LLM-Verlauf (exakt) und im Audit-Log (Substring) fanden nichts,
  wenn Anzeige und Speicherung sich in der Tippform unterschieden.

    python3 tests/test_display_names.py
"""

import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# backend.config NICHT echt importieren: der Import migriert Profile und
# schreibt die Live-settings.json zurueck (siehe test_license.py).
if "backend.config" not in sys.modules:
    _stub = types.ModuleType("backend.config")
    _stub.config = types.SimpleNamespace(
        get_setting=lambda *a, **k: "", ALLOWED_USERS=["jarvis"])
    sys.modules["backend.config"] = _stub

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


MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
AGENT = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
GUARD = (ROOT / "backend" / "security_guard.py").read_text(encoding="utf-8")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("1. _display_name – die Regeln")

# Die Funktion braucht nur `config`, `ALLOWED_USERS` und `_norm_login`; sie wird
# per Quelltext extrahiert, damit der Test ohne fastapi laeuft.
_teile = []
for name in ("_norm_login", "_display_name"):
    m = re.search(rf"^def {name}\(.*?(?=\n(?:def |# |@app|_NAMENSFELDER))", MAIN,
                  re.S | re.M)
    pruefe(bool(m), f"{name} im Quelltext gefunden")
    if m:
        _teile.append(m.group(0))
_ns = {"ALLOWED_USERS": ["jarvis"],
       "config": types.SimpleNamespace(get_setting=lambda k, d="": "nexus.local"),
       "_NON_DOMAIN_USERS": {"api", "root", "system"}}
exec("\n".join(_teile), _ns)  # noqa: S102 – Testcode aus dem eigenen Repo
_dn = _ns["_display_name"]

for eingabe, erwartet, warum in [
    ("sven.sander", "nexus\\sven.sander", "blosser Kontoname bekommt den Praefix"),
    ("nexus\\sven.sander", "nexus\\sven.sander", "vorhandener Praefix bleibt"),
    ("sven.sander@nexus.local", "nexus\\sven.sander", "UPN-Form wird normalisiert"),
    ("jarvis", "jarvis", "lokales Konto NIE praefixen"),
    ("api", "api", "Agent-API-Benutzer NIE praefixen"),
    ("api:Vision-Kamera", "api:Vision-Kamera", "Kanal-Kennung bleibt unangetastet"),
    ("wa:+4915112233", "wa:+4915112233", "WhatsApp-Absender bleibt"),
    ("tg:987654", "tg:987654", "Telegram-Absender bleibt"),
    ("__unprivilegiert__", "__unprivilegiert__", "Platzhalter-Actor bleibt"),
    ("unknown", "unknown", "audit_log-Vorgabe bleibt"),
    ("", "", "leer bleibt leer"),
]:
    r = _dn(eingabe)
    pruefe(r == erwartet, f"{warum}: {eingabe!r} → {r!r}", f"erwartet {erwartet!r}")

# Ohne konfigurierte Domaene wird NICHT geraten
_ns2 = dict(_ns)
_ns2["config"] = types.SimpleNamespace(get_setting=lambda k, d="": "")
exec("\n".join(_teile), _ns2)  # noqa: S102
pruefe(_ns2["_display_name"]("sven.sander") == "sven.sander",
       "ohne ad_domain bleibt es beim blossen Namen (kein Raten)")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("2. Anzeige an ALLEN Endpunkten, die Namen liefern")

pruefe("def _mit_anzeigenamen" in MAIN, "zentraler Aufbereiter existiert")
pruefe("_NAMENSFELDER" in MAIN and '"username"' in MAIN.split("_NAMENSFELDER")[1][:200],
       "die Namensfelder sind eine ausdrueckliche Liste (kein Raten)")

# Je Endpunkt: die Rueckgabe MUSS durch _mit_anzeigenamen gehen.
for route, marker, was in [
    ('@app.get("/api/conv_log")', "get_conversations", "LLM-Verlauf (der gemeldete Fall)"),
    ('@app.get("/api/conv_log/users")', "get_known_users", "Filter-Liste des Verlaufs"),
    ('@app.get("/api/conv_log/{conv_id}")', "get_conv_body", "Verlaufs-Rumpf"),
    ('@app.get("/api/audit_log")', "read_log", "Tool-Audit-Log"),
    ('@app.get("/api/security/violations")', "list_recent_violations", "Zugriffs-Verstoesse"),
    ('@app.get("/api/broker/audit")', "entries", "Broker-Audit"),
    ('@app.get("/api/telemetry/stats")', "get_stats", "Telemetrie (geleert von …)"),
    ('@app.get("/api/issues")', "list_issues", "Issue-Melder"),
]:
    i = MAIN.find(route)
    fenster = MAIN[i:i + 1400] if i >= 0 else ""
    pruefe(i >= 0 and "_mit_anzeigenamen" in fenster, f"{was}: Namen aufbereitet",
           f"Route {route} " + ("nicht gefunden" if i < 0 else "ohne Aufbereitung"))

# Gesperrte Konten + Cron liegen in groesseren Funktionen
pruefe('"blocked": _mit_anzeigenamen(security_guard.list_blocked())' in MAIN,
       "gesperrte Konten: Namen aufbereitet")
i_cron = MAIN.find("if _cron_visible(j, user)]")
pruefe("_mit_anzeigenamen(jobs)" in MAIN[i_cron:i_cron + 400],
       "Cron-Besitzer: Namen aufbereitet")

pruefe(MAIN.count("_mit_anzeigenamen") >= 10,
       f"insgesamt genug Aufrufstellen ({MAIN.count('_mit_anzeigenamen')})")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("3. Filter vergleichen normalisiert (Anzeige darf nicht luegen)")

from backend.audit_log import _user_passt, norm_user as nu_audit  # noqa: E402
from backend.conv_log import norm_user as nu_conv  # noqa: E402

for f, g, erw, warum in [
    ("nexus\\sven.sander", "sven.sander", True, "aus der Anzeige kopierter Name findet den Eintrag"),
    ("sven.sander", "nexus\\sven.sander", True, "und umgekehrt"),
    ("sander", "nexus\\sven.sander", True, "Teileingabe funktioniert weiter"),
    ("SVEN.SANDER", "sven.sander", True, "Gross/Kleinschreibung egal"),
    ("sven.sander@nexus.local", "sven.sander", True, "UPN-Form findet den Eintrag"),
    ("rene.pfeiffer", "sven.sander", False, "ein FREMDER Name findet nichts"),
    ("", "sven.sander", True, "leerer Filter zeigt alles"),
]:
    r = _user_passt(f, g)
    pruefe(r is erw, f"Audit-Filter – {warum}", f"{f!r} vs {g!r} → {r}")

pruefe(nu_audit("NEXUS\\A.B") == nu_conv("a.b@x.y") == "a.b",
       "beide Module normalisieren gleich")
pruefe(nu_audit("wa:+49151") == "wa:+49151" and nu_conv("api:Kamera") == "api:kamera",
       "Kanal-Kennungen werden NICHT am Doppelpunkt zerlegt")

CONV = (ROOT / "backend" / "conv_log.py").read_text(encoding="utf-8")
pruefe("norm_user(e.get(\"username\") or \"\") != norm_user(user_filter)" in CONV,
       "der Verlaufs-Filter vergleicht normalisiert (vorher exakt)")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("4. Sperren und Verstoss-Zaehler: EIN Topf je Mensch")

import importlib  # noqa: E402
import tempfile  # noqa: E402

import backend.security_guard as SG  # noqa: E402
importlib.reload(SG)
_tmp = Path(tempfile.mkdtemp(prefix="jarvis_guard_"))
SG._STATE_FILE = _tmp / "security_state.json"
if not str(SG._STATE_FILE).startswith(str(_tmp)):
    print("ABBRUCH: Sandkasten greift nicht")
    sys.exit(2)
SG._state_cache = None if hasattr(SG, "_state_cache") else None

pruefe(SG.norm_user("NEXUS\\Sven.Sander") == "sven.sander", "norm_user im Guard")
pruefe(SG.norm_user("wa:+49") == "wa:+49", "Kanal-Kennung bleibt")

SG.block("nexus\\testkonto", reason="Test", by="admin")
pruefe(SG.is_blocked("nexus\\testkonto"), "gesperrt: mit Praefix erkannt")
pruefe(SG.is_blocked("testkonto"),
       "gesperrt: OHNE Praefix ebenfalls erkannt (war der Fehler)")
pruefe(SG.is_blocked("testkonto@nexus.local"), "gesperrt: UPN-Form erkannt")
pruefe(SG.get_block("testkonto") is not None, "Sperr-Info auch ohne Praefix")
pruefe(not SG.is_blocked("anderes.konto"), "ein fremdes Konto ist NICHT gesperrt")
pruefe(SG.block("testkonto") is False, "Doppelsperre wird erkannt (nicht neu angelegt)")
pruefe(SG.unblock("testkonto") is True,
       "Entsperren funktioniert mit der ANDEREN Schreibweise (UI sendet den Anzeigenamen)")
pruefe(not SG.is_blocked("nexus\\testkonto"), "danach ist die Sperre weg")

# Verstoss-Zaehler: wechselnde Tippform darf die Schwelle nicht verzoegern
SG._STATE_FILE.write_text('{"blocked": {}, "violations": {}}', encoding="utf-8")
for i, name in enumerate(["zaehler", "nexus\\zaehler", "zaehler@nexus.local"]):
    r = SG.record_violation(name, "chat", "shell-forbidden", detail=f"v{i}")
pruefe(r["count"] == 3,
       f"drei Verstoesse in DREI Schreibweisen zaehlen als 3 (nicht 1+1+1) – {r['count']}")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("5. Cron-Sichtbarkeit")

i_cv = MAIN.find("def _cron_visible")
fenster_cv = MAIN[i_cv:i_cv + 800]
pruefe("_norm_login(job.get(\"owner\")" in fenster_cv,
       "der Besitzer wird normalisiert verglichen")
pruefe('== user' not in fenster_cv.split("return")[1],
       "kein roher Vergleich mehr")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("6. Antwortsprache: die Sprache des Benutzers entscheidet")

pruefe("11. Antworte immer auf Deutsch." not in AGENT,
       "die Vorgabe immer-auf-Deutsch ist aus dem System-Prompt entfernt")
pruefe("ANTWORTSPRACHE: Antworte in der Sprache, in der der Benutzer schreibt" in AGENT,
       "der Prompt verlangt die Sprache des Benutzers")
pruefe("Always respond in English, regardless" not in AGENT,
       "auch der englische Zwang ist weg (er widersprach dem deutschen)")
i_lang = AGENT.find("if lang == \"en\":")
fenster_lang = AGENT[i_lang - 700:i_lang + 1200]
pruefe("English is the default" in fenster_lang or "English " in fenster_lang,
       "die UI-Sprache ist nur noch die VORGABE")
pruefe("else:" in fenster_lang and "ANTWORTSPRACHE" in fenster_lang,
       "auch fuer Deutsch wird die Regel ausdruecklich gesagt")
pruefe("- Antworte auf Deutsch." not in AGENT,
       "der Sub-Agent-Prompt schreibt kein Deutsch mehr vor")
pruefe("Antworte in der Sprache der Aufgabenstellung." in AGENT,
       "…sondern die Sprache der Aufgabe")
pruefe(AGENT.count("in der Sprache der Frage") >= 3,
       f"die Nachschlag-Prompts ebenso ({AGENT.count('in der Sprache der Frage')})")

LLM = (ROOT / "backend" / "llm.py").read_text(encoding="utf-8")
pruefe("antworte normal auf Deutsch" not in LLM,
       "Prompt-Tool-Calling-Modus: keine Deutsch-Vorgabe mehr")

# Interne Artefakte bleiben bewusst deutsch – das ist eine Entscheidung, kein
# Versehen: Lernnotizen und Reflexions-Instruktionen sind Systemdateien eines
# deutschsprachigen Projekts, keine Antworten an einen Benutzer.
LEARN = (ROOT / "backend" / "learning.py").read_text(encoding="utf-8")
pruefe("Antworte auf Deutsch" in LEARN,
       "Faktenextraktion bleibt deutsch (internes Artefakt, bewusst)")

# ═════════════════════════════════════════════════════════════════════════════
abschnitt("7. Waechter: der System-Prompt darf dem Code nicht widersprechen")

# Diese Fehlerklasse ist im Projekt mehrfach teuer geworden: WA_TASK_PROMPT
# versprach `cron_create`, das der Dispatch verweigert (2026-07-29); der Prompt
# sagte "Antworte immer auf Deutsch" UND "Always respond in English"; er nannte
# `filesystem_read`/`filesystem_write`, die es nie gab (der Aufruf endet mit
# "Tool nicht gefunden"). Der Waechter prueft das maschinell.
_i = AGENT.index("SYSTEM_PROMPT = ")
_j = AGENT.index("SUB_AGENT_PROMPT = ")
PROMPT = AGENT[_i:_j]

# a) Werkzeuge, die es nicht gibt
werkzeuge = set()
for _p in list(ROOT.glob("backend/tools/*.py")) + list(ROOT.glob("skills/*/main.py")):
    werkzeuge |= set(re.findall(r'return "([a-z][a-z0-9_]+)"',
                                _p.read_text(encoding="utf-8", errors="replace")))
pruefe(len(werkzeuge) > 40, f"Werkzeugnamen eingesammelt ({len(werkzeuge)})")
# Auf den AUFRUF pruefen, nicht auf das Wort: der Prompt WARNT ausdruecklich vor
# den falschen Namen ("Es gibt KEINE Werkzeuge namens filesystem_read/…") – das
# ist Hilfe, kein Widerspruch. Ein Fund waere `filesystem_read(` als Anleitung.
erfunden = [n for n in ("filesystem_read", "filesystem_write", "filesystem_list",
                        "filesystem_append", "web_search", "browse_web")
            if re.search(rf"{n}\s*\(", PROMPT) and n not in werkzeuge]
pruefe(not erfunden, "der Prompt leitet zu keinem erfundenen Werkzeug an", str(erfunden))
pruefe("Es gibt KEINE Werkzeuge namens filesystem_read" in PROMPT,
       "er warnt sogar ausdruecklich vor den falschen Namen")
pruefe("filesystem(action=" in PROMPT,
       "er nennt die RICHTIGE Aufrufform von filesystem")

# b) Werkzeuge, die fuer Netzwerk-Benutzer gesperrt sind, duerfen im
#    allgemeinen Teil nicht empfohlen werden – sonst laeuft jeder
#    Domaenen-Benutzer in einen protokollierten Deny.
_b = AGENT.index("_BLOCKED_TOOLS_FOR_LDAP = {")
sperrliste = set(re.findall(r'"([a-z_]+)"', AGENT[_b:AGENT.index("}", _b)]))
pruefe(len(sperrliste) >= 6, f"Sperrliste gelesen ({len(sperrliste)})")
empfohlen = [n for n in sperrliste if re.search(rf"\b{n}\s*\(", PROMPT)]
pruefe(not empfohlen,
       "der Prompt empfiehlt kein gesperrtes Werkzeug", str(empfohlen))

# c) Keine zwei Sprachvorgaben, die sich widersprechen
pruefe(not ("immer auf Deutsch" in AGENT and "Always respond in English" in AGENT),
       "es gibt keine zwei widersprechenden Sprachvorgaben mehr")

# d) Der WhatsApp-Prompt verspricht nichts, was der Dispatch verweigert
#    (Lehre vom 2026-07-29 – hier nur nachgeprueft, nicht geaendert)
_wa = MAIN.find("WA_TASK_PROMPT")
if _wa >= 0:
    wa = MAIN[_wa:_wa + 4000]
    pruefe("immer cron_create verwenden" not in wa,
           "WA-Prompt verspricht kein cron_create (Altfehler bleibt behoben)")
    # systemctl DARF vorkommen – aber nur in der Negativliste "WAS UEBER
    # WHATSAPP NICHT GEHT" (Korrektur vom 2026-07-29). Ein Beispiel, das dazu
    # AUFFORDERT, wuerde einen protokollierten Sicherheitsverstoss erzeugen.
    _neg = wa.find("NICHT GEHT")
    pruefe(_neg >= 0, "der WA-Prompt hat einen Abschnitt \"WAS NICHT GEHT\"")
    pruefe("systemctl" not in wa[:_neg] if _neg >= 0 else False,
           "systemctl steht NUR in der Negativliste, nicht als Beispiel")

print(f"\n{'=' * 70}")
print(f"Ergebnis: {_ok} bestanden, {_fail} fehlgeschlagen")
import shutil  # noqa: E402
shutil.rmtree(_tmp, ignore_errors=True)
sys.exit(0 if _fail == 0 else 1)
