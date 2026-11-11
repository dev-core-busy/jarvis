#!/usr/bin/env python3
"""Waechter: Recherche ueber Microsoft 365 Copilot (Skill ``copilot``).

WAS HIER GEMESSEN WIRD – UND WARUM GENAU DAS
--------------------------------------------
Das Werkzeug ``copilot_recherche`` schickt eine Frage an Microsoft und loest
dort eine Bing-Suche aus. Drei Zusagen tragen es, und jede ist eine, deren
Ausfall STILL waere:

1. **Die Internet-Freigabe des Auftraggebers gilt auch hier.** Der
   Backend-Prozess hat Internet; die harte OS-Sperre aus
   ``backend/egress_guard.py`` trifft nur ``shell_execute``. Ohne die Pruefung
   im Werkzeug waere dieses Werkzeug ein Internet-Zugang fuer genau die
   Benutzer, denen er genommen wurde – und zwar einer, der keine nftables-Regel
   beruehrt und deshalb auch keine Fehlermeldung erzeugt.
2. **Der Benutzer ist KEIN Werkzeug-Argument.** Sonst koennte ein
   eingeschmuggelter Satz waehlen, mit wessen Microsoft-Konto recherchiert wird
   – und das Token traegt ``Mail.Read`` und ``Sites.Read.All``.
3. **Die Refresh-Token sind gesperrt** (Dateiwerkzeuge, Shell, Rechte-
   Haertung). Dieselbe Klasse wie ``data/google_auth``, wo am 2026-11-06 die
   zweite Datei desselben Zwecks durch jeden Filter fiel.

GEMESSEN WIRD WIRKUNG, NICHT VORKOMMEN: ``execute()`` wird WIRKLICH ausgefuehrt
und die HTTP-Aufrufe werden GEZAEHLT – ein Waechter, der nach dem Namen der
Freigabe-Funktion im Quelltext sucht, bleibt gruen, wenn ihr Ergebnis nicht
mehr ausgewertet wird. ``is_sensitive``, ``authorize_fs``, ``authorize_shell``
und ``harden_data_dirs`` laufen ebenfalls echt, letzteres gegen einen
Verzeichnisbaum im Sandkasten.

Laeuft ohne das echte ``backend.config`` – der echte Import schreibt die Live-
``settings.json`` zurueck (Register). Exit 2, wenn eine Positivkontrolle nicht
messbar ist: "konnte nicht laufen" muss von "bestanden" unterscheidbar sein.
"""

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def pruefe(bed, text):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text)


def abbruch(text):
    print(f"ABBRUCH (Exit 2): {text}")
    sys.exit(2)


# ─── Stubs VOR dem Import ───────────────────────────────────────────────────
# backend.config nur als Attrappe (Register). Die Marke ``_ist_stub`` belegt
# weiter unten, dass nicht versehentlich das echte Modul geladen wurde.
_skill_states = {"copilot": {"enabled": True, "config": {
    "copilot_tenant_id": "11111111-2222-3333-4444-555555555555",
    "copilot_client_id": "66666666-7777-8888-9999-000000000000",
}}}
_cfg_stub = types.ModuleType("backend.config")
_cfg_stub._ist_stub = True
_cfg_stub.config = types.SimpleNamespace(
    get_skill_states=lambda: _skill_states,
    get_setting=lambda k, d="": d,
)
sys.modules["backend.config"] = _cfg_stub

# backend.main als Attrappe: das Werkzeug fragt dort die Internet-Freigabe ab.
_frei_fuer: set[str] = set()
_main_stub = types.ModuleType("backend.main")
_main_stub._user_has_internet_access = lambda u: (u or "").strip().lower() in _frei_fuer
sys.modules["backend.main"] = _main_stub

from backend import copilot_client as CC  # noqa: E402
from backend import sandbox as SB  # noqa: E402

if not getattr(sys.modules.get("backend.config"), "_ist_stub", False):
    abbruch("backend.config ist nicht die Attrappe – der echte Import "
            "schreibt die Live-settings.json zurueck")

# Skill-Modul aus dem Dateipfad laden (``skills/`` ist kein Paket).
_spec = importlib.util.spec_from_file_location(
    "copilot_skill_main", ROOT / "skills" / "copilot" / "main.py")
