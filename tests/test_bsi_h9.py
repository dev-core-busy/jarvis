#!/usr/bin/env python3
"""BSI H9 – Aktionen mit Aussen- oder Loeschwirkung nur nach Klick.

Befund H9 (BSI-Abgleich 2026-09-29): keine Bestaetigung vor Aktionen mit
Aussenwirkung (E-Mail senden/loeschen, Shell). Massnahme: Werkzeuge nach
Wirkung klassifizieren; Aussen- und Loeschwirkung nur nach Klick in der
Oberflaeche. Betreiberentscheid 2026-10-04: Shell nur ohne Sandbox; Clients
ohne Dialog (Apps) mit Hinweis abweisen. Laeufe ohne Oberflaeche: seit
2026-10-11 Freigabe JE AUFTRAG (vorher "wie bisher") – ohne Freigabe bzw. ohne
jeden Auftrag abgewiesen; ausfuehrlich in tests/test_bsi_h9_auftrag.py.

Gemessen wird:

1. ``wirkung.einstufen()`` AUSGEFUEHRT – Tabelle, Shell/Sandbox, MCP,
   Werkzeug-Attribut, Ausnahmen.
2. REGEL ueber alle Werkzeugnamen im Code (Syntaxbaum): jedes Werkzeug, dessen
   Name nach Senden/Loeschen/Anlegen klingt, ist eingestuft – Tabelle oder
   eigenes Attribut. Ein neuer Skill faellt sonst still in "ohne Wirkung".
3. ``wirkung.freigabe()``/``antwort()`` AUSGEFUEHRT – Klick, Ablehnung, fremder
   Benutzer, Frist, Stop, Client ohne Dialog, Lauf ohne Kanal.
4. ECHTE Laeufe (``run_task`` mit Attrappen-Provider): das Werkzeug laeuft
   NUR nach Klick; ohne Dialog nie; headless nur mit Freigabe; ein Rollen-Agent
   erbt den Kanal (Delegation ist kein Umweg); ein Sandbox-Befehl fragt nicht.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.

    venv/bin/python tests/test_bsi_h9.py
"""
import ast
import asyncio
import hashlib
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n── {t} " + "─" * max(0, 66 - len(t)))


try:
    from backend import wirkung as W
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.wirkung nicht importierbar: {type(e).__name__}: {e}")
    sys.exit(2)

# ── 1. Einstufung ────────────────────────────────────────────────────────────
abschnitt("1. einstufen()")

FAELLE = [
    ("email_senden", {"an": "a@beispiel.de"}, {}, W.AUSSEN),
    ("email_antworten", {}, {}, W.AUSSEN),
    ("email_weiterleiten", {}, {}, W.AUSSEN),
    ("email_loeschen", {"mail_id": "1"}, {}, W.LOESCHEN),
    ("email_verschieben", {"mail_id": "1", "ziel": "Gelöschte Elemente"}, {}, W.LOESCHEN),
    ("email_verschieben", {"mail_id": "1", "ziel": "Papierkorb"}, {}, W.LOESCHEN),
    ("email_verschieben", {"mail_id": "1", "ziel": "Projekte/2026"}, {}, None),
    ("email_lesen", {}, {}, None),
    ("email_entwurf", {}, {}, None),
    ("whatsapp_send", {}, {}, W.AUSSEN),
    ("telegram_send", {}, {}, W.AUSSEN),
    ("vemas_write", {}, {}, W.AUSSEN),
    ("jira_create_issue", {}, {}, W.AUSSEN),
    ("confluence_delete_page", {}, {}, W.LOESCHEN),
    ("cron_create", {}, {}, W.ZEITPLAN),
    ("cron_delete", {}, {}, W.LOESCHEN),
    ("cron_list", {}, {}, None),
    ("google_gmail", {"action": "send_mail"}, {}, W.AUSSEN),
    ("google_gmail", {"action": "read_inbox"}, {}, None),
    ("google_calendar", {"action": "delete_event"}, {}, W.LOESCHEN),
    ("google_calendar", {"action": "list_events"}, {}, None),
    ("memory_manage", {"action": "delete"}, {}, W.LOESCHEN),
    ("memory_manage", {"action": " 'delete' "}, {}, W.LOESCHEN),
    ("memory_manage", {"action": "save"}, {}, None),
    ("knowledge_manage", {"action": "remove_folder"}, {}, W.LOESCHEN),
    ("knowledge_search", {"query": "x"}, {}, None),
    ("shell_execute", {"command": "ls"}, {"sandbox": False}, W.SHELL),
    ("shell_execute", {"command": "rm -rf /tmp/x"}, {"sandbox": True}, None),
    ("mcp_irgendwas", {}, {"fremd": True}, W.AUSSEN),
    ("unbekannt", {}, {}, None),
]
for name, args, kw, soll in FAELLE:
    ist = W.einstufen(name, args, **kw)
    pruefe(ist == soll, f"{name} {args or ''} {kw or ''} -> {soll}", f"ist {ist!r}")


