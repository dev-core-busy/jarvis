#!/usr/bin/env python3
"""Gegenproben zum Chat-Prompt: jede Aenderung EINZELN zurueckdrehen.

Eine Gegenprobe, die nicht beisst, ist ein Testmangel – kein Beweis. Gemessen
wird am EXIT-CODE und an der BILANZZEILE, nie am Zaehlen von FAIL-Zeilen: ein
Lauf, der abbricht, hat 0 FAIL und ist trotzdem kaputt.

⚠ SICHERUNG AUF PLATTE + atexit + SIGTERM: wird das Skript per Timeout
   abgeschossen, laeuft ein `finally` NICHT – im Projekt ist so schon ein
   sabotierter Arbeitsbaum liegengeblieben und hat den naechsten Testlauf
   Fehler melden lassen, die es nicht gab.
"""
import atexit
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-chat-prompt"      # NICHT /tmp (1777, fremde Reste)

DATEIEN = ["backend/agent.py", "backend/chat_sessions.py", "backend/main.py",
           "frontend/js/chat.js", "frontend/js/icons.js", "frontend/css/chat.css"]

WAECHTER = [("Backend", [sys.executable, "tests/test_chat_prompt.py"]),
            ("UI", ["node", "tests/test_chat_prompt_ui.js"])]


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        (ABLAGE / rel.replace("/", "__")).write_bytes((ROOT / rel).read_bytes())


def zurueck():
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists():
            (ROOT / rel).write_bytes(q.read_bytes())


def rueckstand_pruefen():
    """Rueckstand eines abgeschossenen Vorlaufs zuerst zuruecknehmen."""
    if ABLAGE.exists() and any(ABLAGE.iterdir()):
        abweichend = [rel for rel in DATEIEN
                      if (ABLAGE / rel.replace("/", "__")).exists()
                      and (ABLAGE / rel.replace("/", "__")).read_bytes() != (ROOT / rel).read_bytes()]
        if abweichend:
            print(f"⚠ Rueckstand eines frueheren Laufs gefunden – nehme zurueck: {abweichend}")
            zurueck()


def lauf(cmd):
    """(exit, hat_bilanz, fails)."""
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=180)
    aus = p.stdout + p.stderr
    m = re.search(r"Ergebnis:\s*(\d+)\s*OK,\s*(\d+)\s*FAIL", aus)
    return p.returncode, bool(m), int(m.group(2)) if m else -1


def ersetze(rel, alt, neu, anzahl=1):
    """Ersetzt und PRUEFT den Treffer – eine Sabotage, die nicht griff, sieht
    aus wie ein zahnloser Waechter."""
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) >= anzahl, f"Sabotage verfehlt ihr Ziel in {rel}: {alt[:60]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


PROBEN = []


def probe(name, fn):
    PROBEN.append((name, fn))


# ─── die Proben ──────────────────────────────────────────────────────────────
probe("Agent liest den Sitzungs-Prompt gar nicht (Altstand)", lambda: ersetze(
    "backend/agent.py",
    'if session_id:\n                    _pre = (_cs.get_session_preprompt(username, session_id) or "").strip()\n                    _pre_sitzung = bool(_pre)',
    'if False:\n                    _pre = ""\n                    _pre_sitzung = False'))

probe("Agent ERGAENZT statt zu ersetzen", lambda: ersetze(
    "backend/agent.py",
    'if not _pre:\n                    _pre = (_cs.get_preprompt(username) or "").strip()',
    '_pre = ((_cs.get_preprompt(username) or "").strip() + "\\n" + _pre).strip()'))

probe("Agent nennt im Status nicht, welcher Prompt gilt", lambda: ersetze(
    "backend/agent.py",
    'await self._send_status(ws, "📝 Prompt für diesen Chat aktiv"\n                                        if _pre_sitzung else "📝 Persönlicher Preprompt aktiv")',
    'await self._send_status(ws, "📝 Persönlicher Preprompt aktiv")'))

probe("Sub-Agent-Schranke entfernt", lambda: ersetze(
    "backend/agent.py", "if not self.is_sub_agent and username:", "if username:"))

probe("leerer Text speichert einen leeren Eintrag (statt zu entfernen)", lambda: ersetze(
    "backend/chat_sessions.py",
    '        else:\n            meta.pop("preprompt", None)\n            text = ""',
    '        else:\n            meta["preprompt"] = ""\n            text = ""'))

probe("Deckel raus", lambda: ersetze(
    "backend/chat_sessions.py",
    'def save_session_preprompt(user: str, sid: str, text: str) -> str:',
    'def save_session_preprompt(user: str, sid: str, text: str) -> str:  # noqa\n    pass') or
    ersetze("backend/chat_sessions.py", '    text = (text or "")[:_PREPROMPT_MAX]\n    with _LOCK:\n        sd = _sess_dir(user, sid)',
            '    text = (text or "")\n    with _LOCK:\n        sd = _sess_dir(user, sid)'))

probe("has_prompt nicht in der Sitzungsliste", lambda: ersetze(
    "backend/chat_sessions.py",
    '"has_prompt": bool((m.get("preprompt") or "").strip())',
    '"has_prompt2": False'))

probe("Endpunkt nimmt den Benutzer aus dem Rumpf", lambda: ersetze(
    "backend/main.py",
    "    saved = cs.save_session_preprompt(user, sid, text)",
    "    saved = cs.save_session_preprompt(body.get('user') or user, sid, text)"))

probe("Endpunkt prueft die Zugehoerigkeit der Sitzung nicht (Speichern)", lambda: ersetze(
    "backend/main.py",
    '''    from backend import chat_sessions as cs
    if not cs._valid(user, sid):
        return JSONResponse({"ok": False, "error": "Nicht gefunden"}, status_code=404)
    text = ""''',
    '''    from backend import chat_sessions as cs
    text = ""'''))