SK = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SK)


# ─── httpx-Attrappe: die ECHTE Aufrufform, mit Zaehler ──────────────────────
class _Antwort:
    def __init__(self, code=200, daten=None, text=""):
        self.status_code = code
        self._daten = {} if daten is None else daten
        self.text = text

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._daten


AUFRUFE: list[tuple[str, dict]] = []
# Antwort je Endpunkt-Teil; wird je Abschnitt neu belegt.
ANTWORTEN: dict[str, _Antwort] = {}


class _Client:
    """Bildet ``httpx.AsyncClient`` als async-Kontextmanager nach."""

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        AUFRUFE.append((url, kw))
        for teil, antwort in ANTWORTEN.items():
            if teil in url:
                return antwort
        return _Antwort(500, {"error": "Attrappe kennt diese Adresse nicht"})


CC.httpx = types.SimpleNamespace(AsyncClient=_Client)


def _chat_antwort(text="Die Antwort.", quellen=None):
    nachrichten = [{"text": "Die Frage.", "attributions": []}]
    nachrichten.append({"text": text, "attributions": quellen or []})
    return _Antwort(200, {"messages": nachrichten})


def _lauf(frage="Was ist X?", nur_web=True, benutzer="pruef.nutzer"):
    """Einen Werkzeug-Aufruf wirklich ausfuehren; Rueckgabe = Ergebnistext."""
    AUFRUFE.clear()
    marke = CC.current_copilot_user.set(benutzer)
    try:
        werkzeug = SK.get_tools()[0]
        return asyncio.run(werkzeug.execute(frage=frage, nur_web=nur_web))
    finally:
        CC.current_copilot_user.reset(marke)


# Token-Ablage in einen Sandkasten biegen: kein Test fasst die echte an.
_sandkasten = tempfile.TemporaryDirectory()
CC._DATA = Path(_sandkasten.name) / "copilot_auth"
CC._DATEI = CC._DATA / "tokens.json"
if str(CC._DATEI).startswith(str(ROOT)):
    abbruch("die Token-Ablage des Tests zeigt in den Arbeitsbaum")


def _verbinde(benutzer="pruef.nutzer"):
    """Ein gueltiges Token hinterlegen, damit der Weg erreichbar IST."""
    CC._sichere(benutzer, {
        "refresh_token": "rt-attrappe",
        "access_token": "at-attrappe",
        "gueltig_bis": 2 ** 31,          # weit in der Zukunft
        "upn": "pruef.nutzer@beispiel.de",
    })


# ─── 1. Positivkontrolle: der Weg ist ueberhaupt erreichbar ─────────────────
print("1. Positivkontrolle – eine Recherche gelingt grundsaetzlich")
_frei_fuer.add("pruef.nutzer")
_verbinde()
ANTWORTEN.clear()
ANTWORTEN["/copilot/conversations"] = _Antwort(200, {"id": "conv-1"})
# Der laengere Pfad muss zuerst passen – dict haelt die Einfuegereihenfolge,
# und die Attrappe nimmt den ersten Treffer.
ANTWORTEN = {"/chat": _chat_antwort("Antwort aus dem Netz.",
                                    [{"attributionType": "citation",
                                      "providerDisplayName": "Beispielquelle",
                                      "seeMoreWebUrl": "https://beispiel.de/a"}]),
             "/copilot/conversations": _Antwort(200, {"id": "conv-1"})}
_erg = _lauf()
if "Antwort aus dem Netz." not in _erg:
    abbruch("der Regelfall liefert keine Antwort – dann sind alle folgenden "
            f"Pruefungen trivial wahr. Ergebnis war: {_erg[:200]!r}")
pruefe("Antwort aus dem Netz." in _erg, "der Antworttext kommt durch")
pruefe(len(AUFRUFE) == 2,
       f"genau zwei Graph-Aufrufe (Unterhaltung + Frage), gemessen {len(AUFRUFE)}")
pruefe("https://beispiel.de/a" in _erg, "die Quellen-Adresse steht im Ergebnis")
pruefe("Beispielquelle" in _erg, "der Quellen-Name steht im Ergebnis")
pruefe("Bing" in _erg,
       "das Ergebnis sagt dem Benutzer, dass die Frage das Haus verlassen hat")

