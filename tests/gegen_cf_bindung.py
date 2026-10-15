#!/usr/bin/env python3
"""Gegenproben zur dynamischen Confluence-Einbindung (Baum + Abgleich, 2026-09-27).

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der zustaendige
Waechter das meldet. Eine Probe, die nicht beisst, ist ein Testmangel – kein
Beweis (oder die Zusage gibt es gar nicht; dann gehoert die Probe gestrichen,
nicht der Waechter geschaerft).

DREI REGELN AUS DEM REGISTER, hier als CODE statt als Vorsatz:

* **Jede angefasste Datei steht in der Sicherung** – geprueft, nicht gepflegt
  (Exit 2, sonst laesst ein Abbruch einen Rueckstand im Arbeitsbaum liegen).
* **Laufmarke**: nach einem `kill -9` nimmt der naechste Start den Rueckstand
  selbst zurueck; beim geordneten Ende wird sie abgeraeumt, damit ein spaeterer
  Lauf keine veraltete Sicherung herstellt.
* **Gruener Basislauf ist Bedingung** – ohne ihn ist keine Gegenprobe deutbar.

Gemessen wird EXIT-CODE **und** Bilanzzeile: ein Lauf, der ohne Bilanz
abbricht, ist von "bestanden" nicht zu unterscheiden.
"""
from __future__ import annotations

import atexit
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-cf-bindung"
MARKE = ABL / "LAUF"

DATEIEN = [
    "backend/confluence_bindung.py",
    "backend/confluence_abgleich.py",
    "backend/confluence_client.py",
    "backend/main.py",
    "backend/sandbox.py",
    "backend/scheduler.py",
    "frontend/wissen.html",
    "frontend/js/wissen.js",
    "frontend/js/i18n.js",
]

PY_W = [sys.executable, str(ROOT / "tests" / "test_cf_bindung.py")]
CA_W = [sys.executable, str(ROOT / "tests" / "test_cf_abgleich.py")]
JS_W = ["node", str(ROOT / "tests" / "test_cf_bindung_ui.js")]


# ── Sicherung ───────────────────────────────────────────────────────────────
def sichern() -> None:
    ABL.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABL / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)
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


# Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
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


# ── Proben ──────────────────────────────────────────────────────────────────
CFB = "backend/confluence_bindung.py"
CFA = "backend/confluence_abgleich.py"
CCL = "backend/confluence_client.py"
MAIN = "backend/main.py"
SB = "backend/sandbox.py"
SCH = "backend/scheduler.py"
HTML = "frontend/wissen.html"
WJS = "frontend/js/wissen.js"
I18N = "frontend/js/i18n.js"

def _tausche_bloecke(s: str) -> str:
    """Vertauscht den Einbindungs-Container mit dem Block "Mein Wissen".

    Findet die Funktion ihre Marken nicht, gibt sie den Text unveraendert
    zurueck; der Aufrufer wertet das als unbrauchbare Probe."""
    a = s.find("        <!-- Dynamische Confluence-Einbindung.")
    b = s.find("        <!-- Mein Wissen -->")
    e = s.find("    </div>\n\n    <script src=", b if b > 0 else 0)
    if not (0 < a < b < e):
        return s
    return s[:a] + s[b:e] + s[a:b] + s[e:]


def _tags_hinter_baum(s: str) -> str:
    """Verschiebt das Tag-Feld (samt Hinweis) HINTER den Baum."""
    a = s.find("            <!-- Tags (Vorgabe 2026-09-27)")
    b = s.find("</p>\n", s.find('data-i18n="wissen.cfb_tags_hint"', a if a > 0 else 0))
    t = s.find('            <div class="wi-cf-tree wi-cfb-tree" id="wi-cfb-tree"')
    te = s.find("\n", t)
    if not (0 < a < b < t < te):
        return s
    b += len("</p>\n")
    return s[:a] + s[b:te + 1] + s[a:b] + s[te + 1:]


