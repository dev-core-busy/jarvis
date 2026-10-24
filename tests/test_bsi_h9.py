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
    def __init__(self, antwort_mit=None, kaputt=False, aenderungen=None):
        self.nachrichten = []
        self.antwort_mit = antwort_mit      # (benutzer, erlaubt) – Klick-Attrappe
        self.kaputt = kaputt
        # Korrekturen, die der Mensch in der Karte getippt hat. Die echte
        # Oberflaeche schickt sie im selben Paket wie den Klick.
        self.aenderungen = aenderungen

    async def send_json(self, m):
        if self.kaputt:
            raise RuntimeError("Verbindung weg")
        self.nachrichten.append(m)
        if m.get("type") == "bestaetigung_anfrage" and self.antwort_mit is not None:
            benutzer, erlaubt = self.antwort_mit
            # wie der echte Client: Antwort kommt SPAETER, als eigene Nachricht
            asyncio.get_running_loop().call_soon(
                W.antwort, m["id"], benutzer, self, erlaubt, self.aenderungen)

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


async def fall(kanal, *, warte_nachlauf=True, werkzeug="email_senden", args=None,
               exec_args=None):
    """Ein Freigabe-Durchlauf. ``exec_args`` ist der Satz, der AUSGEFUEHRT
    wuerde – im echten Dispatch eine Kopie von ``args``, die VOR der Freigabe
    entsteht. Genau diese Trennung muss der Pruefstand nachbilden, sonst kann
    er nicht sehen, in welchen der beiden Saetze eine Korrektur geschrieben
    wird (und ein Pruefstand mit EINEM Dict waere trivial gruen)."""
    a = {"an": "a@beispiel.de"} if args is None else args
    e = dict(a) if exec_args is None else exec_args
    r = await _gedeckelt(_mit_kanal(kanal, W.freigabe(werkzeug, a, W.AUSSEN, e)))
    if warte_nachlauf:
        await _nachlauf()
    return r


