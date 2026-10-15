#!/usr/bin/env python3
"""Gegenproben zum Mehrfach-Loeschen von Chats: beisst jeder Waechter EINZELN?

Jede Probe dreht GENAU EINE Zusage zurueck und erwartet, dass der zugehoerige
Waechter das meldet. Beisst eine nicht, ist das ein TESTMANGEL – kein Beweis.

Waechter:
  UI = tests/test_chat_mehrfach_loeschen.js  (jsdom: Markup, Auswahl, Loeschen)
  BE = tests/test_chat_sammel_loeschen.py    (AST: Endpunkt, Schranken, Audit)

⚠ SICHERUNG AUF PLATTE mit LAUFMARKE (Register: ein abgeschossener Harness
hinterlaesst den Baum gepatcht). Jede Datei, die eine Probe anfasst, muss in
DATEIEN stehen – als REGEL geprueft, nicht gepflegt.

⚠ OHNE BYTECODE (PYTHONDONTWRITEBYTECODE=1): liegen Sabotage und
Wiederherstellung in derselben Sekunde und sind gleich gross, laedt ein
spaeterer Lauf sonst die .pyc der SABOTAGE – bei byte-gleicher Quelle.

    python3 tests/gegen_chat_mehrfach_loeschen.py
"""
import atexit
import hashlib
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ABLAGE = pathlib.Path.home() / ".gegen-chat-mehrfach-loeschen"
MARKE = ABLAGE / ".laeuft"

DATEIEN = [
    "backend/main.py",
    "frontend/js/chat.js",
    "frontend/chat.html",
    "frontend/css/chat.css",
    "frontend/js/i18n.js",
]

UI = ["node", str(ROOT / "tests" / "test_chat_mehrfach_loeschen.js")]
BE = ["python3", str(ROOT / "tests" / "test_chat_sammel_loeschen.py")]

JS = "frontend/js/chat.js"
HTML = "frontend/chat.html"
CSS = "frontend/css/chat.css"
I18N = "frontend/js/i18n.js"
PY = "backend/main.py"