# ─── 2. Internet-Freigabe: fail-closed, OHNE Netzaufruf ─────────────────────
# Entscheidend ist nicht die Meldung, sondern dass NICHTS hinausgeht.
print("2. Ohne Internet-Freigabe geht keine Anfrage hinaus")
_frei_fuer.clear()
_erg = _lauf()
pruefe(len(AUFRUFE) == 0,
       f"kein einziger Graph-Aufruf (gemessen {len(AUFRUFE)})")
pruefe("abgelehnt" in _erg.lower(), "die Ablehnung ist benannt")
pruefe("Internet-Zugriff" in _erg, "der Grund nennt die Freigabe")
pruefe("Administrator" in _erg and "kein Fehler" in _erg,
       "der Grund sagt, WER abgelehnt hat – sonst raet das Modell auf Stoerung")

print("2b. Ein Benutzer mit Freigabe darf wieder (Gegenrichtung)")
_frei_fuer.add("pruef.nutzer")
_erg = _lauf()
pruefe(len(AUFRUFE) == 2, "mit Freigabe laufen die zwei Aufrufe wieder")

print("2c. Ohne Auftraggeber (headless) geht keine Anfrage hinaus")
_erg = _lauf(benutzer="")
pruefe(len(AUFRUFE) == 0, f"kein Graph-Aufruf (gemessen {len(AUFRUFE)})")
pruefe("Auftraggeber" in _erg, "der Grund nennt den fehlenden Auftraggeber")

print("2d. Nicht eingerichtet -> keine Anfrage")
_skill_states["copilot"]["config"]["copilot_tenant_id"] = ""
_erg = _lauf()
pruefe(len(AUFRUFE) == 0, f"kein Graph-Aufruf (gemessen {len(AUFRUFE)})")
pruefe("nicht eingerichtet" in _erg, "der Grund nennt die fehlende Einrichtung")
_skill_states["copilot"]["config"]["copilot_tenant_id"] = "11111111-2222-3333-4444-555555555555"

print("2e. Nicht verbunden -> keine CHAT-Anfrage")
CC._sichere("pruef.nutzer", None)
_erg = _lauf()
pruefe(not any("/copilot/" in u for u, _ in AUFRUFE),
       "keine Graph-Anfrage ohne hinterlegtes Token")
pruefe("nicht verbunden" in _erg.lower() or "verbunden" in _erg.lower(),
       "der Grund nennt die fehlende Verbindung")
_verbinde()

# ─── 3. Web-Grounding wird AUSDRUECKLICH gesetzt ────────────────────────────
print("3. isWebEnabled")
_lauf(nur_web=True)
_chats = [kw for u, kw in AUFRUFE if "/chat" in u]
if not _chats:
    abbruch("keine Chat-Anfrage gemessen – Abschnitt 3 kann nichts aussagen")
_body = _chats[0].get("json") or {}
_web = (((_body.get("contextualResources") or {}).get("webContext") or {})
        .get("isWebEnabled"))
pruefe(_web is True, f"nur_web=True sendet isWebEnabled=true (gesendet {_web!r})")

_lauf(nur_web=False)
_chats = [kw for u, kw in AUFRUFE if "/chat" in u]
_body = _chats[0].get("json") or {} if _chats else {}
_web = (((_body.get("contextualResources") or {}).get("webContext") or {})
        .get("isWebEnabled"))
pruefe(_web is False, f"nur_web=False sendet isWebEnabled=false (gesendet {_web!r})")
_erg = _lauf(nur_web=False)
pruefe("ohne Internet-Suche" in _erg,
       "das Ergebnis sagt, dass OHNE Internet-Suche geantwortet wurde")

# ─── 4. Der Benutzer ist kein Werkzeug-Argument ─────────────────────────────
# Waere er ein Feld im Schema, koennte das MODELL (und damit ein
# eingeschmuggelter Satz) waehlen, mit wessen Microsoft-Konto recherchiert
# wird. Dieselbe Regel wie bei Postfach, SAP, Jira und Confluence.
print("4. Kein Benutzer-/Konto-Feld im Schema")
_schema = SK.get_tools()[0].parameters_schema()
_felder = set((_schema.get("properties") or {}).keys())
_verboten = {"benutzer", "user", "konto", "account", "upn", "mandant",
             "tenant", "tenant_id", "client_id", "token", "als"}