class _MitAttr:
    def __init__(self, w):
        self.wirkung = w


pruefe(W.einstufen("mcp_x", {}, tool=_MitAttr(None), fremd=True) is None,
       "Werkzeug-Attribut wirkung=None gewinnt (auch bei MCP)")
pruefe(W.einstufen("email_senden", {}, tool=_MitAttr(None)) is None,
       "Werkzeug-Attribut gewinnt gegen die Tabelle")
pruefe(W.einstufen("neu", {"x": 1}, tool=_MitAttr(lambda a: W.LOESCHEN if a.get("x") else None))
       == W.LOESCHEN, "Werkzeug-Attribut als Funktion der Argumente")


def _wirft(a):
    raise RuntimeError("kaputt")


pruefe(W.einstufen("neu", {}, tool=_MitAttr(_wirft)) == W.AUSSEN,
       "scheiternde Einstufung gilt als Aussenwirkung (fail-closed)")
pruefe(W.einstufen("neu", {}, tool=_MitAttr("quatsch")) == W.AUSSEN,
       "unbekannte Klasse gilt als Aussenwirkung")
pruefe(W.einstufen("shell_execute", {}, tool=_MitAttr(None), sandbox=False) == W.SHELL,
       "Shell ohne Sandbox laesst sich nicht per Attribut freistellen")

zeilen = W.anzeige_argumente({"an": "a@beispiel.de", "text": "x" * 5000,
                              "_status_callback": "intern", "liste": [1, 2]})
pruefe([z[0] for z in zeilen] == ["an", "text", "liste"],
       "Dialog zeigt Modell-Argumente in Reihenfolge, ohne interne '_'-Felder",
       str([z[0] for z in zeilen]))
pruefe(zeilen[1][1].startswith("[gekürzt: 4000 von 5000 Zeichen]"),
       "Kuerzung im Dialog ist beziffert und steht VOR dem Text", zeilen[1][1][:40])

# ── 2. Regel ueber alle Werkzeugnamen ────────────────────────────────────────
abschnitt("2. Regel: wirkungsverdaechtige Werkzeuge sind eingestuft")