PROBEN = [
    # ── Markup (chat.html) ──────────────────────────────────────────────────
    ("Werkzeugzeile fehlt ganz", HTML,
     '<div id="cs-tools" class="cs-tools" hidden>',
     '<div id="cs-tools-weg" class="cs-tools" hidden>', UI),
    ("Werkzeugzeile startet sichtbar (ohne Chats)", HTML,
     '<div id="cs-tools" class="cs-tools" hidden>',
     '<div id="cs-tools" class="cs-tools">', UI),
    ("Loeschknopf startet sichtbar", HTML,
     '<button id="cs-seldel" class="cs-tool cs-tool-del" type="button" hidden',
     '<button id="cs-seldel" class="cs-tool cs-tool-del" type="button"', UI),
    ("⚠ Loeschknopf mit .btn-*-Klasse aus style.css (auf /chat nackt)", HTML,
     '<button id="cs-seldel" class="cs-tool cs-tool-del" type="button" hidden',
     '<button id="cs-seldel" class="btn-secondary" type="button" hidden', UI),

    # ── CSS (chat.css) ──────────────────────────────────────────────────────
    ("Klasse ohne jede CSS-Regel (Knopf ohne Aussehen)", CSS,
     "\n.cs-tool {\n", "\n.cs-tool-gibtsnicht {\n", UI),

    # ── Auswahlmodus zeichnen (chat.js) ─────────────────────────────────────
    ("kein Kaestchen an den Zeilen", JS,
     "                cb.type = 'checkbox'; cb.className = 'cs-check';\n",
     "                cb.type = 'checkbox'; cb.className = 'cs-check-x';\n", UI),
    ("⚠ Aktionsknoepfe bleiben im Auswahlmodus stehen", JS,
     "                list.appendChild(item);\n                return;\n            }\n",
     "                list.appendChild(item);\n            }\n", UI),
    ("⚠ Klick auf die Zeile wechselt die Sitzung statt auszuwaehlen", JS,
     "                    _selSetze(s.id, !_selIds.has(s.id));\n",
     "                    _switchSession(s.id);\n", UI),
    ("gewaehlte Zeile ist ohne Mauszeiger nicht erkennbar", JS,
     "                           + (_selMode && _selIds.has(s.id) ? ' cs-picked' : '');\n",
     "                           + '';\n", UI),
    ("⚠ verschwundene Sitzung bleibt in der Auswahl", JS,
     "        if (_selIds.size) {\n"
     "            const da = new Set(_sessions.map(x => x.id));\n"
     "            Array.from(_selIds).forEach(id => { if (!da.has(id)) _selIds.delete(id); });\n"
     "        }\n", "", UI),

    # ── Werkzeugzeile (chat.js) ─────────────────────────────────────────────
    ("Umschalter wechselt seine Beschriftung nicht", JS,
     "            const k  = _selMode ? 'chat.select_cancel' : 'chat.select_many';\n",
     "            const k  = 'chat.select_many';\n", UI),
    ("i18n-Schluessel wandert nicht mit (Sprachwechsel holt den alten Text)", JS,
     "            modus.setAttribute('data-i18n', k);\n", "", UI),
    ("Loeschknopf bei LEERER Auswahl nicht gesperrt", JS,
     "            del.disabled = _selIds.size === 0;\n",
     "            del.disabled = false;\n", UI),
    ("kein Muelleimer am Loeschknopf", JS,
     "            if (ico && !ico.firstChild) JarvisIcons.setTrash(ico);\n", "", UI),
    ("die Zahl der Auswahl steht nicht im Knopf", JS,
     "            if (txt) txt.textContent = window.t('chat.delete_selected').replace('{n}', String(_selIds.size));\n",
     "            if (txt) txt.textContent = window.t('chat.delete_selected').replace('{n}', '');\n", UI),
    ("\"Alle\" zeigt bei Teilauswahl einen vollen Haken", JS,
     "            all.indeterminate = _selMode && _selIds.size > 0 && !voll;\n",
     "            all.checked = _selMode && _selIds.size > 0;\n", UI),

    # ── Loeschen (chat.js) ──────────────────────────────────────────────────
    ("⚠ keine Rueckfrage vor dem Loeschen", JS,
     "        if (!window.confirm(window.t('chat.delete_many_confirm').replace('{n}', String(ids.length)))) return;\n",
     "", UI),
    ("⚠ es gehen ALLE Chats mit, nicht nur die gewaehlten", JS,
     "        const ids = _sessions.filter(s => _selIds.has(s.id)).map(s => s.id);\n",
     "        const ids = _sessions.map(s => s.id);\n", UI),
    ("⚠ Teilfehlschlag ignoriert (Chat verschwindet, obwohl er noch da ist)", JS,
     "        const weg = new Set(d.deleted);\n",
     "        const weg = new Set(ids);\n", UI),
    ("der Fehlschlag bleibt still", JS,
     "        if (offen) showToast(window.t('chat.delete_many_partial').replace('{n}', String(offen)));\n",
     "", UI),
    ("keine Rueckmeldung ueber die Zahl der geloeschten Chats", JS,
     "        if (weg.size) showToast(window.t('chat.delete_many_done').replace('{n}', String(weg.size)));\n",
     "", UI),
    ("Auswahlmodus bleibt nach dem Loeschen stehen", JS,
     "        _selMode = false; _selIds.clear();\n", "", UI),
    ("⚠ die geloeschte AKTIVE Sitzung bleibt aktiv", JS,
     "        if (!aktiveWeg) { _renderSidebar(); return; }\n",
     "        { _renderSidebar(); return; }\n", UI),
    ("⚠ sind alle Chats weg, entsteht keine neue Sitzung", JS,
     "        if (!_activeSid) {\n"
     "            const ns = await _csCreate('');\n"
     "            if (ns) { _sessions.unshift(ns); _activeSid = ns.id; }\n"
     "        }\n", "", UI),

    # ── Texte (i18n.js) ─────────────────────────────────────────────────────
    ("EN-Text fehlt", I18N,
     "        'chat.delete_selected': 'Delete ({n})',\n", "", UI),
    ("die Rueckfrage nennt die Anzahl nicht mehr", I18N,
     "        'chat.delete_many_confirm': '{n} Chats wirklich löschen? Verlauf und Kontext gehen verloren.',\n",
     "        'chat.delete_many_confirm': 'Chats wirklich löschen? Verlauf und Kontext gehen verloren.',\n", UI),

    # ── Serverseite (main.py) ───────────────────────────────────────────────
    ("Endpunkt liegt unter einem anderen Pfad", PY,
     '@app.post("/api/chat/sessions/delete")\n',
     '@app.post("/api/chat/sessions/delete2")\n', BE),
    ("chat.js ruft einen anderen Pfad (zwei Enden, nie verbunden)", JS,
     "'/api/chat/sessions/delete'", "'/api/chat/sessions/delete-x'", BE),
    ("⚠ Typpruefung fehlt (Lauf ueber einen String)", PY,
     '    if not isinstance(roh, list):\n'
     '        return JSONResponse({"ok": False, "error": "ids fehlt"}, status_code=400)\n', "", BE),
    ("kein Deckel auf die Anzahl je Aufruf", PY,
     '    if len(ids) > _CHAT_DELETE_MAX:\n', '    if False:\n', BE),
    ("Teilerfolge werden nicht benannt", PY,
     '    return JSONResponse({"ok": not fehler, "deleted": geloescht, "failed": fehler})\n',
     '    return JSONResponse({"ok": not fehler, "anzahl": len(geloescht)})\n', BE),
    ("⚠ RAM-Kontext der geloeschten Sitzungen bleibt stehen", PY,
     "            geloescht.append(sid)\n            _chat_kontext_vergessen(user, sid)\n",
     "            geloescht.append(sid)\n", BE),
    ("⚠ RAM-Kontext wird auch fuer NICHT geloeschte Ids verworfen", PY,
     "        if cs.delete_session(user, sid):\n"
     "            geloescht.append(sid)\n"
     "            _chat_kontext_vergessen(user, sid)\n",
     "        _chat_kontext_vergessen(user, sid)\n"
     "        if cs.delete_session(user, sid):\n"
     "            geloescht.append(sid)\n", BE),
    ("⚠ die Einzelloeschung verliert den Helfer wieder (Lehre 2026-08-30)", PY,
     '    ok = cs.delete_session(user, sid)\n    _chat_kontext_vergessen(user, sid)\n',
     '    ok = cs.delete_session(user, sid)\n', BE),
    ("Audit-Eintrag fehlt (Handlung heisst nur 'Chat')", PY,
     '    ("POST",   r"/api/chat/sessions/delete",            "Chat · Unterhaltungen gelöscht"),\n',
     "", BE),
    ("⚠ Audit verbucht die Loeschung als 'Unterhaltung begonnen'", PY,
     '    ("POST",   r"/api/chat/sessions/delete",            "Chat · Unterhaltungen gelöscht"),\n',
     '    ("POST",   r"/api/chat/sessions/delete",            "Chat · Unterhaltung begonnen"),\n', BE),
]


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern():
    ABLAGE.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        # ⚠ IMMER erneuern: eine alte Sicherung stellte einen veralteten Stand her.
        shutil.copy2(ROOT / rel, ABLAGE / rel.replace("/", "__"))
    MARKE.write_text("laeuft", encoding="utf-8")