async def teil3():
    erg = {}
    erg["ohne_kanal"] = await W.freigabe("email_senden", {}, W.AUSSEN, {})
    with W.auftrag("Test-Auftrag", True):
        erg["ohne_kanal_frei"] = await W.freigabe("email_senden", {}, W.AUSSEN, {})
    with W.auftrag("Test-Auftrag", False):
        erg["ohne_kanal_nicht_frei"] = await W.freigabe("email_senden", {},
                                                        W.AUSSEN, {})
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
    t = asyncio.ensure_future(_mit_kanal(
        W.Kanal(ws, "anna", True), W.freigabe("email_loeschen", {}, W.LOESCHEN, {})))
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
                                         W.freigabe("email_senden", {}, W.AUSSEN, {})))
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
                                         W.freigabe("email_senden", {}, W.AUSSEN, {})))
    await _nachlauf()
    kid = next((m["id"] for m in ws.nachrichten if m.get("type") == "bestaetigung_anfrage"), "")
    erg["anon_fremde_verbindung"] = W.antwort(kid, "", object(), True)
    erg["anon_eigene_verbindung"] = W.antwort(kid, "", ws, True)
    erg["anon"] = await _gedeckelt(t)

    # ── Korrektur eines Empfaengers in der Karte (AENDERBAR) ────────────────
    # Gemessen wird die WIRKUNG: landet der getippte Wert in dem Satz, mit dem
    # das Werkzeug gerufen wird? Deshalb zwei getrennte Dicts – im Dispatch
    # sind es auch zwei (`exec_args = dict(args)` VOR der Freigabe).
    a = {"an": "Max Mustermann", "betreff": "B", "text": "T"}
    e = dict(a)
    ws = WS(("anna", True), aenderungen={"an": "max.mustermann@beispiel.de"})
    erg["korr_ok"] = (await fall(W.Kanal(ws, "anna", True), args=a, exec_args=e), a, e, ws)

    # Ein Feld, das NICHT in AENDERBAR steht, muss verworfen werden
    a2 = {"an": "x@beispiel.de", "betreff": "Echt", "text": "T"}
    e2 = dict(a2)
    ws = WS(("anna", True), aenderungen={"betreff": "Untergeschoben"})
    erg["korr_fremdes_feld"] = (await fall(W.Kanal(ws, "anna", True),
                                           args=a2, exec_args=e2), e2)

    # Ein Werkzeug ohne aenderbare Felder nimmt gar nichts an
    a3 = {"mail_id": "1"}
    e3 = dict(a3)
    ws = WS(("anna", True), aenderungen={"mail_id": "999"})
    erg["korr_fremdes_werkzeug"] = (await fall(W.Kanal(ws, "anna", True),
                                               werkzeug="email_loeschen",
                                               args=a3, exec_args=e3), e3)

    # ABLEHNEN mit getippter Korrektur: nichts wird uebernommen
    a4 = {"an": "alt@beispiel.de"}
    e4 = dict(a4)
    ws = WS(("anna", False), aenderungen={"an": "neu@beispiel.de"})
    erg["korr_abgelehnt"] = (await fall(W.Kanal(ws, "anna", True),
                                        args=a4, exec_args=e4), e4)

    # ── Eine abgelehnte Aktion kommt NICHT wieder ──────────────────────────
    # Vorfall DEV 2026-10-23: nach "Ablehnen" rief das Modell email_senden im
    # selben Lauf erneut, und es kam eine ZWEITE Karte. Gemessen wird die
    # Wirkung: der zweite Anlauf darf GAR KEINE Karte erzeugen.
    ws_a = WS(("anna", False))
    kanal_a = W.Kanal(ws_a, "anna", True)
    _tok = W.lauf_oeffnen()
    try:
        r1 = await fall(kanal_a, args={"an": "a@beispiel.de"})
        # Zweiter Anlauf im SELBEN Lauf, eigener WS: wuerde eine Karte kommen,
        # stuende sie in ws_b.
        ws_b = WS(("anna", True))
        r2 = await fall(W.Kanal(ws_b, "anna", True), args={"an": "a@beispiel.de"})
        # Anderes Werkzeug, auch abgelehnt -> der Riegel gilt je WERKZEUG
        ws_c = WS(("anna", True))
        r3 = await fall(W.Kanal(ws_c, "anna", True), werkzeug="email_weiterleiten",
                        args={"an": "a@beispiel.de"})
        erg["riegel"] = (r1, r2, r3, ws_b, ws_c)
    finally:
        W.lauf_schliessen(_tok)

    # Auch die FRIST sperrt den zweiten Anlauf: derselbe Mensch wuerde eine
    # zweite Karte genauso nicht beantworten, und der Lauf haengt dann erneut
    # bis zur Frist. (Diese Pruefung fehlte - die Gegenprobe "Frist wird nicht
    # gemerkt" blieb deshalb stumm.)
    _alt_frist = W.FRIST_S
    W.FRIST_S = 0.05
    _tok_f = W.lauf_oeffnen()
    try:
        ws_f1 = WS()                      # antwortet NIE -> Frist
        rf1 = await fall(W.Kanal(ws_f1, "anna", True), args={"an": "a@beispiel.de"})
        ws_f2 = WS(("anna", True))        # wuerde sofort klicken
        rf2 = await fall(W.Kanal(ws_f2, "anna", True), args={"an": "a@beispiel.de"})
        erg["riegel_frist"] = (rf1, rf2, ws_f2)
    finally:
        W.lauf_schliessen(_tok_f)
        W.FRIST_S = _alt_frist

    # ── Delegation ist kein Umweg um den Riegel ────────────────────────────
    # ⚠ CODE-REVIEW 2026-10-24: `run_task` oeffnet die Klammer, und
    # `AgentManager.run_sub_agent` ruft `run_task` ERNEUT (eigener
    # asyncio-Task, ohne `bestaetigung` – der Kanal wird also geerbt). Ein
    # unbedingtes `verweigert_cv.set(set())` gab dem Unter-Agenten damit ein
    # frisches, LEERES Set: nach "Ablehnen" kam fuer dasselbe Werkzeug eine
    # zweite Karte. Gemessen wird deshalb die WIRKUNG in genau diesem Aufbau –
    # verschachtelte Klammer im eigenen Task – und nicht, dass `lauf_oeffnen`
    # irgendwo gerufen wird (das prueft Abschnitt 6 am Syntaxbaum, und es war
    # gruen, waehrend der Riegel offenstand).
    _tok_dl = W.lauf_oeffnen()
    try:
        ws_g1 = WS(("anna", False))         # lehnt ab
        r_g1 = await fall(W.Kanal(ws_g1, "anna", True), args={"an": "a@beispiel.de"})

        async def _unteragent():
            # Genau wie run_task: Klammer oeffnen, arbeiten, schliessen.
            _tok_kind = W.lauf_oeffnen()
            try:
                _geerbt = W.verweigert_grund("email_senden")
                ws_g2 = WS(("anna", True))  # wuerde sofort klicken
                r = await fall(W.Kanal(ws_g2, "anna", True),
                               args={"an": "a@beispiel.de"})
                return _tok_kind, _geerbt, r, ws_g2
            finally:
                W.lauf_schliessen(_tok_kind)

        _tok_kind, _geerbt, r_g2, ws_g2 = await asyncio.create_task(_unteragent())
        # Nach dem Unter-Lauf muss die Marke des ELTERN-Laufs noch stehen:
        # ein `reset` mit einem Token, das gar keinen Wert ersetzt hat, haette
        # sie abgeraeumt (deshalb gibt `lauf_oeffnen` beim Erben None zurueck).
        erg["riegel_delegation"] = (r_g1, _geerbt, r_g2, ws_g2, _tok_kind,
                                    W.verweigert_grund("email_senden"))
    finally:
        W.lauf_schliessen(_tok_dl)

    # OHNE Lauf-Klammer greift der Riegel nicht (headless hat keine Karte)
    ws_d = WS(("anna", False))
    r_d1 = await fall(W.Kanal(ws_d, "anna", True), args={"an": "a@beispiel.de"})
    ws_e = WS(("anna", True))
    r_d2 = await fall(W.Kanal(ws_e, "anna", True), args={"an": "a@beispiel.de"})
    erg["ohne_klammer"] = (r_d1, r_d2, ws_e)

    # ── Versendemaske OHNE Empfaenger ──────────────────────────────────────
    # Betreiberfestlegung: "versende das Bild als E-Mail" ohne Empfaenger darf
    # NICHT im Text zurueckfragen, sondern muss die Maske mit Adressbuch
    # oeffnen. Dafuer kommt der Aufruf OHNE `an` – die Karte bietet das Feld
    # trotzdem an, und der Mensch traegt es dort ein.
    a6 = {"betreff": "B", "text": "T"}        # KEIN `an`
    e6 = dict(a6)
    ws6 = WS(("anna", True), aenderungen={"an": "gewaehlt@beispiel.de"})
    erg["ohne_empfaenger"] = (await fall(W.Kanal(ws6, "anna", True),
                                         args=a6, exec_args=e6), e6, ws6)

    # Zeilenumbruch im getippten Wert wird entschaerft (Kopfzeilen-Hygiene)
    a5 = {"an": "alt@beispiel.de"}
    e5 = dict(a5)
    ws = WS(("anna", True),
            aenderungen={"an": "neu@beispiel.de\nBcc: heimlich@beispiel.de"})
    erg["korr_umbruch"] = (await fall(W.Kanal(ws, "anna", True),
                                      args=a5, exec_args=e5), e5)
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