def _werkzeuge():
    """{name: (datei, klasse_hat_wirkung)} aus allen Klassen in backend/ und skills/."""
    gefunden = {}
    dateien = list((ROOT / "backend").rglob("*.py")) + list((ROOT / "skills").rglob("*.py"))
    for d in dateien:
        try:
            baum = ast.parse(d.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for kl in (n for n in ast.walk(baum) if isinstance(n, ast.ClassDef)):
            name = None
            hat_wirkung = False
            for st in kl.body:
                if isinstance(st, ast.Assign):
                    for t in st.targets:
                        if isinstance(t, ast.Name) and t.id == "name" \
                                and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                            name = st.value.value
                        if isinstance(t, ast.Name) and t.id == "wirkung":
                            hat_wirkung = True
                elif isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if st.name == "wirkung":
                        hat_wirkung = True
                    if st.name == "name":
                        rets = [r for r in ast.walk(st) if isinstance(r, ast.Return)
                                and isinstance(r.value, ast.Constant) and isinstance(r.value.value, str)]
                        if len(rets) == 1:
                            name = rets[0].value.value
            if name and re.fullmatch(r"[a-z][a-z0-9_]+", name):
                gefunden[name] = (str(d.relative_to(ROOT)), hat_wirkung)
    return gefunden


WZ = _werkzeuge()
for pflicht in ("email_senden", "shell_execute", "memory_manage", "cron_create",
                "whatsapp_send", "google_gmail", "knowledge_search"):
    pruefe(pflicht in WZ, f"Positivkontrolle: Werkzeug '{pflicht}' wird gefunden")
pruefe(len(WZ) >= 60, f"Positivkontrolle: genug Werkzeuge gefunden ({len(WZ)})")

VERDAECHTIG = re.compile(
    r"send|senden|antwort|reply|weiterleit|forward|loesch|delete|remove|upload|"
    r"create_issue|add_comment|create_page|update_page|write|cron_create|post|publish")
# Bewusst geprueft und ohne Bestaetigung: die Wirkung bleibt im eigenen Bereich
# (Datei im eigenen Arbeitsverzeichnis, Entwurf im eigenen Postfach) bzw. die
# Aktion liest nur. Wer hier etwas eintraegt, begruendet es in der Zeile.
OHNE_WIRKUNG_GEPRUEFT = {
    "email_entwurf": "Entwurf bleibt im eigenen Postfach, nichts geht hinaus",
    "write_clipboard": "Zwischenablage des Server-Desktops (xclip), erreicht niemanden",
}
for name, (datei, hat_attr) in sorted(WZ.items()):
    if not VERDAECHTIG.search(name) or name in OHNE_WIRKUNG_GEPRUEFT:
        continue
    pruefe(name in W.TABELLE or hat_attr or name == "shell_execute",
           f"{name} ({datei}) ist eingestuft")
for name in W.TABELLE:
    pruefe(name in WZ, f"Tabellenzeile '{name}' meint ein existierendes Werkzeug")

# ── 3. Kanal: freigabe()/antwort() ───────────────────────────────────────────
abschnitt("3. freigabe() und antwort()")


class WS:
    def __init__(self, antwort_mit=None, kaputt=False):
        self.nachrichten = []
        self.antwort_mit = antwort_mit      # (benutzer, erlaubt) – Klick-Attrappe
        self.kaputt = kaputt

    async def send_json(self, m):
        if self.kaputt:
            raise RuntimeError("Verbindung weg")
        self.nachrichten.append(m)
        if m.get("type") == "bestaetigung_anfrage" and self.antwort_mit is not None:
            benutzer, erlaubt = self.antwort_mit
            # wie der echte Client: Antwort kommt SPAETER, als eigene Nachricht
            asyncio.get_running_loop().call_soon(
                W.antwort, m["id"], benutzer, self, erlaubt)

    def typen(self):
        return [m.get("type") for m in self.nachrichten]

    def letzte(self):
        """Letzte Nachricht oder {} – ein [-1] auf leerer Liste WIRFT (Register)."""
        return self.nachrichten[-1] if self.nachrichten else {}


async def _mit_kanal(kanal, coro):
    tok = W.kanal_cv.set(kanal)
    try:
        return await coro
    finally:
        W.kanal_cv.reset(tok)


async def _nachlauf():
    for _ in range(5):
        await asyncio.sleep(0)


HAENGT = "HAENGT"   # Ergebnis, wenn freigabe() nicht zurueckkehrt
DECKEL_S = 10       # weit ueber jeder echten Dauer hier (Klick-Attrappe: sofort)


async def _gedeckelt(aw):
    """Warten mit hartem Deckel. Ein Haenger (z.B. eine Karte an einen Client,
    der nie klicken kann) wird zu einem pruefbaren Ergebnis statt zu einem
    Stillstand – sonst laeuft der Waechter in die Frist von Minuten, und die
    Gegenprobe sieht einen Abbruch statt eines FAIL."""
    try:
        return await asyncio.wait_for(aw, DECKEL_S)
    except asyncio.TimeoutError:
        return HAENGT


async def fall(kanal, *, warte_nachlauf=True):
    r = await _gedeckelt(_mit_kanal(kanal, W.freigabe(
        "email_senden", {"an": "a@beispiel.de"}, W.AUSSEN)))
    if warte_nachlauf:
        await _nachlauf()
    return r


async def teil3():
    erg = {}
    erg["ohne_kanal"] = await W.freigabe("email_senden", {}, W.AUSSEN)
    with W.auftrag("Test-Auftrag", True):
        erg["ohne_kanal_frei"] = await W.freigabe("email_senden", {}, W.AUSSEN)
    with W.auftrag("Test-Auftrag", False):
        erg["ohne_kanal_nicht_frei"] = await W.freigabe("email_senden", {}, W.AUSSEN)
    ws = WS()
    erg["ohne_dialog"] = (await fall(W.Kanal(ws, "anna", False)), ws)
    ws = WS(("anna", True))
    erg["erlaubt"] = (await fall(W.Kanal(ws, "anna", True)), ws)
    ws = WS(("anna", False))
    erg["abgelehnt"] = (await fall(W.Kanal(ws, "anna", True)), ws)
    ws = WS(("anna", "ja"))       # nur das boolesche True gilt als Freigabe
    erg["kein_bool"] = (await fall(W.Kanal(ws, "anna", True)), ws)
    ws = WS(kaputt=True)
    erg["kaputt"] = (await fall(W.Kanal(ws, "anna", True)), ws)

    # fremder Benutzer klickt -> verworfen; danach der richtige
    ws = WS()
    t = asyncio.ensure_future(_mit_kanal(W.Kanal(ws, "anna", True),
                                         W.freigabe("email_loeschen", {}, W.LOESCHEN)))
    await _nachlauf()
    kid = next((m["id"] for m in ws.nachrichten if m.get("type") == "bestaetigung_anfrage"), "")
    erg["fremd_zugestellt"] = W.antwort(kid, "bert", None, True)
    erg["fremd_noch_offen"] = not t.done()
    erg["richtig_zugestellt"] = W.antwort(kid, "anna", None, False)
    erg["nach_fremd"] = await _gedeckelt(t)
    erg["doppelt"] = W.antwort(kid, "anna", None, True)
    await _nachlauf()

    # Stop waehrend des Wartens
    ws = WS()
    t = asyncio.ensure_future(_mit_kanal(W.Kanal(ws, "anna", True),
                                         W.freigabe("email_senden", {}, W.AUSSEN)))
    await _nachlauf()
    t.cancel()
    try:
        await _gedeckelt(t)
    except asyncio.CancelledError:
        pass
    await _nachlauf()
    erg["stop"] = ws

    # Frist
    alt = W.FRIST_S
    W.FRIST_S = 0.05
    try:
        ws = WS()
        erg["frist"] = (await fall(W.Kanal(ws, "anna", True)), ws)
    finally:
        W.FRIST_S = alt

    # API-Schluessel ohne Benutzer: nur dieselbe Verbindung
    ws = WS()
    t = asyncio.ensure_future(_mit_kanal(W.Kanal(ws, "", True),
                                         W.freigabe("email_senden", {}, W.AUSSEN)))
    await _nachlauf()
    kid = next((m["id"] for m in ws.nachrichten if m.get("type") == "bestaetigung_anfrage"), "")
    erg["anon_fremde_verbindung"] = W.antwort(kid, "", object(), True)
    erg["anon_eigene_verbindung"] = W.antwort(kid, "", ws, True)
    erg["anon"] = await _gedeckelt(t)
    return erg


E = asyncio.run(teil3())
def _txt(x):
    return x if isinstance(x, str) else ""


pruefe(_txt(E["ohne_kanal"]).startswith("NICHT AUSGEFÜHRT"),
       "Lauf ohne Kanal und ohne Auftrag: abgewiesen (fail-closed)", str(E["ohne_kanal"])[:80])
pruefe(E["ohne_kanal_frei"] is None, "Lauf ohne Kanal MIT Freigabe des Auftrags: ausgefuehrt")
pruefe(_txt(E["ohne_kanal_nicht_frei"]).startswith("NICHT AUSGEFÜHRT"),
       "Lauf ohne Kanal, Auftrag ohne Freigabe: abgewiesen")
r, ws = E["ohne_dialog"]
pruefe(_txt(r).startswith("NICHT AUSGEFÜHRT") and "Browser" in _txt(r),
       "Client ohne Dialog: nicht ausgefuehrt, Hinweis auf den Browser-Chat", str(r)[:80])
pruefe(ws.nachrichten == [], "Client ohne Dialog: es wird keine Karte geschickt")
r, ws = E["erlaubt"]
pruefe(r is None, "Klick 'Ausfuehren': freigabe() gibt None (= ausfuehren)", str(r))
anf = next((m for m in ws.nachrichten if m.get("type") == "bestaetigung_anfrage"), {})
pruefe(anf.get("werkzeug") == "email_senden" and anf.get("klasse") == W.AUSSEN
       and anf.get("argumente") == [["an", "a@beispiel.de"]],
       "Anfrage nennt Werkzeug, Klasse und Argumente", str(anf)[:120])
pruefe(ws.typen()[-1:] == ["bestaetigung_erledigt"]
       and ws.letzte().get("grund") == "erlaubt",
       "nach dem Klick quittiert der Server die Karte (grund=erlaubt)", str(ws.typen()))
r, ws = E["abgelehnt"]
pruefe(_txt(r).startswith("ABGELEHNT") and "NICHT auf anderem Weg" in _txt(r),
       "Klick 'Ablehnen': nicht ausgefuehrt, kein Umweg", str(r)[:80])
pruefe(ws.letzte().get("grund") == "abgelehnt", "Quittung grund=abgelehnt")
r, _ = E["kein_bool"]
pruefe(_txt(r).startswith("ABGELEHNT"), "nur ein boolesches True gibt frei", str(r))
r, _ = E["kaputt"]
pruefe(_txt(r).startswith("NICHT AUSGEFÜHRT"),
       "Karte nicht zustellbar: nicht ausgefuehrt", str(r)[:80])
pruefe(E["fremd_zugestellt"] is False and E["fremd_noch_offen"],
       "ein ANDERER Benutzer kann nicht freigeben (Anfrage bleibt offen)")
pruefe(E["richtig_zugestellt"] is True and _txt(E["nach_fremd"]).startswith("ABGELEHNT"),
       "der richtige Benutzer entscheidet danach")
pruefe(E["doppelt"] is False, "eine erledigte Anfrage nimmt keinen zweiten Klick an")
ws = E["stop"]
pruefe(ws.letzte().get("type") == "bestaetigung_erledigt"
       and ws.letzte().get("grund") == "abgebrochen",
       "Stop waehrend des Wartens: Karte erfaehrt 'abgebrochen'", str(ws.letzte()))
r, ws = E["frist"]
pruefe(_txt(r).startswith("NICHT AUSGEFÜHRT") and "keine Bestätigung" in _txt(r),
       "Frist abgelaufen: nicht ausgefuehrt", str(r)[:80])
pruefe(ws.letzte().get("grund") == "frist", "Quittung grund=frist")
pruefe(E["anon_fremde_verbindung"] is False and E["anon_eigene_verbindung"] is True
       and E["anon"] is None,
       "ohne Benutzernamen gilt nur die Verbindung, die gefragt wurde")
pruefe(W.offene_anzahl() == 0, f"keine offene Anfrage bleibt liegen ({W.offene_anzahl()})")

# ── 4. Echte Laeufe ──────────────────────────────────────────────────────────
abschnitt("4. Echte Laeufe mit Attrappen-Provider")

_settings = [p for p in (ROOT / "settings.json", ROOT / "data" / "settings.json") if p.exists()]


def _set_md5():
    return {str(p): hashlib.md5(p.read_bytes()).hexdigest() for p in _settings}


_md5_vorher = _set_md5()
try:
    import backend.agent as A
    import backend.agent_roles as R
    from backend.llm import LLMResponse
    from google.genai import types
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.agent nicht ladbar ({type(e).__name__}: {e}) – mit venv/bin/python starten")
    sys.exit(2)

import types as _pytypes  # noqa: E402

A.JarvisAgent.LLM_PROVIDER = property(lambda self: "openai_compatible")

_tmp = Path(tempfile.mkdtemp(prefix="jarvis_h9_"))
R.ROLES_FILE = _tmp / "agent_roles.json"
if not str(R.ROLES_FILE).startswith(str(_tmp)):
    print("ABBRUCH: Rollen-Datei liegt nicht im Sandkasten")
    sys.exit(2)


class Postausgang:
    """Attrappe fuer email_senden: zaehlt, ob WIRKLICH gesendet wurde."""
    name = "email_senden"
    description = "Sendet eine E-Mail"
    gesendet = []

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {"an": {"type": "STRING"}}}

    async def execute(self, **kw):
        Postausgang.gesendet.append(kw.get("an"))
        return "✅ gesendet"


