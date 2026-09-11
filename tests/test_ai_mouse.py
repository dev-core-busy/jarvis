#!/usr/bin/env python3
"""Waechter fuer AI Mouse (backend/ai_mouse.py + der Bild-Weg in agent.py).

GEMESSEN WIRD DIE EIGENSCHAFT, NICHT DAS VORKOMMEN. Die echten Funktionen
laufen; wo ein Modell oder ein Agent noetig waere, steht eine Attrappe, die
AUFZEICHNET, was sie bekommen haette – nur so laesst sich belegen, dass
``_role_tools`` gesetzt war und ``tools=[]`` wirklich leer ankam.

Laeuft ohne fastapi und ohne google-genai: die Provider-Typen werden gestellt.
"""
import ast
import base64
import re
import struct
import sys
import types as _pytypes
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def check(beschreibung, bedingung):
    """ACHTUNG Argumentreihenfolge: (Text, Bedingung).

    Vertauscht waere jede nicht-leere Zeichenkette wahr und der Lauf meldete
    lauter OK, ohne etwas geprueft zu haben – im Projekt am 2026-08-28 mit 57
    Aufrufen passiert. Deshalb bricht die Funktion bei vertauschten Argumenten
    hart ab.
    """
    global ok, fail
    if not isinstance(beschreibung, str) or isinstance(bedingung, str):
        print("ABBRUCH: check() mit vertauschten Argumenten aufgerufen: %r" % (beschreibung,))
        sys.exit(2)
    if bedingung:
        ok += 1
        print("  OK   %s" % beschreibung)
    else:
        fail += 1
        print("  FAIL %s" % beschreibung)


def sicher(fn, *a, **kw):
    """Ruft auf und gibt bei einem Wurf den Fehler zurueck statt abzubrechen.

    Ohne das bricht eine Gegenprobe mitten im Lauf ab – kein FAIL, keine
    Bilanzzeile, und von "nicht gelaufen" nicht zu unterscheiden (Register).
    """
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return e


# ── google.genai stellen, falls nicht vorhanden ─────────────────────────────
# `ai_mouse` importiert `types` erst IN `analysieren`, der Modul-Import geht
# also ohnehin. Fuer den Lauf brauchen wir aber Part/Content.
try:
    from google.genai import types as gtypes  # noqa: F401
    GENAI_ECHT = True
except Exception:  # noqa: BLE001
    GENAI_ECHT = False

    class _Part:
        def __init__(self, text=None, data=None, mime_type=None):
            self.text = text
            self.inline_data = None
            if data is not None:
                self.inline_data = _pytypes.SimpleNamespace(
                    data=data, mime_type=mime_type)

        @staticmethod
        def from_text(text=""):
            return _Part(text=text)

        @staticmethod
        def from_bytes(data=b"", mime_type=""):
            return _Part(data=data, mime_type=mime_type)

    class _Content:
        def __init__(self, role="user", parts=None):
            self.role = role
            self.parts = parts or []

    _mod = _pytypes.ModuleType("google.genai.types")
    _mod.Part, _mod.Content = _Part, _Content
    _genai = _pytypes.ModuleType("google.genai")
    _genai.types = _mod
    _google = sys.modules.get("google") or _pytypes.ModuleType("google")
    _google.genai = _genai
    sys.modules["google"] = _google
    sys.modules["google.genai"] = _genai
    sys.modules["google.genai.types"] = _mod

from backend import ai_mouse as am  # noqa: E402

# ⚠ `paket_bauen` SCHREIBT Vorgaben.cs im Arbeitsbaum (die Hauswerte gehen ja in
# die Anwendung). Genau so sind am 2026-09-09 die Testplatzhalter "M" und
# "https://h" ins Repo gelangt – und weil der automatische Bau sie damals nicht
# ueberschrieb, trug die ausgelieferte EXE sie.
#
# Die Wiederherstellung haengt an `atexit` und nicht an einer Stelle mitten im
# Lauf: ein zweiter Aufruf weiter unten lief sonst DANACH und verbog sie erneut
# (genau so passiert). So ist auch ein kuenftig ergaenzter Aufruf gedeckt – und
# ein Abbruch ebenfalls.
_VORG = ROOT / "ai-mouse" / "src" / "AiMouse" / "Configuration" / "Vorgaben.cs"
_VORG_SICHERUNG = _VORG.read_text(encoding="utf-8") if _VORG.is_file() else None


def _vorgaben_heimholen():
    if _VORG_SICHERUNG is None:
        return
    try:
        if _VORG.read_text(encoding="utf-8") != _VORG_SICHERUNG:
            _VORG.write_text(_VORG_SICHERUNG, encoding="utf-8")
            print("  (Vorgaben.cs im Arbeitsbaum wiederhergestellt)")
    except Exception as e:  # noqa: BLE001
        print("  ⚠ Vorgaben.cs NICHT wiederhergestellt: %s" % e)


import atexit  # noqa: E402

atexit.register(_vorgaben_heimholen)

print("\n=== 1. Bildpruefung (fail-closed) ===")


def png_bytes(w=8, h=8):
    """Ein WIRKLICH dekodierbares PNG. Erfundene Bytes belegen nichts."""
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = png_bytes()
URI = "data:image/png;base64," + base64.b64encode(PNG).decode()

r = sicher(am.bild_pruefen, URI)
check("Data-URI wird angenommen und als PNG erkannt",
      isinstance(r, tuple) and r[0] == PNG and r[1] == "image/png")
r = sicher(am.bild_pruefen, base64.b64encode(PNG).decode())
check("nacktes base64 wird angenommen", isinstance(r, tuple) and r[0] == PNG)

# DIE BYTES ENTSCHEIDEN, NICHT DIE TYPANGABE.
r = sicher(am.bild_pruefen, "data:image/jpeg;base64," + base64.b64encode(PNG).decode())
check("falsche Typangabe wird an den Bytes korrigiert",
      isinstance(r, tuple) and r[1] == "image/png")
r = sicher(am.bild_pruefen, "data:image/png;base64,"
           + base64.b64encode(b"PK\x03\x04kein bild").decode())
check("ZIP unter PNG-Kopf wird abgewiesen", isinstance(r, am.MausFehler))

r = sicher(am.bild_pruefen, "data:image/gif;base64," + base64.b64encode(PNG).decode())
check("Format ausserhalb der Whitelist wird abgewiesen", isinstance(r, am.MausFehler))
r = sicher(am.bild_pruefen, "")
check("leeres Bild wird abgewiesen", isinstance(r, am.MausFehler))
r = sicher(am.bild_pruefen, "data:image/png;base64,%%%")
check("kaputtes base64 wird abgewiesen", isinstance(r, am.MausFehler))

# Der Deckel greift auf den DEKODIERTEN Bytes.
gross = b"\x89PNG\r\n\x1a\n" + b"x" * (am.MAX_BILD_BYTES + 10)
r = sicher(am.bild_pruefen, "data:image/png;base64," + base64.b64encode(gross).decode())
check("Bild ueber dem Deckel wird abgewiesen", isinstance(r, am.MausFehler))
check("die Meldung zum Deckel nennt die erlaubte Groesse",
      isinstance(r, am.MausFehler) and "MB" in str(r))

r = sicher(am.frage_pruefen, "   ")
check("leere Frage wird abgewiesen", isinstance(r, am.MausFehler))
check("Frage wird auf MAX_FRAGE gekuerzt",
      len(am.frage_pruefen("a" * (am.MAX_FRAGE + 500))) == am.MAX_FRAGE)

print("\n=== 2. Bereiche: Vorgabe leer, Whitelist, Laufzeit-Pruefung ===")

_cfg = {}
am.skill_config = lambda: _cfg  # noqa: E731

_cfg.clear()
check("VORGABE: ohne Konfiguration gibt es KEINE Bereiche",
      am.freigegebene_bereiche() == [])
check("ohne Bereiche ist die Werkzeugmenge LEER (nicht None)",
      am.werkzeuge_fuer([]) == set())

_cfg["bereiche"] = "wissen"
check("freigeschalteter Bereich wird erkannt",
      am.freigegebene_bereiche() == ["wissen"])
check("Werkzeuge kommen aus BEREICHE", am.werkzeuge_fuer(["wissen"]) == {"knowledge_search"})

_cfg["bereiche"] = "wissen,fach"
check("Reihenfolge ist stabil nach BEREICHE, nicht nach Eingabe",
      am.freigegebene_bereiche() == ["wissen", "fach"])
_cfg["bereiche"] = "fach,wissen"
check("auch bei umgekehrter Eingabe stabil",
      am.freigegebene_bereiche() == ["wissen", "fach"])

_cfg["bereiche"] = "wissen,erfunden"
check("unbekannter Bereich wird verworfen, nicht geraten",
      am.freigegebene_bereiche() == ["wissen"])
check("werkzeuge_fuer ignoriert unbekannte Bereiche",
      am.werkzeuge_fuer(["erfunden"]) == set())

# NUR LESENDE WERKZEUGE – die tragende Zusage des Moduls.
alle = am.werkzeuge_fuer(list(am.BEREICHE))
verboten = [t for t in alle if any(w in t for w in
            ("create", "add", "update", "delete", "write", "send", "upload"))]
check("kein einziges schreibendes Werkzeug in den Bereichen", not verboten)

print("\n=== 3. analysieren(): der Weg haengt an der leeren MENGE ===")

_spur = {}


class _Resp:
    def __init__(self, text):
        self.parts = [_pytypes.SimpleNamespace(text=text)]


class _Provider:
    async def generate_response(self, **kw):
        _spur["direkt"] = kw
        return _Resp("ANTWORT-DIREKT")


_llm_stub = _pytypes.ModuleType("backend.llm")
_llm_stub.provider_fuer_lauf = lambda **kw: (_Provider(), "modell-x")
_llm_stub.scrub_secrets = lambda s: s
sys.modules["backend.llm"] = _llm_stub


async def _agent_stub(sysp, auftrag, bild_parts, werkzeuge, user):
    _spur["agent"] = {"sysp": sysp, "auftrag": auftrag,
                      "bilder": bild_parts, "werkzeuge": werkzeuge, "user": user}
    return (am.ergebnis_marke(sysp.split("[[ERGEBNIS ")[1].split("]]")[0])
            + " ANTWORT-AGENT" if "[[ERGEBNIS " in sysp else "ANTWORT-AGENT"), "modell-a"

am._agent_lauf = _agent_stub


def lauf(**kw):
    import asyncio
    am._reset_fuer_tests()
    _spur.clear()
    return sicher(asyncio.run, am.analysieren(
        bild_roh=kw.get("bild", URI), frage_roh=kw.get("frage", "Was ist das?"),
        user=kw.get("user", "tester"), lang=kw.get("lang", "de")))


_cfg.clear()
r = lauf()
check("REGELFALL: ohne Bereiche laeuft der direkte Weg",
      isinstance(r, dict) and "direkt" in _spur and "agent" not in _spur)
check("REGELFALL: tools ist eine LEERE Liste",
      _spur.get("direkt", {}).get("tools") == [])
check("REGELFALL: die Antwort kommt beim Aufrufer an",
      isinstance(r, dict) and r.get("text") == "ANTWORT-DIREKT")
check("REGELFALL: bereiche im Ergebnis ist leer",
      isinstance(r, dict) and r.get("bereiche") == [])

# Das Bild MUSS im Aufruf stecken – sonst antwortet das Modell auf nichts.
_teile = _spur.get("direkt", {}).get("contents", [{}])[0]
_parts = getattr(_teile, "parts", [])
check("REGELFALL: ein inline_data-Part mit den Bildbytes geht mit",
      any(getattr(p, "inline_data", None) is not None
          and p.inline_data.data == PNG for p in _parts))
# Die Reihenfolge in DIESER Liste; auf der Leitung dreht llm.py sie um
# (gemessen 2026-09-09) - das ist Bestandsverhalten und nicht Sache dieses Moduls.
check("REGELFALL: das Bild steht in der Part-Liste vor dem Text",
      _parts and getattr(_parts[0], "inline_data", None) is not None)
check("REGELFALL: die Frage des Benutzers steht im Auftragstext",
      any("Was ist das?" in (getattr(p, "text", "") or "") for p in _parts))

_cfg["bereiche"] = "wissen"
r = lauf()
check("MIT Bereich: der Agentenweg laeuft", "agent" in _spur and "direkt" not in _spur)
check("MIT Bereich: die Werkzeug-Whitelist ist genau der Bereich",
      _spur.get("agent", {}).get("werkzeuge") == {"knowledge_search"})
check("MIT Bereich: die Whitelist ist eine MENGE, nie None",
      isinstance(_spur.get("agent", {}).get("werkzeuge"), set))
check("MIT Bereich: das Bild geht als eigener Part an den Agenten",
      len(_spur.get("agent", {}).get("bilder") or []) == 1)
check("MIT Bereich: bereiche im Ergebnis benennt, was der Lauf durfte",
      isinstance(r, dict) and r.get("bereiche") == ["wissen"])

# ⚠ DIE FREIGABE WIRKT ZUR LAUFZEIT: Bereich zurueckgenommen -> sofort weg.
_cfg["bereiche"] = ""
r = lauf()
check("Freigabe zurueckgenommen: sofort wieder der direkte Weg",
      "direkt" in _spur and "agent" not in _spur)

print("\n=== 4. Kein Weg an der Entscheidung des Administrators vorbei ===")

src = (ROOT / "backend" / "ai_mouse.py").read_text(encoding="utf-8")
baum = ast.parse(src)
fn_analyse = next(n for n in ast.walk(baum)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "analysieren")
args = [a.arg for a in fn_analyse.args.args]
check("analysieren() nimmt KEINE Bereiche/Werkzeuge aus dem Aufruf entgegen",
      not any(a in args for a in ("bereiche", "werkzeuge", "tools", "system_prompt")))
check("die Bereiche kommen im Rumpf aus freigegebene_bereiche()",
      any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "freigegebene_bereiche"
          for n in ast.walk(fn_analyse)))

print("\n=== 4b. Freigabe speichern schaltet den Skill NICHT ein ===")

# ⚠ ECHTER FUND vom 2026-09-09, auf DEV gemessen: `update_skill_config` setzt
# `enabled = True`, wenn der Skill dem System noch unbekannt ist
# (skills/manager.py: `if "enabled" not in state`). Das Speichern der FREIGABE
# hat den Bereich damit von selbst aktiviert. Eine Freigabe zu setzen ist nicht
# dasselbe wie einen Bereich einzuschalten – deshalb ist das hier eine Regel.
haupt = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
mbaum = ast.parse(haupt)
fn_save = next((n for n in ast.walk(mbaum)
                if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "ai_mouse_areas_speichern"), None)
check("der Speichern-Endpunkt existiert", fn_save is not None)
if fn_save is not None:
    roh_save = ast.get_source_segment(haupt, fn_save) or ""
    # Kommentare raus - sonst liest der Waechter seine eigene Begruendung
    # (dreizehnter Fall dieser Klasse im Projekt).
    ohne_k = "\n".join(z.split("#")[0] for z in roh_save.splitlines())
    check("der Zustand wird VOR dem Schreiben gelesen",
          "get_skill_states()" in ohne_k)
    check("ein unbekannter Skill wird nicht eingeschaltet",
          "save_skill_state" in ohne_k and "enabled" in ohne_k)
    # Die Reihenfolge zaehlt: erst lesen, dann schreiben, dann korrigieren.
    i_lesen = ohne_k.find("get_skill_states()")
    i_update = ohne_k.find("update_skill_config")
    check("gelesen wird VOR dem Update (sonst ist der Vorzustand schon weg)",
          0 <= i_lesen < i_update)
    check("nur das Freigabe-Feld geht hinaus (Teilmenge, kein Formularstand)",
          "FREIGABE_FELD" in ohne_k)

print("\n=== 5. Actor ist hart unprivilegiert ===")

_st = _pytypes.ModuleType("backend.short_tracks_runner")
_st._rechte = lambda u: (True, True, True)
sys.modules["backend.short_tracks_runner"] = _st
a = am._actor("chef")
check("privileged ist False", a.get("privileged") is False)
check("der Benutzer wird durchgereicht", a.get("user") == "chef")
check("Internet/SAP/VEMAS kommen vom Benutzer",
      a.get("internet") and a.get("sap") and a.get("vemas"))
src_actor = ast.get_source_segment(src, next(
    n for n in ast.walk(baum) if isinstance(n, ast.FunctionDef) and n.name == "_actor"))
check("privileged steht als Literal False im Code (nicht konfigurierbar)",
      '"privileged": False' in src_actor)

print("\n=== 6. agent.py: ohne _role_bilder BYTE-GLEICH ===")

# Die Methode wird per ast geschnitten und WIRKLICH ausgefuehrt – agent.py
# laesst sich hier nicht importieren (fastapi & Co.).
asrc = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
abaum = ast.parse(asrc)
mnode = next((n for n in ast.walk(abaum)
              if isinstance(n, ast.FunctionDef) and n.name == "_headless_user_parts"), None)
check("_headless_user_parts existiert", mnode is not None)

if mnode is not None:
    from google.genai import types as gt
    ns = {"types": gt}
    exec(ast.get_source_segment(asrc, mnode).replace("    def ", "def ", 1)
         .replace("\n    ", "\n"), ns)
    f = ns["_headless_user_parts"]

    class _A:
        pass
    a0 = _A()
    p0 = f(a0, "hallo")
    check("ohne _role_bilder: genau EIN Text-Part (byte-gleich zum Vorzustand)",
          len(p0) == 1 and getattr(p0[0], "text", None) == "hallo")
    a0._role_bilder = []
    check("mit LEERER Bildliste ebenfalls unveraendert", len(f(a0, "x")) == 1)
    bild = gt.Part.from_bytes(data=PNG, mime_type="image/png")
    a0._role_bilder = [bild]
    p1 = f(a0, "hallo")
    check("mit _role_bilder: Bild + Text", len(p1) == 2)
    check("das Bild steht in der Part-Liste vorne",
          getattr(p1[0], "inline_data", None) is not None
          and getattr(p1[1], "text", None) == "hallo")

