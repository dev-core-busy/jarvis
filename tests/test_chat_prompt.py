#!/usr/bin/env python3
"""Waechter: Prompt fuer EINEN Chat (2026-09-09).

Geprueft wird die EIGENSCHAFT, nicht das Vorkommen:

  1. Speichern/Lesen an der Sitzung (meta.json), Deckel, "leer entfernt".
  2. `has_prompt` in Liste und Einzelabruf – nie der INHALT.
  3. Die Endpunkte: Benutzer kommt aus der ANMELDUNG (nie aus dem Rumpf),
     unbekannte Sitzung -> 404, eigener Endpunkt statt Merge im PATCH.
  4. DIE AUFLOESUNG IM AGENTEN: der Sitzungs-Prompt ERSETZT den persoenlichen.
     Der Block wird per `ast` geschnitten und WIRKLICH AUSGEFUEHRT – eine
     Quelltext-Suche bliebe gruen, sobald jemand den Zweig spaeter ueberspringt.

⚠ SANDKASTEN MIT EXIT 2: `chat_sessions` schreibt sonst in den echten Bestand
   unter data/chats/. Ein Test, der die Chats der Benutzer anfasst, ist teurer
   als der Fehler, den er sucht.
"""
import ast
import io
import json
import os
import re
import shutil
import sys
import tempfile
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


def sicher(text, fn, info=""):
    """Ruft `fn` und wertet einen Wurf als FAIL – nie als Abbruch.

    Ohne das endet der Lauf beim ersten Fehler OHNE Bilanzzeile und ist von
    'nicht gelaufen' nicht zu unterscheiden (Register)."""
    try:
        check(text, fn(), info)
    except Exception as e:  # noqa: BLE001
        check(text, False, f"wirft: {type(e).__name__}: {e}")


def ohne_kommentare(quelle: str) -> str:
    """Kommentare + Docstrings weg – ein Waechter, der seine eigene Begruendung
    liest, prueft nichts (Register, dreizehn belegte Faelle)."""
    raus = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
            if tok.type == tokenize.COMMENT:
                continue
            raus.append(tok)
        text = tokenize.untokenize(raus)
    except Exception:  # noqa: BLE001
        text = quelle
    # Docstrings zusaetzlich ueber den AST entfernen
    try:
        baum = ast.parse(text)
        stellen = []
        for n in ast.walk(baum):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                d = ast.get_docstring(n, clean=False)
                if d:
                    ziel = n.body[0]
                    stellen.append((ziel.lineno, ziel.end_lineno))
        zeilen = text.splitlines()
        for a, b in stellen:
            for i in range(a - 1, min(b, len(zeilen))):
                zeilen[i] = ""
        text = "\n".join(zeilen)
    except Exception:  # noqa: BLE001
        pass
    return text


print("=" * 74)
print("Waechter: Prompt fuer EINEN Chat")
print("=" * 74)

# ─────────────────────────────────────────────────────────────────────────────
# Sandkasten
# ─────────────────────────────────────────────────────────────────────────────
SAND = Path(tempfile.mkdtemp(prefix="jarvis-chatprompt-"))
os.environ.setdefault("JARVIS_TEST", "1")

from backend import chat_sessions as cs  # noqa: E402

_echte_wurzel = cs._ROOT
cs._ROOT = SAND / "chats"
if not str(cs._ROOT).startswith(str(SAND)):
    print(f"ABBRUCH: Wurzel zeigt nach {cs._ROOT} – NICHT in den Sandkasten.")
    sys.exit(2)
if str(_echte_wurzel) == str(cs._ROOT):
    print("ABBRUCH: Wurzel wurde nicht umgebogen.")
    sys.exit(2)
print(f"Sandkasten: {SAND}\n")

U = "pruef.benutzer"

# ─────────────────────────────────────────────────────────────────────────────
print("[1] Speichern, Lesen, Entfernen")
# ─────────────────────────────────────────────────────────────────────────────
s1 = cs.create_session(U, "Erster Chat")
s2 = cs.create_session(U, "Zweiter Chat")

sicher("frische Sitzung hat keinen eigenen Prompt",
       lambda: cs.get_session_preprompt(U, s1["id"]) == "")

sicher("gespeicherter Prompt kommt zurueck",
       lambda: cs.save_session_preprompt(U, s1["id"], "Antworte knapp.") == "Antworte knapp."
       and cs.get_session_preprompt(U, s1["id"]) == "Antworte knapp.")

sicher("er gilt NUR fuer diese Sitzung",
       lambda: cs.get_session_preprompt(U, s2["id"]) == "")