class Stub:
    def __init__(self, folge):
        self.folge = list(folge)
        self.antworten = []
        self.systeme = []

    async def generate_response(self, model=None, system_prompt=None, contents=None,
                                tools=None, **kw):
        self.systeme.append(system_prompt or "")
        for c in contents or []:
            for p in (c.parts or []):
                fr = getattr(p, "function_response", None)
                if fr is not None:
                    self.antworten.append((fr.response or {}).get("result") or "")
        parts = self.folge.pop(0) if self.folge else [types.Part.from_text(text="fertig")]
        return LLMResponse(parts=parts, raw=None, usage={})


if "backend.main" not in sys.modules:
    fake = _pytypes.ModuleType("backend.main")
    fake.agent_manager = A.AgentManager()
    sys.modules["backend.main"] = fake
_am = sys.modules["backend.main"].agent_manager

_halter = {"s": None}
A.get_provider = lambda *a, **kw: _halter["s"]

# JEDER neue Agent bekommt die Attrappe – auch der Rollen-Agent, den eine
# Delegation erzeugt (er baut seinen Werkzeugkasten selbst aus den Skills; der
# E-Mail-Skill ist lokal nicht aktiv).
_init_echt = A.JarvisAgent.__init__


def _init_mit_post(self, *a, **kw):
    _init_echt(self, *a, **kw)
    p = Postausgang()
    self.tools_map["email_senden"] = p
    self._tool_instances = [t for t in self._tool_instances
                            if getattr(t, "name", "") != "email_senden"] + [p]