# ── 3b. Korrektur eines Empfaengers in der Karte ─────────────────────────────
abschnitt("3b. Korrektur in der Karte (wirkung.AENDERBAR)")

# Positivkontrolle ZUERST: ohne sie sind die folgenden Pruefungen trivial wahr
# (ein Aufruf, der gar nicht freigegeben wird, aendert selbstverstaendlich auch
# nichts).
#
# ⚠ SIE IST ABER KEIN EXIT-2-GRUND – bezahlte Lehre aus dem ersten Lauf dieses
# Abschnitts: die erste Fassung brach mit `SystemExit(2)` ab, wenn der Aufruf
# nicht freigegeben wurde. Genau diese Bedingung stellt aber die Gegenprobe
# "Kanal wird nie gelesen" her; sie meldete deshalb "konnte nicht laufen"
# STATT eines Bisses, und ein abgebrochener Lauf ist von einem bestandenen
# nicht zu unterscheiden. Die Frage, die das verhindert, ist immer dieselbe:
# WELCHE Sabotagen treffen diesen Riegel? Eine erwartbare Produktaenderung
# gehoert als FAIL mit Zahlen gemeldet; Exit 2 bleibt dem Fall, in dem der
# MESSAUFBAU nicht laufen kann – hier: die Weissliste gibt es gar nicht.
if not hasattr(W, "AENDERBAR") or not hasattr(W, "aenderbare_felder"):
    print("ABBRUCH: wirkung.AENDERBAR / aenderbare_felder fehlen – dieser "
          "Abschnitt kann nichts messen")
    raise SystemExit(2)