sicher("leerer Text entfernt ihn (Schluessel weg, nicht leer)",
       lambda: cs.save_session_preprompt(U, s1["id"], "") == ""
       and "preprompt" not in (cs.get_meta(U, s1["id"]) or {}))

sicher("nur Leerraum zaehlt ebenfalls als 'entfernen'",
       lambda: (cs.save_session_preprompt(U, s1["id"], "Text"),
                cs.save_session_preprompt(U, s1["id"], "   \n  "))[1] == ""
       and cs.get_session_preprompt(U, s1["id"]) == "")

sicher(f"Deckel greift ({cs._PREPROMPT_MAX} Zeichen)",
       lambda: len(cs.save_session_preprompt(U, s1["id"], "x" * (cs._PREPROMPT_MAX + 500)))
       == cs._PREPROMPT_MAX)

sicher("unbekannte Sitzung: kein Schreiben, kein Wurf",
       lambda: cs.save_session_preprompt(U, "gibtsnicht", "hallo") == ""
       and cs.get_session_preprompt(U, "gibtsnicht") == "")

# ⚠ Traversal: die Sitzungs-Kennung kommt aus dem Request.
sicher("Traversal in der Kennung schreibt nichts ausserhalb",
       lambda: cs.save_session_preprompt(U, "../../boese", "x") == ""
       and not (SAND / "boese").exists() and not (SAND.parent / "boese").exists())

cs.save_session_preprompt(U, s1["id"], "Antworte knapp.")

sicher("der Titel der Sitzung bleibt beim Speichern unangetastet",
       lambda: (cs.get_meta(U, s1["id"]) or {}).get("title") == "Erster Chat")

# ─────────────────────────────────────────────────────────────────────────────
print("\n[2] has_prompt: die Aussage, nie der Inhalt")
# ─────────────────────────────────────────────────────────────────────────────
liste = cs.list_sessions(U)
eintrag = {e["id"]: e for e in liste}

sicher("Liste meldet has_prompt=True fuer die gesetzte Sitzung",
       lambda: eintrag[s1["id"]]["has_prompt"] is True)
sicher("Liste meldet has_prompt=False fuer die andere",
       lambda: eintrag[s2["id"]]["has_prompt"] is False)
sicher("die Liste enthaelt den INHALT des Prompts nirgends",
       lambda: "Antworte knapp." not in json.dumps(liste, ensure_ascii=False))

# ─────────────────────────────────────────────────────────────────────────────
print("\n[3] Endpunkte")
# ─────────────────────────────────────────────────────────────────────────────
mq = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
mq_ok = ohne_kommentare(mq)

baum = ast.parse(mq)


def rumpf(name):
    for n in ast.walk(baum):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(mq, n) or ""
    return ""


def dekoratoren(name):
    for n in ast.walk(baum):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return [ast.get_source_segment(mq, d) or "" for d in n.decorator_list]
    return []

for fn, verb in (("chat_session_preprompt_get", "get"), ("chat_session_preprompt_save", "put")):
    d = " ".join(dekoratoren(fn))
    sicher(f"{fn}: Route auf /api/chat/sessions/{{sid}}/preprompt ({verb})",
           lambda d=d, verb=verb: f'app.{verb}("/api/chat/sessions/{{sid}}/preprompt")' in d)
    r = rumpf(fn)
    sicher(f"{fn}: Benutzer aus der Anmeldung (Depends(require_auth))",
           lambda r=r: "user: str = Depends(require_auth)" in r)
    sicher(f"{fn}: prueft die Zugehoerigkeit der Sitzung (_valid) und antwortet 404",
           lambda r=r: "cs._valid(user, sid)" in r and "status_code=404" in r)

rs = rumpf("chat_session_preprompt_save")
rs_ok = ohne_kommentare(rs)
# ⚠ Der Benutzer darf NIE aus dem Rumpf kommen – sonst waere der Endpunkt ein
# Weg in fremde Chatordner (gleiche Regel wie beim Empfaenger einer Erinnerung).
sicher("Speichern liest KEINEN Benutzernamen aus dem Rumpf",
       lambda: not re.search(r"body\.get\(\s*[\"'](user|username|benutzer|owner)[\"']", rs_ok),
       rs_ok[:200])
sicher("Speichern reicht genau die Sitzung des angemeldeten Benutzers durch",
       lambda: "cs.save_session_preprompt(user, sid, text)" in rs_ok)
sicher("Antwort traegt has_prompt (die Seitenleiste zeichnet danach neu)",
       lambda: "has_prompt" in rs_ok)