A.JarvisAgent.__init__ = _init_mit_post
haupt = A.JarvisAgent()
_am.main_agent = haupt
_am.agents[haupt.agent_id] = haupt


def fc(name, **args):
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def lauf(folge, *, ws=None, bestaetigung=True, headless=False, user="jarvis", freigabe=None):
    stub = Stub(folge)
    _halter["s"] = stub
    haupt.provider = stub
    haupt._user_histories.clear()
    Postausgang.gesendet = []
    ws = ws or WS()
    if headless:
        lauf_ = haupt.run_task_headless("Schick die Mail", actor={
            "user": user, "privileged": True})
        if freigabe is not None:
            lauf_ = W.mit_auftrag("Test-Auftrag", freigabe, lauf_)
        asyncio.run(lauf_)
    else:
        asyncio.run(haupt.run_task("Schick die Mail", ws, username=user,
                                   bestaetigung=bestaetigung))
    return stub, ws, list(Postausgang.gesendet)


SENDEN = [[fc("email_senden", an="x@beispiel.de")], [types.Part.from_text(text="ok")]]
# Kurze Frist im Laufteil: die Klick-Attrappe antwortet sofort; bleibt eine
# Antwort aus (Sabotage), endet der Lauf nach Sekunden statt nach Minuten.
_FRIST_ECHT = W.FRIST_S
W.FRIST_S = 5
try:
    stub, ws, gesendet = lauf(SENDEN, ws=WS(("jarvis", True)))
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    print(f"ABBRUCH: Lauf nicht moeglich: {type(e).__name__}: {e}")
    sys.exit(2)