# REGEL: in _run_headless darf der Benutzer-Content nicht mehr von Hand
# gebaut werden - sonst faellt eine kuenftige Stelle still aus dem Bild-Weg.
fn_head = next((n for n in ast.walk(abaum)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_headless"), None)
check("_run_headless gefunden", fn_head is not None)
if fn_head is not None:
    roh_head = ast.get_source_segment(asrc, fn_head) or ""
    check("_run_headless benutzt _headless_user_parts",
          "_headless_user_parts" in roh_head)
    # Genau EINE Ausnahme bleibt: der Auto-Learning-Aufruf (Faktenextraktion,
    # dort waere ein Bild reiner Token-Aufwand). Mehr duerfen es nicht werden.
    check("hoechstens EINE handgebaute Text-Stelle uebrig (Auto-Learning)",
          roh_head.count("parts=[types.Part.from_text(text=task_text)]") <= 1)

print("\n=== 7. Drift-Schranke: _FACH_LESEND steht in vier Modulen ===")


def fach_liste(pfad, name):
    """Holt die Fach-Werkzeugliste aus einem Modul, ohne es zu importieren."""
    try:
        q = (ROOT / pfad).read_text(encoding="utf-8")
        b = ast.parse(q)
    except Exception:  # noqa: BLE001
        return None
    for n in ast.walk(b):
        # ⚠ BEIDE Zuweisungsformen: `X = {...}` ist ein Assign,
        # `X: dict[str, dict] = {...}` ein AnnAssign. Die erste Fassung kannte
        # nur Assign und meldete deshalb zwei Module als "nicht lesbar" –
        # ein Fehler des Waechters, nicht der Daten.
        if isinstance(n, ast.Assign):
            ziele = [getattr(t, "id", "") for t in n.targets]
        elif isinstance(n, ast.AnnAssign):
            ziele = [getattr(n.target, "id", "")]
        else:
            continue
        if n.value is None:
            continue
        if name not in ziele:
            continue
        # Einfache Liste (`_FACH_LESEND = [...]`).
        if isinstance(n.value, (ast.List, ast.Tuple)):
            try:
                return set(ast.literal_eval(n.value))
            except Exception:  # noqa: BLE001
                return None
        # ⚠ BEREICHE als dict: NICHT das ganze dict auswerten. Es enthaelt an
        # anderer Stelle einen Aufruf (`list(...)`), und `literal_eval`
        # scheitert dann am GANZEN Knoten – die zweite Fassung dieses Lesers
        # meldete deshalb "nicht lesbar", obwohl die Listen identisch waren.
        # Also gezielt zu BEREICHE["fach"]["tools"] navigieren.
        if isinstance(n.value, ast.Dict):
            for k, v in zip(n.value.keys, n.value.values):
                if getattr(k, "value", None) != "fach" or not isinstance(v, ast.Dict):
                    continue
                for k2, v2 in zip(v.keys, v.values):
                    if getattr(k2, "value", None) == "tools":
                        try:
                            return set(ast.literal_eval(v2))
                        except Exception:  # noqa: BLE001
                            return None
        return None
    return None


meins = set(am._FACH_LESEND)
check("die eigene Liste ist nicht leer (Positivkontrolle)", len(meins) > 5)
for pfad, name in (("backend/jira_assist.py", "_FACH_LESEND"),
                   ("backend/mail_rules.py", "BEREICHE"),
                   ("backend/short_tracks.py", "BEREICHE")):
    andere = fach_liste(pfad, name)
    if andere is None:
        check("%s: Fach-Liste lesbar" % pfad, False)
    else:
        check("%s traegt dieselbe Fach-Werkzeugliste" % pfad, andere == meins)

print("\n=== 8. Paket: Branding und die ehrliche Grenze ===")

# ⚠ ES GIBT KEINE settings.json UND KEINE prompts.json MEHR (Vorgabe des
# Betreibers, 2026-09-09). Die Hauswerte gehen in den BAU (Vorgaben.cs), die
# Fragen auf den Server, die Benutzereinstellungen in die Registry.
cs = am.vorgaben_cs("https://host.example/", "Nexus DP", "#B80F2E")
check("die Serveradresse steht im erzeugten Quelltext",
      'Endpoint = "https://host.example"' in cs)
check("der abschliessende Schraegstrich faellt weg",
      'https://host.example/"' not in cs)
check("die Marke steht darin", 'Marke = "Nexus DP"' in cs)
check("der Akzent steht darin", '#B80F2E' in cs)
check("KEIN Kennwort und KEIN Token", "kennwort" not in cs.lower() and "token" not in cs.lower())
cs2 = am.vorgaben_cs("x", "M", "rot")
check("unbrauchbare Farbe wird verworfen, nicht durchgereicht",
      am.AKZENT_STANDARD in cs2 and "rot" not in cs2)

# ⚠ DER WERT GEHT IN QUELLTEXT, der uebersetzt wird. Ein Anfuehrungszeichen im
# Firmennamen wuerde die Datei zerlegen – oder waere eine Einschleusung in den
# Bau. Deshalb wird escaped, nicht gehofft.
boes = am.vorgaben_cs("h", 'A" ; class X { static void Y() {} } //', "#000000")
check("Anfuehrungszeichen im Namen werden escaped", '\\"' in boes)
check("der Quelltext bleibt eine einzige Klasse",
      boes.count("internal static class") == 1)
zeilen = am.vorgaben_cs("h", "A\nB", "#000000")
check("ein Zeilenumbruch sprengt die Datei nicht",
      zeilen.count("public const string Marke") == 1)

check("es gibt keine settings.json mehr", not hasattr(am, "settings_gebrandet"))
check("es gibt keine prompts.json mehr", not hasattr(am, "_prompts_vorgabe"))

# Das Paket enthaelt NUR die Anwendung und die Kurzanleitung.
#
# ⚠ `paket_bauen` SCHREIBT Vorgaben.cs im Arbeitsbaum (die Hauswerte gehen ja
# in die Anwendung). Genau so sind am 2026-09-09 die Testplatzhalter "M" und
# "https://h" ins Repo gelangt – und weil der automatische Bau sie damals nicht
# ueberschrieb, trug die ausgelieferte EXE sie. Der Wächter sichert die Datei
# deshalb und stellt sie danach wieder her; ein Test, der den echten Bestand
# veraendert, ist teurer als der Fehler, den er sucht (Register).
if am.paket_vorhanden():
    # ⚠ MIT DEN ECHTEN HAUSWERTEN rufen, nicht mit erfundenen. `_hauswerte_
    # schreiben` ist dann idempotent, es wird nichts geschrieben und KEIN Bau
    # angestossen. Mit "Testhaus"/"https://h" schrieb der Waechter die Quelle um
    # UND startete einen Hintergrund-Thread, der sie NACH der Wiederherstellung
    # noch einmal anfasste – so sind die Platzhalter ins Repo gelangt.
    # Leerer `basis` heisst "bisherige Adresse behalten".
    _mk, _ak = am.branding()
    name, daten = am.paket_bauen("", _mk, _ak)
    import io as _io, zipfile as _z
    innen = sorted(x.filename for x in _z.ZipFile(_io.BytesIO(daten)).infolist())
    # ⚠ GENAU EINE DATEI (Vorgabe 2026-09-11): die Kurzanleitung ist raus,
    # derselbe Inhalt steht in der Kachel. Geprueft wird auf GLEICHHEIT, nicht
    # auf "enthaelt die EXE" – sonst faellt eine kuenftig wieder ergaenzte
    # Beilage nicht auf, und genau darum geht es hier.
    check("im Paket liegt NUR die EXE", innen == ["AiMouse.exe"])
    check("keine Konfigurationsdatei im Paket",
          not any(x.endswith(".json") for x in innen))
    check("keine Kurzanleitung im Paket",
          not any("LIESMICH" in x.upper() or "README" in x.upper() for x in innen))
else:
    check("Paketinhalt geprueft (uebersprungen: keine EXE gebaut)", True)


am.paket_vorhanden = lambda: False
r = sicher(am.paket_bauen, "https://h", "M", "#000000")
check("ohne hinterlegte EXE: Fehler statt kaputtem ZIP", isinstance(r, am.MausFehler))
# ⚠ DIE MELDUNG DARF KEINE HANDARBEIT FORDERN. Eine Aufforderung, ein Skript
# im Terminal auszufuehren, setzt voraus, dass ein Administrator sie zufaellig
# liest – am 2026-09-04 fuer den OneNote-Import ausdruecklich als inakzeptabel
# zurueckgewiesen, am 2026-09-09 hier erneut. Der Server baut selbst.
txt = str(r) if isinstance(r, am.MausFehler) else ""
check("die Meldung sagt, dass automatisch gebaut wird",
      "automatisch" in txt.lower())
check("die Meldung fordert KEINE Handarbeit (kein Skriptaufruf)",
      "ai_mouse_build.sh" not in txt and "bash " not in txt)

print("\n=== 8b. Die Automatik: idempotent und fail-safe ===")

check("Vorgabe: die Automatik ist AN", am.automatik_an())
import os as _os
_os.environ["JARVIS_AIMOUSE_AUTO"] = "0"
check("JARVIS_AIMOUSE_AUTO=0 schaltet sie ab", not am.automatik_an())
check("abgeschaltet wird nichts angestossen",
      am.einrichtung_anstossen("test").startswith("Automatik abgeschaltet"))
_os.environ.pop("JARVIS_AIMOUSE_AUTO", None)

# Liegt eine AKTUELLE Anwendung bereits, passiert NICHTS – auch das ist eine
# Zusage: sonst baute jeder Abruf neu.
#
# ⚠ HIER STAND NUR `paket_vorhanden = True`. Seit dem 2026-09-10 genuegt das
# nicht mehr: eine vorhandene, aber VERALTETE Anwendung ist sehr wohl ein
# Grund zu bauen (gemeldet von ECHT). Der Stub muss die neue Zusage abbilden,
# sonst prueft er eine, die es nicht mehr gibt – und meldet einen Fehler, den
# es nicht gibt.
# ⚠ DIE ECHTEN FUNKTIONEN SICHERN, BEVOR sie ersetzt werden: Abschnitt 18
#   fuehrt `bau_noetig` WIRKLICH aus – ohne diese Sicherung riefe er den Stub
#   von hier und misst seine eigene Attrappe (genau so passiert).
_ECHT_BAU_NOETIG = am.bau_noetig
_ECHT_PAKET_VORHANDEN = am.paket_vorhanden

am.paket_vorhanden = lambda: True
am.bau_noetig = lambda: False
check("bereits vorhanden UND aktuell -> kein Bau",
      am.einrichtung_anstossen("x") == "bereits vorhanden")
# Und die Gegenrichtung – die eigentliche Neuerung.
am.bau_noetig = lambda: True
check("vorhanden, aber VERALTET -> es wird gebaut",
      am.einrichtung_anstossen("x") != "bereits vorhanden")
# ⚠ BEIDE zurueckstellen – die folgenden Pruefungen wollen bis zur
#   Zustandspruefung DURCHkommen. Bliebe `bau_noetig` auf False, gaebe
#   `einrichtung_anstossen` schon vorher „bereits vorhanden" zurueck, und
#   „zu jung"/„laeuft bereits" waeren nie erreichbar (genau so passiert).
am.paket_vorhanden = lambda: False
am.bau_noetig = lambda: True

# ⚠ MINDESTABSTAND: ohne ihn stiesse JEDER Abruf einen eigenen Bau an – auf
# einem Server ohne SDK also im Minutentakt einen vergeblichen apt-Lauf.
am._bau["laeuft"] = False
am._bau["letzter_start"] = __import__("time").time()
check("ein zu junger Versuch wird nicht wiederholt",
      "zu jung" in am.einrichtung_anstossen("x"))
am._bau["laeuft"] = True
check("ein laufender Bau wird nicht doppelt angestossen",
      am.einrichtung_anstossen("x") == "laeuft bereits")
am._bau["laeuft"] = False
am._bau["letzter_start"] = 0.0

# ⚠ DER BAU BRAUCHT KEINE ROOT-RECHTE – und das ist eine Zusage, keine
# Nebensache. Eine erste Fassung ging ueber eine Broker-Op mit
# `apt-get install dotnet-sdk-8.0`; GEMESSEN am 2026-09-09 gibt es dieses Paket
# in Debian 13 gar nicht. Das Bauskript holt sich das SDK stattdessen selbst
# nach vendor/dotnet (Microsofts dotnet-install.sh) – ohne apt, ohne fremdes
# Repo, ohne Broker. Weniger Rechte, weniger Teile, mehr Systeme.
quelle = (ROOT / "backend" / "ai_mouse.py").read_text(encoding="utf-8")
qbaum = ast.parse(quelle)
fn_bau = next((n for n in ast.walk(qbaum)
               if isinstance(n, ast.FunctionDef) and n.name == "_bauen"), None)
check("_bauen existiert", fn_bau is not None)
if fn_bau is not None:
    roh_bau = ast.get_source_segment(quelle, fn_bau) or ""
    ohne_bau = "\n".join(z.split("#")[0] for z in roh_bau.splitlines())
    check("der Bau ruft das Skript direkt", "ai_mouse_build.sh" in ohne_bau)
    check("KEIN Broker-Aufruf mehr im Bau", "broker" not in ohne_bau.lower())
check("kein toter Broker-Zweig im Modul", "_sdk_nachinstallieren" not in quelle)
ops = (ROOT / "backend" / "broker" / "ops.py").read_text(encoding="utf-8")
check("keine verwaiste Broker-Op (Rechtefrage ohne Aufrufer)",
      "ai_mouse_build" not in ops)

# Das Skript muss das SDK selbst beschaffen koennen.
skript = (ROOT / "deploy" / "ai_mouse_build.sh").read_text(encoding="utf-8")
check("das Bauskript holt das SDK bei Bedarf selbst",
      "dotnet-install.sh" in skript)
check("es legt es unter vendor/ ab (dem Dienstbenutzer gehoerend)",
      "vendor/dotnet" in skript)
check("kein apt-Paket, das es auf Debian 13 nicht gibt",
      "apt-get install -y dotnet-sdk" not in skript)
check("abschaltbar", "JARVIS_AIMOUSE_SDK_AUTO" in skript)

print("\n=== 8c. Die Sitzung ueberlebt Test und Speichern (C#-Regeln) ===")

# ⚠ DIESER ABSCHNITT PRUEFT QUELLTEXT, NICHT VERHALTEN. Die Anwendung ist ein
# Windows-Programm und laesst sich hier nicht ausfuehren; gemessen wird also
# die EIGENSCHAFT im Code, nicht ihre Wirkung. Das ist schwaecher als ein Lauf
# und steht deshalb ausdruecklich so da.
#
# GEMELDET am 2026-09-09: "die Authentifizierung wird beim Verbindung testen
# abgefragt, aber nicht gespeichert". Zwei Ursachen, beide hier abgesichert.
cs_tray = (ROOT / "ai-mouse" / "src" / "AiMouse" / "TrayApplicationContext.cs").read_text(encoding="utf-8")
cs_client = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Vision" / "JarvisClient.cs").read_text(encoding="utf-8")


def cs_block(quelle, kopf):
    """Schneidet einen C#-Methodenrumpf ueber die Klammerbilanz.

    Ein Schnitt "bis zur naechsten Leerzeile" oder "bis zum ersten }" wuerde
    hier zu frueh enden (verschachtelte try-Bloecke) oder zu weit greifen und
    fremden Code messen – der 446-Zeilen-Fehler aus dem Register.
    """
    i = quelle.find(kopf)
    if i < 0:
        return ""
    j = quelle.index("{", i)
    tiefe, k = 0, j
    while k < len(quelle):
        if quelle[k] == "{":
            tiefe += 1
        elif quelle[k] == "}":
            tiefe -= 1
            if tiefe == 0:
                return quelle[i:k + 1]
        k += 1
    return quelle[i:]


test = cs_block(cs_tray, "private async Task<string> TestConnectionAsync")
check("TestConnectionAsync gefunden", len(test) > 200)
if test:
    # (1) Ein `using var` haette das Token beim Verlassen weggeworfen - genau
    # der gemeldete Fall.
    check("der Probe-Client ist KEIN `using var` (sonst stirbt das Token)",
          "using var probeClient" not in test)
    check("die Sitzung wird uebernommen", "SitzungUebernehmen" in test)
    check("nur bei GLEICHER Adresse", "gleicheAdresse" in test)
    check("die Adressen werden ueber EndpointResolver verglichen (eine Regel)",
          test.count("EndpointResolver.Basis") >= 2)
    check("der Benutzername wird gemerkt", "ConfigStore.SaveSettings" in test)
    check("der Client wird auch im Fehlerfall freigegeben",
          "finally" in test and "probeClient.Dispose()" in test)

anw = cs_block(cs_tray, "private void ApplySettings")
check("ApplySettings gefunden", len(anw) > 100)
if anw:
    # (2) Der schwerere Fall: JEDES Speichern baute den Client neu und warf die
    # Anmeldung weg - auch ein blosser Sprachwechsel.
    check("beim Speichern wird die Sitzung mitgenommen",
          "SitzungUebernehmen" in anw)
    check("aber NICHT bei geaenderter Adresse (Token gilt dort nicht)",
          "!adresseNeu" in anw)
    check("der alte Client wird freigegeben", "alt.Dispose()" in anw)

uebern = cs_block(cs_client, "public void SitzungUebernehmen")
check("SitzungUebernehmen gefunden", len(uebern) > 50)
if uebern:
    check("ein leeres Token wird nicht uebernommen",
          "_token.Length > 0" in uebern)
    check("null wird abgefangen", "is not null" in uebern)

print("\n=== 8d. Die Fragen werden BEIM START geladen ===")
# ⚠ VORGABE 2026-09-09: "Die Anwendung muss das beim Start laden!" Vorher hing
# das Nachladen nur am Verbindungstest und am Tray-Menue – nach einer normalen
# Anmeldung stand im Menue dauerhaft die eingebaute Vorgabeliste, und was jemand
# im Portal eintrug, tauchte NIE auf (genau so gemeldet).
#
# Gemessen wird die EIGENSCHAFT "jeder Weg, der anmeldet, laedt danach", nicht
# das Vorkommen des Namens irgendwo in der Datei.
cs_sicher = cs_block(cs_tray, "private async Task<bool> SicherstellenAngemeldetAsync")
check("SicherstellenAngemeldetAsync gefunden", len(cs_sicher) > 100)
if cs_sicher:
    check("nach der Anmeldung werden die Fragen geholt",
          "FragenNachladenAsync" in cs_sicher)
    # AWAIT, nicht nebenher: der Aufrufer baut unmittelbar danach das Menue.
    # Ein nebenherlaufender Abruf waere ein Wettlauf, den der Benutzer als
    # "die erste Frage fehlt noch" sieht.
    check("und zwar ABGEWARTET, nicht nebenher",
          "await FragenNachladenAsync()" in cs_sicher)
    i_f = cs_sicher.find("FragenNachladenAsync")
    i_r = cs_sicher.rfind("return true")
    check("der Abruf steht VOR dem Erfolgs-Rueckgabewert",
          0 < i_f < i_r)

start = cs_block(cs_tray, "private async Task StartAnmeldungAsync")
check("StartAnmeldungAsync gefunden", len(start) > 100)
if start:
    check("sie meldet an (und laedt damit die Fragen)",
          "SicherstellenAngemeldetAsync" in start)
    # Ohne Serveradresse waere die Anmeldemaske eine Sackgasse.
    check("ohne Einrichtung fuehrt der Weg in die Einstellungen",
          "ConfigStore.Eingerichtet()" in start and "ShowSettings()" in start)
    # Ein Fehlerfenster beim Windows-Start waere Stoerung, kein Dienst.
    check("ein Fehlschlag ist still", "catch (Exception)" in start)

# Der Aufruf im Konstruktor ist die eigentliche Zusage – ohne ihn ist die
# Methode toter Code, und "beim Start" waere unerfuellt.
ktor = cs_block(cs_tray, "public TrayApplicationContext()")
check("der Konstruktor stoesst die Start-Anmeldung an",
      "StartAnmeldungAsync" in ktor)
# BeginInvoke und nicht direkt: der Konstruktor laeuft VOR der
# Nachrichtenschleife – ein modaler Dialog von dort haette kein Fenster, an dem
# er haengen kann, und erschiene hinter allem anderen oder gar nicht.
check("ueber BeginInvoke, nicht mitten im Konstruktor",
      "BeginInvoke" in ktor and "StartAnmeldungAsync" in ktor.split("BeginInvoke")[-1])

laden = cs_block(cs_tray, "private async Task FragenNachladenAsync")
if laden:
    # Eine LEERE Antwort darf die vorhandenen Fragen nicht wegwerfen: ein
    # Serverfehler saehe sonst aus wie "alle Fragen geloescht".
    check("eine leere Antwort ersetzt die Liste NICHT", "neu.Count > 0" in laden)
    check("ohne Anmeldung wird gar nicht erst gefragt", "_client.Angemeldet" in laden)

print("\n=== 8e. Erster Start: Adresse fragen, Sitzung merken, kein Kennwort ===")
# ⚠ VORGABE 2026-09-09: "Beim ersten Start der EXE muss Server URL und
# Anmeldedaten abgefragt werden, dann wenn die Anmeldung moeglich ist die
# Prompts geladen werden und alles in die registry."
cs_store = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Configuration" / "ConfigStore.cs").read_text(encoding="utf-8")
cs_login = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "LoginWindow.cs").read_text(encoding="utf-8")

# (a) Die Adresse steht in den EINSTELLUNGEN, nicht in der Anmeldemaske
# (Vorgabe 2026-09-09, zweite Aufforderung) – dort, wo sie auch spaeter
# geaendert wird. Der Wächter für die Felder steht in Abschnitt 8f.
check("die Anmeldemaske fragt die Adresse NICHT", "_adresse" not in cs_login)
# Ein leerer Benutzername darf nicht durchgehen.
check("ein leerer Benutzername wird abgefangen",
      "FormClosing" in cs_login and "e.Cancel = true" in cs_login)

# (b) Der erste Start wird an der ADRESSE erkannt, nicht am Schluessel.
eingr = cs_block(cs_store, "public static bool Eingerichtet()")
check("Eingerichtet() gefunden", len(eingr) > 30)
check("es entscheidet die Serveradresse, nicht die Existenz des Schluessels",
      'Lies(k, "Endpoint").Length > 0' in eingr)

sicher2 = cs_block(cs_tray, "private async Task<bool> SicherstellenAngemeldetAsync")
check("der erste Start wird ueber Eingerichtet() erkannt",
      "ConfigStore.Eingerichtet()" in sicher2)
check("und fuehrt in die Einstellungen", "ShowSettings()" in sicher2)
i_anm = sicher2.find("AnmeldenAsync")

# (c) Geschrieben wird erst NACH gelungener Anmeldung.
i_save = sicher2.find("ConfigStore.SaveSettings")
check("gespeichert wird erst NACH dem Anmelden", 0 < i_anm < i_save)
check("die Sitzung wird gemerkt", "ConfigStore.SaveToken(_client.Token)" in sicher2)

# (d) NIE ein Kennwort auf Platte – die zentrale Zusage.
# ⚠ OHNE KOMMENTARE MESSEN. Der Modulkopf erklaert, WARUM hier nie ein
# Kennwort steht – wer den Rohtext durchsucht, findet die eigene Begruendung
# und meldet einen Fehler, den es nicht gibt (im Projekt der 14. Fall).
#
# SCHLICHT, nicht klug: eine Zustandsmaschine ueber C#-Strings stolpert ueber
# verbatim-Literale (@"Software\AiMouse" – dort ist \ kein Escape); mein
# erster Anlauf tat das und lieferte den Text unveraendert zurueck. Hier
# genuegt "Zeile beginnt mit //", und die Positivkontrolle darunter belegt,
# dass es wirklich gegriffen hat.
store_code = "\n".join(z for z in cs_store.split("\n")
                        if not z.lstrip().startswith("//"))
check("Kommentar-Entferner greift (Positivkontrolle)",
      "DataProtectionScope" in store_code and "DPAPI" not in store_code)
check("ConfigStore schreibt kein Kennwort",
      "Kennwort" not in store_code and "assword" not in store_code)
tok = cs_block(cs_store, "public static void SaveToken")
check("SaveToken gefunden", len(tok) > 50)
if tok:
    # DPAPI bindet den Wert an das Windows-Konto: ein anderer Benutzer
    # desselben Rechners kann ihn nicht lesen, eine kopierte Registry ist
    # woanders wertlos. Ohne das laege ein Token im Klartext, das die VOLLE
    # Sitzung traegt.
    check("das Token wird per DPAPI verschluesselt",
          "ProtectedData.Protect" in tok and "DataProtectionScope.CurrentUser" in tok)
    check("ein leeres Token LOESCHT den Wert (Rest waere gefaehrlich)",
          "DeleteValue" in tok)

# (e) Beim Start werden Sitzung UND Fragen uebernommen – ohne Serveraufruf.
ktor2 = cs_block(cs_tray, "public TrayApplicationContext()")
check("die gemerkte Sitzung wird beim Start uebernommen",
      "_client.TokenSetzen(ConfigStore.LoadToken())" in ktor2)
check("die gemerkten Fragen ebenso", "ConfigStore.LoadPrompts()" in ktor2)
check("ohne gemerkte Fragen gelten die eingebauten",
      "PromptItem.Defaults" in ktor2)
laden2 = cs_block(cs_tray, "private async Task FragenNachladenAsync")
check("geholte Fragen werden gemerkt", "ConfigStore.SavePrompts" in laden2)

# (f) Ein Adresswechsel raeumt Sitzung und Fragen ab.
anw2 = cs_block(cs_tray, "private void ApplySettings")
check("bei neuer Adresse wird die gemerkte Sitzung verworfen",
      "ConfigStore.SaveToken(null)" in anw2)
check("und die Fragen des alten Kontos auch",
      "ConfigStore.SavePrompts([])" in anw2)

# (g) "Konfiguration neu laden" ist obsolet (Vorgabe).
# Es gibt keine Dateien mehr, die man neu einlesen koennte.
check("der Menuepunkt ist weg", "ReloadConfiguration" not in cs_tray)
cs_texte = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Localization" / "Texte.cs").read_text(encoding="utf-8")
check("und sein Text ebenfalls (kein toter Code)", "NeuLaden" not in cs_texte)

def py_schnitt(name):
    """Rumpf einer Funktion aus backend/ai_mouse.py – ueber den AST, damit ein
    gleichlautender Name in einem Kommentar nicht mitgeschnitten wird."""
    baum = ast.parse(quelle)
    for k in ast.walk(baum):
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            zeilen = quelle.split("\n")[k.lineno - 1:k.end_lineno]
            return "\n".join(zeilen)
    return ""


print("\n=== 8f. Branding, Zugangsdaten und Sprache (Vorgaben 2026-09-09) ===")
cs_set = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "SettingsWindow.cs").read_text(encoding="utf-8")
# ⚠ DIE SICHERUNG, nicht die Datei: weiter oben hat ein `paket_bauen`-Aufruf
# die Hauswerte dieses Servers hineingeschrieben. Gemeint ist hier aber der
# Stand IM REPO – also der, mit dem der Lauf begonnen hat.
cs_vorg = _VORG_SICHERUNG or ""