pruefe(not (_felder & _verboten),
       f"keines der Konto-Felder im Schema (Felder: {sorted(_felder)})")
pruefe(_felder == {"frage", "nur_web"},
       f"genau 'frage' und 'nur_web' (ist {sorted(_felder)})")
pruefe("required" in _schema and _schema["required"] == ["frage"],
       "nur 'frage' ist Pflicht")

# ─── 5. Die Beschreibung warnt vor dem Datenabfluss ────────────────────────
# Sie ist die einzige Stelle, an der das MODELL erfaehrt, dass die Frage das
# Haus verlaesst – und damit das einzige, was es zu einer sachlichen
# Formulierung anhalten kann.
print("5. Werkzeug-Beschreibung")
_beschr = SK.get_tools()[0].description
pruefe("verlaesst das Haus" in _beschr,
       "die Beschreibung sagt, dass die Frage das Haus verlaesst")
pruefe("Kundennamen" in _beschr,
       "sie haelt das Modell zu einer Formulierung ohne Kundennamen an")
pruefe("knowledge_search" in _beschr,
       "sie nennt den Hausweg fuer Fragen, die kein Internet brauchen")

# ─── 6. Kuerzung beziffert, und der Hinweis steht DAVOR ────────────────────
# Am Ende schneidet ihn die naechste Kappung selbst weg, und das Modell haelt
# den Ausschnitt fuer vollstaendig (Register).
print("6. Kuerzung")
_lang = "A" * (SK.MAX_ANTWORT + 5000)
ANTWORTEN["/chat"] = _chat_antwort(_lang)
_erg = _lauf()
pruefe("Gekuerzt" in _erg, "die Kuerzung wird genannt")
pruefe(str(SK.MAX_ANTWORT) in _erg and str(len(_lang)) in _erg,
       "beide Zahlen stehen im Hinweis (gezeigt von gesamt)")
_i_hinweis = _erg.find("Gekuerzt")
_i_text = _erg.find("A" * 50)
pruefe(0 <= _i_hinweis < _i_text,
       "der Hinweis steht VOR dem gekuerzten Text")
# ⚠ NICHT ueber count("A") messen: die Hinweiszeilen dieses Ergebnisses
# enthalten selbst grosse A ("Antwort", "Anfrage"), die Zahl waere also immer
# zu hoch – erster Lauf 1 FAIL ohne Produktursache. Gemessen wird die
# Eigenschaft am LAENGSTEN Nutztext-Lauf: genau MAX_ANTWORT, nicht mehr.
pruefe("A" * SK.MAX_ANTWORT in _erg,
       f"die ersten {SK.MAX_ANTWORT} Zeichen sind vollstaendig da")
pruefe("A" * (SK.MAX_ANTWORT + 1) not in _erg,
       f"und kein Zeichen mehr als {SK.MAX_ANTWORT}")

print("6b. Eine kurze Antwort traegt KEINEN Kuerzungshinweis")
ANTWORTEN["/chat"] = _chat_antwort("Kurz.")
pruefe("Gekuerzt" not in _lauf(), "kein Hinweis ohne Kuerzung")

# ─── 7. Fehlende Quellen sind eine AUSKUNFT, keine Entwarnung ──────────────
print("7. Quellen")
ANTWORTEN["/chat"] = _chat_antwort("Ohne Belege.", [])
_erg = _lauf()
pruefe("keine Quellen" in _erg and "nicht nachpruefbar" in _erg,
       "ohne Quellen sagt das Ergebnis, dass es nicht nachpruefbar ist")

print("7b. Mehr Quellen als der Deckel -> Anzahl genannt")
_viele = [{"attributionType": "citation", "providerDisplayName": f"Q{i}",
           "seeMoreWebUrl": f"https://beispiel.de/{i}"}
          for i in range(SK.MAX_QUELLEN + 4)]
ANTWORTEN["/chat"] = _chat_antwort("Mit vielen Belegen.", _viele)
_erg = _lauf()
pruefe(str(len(_viele)) in _erg,
       f"die Gesamtzahl {len(_viele)} steht im Ergebnis")