pruefe("bestaetigung_anfrage" in ws.typen(), "Chat: email_senden legt eine Karte vor")
pruefe(gesendet == ["x@beispiel.de"], "Chat + Klick 'Ausfuehren': die Mail geht hinaus", str(gesendet))
pruefe(any("gesendet" in a for a in stub.antworten), "das Modell bekommt das Ergebnis des Sendens")

stub, ws, gesendet = lauf(SENDEN, ws=WS(("jarvis", False)))
pruefe(gesendet == [], "Chat + Klick 'Ablehnen': es wird NICHTS gesendet", str(gesendet))
pruefe(any("ABGELEHNT" in a for a in stub.antworten), "das Modell erfaehrt die Ablehnung")

stub, ws, gesendet = lauf(SENDEN, bestaetigung=False)
pruefe(gesendet == [] and "bestaetigung_anfrage" not in ws.typen(),
       "App ohne Dialog: nichts gesendet, keine Karte", f"{gesendet} {ws.typen()}")
pruefe(any("NICHT AUSGEFÜHRT" in a for a in stub.antworten),
       "App ohne Dialog: das Modell bekommt den Hinweis")

stub, ws, gesendet = lauf(SENDEN, headless=True)
pruefe(gesendet == [] and any("NICHT AUSGEFÜHRT" in a for a in stub.antworten),
       "Lauf ohne Oberflaeche, ohne Auftrag: nichts gesendet, Modell bekommt den Grund",
       str(gesendet))