# Der PATCH daneben schreibt weiterhin NUR den Titel: eine Merge-Semantik dort
# ("was nicht im Rumpf steht, bleibt?") hat im Projekt schon Felder verloren.
rp = ohne_kommentare(rumpf("chat_sessions_rename"))
sicher("der PATCH (umbenennen) fasst den Prompt NICHT an",
       lambda: "preprompt" not in rp)

rg = ohne_kommentare(rumpf("chat_sessions_get"))
sicher("Einzelabruf der Sitzung meldet has_prompt, gibt aber den Text nicht heraus",
       lambda: "has_prompt" in rg and "get_session_preprompt" not in rg)

# ─────────────────────────────────────────────────────────────────────────────
print("\n[4] Aufloesung im Agenten – AUSGEFUEHRT, nicht gelesen")
# ─────────────────────────────────────────────────────────────────────────────
aq = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")

# Den Block schneiden – ab dem `if not self.is_sub_agent`, das die ganze
# Klammer aufmacht, bis zum Ende ihrer Einrueckung.
#
# ⚠ DER SCHNITT MUSS DIE BEDINGUNG ENTHALTEN. Eine erste Fassung begann erst
# bei der Zuweisung darin – damit lief im Test ein Block OHNE die
# Sub-Agent-Schranke, und die Pruefung "ein Sub-Agent bekommt nichts" mass
# etwas, das gar nicht im gemessenen Code stand (Register: ein zu enger
# Schnitt prueft fremden bzw. halben Code). Die Positivkontrolle unten haelt
# das fest.
zeilen = aq.splitlines()
anker = next((i for i, z in enumerate(zeilen) if "_pre, _pre_sitzung = " in z), -1)
if anker < 0:
    print("ABBRUCH: Block im Agenten nicht gefunden (umbenannt?).")
    sys.exit(2)
# ⚠ NUR IN DER NAEHE SUCHEN (und auf die exakte Zeile). `if not
# self.is_sub_agent` steht in agent.py mehrfach – eine unbegrenzte
# Rueckwaertssuche fand bei einer Gegenprobe eine Stelle weit darueber und
# schnitt fremden Code mit (der Lauf starb dann an `_LOCAL_PRIVILEGED_USERS`,
# also OHNE Bilanz und ohne erkennbare Ursache).
start = next((i for i in range(anker, max(anker - 20, -1), -1)
              if zeilen[i].strip() == "if not self.is_sub_agent and username:"), -1)
if start < 0:
    # Das ist ein BEFUND, kein "konnte nicht laufen": ohne die Schranke bekaeme
    # ein Sub-Agent den Preprompt. Also FAIL mit Bilanz, nicht Exit 2.
    check("⚠ die Sub-Agent-Schranke steht unmittelbar vor dem Block", False,
          "Zeile 'if not self.is_sub_agent and username:' fehlt in den 20 Zeilen davor")
    print("\n" + "=" * 74)
    print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
    print("=" * 74)
    shutil.rmtree(SAND, ignore_errors=True)
    sys.exit(1)
_ein = len(zeilen[start]) - len(zeilen[start].lstrip())
ende = start
for i in range(start + 1, len(zeilen)):
    z = zeilen[i]
    if z.strip() and (len(z) - len(z.lstrip())) <= _ein:
        break
    ende = i
block = "\n".join(z[_ein:] if z.startswith(" " * _ein) else z for z in zeilen[start:ende + 1])

sicher("der geschnittene Block enthaelt beide Quellen",
       lambda: "get_session_preprompt" in block and "get_preprompt" in block,
       block[:200])
sicher("⚠ und die Sub-Agent-Schranke (sonst misst der Lauf halben Code)",
       lambda: block.lstrip().startswith("if not self.is_sub_agent"),
       block[:80])


class _Cs:
    """Attrappe der beiden Leser – zaehlt, WAS gefragt wurde."""

    def __init__(self, sitzung="", benutzer=""):
        self.sitzung, self.benutzer = sitzung, benutzer
        self.gefragt = []

    def get_session_preprompt(self, u, sid):
        self.gefragt.append(("sitzung", u, sid))
        return self.sitzung

    def get_preprompt(self, u):
        self.gefragt.append(("benutzer", u))
        return self.benutzer


class _Werfer(_Cs):
    def get_session_preprompt(self, u, sid):
        raise RuntimeError("Platte weg")

    def get_preprompt(self, u):
        raise RuntimeError("Platte weg")