pruefe(_erg.count("https://beispiel.de/") == SK.MAX_QUELLEN,
       f"genau {SK.MAX_QUELLEN} Adressen gezeigt "
       f"(gemessen {_erg.count('https://beispiel.de/')})")

# ─── 8. Eine Antwort ohne Text wirft NICHT, sie meldet ─────────────────────
# Ein Wurf in einem Werkzeug ist von "nicht gelaufen" nicht zu unterscheiden.
print("8. Antwortform der Preview-API")
for name, antwort in (("ohne messages", _Antwort(200, {})),
                      ("leere Liste", _Antwort(200, {"messages": []})),
                      ("messages ist kein Array", _Antwort(200, {"messages": "x"})),
                      ("Nachricht ohne text", _Antwort(200, {"messages": [{"a": 1}]}))):
    ANTWORTEN["/chat"] = antwort
    try:
        _erg = _lauf()
        pruefe("fehlgeschlagen" in _erg.lower(),
               f"{name}: Meldung statt Wurf ({_erg[:60]!r})")
        pruefe("/beta" in _erg,
               f"{name}: der Grund nennt den Preview-Stand als Ursache")
    except Exception as e:  # noqa: BLE001
        pruefe(False, f"{name}: hat GEWORFEN ({type(e).__name__}: {e})")

print("8b. Die letzte Nachricht MIT Text gewinnt, nicht die erste")
ANTWORTEN["/chat"] = _Antwort(200, {"messages": [
    {"text": "Das ist die Frage."},
    {"text": "Das ist die Antwort."},
]})
pruefe("Das ist die Antwort." in _lauf(), "die Antwort wird gelesen")

print("8c. Die eigene Frage ist nie die Antwort (Review 2026-11-10)")
# Die Antwort traegt keinen Text (nur Anhaenge): ohne die Schranke bekaeme das
# Modell seine eigene, zurueckgespiegelte Frage als Rechercheergebnis.
ANTWORTEN["/chat"] = _Antwort(200, {"messages": [
    {"text": "Sondenfrage 4711?"},
    {"text": "", "attributions": [{"seeMoreWebUrl": "https://beispiel.de/q",
                                   "providerDisplayName": "Q"}]},
]})
_erg = _lauf(frage="Sondenfrage 4711?")
pruefe("fehlgeschlagen" in _erg.lower() and "Sondenfrage 4711?" not in _erg,
       f"Antwort ohne Text: Meldung, nicht die Frage als Ergebnis ({_erg[:60]!r})")

# ─── 9. Fehlergruende nennen den naechsten Schritt ─────────────────────────
# Ein 403 ohne Hinweis schickt die Suche in die Rechteverwaltung, waehrend die
# fehlende Lizenz die haeufigere Ursache ist (Register: ein Fehlergrund, der
# die falsche Ursache benennt, ist teurer als einer, der schweigt).
print("9. Fehlergruende")
ANTWORTEN["/copilot/conversations"] = _Antwort(403, {"error": {"message": "Forbidden"}})
_erg = _lauf()
pruefe("Lizenz" in _erg, "403 nennt die fehlende Copilot-Lizenz als Ursache")
pruefe("Berechtigungen" in _erg, "403 nennt auch die Scopes als Moeglichkeit")

ANTWORTEN["/copilot/conversations"] = _Antwort(429, {})
pruefe("drosselt" in _lauf(), "429 nennt die Drosselung")
ANTWORTEN["/copilot/conversations"] = _Antwort(404, {})
pruefe("/beta" in _lauf(), "404 nennt den Preview-Stand")

print("9b. Ein abgelaufenes Refresh-Token loest die Verbindung")
ANTWORTEN = {"/oauth2/v2.0/token": _Antwort(400, {"error": "invalid_grant"}),
             "/chat": _chat_antwort(),
             "/copilot/conversations": _Antwort(200, {"id": "c"})}
CC._sichere("pruef.nutzer", {"refresh_token": "alt", "access_token": "",
                             "gueltig_bis": 0, "upn": "x@beispiel.de"})
_erg = _lauf()
pruefe(not CC.verbunden("pruef.nutzer"),
       "die Verbindung ist danach geloest (die Oberflaeche zeigt 'nicht verbunden')")
pruefe("neu verbinden" in _erg, "der Grund nennt den naechsten Schritt")