stub, ws, gesendet = lauf(SENDEN, headless=True, freigabe=False)
pruefe(gesendet == [], "Lauf ohne Oberflaeche, Auftrag ohne Freigabe: nichts gesendet", str(gesendet))
stub, ws, gesendet = lauf(SENDEN, headless=True, freigabe=True)
pruefe(gesendet == ["x@beispiel.de"] and ws.nachrichten == [],
       "Lauf ohne Oberflaeche MIT Freigabe: gesendet, ohne Rueckfrage", str(gesendet))

# Delegation an eine Rolle mit email_senden: der Rollen-Agent erbt den Kanal.
# ``_delegate_to_role`` wird DIREKT gerufen – ob das Werkzeug ``delegate``
# angeboten wird, haengt am Orchestrator-Skill (lokal aus). Ueber ``run_task``
# rief am 2026-10-04 deshalb der ORCHESTRATOR selbst ``email_senden``, und die
# Pruefung war trivial wahr ("Rolle" stand in "Rolle fertig").
R.anlegen({"id": "post", "name": "Post", "description": "verschickt Post",
           "prompt": "DU BIST DIE POSTSTELLE.", "tools": ["email_senden"], "max_steps": 3})


def delegation(kanal_ws, mit_kanal, freigabe=None):
    stub = Stub([[fc("email_senden", an="y@beispiel.de")],
                 [types.Part.from_text(text="erledigt")]])
    _halter["s"] = stub
    Postausgang.gesendet = []

    async def _los():
        tok = W.kanal_cv.set(W.Kanal(kanal_ws, "jarvis", True)) if mit_kanal else None
        try:
            lauf_ = haupt._delegate_to_role("post", "Schick die Mail", ws=kanal_ws)
            if freigabe is not None:
                return await W.mit_auftrag("Test-Auftrag", freigabe, lauf_)
            return await lauf_
        finally:
            if tok is not None:
                W.kanal_cv.reset(tok)
    haupt._current_username = "jarvis"
    erg = asyncio.run(_los())
    return stub, erg, list(Postausgang.gesendet)


ws = WS(("jarvis", False))
stub, erg, gesendet = delegation(ws, True)
pruefe(any("DU BIST DIE POSTSTELLE." in sp for sp in stub.systeme),
       "Positivkontrolle: der ROLLEN-Prompt lief (es war wirklich die Rolle)",
       str([sp[:40] for sp in stub.systeme]))
pruefe(any(m.get("type") == "bestaetigung_anfrage" and m.get("werkzeug") == "email_senden"
           for m in ws.nachrichten),
       "Delegation: die Rolle legt die Karte ueber den Chat-Kanal vor", str(ws.typen()))
pruefe(gesendet == [], "Delegation ist kein Umweg: Ablehnung gilt auch fuer die Rolle",
       str(gesendet))
stub, erg, gesendet = delegation(WS(), False, freigabe=True)
pruefe(any("DU BIST DIE POSTSTELLE." in sp for sp in stub.systeme) and gesendet == ["y@beispiel.de"],
       "Gegenkontrolle: dieselbe Delegation ohne Kanal, MIT Freigabe des Auftrags sendet",
       f"{gesendet} {erg[:80] if erg else ''}")
stub, erg, gesendet = delegation(WS(), False)
pruefe(gesendet == [],
       "Delegation aus einem Lauf ohne Auftrag sendet NICHT (die Rolle erbt die Verweigerung)",
       f"{gesendet} {erg[:80] if erg else ''}")

# Sandbox-Shell fragt nicht: Einstufung im Dispatch bekommt sandbox=True
quelle = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
baum = ast.parse(quelle)
ruf = [n for n in ast.walk(baum) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
       and n.func.attr == "einstufen" and isinstance(n.func.value, ast.Name)
       and n.func.value.id == "_wirkung"]
pruefe(len(ruf) == 1, f"genau eine Einstufung im Dispatch ({len(ruf)})")
sb = next((k.value for k in (ruf[0].keywords if ruf else []) if k.arg == "sandbox"), None)
pruefe(sb is not None and "_sandbox_user" in ast.unparse(sb),
       "die Sandbox-Angabe kommt aus exec_args['_sandbox_user'] (der echten Entscheidung)",
       ast.unparse(sb) if sb is not None else "fehlt")