# (a) ⚠ DAS BRANDING MUSS IN DIE EXE – gemeldet, weil der AUTOMATISCHE Bau
# (Startup, Bootstrap 6g, auf Bedarf) mit dem lief, was zufaellig in
# Vorgaben.cs stand. Im Repo waren das Testplatzhalter; die ausgelieferte
# Anwendung trug damit weder Marke noch Farbe des Hauses.
bauen = py_schnitt("_bauen")
check("_bauen gefunden", len(bauen) > 50)
check("der Bau setzt die Hauswerte SELBST", "_hauswerte_schreiben()" in bauen)
i_hw = bauen.find("_hauswerte_schreiben")
i_run = bauen.find("subprocess.run")
check("und zwar VOR dem Aufruf des Bauskripts", 0 < i_hw < i_run)
# Fail-open: lieber mit alten Werten bauen als gar nicht.
check("ein Fehlschlag verhindert den Bau NICHT",
      "except Exception" in bauen[i_hw:i_run])

hw = py_schnitt("_hauswerte_schreiben")
check("_hauswerte_schreiben gefunden", len(hw) > 50)
check("Marke und Akzent kommen aus branding()", "branding()" in hw)
check("die Sprache aus sprache()", "sprache()" in hw)
# Ohne Request bleibt die Adresse stehen, statt geleert zu werden.
check("ohne Adresse wird die bisherige uebernommen", "Endpoint" in hw)
# EINE Stelle schreibt die Quelle – zwei liefen beim naechsten Feld auseinander.
check("der Download-Weg benutzt dieselbe Funktion",
      "_hauswerte_schreiben(basis)" in py_schnitt("_vorgaben_sicherstellen"))

# Im Repo stehen ehrliche Vorgaben, keine Testreste.
# ⚠ AUCH DAS BAU-SKRIPT MUSS SIE SETZEN – es ist der Weg des Bootstraps
# (Schritt 6g) und der Handarbeit. Nur im Python-Weg zu korrigieren liess
# genau diese Wege eine Anwendung ohne Hausmarke bauen (live gemessen:
# vorher „Jarvis", nach dem Fix „Nexus DP").
skript = (ROOT / "deploy" / "ai_mouse_build.sh").read_text(encoding="utf-8")
check("das Bau-Skript setzt die Hauswerte", "_hauswerte_schreiben()" in skript)
# ⚠ OHNE KOMMENTARE SUCHEN: der Skriptkopf zitiert `dotnet publish` in seiner
# Begruendung, und `find()` traf diese Zeile statt des Aufrufs – der Waechter
# meldete einen Fehler, den es nicht gab (15. Fall dieser Klasse).
skript_code = "\n".join(z for z in skript.split("\n") if not z.lstrip().startswith("#"))
i_hw2 = skript_code.find("_hauswerte_schreiben")
i_pub = skript_code.find("dotnet publish")
check("Kommentar-Filter greift (Positivkontrolle)",
      "dotnet publish" in skript_code and "DEV-Hardware" not in skript_code)
check("und zwar VOR dem Uebersetzen", 0 < i_hw2 < i_pub)
check("ein Fehlschlag verhindert den Bau nicht (fail-open)",
      "baue mit den vorhandenen" in skript)

# ⚠ `branding()` MUSS OHNE GELADENES `main` FUNKTIONIEREN – ein frisches
# Python (Skript, Bootstrap) hat es nicht, und ohne Rueckfall lieferte es dort
# den Jarvis-Standard: genau der gemeldete Zustand.
brd = py_schnitt("branding")
check("branding() liest notfalls selbst aus der Konfiguration",
      "get_skill_states()" in brd)

check("keine Testplatzhalter im Repo",
      '"M"' not in cs_vorg and '"https://h"' not in cs_vorg)
# ⚠ NUR IM AUSLIEFERUNGSSTAND. Auf einem BETRIEBENEN Server hat der erste
# Paket-Download die Adresse eingetragen – dort ist ein Wert richtig, und die
# Pruefung meldete einen Fehler, den es nicht gibt (auf DEV genau so passiert).
# Erkannt an der Marke: steht dort die Vorgabe, hat noch kein Bau stattgefunden.
if 'Marke = "Jarvis"' in cs_vorg:
    check("im Auslieferungsstand ist die Adresse LEER",
          'Endpoint = ""' in cs_vorg)
else:
    check("Adresse: uebersprungen (Server hat eigene Hauswerte gesetzt)", True)

# (c) i18n in die EXE.
spr = py_schnitt("sprache")
check("sprache() gefunden", len(spr) > 30)
check("alles ausser 'en' ist Deutsch (fail-safe)", 'startswith("en")' in spr)
check("die Sprache steht in den einkompilierten Vorgaben", "Sprache" in cs_vorg)
cs_texte2 = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Localization" / "Texte.cs").read_text(encoding="utf-8")
check("der Client liest sie von dort", "Vorgaben.Sprache" in cs_store)

# (b) ⚠ DIE ZUGANGSDATEN GEHOEREN IN DIE EINSTELLUNGS-MASKE (zweite
# Aufforderung des Betreibers). Vorher standen sie in einer eigenen Maske, die
# nur beim ersten Start erschien – wer sein Kennwort aenderte, fand keinen Weg.
# ⚠ NICHT die Deklaration pruefen, sondern die ZEILE IM FORMULAR: ein Feld,
# das nur deklariert ist, sieht niemand. Zwei Gegenproben blieben dadurch
# zuerst stumm (Register: die Eigenschaft messen, nicht das Vorkommen).
check("der Einstellungsdialog ZEIGT ein Benutzerfeld",
      "AddRow(layout, Texte.Benutzername, _benutzer)" in cs_set)
check("und ein Kennwortfeld",
      "AddRow(layout, Texte.Kennwort, _kennwort)" in cs_set)
check("das Kennwort ist maskiert", "UseSystemPasswordChar = true" in cs_set)
# Es darf NICHT in AppSettings landen: das wird gespeichert.
check("das Kennwort ist KEINE Einstellung, sondern eine eigene Eigenschaft",
      "public string Kennwort { get; private set; }" in cs_set)
set_code = "\n".join(z for z in cs_set.split("\n") if not z.lstrip().startswith("//"))
check("es wird nirgends in die Einstellungen geschrieben",
      "Kennwort = _kennwort" not in set_code.replace("Kennwort = _kennwort.Text;", ""))
# Ein leerer Benutzername darf den bisherigen nicht loeschen.
check("leerer Benutzername laesst den bisherigen stehen",
      "_ausgang.Benutzer" in cs_set)

zeig = cs_block(cs_tray, "private void ShowSettings")
check("nach dem Speichern wird mit Kennwort angemeldet",
      "AnmeldenMitKennwortAsync" in zeig)
check("aber NUR wenn eines eingegeben wurde",
      "dialog.Kennwort.Length > 0" in zeig)
anm = cs_block(cs_tray, "private async Task AnmeldenMitKennwortAsync")
check("dieser Weg merkt die Sitzung", "ConfigStore.SaveToken" in anm)
check("und holt die Fragen", "FragenNachladenAsync" in anm)
check("ein Fehlschlag wird gemeldet", "ShowTrayError" in anm)

# Der erste Start fuehrt in die EINSTELLUNGEN, nicht in eine eigene Maske.
start2 = cs_block(cs_tray, "private async Task StartAnmeldungAsync")
check("der erste Start oeffnet die Einstellungen", "ShowSettings()" in start2)
sich3 = cs_block(cs_tray, "private async Task<bool> SicherstellenAngemeldetAsync")
check("auch der Anmeldeweg schickt Uneingerichtete dorthin",
      "ShowSettings()" in sich3)
# Die Anmeldemaske fragt die Adresse NICHT mehr – toter Code waere sie sonst.
cs_login2 = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "LoginWindow.cs").read_text(encoding="utf-8")
check("die Anmeldemaske hat kein Adressfeld mehr", "_adresse" not in cs_login2)
check("und kein toter Text blieb zurueck", "AdresseUnbrauchbar" not in cs_texte2)

print("\n=== 8g. Kein zweites Anmeldefenster (Vorgaben 2026-09-09) ===")
# ⚠ ZWEI GEMELDETE FEHLER, beide Folge davon, dass die Zugangsdaten in den
# Einstellungsdialog gewandert sind und ich die Wege drumherum nicht mitzog.

# (1) „Verbindung testen" fragte die Zugangsdaten in einem EIGENEN Fenster ab,
# waehrend sie zwei Zeilen darueber im Dialog standen.
test = cs_block(cs_tray, "private async Task<string> TestConnectionAsync")
check("TestConnectionAsync gefunden", len(test) > 100)
check("es bekommt Benutzer und Kennwort UEBERGEBEN",
      "string benutzer," in test and "string kennwort," in test)
# ⚠ Der Einmal-Code BLEIBT eine Rueckfrage: er steht nicht im Dialog, und nur
# die Oberflaeche kann ihn erfragen. Verboten ist die Frage nach BENUTZER und
# KENNWORT – also der Aufruf ohne `totpNoetig`.
import re as _re
_fragen = [z for z in test.split("\n")
           if "FrageAnmeldung(" in z and "totpNoetig" not in z]
check("es fragt Benutzer/Kennwort NICHT mehr selbst ab (%s)" % (_fragen[:1] or "sauber"), not _fragen)
# Ohne Kennwort wird die laufende Sitzung geprueft statt zu fragen – das ist
# der haeufige Fall (Kleinigkeit geaendert, dann testen).
check("ohne Kennwort wird die laufende Sitzung geprueft",
      "kennwort.Length == 0" in test and "_client.Angemeldet" in test)
check("bei fremder Adresse ohne Kennwort eine klare Absage",
      "KennwortFehlt" in test)
# ⚠ AM AUFRUF messen, nicht irgendwo in der Datei: `_benutzer.Text.Trim()`
# steht auch in `BuildSettings` – die Pruefung blieb dadurch gruen, als der
# Aufruf leere Zeichenketten uebergab.
import re as _re2
# Non-greedy stoppt an der ERSTEN Klammer – das ist `_benutzer.Text.Trim()`.
# Deshalb bis zum letzten Argument schneiden, das jeder Aufruf hat.
_i = cs_set.find("_tester(")
_ruf = _re2.match(r"(.*?_testCts\.Token)", cs_set[_i:], _re2.S) if _i >= 0 else None
check("der Dialog reicht die Felder AM AUFRUF durch",
      bool(_ruf) and "_benutzer.Text" in _ruf.group(1) and "_kennwort.Text" in _ruf.group(1),
)
check("und seine Signatur nimmt sie an",
      "Func<AppSettings, string, string, CancellationToken, Task<string>>" in cs_set)

# (2) Direkt nach dem Start erschien ein Anmeldefenster.
start3 = cs_block(cs_tray, "private async Task StartAnmeldungAsync")
# ⚠ OHNE KOMMENTARE: der Block erklaert, WARUM er sich nicht anmeldet, und
# nennt die Funktion dabei beim Namen (16. Fall dieser Klasse).
start3_code = "\n".join(z for z in start3.split("\n") if not z.lstrip().startswith("//"))
# ⚠ Die Positivkontrolle braucht einen Ausdruck, der NUR im Kommentar steht.
# Mein erster ("gemeldet") steckt in „An\u0067emeldet" – der Filter sah kaputt
# aus, obwohl er greift.
check("Kommentar-Filter greift (Positivkontrolle)",
      "ConfigStore.Eingerichtet()" in start3_code
      and "Anmeldefenster" not in start3_code)
check("der Start meldet sich NICHT selbst an",
      "SicherstellenAngemeldetAsync" not in start3_code)
check("er holt nur die Fragen – und nur mit gemerkter Sitzung",
      "_client.Angemeldet" in start3 and "FragenNachladenAsync" in start3)
# Ohne Einrichtung bleibt der Weg in die Einstellungen: sonst kann der
# Benutzer gar nichts tun.
check("uneingerichtet fuehrt es weiterhin in die Einstellungen",
      "ConfigStore.Eingerichtet()" in start3 and "ShowSettings()" in start3)
# Die Anmeldung passiert dort, wo sie gebraucht wird.
check("der Rahmen-Weg meldet weiterhin an",
      "SicherstellenAngemeldetAsync" in cs_tray)

print("\n=== 8h. Anzeigename: DE AI-Maus, EN AI-Mouse (Vorgabe 2026-09-09) ===")
import json as _json2
_skill = _json2.loads((ROOT / "skills" / "ai_mouse" / "skill.json").read_text(encoding="utf-8"))
check("der Skill heisst AI-Maus", _skill.get("name") == "AI-Maus")
# ⚠ DER VERZEICHNISNAME BLEIBT `ai_mouse`. Daran haengen SKILL_NAME, die
# Freigabefelder (`aimouse_allowed_*`) und die gespeicherten Skill-Zustaende –
# ein Umbenennen waere ein stiller Verlust der Konfiguration auf jedem Server.
check("der Verzeichnisname ist unveraendert", (ROOT / "skills" / "ai_mouse").is_dir())
check("SKILL_NAME zeigt weiter darauf", 'SKILL_NAME = "ai_mouse"' in quelle)

# Der Anzeigename ist zweisprachig – und jede Haelfte traegt IHRE Schreibweise.
_i18 = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8").split("\n")
_gr = next(i for i, x in enumerate(_i18) if x.rstrip() == "    en: {")
_de_falsch = [x.strip()[:60] for i, x in enumerate(_i18) if i < _gr and "AI-Mouse" in x]
_en_falsch = [x.strip()[:60] for i, x in enumerate(_i18) if i >= _gr and "AI-Maus" in x]
check("kein AI-Mouse in der deutschen Haelfte (%s)" % (_de_falsch[:1] or "sauber"), not _de_falsch)
check("kein AI-Maus in der englischen Haelfte (%s)" % (_en_falsch[:1] or "sauber"), not _en_falsch)
def _wert(schl, engl):
    ab = _gr if engl else 0
    bis = len(_i18) if engl else _gr
    for i in range(ab, bis):
        if ("'%s':" % schl) in _i18[i]:
            return _i18[i].split(":", 1)[1].strip().rstrip(",").strip("'")
    return None
check("Kachel DE = AI-Maus", _wert("portal.card_aimouse", False) == "AI-Maus")
check("Kachel EN = AI-Mouse", _wert("portal.card_aimouse", True) == "AI-Mouse")
check("Seitentitel ebenso",
      _wert("aimouse.title", False) == "AI-Maus" and _wert("aimouse.title", True) == "AI-Mouse")
# Das Rueckfall-Markup gilt, bis i18n greift – es darf nicht die alte
# Schreibweise zeigen.
for _d in ("frontend/portal.html", "frontend/ai_mouse.html", "frontend/settings.html"):
    check("%s ohne alte Schreibweise" % Path(_d).name,
          "AI Mouse" not in (ROOT / _d).read_text(encoding="utf-8"))

print("\n=== 8i. Erster Start und Branding der Fenster (Vorgaben 2026-09-09) ===")
cs_login3 = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "LoginWindow.cs").read_text(encoding="utf-8")
cs_set3 = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "SettingsWindow.cs").read_text(encoding="utf-8")
cs_mark = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "Marken.cs")

# (a) „Eingerichtet" heisst: man kann damit ARBEITEN. Die Adresse allein
# genuegt nicht – sie ist einkompiliert und wird beim ersten Speichern
# mitgeschrieben; die Anwendung galt damit als eingerichtet, obwohl noch keine
# Zugangsdaten hinterlegt waren, und der Dialog blieb aus.
eing = cs_block(cs_store, "public static bool Eingerichtet()")
check("Eingerichtet() verlangt Adresse UND Benutzer",
      'Lies(k, "Endpoint")' in eing and 'Lies(k, "Benutzer")' in eing)
check("und verknuepft sie mit UND, nicht ODER", "&&" in eing and "||" not in eing)

# (b) Der Marken-Kopf gehoert BEIDEN Fenstern – aus EINER Fassung.
check("es gibt ein gemeinsames Marken-Modul", cs_mark.is_file())
if cs_mark.is_file():
    mk = cs_mark.read_text(encoding="utf-8")
    # ⚠ DIE EIGENSCHAFT, NICHT DIE SCHREIBWEISE. Hier stand
    #   `"public static Label Kopf" in mk` – das ist eine Aussage ueber den
    #   RUECKGABETYP, nicht darueber, dass ein Kopf geliefert wird. Als der Kopf
    #   um die Versionsanzeige wuchs (zwei Schriftgrade brauchen einen Container,
    #   also `Control` statt `Label`), meldete der Waechter einen Fehler, den es
    #   nicht gab. Ein Waechter, der eine Erweiterung verbietet, die er gar nicht
    #   pruefen will, ist die haeufigste Fehlerklasse dieses Projekts.
    check("es liefert einen Kopf",
          re.search(r"public\s+static\s+\w+\s+Kopf\s*\(", mk) is not None)
    check("und die Hausfarbe", "public static Color AkzentFarbe" in mk)
    # Die Version steht im GETEILTEN Kopf und damit in BEIDEN Fenstern – bis
    # 2026-09-11 war sie nur ueber die Windows-Dateieigenschaften zu sehen.
    check("der Kopf nennt die Version",
          "Aktualisierung.EigeneAnzeige" in mk and "Texte.Version" in mk)
    # Fail-safe: eine kaputte Farbe darf kein Fenster blockieren.
    check("eine unbrauchbare Farbe wird abgefangen",
          "catch (Exception)" in mk and "SystemColors.ControlText" in mk)
check("die Anmeldemaske benutzt es", "Marken.Kopf(" in cs_login3)
check("der Einstellungsdialog ebenfalls", "Marken.Kopf(" in cs_set3)
# Keine zweite Fassung: sonst traegt ein Fenster die Hausfarbe und das andere
# nicht, und niemand kann erklaeren warum.
check("keine eigene Farbfunktion mehr im Anmeldefenster",
      "private static Color AkzentFarbe" not in cs_login3)
check("und keine im Einstellungsdialog",
      "private static Color AkzentFarbe" not in cs_set3)

print("\n=== 9. System-Prompt: Bildinhalt ist Material ===")

p_ohne = am._system_prompt([], "aa11")
check("der Prompt sagt, dass Bildinhalt keine Anweisung ist",
      "KEINE ANWEISUNG" in p_ohne.upper())
check("ohne Bereiche steht keine Ergebnis-Marke im Prompt",
      "[[ERGEBNIS" not in p_ohne)
p_mit = am._system_prompt(["wissen"], "aa11")
check("mit Bereichen traegt der Prompt die Ergebnis-Marke samt Kennung",
      "[[ERGEBNIS aa11]]" in p_mit)
check("mit Bereichen wird auf 'nur lesend' hingewiesen",
      "lesend" in p_mit.lower())

print("\n=== 10. Ergebnis-Marke: fail-open ===")

check("Text nach der Marke wird herausgeschnitten",
      am._ergebnis_teilen("Ich sehe nach.[[ERGEBNIS a1]]\nDas Ergebnis.", "a1")
      == "Das Ergebnis.")
check("OHNE Marke gilt der ganze Text (fail-open)",
      am._ergebnis_teilen("Nur Text.", "a1") == "Nur Text.")
check("Marke ohne Text dahinter: ganzer Text (fail-open)",
      am._ergebnis_teilen("Vorher.[[ERGEBNIS a1]]   ", "a1") == "Vorher.[[ERGEBNIS a1]]   ")

print("\n=== 11. Drossel ===")

am._reset_fuer_tests()
am._drosseln("u1")
r = sicher(am._drosseln, "u1")
check("zwei Anfragen unmittelbar hintereinander: die zweite wird gebremst",
      isinstance(r, am.MausFehler))
check("ein ANDERER Benutzer ist davon nicht betroffen",
      not isinstance(sicher(am._drosseln, "u2"), am.MausFehler))