PROBEN = [
    # ── Ablage (confluence_bindung) ─────────────────────────────────────────
    ("Zweig ist nicht mehr automatisch markierte Seite", CFB,
     "        for z in zweige:\n            if z not in seiten:\n                seiten.append(z)\n", "", PY_W),
    ("ganz per Falsyness statt is True", CFB,
     '        ganz = el.get("ganz") is True\n', '        ganz = bool(el.get("ganz"))\n', PY_W),
    ("Wissensgruppen-Pflicht an der Ablage weg", CFB,
     '    if not aus:\n        raise BindungFehler("Bitte mindestens eine Wissensgruppe zuordnen.")\n', "", PY_W),
    ("Anzeigename aus dem Rumpf gewinnt", CFB,
     "        name = (namen or {}).get(k) if namen else None\n", "        name = None\n", PY_W),
    ("Altbestand: 'inkl. Unterseiten' wird ignoriert", CFB,
     '        ganz = c.get("inkl_unter") is True\n', "        ganz = False\n", PY_W),
    ("Bearbeiten ueberschreibt das Anlagedatum", CFB,
     '                    "angelegt": b.get("angelegt") or "",\n',
     '                    "angelegt": datetime.now().isoformat(timespec="seconds"),\n', PY_W),
    ("zu langer Schluessel wird gekuerzt statt abgewiesen", CFB,
     "        if len(k) > KEY_MAX or not _KEY_RE.match(k):\n            raise BindungFehler(\"Der Bereichs-Schluessel",
     "        if not _KEY_RE.match(k[:KEY_MAX]):\n            raise BindungFehler(\"Der Bereichs-Schluessel", PY_W),
    ("Seitenkennung wird nicht mehr geprueft", CFB,
     "        if len(k) > SEITE_MAX or not _SEITE_RE.match(k):\n", "        if False:\n", PY_W),

    # ── Endpunkte (main.py) ─────────────────────────────────────────────────
    ("unsichtbarer Bereich wird angenommen", MAIN, "    if fremd:\n", "    if False:\n", PY_W),
    ("PUT verliert fremde Wissensgruppen", MAIN,
     "    gruppen = list(req_groups) + [g for g in (alt.get(\"gruppen\") or [])\n"
     "                                  if g not in eigene and g not in req_groups]\n",
     "    gruppen = list(req_groups)\n", PY_W),
    ("Gruppenpruefung gegen den eigenen Bereich weg", MAIN,
     '    req_groups = _gruppen_normieren(body.get("groups"))\n    ok, err = _wissen_check_groups(user, req_groups)\n',
     '    req_groups = _gruppen_normieren(body.get("groups"))\n    ok, err = True, ""\n', PY_W),
    ("Namen vom Server werden nicht uebergeben", MAIN,
     "        eintrag = _cfb.hinzufuegen(auswahl, _display_name(user), req_groups, namen, tags)\n",
     "        eintrag = _cfb.hinzufuegen(auswahl, _display_name(user), req_groups, None, tags)\n", PY_W),
    ("Liste traegt kein Abgleichsergebnis mehr", MAIN,
     '        c["abgleich"] = staende.get(c.get("id") or "")\n', "", PY_W),
    ("eigene Gruppen als dicts statt Kennungen", MAIN,
     '    eigene = {g.get("id") for g in (_editable_groups_for(user) or []) if isinstance(g, dict)}\n',
     '    eigene = set(str(g) for g in (_editable_groups_for(user) or []))\n', PY_W),

    # ── Sperrlisten ─────────────────────────────────────────────────────────
    ("Abgleichsstand faellt aus _APP_DENY_REL", SB,
     '\n    "data/confluence_bindung.json", "data/confluence_abgleich.json",\n',
     '\n    "data/confluence_bindung.json",\n', PY_W),
    ("Abgleichsstand faellt aus dem Shell-Muster", SB,
     "    r'confluence_bindung\\.json\\b|confluence_abgleich\\.json\\b|'\n",
     "    r'confluence_bindung\\.json\\b|'\n", PY_W),

    # ── Abgleich ────────────────────────────────────────────────────────────
    ("⚠ ein fehlgeschlagener Abruf LOESCHT", CFA,
     '        if (alt.get("space") or "") in gescheitert:\n            seiten_neu[pid] = alt\n            continue\n',
     "", CA_W),
    ("Versionsaenderung wird nicht erkannt", CFA,
     'int(alt.get("v") or -1) == g["version"]\n                   and ', "", CA_W),
    ("Zweig nimmt die Nachfahren nicht mit", CFA,
     "            aus |= _nachfahren(kinder, z)\n", "", CA_W),
    ("ganzer Bereich wird ignoriert", CFA,
     '    if sel.get("ganz") is True:\n        return set(ids)\n', "", CA_W),
    ("fremde Seitenkennung wird durchgelassen", CFA,
     '    aus = {s for s in (sel.get("seiten") or []) if s in ids}\n',
     '    aus = set(sel.get("seiten") or [])\n', CA_W),
    ("Skill aus: der Abgleich laeuft trotzdem", CFA,
     '    if not ok:\n        return {**leer, "grund": grund}\n', "    if not ok:\n        pass\n", CA_W),
    ("kein Deckel je Takt", CFA, "        if abrufe >= MAX_ABRUFE_JE_LAUF:\n", "        if False:\n", CA_W),
    ("Gruppen zweier Eintraege werden ueberschrieben statt vereinigt", CFA,
     '                for gid in gruppen:           # mehrere Eintraege: Gruppen vereinigen\n'
     '                    if gid not in g["gruppen"]:\n                        g["gruppen"].append(gid)\n',
     '                g["gruppen"] = list(gruppen)\n', CA_W),
    ("kaputter Stand: weiter mit leerem Stand", CFA,
     '        raise RuntimeError(f"Stand {p} nicht lesbar ({type(e).__name__}: {e})") from e\n',
     '        return {"version": 1, "seiten": {}, "eintraege": {}}\n', CA_W),
    ("Zuordnung der Wissensgruppe wird nicht gesetzt", CFA,
     '                kg.set_assignment(rel, g["gruppen"])\n', "                pass\n", CA_W),
    ("Eintrag ohne Wissensgruppe wird trotzdem abgeglichen", CFA,
     "        if not gruppen:\n", "        if False:\n", CA_W),
    ("geloeschte Seite behaelt ihre Datei", CFA,
     '        _datei_weg(alt.get("datei") or "")\n        entfernt += 1\n', "        entfernt += 1\n", CA_W),
    ("Abgleich nutzt eine eigene Aktiv-Regel", CFA,
     "        from backend.main import _cfb_aktiv\n        skill, conf = _cfb_aktiv()\n",
     "        skill, conf = True, True\n", PY_W),

    # ── Cron-Auftrag ────────────────────────────────────────────────────────
    ("⚠ Index VOR Confluence (Aenderung liegt einen Takt brach)", SCH,
     "                cf = await asyncio.to_thread(confluence_abgleich.lauf)\n"
     "                erg = await asyncio.to_thread(rag_autoindex.lauf)\n",
     "                erg = await asyncio.to_thread(rag_autoindex.lauf)\n"
     "                cf = await asyncio.to_thread(confluence_abgleich.lauf)\n", CA_W),
    ("Confluence wird im Auftrag gar nicht gerufen", SCH,
     "                cf = await asyncio.to_thread(confluence_abgleich.lauf)\n", "                cf = {}\n", CA_W),

    # ── Markup ──────────────────────────────────────────────────────────────
    ("Container rutscht hinter 'Mein Wissen'", HTML, _tausche_bloecke, None, PY_W),
    ("Pulldown kommt zurueck", HTML,
     '            <div class="wi-cf-tree wi-cfb-tree" id="wi-cfb-tree"',
     '            <select id="wi-cfb-space"></select>\n            <div class="wi-cf-tree wi-cfb-tree" id="wi-cfb-tree"', PY_W),
    ("Warnung 'noch nicht produktiv' kommt zurueck", HTML,
     '            <p class="desc" data-i18n="wissen.cfb_sync_hint">',
     '            <p class="desc wi-cfb-soon" data-i18n="wissen.cfb_soon">x</p>\n            <p class="desc" data-i18n="wissen.cfb_sync_hint">', PY_W),
    ("Rueckfall-Markup des Abgleich-Hinweises weicht von DE ab", HTML,
     '<p class="desc" data-i18n="wissen.cfb_sync_hint">Gespeicherte Einträge',
     '<p class="desc" data-i18n="wissen.cfb_sync_hint">Alte Einträge', PY_W),
    ("Knopf startet frei", HTML,
     '                        data-i18n="wissen.cfb_add" disabled>Übernehmen</button>',
     '                        data-i18n="wissen.cfb_add">Übernehmen</button>', PY_W),

    # ── Oberflaeche (wissen.js) ─────────────────────────────────────────────
    ("⚠ [-] laesst die Unterbereiche markiert", WJS,
     "            cfbOeffnen(li, false);\n            cfbUnten(li, false);\n",
     "            cfbOeffnen(li, false);\n", JS_W),
    ("⚠ [+] markiert die Unterbereiche nicht", WJS,
     "            cfbUnten(li, true);\n            cfbOeffnen(li, true);\n",
     "            cfbOeffnen(li, true);\n", JS_W),
    ("[+] markiert den Eintrag selbst nicht", WJS,
     "            var cb = cfbCb(li); if (cb) cb.checked = true;\n", "", JS_W),
    ("⚠ der Name markiert beim Aufklappen", WJS,
     "        return fertig.then(function () { cfbOeffnen(li, true); }, function () {});",
     "        return fertig.then(function () { cfbOeffnen(li, true); cfbUnten(li, true); }, function () {});", JS_W),
    ("⚠ ein Haken zieht die Unterbereiche mit", WJS,
     "                if (ev.target.classList && ev.target.classList.contains('wi-cfb-cb')) cfbMarken();",
     "                if (ev.target.classList && ev.target.classList.contains('wi-cfb-cb')) { cfbUnten(ev.target.closest('li'), ev.target.checked); cfbMarken(); }", JS_W),
    ("ganzer Bereich geht nie als ganz raus", WJS,
     "ganz: cfbKomplett(li) && (li._cfbZahl || 0) > 0,", "ganz: false,", JS_W),
    ("ein Blatt zaehlt als Zweig", WJS,
     "if (cfbKind(pg, 'wi-cf-kids') && cfbKomplett(pg)) zweige.push(id);",
     "if (!cfbKind(pg, 'wi-cf-kids') || cfbKomplett(pg)) zweige.push(id);", JS_W),
    ("Wissensgruppen gehen nicht mit", WJS,
     "body: JSON.stringify({ auswahl: auswahl, groups: grp, tags: cfbTagsLesen() })",
     "body: JSON.stringify({ auswahl: auswahl, tags: cfbTagsLesen() })", JS_W),
    ("⚠ Bearbeiten legt einen NEUEN Eintrag an", WJS,
     "method: edit ? 'PUT' : 'POST'", "method: 'POST'", JS_W),
    ("Baum bleibt nach dem Uebernehmen markiert", WJS,
     "              cfbEditModus(null);\n              cfbBaumLeeren();\n              cfbRender();\n",
     "              cfbEditModus(null);\n              cfbRender();\n", JS_W),
    ("Baum wird bei jedem Render neu gezeichnet", WJS,
     "        if (_cfbBaumFuer === _cfSpaces && tree.querySelector('.wi-cfb-sp')) { cfbAddKnopf(); return; }\n",
     "", PY_W),
    ("Knopf frei ohne Wissensgruppe", WJS,
     "        btn.disabled = !!laeuft || _cfbLaeuft || !n || !grp;\n",
     "        btn.disabled = !!laeuft || _cfbLaeuft || !n;\n", JS_W),
    ("nicht ladbarer Bereich verliert beim Bearbeiten seine Auswahl", WJS,
     "                if (li._cfbVorher && cb && cb.checked === !!li._cfbVorher.start) {\n"
     "                    aus.push(li._cfbVorher);\n                } else if",
     "                if (false) {\n                } else if", JS_W),
    ("die Suche versteckt markierte Bereiche", WJS,
     "            var drin = !q || li.getAttribute('data-such').indexOf(q) !== -1\n"
     "                || (cb && (cb.checked || cb.indeterminate));\n",
     "            var drin = !q || li.getAttribute('data-such').indexOf(q) !== -1;\n", JS_W),
    ("gespeicherte Seiten werden beim Bearbeiten nicht angehakt", WJS,
     "                    if ((a.seiten || []).indexOf(id2) !== -1) { var c = cfbCb(pg); if (c) c.checked = true; }\n",
     "", JS_W),
    ("Abgleichsergebnis fehlt in der Zeile", WJS, "                + cfbSyncZeile(b)\n", "", JS_W),
    ("Eintrag ohne Gruppe wird nicht benannt", WJS, "            if (!gi.length) {\n", "            if (false) {\n", JS_W),
    ("kein Muelleimer mehr, sondern ×", WJS,
     "esc(t('wissen.cfb_del')) + '\">' + JarvisIcons.trash() + '</button>'",
     "esc(t('wissen.cfb_del')) + '\">×</button>'", JS_W),
    ("Fehlschlag verwirft die Markierung", WJS,
     "                  cfbStatus('⚠️ ' + ((d && d.error) || t('wissen.cfb_err')), true);\n                  cfbAddKnopf();\n",
     "                  cfbStatus('⚠️ ' + ((d && d.error) || t('wissen.cfb_err')), true);\n                  cfbBaumLeeren();\n", JS_W),

    # ── i18n ────────────────────────────────────────────────────────────────
    ("EN-Schluessel fehlt", I18N, "        'wissen.cfb_save': 'Save',\n", "", PY_W),

    # ── Tags je Eintrag (Vorgabe 2026-09-27) ────────────────────────────────
    ("Tags werden nicht klein geschrieben", CFB,
     '        k = t.strip().lstrip("#").strip().lower()\n', '        k = t.strip().lstrip("#").strip()\n', PY_W),
    ("Tag mit Leerraum/Trenner wird angenommen", CFB,
     "        if len(k) > TAG_MAX or _TAG_BOESE_RE.search(k):\n", "        if len(k) > TAG_MAX:\n", PY_W),
    ("zu langer Tag wird angenommen", CFB,
     "        if len(k) > TAG_MAX or _TAG_BOESE_RE.search(k):\n", "        if _TAG_BOESE_RE.search(k):\n", PY_W),
    ("ein String wird Zeichen fuer Zeichen zu Tags", CFB,
     "    if isinstance(tags, (str, bytes)) or not isinstance(tags, (list, tuple)):\n",
     "    if not isinstance(tags, (list, tuple, str)):\n", PY_W),
    ("hinzufuegen legt die Tags nicht ab", CFB,
     '            "tags": tg,\n            "angelegt": jetzt,\n', '            "angelegt": jetzt,\n', PY_W),
    ("aendern behaelt die alten Tags", CFB,
     '                    "tags": tg,\n                    "angelegt": b.get("angelegt") or "",\n',
     '                    "tags": b.get("tags") or [],\n                    "angelegt": b.get("angelegt") or "",\n', PY_W),
    ("⚠ kaputte Tag-Angabe wird zu 'kein Filter'", CFB,
     '        c["tags_ungueltig"] = True\n', "", CA_W),
    ("Tags werden im Endpunkt nicht geprueft", MAIN,
     '        tags = _cfb._tags_pruefen(body.get("tags"))\n', '        tags = body.get("tags")\n', PY_W),
    ("POST speichert die Tags nicht", MAIN,
     "        eintrag = _cfb.hinzufuegen(auswahl, _display_name(user), req_groups, namen, tags)\n",
     "        eintrag = _cfb.hinzufuegen(auswahl, _display_name(user), req_groups, namen)\n", PY_W),
    ("PUT speichert die Tags nicht", MAIN,
     "        eintrag = _cfb.aendern(bid, auswahl, _display_name(user), gruppen, namen, tags)\n",
     "        eintrag = _cfb.aendern(bid, auswahl, _display_name(user), gruppen, namen)\n", PY_W),
    ("⚠ der Abgleich ignoriert die Tags", CFA,
     "            ids = tags_filtern(seiten_der_auswahl(sel, liste, st), liste, tags)\n",
     "            ids = seiten_der_auswahl(sel, liste, st)\n", CA_W),
    ("⚠ unbekannte Labels gelten als 'kein Tag' (loescht Wissen)", CFA,
     "        if lab is None:\n            return None\n", "        if lab is None:\n            continue\n", CA_W),
    ("Tag-Vergleich achtet auf Gross-/Kleinschreibung", CFA,
     "    gesucht = {str(t).lower() for t in (tags or []) if t}\n",
     "    gesucht = {str(t) for t in (tags or []) if t}\n", CA_W),
    ("Labels werden nie verlangt", CFA,
     '    mit_labels = any(e.get("tags") for e in eintraege)\n', "    mit_labels = False\n", CA_W),
    ("Labels werden immer verlangt (Abruf ohne Tags veraendert)", CFA,
     '    mit_labels = any(e.get("tags") for e in eintraege)\n', "    mit_labels = True\n", CA_W),
    ("kaputte Tags: Eintrag wird ungefiltert abgeglichen", CFA,
     '        if e.get("tags_ungueltig"):\n', "        if False:\n", CA_W),
    ("⚠ Client: fehlende metadata wird zu 'keine Labels'", CCL,
     "                        if isinstance(lab, dict) else None)\n", "                        if isinstance(lab, dict) else [])\n", CA_W),
    ("Client: Labels nicht klein geschrieben", CCL,
     '                        [str(x.get("name") or "").strip().lower()\n',
     '                        [str(x.get("name") or "").strip()\n', CA_W),
    ("Client: expand verlangt die Labels nicht", CCL,
     '("metadata.labels", with_labels)', '("metadata.labels", False)', CA_W),
    ("Tag-Feld steht HINTER dem Baum", HTML, _tags_hinter_baum, None, JS_W),
    ("Rueckfall-Markup des Tag-Hinweises weicht von DE ab", HTML,
     '<p class="desc" data-i18n="wissen.cfb_tags_hint">Nur Seiten,',
     '<p class="desc" data-i18n="wissen.cfb_tags_hint">Alle Seiten,', PY_W),
    ("Tags gehen nicht mit", WJS,
     "body: JSON.stringify({ auswahl: auswahl, groups: grp, tags: cfbTagsLesen() })",
     "body: JSON.stringify({ auswahl: auswahl, groups: grp })", JS_W),
    ("Tags nur an Komma getrennt", WJS,
     "        return String((el && el.value) || '').split(/[\\s,;]+/)",
     "        return String((el && el.value) || '').split(/,/)", JS_W),
    ("⚠ Tag-Feld wird nach dem Eintrag nicht geleert", WJS,
     "        if (tg) tg.value = b ? (b.tags || []).join(', ') : '';\n",
     "        if (tg && b) tg.value = (b.tags || []).join(', ');\n", JS_W),
    ("Bearbeiten fuellt die Tags nicht ein", WJS,
     "        if (tg) tg.value = b ? (b.tags || []).join(', ') : '';\n",
     "        if (tg && !b) tg.value = '';\n", JS_W),
    ("Liste nennt die Tags nicht", WJS,
     "                + ((b.tags || []).length\n", "                + ((b.tags || []).length && false\n", JS_W),
    ("⚠ Tags in der Liste unmaskiert", WJS,
     "                      + esc(t('wissen.cfb_sum_tags', { t: b.tags.join(', ') })) + '</div>'",
     "                      + t('wissen.cfb_sum_tags', { t: b.tags.join(', ') }) + '</div>'", JS_W),
    ("EN-Tag-Text fehlt", I18N, "        'wissen.cfb_tags_ph': 'e.g. handbook, approved',\n", "", PY_W),
]