# ─── 10. Alle sieben Graph-Scopes ──────────────────────────────────────────
# Microsoft: "You need all of these Microsoft Graph permissions to
# successfully call the Microsoft 365 Copilot Chat API." Ein fehlender Eintrag
# ergibt kein eingeschraenktes Ergebnis, sondern einen Fehlschlag.
print("10. Scopes")
_soll = {"Sites.Read.All", "Mail.Read", "People.Read.All",
         "OnlineMeetingTranscript.Read.All", "Chat.Read",
         "ChannelMessage.Read.All", "ExternalItem.Read.All"}
pruefe(set(CC.SCOPES) == _soll,
       f"genau die sieben Pflicht-Scopes (fehlt: {sorted(_soll - set(CC.SCOPES))}, "
       f"zuviel: {sorted(set(CC.SCOPES) - _soll)})")
_scope_str = CC._scope_string()
pruefe("offline_access" in _scope_str,
       "offline_access ist dabei (ohne Refresh-Token waere jede Frage eine "
       "neue Geraete-Anmeldung)")
for s in _soll:
    pruefe(f"https://graph.microsoft.com/{s}" in _scope_str,
           f"als Graph-Adresse angefordert: {s}")

# ─── 11. Kein Client-Geheimnis ─────────────────────────────────────────────
# Ein oeffentlicher Client braucht keines, und ein hinterlegtes waere ein
# Geheimnis mehr, das nirgends gebraucht wird.
print("11. Oeffentlicher Client")
_quelle = (ROOT / "backend" / "copilot_client.py").read_text("utf-8")
import ast  # noqa: E402

_baum = ast.parse(_quelle)
_literale = {n.value for n in ast.walk(_baum)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)}
pruefe(not any("client_secret" == l for l in _literale),
       "client_secret wird nirgends als Feld gesendet")
_schema_json = json.loads((ROOT / "skills" / "copilot" / "skill.json").read_text("utf-8"))
_cfg_felder = set((_schema_json.get("config_schema") or {}).keys())
pruefe(not any("secret" in f.lower() for f in _cfg_felder),
       f"kein Geheimnis-Feld in der Skill-Konfiguration ({sorted(_cfg_felder)})")
pruefe(_schema_json.get("enabled") is False,
       "der Skill ist per Vorgabe AUS")

# ─── 12. Keine zweite Entschaerfung (Dopplung) ─────────────────────────────
# ``backend/werkzeug_rahmen`` entschaerft JEDES Werkzeugergebnis zentral
# (BSI H8). Eine zweite Entschaerfung im Skill waere die Dopplung, an der jede
# Gegenprobe stumm wird – und man liest das als "blinder Waechter".
print("12. Keine Dopplung der Fremdtext-Entschaerfung")
_skill_quelle = (ROOT / "skills" / "copilot" / "main.py").read_text("utf-8")
_sk_baum = ast.parse(_skill_quelle)
_importe = set()
for n in ast.walk(_sk_baum):
    if isinstance(n, ast.ImportFrom) and n.module:
        _importe.add(n.module)
        for a in n.names:
            _importe.add(f"{n.module}.{a.name}")
    elif isinstance(n, ast.Import):
        for a in n.names:
            _importe.add(a.name)
pruefe(not any("fremdtext" in i for i in _importe),
       "der Skill importiert fremdtext NICHT (zentral geregelt)")
pruefe(not any("werkzeug_rahmen" in i for i in _importe),
       "der Skill importiert werkzeug_rahmen NICHT")
pruefe(not any("audit_log" in i for i in _importe),
       "der Skill schreibt KEINE eigene Audit-Zeile (der Dispatch tut es)")

# ─── 13. Die Dispatch-Bindung existiert WIRKLICH ───────────────────────────
# Ohne sie ist ``current_copilot_user`` immer leer und das Werkzeug lehnt in
# jedem Lauf ab – ein Ausfall, der wie eine Fehlkonfiguration aussieht.
print("13. agent.py bindet den Actor an current_copilot_user")
_agent = ast.parse((ROOT / "backend" / "agent.py").read_text("utf-8"))
_setzt = False
_importiert = False
for n in ast.walk(_agent):
    if (isinstance(n, ast.ImportFrom) and n.module == "backend.copilot_client"
            and any(a.name == "current_copilot_user" for a in n.names)):
        _importiert = True
    # Ein echter Aufruf ``<name>.set(...)`` auf den importierten Alias
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "set" and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "_cpcv"):
        _setzt = True