def zurueck():
    for rel in DATEIEN:
        z = ABLAGE / rel.replace("/", "__")
        if z.exists():
            shutil.copy2(z, ROOT / rel)
    if MARKE.exists():
        MARKE.unlink()


def lauf(cmd):
    """(Exit, hat_bilanz, FAIL-Zahl)."""
    env = {**os.environ,
           "JSDOM_PATH": str(ROOT / "node_modules" / "jsdom"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=300, env=env)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout + r.stderr)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


def main():
    fehlend = sorted({p[1] for p in PROBEN} - set(DATEIEN))
    if fehlend:
        print("ABBRUCH: nicht gesicherte Dateien in PROBEN: %r" % fehlend)
        sys.exit(2)
    if MARKE.exists():
        print("⚠ Rueckstand eines abgeschossenen Laufs – nehme ihn zurueck")
        zurueck()
    sichern()
    stand = {rel: md5(ROOT / rel) for rel in DATEIEN}
    atexit.register(zurueck)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *a: (zurueck(), sys.exit(1)))

    # ⚠ Ohne gruenen Basislauf ist keine Gegenprobe deutbar.
    print("Basislauf…")
    for name, cmd in (("UI", UI), ("BE", BE)):
        rc, bil, f = lauf(cmd)
        if rc != 0 or not bil:
            print("ABBRUCH: Basislauf %s nicht gruen (exit=%s, bilanz=%s, fail=%s)"
                  % (name, rc, bil, f))
            sys.exit(2)
        print("  Basis %s: gruen" % name)

    beissen = nicht = 0
    for name, rel, alt, neu, cmd in PROBEN:
        datei = ROOT / rel
        s = datei.read_text(encoding="utf-8")
        if s.count(alt) != 1:
            print("  \033[33m?\033[0m %-64s SABOTAGE TRIFFT NICHT (%dx)" % (name, s.count(alt)))
            nicht += 1
            continue
        datei.write_text(s.replace(alt, neu, 1), encoding="utf-8")
        rc, bil, f = lauf(cmd)
        datei.write_text(s, encoding="utf-8")
        if rc != 0 and bil and f > 0:
            print("  \033[32m✓\033[0m %-64s beisst (%d FAIL)" % (name, f))
            beissen += 1
        elif rc == 2 and not bil:
            # Exit 2 = "konnte nicht laufen" – das ist ein Melden, kein Bestehen.
            print("  \033[32m✓\033[0m %-64s beisst (Abbruch, Exit 2)" % name)
            beissen += 1
        elif rc != 0 and not bil:
            print("  \033[33m!\033[0m %-64s BRICHT AB ohne Bilanz" % name)
            nicht += 1
        else:
            print("  \033[31m✗\033[0m %-64s BEISST NICHT" % name)
            nicht += 1

    zurueck()
    abw = [rel for rel in DATEIEN if md5(ROOT / rel) != stand[rel]]
    print("\nByte-Gleichheit nach dem Lauf:", "ja" if not abw else "NEIN: %r" % abw)
    print("=" * 84)
    print("beissen: %d von %d" % (beissen, len(PROBEN)))
    sys.exit(1 if (nicht or abw) else 0)


if __name__ == "__main__":
    main()