print("\n=== 12. Ergebnisfenster: klickbare Links (2026-09-10) ===")
#
# VORGABE: "kann das Ergebnisfenster RICH Text liefern, also einen klickbaren
# Link?" – ja, ueber `RichTextBox.DetectUrls`. FORMATIERT WIRD NICHTS, nur
# Adressen werden Links.
#
# ⚠ DER LINKTEXT IST FREMDTEXT: die Antwort entsteht aus einem
# BILDSCHIRMAUSSCHNITT. `Process.Start(..., UseShellExecute = true)` startet
# JEDES registrierte Schema – deshalb eine Erlaubnisliste. Was `Uri.TryCreate`
# mit `ms-msdt:` oder `\\server\freigabe` wirklich macht, entscheidet die
# .NET-Laufzeit und NICHT dieser Waechter: das misst
# `tests/live_linkziel_dev.py`, indem es die ECHTE Klasse uebersetzt und
# AUSFUEHRT. Hier steht die Verdrahtung.
cs_ergebnis = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui"
               / "ResultWindow.cs").read_text(encoding="utf-8")
cs_linkziel = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui"
               / "LinkZiel.cs").read_text(encoding="utf-8")


def cs_nackt(s):
    """C#-Kommentare zeilenweise weg – ein Waechter, der seine eigene
    Begruendung liest, prueft nichts (Register, dreizehn belegte Faelle).
    Bewusst die schlichte Variante samt Positivkontrolle darunter: ein
    Zustandsautomat stolpert ueber verbatim-Literale und gibt den Text dann
    unveraendert zurueck – am 2026-09-09 genau so passiert."""
    return "\n".join(z for z in s.split("\n") if not z.lstrip().startswith("//"))


erg_code = cs_nackt(cs_ergebnis)
lz_code = cs_nackt(cs_linkziel)
check("Positivkontrolle: der Kommentar-Entferner hat wirklich gekuerzt",
      len(erg_code) < len(cs_ergebnis) and "RichTextBox" in erg_code)

# (a) Das Ausgabefeld kann ueberhaupt Links.
check("das Ausgabefeld ist eine RichTextBox (die TextBox konnte keine Links)",
      "new RichTextBox" in erg_code and "new TextBox" not in erg_code)
check("Linkerkennung ist eingeschaltet", "DetectUrls = true" in erg_code)
# ⚠ Ohne Zuhoerer ist der Link blau und TOT – die RichTextBox oeffnet nichts.
check("und der Klick ist verdrahtet (sonst ist der Link blau und wirkungslos)",
      "LinkClicked" in erg_code and "LinkOeffnen" in erg_code)

# (b) Geoeffnet wird NUR die gepruefte Adresse.
oeffner = cs_block(cs_ergebnis, "private void LinkOeffnen")
oeffner_code = cs_nackt(oeffner)
check("der Oeffner fragt LinkZiel.IstWeb", "LinkZiel.IstWeb" in oeffner_code)
check("⚠ und startet NUR die gepruefte Adresse (AbsoluteUri), nie den Rohtext",
      "adresse.AbsoluteUri" in oeffner_code
      and "ProcessStartInfo(ziel" not in oeffner_code)
check("bei Ablehnung wird gar nicht erst gestartet (frueher Ausstieg)",
      "return;" in oeffner_code and "Process.Start" in oeffner_code
      and oeffner_code.index("return;") < oeffner_code.index("Process.Start"))
# Eine stille Ablehnung waere von einem kaputten Fenster nicht zu unterscheiden.
check("eine Ablehnung SAGT es (Grund + Ausweg im Kopf des Fensters)",
      "Texte.LinkNichtGeoeffnet" in oeffner_code)
check("ein Fehlschlag beim Oeffnen wird ebenfalls gemeldet",
      "Texte.LinkFehler" in oeffner_code)

# (c) Die Regel steht in EINER Klasse – und die haengt an keiner Oberflaeche
#     (sonst waere sie nicht ausfuehrbar zu pruefen).
check("die Pruefung liegt in LinkZiel", "static class LinkZiel" in lz_code)
check("LinkZiel haengt an KEINER Oberflaeche (sonst nicht ausfuehrbar messbar)",
      not any(w in lz_code for w in ("Form", "Control", "System.Windows.Forms",
                                     "MessageBox", "RichTextBox")))
check("⚠ ERLAUBNISLISTE statt Sperrliste (was morgen dazukommt, ist draussen)",
      "UriSchemeHttp" in lz_code and "UriSchemeHttps" in lz_code)
# ⚠ HIER STAND EINMAL "IsFile/IsUnc ist zusaetzlich ausgeschlossen" – die Zeile
# im Code war NACHWEISLICH TOT (UNC und C:\… tragen in .NET das Schema `file`
# und scheitern schon an der Erlaubnisliste; ihr Entfernen aenderte keinen
# einzigen der 24 Live-Faelle). Sie ist deshalb raus, und diese Pruefung misst
# jetzt, dass sie nicht als Schein-Tiefenverteidigung zurueckkommt. Dass UNC
# WIRKLICH abgewiesen wird, misst `tests/live_linkziel_dev.py` ausgefuehrt.
check("keine tote Zweitpruefung (IsFile/IsUnc waere hier wirkungslos)",
      "IsUnc" not in lz_code and "IsFile" not in lz_code)
check("nur LinkZiel entscheidet – im Fenster steht keine zweite Schema-Regel",
      "UriScheme" not in erg_code)

# (d) Der Rest des Fensters bleibt, wie er war.
check("Kopieren funktioniert weiter", "Clipboard.SetText(_output.Text)" in erg_code)
check("das Feld bleibt schreibgeschuetzt", "ReadOnly = true" in erg_code)
# ⚠ HIER STAND "es wird NICHT formatiert". Das war der Ist-Zustand vom
# 2026-09-10 frueh und ist seit der Vorgabe „der MD-Parser wie im
# Browser-Plugin" falsch – ein Test, der einen Zustand festschreibt statt einer
# EIGENSCHAFT, meldet die Behebung als Fehler (Register).
# Geblieben ist die Zusage, die weiter gilt: KEIN selbst gebautes RTF.
check("die Anzeige baut kein RTF selbst (Fremdtext, Maskierung von \\ { })",
      ".Rtf" not in erg_code and "SelectedRtf" not in erg_code)

# (e) Texte in DE UND EN.
def _texteintrag_cs(name):
    """Die Deklaration bis zu ihrem Ende – NICHT ein Fenster fester Groesse:
    ein laengerer Text sprengt das sonst still, und der Waechter meldet einen
    Fehler, den es nicht gibt (beim ersten Lauf genau so passiert)."""
    i = cs_texte.find("public static string %s" % name)
    if i < 0:
        return ""
    j = cs_texte.find(");", i)
    k = cs_texte.find(";", i)
    ende = (j + 2) if 0 <= j <= k + 200 else (k + 1 if k >= 0 else len(cs_texte))
    return cs_texte[i:ende]


for _n in ("LinkGeoeffnet", "LinkNichtGeoeffnet", "LinkFehler"):
    _e = _texteintrag_cs(_n)
    # ⚠ `T("` als Muster ist zu starr: bei einem mehrzeiligen Aufruf steht nach
    # `T(` ein Umbruch. Geprueft wird die EIGENSCHAFT – Aufruf von T() mit zwei
    # Zeichenketten.
    check("Text %s ist zweisprachig hinterlegt (T(de, en))" % _n,
          "T(" in _e and _e.count('"') >= 4)
_lt = _texteintrag_cs("LinkNichtGeoeffnet")
check("die Absage nennt den Ausweg (kopieren), nicht nur das Verbot",
      "kopier" in _lt.lower() and "copy" in _lt.lower())

print("\n=== 13. Vorgabe-Fragen: was ein neuer Benutzer bekommt (2026-09-10) ===")
#
# VORGABE: "der Administrator kann Default-Menue-Eintraege definieren, die beim
# ersten Start uebernommen werden. Der Benutzer kann diese Defaults weiterhin
# anpassen." Das ist NICHT dasselbe wie eine gemeinsame Frage (die gehoert dem
# Administrator und ist fuer den Benutzer unveraenderlich) – deshalb ein
# eigener Topf `vorgaben`, der beim ersten Kontakt KOPIERT wird.
#
# ⚠ SANDKASTEN: das Modul schreibt sonst in data/ai_mouse_fragen.json des
#    laufenden Servers – ein Test, der die Fragen der Benutzer anfasst, ist
#    teurer als der Fehler, den er sucht.
import tempfile as _tf  # noqa: E402
import shutil as _sh    # noqa: E402

from backend import ai_mouse_fragen as amf  # noqa: E402

_SAND = Path(_tf.mkdtemp(prefix="amf-"))
_echt = amf._pfad()
amf._pfad = lambda: _SAND / "fragen.json"
if not str(amf._pfad()).startswith(str(_SAND)) or str(amf._pfad()) == str(_echt):
    print("ABBRUCH: Sandkasten nicht wirksam – der Lauf wuerde den echten Bestand aendern.")
    sys.exit(2)


def _titel(liste):
    return [e.get("titel") for e in liste]


# (a) Die Saat ist genau das, was der Betreiber vorgegeben hat – WOERTLICH.
SOLL = [
    ("Text erkennen (OCR)", "Agiere als OCR-System. Erkenne den Text"),
    ("extrahiere Adressdaten (OCR)", None),
    ("was ist das ?", None),
    ("Tabelle zusammenfassen", None),
    # Wortlaut nachgezogen 2026-09-10 ("link" -> "hyperlink", Vorgabe des
    # Betreibers). Der woertliche Vergleich BLEIBT richtig: er haelt fest, was
    # bestellt wurde – eine Pruefung gegen das Modul selbst waere trivial wahr.
    ("suche homepage",
     "suche die homepage der Adresse und zeige sie als klickbaren hyperlink an"),
    ("übersetze nach Deutsch", "Agiere als OCR-System. Übersetze den Text nach Deutsch"),
]
vorg = amf.vorgaben_liste()
check("es sind genau die sechs vorgegebenen Eintraege", len(vorg) == 6)
check("Titel und Reihenfolge stimmen",
      _titel(vorg) == [t for t, _ in SOLL])
for i, (t_soll, p_soll) in enumerate(SOLL):
    if p_soll is None or i >= len(vorg):
        continue
    check("Prompt woertlich uebernommen: %s" % t_soll, vorg[i].get("prompt") == p_soll)
check("der lange Adress-Prompt ist vollstaendig (nicht gekuerzt)",
      len(vorg) > 1 and "strukturierten Daten zurück" in vorg[1].get("prompt", "")
      and len(vorg[1].get("prompt", "")) < amf.PROMPT_MAX)


def _erste(liste):
    """Erster Eintrag oder ein leeres dict – NIE ungeprueft dereferenzieren:
    eine Gegenprobe, die den Lauf mit IndexError beendet, hinterlaesst keine
    Bilanzzeile und ist von "nicht gelaufen" nicht zu unterscheiden."""
    return liste[0] if liste else {}

# (b) Der neue Benutzer bekommt sie als EIGENE – das ist die Zusage.
l1 = amf.liste("neu.benutzer")
check("ein neuer Benutzer bekommt alle sechs", len(l1) == 6)
check("⚠ und zwar als EIGENE (aenderbar), nicht als gemeinsame",
      all((not e["gemeinsam"]) and e["darf_aendern"] for e in l1))
check("⚠ mit EIGENEN Kennungen (nicht denen der Vorgabe)",
      not ({e["id"] for e in l1} & {v["id"] for v in vorg}))

# (c) Was der Benutzer aendert, bleibt seins.
sicher(amf.speichern, "neu.benutzer", _erste(l1).get("id", ""), "Mein eigener Titel", "Mein Text")
l2 = amf.liste("neu.benutzer")
check("eine geaenderte Vorgabe bleibt geaendert", "Mein eigener Titel" in _titel(l2))
check("und die Vorgabe-Liste selbst ist unberuehrt",
      _titel(amf.vorgaben_liste()) == [t for t, _ in SOLL])

# (d) ⚠ Geloeschtes kommt NICHT zurueck (Marker je Benutzer).
for e in amf.liste("neu.benutzer"):
    amf.loeschen("neu.benutzer", e["id"])
check("nach dem Loeschen ALLER Fragen ist die Liste leer", amf.liste("neu.benutzer") == [])
check("⚠ und sie bleibt leer – die Vorgaben kommen nicht zurueck",
      amf.liste("neu.benutzer") == [])

# (e) Eine spaetere Aenderung der Vorgaben erreicht Bestandsbenutzer NICHT.
amf.vorgabe_speichern("", "Ganz neue Vorgabe", "Text dazu")
check("die neue Vorgabe steht in der Vorlage", "Ganz neue Vorgabe" in _titel(amf.vorgaben_liste()))
check("⚠ ein Bestandsbenutzer bekommt sie NICHT nachtraeglich",
      "Ganz neue Vorgabe" not in _titel(amf.liste("neu.benutzer")))
check("ein WEITERER neuer Benutzer bekommt sie dagegen schon",
      "Ganz neue Vorgabe" in _titel(amf.liste("zweiter.benutzer")))

# (f) Der Altbestand der gemeinsamen Fragen wird EINMALIG geraeumt – und eine
#     danach angelegte gemeinsame Frage ueberlebt. Ohne den Marker waere die
#     Funktion "gemeinsame Frage" still kaputt.
d = amf._laden()
d["global_"] = [amf._neu("Alte gemeinsame", "Text")]
d.pop("_global_geraeumt", None)
amf._speichern(d)
amf.liste("dritter.benutzer")
check("der Altbestand der gemeinsamen Fragen wird geraeumt",
      not (amf._laden().get("global_") or []))
amf.speichern("admin.person", "", "Neue gemeinsame", "Text", gemeinsam=True, ist_admin=True)
check("⚠ eine DANACH angelegte gemeinsame Frage ueberlebt (Marker greift)",
      "Neue gemeinsame" in _titel(amf.liste("vierter.benutzer")))
check("und sie ist fuer einen normalen Benutzer NICHT aenderbar",
      all(e["darf_aendern"] is False
          for e in amf.liste("vierter.benutzer") if e["gemeinsam"]))

# (g) Pflege der Vorgaben.
v = amf.vorgabe_speichern("", "Zum Aendern", "Alt")
v2 = amf.vorgabe_speichern(v["id"], "Geaendert", "Neu")
check("Vorgabe aendern behaelt die Kennung", v2["id"] == v["id"])
check("und den neuen Text", v2["prompt"] == "Neu")
check("Loeschen meldet Erfolg", amf.vorgabe_loeschen(v["id"]) is True)
check("unbekannte Vorgabe: False (der Aufrufer antwortet 404)",
      amf.vorgabe_loeschen("gibtsnicht") is False)
check("leerer Titel wird abgewiesen",
      isinstance(sicher(amf.vorgabe_speichern, "", "  ", "Text"), amf.FragenFehler))
check("leerer Prompt wird abgewiesen",
      isinstance(sicher(amf.vorgabe_speichern, "", "Titel", "  "), amf.FragenFehler))
check("unbekannte Kennung beim Aendern wird abgewiesen (kein stilles Anlegen)",
      isinstance(sicher(amf.vorgabe_speichern, "abc123", "T", "P"), amf.FragenFehler))

# (h) Deckel: die Kopie darf die Grenze je Benutzer nicht sprengen.
d = amf._laden()
d["vorgaben"] = [amf._neu("V%d" % i, "P") for i in range(amf.MAX_JE_BENUTZER + 10)]
amf._speichern(d)
lv = amf.liste("deckel.benutzer")
check("beim Kopieren greift der Deckel je Benutzer",
      len(lv) <= amf.MAX_JE_BENUTZER + len(amf._laden().get("global_") or []))

_sh.rmtree(_SAND, ignore_errors=True)

# (i) Endpunkte + Oberflaeche.
import re as _re  # noqa: E402
_mq = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
for _r, _m in (("/api/ai-mouse/admin/vorgaben", "get"),
               ("/api/ai-mouse/admin/vorgaben", "post"),
               ("/api/ai-mouse/admin/vorgaben/{fid}", "delete")):
    check("Route %s (%s) vorhanden" % (_r, _m), ('app.%s("%s")' % (_m, _r)) in _mq)
# ⚠ require_local_auth und NICHT require_aimouse_access: dessen Freigabe kennt
# keinen Admin-Bypass – ein Administrator ohne eigene AI-Maus-Freigabe koennte
# die Vorgaben sonst nicht pflegen (gleiche Stelle wie beim Bereichs-Katalog).
_vb = _mq[_mq.find('@app.get("/api/ai-mouse/admin/vorgaben")'):]
_vb = _vb[:_vb.find("@app.get(\"/api/ai-mouse/admin/areas\")")]
# ⚠ OHNE KOMMENTARE UND DOCSTRINGS pruefen: die Begruendung im Rumpf nennt
# `require_aimouse_access` woertlich ("und NICHT ..."), und der Waechter las
# damit seine eigene Erklaerung – beim ersten Lauf genau so passiert
# (vierzehnter Fall dieser Klasse im Projekt).
_vb_code = "\n".join(z for z in _vb.split("\n")
                     if not z.lstrip().startswith("#"))
_vb_code = _re.sub(r'"""[\s\S]*?"""', "", _vb_code)
check("Positivkontrolle: Kommentare/Docstrings sind wirklich raus",
      len(_vb_code) < len(_vb) and "Depends(require_local_auth)" in _vb_code)
check("alle drei haengen an require_local_auth",
      _vb_code.count("Depends(require_local_auth)") == 3
      and "require_aimouse_access" not in _vb_code)
check("unbekannte Vorgabe beim Loeschen: 404 (nicht 403)",
      "status_code=404" in _vb)

_sh_html = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
_adm = (ROOT / "frontend" / "js" / "ai_mouse_admin.js").read_text(encoding="utf-8")
_app = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
_css = (ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")
_i18n = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")

check("der Container liegt im AI-Maus-Reiter", 'id="am-sect-vorg"' in _sh_html)
# ⚠ JEDE .kb-section des Reiters muss in der Klapp-Verdrahtung stehen – eine
# vergessene bleibt zugeklappt und laesst sich nicht oeffnen (der Kommentar in
# app.js warnt genau davor).
_tab = _sh_html[_sh_html.find('id="settings-tab-aimouse"'):]
_tab = _tab[:_tab.find('id="settings-tab-tracks"')]
_sekt = _re.findall(r'class="kb-section" id="([^"]+)"', _tab)
check("jede Sektion des Reiters ist klappbar verdrahtet",
      all(("'%s-hdr'" % s) in _app for s in _sekt))
check("die Liste wird beim Oeffnen des Reiters geladen",
      "vorgabenLaden" in _adm and "this.vorgabenLaden()" in _adm)
check("Loeschen fragt nach", "confirm(" in _adm and "amvorg.del_ask" in _adm)
check("der Muelleimer kommt aus JarvisIcons (Symbol-Semantik)",
      "JarvisIcons.trash()" in _adm)
# ⚠ KEIN ×-RUECKFALL an einem Loeschknopf: genau die Verwechslung, gegen die
# icons.js gebaut ist. Der Zweig war toter Code (icons.js liegt auf jeder Seite
# als erstes Skript) mit falscher Semantik – test_icon_semantik hat ihn gemeldet.
check("und ohne ×-Rueckfall (× heisst schliessen, nie loeschen)",
      "JarvisIcons.trash() : '×'" not in _adm)
# Ein Ladefehler darf die Liste nicht LEEREN – sonst haelt ein Administrator
# den Bestand fuer weg und legt alles neu an.
_lade = _adm[_adm.find("vorgabenLaden: function"):]
_lade = _lade[:_lade.find("vorgabenZeichnen: function")]
check("ein Ladefehler leert die Liste nicht",
      "setStatus('amvorg-status'" in _lade and "innerHTML" not in _lade)
check("Werte gehen per .value ins Formular (kein Interpolieren ins Markup)",
      "ti.value = v.titel" in _adm and 'value="' + "' + esc(v.titel)" not in _adm)
for _k in ("amvorg.h", "amvorg.intro", "amvorg.warn", "amvorg.new", "amvorg.empty",
           "amvorg.f_titel", "amvorg.f_prompt", "amvorg.saved", "amvorg.deleted",
           "amvorg.del_ask"):
    check("i18n %s in DE UND EN" % _k, _i18n.count("'%s'" % _k) >= 2)
def _i18n_wert(schluessel, ab=0):
    """Der WERT eines i18n-Schluessels ab Position `ab` – nicht die ganze Datei:
    ueber den Gesamttext gesucht ist fast jedes Wort trivial vorhanden, und die
    Gegenprobe biss nicht."""
    i = _i18n.find("'%s':" % schluessel, ab)
    if i < 0:
        return "", -1
    j = _i18n.find("\n", i)
    return _i18n[i:j if j > 0 else len(_i18n)], i


_w_de, _p_de = _i18n_wert("amvorg.warn")
_w_en, _ = _i18n_wert("amvorg.warn", _p_de + 10 if _p_de >= 0 else 0)
check("der Hinweis (DE) sagt, dass eine Aenderung Bestandsbenutzer NICHT erreicht",
      "noch nie" in _w_de)
check("der Hinweis (EN) ebenso", "never" in _w_en)
check("Positivkontrolle: es sind zwei VERSCHIEDENE Texte (DE und EN gefunden)",
      bool(_w_de) and bool(_w_en) and _w_de != _w_en)
check("CSS: min-width am Textteil (sonst schiebt ein langer Prompt die Knoepfe raus)",
      _re.search(r"\.am-vorg-main\s*\{[^}]*min-width:\s*0", _css) is not None)
check("CSS: die Karte fasst das Formular ein (overflow hidden)",
      _re.search(r"\.am-vorg-card\s*\{[^}]*overflow:\s*hidden", _css) is not None)

print("\n=== 14. Rechtsziehen: Taste statt Erkennung (2026-09-10) ===")
#
# FRAGE: "wenn beim Rechtsklick ein ziehbares Objekt unter der Maus liegt, dann
# Drag bevorzugen und KEIN Lasso – sinnvoll machbar?" ERKENNEN: nein. Ziehbarkeit
# ist kein Zustand, den man abfragen kann; UIA-`IsDraggable` implementiert kaum
# eine Anwendung; `LVM_HITTEST` hilft beim modernen Explorer nicht mehr. Und der
# LL-Hook muss innerhalb `LowLevelHooksTimeout` (300 ms) zurueck – ein
# UIA-Aufruf kann ihn stillschweigend aushaengen lassen.
# UMGESETZT ist deshalb eine MODIFIKATORTASTE: sie reicht den Rechtsklick
# durch, statt ihn fuer die Geste zu nehmen.
#
# ⚠ Die ENTSCHEIDUNG selbst wird nicht hier geprueft, sondern AUSGEFUEHRT in
#    `tests/live_gestentaste_dev.py` (dort steht das .NET SDK). Hier steht die
#    Verdrahtung durch die Einstellungs-Kette.
cs_hook = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Input"
           / "MouseGestureHook.cs").read_text(encoding="utf-8")