def lauf(cs_att, username="anna", session_id="sid1"):
    """Fuehrt den echten Block aus und liefert (Prompt-Zusatz, Statustext)."""
    stati = []

    class _Ich:
        is_sub_agent = False

        async def _send_status(self, ws, text):
            stati.append(text)

    import asyncio
    import types
    # ⚠ Der Block SCHREIBT `system_prompt` (+=). Als Modul-Global waere die
    # Variable in der Wegwerf-Funktion lokal und beim Lesen ungebunden – die
    # Werte gehen deshalb als PARAMETER hinein und kommen als Rueckgabe heraus.
    quelle = ("async def _f(self, ws, username, session_id, system_prompt):\n"
              + "\n".join("    " + z for z in block.splitlines())
              + "\n    return system_prompt\n")
    # `from backend import chat_sessions as _cs` im Block bedienen
    mod = types.ModuleType("backend")
    mod.chat_sessions = cs_att
    alt = sys.modules.get("backend")
    sys.modules["backend"] = mod
    try:
        g = {}
        exec(compile(quelle, "<block>", "exec"), g)   # noqa: S102
        sp = asyncio.run(g["_f"](_Ich(), None, username, session_id, "BASIS"))
        return sp, stati
    finally:
        if alt is not None:
            sys.modules["backend"] = alt
        else:
            sys.modules.pop("backend", None)


# (a) Nur persoenlicher Preprompt
a = _Cs(sitzung="", benutzer="IMMER DEUTSCH")
sp, st = lauf(a)
sicher("ohne Chat-Prompt gilt der persoenliche",
       lambda: "IMMER DEUTSCH" in sp and any("Persönlicher" in s for s in st), f"{sp[:80]} {st}")

# (b) Chat-Prompt vorhanden -> ERSETZT
b = _Cs(sitzung="NUR ENGLISCH", benutzer="IMMER DEUTSCH")
sp, st = lauf(b)
sicher("mit Chat-Prompt steht dieser im System-Prompt",
       lambda: "NUR ENGLISCH" in sp)
sicher("⚠ und der persoenliche steht dann NICHT daneben (er wird ERSETZT)",
       lambda: "IMMER DEUTSCH" not in sp, sp[-120:])
sicher("der Status nennt, dass der Chat-Prompt gilt",
       lambda: any("diesen Chat" in s for s in st), str(st))
sicher("der persoenliche wird dann gar nicht erst gelesen",
       lambda: not any(g[0] == "benutzer" for g in b.gefragt), str(b.gefragt))

# (c) Leerer Chat-Prompt faellt auf den persoenlichen zurueck
c = _Cs(sitzung="   ", benutzer="IMMER DEUTSCH")
sp, st = lauf(c)
sicher("ein Chat-Prompt aus reinem Leerraum zaehlt nicht",
       lambda: "IMMER DEUTSCH" in sp and any("Persönlicher" in s for s in st))

# (d) Ohne Sitzung (z.B. sitzungsloser Aufruf): nur der persoenliche
d = _Cs(sitzung="NUR ENGLISCH", benutzer="IMMER DEUTSCH")
sp, st = lauf(d, session_id="")
sicher("ohne session_id wird die Sitzung gar nicht gefragt",
       lambda: not any(g[0] == "sitzung" for g in d.gefragt) and "IMMER DEUTSCH" in sp)

# (e) Fail-safe: ein Fehler beim Lesen darf den Lauf nicht abbrechen
sp, st = lauf(_Werfer())
sicher("ein Lesefehler laesst den Lauf weiterlaufen (kein Preprompt, kein Wurf)",
       lambda: sp == "BASIS" and not st)

# (f) Beide leer
sp, st = lauf(_Cs())
sicher("ohne beides bleibt der System-Prompt unveraendert",
       lambda: sp == "BASIS" and not st)

# (g) Nur der HAUPTAGENT – ein Sub-Agent bekommt nichts davon
stati_sub = []


def lauf_sub():
    import asyncio
    import types

    class _Ich:
        is_sub_agent = True

        async def _send_status(self, ws, text):
            stati_sub.append(text)

    att = _Cs(sitzung="NUR ENGLISCH", benutzer="IMMER DEUTSCH")
    mod = types.ModuleType("backend")
    mod.chat_sessions = att
    alt = sys.modules.get("backend")
    sys.modules["backend"] = mod
    try:
        quelle = ("async def _f(self, ws, username, session_id, system_prompt):\n"
                  + "\n".join("    " + z for z in block.splitlines())
                  + "\n    return system_prompt\n")
        g = {}
        exec(compile(quelle, "<block>", "exec"), g)   # noqa: S102
        return asyncio.run(g["_f"](_Ich(), None, "anna", "sid1", "BASIS"))
    finally:
        if alt is not None:
            sys.modules["backend"] = alt
        else:
            sys.modules.pop("backend", None)