# ── REGEL: jede angefasste Datei muss gesichert sein ────────────────────────
fremd = sorted({p[1] for p in PROBEN} - set(DATEIEN))
if fremd:
    print(f"⚠ Probe fasst ungesicherte Datei(en) an: {fremd} – Abbruch")
    sys.exit(2)

atexit.register(aufraeumen)
signal.signal(signal.SIGTERM, lambda *_: (aufraeumen(), sys.exit(143)))

sichern()

# ── Basislauf ───────────────────────────────────────────────────────────────
print("\033[1mBasislauf (muss gruen sein – sonst ist keine Probe deutbar)\033[0m")
basis_ok = True
for name, cmd in [("Backend/Regeln", PY_W), ("Abgleich", CA_W), ("Oberflaeche (jsdom)", JS_W)]:
    rc, aus = lauf(cmd)
    z = [l for l in aus.splitlines() if "Ergebnis:" in l]
    print(f"  {name}: rc={rc} {z[-1].strip() if z else '(keine Bilanz)'}")
    if rc != 0:
        basis_ok = False
if not basis_ok:
    print("\033[31m⚠ Basis ist NICHT gruen – Abbruch\033[0m")
    sys.exit(2)

# ── Proben ──────────────────────────────────────────────────────────────────
print(f"\n\033[1m{len(PROBEN)} Gegenproben\033[0m")
beissen = 0
stumm = []
for name, rel, alt, neu, cmd in PROBEN:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    # Trefferkontrolle: eine Ersetzung ohne Treffer ist kein Messwert. Fuer
    # Umbauten, die sich nicht als EIN Textersatz schreiben lassen (etwas
    # wirklich VERSCHIEBEN), darf `alt` eine Funktion sein – sie muss den Text
    # nachweislich aendern, sonst gilt die Probe als unbrauchbar.
    if callable(alt):
        s2 = alt(s)
        if s2 == s:
            print(f"  \033[33m⚠\033[0m {name}: SABOTAGE AENDERT NICHTS – Probe unbrauchbar")
            stumm.append(name + " (aendert nichts)")
            continue
    else:
        if s.count(alt) != 1:
            print(f"  \033[33m⚠\033[0m {name}: SABOTAGE TRIFFT NICHT ({s.count(alt)}x) – Probe unbrauchbar")
            stumm.append(name + " (trifft nicht)")
            continue
        s2 = s.replace(alt, neu, 1)
    p.write_text(s2, encoding="utf-8")
    try:
        gemeldet, info = bewerte(cmd)
    finally:
        zurueck()
    if gemeldet:
        beissen += 1
        print(f"  \033[32m✓\033[0m {name} → {info}")
    else:
        stumm.append(name)
        print(f"  \033[31m✗\033[0m {name} → BEISST NICHT ({info})")

# ── Kontrolle: der Arbeitsbaum ist wieder byte-gleich ───────────────────────
abweichend = [rel for rel in DATEIEN
              if (ROOT / rel).read_bytes() != (ABL / rel.replace("/", "__")).read_bytes()]
print(f"\n\033[1mErgebnis: {beissen}/{len(PROBEN)} Proben beissen\033[0m")
print(f"Arbeitsbaum wiederhergestellt: {'ja' if not abweichend else 'NEIN – ' + str(abweichend)}")
if stumm:
    print("Stumm: " + "; ".join(stumm))
sys.exit(1 if (stumm or abweichend) else 0)
