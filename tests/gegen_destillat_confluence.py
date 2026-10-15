#!/usr/bin/env python3
"""Gegenproben: Destillat als neue Confluence-Seite (Vorgabe 2026-09-29).

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob `test_destillat_confluence`
das meldet. Eine Probe, die nicht beisst, ist ein Testmangel – kein Beweis; und
wenn die Zusage gar nicht existiert, gehoert die Probe gestrichen, nicht der
Waechter geschaerft.

Gleiche drei Regeln wie im Nachbar-Harness, als Code statt als Vorsatz:
Sicherungsliste wird GEPRUEFT (Exit 2), Laufmarke nimmt einen Rueckstand nach
`kill -9` selbst zurueck, und ohne gruenen Basislauf ist keine Probe deutbar.
"""
from __future__ import annotations

import atexit
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-destillat-confluence"
MARKE = ABL / "LAUF"

WD = "backend/wissen_destillat.py"
MAIN = "backend/main.py"
HTML = "frontend/wissen.html"
JS = "frontend/js/wissen_destillat.js"
WJS = "frontend/js/wissen.js"
I18N = "frontend/js/i18n.js"
CLIENT = "backend/confluence_client.py"

DATEIEN = [WD, MAIN, HTML, JS, WJS, I18N, CLIENT]
W = [sys.executable, str(ROOT / "tests" / "test_destillat_confluence.py")]
UI = ["node", str(ROOT / "tests" / "test_destillat_cf_ui.js")]


def sichern() -> None:
    ABL.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABL / rel.replace("/", "__"))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck() -> None:
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


def aufraeumen() -> None:
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