cs_gtaste = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Input"
             / "GestenTaste.cs").read_text(encoding="utf-8")
cs_nm = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Interop"
         / "NativeMethods.cs").read_text(encoding="utf-8")
cs_appset = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Configuration"
             / "AppSettings.cs").read_text(encoding="utf-8")
cs_sw = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui"
         / "SettingsWindow.cs").read_text(encoding="utf-8")

hook_code = cs_nackt(cs_hook)
check("Positivkontrolle: der Kommentar-Entferner hat gekuerzt",
      len(hook_code) < len(cs_hook) and "WM_RBUTTONDOWN" in hook_code)

# (a) Die Taste wird im DOWN geprueft – und zwar VOR dem Zurueckhalten.
down = hook_code[hook_code.find("case NativeMethods.WM_RBUTTONDOWN"):]
down = down[:down.find("case NativeMethods.WM_MOUSEMOVE")]
check("die Taste wird beim Druecken geprueft", "TasteGehalten(Durchreichen)" in down)
check("⚠ und ZWINGEND vor dem Zurueckhalten des Klicks",
      down.find("TasteGehalten(Durchreichen)") < down.find("_pressWithheld = true"))
# ⚠ Bliebe `_pressWithheld` stehen, verschluckte der spaetere BUTTONUP den
#   Klick des Benutzers – er waere dann ganz weg.
zweig = down[down.find("TasteGehalten(Durchreichen)"):]
zweig = zweig[:zweig.find("InjectionGuard")]
check("⚠ der Durchreich-Zweig setzt _pressWithheld ausdruecklich auf false",
      "_pressWithheld = false" in zweig)
check("und reicht den Klick durch (break, kein return 1)",
      "break;" in zweig and "return (IntPtr)1" not in zweig)

# (b) GetAsyncKeyState, nicht GetKeyState.
check("⚠ GetAsyncKeyState (GetKeyState liest die Warteschlange DIESES Threads)",
      "GetAsyncKeyState" in cs_nm and "GetKeyState(" not in cs_nm)
check("nur das HOHE Bit zaehlt (das niedrige heisst 'war mal gedrueckt')",
      "0x8000" in cs_nackt(cs_hook))
check("die drei Tasten sind seitenunabhaengig (VK_CONTROL/VK_MENU/VK_SHIFT)",
      all(v in cs_nm for v in ("VK_CONTROL", "VK_MENU", "VK_SHIFT")))

# (c) Vorgabe und fail-safe-Richtung.
check("AppSettings-Vorgabe ist ctrl (nicht none)",
      'RightDragKey { get; set; } = "ctrl"' in cs_appset)
tray_code = cs_nackt(cs_tray)
umsetz = tray_code[tray_code.find("private static GestenTaste GestenTasteAus"):]
umsetz = umsetz[:umsetz.find("private void ApplySettings")]
# ⚠ HIER STAND `"_ => GestenTaste.Strg" in umsetz` – also die SCHREIBWEISE.
# Seit die Umsetzung eine je Feld verschiedene Vorgabe nimmt (2026-09-10),
# heisst der Zweig `_ => vorgabe`, und die Pruefung meldete einen Fehler, den
# es nicht gibt. Gemessen wird die EIGENSCHAFT; AUSGEFUEHRT belegt es
# `tests/live_tastenaus_dev.py` (dort ergibt "quatsch" nachweislich Strg).
check("ein UNBEKANNTER gespeicherter Wert ergibt Strg, nicht Keine",
      "GestenTaste vorgabe = GestenTaste.Strg" in umsetz and "_ => vorgabe," in umsetz)
check('"none" bleibt waehlbar (Verhalten wie vorher)', '"none" => GestenTaste.Keine' in umsetz)

# (d) Die Kette: gespeichert, gelesen, beim Start UND beim Speichern gesetzt.
cs_store = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Configuration"
            / "ConfigStore.cs").read_text(encoding="utf-8")
check("wird in die Registry geschrieben", 'k.SetValue("RightDragKey"' in cs_store)
check("und wieder gelesen", 'Lies(k, "RightDragKey")' in cs_store)
check("ein LEERER gespeicherter Wert laesst die Vorgabe stehen",
      "if (rdk.Length > 0)" in cs_store)
# ⚠ AUCH HIER STAND DIE SCHREIBWEISE. Seit es zwei entgegengesetzte
# Tastenfelder gibt, laeuft beides ueber `TastenAus` – die Eigenschaft ist
# „der Hook bekommt seine Tasten an beiden Stellen aus der Aufloesung",
# nicht „dort steht dieser eine Ausdruck".
check("beim Start wird der Hook damit gesetzt",
      "TastenAus(_settings)" in tray_code)
check("⚠ und beim Speichern der Einstellungen ebenfalls (sonst erst nach Neustart)",
      "(_hook.GesteVerlangt, _hook.Durchreichen) = TastenAus(settings);" in tray_code)

# (e) Oberflaeche: Pulldown, Werte-Reihenfolge, Texte.
sw_code = cs_nackt(cs_sw)
check("der Dialog hat ein Auswahlfeld", "_rightDrag" in sw_code and "AddRow" in sw_code)
check("es wird gespeichert", "RightDragKey = _RD_WERTE[" in sw_code)
# ⚠ Drift: Reihenfolge der Anzeige muss zur Werteliste passen, sonst speichert
#   das Feld etwas anderes, als dasteht.
check("Werteliste in der Reihenfolge des Pulldowns",
      '["none", "ctrl", "alt", "shift"]' in sw_code)
i_items = sw_code.find("_rightDrag.Items.AddRange")
zeile = sw_code[i_items:sw_code.find("\n", i_items)]
check("die Anzeige beginnt mit 'aus' und nennt dann Strg, Alt, Umschalt",
      "RdKeine" in zeile and zeile.find("Strg") < zeile.find("Alt") < zeile.find("RdUmschalt"))
check("unbekannter Wert zeigt Strg an (wie im Tray)", "rd >= 0 ? rd : 1" in sw_code)
for _n in ("RechtsziehTaste", "RdKeine", "RdUmschalt"):
    _e = _texteintrag_cs(_n)
    check("Text %s ist zweisprachig" % _n, "T(" in _e and _e.count('"') >= 4)

# (f) Die Begruendung steht am Code – sonst untersucht das jemand erneut.
check("die Datei erklaert, warum eine Erkennung NICHT geht (UIA/Timeout)",
      "IsDraggable" in cs_hook and "LowLevelHooksTimeout" in cs_hook)
check("und warum gerade Strg die Vorgabe ist", "Umschalt" in cs_gtaste
      and "erweiterte" in cs_gtaste.lower())

# ══════════════════════════════════════════════════════════════════════════
# 15. Markdown im Ergebnisfenster + KEIN harter UI-Text mehr (2026-09-10)
#
# Gemeldet: „ich moechte doch den MD parser (wie im browser plugin) im
# Ergebnisfenster" und „die Menues sind immer noch nicht i18n: 'copy image to
# clipboard' und 'Save Image as'".
#
# ⚠ „IMMER NOCH" IST DER GRUND FUER DIE REGEL WEITER UNTEN. Zwei Eintraege
# nachzutragen loest den Fall nicht: gemessen standen SIEBZEHN Literale hart
# im Code, und `Texte.Kopieren`/`Texte.Schliessen` gab es sogar schon – sie
# waren nur nie verdrahtet. Eine gepflegte Liste im Waechter waere beim
# naechsten Knopf wieder unvollstaendig.
# ══════════════════════════════════════════════════════════════════════════
print("\n--- 15. Markdown-Parser + i18n ---")

cs_md   = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "Markdown.cs").read_text(encoding="utf-8")
cs_tray = (ROOT / "ai-mouse" / "src" / "AiMouse" / "TrayApplicationContext.cs").read_text(encoding="utf-8")
md_code   = cs_nackt(cs_md)
tray_code = cs_nackt(cs_tray)
check("Positivkontrolle: der Kommentar-Entferner hat auch hier gekuerzt",
      len(md_code) < len(cs_md) and "ZuZeilen" in md_code)

# (a) Die zwei gemeldeten Eintraege.
check("'Bild in die Zwischenablage' kommt aus der Texttabelle",
      "ToolStripMenuItem(Texte.BildKopieren)" in tray_code)
check("'Bild speichern unter' kommt aus der Texttabelle",
      "ToolStripMenuItem(Texte.BildSpeichern)" in tray_code)
check("der Dateifilter des Speichern-Dialogs ebenfalls",
      "Filter = Texte.PngFilter" in tray_code)

# (b) DIE REGEL: kein UI-Literal ohne Texte./T().
#
# Gesucht wird an den Stellen, die einen Text ANZEIGEN. Ausnahmen stehen
# EINZELN und begruendet – eine Sammelfreigabe waere das Ende der Regel.
UI_STELLE = re.compile(
    r"(ToolStripMenuItem\(|MessageBox\.Show\(|ShowBalloonTip\(|\bText\s*=|\bTitle\s*="
    r"|\.Filter\s*=|ToolTipText\s*=)")
LITERAL = re.compile(r'"([^"\\]{2,}?)"')
AUSNAHMEN = {
    # Schriftname – kein Anzeigetext, sondern eine Systemressource.
    "Segoe UI",
    # Prompts gehen an das MODELL, nicht an den Benutzer.
    "Act as an OCR system. Extract all visible text from this image precisely without added commentary.",
    "Describe the contents and key visual elements of this image in detail.",
    "Analyze the error message or code shown in this snippet and propose a solution.",
}
harte = []
for _f in sorted((ROOT / "ai-mouse" / "src" / "AiMouse").rglob("*.cs")):
    if "obj" in _f.parts:
        continue
    for _i, _z in enumerate(cs_nackt(_f.read_text(encoding="utf-8")).split("\n"), 1):
        if not UI_STELLE.search(_z):
            continue
        for _lit in LITERAL.findall(_z):
            if _lit in AUSNAHMEN or not re.search(r"[A-Za-zÄÖÜäöü]", _lit):
                continue
            # Ein Format-Literal ist erlaubt, SOLANGE sein Inhalt aus der
            # Tabelle kommt: $"{Texte.Marke} — {Texte.TrayHinweis}".
            if "Texte." in _z:
                continue
            harte.append("%s:%d %r" % (_f.name, _i, _lit[:48]))
check("REGEL: kein Oberflaechentext steht hart im Code (%s)"
      % ("keiner" if not harte else " | ".join(harte[:6])), not harte)
check("Positivkontrolle: die Regel sieht die UI-Stellen ueberhaupt",
      UI_STELLE.search('var x = new ToolStripMenuItem("Test");') is not None)

# (c) Die Marke wird nicht abgeschrieben.
_marke_hart = [z for z in tray_code.split("\n") if '"AI Mouse"' in z]
check("kein festes \"AI Mouse\" mehr im Tray-Code", not _marke_hart)
check("das Ergebnisfenster nennt die Marke aus der Tabelle",
      "Texte.Marke" in erg_code and '"AI Mouse' not in erg_code)
check("die Marke kommt aus den Einstellungen, nicht aus einer Konstante",
      "settings.Marke" in cs_texte and "_marke" in cs_texte)
check("und faellt auf den einkompilierten Wert zurueck, nie auf leer",
      "Vorgaben.Marke" in cs_texte)

# (d) Der Parser – und die DRIFT-SCHRANKE zum Browser-Plugin.
#
# ⚠ DAS IST DER KERN DIESER PRUEFUNG: „wie im Browser-Plugin" ist eine
# Zusage ueber die REGEL, nicht ueber das Ergebnis. Laufen die beiden
# Ausdruecke auseinander, deutet dieselbe Antwort in Jira und in der AI-Maus
# verschieden – und niemand koennte erklaeren warum.
_pop = (ROOT / "browser-addon" / "popup.js").read_text(encoding="utf-8")
_m = re.search(r"const _FETT_RE = /(.+?)/;", _pop)
check("die Fett-Regel des Plugins ist auffindbar", _m is not None)
if _m:
    _js = _m.group(1)
    _cs = re.search(r'new\(@"(.+?)",', md_code)
    check("die Regel ist zeichengleich zum Plugin (%s)" % _js,
          _cs is not None and _cs.group(1) == _js)
check("der Parser liegt UI-frei (auf dem Bauserver ausfuehrbar)",
      "Form" not in md_code and "RichTextBox" not in md_code
      and "using System.Windows.Forms" not in cs_md)
check("das Fenster benutzt ihn", "Markdown.ZuZeilen" in erg_code)
# ⚠ NICHT auf das VORKOMMEN von `SelectionFont` pruefen – das bleibt wahr,
# wenn jemand dort pauschal `normal` zuweist (Gegenprobe war damit zahnlos).
# Gemessen wird die EIGENSCHAFT: die Schrift haengt am LAUF.
_sf = [z for z in erg_code.split("\n") if "SelectionFont =" in z and "Fett" in z]
check("die Schriftwahl haengt am Lauf, nicht pauschal am Normalfont", bool(_sf))
check("und die Fettschrift ist aus dem Normalfont abgeleitet",
      "new Font(normal, FontStyle.Bold)" in erg_code)
check("Fehlermeldungen werden NICHT gedeutet (kein Markdown vom Server)",
      "markdown: false" in erg_code)
check("die Antwort schon", "markdown: true" in erg_code)

# ⚠ `.Handle` ERZWINGT die Handle-Erzeugung – beim ersten Fuellen gibt es
# noch keines, und ein erzwungener Aufbau waere eine Nebenwirkung ohne
# Gegenwert.
check("das Flackerschutz-Handle wird nicht erzwungen",
      "IsHandleCreated" in erg_code)
check("die Zeichenzahl zaehlt den ANGEZEIGTEN Text (ohne die Sternchen)",
      "Texte.Zeichen(_output.TextLength)" in erg_code)

# (e) Die eingebauten Fragen folgen einem Sprachwechsel.
check("Defaults ist ein Ausdruckskoerper, kein einmaliger Initialisierer",
      re.search(r"Defaults\s*=>", cs_prompt_item := (ROOT / "ai-mouse" / "src" / "AiMouse"
                / "Configuration" / "PromptItem.cs").read_text(encoding="utf-8")) is not None)
check("und ihre Titel kommen aus der Tabelle", "Texte.FrageOcr" in cs_prompt_item)
check("der Prompt bleibt englisch (er geht an das Modell)",
      "Act as an OCR system" in cs_prompt_item)

# (f) Alle neuen Texte zweisprachig.
for _n in ("BildKopieren", "BildSpeichern", "PngFilter", "WarteAufModell",
           "AnfrageFehlgeschlagen", "InZwischenablage", "AufnahmeFehler",
           "ZwischenablageBelegt", "SpeichernFehler", "OeffnenFehler",
           "UnerwarteterFehler", "FrageOcr", "FrageBeschreiben", "FrageFehler"):
    _e = _texteintrag_cs(_n)
    check("Text %s ist zweisprachig" % _n, "T(" in _e and _e.count('"') >= 4)

# ══════════════════════════════════════════════════════════════════════════
# 16. Halten ohne Bewegung -> Rechtsziehen statt Lasso (2026-09-10)
#
# Vorgabe: „wenn ich die rechte Maustaste gedrueckt halte ohne sie zu bewegen
# (an das entsprechende Windows timeout anpassen) soll geprueft werden, ob ein
# dragable Object unterhalb vom Mauszeiger liegt … wenn ja, dann kein Lasso
# ziehen sondern object drag starten".
#
# ⚠ WAS SICH GEGENUEBER DEM 2026-09-10 FRUEH GEAENDERT HAT: der Einwand gegen
# eine Erkennung war der 300-ms-Deckel des Hook-Callbacks. Der gilt fuer einen
# TIMER nicht – deshalb ist die Erkennung jetzt moeglich. Die anderen zwei
# Einwaende bestehen weiter und stehen als Begruendung am Code: Ziehbarkeit ist
# kein abfragbarer Zustand, und UIA `IsDragPatternAvailable` implementiert
# kaum jemand. Es ist also eine HEURISTIK, und sie faellt im Zweifel auf NEIN.
# ══════════════════════════════════════════════════════════════════════════
print("\n--- 16. Halten -> Rechtsziehen ---")

_in = ROOT / "ai-mouse" / "src" / "AiMouse" / "Input"
cs_regel = (_in / "ZiehbarRegel.cs").read_text(encoding="utf-8")
cs_pruef = (_in / "ZiehbarPruefer.cs").read_text(encoding="utf-8")
cs_sysw = (_in / "SystemWerte.cs").read_text(encoding="utf-8")
cs_hook2 = (_in / "MouseGestureHook.cs").read_text(encoding="utf-8")
cs_reply = (_in / "InputReplay.cs").read_text(encoding="utf-8")
regel_code, pruef_code = cs_nackt(cs_regel), cs_nackt(cs_pruef)
sysw_code, hook2_code = cs_nackt(cs_sysw), cs_nackt(cs_hook2)
check("Positivkontrolle: der Kommentar-Entferner hat gekuerzt",
      len(pruef_code) < len(cs_pruef) and "ElementFromPoint" in pruef_code)

# (a) ⚠ DER TEUERSTE PUNKT DER GANZEN AUFGABE: GUIDs und vtable-Positionen.
#     Ein `[ComImport]`-Interface mit falscher Reihenfolge UEBERSETZT
#     FEHLERFREI und ruft zur Laufzeit die falsche Funktion – der Absturz
#     kaeme erst am Arbeitsplatz. Die Werte sind aus `UIAutomationClient.idl`
#     (Windows SDK) verifiziert.
for name, guid in (("IUIAutomation", "30cbe57d-d9d0-452a-ab13-7ac5ac4825ee"),
                   ("IUIAutomationElement", "d22108aa-8ac5-49a5-837b-37bbb3d7591e"),
                   ("CUIAutomation", "ff48dba4-60ef-4201-aa87-54103eef594e")):
    check("GUID von %s ist die aus der SDK-IDL" % name, guid in pruef_code)

def _vtable(quelle, interface):
    """Methodennamen in DEKLARATIONSreihenfolge – das IST die vtable."""
    # ⚠ PRAEFIX-FALLE: `find("interface IUIAutomation")` trifft
    #   `IUIAutomationElement` zuerst, wenn das im Quelltext oben steht – der
    #   Waechter meldete damit einen Fehler, den es nicht gab. Dieselbe Klasse
    #   wie `share_1` in `share_10` (Register). Also auf Wortgrenze suchen.
    m = re.search(r"\binterface\s+" + re.escape(interface) + r"\b(?!\w)", quelle)
    if m is None:
        return []
    i = m.start()
    j = quelle.find("{", i)
    tiefe, k = 1, j + 1
    while k < len(quelle) and tiefe:
        if quelle[k] == "{":
            tiefe += 1
        elif quelle[k] == "}":
            tiefe -= 1
        k += 1
    return re.findall(r"\b(\w+)\s*\([^)]*\)\s*;", quelle[j:k])

_vt_a = _vtable(pruef_code, "IUIAutomation")
check("ElementFromPoint steht an vtable-Position 5 (SDK-IDL)",
      len(_vt_a) >= 5 and _vt_a[4] == "ElementFromPoint")
_vt_e = _vtable(pruef_code, "IUIAutomationElement")
check("GetCurrentPropertyValue steht an Position 8 (SDK-IDL)",
      len(_vt_e) >= 8 and _vt_e[7] == "GetCurrentPropertyValue")
# ⚠ Je weiter hinten die Methode liegt, desto mehr Platzhalter muessen exakt
#   stimmen. Deshalb bewusst 8 statt 19 (get_CurrentControlType).
check("und `get_CurrentControlType` wird bewusst NICHT benutzt (Position 19)",
      "CurrentControlType" not in pruef_code)
check("die Herkunft der Werte steht am Code",
      "UIAutomationClient.idl" in cs_pruef)

# (b) Die Regel ist von COM getrennt – sonst waere sie nicht messbar.
check("die Entscheidung liegt COM-frei in ZiehbarRegel",
      "ComImport" not in regel_code and "Marshal" not in regel_code)
check("und der Pruefer benutzt sie, statt selbst zu entscheiden",
      "ZiehbarRegel.IstZiehbar" in pruef_code)

# (c) Fail-safe: im Zweifel KEIN Drag.
# ⚠ NICHT auf das VORKOMMEN von `ergebnis = false` pruefen: das steht auch
# als Initialisierung da und bleibt bei jeder Sabotage stehen (Gegenprobe war
# damit zahnlos). Gemessen wird die EIGENSCHAFT: der catch-Zweig setzt false.
_i_catch = pruef_code.find("catch")
_i_ende = pruef_code.find("})", _i_catch)
_catchblock = pruef_code[_i_catch:_i_ende] if 0 < _i_catch < _i_ende else ""
check("der catch-Zweig der Abfrage setzt 'nicht ziehbar'",
      "ergebnis = false;" in _catchblock and "ergebnis = true" not in _catchblock)