# ── 5. main.py: Faehigkeit und Antwortweg ───────────────────────────────────
abschnitt("5. main.py: Dialogfaehigkeit nur ausdruecklich, Antwort nur vom Benutzer")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
MB = ast.parse(MAIN)
hwm = next((n for n in ast.walk(MB) if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "handle_ws_message"), None)
pruefe(hwm is not None, "Positivkontrolle: handle_ws_message gefunden")


def _ist_get(knoten, schluessel):
    """``msg.get("<schluessel>")``"""
    return (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Attribute)
            and knoten.func.attr == "get" and isinstance(knoten.func.value, ast.Name)
            and knoten.func.value.id == "msg" and knoten.args
            and isinstance(knoten.args[0], ast.Constant) and knoten.args[0].value == schluessel)


def _ist_is_true(knoten, schluessel):
    return (isinstance(knoten, ast.Compare) and _ist_get(knoten.left, schluessel)
            and len(knoten.ops) == 1 and isinstance(knoten.ops[0], ast.Is)
            and isinstance(knoten.comparators[0], ast.Constant)
            and knoten.comparators[0].value is True)


zuw = [n for n in ast.walk(hwm or MB) if isinstance(n, ast.Assign)
       and any(isinstance(z, ast.Name) and z.id == "_kann_bestaetigen" for z in n.targets)]
pruefe(len(zuw) == 1 and _ist_is_true(zuw[0].value, "bestaetigung"),
       "_kann_bestaetigen = msg.get('bestaetigung') is True (nur ausdrueckliches true)",
       ast.unparse(zuw[0].value) if zuw else "fehlt")
rufe = [n for n in ast.walk(MB) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "run_task"]
pruefe(len(rufe) >= 2, f"Positivkontrolle: run_task-Aufrufe in main.py ({len(rufe)})")
for r in rufe:
    kw = next((k.value for k in r.keywords if k.arg == "bestaetigung"), None)
    pruefe(isinstance(kw, ast.Name) and kw.id == "_kann_bestaetigen",
           f"run_task in Zeile {r.lineno} gibt bestaetigung=_kann_bestaetigen",
           ast.unparse(kw) if kw is not None else "fehlt (Unter-Agent-Erbe statt Angabe)")

zweig = None
for n in ast.walk(hwm or MB):
    if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) \
            and isinstance(n.test.left, ast.Name) and n.test.left.id == "msg_type" \
            and isinstance(n.test.comparators[0], ast.Constant) \
            and n.test.comparators[0].value == "bestaetigung_antwort":
        zweig = n
pruefe(zweig is not None, "Zweig fuer 'bestaetigung_antwort' vorhanden")
ant = [c for c in ast.walk(ast.Module(body=(zweig.body if zweig else []), type_ignores=[]))
       if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "antwort"]
pruefe(len(ant) == 1 and len(ant[0].args) == 4, "der Zweig ruft wirkung.antwort(id, benutzer, ws, erlaubt)")
if len(ant) == 1 and len(ant[0].args) == 4:
    a_ben, a_ws, a_erl = ant[0].args[1], ant[0].args[2], ant[0].args[3]
    pruefe("_ws_usernames" in ast.unparse(a_ben) and "id(ws)" in ast.unparse(a_ben),
           "Benutzer kommt aus der Anmeldung der Verbindung, nicht aus der Nachricht",
           ast.unparse(a_ben))
    pruefe(isinstance(a_ws, ast.Name) and a_ws.id == "ws", "die Verbindung wird mitgegeben")
    pruefe(_ist_is_true(a_erl, "erlaubt"), "erlaubt nur bei ausdruecklichem true",
           ast.unparse(a_erl))
# Die Token-Pruefung oben in handle_ws_message gilt fuer alles ausser ping –
# also auch fuer die Antwort. Positivkontrolle, dass es diese Schranke gibt:
pruefe(hwm is not None and 'if msg_type != "ping":' in ast.get_source_segment(MAIN, hwm),
       "Token-Pruefung gilt auch fuer die Antwort (nur ping ist ausgenommen)")

W.FRIST_S = _FRIST_ECHT
shutil.rmtree(_tmp, ignore_errors=True)
_md5_nachher = _set_md5()
pruefe(_md5_vorher == _md5_nachher, "settings.json vom Test NICHT veraendert")

print(f"\n{'=' * 70}\nErgebnis: {_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(0 if _fail == 0 else 1)