pruefe(_importiert, "agent.py importiert current_copilot_user")
pruefe(_setzt, "und ruft darauf .set() auf (echter Aufruf, nicht nur der Name)")
pruefe("sandbox.tool_user" not in _skill_quelle
       and "set_tool_user" not in _skill_quelle,
       "der Skill benutzt NICHT tool_user() – der ist fuer privilegierte "
       "Benutzer leer, Administratoren haetten sonst gar kein Konto")

# ─── 14. Token-Ablage: eine Datei mit FESTEM Namen ─────────────────────────
print("14. Token-Ablage")
VERZ = "data/copilot_auth"
DATEI = VERZ + "/tokens.json"
_p = lambda rel: (SB.PROJECT_ROOT / rel).resolve()

# Positivkontrolle: die Sonde unterscheidet ueberhaupt
_harmlos = _p("data/knowledge/beispiel.txt")
if SB.is_sensitive(_harmlos):
    abbruch("is_sensitive haelt schon einen Wissenspfad fuer sensibel – dann "
            "ist Abschnitt 14 trivial wahr")
pruefe(not SB.is_sensitive(_harmlos),
       "ein Wissenspfad gilt NICHT als sensibel (sonst waere alles trivial)")
_erlaubt_h, _, _ = SB.authorize_shell("grep -r suchbegriff data/rag")
if not _erlaubt_h:
    abbruch("authorize_shell verweigert schon eine harmlose Suche – dann sagt "
            "Abschnitt 14 nichts aus")
pruefe(_erlaubt_h, "eine harmlose Suche bleibt in der Shell erlaubt")

pruefe(SB.is_sensitive(_p(DATEI)), f"gesperrt: {DATEI}")
pruefe(SB.is_sensitive(_p(VERZ)), f"gesperrt: das Verzeichnis {VERZ} selbst")
# DAS ist der Kern: eine Datei, die es heute noch nicht gibt (Lehre aus
# data/google_auth, wo die zweite Datei desselben Zwecks durchfiel).
pruefe(SB.is_sensitive(_p(VERZ + "/kuenftige_datei.json")),
       "gesperrt: eine kuenftige, heute unbekannte Datei im Verzeichnis")

print("14b. Der Backend-Weg nennt die Sensibilitaet als Grund")
_erlaubt, _grund = SB.authorize_fs("read", str(_p(DATEI)), username="pruef.nutzer")
pruefe(not _erlaubt, f"read verweigert: {DATEI}")
pruefe("Arbeitsbereich" not in _grund and "Arbeitsverzeichnis" not in _grund,
       f"Grund ist die Sensibilitaet, nicht der Ort ({_grund!r})")
pruefe(SB.fs_target_sensitive(str(_p(DATEI))), "zaehlt als Angriffsindiz")

print("14c. Der Shell-Weg")
for cmd in (f"cat {SB.PROJECT_ROOT}/{DATEI}",
            f"cd {VERZ} && cat tokens.json",
            f"tar czf /tmp/x.tgz {VERZ}",
            f"cat {VERZ}/*"):
    _erlaubt, _grund, _marke = SB.authorize_shell(cmd)
    pruefe(not _erlaubt, f"gesperrt: {cmd[:58]}")
    pruefe(bool(_marke), f"Schranke ist benannt (marke={_marke!r})")

print("14d. harden_data_dirs setzt die Rechte wirklich")
with tempfile.TemporaryDirectory() as tmp:
    baum = Path(tmp)
    (baum / VERZ).mkdir(parents=True)
    (baum / VERZ).chmod(0o755)
    f = baum / DATEI
    f.write_text("{}", encoding="utf-8")
    f.chmod(0o644)
    (baum / "data" / "knowledge").mkdir(parents=True)
    unberuehrt = baum / "data" / "knowledge" / "beispiel.txt"
    unberuehrt.write_text("x", encoding="utf-8")
    unberuehrt.chmod(0o644)
    alt = SB.PROJECT_ROOT
    try:
        SB.PROJECT_ROOT = baum
        if (baum / DATEI).stat().st_mode & 0o777 != 0o644:
            abbruch("Sandkasten nicht in der Ausgangslage")
        SB.harden_data_dirs()
    finally:
        SB.PROJECT_ROOT = alt
    modus = lambda p: p.stat().st_mode & 0o777
    pruefe(modus(baum / VERZ) == 0o750,
           f"Verzeichnis {VERZ} auf 0750 (ist {oct(modus(baum / VERZ))})")
    pruefe(modus(baum / DATEI) == 0o600,
           f"{DATEI} auf 0600 (ist {oct(modus(baum / DATEI))})")
    pruefe(modus(unberuehrt) == 0o644,
           "eine harmlose Wissensdatei bleibt unberuehrt")