check("Positivkontrolle: der catch-Block wurde ueberhaupt gefunden",
      len(_catchblock) > 20)
check("die Abfrage laeuft in einem eigenen Thread mit Zeitgrenze",
      "SetApartmentState" in pruef_code and "Join(grenze)" in pruef_code)
check("und der Thread ist ein Hintergrund-Thread (haengt er, stirbt er mit)",
      "IsBackground = true" in pruef_code)
# ⚠ Ohne STA kein COM.
check("STA, weil COM es verlangt", "ApartmentState.STA" in pruef_code)

# (d) Die Systemwerte – ausdrueckliche Vorgabe „an das Windows timeout anpassen".
check("die Verweilzeit kommt von Windows (SPI_GETMOUSEHOVERTIME)",
      "SPI_GETMOUSEHOVERTIME" in sysw_code)
check("die Zieh-Toleranz ebenfalls (SM_CXDRAG/SM_CYDRAG)",
      "SM_CXDRAG" in sysw_code and "SM_CYDRAG" in sysw_code)
# ⚠ Eine Verweilzeit von 0 hiesse „sofort durchreichen" – dann gaebe es das
#   Lasso praktisch nicht mehr, und niemand koennte sich erklaeren warum.
check("eine unbrauchbare Verweilzeit wird begrenzt, nicht uebernommen",
      "Clamp" in sysw_code and "VerweilVorgabe" in sysw_code)
check("und eine Toleranz von 0 ebenso", "x > 0 ? x : 4" in sysw_code)

# (e) Die Verdrahtung im Hook.
check("der Halte-Timer laeuft auf dem UI-Thread (WinForms-Timer)",
      "System.Windows.Forms.Timer" in hook2_code)
check("er startet beim Druecken", "_halten.Start();" in hook2_code)
check("Bewegung ueber die Toleranz beendet ihn",
      "SystemWerte.UeberToleranz" in hook2_code and "_halten.Stop();" in hook2_code)
# ⚠ Zwischen Timer-Start und Ablauf kann der Benutzer losgelassen haben oder
#   zu ziehen begonnen haben – ohne diese Pruefung wuerde mitten in ein
#   laufendes Lasso hinein ein Klick injiziert.
check("der Zustand wird beim Ablauf ERNEUT geprueft",
      "!_pressWithheld || _isDragging || _durchgereicht" in hook2_code)
# ⚠ Erst den Zustand umstellen, DANN injizieren: der injizierte Druck laeuft
#   durch denselben Hook und muss dort schon als "gehoert der Anwendung"
#   ankommen.
_i1 = hook2_code.find("_durchgereicht = true;")
_i2 = hook2_code.find("InputReplay.SendRightDown()")
check("erst Zustand umstellen, dann injizieren", 0 < _i1 < _i2)
check("es wird NUR gedrueckt, nicht auch losgelassen",
      "SendRightDown" in cs_reply and "SendRightDown" in hook2_code)
check("  … und SendRightDown schickt wirklich nur ein DOWN",
      cs_nackt(cs_reply).split("SendRightDown")[1].split("}")[0].count("RIGHTUP") == 0)
# ⚠ Scheitert die Injektion, ist der Klick des Benutzers VERLOREN.
check("eine gescheiterte Injektion wird gemeldet und zurueckgedreht",
      "_durchgereicht = false;" in hook2_code and "ReplayFailed?.Invoke(fehler)" in hook2_code)
check("ein laufender Auswahlrahmen wird abgeraeumt",
      "Durchgereicht" in cs_nackt(cs_tray) and "_overlay.EndSelection()" in cs_nackt(cs_tray))
check("der Pruefer ist als Delegat gesetzt (Hook bleibt ohne UIA testbar)",
      "LiegtObjektUnter" in hook2_code and "Func<Point, bool>" in hook2_code)
check("und im Tray mit einer Zeitgrenze verdrahtet",
      "ZiehbarPruefer.LiegtObjektUnter" in cs_nackt(cs_tray)
      and "FromMilliseconds" in cs_nackt(cs_tray))
check("der Timer wird beim Aufraeumen gestoppt",
      "_halten.Stop();" in hook2_code and "_halten.Dispose();" in hook2_code)

# (f) Die Begruendung steht am Code – sonst untersucht das jemand erneut.
check("die Datei erklaert, warum es eine HEURISTIK ist",
      "Heuristik" in cs_regel or "HEURISTIK" in cs_regel)
check("und warum im Zweifel NICHT gezogen wird",
      "fail-safe" in cs_regel.lower() or "FAIL-SAFE" in cs_regel)

# ══════════════════════════════════════════════════════════════════════════
# 17. Rechte Taste nur mit Sondertaste (Vorgabe 2026-09-10)
#
# „baue einen Schalter unter exe Einstellungen ein, der dem User ermoeglicht
# zu entscheiden, ob er die rechte Taste nur in Verbindung einer Sondertaste
# verwenden will (ALT oder STRG oder ...)".
#
# ⚠ DAS IST DIE UMKEHRUNG DER BESTEHENDEN EINSTELLUNG, und darin liegt die
# ganze Schwierigkeit: `RightDragKey` heisst „die Geste nimmt jeden Klick,
# ausser mit dieser Taste", `GestureKey` heisst „der Klick gehoert der
# Anwendung, ausser mit dieser Taste". Beide gleichzeitig ergeben keinen Sinn –
# dieselbe Taste koennte zweierlei bedeuten.
# ══════════════════════════════════════════════════════════════════════════
print("\n--- 17. Geste nur mit Sondertaste ---")

cs_app = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Configuration"
          / "AppSettings.cs").read_text(encoding="utf-8")
cs_cfg = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Configuration"
          / "ConfigStore.cs").read_text(encoding="utf-8")
app_code, cfg_code = cs_nackt(cs_app), cs_nackt(cs_cfg)
tray_code2, sw2 = cs_nackt(cs_tray), cs_nackt(cs_sw)
hook3 = cs_nackt((ROOT / "ai-mouse" / "src" / "AiMouse" / "Input"
                  / "MouseGestureHook.cs").read_text(encoding="utf-8"))

# (a) Die Einstellung selbst.
check("die Einstellung existiert", "GestureKey" in app_code)
# ⚠ VORGABE LEER = wie bisher. Alles andere waere eine abschaltende Aenderung:
#   nach dem Update haette niemand mehr ein Lasso, ohne etwas getan zu haben.
check("Vorgabe ist LEER (Verhalten wie bisher)",
      'GestureKey { get; set; } = string.Empty;' in app_code)
check("sie wird gelesen und geschrieben",
      'Lies(k, "GestureKey")' in cfg_code and 'SetValue("GestureKey"' in cfg_code)

# (b) Der Hook.
check("der Hook kennt die Gestentaste", "GesteVerlangt" in hook3)
check("ohne gehaltene Taste gehoert der Klick der Anwendung",
      "GesteVerlangt != GestenTaste.Keine && !TasteGehalten(GesteVerlangt)" in hook3)
# ⚠ Der teure Fehler: bliebe `_pressWithheld` stehen, verschluckte der spaetere
#   BUTTONUP den Klick des Benutzers.
_i_g = hook3.find("GesteVerlangt != GestenTaste.Keine")
_i_w = hook3.find("_pressWithheld = false;", _i_g)
_i_b = hook3.find("break;", _i_g)
check("  … und nichts bleibt zurueckgehalten", 0 < _i_w < _i_b)
# ⚠ Die Reihenfolge ist Semantik: mit Gestentaste ist Durchreichen bedeutungslos.
check("die Gestentaste wird VOR der Durchreich-Taste geprueft",
      0 < _i_g < hook3.find("TasteGehalten(Durchreichen)"))

# (c) DIE AUFLOESUNG – die eine Stelle.
check("es gibt eine gemeinsame Aufloesung", "TastenAus" in tray_code2)
check("und sie wird beim Setzen benutzt",
      "(_hook.GesteVerlangt, _hook.Durchreichen) = TastenAus(settings);" in tray_code2)
# ⚠ AUCH DER KONSTRUKTOR – sonst gaelte die Aufloesung erst nach dem ersten
#   Speichern, und bis dahin koennten beide gleichzeitig aktiv sein.
check("auch der Konstruktor geht darueber, nicht daran vorbei",
      "TastenAus(_settings)" in tray_code2)
check("kein direktes GestenTasteAus(RightDragKey) mehr am Hook",
      "Durchreichen = GestenTasteAus(" not in tray_code2)
# ⚠ Die Vorgaben sind ENTGEGENGESETZT und beide fallen auf das BISHERIGE
#   Verhalten zurueck – ein Tippfehler darf weder das Lasso abschalten noch
#   Windows' Right-Drag.
check("die Gestentaste faellt bei Unbekanntem auf 'Keine'",
      "GestenTasteAus(s.GestureKey, GestenTaste.Keine)" in tray_code2)
check("die Durchreich-Taste weiterhin auf 'Strg'",
      "_ => vorgabe," in tray_code2 and "GestenTaste vorgabe = GestenTaste.Strg" in tray_code2)

# (d) Der Dialog.
check("der Dialog hat ein Auswahlfeld dafuer", "_gesteTaste" in sw2)
check("es steht VOR der Durchreich-Taste (die haengt davon ab)",
      0 < sw2.find("Texte.GesteTaste, _gesteTaste")
      < sw2.find("Texte.RechtsziehTaste, _rightDrag"))
check("es wird gespeichert", "GestureKey = _RD_WERTE[" in sw2)
check("und belegt", "s.GestureKey" in sw2)
# ⚠ GESPERRT MIT BEGRUENDUNG STATT VERBORGEN (Projektregel): ein Feld, das je
#   nach Einstellung verschwindet, ist von einem fehlenden nicht zu
#   unterscheiden.
check("die Durchreich-Taste wird gesperrt, wenn eine Gestentaste gilt",
      "_rightDrag.Enabled = !mitGeste;" in sw2)
check("  … und der Grund steht daneben",
      "_rdHinweis.Text = mitGeste ? Texte.RdGesperrt" in sw2)
check("  … sie wird NICHT versteckt",
      "_rightDrag.Visible = false" not in sw2)
# ⚠ Sofort, nicht erst beim Speichern – sonst steht die Sperre erst da, wenn
#   der Dialog schon zu ist.
check("die Sperre folgt der Auswahl sofort",
      "SelectedIndexChanged += (_, _) => TastenfelderAbgleichen();" in sw2)
check("und gilt schon beim Oeffnen",
      sw2.count("TastenfelderAbgleichen()") >= 3)
# ⚠ Unbekanntes zeigt hier 0 („keine"), beim anderen Feld 1 („Strg").
check("das Feld zeigt bei Unbekanntem 'keine' an", "gk >= 0 ? gk : 0" in sw2)

# (e) Texte zweisprachig.
for _n in ("GesteTaste", "GkKeine", "RdGesperrt"):
    _e = _texteintrag_cs(_n)
    check("Text %s ist zweisprachig" % _n, "T(" in _e and _e.count('"') >= 4)

# ══════════════════════════════════════════════════════════════════════════
# 18. Nach einem Update wird die EXE NEU GEBAUT (gemeldet 2026-09-10)
#
# „trotz update ist auf ECHT noch eine alte exe" – zutreffend und GEMESSEN:
# Code `c875336` von 12:59, EXE von 06:04.
#
# ⚠ URSACHE: der Neubau haing ausschliesslich an den HAUSWERTEN
# (`Vorgaben.cs`). Beide Wege fragten nur, ob IRGENDEINE Anwendung da ist –
# `paket_vorhanden()` im Backend, `liegt_bereit()` im Bootstrap. Ein `git pull`
# mit neuem Quelltext loeste damit NICHTS aus. Auf DEV fiel es nie auf, weil
# dort nach jeder Aenderung von Hand gebaut wurde.
#
# Dieselbe Fehlerklasse wie beim Root-Broker: „ein Fix, der still nicht
# ankommt". Und dieselbe Loesung: die ZEIT vergleichen, nicht eine Version.
# ══════════════════════════════════════════════════════════════════════════
print("\n--- 18. Neubau nach Update ---")

cs_am = (ROOT / "backend" / "ai_mouse.py").read_text(encoding="utf-8")
sh_bau = (ROOT / "deploy" / "ai_mouse_build.sh").read_text(encoding="utf-8")
py_main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")

check("es gibt eine Aktualitaets-Pruefung", "def bau_noetig(" in cs_am)
check("sie vergleicht die ZEIT, nicht eine Version",
      "st_mtime" in cs_am and "quellen_stand" in cs_am)
# ⚠ `obj/` und `bin/` MUESSEN ausgenommen sein: dort liegen die Ergebnisse des
#   letzten Baus, die per Definition juenger sind als die EXE – ohne die
#   Ausnahme waere JEDER Dienststart ein Neubau.
check("obj/ und bin/ sind ausgenommen (sonst Dauerbau)",
      '"obj" in datei.parts' in cs_am and '"bin" in datei.parts' in cs_am)
check("und im Bauskript ebenso",
      "-name obj -o -name bin" in sh_bau and "-prune" in sh_bau)
# ⚠ FAIL-SAFE IST „NICHT NOETIG" – ein Bau bei jedem Start waere teurer als
#   eine Anwendung, die einen Tag alt ist.
check("unlesbarer Quellstand baut NICHT (fail-safe)",
      "if quellen <= 0:\n        return False" in cs_am)
check("eine FEHLENDE Anwendung wird trotzdem immer gebaut",
      "if not paket_vorhanden():\n        return True" in cs_am)

# Beide Wege benutzen sie – einer allein waere die halbe Reparatur.
check("der Dienststart prueft die Aktualitaet",
      "if not ai_mouse.bau_noetig():" in py_main)
check("  … und nicht mehr nur die Existenz",
      "if ai_mouse.paket_vorhanden():\n                return" not in py_main)
check("der Download-Weg ebenfalls",
      "if not bau_noetig() and not erzwingen:" in cs_am)
check("und der Bootstrap ueber --pruefen",
      "aktuell()" in sh_bau and "    aktuell\n}" in sh_bau)

# ⚠ „veraltet" und „fehlt" sind ZWEI Befunde – wer bei vorhandener Datei
#   „NICHT vorhanden" liest, sucht am falschen Ende.
check("die Meldung unterscheidet veraltet von fehlend",
      "veraltet (Quelltext ist neuer)" in sh_bau)

# ⚠ UND JETZT AUSGEFUEHRT. Die Pruefungen oben lesen nur den Quelltext – ein
# `return False` ganz oben in `bau_noetig` macht alles tot, und sie blieben
# gruen (Gegenprobe war damit zahnlos). Gemessen wird die EIGENSCHAFT.
import tempfile as _tf  # noqa: PLC0415

with _tf.TemporaryDirectory(prefix="baunoetig-") as _t:
    _t = Path(_t)
    (_t / "ai-mouse" / "src" / "AiMouse" / "obj").mkdir(parents=True)
    (_t / "vendor" / "ai-mouse").mkdir(parents=True)
    _q = _t / "ai-mouse" / "src" / "AiMouse" / "Program.cs"
    _e = _t / "vendor" / "ai-mouse" / "AiMouse.exe"
    _q.write_text("// quelle", encoding="utf-8")
    _e.write_bytes(b"MZ" + b"\0" * 100)

    _alt_w, _alt_e = am._projekt_wurzel, am.exe_pfad
    _alt_p, _alt_b = am.paket_vorhanden, am.bau_noetig
    am._projekt_wurzel = lambda: _t
    am.exe_pfad = lambda: _e
    am.paket_vorhanden = lambda: _e.is_file()
    # ⚠ DIE ECHTE Funktion, nicht den Stub aus Abschnitt 5.
    am.bau_noetig = _ECHT_BAU_NOETIG
    try:
        import os as _o
        # (1) EXE juenger als die Quelle -> kein Bau
        _o.utime(_q, (1000, 1000))
        _o.utime(_e, (2000, 2000))
        check("AUSGEFUEHRT: aktuelle EXE -> kein Bau noetig", am.bau_noetig() is False)

        # (2) Quelle juenger -> Bau. ⚠ DER GEMELDETE FALL.
        _o.utime(_q, (3000, 3000))
        check("AUSGEFUEHRT: Quelltext neuer -> Bau noetig", am.bau_noetig() is True)

        # (3) obj/ ist ausgenommen – sonst waere JEDER Start ein Neubau.
        _o.utime(_q, (1000, 1000))
        _ob = _t / "ai-mouse" / "src" / "AiMouse" / "obj" / "x.cs"
        _ob.write_text("// artefakt", encoding="utf-8")
        _o.utime(_ob, (9000, 9000))
        check("AUSGEFUEHRT: obj/ loest KEINEN Bau aus", am.bau_noetig() is False)

        # (4) keine EXE -> immer bauen
        _e.unlink()
        check("AUSGEFUEHRT: fehlende EXE -> Bau noetig", am.bau_noetig() is True)
    finally:
        am._projekt_wurzel, am.exe_pfad = _alt_w, _alt_e
        am.paket_vorhanden, am.bau_noetig = _alt_p, _alt_b

# ══════════════════════════════════════════════════════════════════════════
# 19. Bildschirm-Zoom > 100 %% (gemeldet 2026-09-10)
#
# „Felder werden unvollstaendig und abgeschnitten angezeigt".
#
# ⚠ DIE URSACHE IST EINE KETTE AUS DREI TEILEN – jeder fuer sich sieht richtig
# aus, erst zusammen ergeben sie den Fehler:
#   1. `app.manifest` deklariert PerMonitorV2 → Windows streckt das Fenster
#      NICHT mehr (kein Bitmap-Stretching als Notnagel).
#   2. `AutoScaleMode.Font` braucht `AutoScaleDimensions` als Referenz – die
#      setzt sonst der Designer. Diese Fenster sind von Hand gebaut, der Wert
#      blieb (0,0), der Faktor damit 1.0: es wurde NICHT skaliert.
#   3. Die Schrift skaliert trotzdem – `new Font("Segoe UI", 9f)` ist in PUNKT
#      angegeben, und Punkt→Pixel haengt an der DPI.
# ⇒ groessere Schrift in unveraenderten Kaesten.
# ══════════════════════════════════════════════════════════════════════════
print("\n--- 19. Zoom ueber 100 Prozent ---")

_ui = ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui"
_manifest = (ROOT / "ai-mouse" / "src" / "AiMouse" / "app.manifest").read_text(encoding="utf-8")

# (a) Die Voraussetzung, aus der die Pflicht folgt.
check("das Manifest deklariert PerMonitorV2 (die App skaliert selbst)",
      "PerMonitorV2" in _manifest)

# (b) DIE REGEL: jedes Dialogfenster skaliert nach DPI – mit Referenzwert.
#
# ⚠ ALS REGEL UEBER ALLE FENSTER, nicht als Liste: ein kuenftiges Fenster
#   faellt damit von selbst auf. Die Ausnahme steht EINZELN und begruendet.
_AUSNAHMEN = {
    # ⚠ SelectionOverlay arbeitet mit den PHYSISCHEN Pixelkoordinaten des
    #   Maus-Hooks. Wuerde es skaliert, laege der Auswahlrahmen neben dem
    #   Zeiger – und der aufgenommene Ausschnitt waere ein anderer als der
    #   markierte. `AutoScaleMode.None` ist dort Absicht.
    "SelectionOverlay.cs",
}
_fenster = []
for _f in sorted(_ui.glob("*.cs")):
    _q = cs_nackt(_f.read_text(encoding="utf-8"))
    if ": Form" not in _q:
        continue
    _fenster.append(_f.name)
    if _f.name in _AUSNAHMEN:
        check("%s ist ausgenommen und sagt es (AutoScaleMode.None)" % _f.name,
              "AutoScaleMode.None" in _q)
        continue
    check("%s skaliert nach DPI" % _f.name, "AutoScaleMode.Dpi" in _q)
    # ⚠ OHNE REFERENZWERT IST DER FAKTOR UNDEFINIERT – genau daran lag es.
    check("  … und hat den Referenzwert 96 dpi",
          "AutoScaleDimensions = new SizeF(96F, 96F)" in _q)
check("Positivkontrolle: es wurden ueberhaupt Fenster gefunden (%d)" % len(_fenster),
      len(_fenster) >= 3)
# ⚠ `Font` ist hier die falsche Betriebsart: bei fest gesetzter Punktgroesse
#   ergibt der Schriftvergleich immer 1.0.
check("kein Fenster benutzt mehr AutoScaleMode.Font",
      not any("AutoScaleMode.Font" in cs_nackt((_ui / n).read_text(encoding="utf-8"))
              for n in _fenster))

# (c) Textfelder mit Fliesstext duerfen keine feste Hoehe haben – sonst
#     schneiden sie die zweite Zeile ab, sobald die Schrift waechst.
_sw = cs_nackt((_ui / "SettingsWindow.cs").read_text(encoding="utf-8"))
check("der Status-Kasten waechst mit (AutoSize + Mindesthoehe)",
      "AutoSize = true," in _sw and "MinimumSize = new Size(0, 52)" in _sw)
check("  … und hat keine feste Hoehe mehr", "Height = 52," not in _sw)
check("der Sperr-Hinweis ebenfalls", "Height = 30," not in _sw)
_mk = cs_nackt((_ui / "Marken.cs").read_text(encoding="utf-8"))
check("der Markenkopf waechst mit", "AutoSize = true" in _mk and "Height = 38," not in _mk)


# ── Abschnitt 20: der Verweiltimer und der Bild-Knopf (2026-09-10) ──────────
# Gemeldet: „ziehen funktioniert trotz Rechtsklick und kurz warten nicht mehr in
# 100 % der Versuche" – und dazu der Wunsch nach einem Kopier-Knopf fuer den
# untersuchten Ausschnitt.
print("\n── Verweiltimer und Bild-Knopf ──")