r, a, e, ws = E["korr_ok"]
_frei = r is None
pruefe(_frei, "Positivkontrolle: der korrigierte Aufruf wird freigegeben",
       str(r)[:120])
# Die folgenden Pruefungen werden NICHT uebersprungen, wenn die Kontrolle
# faellt – eine uebersprungene Pruefung sieht wie eine bestandene aus. Sie
# melden stattdessen mit dem Grund, dass sie nicht deutbar sind.
_grund = "" if _frei else " [nicht deutbar: Aufruf nicht freigegeben]"
pruefe(_frei and e.get("an") == "max.mustermann@beispiel.de",
       "die getippte Adresse steht in dem Satz, der AUSGEFUEHRT wird",
       str(e) + _grund)
pruefe(a.get("an") == "Max Mustermann",
       "der Vorschlag des Modells bleibt unveraendert (die Karte zeigt ihn)", str(a))
anf = next((m for m in ws.nachrichten if m.get("type") == "bestaetigung_anfrage"), {})
pruefe(anf.get("aenderbar") == ["an"],
       "die Anfrage nennt genau die aenderbaren Felder dieses Aufrufs",
       str(anf.get("aenderbar")))
# ⚠ Dass der SERVER die Herkunft mitschickt, war ungemessen (die Gegenprobe
# "Herkunft wird nicht mitgeschickt" blieb stumm): Abschnitt 3e prueft die
# FUNKTION, der UI-Waechter speist das Feld von Hand ein. Beides sagt nichts
# ueber die gesendete Nachricht.
pruefe("herkunft" in anf,
       "die Anfrage traegt die Herkunft der aenderbaren Felder", str(sorted(anf)))
pruefe(isinstance(anf.get("herkunft"), dict) and "an" in (anf.get("herkunft") or {}),
       "und zwar fuer das Empfaengerfeld", str(anf.get("herkunft")))

r, e2 = E["korr_fremdes_feld"]
pruefe(r is None and e2.get("betreff") == "Echt",
       "ein Feld ausserhalb der Weissliste wird VERWORFEN", str(e2))
pruefe(e2.get("an") == "x@beispiel.de", "und der Empfaenger bleibt unberuehrt")

r, e3 = E["korr_fremdes_werkzeug"]
pruefe(e3.get("mail_id") == "1",
       "ein Werkzeug ohne aenderbare Felder nimmt keine Korrektur an", str(e3))

r, e4 = E["korr_abgelehnt"]
pruefe(_txt(r).startswith("ABGELEHNT") and e4.get("an") == "alt@beispiel.de",
       "bei 'Ablehnen' wird NICHTS uebernommen", str(e4))

r, e5 = E["korr_umbruch"]
pruefe("\n" not in e5.get("an", "") and "\r" not in e5.get("an", ""),
       "ein Zeilenumbruch im getippten Wert wird entschaerft", repr(e5.get("an")))

# Die Weissliste selbst: `email_antworten` hat KEIN Empfaengerfeld, darf also
# keines anbieten – eine Zusage ohne Wirkung waere schlimmer als keine.
pruefe("email_antworten" not in W.AENDERBAR,
       "email_antworten bietet kein Empfaengerfeld an (es hat keines)")
pruefe(W.aenderbare_felder("email_senden", {"an": "x", "betreff": "b"}) == ["an"],
       "nur Felder, die der Aufruf WIRKLICH hat, werden angeboten",
       str(W.aenderbare_felder("email_senden", {"an": "x", "betreff": "b"})))