sicher("ein Sub-Agent bekommt weder den einen noch den anderen Prompt",
       lambda: lauf_sub() == "BASIS")

# Positivkontrolle des Messaufbaus: ohne sie waeren die Gleichheits-Pruefungen
# oben ("== BASIS") auch dann erfuellt, wenn der Block gar nichts tut.
sicher("Positivkontrolle: der Aufbau KANN den System-Prompt veraendern",
       lambda: lauf(_Cs(benutzer="X"))[0] != "BASIS")

# ─────────────────────────────────────────────────────────────────────────────
print("\n[5] Frontend: Symbol, Zustand, Endpunktnutzung")
# ─────────────────────────────────────────────────────────────────────────────
cj = (ROOT / "frontend" / "js" / "chat.js").read_text(encoding="utf-8")
ij = (ROOT / "frontend" / "js" / "icons.js").read_text(encoding="utf-8")
ht = (ROOT / "frontend" / "chat.html").read_text(encoding="utf-8")
css = (ROOT / "frontend" / "css" / "chat.css").read_text(encoding="utf-8")
i18 = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")

sicher("das Symbol liegt zentral in icons.js (zwei Formen)",
       lambda: "prompt: function" in ij and "setPrompt: function" in ij and "BLASE_VOLL" in ij)
sicher("es ist ein Inline-SVG, kein Emoji",
       lambda: "<svg" in ij.split("var BLASE")[1][:400] and "💬" not in ij and "📝" not in ij)
sicher("die Zeile benutzt es ueber JarvisIcons (keine eigene Kopie)",
       lambda: "JarvisIcons.setPrompt" in cj and "<svg" not in cj.split("cs-prompt")[1][:400])

# ⚠ Die gesetzte Sprechblase muss OHNE Hover sichtbar sein: `.cs-act` steht auf
# opacity 0 – als reine Hover-Aktion waere der Zustand unsichtbar.
css_ohne_kommentar = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
sicher("ein gesetzter Chat-Prompt ist OHNE Ueberfahren sichtbar",
       lambda: re.search(r"\.cs-prompt\.is-gesetzt\s*\{[^}]*opacity:\s*1", css_ohne_kommentar) is not None,
       "opacity-Regel fehlt")

sicher("der Knopf traegt den Zustand auch in WORTEN (title/aria-label)",
       lambda: "sprompt_btn_set" in cj and "aria-label" in cj.split("cs-prompt")[1][:600])

for k in ("chat.sprompt_btn", "chat.sprompt_btn_set", "chat.sprompt_title", "chat.sprompt_desc",
          "chat.sprompt_ph", "chat.sprompt_state_own", "chat.sprompt_state_default",
          "chat.sprompt_load_failed"):
    sicher(f"i18n: {k} in DE UND EN",
           lambda k=k: i18.count(f"'{k}'") >= 2)

sicher("der Dialog liegt im Markup und ist als direktes Kind von body geschlossen",
       lambda: 'id="chat-prompt-modal"' in ht and 'class="modal-overlay hidden"' in
       ht.split('id="chat-prompt-modal"')[1][:60])

sicher("gespeichert wird ueber den eigenen Endpunkt der SITZUNG",
       lambda: "'/preprompt'" in cj and "/api/chat/sessions/' + encodeURIComponent(sid) + '/preprompt'" in cj)

# ⚠ Ein Ladefehler darf nicht als leeres Feld erscheinen – ein Speichern darauf
# wuerde einen vorhandenen Prompt loeschen, den niemand gesehen hat.
sp_block = cj.split("async function _openSessionPrompt")[1].split("function _closeSessionPrompt")[0]
sicher("ein Ladefehler sperrt das Feld und sagt es",
       lambda: "ta.disabled = true" in sp_block and "sprompt_load_failed" in sp_block)
sicher("gespeichert wird nur bei entsperrtem Feld",
       lambda: "ta.disabled" in cj.split("async function _saveSessionPrompt")[1][:400])

sicher("der Dialog merkt sich die ANGEKLICKTE Sitzung (nicht die aktive)",
       lambda: "_spSid = s.id" in cj and "_activeSid" not in
       cj.split("async function _saveSessionPrompt")[1].split("async function _renameSession")[0])

sicher("nach dem Speichern wird die Seitenleiste neu gezeichnet",
       lambda: "_renderSidebar()" in cj.split("async function _saveSessionPrompt")[1][:1400])

# ─────────────────────────────────────────────────────────────────────────────
shutil.rmtree(SAND, ignore_errors=True)
print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
print("=" * 74)
sys.exit(1 if _fail else 0)