_hook_roh = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Input"
             / "MouseGestureHook.cs").read_text(encoding="utf-8")
_hook = cs_nackt(_hook_roh)
check("Positivkontrolle: der Hook wurde gelesen und gekuerzt",
      len(_hook) < len(_hook_roh) and "WM_RBUTTONDOWN" in _hook)

# (a) ⚠ DER KERN DES FEHLERS: eine kleine Bewegung darf den Verweiltimer
#     ZURUECKSETZEN, nicht abbrechen. Abgebrochen gehoert er erst, wenn das
#     Lasso wirklich beginnt – dazwischen liegt das Fenster 4..8 px, in dem
#     vorher GAR NICHTS mehr passierte.
_bew = _hook[_hook.index("case NativeMethods.WM_MOUSEMOVE"):
             _hook.index("case NativeMethods.WM_RBUTTONUP")]
check("eine Bewegung startet den Verweiltimer NEU",
      "_halten.Stop();" in _bew and "_halten.Start();" in _bew)
check("  … gemessen gegen die letzte RUHEPOSITION, nicht den Druckpunkt",
      "UeberToleranz(_haltenAnker, point)" in _bew
      and "UeberToleranz(_start, point)" not in _bew)
check("  … und der Anker wird dabei nachgezogen", "_haltenAnker = point;" in _bew)
# Die Gegenrichtung: sobald ein Rahmen entsteht, ist Objektziehen vom Tisch.
_ab_lasso = _bew[_bew.index("_isDragging = true;"):]
check("erst das beginnende Lasso beendet das Halten",
      "_halten.Stop();" in _ab_lasso)

# (b) Der Anker muss beim Druecken gesetzt werden – ein Feld, das nur im
#     Bewegungszweig geschrieben wird, traegt beim ersten Ablauf (0,0).
_down = _hook[_hook.index("case NativeMethods.WM_RBUTTONDOWN"):
              _hook.index("case NativeMethods.WM_MOUSEMOVE")]
check("der Anker wird beim Druecken gesetzt", "_haltenAnker = point;" in _down)

# (c) Geprueft wird, wo der Klick ANKOMMT: `SendRightDown` injiziert an der
#     aktuellen Zeigerposition, und das ist die Ruheposition.
_halten_fn = _hook[_hook.index("private void HaltenAbgelaufen"):]
check("die Ziehbar-Pruefung fragt die Ruheposition ab",
      "pruefer(_haltenAnker)" in _halten_fn and "pruefer(_start)" not in _halten_fn)

# (d) Der Bild-Knopf im Antwortfenster.
_rw_roh = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui"
           / "ResultWindow.cs").read_text(encoding="utf-8")
_rw = cs_nackt(_rw_roh)
check("das Fenster hat einen Knopf fuer den Ausschnitt",
      "_bildButton" in _rw and "Texte.BildKopierenKnopf" in _rw)
check("er ist zunaechst gesperrt und wird mit dem Bild freigegeben",
      "public void BildUebernehmen(Bitmap bild)" in _rw
      and "_bildButton.Enabled = true;" in _rw)
# ⚠ LEBENSDAUER: das Fenster besitzt das Bitmap und gibt es frei.
check("das Fenster gibt den Ausschnitt beim Schliessen frei",
      "_bild?.Dispose();" in _rw[_rw.index("OnFormClosed"):])
check("  … und auch, wenn es beim Uebergeben schon zu ist (kein Leck)",
      "if (IsDisposed)" in _rw[_rw.index("BildUebernehmen"):
                               _rw.index("public void ShowAnswer")])
# ⚠ ERFOLG UND FEHLSCHLAG SIND BEIDE EINE AUSKUNFT.
_bk = _rw[_rw.index("private void BildKopieren"):]
check("Erfolg wird gemeldet", "Texte.BildInZwischenablage" in _bk)
check("  … und ein Fehlschlag ebenfalls", "Color.Firebrick" in _bk)

# (e) Der Aufrufer darf das Bitmap NICHT mehr sofort freigeben.
_tray = cs_nackt((ROOT / "ai-mouse" / "src" / "AiMouse"
                  / "TrayApplicationContext.cs").read_text(encoding="utf-8"))
check("der Aufrufer uebergibt den Ausschnitt ans Fenster",
      "window.BildUebernehmen(capture);" in _tray)
check("  … und gibt ihn nicht mehr selbst frei (kein `using (capture)`)",
      "using (capture)" not in _tray)

# (f) EINE Stelle fuer die Zwischenablage – zwei liefen auseinander.
_zw = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui"
       / "Zwischenablage.cs").read_text(encoding="utf-8")
check("es gibt eine gemeinsame Kopier-Stelle", "public static string? BildSetzen" in _zw)
_alle_cs = [p for p in (ROOT / "ai-mouse" / "src").rglob("*.cs") if "obj" not in p.parts]
_setimage = [p.name for p in _alle_cs
             if "Clipboard.SetImage" in cs_nackt(p.read_text(encoding="utf-8"))]
check("und NUR dort steht ein SetImage (%s)" % ", ".join(_setimage) if _setimage
      else "und NUR dort steht ein SetImage",
      _setimage == ["Zwischenablage.cs"])

# (g) Zwei Kopier-Knoepfe muessen sagen, was sie kopieren.
_txt = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Localization"
        / "Texte.cs").read_text(encoding="utf-8")
check("der Textknopf heisst nicht mehr blosss 'Kopieren'",
      'T("Text kopieren", "Copy text")' in _txt)
check("  … und die Rueckmeldung nennt den Gegenstand",
      'T("Text in die Zwischenablage kopiert.' in _txt
      and 'T("Bild in die Zwischenablage kopiert.' in _txt)
check("beide neuen Texte gibt es in DE und EN",
      '"Copy image"' in _txt and '"Image copied to clipboard."' in _txt)


# ─────────────────────────────────────────────────────────────────────────────
print("\n[21] Version 1.0.0 und stille Aktualisierung (2026-09-11)")
# ─────────────────────────────────────────────────────────────────────────────
_proj = (ROOT / "ai-mouse" / "src" / "AiMouse" / "AiMouse.csproj").read_text(
    encoding="utf-8")

check("die csproj traegt eine <Version>",
      bool(re.search(r"<Version>\s*[0-9]+(\.[0-9]+)*\s*</Version>", _proj)))
check("klient_version() liest sie und liefert 1.0.0 oder mehr",
      re.fullmatch(r"[0-9]+(\.[0-9]+){1,3}", am.klient_version() or "") is not None)

# ⚠ EINE QUELLE: eine Backend-Konstante waere eine Kopie, und eine Kopie, die
# driftet, erzeugt hier eine UPDATE-SCHLEIFE (Server behauptet eine Version,
# die die EXE nicht hat -> jeder Arbeitsplatz laedt sie immer wieder).
_am_code = "\n".join(
    z for z in (ROOT / "backend" / "ai_mouse.py").read_text(
        encoding="utf-8").split("\n") if not z.lstrip().startswith("#"))
check("Kommentar-Filter greift (Positivkontrolle)",
      "def klient_version" in _am_code and "UPDATE-SCHLEIFE" not in _am_code)
check("die Version steht NICHT zusaetzlich als Backend-Konstante",
      not re.search(r"^[A-Z_]*VERSION[A-Z_]*\s*=\s*[\"'][0-9]", _am_code,
                    re.MULTILINE))
check("klient_version liest die csproj (keine zweite Fassung)",
      "AiMouse.csproj" in _am_code and "<Version>" in _am_code)

# ⚠ Eine Versionserhoehung MUSS einen Neubau ausloesen – sonst liefert der
# Server eine Nummer, die die EXE nicht traegt. Die csproj muss deshalb im
# Quellen-Scan liegen.
check("`.csproj` zaehlt in quellen_stand() (Neubau bei Versionswechsel)",
      '".csproj"' in _am_code and "quellen_stand" in _am_code)

_main_code = "\n".join(
    z for z in (ROOT / "backend" / "main.py").read_text(
        encoding="utf-8").split("\n") if not z.lstrip().startswith("#"))
check("health liefert klient_version",
      '"klient_version": ai_mouse.klient_version()' in _main_code)

# ── Der Client ───────────────────────────────────────────────────────────────
_upd = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Update"
        / "Aktualisierung.cs").read_text(encoding="utf-8")
_upd_code = "\n".join(z for z in _upd.split("\n")
                      if not z.lstrip().startswith("//")
                      and not z.lstrip().startswith("///"))
check("Kommentar-Filter greift (Positivkontrolle, Update-Modul)",
      "BeimStartEinwechseln" in _upd_code
      and "Man-in-the-Middle" not in _upd_code)

# ⚠ DER EIGENE PFAD DARF NICHT UEBER Assembly.Location KOMMEN: bei
# PublishSingleFile ist das ein LEERER String, und dann findet der Einwechsel
# seine eigene Datei nicht.
check("der eigene Pfad kommt aus Environment.ProcessPath",
      "Environment.ProcessPath" in _upd_code
      and "Assembly.Location" not in _upd_code)

# ⚠ Versionen als ZAHLEN und auf vier Teile normiert – sonst ist "1.0.0"
# kleiner als "1.0.0.0" und jeder Start loest ein Update aus, das nichts
# aendert (Endlosschleife), bzw. "0.10.0" gilt als aelter als "0.9.0".
check("Versionsvergleich ueber Version.TryParse, nicht als Text",
      "Version.TryParse" in _upd_code)
check("  … und auf vier Teile normiert",
      "Normiert" in _upd_code and "Math.Max" in _upd_code)

# ⚠ DEN ZWEIG ISOLIEREN, nicht das Vorkommen zaehlen: `return false` steht in
# diesem Modul mehrfach, die Gegenprobe ("unbekannte Version loest ein Update
# aus") blieb deshalb gruen. Gemessen wird, was NACH der Bedingung kommt.
_izweig = _upd_code[_upd_code.find("IsNullOrWhiteSpace(ziel)"):]
_izweig = _izweig[:_izweig.find("TryParse")] if "TryParse" in _izweig else _izweig
check("eine unbekannte Serverversion tut NICHTS (fail-safe)",
      "IsNullOrWhiteSpace(ziel)" in _upd_code
      and "return false;" in _izweig and "return true;" not in _izweig)

# ⚠ DIE REIHENFOLGE IST DIE SICHERUNG: alte Datei erst umbenennen, dann die
# neue an ihre Stelle – und bei Fehlschlag ZURUECKNEHMEN. Ohne die Ruecknahme
# bliebe gar keine EXE stehen; die Anwendung waere auf diesem Arbeitsplatz weg.
_ein = _upd_code[_upd_code.find("BeimStartEinwechseln"):]
_ein = _ein[:_ein.find("PruefenUndHolenAsync")] if "PruefenUndHolenAsync" in _ein else _ein
check("Einwechsel: alte Fassung wird umbenannt, nicht geloescht",
      "File.Move(exe, alt" in _ein)
check("Einwechsel: Fehlschlag wird ZURUECKGENOMMEN",
      "File.Move(alt, exe" in _ein)
check("Einwechsel: eine zu kleine Datei wird verworfen, nicht eingewechselt",
      "1_000_000" in _ein)

# ⚠ NICHTS WIRD SOFORT ERSETZT: das Ersetzen verlangt, dass sich die laufende
# EXE beendet – und genau das ist nicht still (offenes Ergebnisfenster weg).
# Geholt wird nur DANEBEN; eingewechselt beim naechsten Start.
_hol = _upd_code[_upd_code.find("PruefenUndHolenAsync"):]
check("das Holen startet nichts neu und beendet nichts",
      "Process.Start" not in _hol and "Application.Exit" not in _hol
      and "Environment.Exit" not in _hol)
check("bereits geholte Fassung wird nicht erneut geladen",
      'File.Exists(neu)' in _hol)
check("Schreibrecht wird VOR dem Download geprueft",
      _hol.find("schreibprobe") < _hol.find("paketHolen("))
# ⚠ DIE ZUWEISUNG pruefen, nicht das Vorkommen von ".teil": der Name steht
# auch im `catch`-Block (Aufraeumen), und die Gegenprobe `string teil = neu;`
# blieb deshalb gruen – dabei waere genau das der Fehler, den ein abgebrochener
# Download hinterlaesst: eine halbe `.neu`, die der naechste Start einwechselt.
check("zuerst in eine Nebendatei, dann umbenennen",
      'string teil = exe + ".teil";' in _hol
      and "File.Move(teil, neu" in _hol)

_prog = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Program.cs").read_text(
    encoding="utf-8")
_prog_code = "\n".join(z for z in _prog.split("\n")
                       if not z.lstrip().startswith("//"))
# ⚠ VOR ALLEM ANDEREN: ab dem ersten Fenster waere etwas zu verlieren.
check("der Einwechsel steht vor Application.EnableVisualStyles",
      0 < _prog_code.find("BeimStartEinwechseln")
      < _prog_code.find("EnableVisualStyles"))
# ⚠ UND ER DARF KEIN TOTER ZWEIG SEIN: die Gegenprobe `if (false && …)` liess
# die POSITION unveraendert und blieb damit gruen – eine Pruefung auf die
# Stelle beantwortet nicht, ob der Code je laeuft (Register: die Eigenschaft
# messen, nicht das Vorkommen).
check("  … und seine Bedingung ist kein toter Zweig",
      "if (isOnlyInstance && Aktualisierung.NeueFassungLiegtBereit())"
      in _prog_code)
# ⚠ UND HINTER DER EINZELINSTANZ-SPERRE: zwei gleichzeitig gestartete
# Instanzen wuerden sonst dieselbe Datei umbenennen.
check("  … und hinter der Einzelinstanz-Sperre",
      _prog_code.find("new Mutex(") < _prog_code.find("BeimStartEinwechseln"))
# ⚠ Die Sperre MUSS vor dem Neustart freigegeben werden, sonst laeuft die neue
# Instanz in die "laeuft bereits"-Meldung – genau dann, wenn aktualisiert wurde.
check("die Einzelinstanz-Sperre wird vor dem Neustart freigegeben",
      0 < _prog_code.find("ReleaseMutex")
      < _prog_code.find("BeimStartEinwechseln()"))

_tray_u = "\n".join(z for z in cs_tray.split("\n")
                    if not z.lstrip().startswith("//")
                    and not z.lstrip().startswith("///"))
check("die Pruefung haengt an der Stelle, an der eine Sitzung existiert",
      "AktualisierungPruefenAsync" in _tray_u
      and "_ = AktualisierungPruefenAsync();" in _tray_u)
# ⚠ NICHT ABGEWARTET: 66 MB Download darf das Fragenmenue nicht aufhalten.
check("die Pruefung wird NICHT abgewartet",
      "await AktualisierungPruefenAsync()" not in _tray_u)
# ⚠ STILL heisst: kein Dialog, keine Blase, keine Fehlermeldung.
_ap = _tray_u[_tray_u.find("private async Task AktualisierungPruefenAsync"):]
_ap = _ap[:_ap.find("private void ShowTrayError")] if "private void ShowTrayError" in _ap else _ap
check("die Pruefung meldet dem Benutzer NICHTS",
      "MessageBox" not in _ap and "ShowBalloonTip" not in _ap
      and "ShowTrayError" not in _ap)

_cl_u = "\n".join(z for z in cs_client.split("\n")
                  if not z.lstrip().startswith("//")
                  and not z.lstrip().startswith("///"))
check("der Client kennt ServerVersionAsync und PaketAsync",
      "ServerVersionAsync" in _cl_u and "PaketAsync" in _cl_u)
# ⚠ HIER KOMMT CODE UEBER DIE LEITUNG. Der Schutz ist die TLS-Pruefung des
# Standard-HttpClient – eine Ausnahme dafuer waere ein Weg zur
# Codeausfuehrung per Man-in-the-Middle.
check("nirgends eine Zertifikats-Ausnahme im Client",
      "ServerCertificateCustomValidationCallback" not in _cl_u
      and "DangerousAcceptAnyServerCertificate" not in _cl_u)
# ⚠ Der gemeinsame HttpClient traegt das Zeitlimit der AUSWERTUNG (bis 1 h);
# ein haengender 66-MB-Download darf nicht stundenlang eine Verbindung halten.
_pa = _cl_u[_cl_u.find("public async Task<byte[]> PaketAsync"):]
_pa = _pa[:_pa.find("public async Task<List<PromptItem>>")] if "public async Task<List<PromptItem>>" in _pa else _pa
check("PaketAsync hat ein eigenes, kurzes Zeitlimit",
      "CancellationTokenSource(TimeSpan" in _pa)
check("ServerVersionAsync wirft nicht (leer = unbekannt)",
      "return string.Empty;" in _cl_u[_cl_u.find("ServerVersionAsync"):
                                      _cl_u.find("PaketAsync")])


# ─────────────────────────────────────────────────────────────────────────────
print("\n[22] Beschriftung der beiden Tastenfelder (Vorgabe 2026-09-11)")
# ─────────────────────────────────────────────────────────────────────────────
_tx = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Localization"
       / "Texte.cs").read_text(encoding="utf-8")
check("das Rechtszieh-Feld heisst 'Ziehen nur mit Taste'",
      'T("Ziehen nur mit Taste",' in _tx)
check("  … und auf Englisch 'Drag only with key'",
      '"Drag only with key"' in _tx)
check("der alte Wortlaut kommt nicht zurueck",
      "Ziehen & Ablegen mit Taste" not in _tx
      and "Drag & drop with key" not in _tx)

# ⚠ DIE PARALLELITAET IST DIE ZUSAGE: die zwei Felder stehen im Dialog
# untereinander und sind Gegenstuecke (eines sperrt das Lasso, das andere
# Windows' Rechtsziehen). Verschieden gebaute Beschriftungen lesen sich wie
# zwei unabhaengige Features – genau das war der Grund fuer die Umbenennung.
# Geprueft wird die EIGENSCHAFT, nicht der Wortlaut: beide nennen dieselbe
# Bedingung in derselben Form.
import re as _re22
_paare = dict(_re22.findall(
    r'public static string (RechtsziehTaste|GesteTaste) => T\("([^"]+)"', _tx))
check("beide Tastenfelder gefunden (%s)" % ", ".join(sorted(_paare)),
      len(_paare) == 2)
check("beide sind gleich gebaut ('… nur mit Taste'): %s"
      % " | ".join(sorted(_paare.values())),
      bool(_paare) and all(v.endswith("nur mit Taste") for v in _paare.values()))
# Und sie muessen sich UNTERSCHEIDEN – sonst ist im Dialog nicht erkennbar,
# welches Feld welches ist.
check("und sie sind trotzdem unterscheidbar",
      len(set(_paare.values())) == 2)


# ─────────────────────────────────────────────────────────────────────────────
print("\n[23] Reihenfolge ziehen (Vorgabe 2026-09-11)")


# ⚠ ZWEI HELFER, WEIL DREI GEGENPROBEN OHNE BILANZ ABGEBROCHEN SIND:
#   * `_nach23` statt `split(...)[1]` – fehlt die Marke, wirft der Index, der
#     Lauf endet ohne Bilanzzeile und ist von "nicht gelaufen" nicht zu
#     unterscheiden (Register, hier drei Faelle auf einmal).
#   * `_ruf23` fuer Aufrufe in den ECHTEN Code: eine sabotierte Sortierregel
#     kann `None` in die Liste legen, und dann wirft erst `liste()`. Ein Wurf
#     ist ein FAIL, kein Abbruch.
def _nach23(text, marke, laenge=400):
    i = text.find(marke)
    return "" if i < 0 else text[i + len(marke):i + len(marke) + laenge]


def _ruf23(fn, *a, **kw):
    try:
        return fn(*a, **kw), None
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)
# ─────────────────────────────────────────────────────────────────────────────
# Die echte Funktion laeuft im Sandkasten von Abschnitt [13] – gemessen wird
# das ERGEBNIS, nicht das Vorkommen von `sortieren`.
_U23 = "sortier.pruef"
for _t in ("Alpha", "Beta", "Gamma", "Delta"):
    amf.speichern(_U23, "", _t, "Prompt " + _t)
_v = amf.liste(_U23)
_eigen = [e for e in _v if not e.get("gemeinsam")]
_ids = [e["id"] for e in _eigen]
check("vier eigene Fragen angelegt (Positivkontrolle)", len(_ids) >= 4)

# Umdrehen
_r, _f = _ruf23(amf.sortieren, _U23, list(reversed(_ids)))
_l, _f2 = _ruf23(amf.liste, _U23)
check("die Reihenfolge folgt den uebergebenen Kennungen (%s)" % (_f or _f2 or "ok"),
      _l is not None
      and [e["id"] for e in _l if not e.get("gemeinsam")] == list(reversed(_ids)))

# ⚠ TOLERANZ: eine unbekannte Kennung darf nichts kaputt machen, und ein NICHT
# genannter Eintrag muss erhalten bleiben – sonst verschwindet eine Frage aus
# dem Menue, nur weil die Oberflaeche sie nicht kannte.
_lv, _ = _ruf23(amf.liste, _U23)
_nach2_vorher = [e["id"] for e in (_lv or []) if not e.get("gemeinsam")]
_r, _f = _ruf23(amf.sortieren, _U23, [_ids[0], "gibtsnicht", _ids[2]])
_l, _f2 = _ruf23(amf.liste, _U23)
_nach2 = [e["id"] for e in (_l or []) if not e.get("gemeinsam")]
check("unbekannte Kennung wird verworfen, nicht geraten (%s)"
      % (_f or _f2 or "ok"),
      _f is None and _f2 is None
      and set(_nach2) == set(_ids) and len(_nach2) == len(_ids))
check("die genannten stehen vorn, in der gewuenschten Folge",
      _nach2[0] == _ids[0] and _nach2[1] == _ids[2])