pruefe(W.aenderbare_felder("shell_execute", {"command": "ls"}) == [],
       "ein Werkzeug ausserhalb der Weissliste bietet nichts an")

# ── 3d. Eine abgelehnte Aktion kommt nicht wieder ───────────────────────────
abschnitt("3d. Riegel: kein zweiter Anlauf nach einer Ablehnung")
r1, r2, r3, ws_b, ws_c = E["riegel"]
# Positivkontrolle: der ERSTE Anlauf wurde ueberhaupt abgelehnt.
pruefe(_txt(r1).startswith("ABGELEHNT"),
       "Positivkontrolle: der erste Anlauf wird abgelehnt", str(r1)[:80])
pruefe(_txt(r2).startswith("NICHT AUSGEFÜHRT") and "schon vorgelegt" in _txt(r2),
       "der zweite Anlauf wird OHNE Karte abgewiesen", str(r2)[:110])
_karten_b = [m for m in ws_b.nachrichten if m.get("type") == "bestaetigung_anfrage"]
pruefe(_karten_b == [],
       "und es entsteht GAR KEINE zweite Karte (kein Karten-Spam, kein "
       "versehentlicher Klick)", str(len(_karten_b)))
pruefe("ausgeschlossen" in _txt(r2) and "nächste Anweisung" in _txt(r2),
       "die Antwort nennt den naechsten Schritt (Benutzer hat das Wort)",
       str(r2)[:140])
pruefe("anderem Empfänger" in _txt(r2),
       "sie schliesst ausdruecklich auch den Versuch mit anderen Argumenten aus",
       str(r2)[:140])
# Der Riegel gilt JE WERKZEUG: ein anderes Werkzeug darf weiter fragen.
_karten_c = [m for m in ws_c.nachrichten if m.get("type") == "bestaetigung_anfrage"]
pruefe(r3 is None and len(_karten_c) == 1,
       "ein ANDERES Werkzeug wird weiterhin vorgelegt (der Riegel sperrt nicht "
       "den ganzen Lauf)", f"r3={str(r3)[:40]} karten={len(_karten_c)}")

rf1, rf2, ws_f2 = E["riegel_frist"]
pruefe(_txt(rf1).startswith("NICHT AUSGEFÜHRT") and "keine Bestätigung" in _txt(rf1),
       "Positivkontrolle: der erste Anlauf laeuft in die Frist", str(rf1)[:80])
pruefe(_txt(rf2).startswith("NICHT AUSGEFÜHRT") and "schon vorgelegt" in _txt(rf2),
       "nach einer FRIST wird der zweite Anlauf ebenfalls abgewiesen", str(rf2)[:110])
pruefe([m for m in ws_f2.nachrichten
        if m.get("type") == "bestaetigung_anfrage"] == [],
       "und auch dann entsteht keine zweite Karte")

r_g1, _geerbt, r_g2, ws_g2, _tok_kind, _nachher = E["riegel_delegation"]
pruefe(_txt(r_g1).startswith("ABGELEHNT"),
       "Positivkontrolle: im Eltern-Lauf wird abgelehnt", str(r_g1)[:60])
pruefe(_geerbt == "abgelehnt",
       "ein Unter-Agent ERBT die Verweigerung (eigene Lauf-Klammer, eigener "
       "asyncio-Task)", repr(_geerbt))
pruefe(_tok_kind is None,
       "eine schon offene Klammer wird nicht ersetzt (lauf_oeffnen gibt None)",
       repr(_tok_kind))
pruefe(_txt(r_g2).startswith("NICHT AUSGEFÜHRT") and "schon vorgelegt" in _txt(r_g2),
       "Delegation ist kein Umweg: der Unter-Agent wird ebenfalls abgewiesen",
       str(r_g2)[:110])
pruefe([m for m in ws_g2.nachrichten
        if m.get("type") == "bestaetigung_anfrage"] == [],
       "und im Unter-Agenten entsteht GAR KEINE zweite Karte",
       str(len([m for m in ws_g2.nachrichten
                if m.get("type") == "bestaetigung_anfrage"])))