print("14e. Der Dateiname ist FEST – sonst greift PRIVATE_FILES_STRENG nicht")
pruefe(CC._DATEI.name == "tokens.json",
       f"die Ablage heisst tokens.json (ist {CC._DATEI.name})")
pruefe(DATEI in SB.PRIVATE_FILES_STRENG,
       f"{DATEI} steht in PRIVATE_FILES_STRENG")
pruefe(VERZ in SB.PRIVATE_DIRS, f"{VERZ} steht in PRIVATE_DIRS")

print("14f. Beim Schreiben entsteht die Datei direkt mit 0600")
CC._sichere("pruef.nutzer", {"refresh_token": "rt", "access_token": "",
                             "gueltig_bis": 0, "upn": "a@beispiel.de"})
pruefe((CC._DATEI.stat().st_mode & 0o777) == 0o600,
       f"0600 ohne Nachsetzen (ist {oct(CC._DATEI.stat().st_mode & 0o777)})")
pruefe("pruef.nutzer" not in CC._DATEI.read_text("utf-8"),
       "der Benutzername steht NICHT im Klartext in der Ablage")

print("14g. Zwei Benutzer stehen nebeneinander, keiner verdraengt den anderen")
CC._sichere("zweiter.nutzer", {"refresh_token": "rt2", "access_token": "",
                               "gueltig_bis": 0, "upn": "b@beispiel.de"})
pruefe(CC.verbunden("pruef.nutzer") and CC.verbunden("zweiter.nutzer"),
       "beide Eintraege sind da")
CC.trennen("pruef.nutzer")
pruefe(not CC.verbunden("pruef.nutzer") and CC.verbunden("zweiter.nutzer"),
       "Trennen entfernt genau einen Eintrag")
pruefe(CC._kennung("pruef.nutzer") not in CC._DATEI.read_text("utf-8"),
       "der getrennte Eintrag ist ENTFERNT, nicht geleert")

# ─── 15. Endpunkte: der Benutzer kommt aus der Dependency ─────────────────
# Ein Benutzerfeld im Rumpf waere der Weg, eine fremde Verbindung zu starten
# oder zu loesen (dieselbe Lehre wie bei run_message: die Kennung waehlt die
# Nachricht, nicht das Postfach).
print("15. Endpunkte")
_main = ast.parse((ROOT / "backend" / "main.py").read_text("utf-8"))
_gefunden: dict[str, ast.AST] = {}
for n in ast.walk(_main):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
            n.name.startswith("copilot_"):
        _gefunden[n.name] = n
_erwartet = {"copilot_status", "copilot_device_start", "copilot_device_status",
             "copilot_trennen"}
if not _erwartet <= set(_gefunden):
    abbruch(f"Endpunkte fehlen: {sorted(_erwartet - set(_gefunden))}")
pruefe(_erwartet <= set(_gefunden), "alle vier Endpunkte sind da")
for name in sorted(_erwartet):
    fn = _gefunden[name]
    args = [a.arg for a in fn.args.args]
    pruefe(args == ["user"],
           f"{name}: genau ein Parameter 'user' (ist {args})")
    # Die Vorgabe muss ein Depends(require_auth) sein, nicht etwas Freieres.
    vorgaben = [ast.unparse(d) for d in fn.args.defaults]
    pruefe(any("Depends(require_auth)" in v for v in vorgaben),
           f"{name}: haengt an require_auth (ist {vorgaben})")

# ─── Bilanz ────────────────────────────────────────────────────────────────
_sandkasten.cleanup()
print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
