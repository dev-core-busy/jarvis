#!/usr/bin/env python3
"""Gegenproben zu Fragefeld und Referenzdateien in Short Tracks.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob einer der beiden
Waechter beisst (``test_short_tracks_fragen.py`` / ``…_ui.js``). Eine Probe,
die nicht beisst, ist ein Testmangel – kein Beweis.

SABOTIERT WIRD EINE KOPIE, NICHT DER ARBEITSBAUM. Die bisherigen Harnesse
patchen die echten Dateien und sichern sie auf Platte; hier arbeitet der
Betreiber parallel an denselben Dateien (``main.py``, ``i18n.js``), und ein
Zurueckstellen aus der Sicherung wuerde eine Aenderung, die er WAEHREND des
Laufs speichert, still ueberschreiben. Jede Probe bekommt deshalb einen frischen
Wegwerf-Baum (``backend/``, die betroffenen Frontend-Dateien, die beiden
Waechter samt ``tests/lib``) – ein abgeschossener Lauf hinterlaesst dort
hoechstens ein Verzeichnis im Scratch, nie einen sabotierten Arbeitsbaum.

Gezaehlt wird nur ein ECHTER Biss: Exit 1 MIT Bilanzzeile und mindestens einem
FAIL. Exit 2 oder ein Absturz ohne Bilanz ist "konnte nicht laufen" und zaehlt
als NICHT gebissen (Register: ein Absturz ist kein Biss).

    python3 tests/gegen_short_tracks_fragen.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JSDOM = os.environ.get("JSDOM_PATH") or str(ROOT / "node_modules" / "jsdom")
PY = "tests/test_short_tracks_fragen.py"
JS = "tests/test_short_tracks_fragen_ui.js"
FRONT = ["frontend/tracks.html", "frontend/js/tracks.js", "frontend/js/i18n.js",
         "frontend/js/chatlib.js",
         "frontend/js/icons.js", "frontend/js/sitzung.js", "frontend/js/seite_breit.js"]


def baum() -> Path:
    """Frischer Wegwerf-Baum mit allem, was die beiden Waechter lesen."""
    wurzel = Path(tempfile.mkdtemp(prefix="gegen_st_fragen_"))
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "backend", wurzel / "backend", ignore=ign)
    shutil.copytree(ROOT / "tests" / "lib", wurzel / "tests" / "lib", ignore=ign)
    for rel in FRONT + [PY, JS]:
        ziel = wurzel / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, ziel)
    (wurzel / "data").mkdir()
    return wurzel


def lauf(wurzel: Path, wer: str) -> tuple[int, int, bool]:
    """(exit, FAIL-Anzahl, Bilanz gesehen?) eines Waechters im Wegwerf-Baum."""
    cmd = ([sys.executable, PY] if wer == "py" else ["node", JS])
    env = dict(os.environ, JSDOM_PATH=JSDOM, PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run(cmd, cwd=wurzel, capture_output=True, text=True,
                           timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return (124, -1, False)
    m = re.search(r"(\d+) OK, (\d+) FAIL", p.stdout + p.stderr)
    return (p.returncode, int(m.group(2)) if m else -1, bool(m))


def patch(wurzel: Path, rel: str, alt: str, neu: str) -> None:
    p = wurzel / rel
    s = p.read_text(encoding="utf-8")
    n = s.count(alt)
    if n != 1:
        raise SystemExit("ABBRUCH: Sabotage-Anker in %s trifft %d-mal statt einmal:\n%s"
                         % (rel, n, alt[:160]))
    p.write_text(s.replace(alt, neu), encoding="utf-8")


PROBEN = []


def probe(name, wer, *aenderungen):
    PROBEN.append((name, wer, aenderungen))


ST, RUN, MAIN, SB = ("backend/short_tracks.py", "backend/short_tracks_runner.py",
                     "backend/main.py", "backend/sandbox.py")
TJ, I18 = "frontend/js/tracks.js", "frontend/js/i18n.js"

# ── Registry ────────────────────────────────────────────────────────────────
probe("ref_name laesst fuehrende Punkte stehen ('..' wird gueltig)", "py",
      (ST, '    n = n.lstrip(".").strip("_")', '    n = n.strip("_")'))
probe("referenz_ablegen prueft das Aenderungsrecht nicht", "py",
      (ST, '''        d = holen(dump_id)
        if not d or not darf_aendern(d, user, ist_admin):
            raise DumpFehler("Dump nicht gefunden.")
        name = ref_name(dateiname)''', '''        d = holen(dump_id)
        if not d:
            raise DumpFehler("Dump nicht gefunden.")
        name = ref_name(dateiname)'''))
probe("Deckel MAX_REFERENZEN raus", "py",
      (ST, "        if not ersetzt and len(vorhanden) >= MAX_REFERENZEN:",
           "        if False:"))
probe("Ablage loeschen raeumt die Referenzen nicht mit ab", "py",
      (ST, "                shutil.rmtree(ordner, ignore_errors=True)", "                pass"))
probe("Symlinks im Referenzverzeichnis zaehlen mit", "py",
      (ST, '''        if p.name.startswith(".") or p.is_symlink() or not p.is_file():''',
           '''        if p.name.startswith(".") or not p.is_file():'''))
probe("referenz_loeschen prueft das Aenderungsrecht nicht", "py",
      (ST, '''        d = holen(dump_id)
        if not d or not darf_aendern(d, user, ist_admin):
            return False
        if not name or ref_name(name) != name:''', '''        d = holen(dump_id)
        if not d:
            return False
        if not name or ref_name(name) != name:'''))
probe("Fragefeld ist per Vorgabe AN", "py",
      (ST, '        "fragen": bool(q.get("fragen", False)),',
           '        "fragen": bool(q.get("fragen", True)),'))
probe("Referenzen ohne Verzeichnisrechte 0750", "py",
      (ST, "                os.chmod(verz, VERZ_MODUS)", "                pass"))

# ── Runner ──────────────────────────────────────────────────────────────────
probe("die Frage steht am Ende NICHT noch einmal", "py",
      (RUN, '''    if frage:
        wiederholung += (''', '''    if False:
        wiederholung += ('''))
probe("'REFERENZ DER ABLAGE' wird im Fremdtext nicht gebrochen", "py",
      (RUN, '''    "REFERENZ DER ABLAGE",\n''', ""))
probe("'FRAGE DES BENUTZERS' wird im Fremdtext nicht gebrochen", "py",
      (RUN, '''    "FRAGE DES BENUTZERS",\n''', ""))
probe("Referenzen stehen HINTER dem abgelegten Inhalt", "py",
      (RUN, '''    for i, t in enumerate(referenzen, 1):
        marke = ("REFERENZ DER ABLAGE %d von %d" % (i, len(referenzen))) \\
            if len(referenzen) > 1 else "REFERENZ DER ABLAGE"
        stuecke.append(_inhaltsblock(nonce, marke, t))

    mehrere = len(teile) > 1
    for i, t in enumerate(teile, 1):
        marke = ("ABGELEGTER INHALT %d von %d" % (i, len(teile))) if mehrere \\
            else "ABGELEGTER INHALT"
        stuecke.append(_inhaltsblock(nonce, marke, t))''', '''    mehrere = len(teile) > 1
    for i, t in enumerate(teile, 1):
        marke = ("ABGELEGTER INHALT %d von %d" % (i, len(teile))) if mehrere \\
            else "ABGELEGTER INHALT"
        stuecke.append(_inhaltsblock(nonce, marke, t))

    for i, t in enumerate(referenzen, 1):
        marke = ("REFERENZ DER ABLAGE %d von %d" % (i, len(referenzen))) \\
            if len(referenzen) > 1 else "REFERENZ DER ABLAGE"
        stuecke.append(_inhaltsblock(nonce, marke, t))'''))
probe("Bestand meldet bei einer Frage 'kein Inhalt'", "py",
      (RUN, "    if not zeilen and frage:", "    if False:"))
probe("Referenzen werden beim Lauf nicht geladen", "py",
      (RUN, '''        refs = await asyncio.to_thread(
            referenz_teile, dump, j.get("owner_roh") or j.get("owner") or "")''',
            '''        refs = []'''))
probe("Referenzen gelten NICHT als schon geliefert", "py",
      (RUN, '''        text, chips = await _lauf(j, dump, auftrag, j["_teile"] + refs)''',
            '''        text, chips = await _lauf(j, dump, auftrag, j["_teile"])'''))
probe("Referenzen werden bei jedem Lauf erneut gemeldet", "py",
      (RUN, '''        await _injektion_pruefen(j, j["_teile"] + (''',
            '''        await _injektion_pruefen(j, j["_teile"] + refs + ('''))
probe("Referenzbudget gilt nicht je Datei", "py",
      (RUN, "    je_datei = max(REF_TEXT_MIN, REF_TEXT_MAX // len(pfade))",
            "    je_datei = TEXT_MAX"))

# ── Endpunkte ───────────────────────────────────────────────────────────────
probe("Frage ohne eingeschaltetes Fragefeld angenommen", "py",
      (MAIN, '''    if not dump.get("fragen"):''', '''    if False:'''))
probe("Referenz-Upload mit blossem Benutzungsrecht", "py",
      (MAIN, '''    if not dump or not _st.darf_aendern(dump, user, ist_admin):
        # 404 auch fuer eine fremde Ablage – kein Existenz-Orakel.''',
            '''    if not dump or not _st.darf_benutzen(dump, user):
        # 404 auch fuer eine fremde Ablage – kein Existenz-Orakel.'''))
probe("zu lange Frage wird gekuerzt statt abgewiesen", "py",
      (MAIN, '''    if len(frage) > _st.FRAGE_MAX:
        return JSONResponse({"ok": False, "error":
                             "Die Frage ist zu lang (hoechstens %d Zeichen)."
                             % _st.FRAGE_MAX}, status_code=400)''',
            '''    frage = frage[:_st.FRAGE_MAX]'''))
probe("Referenz-Upload ohne Magie-Byte-Pruefung", "py",
      (MAIN, '''        grund = _anhang_ausfuehrbar(endung, f.content_type or "", daten)
        if grund:
            abgewiesen.append({"name": name, "grund": grund})
            continue
        try:
            info = await''', '''        try:
            info = await'''))

# ── Sandbox ─────────────────────────────────────────────────────────────────
probe("Verzeichnis nicht in _APP_DENY_REL", "py",
      (SB, '''    "data/short_tracks_ref",
    # Claude Subagent''', '''    # Claude Subagent'''))
probe("Verzeichnis nicht in PRIVATE_DIRS", "py",
      (SB, '''                # Referenzdateien der Short-Tracks-Ablagen (siehe _APP_DENY_REL)
                "data/short_tracks_ref",\n''', ""))
probe("Verzeichnis nicht in SHELL_SECRET_PATHS", "py",
      (SB, "    r'short_tracks_ref\\b|'\n", ""))

# ── Oberflaeche ─────────────────────────────────────────────────────────────
probe("Fragefeld auch ohne eingeschalteten Schalter", "js",
      (TJ, "                ((d.fragen && d.enabled)", "                ((d.enabled)"))
probe("Feld wird VOR der Annahme geleert", "js",
      (TJ, '''        if (knopf) knopf.disabled = true;
        toast(T('tracks.ask_sending''', '''        feld.value = '';
        if (knopf) knopf.disabled = true;
        toast(T('tracks.ask_sending'''),
      (TJ, '''            .then(function () {
                feld.value = '';
                toast(T('tracks.ask_queued''', '''            .then(function () {
                toast(T('tracks.ask_queued'''))
probe("Umschalt+Enter sendet ebenfalls", "js",
      (TJ, "                if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {",
           "                if (ev.key === 'Enter' && !ev.isComposing) {"))
probe("leere Frage wird gesendet", "js",
      (TJ, '''        if (!frage) {
            toast(T('tracks.ask_empty''', '''        if (false) {
            toast(T('tracks.ask_empty'''))
probe("Speichern sendet `fragen` nicht", "js",
      (TJ, "            enabled: $('st-f-enabled').checked,\n            fragen: $('st-f-fragen').checked\n",
           "            enabled: $('st-f-enabled').checked\n"))
probe("Haken wird nicht vorbelegt", "js",
      (TJ, "        $('st-f-fragen').checked = !!d.fragen;", "        $('st-f-fragen').checked = false;"))
probe("Referenzname auf der Karte nicht escaped", "js",
      (TJ, "                              esc((d.referenzen || []).map(function (r) { return r.name; }).join(', ')) +",
           "                              ((d.referenzen || []).map(function (r) { return r.name; }).join(', ')) +"))
probe("Loeschen ohne Rueckfrage", "js",
      (TJ, '''        if (!window.confirm(T('tracks.refs_del_ask''', '''        if (false && !window.confirm(T('tracks.refs_del_ask'''))
probe("Name im Loeschpfad nicht kodiert", "js",
      (TJ, "'/refs/' + encodeURIComponent(name),", "'/refs/' + name,"))
probe("neue Ablage bietet schon einen Upload an", "js",
      (TJ, "        if (!_editId || _editId === 'neu') {", "        if (!_editId) {"))
probe("Referenzliste wird nach dem Neuladen nicht neu gezeichnet", "js",
      (TJ, "        if (_editId && $('st-f-refs')) zeichneRefs();", ""))
probe("Deckel sperrt den Upload-Knopf nicht", "js",
      (TJ, "(refs.length >= max ? ' disabled' : '')", "''"))
probe("Frage: Takt vor dem Laden gewaehlt (Altstand)", "js",
      (TJ, "                ladeJobs().then(takt);\n            })\n            .catch(function (e) { toast(e.message, true); })\n            .then(function () { if (knopf) knopf.disabled = false; });",
           "                ladeJobs();\n                takt();\n            })\n            .catch(function (e) { toast(e.message, true); })\n            .then(function () { if (knopf) knopf.disabled = false; });"))
probe("Drop: Takt vor dem Laden gewaehlt (Altstand)", "js",
      (TJ, "        // entscheidet takt() an der alten Liste (Begruendung in stelleFrage).\n        ladeJobs().then(takt);",
           "        // entscheidet takt() an der alten Liste (Begruendung in stelleFrage).\n        ladeJobs();\n        takt();"))
probe("Ergebnis wird direkt ins Dokument gerendert (Filter zu spaet)", "js",
      (TJ, """        var tpl = document.createElement('template');
        tpl.innerHTML = lib.renderMarkdown(String(text || '').replace(_ZEICHEN_ZAUN, '```text'));
        tpl.content.querySelectorAll('img')""",
           """        el.innerHTML = lib.renderMarkdown(String(text || '').replace(_ZEICHEN_ZAUN, '```text'));
        var tpl = { content: document.createDocumentFragment() };
        el.querySelectorAll('img')"""))
probe("fremde Bilder werden nicht ausgefiltert", "js",
      (TJ, "            if (/^\\/(?!\\/)/.test(src) || /^data:image\\//i.test(src)) return;",
           "            return;"))
probe("`//host` gilt als eigener Pfad", "js",
      (TJ, "            if (/^\\/(?!\\/)/.test(src) || /^data:image\\//i.test(src)) return;",
           "            if (/^\\//.test(src) || /^data:image\\//i.test(src)) return;"))
probe("Diagramm-Bloecke werden nicht als Code gezeigt", "js",
      (TJ, "        tpl.innerHTML = lib.renderMarkdown(String(text || '').replace(_ZEICHEN_ZAUN, '```text'));",
           "        tpl.innerHTML = lib.renderMarkdown(String(text || ''));"))
probe("Protokoll rendert nicht", "js",
      (TJ, "                if (x) setzeErgebnis(el, x.ergebnis);", "                if (x) el.textContent = x.ergebnis;"))
probe("Ergebnis wieder als Rohtext", "js",
      (TJ, "            if (j.ergebnis) setzeErgebnis(z.querySelector('[data-ergebnis]'), j.ergebnis);",
           "            if (j.ergebnis) z.querySelector('[data-ergebnis]').textContent = j.ergebnis;"))
probe("englischer Schluessel fehlt", "js",
      (I18, "        'tracks.ask_btn':               'Ask',\n", ""))
probe("Hilfetext verschweigt, dass Benutzer den Inhalt erfahren", "js",
      (I18, "<li><b>Wer die Ablage benutzen darf, erfährt den Inhalt der Referenzen</b> – über seine Fragen. Lege nur ab, was alle Benutzer dieser Ablage sehen dürfen.</li>", ""),
      (TJ, "'<ul><li><b>Wer die Ablage benutzen darf, erfährt den Inhalt der Referenzen</b> – über seine Fragen. Lege nur ab, was alle Benutzer dieser Ablage sehen dürfen.</li>' +",
           "'<ul>' +"))


# ── Ablauf ──────────────────────────────────────────────────────────────────
# Regel statt gepflegter Liste: jede sabotierte Datei muss in den Wegwerf-Baum
# kopiert werden, sonst traefe die Probe nichts (Register).
_kopiert = {"backend/"} | set(FRONT)
for name, wer, aend in PROBEN:
    for rel, _a, _n in aend:
        if not (rel.startswith("backend/") or rel in FRONT):
            print("ABBRUCH: Probe '%s' sabotiert %s, das nicht kopiert wird" % (name, rel))
            sys.exit(2)

basis = baum()
try:
    for wer in ("py", "js"):
        code, fails, bilanz = lauf(basis, wer)
        if code != 0 or fails != 0 or not bilanz:
            print("ABBRUCH: Basis ist nicht gruen (%s: exit=%s FAIL=%s Bilanz=%s)"
                  % (wer, code, fails, bilanz))
            sys.exit(2)
finally:
    shutil.rmtree(basis, ignore_errors=True)
print("Basis gruen in beiden Waechtern (Wegwerf-Baum)\n")

stumm, abgestuerzt = [], []
for name, wer, aend in PROBEN:
    w = baum()
    try:
        for rel, alt, neu in aend:
            patch(w, rel, alt, neu)
        code, fails, bilanz = lauf(w, wer)
    finally:
        shutil.rmtree(w, ignore_errors=True)
    if code == 1 and bilanz and fails > 0:
        print("  BEISST  %-62s %d FAIL" % (name, fails))
    elif not bilanz or code not in (0, 1):
        abgestuerzt.append(name)
        print("  ABSTURZ %-62s exit=%s (kein Biss)" % (name, code))
    else:
        stumm.append(name)
        print("  STUMM   %-62s" % name)

print("\n%d Proben: %d beissen, %d stumm, %d abgestuerzt"
      % (len(PROBEN), len(PROBEN) - len(stumm) - len(abgestuerzt),
         len(stumm), len(abgestuerzt)))
sys.exit(1 if (stumm or abgestuerzt) else 0)