pruefe(_nachher == "abgelehnt",
       "der Unter-Lauf raeumt die Marke des Eltern-Laufs NICHT ab", repr(_nachher))

r_d1, r_d2, ws_e = E["ohne_klammer"]
pruefe(_txt(r_d1).startswith("ABGELEHNT") and r_d2 is None,
       "ohne Lauf-Klammer greift der Riegel NICHT (headless entscheidet die "
       "Auftrags-Freigabe)", str(r_d2)[:60])
pruefe(W.verweigert_grund("email_senden") == "",
       "nach dem Lauf ist die Marke abgeraeumt (kein Nachwirken in den naechsten "
       "Auftrag)", W.verweigert_grund("email_senden"))

# ── 3e. Herkunft der Adresse ────────────────────────────────────────────────
abschnitt("3e. Herkunft: aufgeloest gegen uebernommen")
from backend import adressbuch as _AB                                # noqa: E402
# Ohne Klammer: UNBEKANNT – und das ist nicht "uebernommen" (eine Anzeige darf
# keinen Zustand behaupten, den sie nicht kennt).
pruefe(_AB.ist_aufgeloest("x@beispiel.de") is None,
       "ohne Lauf-Klammer ist die Herkunft UNBEKANNT (nicht 'uebernommen')")
pruefe(W.herkunft_felder("email_senden", {"an": "x@beispiel.de"})
       .get("an") == "unbekannt",
       "und die Karte bekommt genau das gesagt")
_t = _AB.lauf_oeffnen()
try:
    pruefe(_AB.ist_aufgeloest("x@beispiel.de") is False,
           "im Lauf ohne Suche: NICHT aufgeloest")
    _AB.merken(["x@beispiel.de"])
    pruefe(_AB.ist_aufgeloest("x@beispiel.de") is True,
           "nach der Suche: aufgeloest")
    pruefe(_AB.ist_aufgeloest("X@Beispiel.DE") is True,
           "ohne Ruecksicht auf Gross/Klein")
    # ⚠ Mehrere Empfaenger: EINE uebernommene Adresse macht die Zeile ungeprueft
    pruefe(_AB.ist_aufgeloest("x@beispiel.de, fremd@beispiel.de") is False,
           "eine einzige uebernommene Adresse macht die ganze Zeile ungeprueft")
    h = W.herkunft_felder("email_senden", {"an": "x@beispiel.de",
                                           "cc": "fremd@beispiel.de"})
    pruefe(h.get("an") == "aufgeloest" and h.get("cc") == "uebernommen",
           "die Karte bekommt die Herkunft JE FELD", str(h))
    pruefe("betreff" not in h,
           "fuer nicht aenderbare Felder wird keine Herkunft behauptet", str(h))
    # ⚠ CODE-REVIEW 2026-10-24: dieselbe Erb-Regel wie beim Riegel – ein
    # Unter-Agent oeffnet die Klammer erneut. Mit einem frischen Set waere
    # `ist_aufgeloest` dort FALSE, und die Karte haette eine im Eltern-Lauf
    # nachgesehene Adresse als "nicht geprueft" gewarnt: eine Warnung im
    # Regelfall, die den Fall nicht mehr traegt, fuer den sie gebaut ist.
    _t_kind = _AB.lauf_oeffnen()
    try:
        pruefe(_t_kind is None,
               "Adressbuch: eine offene Klammer wird geerbt, nicht ersetzt",
               repr(_t_kind))
        pruefe(_AB.ist_aufgeloest("x@beispiel.de") is True,
               "ein Unter-Agent sieht die im Eltern-Lauf aufgeloeste Adresse")
    finally:
        _AB.lauf_schliessen(_t_kind)
    pruefe(_AB.ist_aufgeloest("x@beispiel.de") is True,
           "und der Unter-Lauf raeumt die Marke des Eltern-Laufs nicht ab")
finally:
    _AB.lauf_schliessen(_t)

# ── 3f. Versendemaske OHNE Empfaenger ───────────────────────────────────────
abschnitt("3f. Maske ohne Empfaenger (Adressbuch statt Textfrage)")
pruefe(W.pflichtfelder("email_senden") == ["an"],
       "email_senden hat den Empfaenger als PFLICHTfeld der Maske",
       str(W.pflichtfelder("email_senden")))