if MARKE.exists():
    print("⚠ Rueckstand eines frueheren Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()


def lauf(cmd) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def bewerte(cmd) -> tuple[bool, str]:
    """(hat gemeldet?, Kurztext). Eine fehlende Bilanzzeile zaehlt als Meldung
    MIT Vorbehalt – sie bedeutet Abbruch, nicht Erfolg."""
    rc, aus = lauf(cmd)
    bilanz = [z for z in aus.splitlines() if "Ergebnis:" in z]
    if not bilanz:
        return True, "ABGEBROCHEN (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if "✗" in z)
    return (rc != 0), f"{bilanz[-1].strip()} / {fails} FAIL"


# ── Sabotagen, die mehr als eine Stelle brauchen ────────────────────────────

def _ausrichtung_weg(s: str) -> str:
    """Verworfene Bilder werden WEGGELASSEN statt als None gefuehrt.

    Genau der Fehler, den es beim Bau gab: jeder `[BILD-N]` hinter einem
    verworfenen Bild zeigt danach auf das falsche Bild – ohne Fehlermeldung.
    """
    a = ("        raus.append(None)\n"
         "        if genommen >= MAX_BILDER or gesamt >= MAX_BILDER_GESAMT:\n")
    b = "        raus[-1] = (f\"bild-{i}.{_MIME_ENDUNG.get(mime, 'png')}\", daten, mime)\n"
    if s.count(a) != 1 or s.count(b) != 1:
        return s
    s = s.replace(a, "        if genommen >= MAX_BILDER or gesamt >= MAX_BILDER_GESAMT:\n")
    return s.replace(
        b, "        raus.append((f\"bild-{i}.{_MIME_ENDUNG.get(mime, 'png')}\", daten, mime))\n")


def _toter_verweis(s: str) -> str:
    """Ein Marker OHNE Anhang bekommt trotzdem einen Verweis – auf der Seite
    steht dann ein defektes Bild statt eines lesbaren Hinweises."""
    a = ("        if 0 <= i < len(namen) and namen[i]:\n"
         "            bloecke.append('<ac:image><ri:attachment ri:filename=\"%s\" /></ac:image>'\n"
         "                           % _xesc(namen[i]))\n"
         "            return \"\\x00B%d\\x00\" % (len(bloecke) - 1)\n"
         "        return \"<em>(Bild %d – im Originaldokument enthalten)</em>\" % (i + 1)\n")
    if s.count(a) != 1:
        return s
    return s.replace(
        a,
        "        bloecke.append('<ac:image><ri:attachment ri:filename=\"bild-%d.png\" /></ac:image>'\n"
        "                       % (i + 1))\n"
        "        return \"\\x00B%d\\x00\" % (len(bloecke) - 1)\n")


def _endpunkt_zeile(alt: str, neu: str):
    """Sabotage-Fabrik fuer GENAU EINE Zeile im Confluence-Endpunkt.

    Die Zeilen stehen teils wortgleich in den Nachbar-Endpunkten – ein
    Textersatz ueber die ganze Datei traefe den falschen (Register).
    """
    def sab(s: str) -> str:
        a = s.find("async def wissen_destillat_confluence(")
        if a < 0:
            return s
        e = s.find("\n@app.", a)
        e = e if e > 0 else len(s)
        block = s[a:e]
        if block.count(alt) != 1:
            return s
        return s[:a] + block.replace(alt, neu) + s[e:]
    return sab


PROBEN = [
    # ── Die Vorgabe: der Inhalt geht als HTML raus ─────────────────────────
    ("⚠ Konverter gibt das rohe Markdown zurueck (Vorgabe verletzt)", WD,
     '    return re.sub(r"\\x00B(\\d+)\\x00", lambda m: bloecke[int(m.group(1))], s)',
     '    return str(markdown or "")', W),

    ("`<br>` statt XHTML `<br />` (Confluence lehnt den Rumpf ab)", WD,
     '            teile.append("<p>" + a.replace("\\n", "<br />") + "</p>")',
     '            teile.append("<p>" + a.replace("\\n", "<br>") + "</p>")', W),

    # ── Fremdtext ──────────────────────────────────────────────────────────
    ("⚠ Maskierung raus (Fremdtext kann Markup erzeugen)", WD,
     '    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")\n'
     '            .replace(">", "&gt;").replace(\'"\', "&quot;"))',
     '    return str(s or "")', W),

    ("Steuerzeichen bleiben stehen (XML wird ungueltig)", WD,
     '    s = _STEUER.sub("", str(markdown or ""))',
     '    s = str(markdown or "")', W),

    ("`javascript:` wird wieder verlinkt", WD,
     '    s = re.sub(r"\\[([^\\]]+)\\]\\((https?://[^)\\s]+)\\)",\n'
     '               r\'<a href="\\2">\\1</a>\', s)',
     '    s = re.sub(r"\\[([^\\]]+)\\]\\(([^)\\s]+)\\)",\n'
     '               r\'<a href="\\2">\\1</a>\', s)', W),

    # ── Blockelemente ──────────────────────────────────────────────────────
    ("Ueberschrift ohne Leerzeilen (der Absatz darunter geht verloren)", WD,
     '        s = re.sub(muster, "\\n<%s>\\\\1</%s>\\n" % (tag, tag), s, flags=re.M)',
     '        s = re.sub(muster, "<%s>\\\\1</%s>" % (tag, tag), s, flags=re.M)', W),

    ("Liste ohne Leerzeile danach", WD,
     '        return "\\n<%s>%s</%s>\\n\\n" % (tag, li, tag)',
     '        return "<%s>%s</%s>\\n" % (tag, li, tag)', W),

    # ── Bilder ─────────────────────────────────────────────────────────────
    ("⚠ Indexausrichtung der Bildmarker aufgehoben", WD, None,
     _ausrichtung_weg, W),

    ("Marker ohne Anhang bekommt einen TOTEN Verweis", WD, None,
     _toter_verweis, W),

    ("der behauptete MIME-Typ wird geglaubt (Fremdeingabe)", WD,
     "        mime = _bild_mime(daten)\n"
     "        if not mime or len(daten) > MAX_BILD_BYTES:",
     "        mime = m.group(1).lower()\n"
     "        if not mime or len(daten) > MAX_BILD_BYTES:", W),

    ("Deckel fuer die Einzelgroesse raus", WD,
     "        if not mime or len(daten) > MAX_BILD_BYTES:",
     "        if not mime:", W),

    # ── Endpunkt ───────────────────────────────────────────────────────────
    ("⚠ Rechte-Pruefung des Endpunkts stillgelegt", MAIN, None,
     _endpunkt_zeile("    if not _destillat_erlaubt(user):",
                     "    if False:"), W),

    ("Confluence-Zustand wird nicht mehr geprueft", MAIN, None,
     _endpunkt_zeile("    aktiv, konfiguriert = _cfb_aktiv()",
                     "    aktiv, konfiguriert = True, True"), W),

    ("⚠ Bereichs-Sichtbarkeit wird nicht mehr geprueft", MAIN, None,
     _endpunkt_zeile(
         "        sichtbar = {s.get(\"key\") for s in await _wissen_visible_spaces(c)}",
         "        sichtbar = {space}"), W),

    ("⚠ die Elternseite wird nicht mehr gegen den Bereich geprueft", MAIN, None,
     _endpunkt_zeile(
         "            seiten = await asyncio.to_thread(c.pages_in_space, space, _CF_MAX_SEITEN)",
         "            seiten = [{\"id\": parent}]"), W),

    ("⚠ es wird UEBERSCHRIEBEN statt angelegt", MAIN, None,
     _endpunkt_zeile(
         "        seite = await asyncio.to_thread(c.create_page, space, titel, storage, parent or None)",
         "        seite = await asyncio.to_thread(c.update_page, parent, storage, titel)"), W),

    ("der Titel wird gekuerzt statt abgewiesen", MAIN, None,
     _endpunkt_zeile(
         "    if len(titel) > _wd.TITEL_MAX:",
         "    titel = titel[:_wd.TITEL_MAX]\n    if False:"), W),

    ("das rohe Markdown geht als Seitenrumpf raus (kein HTML)", MAIN, None,
     _endpunkt_zeile("        storage = _wd.storage_aus_markdown(markdown, namen)",
                     "        storage = markdown"), W),

    ("Bilder werden gar nicht mehr angehaengt", MAIN, None,
     _endpunkt_zeile(
         "                await asyncio.to_thread(c.upload_attachment_bytes, seiten_id, name, daten, mime)",
         "                pass"), W),

    # ── Oberflaeche ────────────────────────────────────────────────────────
    ("⚠ CSS-Regel gegen das ueberschlagene hidden-Attribut raus", HTML,
     "        .wi-dest-actions .sec-btn[hidden] { display: none; }\n", "", W),

    ("der Container holt die Bereichsliste selbst (zweite Quelle)", JS,
     "    function cfKnopf() {",
     "    function cfSpacesSelbst() {\n"
     "        return fetch('/api/wissen/confluence/spaces', { headers: authH() });\n"
     "    }\n"
     "    function cfKnopf() {", W),

    ("Seitenhierarchie wird nachgebaut statt WissenPortal.cfBaum zu nutzen", JS,
     "        var bauen = (window.WissenPortal && window.WissenPortal.cfBaum) || null;",
     "        var bauen = function (ps) { return (ps || []).map(function (p) {\n"
     "            return { id: p.id, title: p.title, kids: [] }; }); };", W),

    ("i18n nur deutsch (ein EN-Schluessel fehlt)", I18N,
     "        'wissen.dest_cf_go': 'Create page',\n", "", W),

    # ── Verhalten (gegen den UI-Waechter, jsdom, geklickt statt gelesen) ───
    ("⚠ der Knopf steht auch ohne aktives Confluence da", JS,
     "        b.hidden = !cfAktiv;", "        b.hidden = false;", UI),

    ("ein bearbeiteter Titel wird beim Oeffnen ueberschrieben", JS,
     "        if (ti && !ti.dataset.beruehrt) ti.value = cfTitelVorschlag();",
     "        if (ti) ti.value = cfTitelVorschlag();", UI),

    ("„Seite anlegen\" ist nie gesperrt", JS,
     "        if (!space) { btn.disabled = true; btn.title = t('wissen.dest_cf_need_space'); return; }",
     "        if (!space) { btn.disabled = false; btn.title = ''; return; }", UI),

    ("der Sperrgrund ist der FALSCHE (fragt nach dem Titel statt dem Bereich)", JS,
     "        if (!space) { btn.disabled = true; btn.title = t('wissen.dest_cf_need_space'); return; }",
     "        if (!space) { btn.disabled = true; btn.title = t('wissen.dest_cf_need_title'); return; }", UI),

    ("die Einrueckung des Seitenbaums faellt weg (sieht flach aus)", JS,
     "                var ein = new Array(tiefe + 1).join('\\u00a0\\u00a0\\u00a0');",
     "                var ein = '';", UI),

    ("⚠ ein Bereichswechsel setzt die Elternseite NICHT mehr zurueck", JS,
     "        sel.innerHTML = '<option value=\"\">' + esc(t('common.loading')) + '</option>';\n"
     "        sel.disabled = true;\n",
     "        sel.disabled = true;\n", UI),

    ("ein neues Destillat setzt den Titel nicht zurueck", JS,
     "        if (ct) { delete ct.dataset.beruehrt; ct.value = ''; }",
     "        if (ct) { /* nichts */ }", UI),

    ("die neue Seite wird als Kennung statt als Link gezeigt", JS,
     "            html += ' <a href=\"' + esc(d.link) + '\" target=\"_blank\" rel=\"noopener noreferrer\">'\n"
     "                 + esc(d.title || '') + '</a>';",
     "            html += ' ' + esc(d.title || '');", UI),
]


def main() -> int:
    sichern()
    atexit.register(aufraeumen)

    # Die Sicherungsliste wird GEPRUEFT, nicht gepflegt: eine Probe auf eine
    # ungesicherte Datei liesse nach einem Abbruch einen Rueckstand liegen.
    unbekannt = {p[1] for p in PROBEN} - set(DATEIEN)
    if unbekannt:
        print(f"\033[31mABBRUCH: nicht gesichert: {sorted(unbekannt)}\033[0m")
        return 2

    print("\033[1mBasislauf\033[0m")
    for cmd, name in ((W, "Backend"), (UI, "UI")):
        rc, aus = lauf(cmd)
        bil = [z for z in aus.splitlines() if "Ergebnis:" in z]
        print(f"  {name}: {bil[-1].strip() if bil else 'KEINE BILANZ'}")
        if rc != 0:
            print(f"\033[31mABBRUCH: Basislauf {name} nicht gruen – "
                  "keine Gegenprobe deutbar\033[0m")
            return 2

    beisst = stumm = kaputt = 0
    print()
    for i, (name, datei, alt, neu, waechter) in enumerate(PROBEN, 1):
        pfad = ROOT / datei
        orig = pfad.read_text(encoding="utf-8")
        if callable(neu):
            sab = neu(orig)
            traf = sab != orig
        else:
            traf = orig.count(alt) == 1
            sab = orig.replace(alt, neu, 1) if traf else orig
        if not traf:
            # Eine Probe, die ihr Ziel verfehlt, ist ein PROBEN-Mangel – und
            # wird als solcher ausgewiesen, nicht als zahnloser Waechter.
            print(f"  \033[33m⚠\033[0m {i:2}. {name}\n"
                  f"        SABOTAGE TRIFFT NICHT ({datei}) – Probe unbrauchbar")
            kaputt += 1
            continue
        pfad.write_text(sab, encoding="utf-8")
        try:
            gemeldet, info = bewerte(waechter)
        finally:
            pfad.write_text(orig, encoding="utf-8")
        if gemeldet:
            beisst += 1
            print(f"  \033[32m✓\033[0m {i:2}. {name}\n        {info}")
        else:
            stumm += 1
            print(f"  \033[31m✗\033[0m {i:2}. {name}\n"
                  f"        \033[31mSTUMM\033[0m – {info}")

    print(f"\n\033[1mbeisst: {beisst}/{len(PROBEN)}"
          + (f", stumm: {stumm}" if stumm else "")
          + (f", unbrauchbar: {kaputt}" if kaputt else "") + "\033[0m")

    aufraeumen()
    rest = [r for r in DATEIEN
            if (ROOT / r).read_bytes() != (ABL / r.replace("/", "__")).read_bytes()]
    print("Arbeitsbaum wiederhergestellt: "
          + ("\033[32mja\033[0m" if not rest else f"\033[31mNEIN: {rest}\033[0m"))
    return 0 if (not stumm and not kaputt and not rest) else 1


if __name__ == "__main__":
    sys.exit(main())