# ⚠ DIE REIHENFOLGE, nicht nur die MENGE: eine Gegenprobe, die die nicht
# genannten UMDREHT, blieb bei einem Mengenvergleich gruen.
_uebrig23 = [i for i in _nach2_vorher if i not in (_ids[0], _ids[2])]
check("nicht genannte Eintraege bleiben erhalten (hinten, in alter Folge): %r"
      % (_nach2[2:] == _uebrig23,), _nach2[2:] == _uebrig23)

# Eine doppelte Kennung darf den Eintrag nicht verdoppeln.
_r, _f = _ruf23(amf.sortieren, _U23, [_ids[1], _ids[1]] + _ids)
_l, _f2 = _ruf23(amf.liste, _U23)
_nach3 = [e["id"] for e in (_l or []) if not e.get("gemeinsam")]
check("doppelte Kennung verdoppelt den Eintrag nicht (%s)"
      % (_f or _f2 or "ok"),
      _f is None and _f2 is None
      and len(_nach3) == len(set(_nach3)) == len(_ids))

# Leere Liste: nichts tun (und nicht alles leeren).
_vor4 = [e["id"] for e in amf.liste(_U23) if not e.get("gemeinsam")]
check("leere Liste aendert nichts", _ruf23(amf.sortieren, _U23, [])[0] == 0
      and [e["id"] for e in amf.liste(_U23) if not e.get("gemeinsam")] == _vor4)

# ⚠ FREMDE FRAGEN BLEIBEN UNBERUEHRT: die Kennungen kommen aus dem Request.
_U23B = "sortier.fremd"
amf.speichern(_U23B, "", "Fremd1", "P1")
amf.speichern(_U23B, "", "Fremd2", "P2")
_fremd_vor = [e["id"] for e in amf.liste(_U23B)]
_r, _f = _ruf23(amf.sortieren, _U23, list(reversed(_fremd_vor)))
check("fremde Fragen lassen sich nicht umsortieren",
      [e["id"] for e in amf.liste(_U23B)] == _fremd_vor)

# ⚠ GEMEINSAME NUR ALS ADMINISTRATOR – geprueft in der Funktion, nicht nur in
# der Oberflaeche.
_g1 = amf.speichern(_U23, "", "Gem A", "PA", gemeinsam=True, ist_admin=True)
_g2 = amf.speichern(_U23, "", "Gem B", "PB", gemeinsam=True, ist_admin=True)
_gem_vor = [e["id"] for e in amf.liste(_U23) if e.get("gemeinsam")]
check("zwei gemeinsame Fragen angelegt (Positivkontrolle)", len(_gem_vor) == 2)
_r, _f = _ruf23(amf.sortieren, _U23, list(reversed(_gem_vor)), ist_admin=False)
check("ein Nicht-Admin kann gemeinsame NICHT umsortieren",
      [e["id"] for e in amf.liste(_U23) if e.get("gemeinsam")] == _gem_vor)
_r, _f = _ruf23(amf.sortieren, _U23, list(reversed(_gem_vor)), ist_admin=True)
check("ein Admin kann es",
      [e["id"] for e in amf.liste(_U23) if e.get("gemeinsam")]
      == list(reversed(_gem_vor)))

# Die Gruppen bleiben getrennt: gemeinsame stehen weiter VORN.
_alle = amf.liste(_U23)
_erste_eigen = next((i for i, e in enumerate(_alle) if not e.get("gemeinsam")), 0)
check("gemeinsame stehen weiter vor den eigenen",
      all(e.get("gemeinsam") for e in _alle[:_erste_eigen])
      and not any(e.get("gemeinsam") for e in _alle[_erste_eigen:]))

# ── Endpunkt ────────────────────────────────────────────────────────────────
_mq23 = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_mq23_ok = "\n".join(z for z in _mq23.split("\n")
                      if not z.lstrip().startswith("#"))
import ast as _ast23
_b23 = _ast23.parse(_mq23)
_r23 = ""
for _n23 in _ast23.walk(_b23):
    if (isinstance(_n23, (_ast23.FunctionDef, _ast23.AsyncFunctionDef))
            and _n23.name == "ai_mouse_fragen_sortieren"):
        _r23 = _ast23.get_source_segment(_mq23, _n23) or ""
_r23_ok = "\n".join(z for z in _r23.split("\n")
                     if not z.lstrip().startswith("#"))
check("der Endpunkt existiert", len(_r23) > 100)
check("er haengt an der Bereichs-Freigabe",
      "Depends(require_aimouse_access)" in _r23_ok)
# ⚠ DER BENUTZER KOMMT AUS DER ANMELDUNG, nie aus dem Rumpf.
# ⚠ AUF `.get("user")` PRUEFEN, nicht auf `body.get("user")`: die Gegenprobe
# schrieb `(body or {}).get("user")` und blieb damit gruen.
check("kein Benutzername aus dem Rumpf",
      not any(x in _r23_ok for x in ('.get("user")', ".get('user')",
                                     '.get("benutzer")')))
check("die Kennungsliste wird auf Typ geprueft",
      "isinstance(ids, list)" in _r23_ok)
check("es gibt einen Deckel auf die Anzahl",
      "MAX_JE_BENUTZER" in _r23_ok and "MAX_GEMEINSAM" in _r23_ok)
# ⚠ AN DER `sortieren`-ZEILE pruefen: `_is_admin_user(user)` steht auch in der
# `liste()`-Zeile darunter – die Gegenprobe "Admin-Recht nicht durchgereicht"
# blieb deshalb gruen.
# ⚠ UEBER DEN AST, NICHT UEBER EIN TEXTFENSTER. 200 Zeichen ab `amf.sortieren`
# reichen bis in die `liste()`-Zeile darunter, die `_is_admin_user(user)`
# ebenfalls enthaelt – die Gegenprobe "Admin-Recht nicht durchgereicht" blieb
# deshalb gruen. Geprueft werden jetzt die ARGUMENTE des Aufrufs.
def _argtexte23(rumpf_quelle, funcname):
    """Argumenttexte JEDES Aufrufs von `funcname` im Rumpf."""
    raus = []
    try:
        baum = _ast23.parse(rumpf_quelle.strip())
    except SyntaxError:
        return raus
    for k in _ast23.walk(baum):
        if not isinstance(k, _ast23.Call):
            continue
        for arg in list(k.args) + [kw.value for kw in k.keywords]:
            t = _ast23.unparse(arg) if hasattr(_ast23, "unparse") else ""
            if t == funcname or t.endswith("." + funcname.split(".")[-1]):
                raus.append([_ast23.unparse(x) for x in k.args])
        f = _ast23.unparse(k.func) if hasattr(_ast23, "unparse") else ""
        if f == funcname:
            raus.append([_ast23.unparse(x) for x in k.args])
    return raus


# `amf.sortieren` wird ueber `to_thread` gerufen – die Argumente stehen also am
# to_thread-Aufruf.
_sortargs23 = _argtexte23(_r23, "amf.sortieren")
check("der sortieren-Aufruf wurde gefunden (Positivkontrolle)", bool(_sortargs23))
check("Admin-Rechte werden an sortieren durchgereicht",
      any("_is_admin_user" in " ".join(a) for a in _sortargs23))
# Blockierende Datei-Arbeit gehoert nicht in den Event-Loop.
check("sortieren laeuft in einem Thread", "to_thread" in _r23_ok)
# ⚠ `JSONResponse({` kommt in dieser Funktion MEHRFACH vor (die 400er-
# Antworten) – `find` traf die erste und die Pruefung meldete einen Fehler, den
# es nicht gab. Gemessen wird die EIGENSCHAFT: es gibt eine Rueckgabe, die
# `"fragen"` aus `amf.liste(` fuellt.
# ⚠ EBENFALLS UEBER DEN AST: die Textvariante war nicht verlaesslich (eine
# Gegenprobe blieb gruen, und die Ursache liess sich am Text nicht sauber
# ermitteln). Geprueft wird die EIGENSCHAFT: irgendeine Rueckgabe traegt einen
# Schluessel "fragen", dessen Wert aus `amf.liste(...)` kommt.
def _liefert_fragen23(quelle):
    try:
        baum = _ast23.parse(quelle.strip())
    except SyntaxError:
        return False
    for k in _ast23.walk(baum):
        if not isinstance(k, _ast23.Dict):
            continue
        for sch, wert in zip(k.keys, k.values):
            if (isinstance(sch, _ast23.Constant) and sch.value == "fragen"
                    and hasattr(_ast23, "unparse")
                    and "liste(" in _ast23.unparse(wert)):
                return True
    return False


check("die neue Liste kommt zurueck (Client zeichnet daraus)",
      _liefert_fragen23(_r23))

# ── Oberflaeche ─────────────────────────────────────────────────────────────
_amjs = (ROOT / "frontend" / "js" / "ai_mouse.js").read_text(encoding="utf-8")
# ⚠ AUCH BLOCK-KOMMENTARE ENTFERNEN. Ein Zeilenfilter auf `//` genuegt nicht:
# die Begruendungen dieses Moduls stehen teils in `/* ... */`, und darin kommen
# `dragover`, `preventDefault` und `data-gem` woertlich vor – vier Pruefungen
# lasen so MEINEN EIGENEN KOMMENTAR und schlugen fehl, obwohl der Code stimmt
# (die Falle in neuer Variante, jetzt der 16. Fall im Projekt).
import re as _re23
_amjs_ok = _re23.sub(r"/\*.*?\*/", "", _amjs, flags=_re23.S)
_amjs_ok = "\n".join(z for z in _amjs_ok.split("\n")
                      if not z.lstrip().startswith("//"))
check("Kommentar-Filter greift (Positivkontrolle)",
      "ziehenBinden" in _amjs_ok and "Register" not in _amjs_ok
      and "Firefox" not in _amjs_ok)
# ⚠ DER GRIFF HAENGT AN `darf_aendern` – ein Griff ohne Wirkung waere die
# "ein Klick tut nichts"-Falle.
# ⚠ AM GRIFF-BLOCK pruefen: `f.darf_aendern` steht auch bei `var acts` – die
# Gegenprobe "Griff auch ohne darf_aendern" blieb ueber die ganze Datei gruen.
check("der Ziehgriff haengt an darf_aendern",
      "f.darf_aendern" in _nach23(_amjs_ok, "var griff =", 60)
      and 'draggable="true"' in _nach23(_amjs_ok, "var griff =", 300))
check("die Karte traegt ihre Gruppe als Merkmal", "data-gem=" in _amjs_ok)
# ⚠ NUR INNERHALB DER GRUPPE: der Server sortiert je Topf.
check("dragover lehnt ein fremdes Ziel ab",
      "data-gem" in _nach23(_amjs_ok, "'dragover'", 400))
check("drop prueft die Gruppe ebenfalls",
      "data-gem" in _nach23(_amjs_ok, "'drop'", 500))
# ⚠ preventDefault im dragover ist das, was das Ablegen ueberhaupt erlaubt.
check("dragover ruft preventDefault",
      "preventDefault" in _nach23(_amjs_ok, "'dragover'", 500))
# ⚠ Ohne Nutzlast bricht Firefox das Ziehen ab.
check("dragstart setzt eine Nutzlast", "setData(" in _amjs_ok)
# ⚠ TASTATUR: ohne sie gaebe es ohne Maus GAR KEINEN Weg.
check("der Griff ist per Tastatur bedienbar (Strg+Pfeil)",
      "ctrlKey" in _amjs_ok and "ArrowUp" in _amjs_ok and "ArrowDown" in _amjs_ok)
check("  … und der Fokus wandert mit",
      ".focus()" in _nach23(_amjs_ok, "ctrlKey", 1200))
# ⚠ AUS DER SERVER-ANTWORT ZEICHNEN, nicht aus dem DOM.
check("nach dem Senden wird aus der Antwort gezeichnet",
      "d.fragen" in _amjs_ok and "_fragen = d.fragen" in _amjs_ok)
# ⚠ DIE FUNKTION SCHNEIDEN, nicht "das letzte catch" raten: in dieser Datei
# gibt es mehrere, und der Schnitt traf eine fremde Stelle.
_send23 = _amjs_ok.split("function reihenfolgeSenden")
_send23 = _send23[1].split("function karteSchieben")[0] if len(_send23) > 1 else ""
check("der Sende-Weg wurde gefunden (Positivkontrolle)", len(_send23) > 200)
# ⚠ IM CATCH-ZWEIG pruefen: `zugMelden('')` steht auch am Anfang derselben
# Funktion – die Gegenprobe "Fehlschlag wird verschwiegen" blieb gruen.
_catch23 = _nach23(_send23, "catch", 500)
check("ein Fehlschlag wird GEMELDET und neu gezeichnet",
      "zugMelden" in _catch23 and "fragenZeichnen()" in _catch23)
check("die Ziehmeldung hat einen Platz AUSSERHALB des Formulars",
      "am-q-zug" in _amjs_ok)

_amhtml = (ROOT / "frontend" / "ai_mouse.html").read_text(encoding="utf-8")
check("der Meldeplatz steht im Markup und startet versteckt",
      'id="am-q-zug"' in _amhtml
      and "hidden" in _amhtml.split('id="am-q-zug"')[1][:200])
# ⚠ `data-i18n-html`: der Hinweistext traegt ein <span>.
check("der Hinweistext benutzt data-i18n-html (er traegt Markup)",
      'data-i18n-html="aimouse.q_order"' in _amhtml)
_i18n23 = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
for _k23 in ("aimouse.q_order", "aimouse.q_move", "aimouse.q_move_err"):
    check("i18n: %s in DE und EN" % _k23,
          _i18n23.count("'%s'" % _k23) >= 2)
_css23 = (ROOT / "frontend" / "css" / "jira_addon.css").read_text(encoding="utf-8")
# ⚠ flex: 0 0 auto – sonst gibt der Griff in der Flex-Zeile als Erstes nach.
check("der Griff gibt in der Flex-Zeile nicht nach",
      "flex: 0 0 auto" in _css23.split(".am-q-griff")[1][:200])
check("er hat einen sichtbaren Tastatur-Fokus",
      ".am-q-griff:focus-visible" in _css23)
check("der ausgeschaltete Griff behaelt die Breite",
      ".am-q-griff.is-aus" in _css23
      and "width: 20px" in _css23.split(".am-q-griff")[1][:200])

print("\n=== 24. Die Version ist SICHTBAR (2026-09-11) ===")
# Gemeldet: "wo finde ich die Versionsnummer der AI-Maus exe?" – sie stand in
# der csproj, in den Windows-Dateieigenschaften und im health-Endpunkt, also an
# drei Orten, die am Arbeitsplatz niemand aufschlaegt. Damit war die Frage, die
# beim Melden eines Fehlers IMMER zuerst kommt, nur per Rechtsklick auf die EXE
# zu beantworten.

def _nach24(text, marke, laenge=400):
    """Der Abschnitt HINTER `marke` – "" wenn es sie nicht gibt.

    ⚠ NIE `text.split(marke)[1]`: fehlt die Marke, wirft das einen IndexError,
      und die Gegenprobe bricht ab statt fehlzuschlagen. Genau so blieb
      "Hinweisklasse wieder undefiniert" zuerst ohne Bilanz.
    """
    teile = text.split(marke, 1)
    return teile[1][:laenge] if len(teile) > 1 else ""


_akt24 = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Update" / "Aktualisierung.cs").read_text(encoding="utf-8")
_mark24 = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "Marken.cs").read_text(encoding="utf-8")
_txt24 = (ROOT / "ai-mouse" / "src" / "AiMouse" / "Localization" / "Texte.cs").read_text(encoding="utf-8")

# ── Die Anzeigefassung ──────────────────────────────────────────────────────
check("es gibt eine eigene Fassung ZUM ANZEIGEN",
      "public static string EigeneAnzeige" in _akt24)
# ⚠ Die Assembly traegt VIER Teile ("1.0.2.0"), der Server nennt DREI ("1.0.2").
#   Wer beides nebeneinander liest, haelt zwei Schreibweisen derselben Zahl fuer
#   zwei Staende – und genau diese Frage soll die Anzeige beantworten.
_ea24 = _nach24(_akt24, "public static string EigeneAnzeige", 600)
check("sie ist dreiteilig (nicht Eigene.ToString())",
      "v.Major" in _ea24 and "v.Minor" in _ea24 and "v.Build" in _ea24
      and "Eigene.ToString()" not in _ea24)
# ⚠ Version(0,0).Build IST -1 – das ist der Rueckfall in `Eigene`. Ungeprueft
#   stuende im Kopf "Version 0.0.-1".
check("ein fehlender Build-Teil wird abgefangen (-1)", "v.Build >= 0" in _ea24)

# ── Die Anzeigeregel WIRD AUSGEFUEHRT, nicht gelesen ────────────────────────
# Ein Quelltext-Vergleich kann nicht sagen, WAS herauskommt. Die Formel wird
# deshalb in Python nachgebildet UND gegen den C#-Quelltext abgeglichen, damit
# sie nicht auseinanderlaufen kann.
def _anzeige24(major, minor, build):
    return ("%d.%d.%d" % (major, minor, build)) if build >= 0 else ("%d.%d" % (major, minor))

for _maj, _min, _bld, _soll in (
    (1, 0, 2, "1.0.2"),      # der Regelfall
    (1, 0, 0, "1.0.0"),
    (0, 10, 0, "0.10.0"),    # zweistellig – nicht als Text vergleichen
    (0, 0, -1, "0.0"),       # der Rueckfall `new Version(0, 0)`
):
    check("Anzeige %d.%d(.%d) -> %s (ist: %s)"
          % (_maj, _min, _bld, _soll, _anzeige24(_maj, _min, _bld)),
          _anzeige24(_maj, _min, _bld) == _soll)

# ── Der Kopf traegt sie, und zwar fuer BEIDE Fenster ────────────────────────
check("der Kopf ist ein Container (zwei Schriftgrade)",
      "FlowLayoutPanel" in _mark24)
# ⚠ `Dock = Top` in einem AutoSize-Container ist der bekannte WinForms-Fallstrick;
#   der Fluss waechst dagegen mit der Schrift – also auch bei 150 % Zoom.
check("er waechst mit der Schrift (Zoom)",
      "AutoSize = true" in _mark24 and "AutoSizeMode.GrowAndShrink" in _mark24)
# ⚠ Passt die Version nicht mehr daneben, rutscht sie DARUNTER statt
#   abgeschnitten zu werden – fail-safe in die lesbare Richtung.
check("bei grosser Schrift bricht sie um statt zu verschwinden",
      "WrapContents = true" in _mark24)
check("die Marke steht weiter in der Hausfarbe",
      "AkzentFarbe(s.Akzent)" in _mark24)
# Kein hartes Literal – die Regel dieses Projekts fuer JEDEN UI-Text.
check("die Beschriftung kommt aus Texte", "Texte.Version" in _mark24)
check("und ist dort zweisprachig deklariert",
      'public static string Version => T("Version", "Version")' in _txt24)
# ⚠ In beiden Sprachen gleich – das MUSS die Ausnahmeliste kennen, sonst faellt
#   der Live-Waechter ueber einen Eintrag, der korrekt ist.
_lt24 = (ROOT / "tests" / "live_texte_dev.py").read_text(encoding="utf-8")
check("die DE=EN-Ausnahme ist eingetragen und begruendet",
      '"Version",' in _nach24(_lt24, "ERLAUBT_GLEICH", 400))

# ── Die Portal-Kachel ───────────────────────────────────────────────────────
_amjs24 = (ROOT / "frontend" / "js" / "ai_mouse.js").read_text(encoding="utf-8")
check("die Kachel hat einen Platz fuer die Version", 'id="am-version"' in _amhtml)
check("er steht beim Download-Knopf",
      'id="am-version"' in _nach24(_amhtml, 'class="ja-dl"', 700))
# ⚠ KEINE abgetippte Zahl im Markup: sie wuerde driften, und dann behauptet die
#   Kachel einen Stand, den das ZIP nicht hat.
check("die Zahl steht NICHT im Markup",
      "klient_version" not in _amhtml)
check("sie wird aus health gefuellt", "klient_version" in _amjs24)
# ⚠ Ohne Angabe bleibt sie LEER – "" heisst unbekannt, und eine geratene Nummer
#   waere genau die Behauptung, gegen die die Anzeige gebaut ist.
_dk24 = _nach24(_amjs24, "function downloadKnopfSetzen", 1400)
check("ohne Angabe bleibt sie leer (keine Behauptung)",
      "_health.klient_version || ''" in _dk24 and "v ?" in _dk24)
check("Fremdtext nur per textContent", "vs.textContent" in _dk24)
_i24 = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
check("i18n: aimouse.version in DE und EN",
      _i24.count("'aimouse.version'") >= 2)
# ⚠ `.ja-note` war an SIEBEN Stellen im Markup und NIRGENDS definiert – die
#   Hinweise sahen aus wie gewoehnlicher Fliesstext (Klasse `.ja-actions`, Register).
check("die Hinweisklasse ist ueberhaupt definiert", ".ja-note" in _css23)
# `--text-muted` liegt in beiden Themen unter 4,5:1 – fuer eine Zahl, die man
# ABLESEN soll, zu blass.
check("und nicht im zu blassen Ton",
      "var(--text-secondary)" in _nach24(_css23, ".ja-note", 160))
check("die Version steht mittig neben dem Knopf, nicht oben",
      "align-self: center" in _nach24(_css23, "#am-version", 120))

# ── Die Version selbst ──────────────────────────────────────────────────────
# ⚠ EINE CLIENT-AENDERUNG OHNE ERHOEHUNG ERREICHT KEINEN ARBEITSPLATZ: der
#   Server baut zwar neu, aber `IstNeuer` sagt bei gleicher Nummer zu Recht nein.
check("die Version ist hochgezaehlt (ist: %s)" % (am.klient_version() or "—"),
      am.klient_version() == "1.0.2")


print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