pruefe(W.pflichtfelder("email_entwurf") == [],
       "email_entwurf NICHT – ein Entwurf ohne Empfaenger ist zulaessig",
       str(W.pflichtfelder("email_entwurf")))
# Die Kernzusage: das Feld wird angeboten, OBWOHL der Aufruf es nicht hat.
pruefe(W.aenderbare_felder("email_senden", {"betreff": "B", "text": "T"}) == ["an"],
       "ein FEHLENDER Empfaenger wird trotzdem als aenderbares Feld angeboten",
       str(W.aenderbare_felder("email_senden", {"betreff": "B", "text": "T"})))
pruefe(W.aenderbare_felder("email_entwurf", {"betreff": "B"}) == [],
       "beim Entwurf wird nichts erfunden, was der Aufruf nicht hat")

r6, e6, ws6 = E["ohne_empfaenger"]
pruefe(r6 is None, "Positivkontrolle: der Aufruf ohne Empfaenger wird "
                   "freigegeben (die Maske kam)", str(r6)[:80])
pruefe(e6.get("an") == "gewaehlt@beispiel.de",
       "der in der Maske gewaehlte Empfaenger landet im AUSGEFUEHRTEN Satz",
       str(e6))
anf6 = next((m for m in ws6.nachrichten
             if m.get("type") == "bestaetigung_anfrage"), {})
pruefe(anf6.get("pflicht") == ["an"],
       "die Karte erfaehrt, welches Feld gefuellt sein MUSS",
       str(anf6.get("pflicht")))
pruefe("an" in (anf6.get("aenderbar") or []),
       "und dass der Empfaenger aenderbar ist", str(anf6.get("aenderbar")))
# Ein Feld, das WEDER im Aufruf steht NOCH Pflichtfeld ist, bleibt gesperrt.
_z = {"betreff": "Echt"}
pruefe(W.uebernehmen("email_senden", _z, {"cc": "untergeschoben@beispiel.de"}) == []
       and "cc" not in _z,
       "ein fehlendes Feld OHNE Pflicht wird weiterhin verworfen", str(_z))

# ── 3c. Die beiden Argumentsaetze duerfen nicht verwechselt werden ───────────
abschnitt("3c. Anzeige-Satz gegen Ausfuehrungs-Satz (agent.py)")
#
# Die teuerste denkbare Verwechslung an dieser Stelle: `freigabe` bekommt den
# Satz, der ANGEZEIGT wurde, statt den, der AUSGEFUEHRT wird. Im Dispatch sind
# das zwei Objekte (`exec_args = dict(args)` entsteht VOR der Freigabe) – eine
# Korrektur ginge dann in die Anzeige und die Mail an die alte Adresse. Das ist
# am Ergebnis NICHT zu sehen, deshalb wird es hier am Syntaxbaum gemessen.
import ast as _ast2                                                  # noqa: E402
_AGQ = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
_agb = _ast2.parse(_AGQ)
_frg = [n for n in _ast2.walk(_agb)
        if isinstance(n, _ast2.Call) and isinstance(n.func, _ast2.Attribute)
        and n.func.attr == "freigabe"]
pruefe(len(_frg) == 1, f"Positivkontrolle: genau ein freigabe()-Aufruf im Dispatch "
                       f"({len(_frg)})")
if len(_frg) == 1:
    _a = [_ast2.unparse(x) for x in _frg[0].args]
    pruefe(len(_a) == 4 and _a[3] == "exec_args",
           "freigabe() bekommt den Satz, der AUSGEFUEHRT wird (exec_args)", str(_a))
    # Und derselbe Name muss unten wirklich entpackt werden – ein `exec_args`,
    # das nicht in `tool.execute(**…)` landet, waere ein zweiter toter Satz.
    _exe = [n for n in _ast2.walk(_agb)
            if isinstance(n, _ast2.Call) and isinstance(n.func, _ast2.Attribute)
            and n.func.attr == "execute"
            and any(isinstance(k, _ast2.keyword) and k.arg is None for k in n.keywords)]
    _namen = {_ast2.unparse(k.value) for n in _exe for k in n.keywords if k.arg is None}
    pruefe("exec_args" in _namen,
           "und genau dieser Satz wird an das Werkzeug entpackt", str(_namen))