probe("Sprechblase gar nicht gerendert", lambda: ersetze(
    "frontend/js/chat.js",
    "item.appendChild(title); item.appendChild(pr); item.appendChild(ren); item.appendChild(del);",
    "item.appendChild(title); item.appendChild(ren); item.appendChild(del);"))

probe("nur EINE Form (gefuellt = hohl)", lambda: ersetze(
    "frontend/js/icons.js",
    "prompt: function (gesetzt) { return gesetzt ? BLASE_VOLL : BLASE; },\n        setPrompt: function (el, gesetzt) { return setzen(el, gesetzt ? BLASE_VOLL : BLASE); }",
    "prompt: function (gesetzt) { return BLASE; },\n        setPrompt: function (el, gesetzt) { return setzen(el, BLASE); }"))

probe("Zustand nicht in Worten (title/aria bleibt gleich)", lambda: ersetze(
    "frontend/js/chat.js",
    "pr.title = window.t(s.has_prompt ? 'chat.sprompt_btn_set' : 'chat.sprompt_btn');",
    "pr.title = window.t('chat.sprompt_btn');"))

probe("gesetzte Blase nur beim Ueberfahren sichtbar (opacity-Regel raus)", lambda: ersetze(
    "frontend/css/chat.css",
    ".cs-item .cs-act.cs-prompt.is-gesetzt { opacity: 1; color: var(--accent); }",
    ".cs-item .cs-act.cs-prompt.is-gesetzt { color: var(--accent); }"))

probe("Dialog laedt die AKTIVE statt der angeklickten Sitzung", lambda: ersetze(
    "frontend/js/chat.js",
    "        _spSid = s.id;\n", "        _spSid = _activeSid || s.id;\n"))

probe("Ladefehler sperrt das Feld nicht", lambda: ersetze(
    "frontend/js/chat.js",
    "            if (ta) ta.disabled = true;\n",
    ""))

probe("Speichern prueft die Sperre nicht (schreibt trotz Ladefehler)", lambda: ersetze(
    "frontend/js/chat.js",
    "        if (!ta || !_spSid || ta.disabled) return;",
    "        if (!ta || !_spSid) return;"))

probe("Seitenleiste wird nach dem Speichern nicht neu gezeichnet", lambda: ersetze(
    "frontend/js/chat.js",
    "if (s) { s.has_prompt = !!d.has_prompt; _renderSidebar(); }",
    "if (s) { s.has_prompt = !!d.has_prompt; }"))

probe("Antwort des Servers wird ignoriert (Formularstand gewinnt)", lambda: ersetze(
    "frontend/js/chat.js",
    "                ta.value = d.preprompt || '';\n                const s = _sessions.find(x => x.id === sid);\n                if (s) { s.has_prompt = !!d.has_prompt; _renderSidebar(); }",
    "                const s = _sessions.find(x => x.id === sid);\n                if (s) { s.has_prompt = !!ta.value.trim(); _renderSidebar(); }"))


# ─── Ablauf ──────────────────────────────────────────────────────────────────
def main():
    rueckstand_pruefen()
    sichern()
    atexit.register(zurueck)
    signal.signal(signal.SIGTERM, lambda *a: (zurueck(), sys.exit(143)))

    print("=" * 74)
    print("BASISLAUF (ohne gruene Basis ist keine Gegenprobe deutbar)")
    print("=" * 74)
    basis = {}
    for name, cmd in WAECHTER:
        rc, bilanz, fails = lauf(cmd)
        basis[name] = fails
        print(f"  {name:8s} exit={rc} bilanz={bilanz} FAIL={fails}")
        if rc != 0 or not bilanz or fails != 0:
            print("ABBRUCH: Basis ist nicht gruen.")
            return 2

    print("\n" + "=" * 74)
    print("GEGENPROBEN")
    print("=" * 74)
    zahnlos = []
    for name, fn in PROBEN:
        zurueck()
        try:
            fn()
        except AssertionError as e:
            print(f"  ⚠ {name}: {e}")
            zahnlos.append(name + " (Sabotage verfehlt)")
            continue
        teil = []
        gebissen = False
        for wn, cmd in WAECHTER:
            rc, bilanz, fails = lauf(cmd)
            if rc != 0:
                gebissen = True
            teil.append(f"{wn}: exit={rc} " + (f"FAIL={fails}" if bilanz else "OHNE BILANZ"))
        print(("  ✔ " if gebissen else "  ✗ ZAHNLOS ") + name + "  [" + " · ".join(teil) + "]")
        if not gebissen:
            zahnlos.append(name)

    zurueck()
    # Byte-Gleichheit nach dem Wiederherstellen pruefen.
    schlecht = [rel for rel in DATEIEN
                if (ROOT / rel).read_bytes() != (ABLAGE / rel.replace("/", "__")).read_bytes()]
    print("\n" + "=" * 74)
    print(f"Wiederhergestellt: {'OK' if not schlecht else 'ABWEICHUNG ' + str(schlecht)}")
    print(f"Gebissen: {len(PROBEN) - len(zahnlos)} von {len(PROBEN)}"
          + (f" · ZAHNLOS: {zahnlos}" if zahnlos else ""))
    print("=" * 74)
    # Die Sicherung beim GEORDNETEN Ende abraeumen – bleibt sie liegen, stellt
    # ein spaeterer Lauf einen veralteten Stand her.
    for f in ABLAGE.iterdir():
        f.unlink()
    return 1 if (zahnlos or schlecht) else 0


if __name__ == "__main__":
    sys.exit(main())