# ⚠ Die Lauf-Klammern: ohne sie ist der Riegel wirkungslos und die Herkunft
# dauerhaft "unbekannt". Das war ungemessen (die Gegenprobe "Lauf-Klammer
# fehlt" blieb stumm), weil der Waechter seine Klammer SELBST oeffnet.
# Geprueft wird deshalb am Syntaxbaum, dass `run_task` sie oeffnet UND
# schliesst – eine geoeffnete Klammer ohne Reset haengt am Kontext des
# naechsten Laufs.
for _mod, _auf, _zu in (("_wirkung", "lauf_oeffnen", "lauf_schliessen"),
                        ("_adrb", "lauf_oeffnen", "lauf_schliessen")):
    _rufe = [n for n in _ast2.walk(_agb)
             if isinstance(n, _ast2.Call) and isinstance(n.func, _ast2.Attribute)
             and n.func.attr == _auf
             and isinstance(n.func.value, _ast2.Name) and n.func.value.id == _mod]
    pruefe(len(_rufe) == 1,
           f"run_task oeffnet die Lauf-Klammer {_mod}.{_auf}() genau einmal",
           str(len(_rufe)))
    _resets = [n for n in _ast2.walk(_agb)
               if isinstance(n, _ast2.Call) and isinstance(n.func, _ast2.Attribute)
               and n.func.attr == _zu
               and isinstance(n.func.value, _ast2.Name) and n.func.value.id == _mod]
    pruefe(len(_resets) == 1,
           f"und schliesst sie wieder ({_mod}.{_zu}())", str(len(_resets)))

# Der Audit protokolliert, was WIRKLICH lief – nicht den Vorschlag des Modells.
_aud = [n for n in _ast2.walk(_agb)
        if isinstance(n, _ast2.Call) and isinstance(n.func, _ast2.Name)
        and n.func.id == "_audit"]
pruefe(len(_aud) == 1, f"Positivkontrolle: ein Audit-Aufruf im Dispatch ({len(_aud)})")
if len(_aud) == 1:
    _kw = next((k.value for k in _aud[0].keywords if k.arg == "args"), None)
    pruefe(isinstance(_kw, _ast2.Name) and _kw.id == "exec_args",
           "der Audit protokolliert exec_args (das Ausgefuehrte), nicht args",
           _ast2.unparse(_kw) if _kw is not None else "fehlt")

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
pruefe(len(ant) == 1, "der Zweig ruft wirkung.antwort() genau einmal",
       f"{len(ant)} Aufrufe")
# ⚠ HIER STAND `len(args) == 4` – eine ZAHL, also eine Zeitbombe: mit den
# Korrekturen aus der Karte sind es fuenf, und die Zahl haette einen Fehler
# gemeldet, den es nicht gibt. Gemessen wird jetzt die EIGENSCHAFT, und die
# wichtigste davon kann eine Argumentzahl ueberhaupt nicht sehen:
_ruf = ant[0] if ant else None
_quelltext = [ast.unparse(x) for x in (_ruf.args if _ruf else [])]
# (a) Der BENUTZERNAME kommt aus der Verbindung, NICHT aus der Nachricht.
#     Stuende dort `msg.get("user")`, koennte jeder Angemeldete eine fremde
#     Aktion freigeben, indem er den Namen des Besitzers behauptet – die
#     Pruefung in wirkung.antwort() waere dann gegen sich selbst gerichtet.
pruefe(len(_quelltext) >= 2 and "_ws_usernames" in _quelltext[1]
       and "msg" not in _quelltext[1],
       "der Benutzername kommt aus der Verbindung, nicht aus der Nachricht",
       _quelltext[1] if len(_quelltext) >= 2 else "fehlt")
# (b) Die Korrekturen werden ueberhaupt durchgereicht – ohne das waere das
#     Empfaengerfeld in der Karte eine Anzeige ohne Wirkung.
pruefe(any("aenderungen" in s for s in _quelltext),
       "die Korrekturen aus der Karte werden durchgereicht", str(_quelltext))
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
