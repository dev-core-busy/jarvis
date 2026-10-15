#!/usr/bin/env python3
"""Gegenproben zum Wissens-Destillat (/wissen).

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der zustaendige
Waechter das meldet. Eine Probe, die nicht beisst, ist ein Testmangel – kein
Beweis. Und wenn die Zusage gar nicht existiert, gehoert die Probe gestrichen,
nicht der Waechter geschaerft.

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
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-wissen-destillat"
MARKE = ABL / "LAUF"

WD = "backend/wissen_destillat.py"
MAIN = "backend/main.py"
HTML = "frontend/wissen.html"
JS = "frontend/js/wissen_destillat.js"
WJS = "frontend/js/wissen.js"
I18N = "frontend/js/i18n.js"

DATEIEN = [WD, MAIN, HTML, JS, WJS, I18N]

PY_W = [sys.executable, str(ROOT / "tests" / "test_wissen_destillat.py")]
JS_W = ["node", str(ROOT / "tests" / "test_wissen_destillat_ui.js")]


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


def _container_verschieben(s: str) -> str:
    """Schiebt den Destillat-Container HINTER die Confluence-Einbindung.

    Damit stimmt die zugesicherte Reihenfolge nicht mehr. Findet die Funktion
    ihre Marken nicht, gibt sie den Text UNVERAENDERT zurueck – der Aufrufer
    wertet das als unbrauchbare Probe und nicht als bestandenen Waechter.
    """
    a = s.find("        <!-- Wissens-Destillat (Import aus")
    b = s.find("        <!-- Dynamische Confluence-Einbindung.")
    e = s.find("        <!-- Mein Wissen -->")
    if not (0 < a < b < e):
        return s
    return s[:a] + s[b:e] + s[a:b] + s[e:]


def _rechte_verschieben(s: str) -> str:
    """Schiebt die Rechte-Pruefung des Uebernehmen-Endpunkts HINTER das Lesen
    des Rumpfes. Sie steht dann noch da, aber an der falschen Stelle – genau
    diese Reihenfolge sichert der Waechter zu, und eine Textsuche saehe den
    Unterschied nicht."""
    block = ('    if not _destillat_erlaubt(user):\n'
             '        return JSONResponse({"error": "Dir ist kein Wissensbereich zugewiesen."},\n'
             '                            status_code=403)\n'
             '    from backend import wissen_destillat as _wd\n'
             '\n'
             '    body = await request.json()\n'
             '    markdown = str(body.get("markdown") or "").strip()\n')
    ersatz = ('    from backend import wissen_destillat as _wd\n'
              '\n'
              '    body = await request.json()\n'
              '    if not _destillat_erlaubt(user):\n'
              '        return JSONResponse({"error": "Dir ist kein Wissensbereich zugewiesen."},\n'
              '                            status_code=403)\n'
              '    markdown = str(body.get("markdown") or "").strip()\n')
    if s.count(block) != 1:
        return s
    return s.replace(block, ersatz)


def _erstes_recht_weg(funktion: str):
    """Sabotage-Fabrik: in GENAU EINER Funktion die Rechte-Pruefung stilllegen
    (die Zeile steht in jedem Destillat-Endpunkt gleich – ein Textersatz
    traefe den falschen)."""
    def sab(s: str) -> str:
        a = s.find(f"async def {funktion}(")
        z = "    if not _destillat_erlaubt(user):\n"
        b = s.find(z, a) if a >= 0 else -1
        if a < 0 or b < 0 or s.find("\n@app.", a) < b:
            return s
        return s[:b] + "    if False:\n" + s[b + len(z):]
    return sab


def _filter_hinter_ablage(s: str) -> str:
    """Verschiebt den Filterkasten HINTER die Ablage."""
    a = s.find("            <!-- 0. Dateifilter (Vorgabe 2026-09-27)")
    b = s.find("            </details>\n", a if a > 0 else 0)
    d = s.find("            <div class=\"wi-list\" id=\"wi-dest-filelist\">")
    if not (0 < a < b < d):
        return s
    b += len("            </details>\n")
    return s[:a] + s[b:d] + s[a:b] + s[d:]


PROBEN = [
    # ── Die zentrale Zusage: KEIN AGENT ────────────────────────────────────
    ("⚠ tools=[] raus (aus der Hilfe wird eine Hintertuer)", WD,
     "        tools=[],", "        tools=None,", PY_W),

    ("Modellaufruf ueber get_provider statt provider_fuer_lauf", WD,
     "provider, model = _llm.provider_fuer_lauf(prompt_tool_calling=False)",
     "provider, model = _llm.get_provider(), 'x'", PY_W),

    # ── Fremdtext ──────────────────────────────────────────────────────────
    # An der FUNKTION angesetzt, nicht an einer Aufrufstelle: so trifft die
    # Probe beide Aufrufer (Block-Auftrag UND Zusammenfuehrung) und haengt
    # nicht an den Escape-Ebenen des Quelltexts (erster Anlauf verfehlte sie
    # deshalb – ein Proben-Mangel, kein zahnloser Waechter).
    ("Fremdtext wird nicht mehr entschaerft", WD,
     "        from backend.short_tracks_runner import fremdtext_entschaerfen\n"
     "        return fremdtext_entschaerfen(text)",
     "        return text", PY_W),

    ("Auftrag steht HINTER dem Inhalt (Dokument kann ihn ueberschreiben)", WD,
     '        + "=== AUFTRAG ===\\n" + prompt.strip() + "\\n\\n"\n'
     '        + ("=== GLIEDERUNG ===\\n" + gruppen_prompt.strip() + "\\n\\n"\n'
     '           if gruppen_prompt.strip() else "")\n'
     '        + f"=== INHALT ===\\nBEGINN INHALT-{kennung}\\n"\n'
     '        + _entschaerfen(inhalt)\n'
     '        + f"\\nENDE INHALT-{kennung}\\n")',
     '        + f"=== INHALT ===\\nBEGINN INHALT-{kennung}\\n"\n'
     '        + _entschaerfen(inhalt)\n'
     '        + f"\\nENDE INHALT-{kennung}\\n"\n'
     '        + "=== AUFTRAG ===\\n" + prompt.strip() + "\\n\\n"\n'
     '        + ("=== GLIEDERUNG ===\\n" + gruppen_prompt.strip() + "\\n\\n"\n'
     '           if gruppen_prompt.strip() else ""))', PY_W),

    # ── Bloecke ────────────────────────────────────────────────────────────
    ("ein Riesenabsatz wird NICHT mehr hart geteilt", WD,
     "            for i in range(0, len(absatz), BLOCK_ZEICHEN):\n"
     "                raus.append(absatz[i:i + BLOCK_ZEICHEN])\n"
     "            continue",
     "            raus.append(absatz)\n"
     "            continue", PY_W),

    # ── DOCX-Bilder ────────────────────────────────────────────────────────
    ("⚠ alphabetische statt numerischer Sortierung (image10 vor image2)", WD,
     "            for name in sorted(namen, key=_num):",
     "            for name in sorted(namen):", PY_W),

    ("magische Bytes werden nicht geprueft (EMF/Fake-PNG kommen durch)", WD,
     "                mime = _bild_mime(daten)\n"
     "                if not mime:\n"
     "                    continue",
     "                mime = _bild_mime(daten) or 'image/png'", PY_W),

    ("Bild-Deckel raus", WD,
     "                if len(raus) >= MAX_BILDER or gesamt >= MAX_BILDER_GESAMT:\n"
     "                    break",
     "                if False:\n"
     "                    break", PY_W),

    ("beschaedigtes Archiv wirft statt leer zurueckzugeben", WD,
     "    except Exception:  # noqa: BLE001\n"
     "        # Kein gueltiges ZIP / beschaedigt: der TEXT ist der primaere Weg und\n"
     "        # muss trotzdem durchkommen. Genau so macht es das Original.\n"
     "        return []",
     "    except Exception:  # noqa: BLE001\n"
     "        raise", PY_W),

    # ── Bilder und Wissensdatenbank ────────────────────────────────────────
    ("⚠ Bilder werden in die WISSENSDATENBANK eingebettet (Index-Rauschen)", MAIN,
     "        inhalt = _wd.markdown_fuer_wissen(markdown, bilder if isinstance(bilder, list) else [])",
     "        inhalt = _wd.markdown_mit_bildern(markdown, bilder if isinstance(bilder, list) else [])",
     PY_W),

    ("unbekannter Bild-Marker wird stillschweigend entfernt", WD,
     "        if 0 <= i < len(bilder):\n"
     "            return f\"\\n\\n![Bild]({bilder[i]})\\n\\n\"\n"
     "        return m.group(0)",
     "        if 0 <= i < len(bilder):\n"
     "            return f\"\\n\\n![Bild]({bilder[i]})\\n\\n\"\n"
     "        return \"\"", PY_W),

    # ── Endpunkt-Rechte ────────────────────────────────────────────────────
    ("Rechte-Pruefung im Lauf-Endpunkt raus", MAIN,
     '    if not _destillat_erlaubt(user):\n'
     '        return JSONResponse({"error": "Dir ist kein Wissensbereich zugewiesen."},\n'
     '                            status_code=403)\n'
     '    from backend import wissen_destillat as _wd\n'
     '\n'
     '    body = await request.json()\n'
     '    text = str(body.get("text") or "")',
     '    from backend import wissen_destillat as _wd\n'
     '\n'
     '    body = await request.json()\n'
     '    text = str(body.get("text") or "")', PY_W),

    ("⚠ Rechte-Pruefung HINTER dem Lesen des Rumpfes", MAIN, None,
     _rechte_verschieben, PY_W),

    ("Gruppen-Pruefung wird nachgebaut statt benutzt", MAIN,
     "    ok, fehler = _wissen_check_groups(user, groups)\n"
     "    if not ok:\n"
     "        return JSONResponse({\"error\": fehler}, status_code=403)",
     "    if not groups:\n"
     "        return JSONResponse({\"error\": \"keine Gruppe\"}, status_code=403)", PY_W),

    ("Benutzer kommt aus dem RUMPF statt aus der Anmeldung", MAIN,
     '            "created_by": _norm_login(user),',
     '            "created_by": str(body.get("user") or ""),', PY_W),

    ("_destillat_erlaubt ist nicht mehr fail-closed", MAIN,
     "    try:\n"
     "        return bool(_editable_groups_for(user))\n"
     "    except Exception:  # noqa: BLE001\n"
     "        return False",
     "    return bool(_editable_groups_for(user))", PY_W),

    ("Extraktion laeuft im Event-Loop (Dienst steht fuer ALLE)", MAIN,
     "        ergebnis = await asyncio.to_thread(_wd.extrahiere, dateien)",
     "        ergebnis = _wd.extrahiere(dateien)", PY_W),

    # ── Modul schreibt nichts Dauerhaftes ──────────────────────────────────
    ("das Modul legt Dateien dauerhaft ab", WD,
     "MAX_BLOECKE = 40 ",
     "_LECK = Path('/tmp/x').write_text('y')\nMAX_BLOECKE = 40 ", PY_W),

    ("Gruppen gehen NICHT durch die gemeinsame Normierung", MAIN,
     '    groups = _gruppen_normieren(body.get("groups"))\n    quelle =',
     '    groups = list(body.get("groups") or [])\n    quelle =', PY_W),

    # ── Frontend: Position und Sichtbarkeit ────────────────────────────────
    ("⚠ Container steht HINTER der Confluence-Einbindung", HTML, None,
     _container_verschieben, JS_W),

    ("Container ist ohne Wissensgruppe SICHTBAR", JS,
     "        if (!SCOPE || !SCOPE.groups || !SCOPE.groups.length) {\n"
     "            sec.classList.add('hidden');\n"
     "            return;\n"
     "        }",
     "        if (false) {\n"
     "            sec.classList.add('hidden');\n"
     "            return;\n"
     "        }", JS_W),

    ("Modul holt den Scope selbst (zwei Quellen)", JS,
     "        SCOPE = opt.scope || null;",
     "        SCOPE = opt.scope || null;\n"
     "        fetch('/api/wissen/scope');", JS_W),

    # ── Frontend: Renderer ─────────────────────────────────────────────────
    ("⚠ Markdown wird NICHT maskiert (Einschleusung moeglich)", JS,
     "        var s = esc(String(text || ''));",
     "        var s = String(text || '');", JS_W),

    ("javascript:-Links werden verlinkt", JS,
     "        s = s.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)\\s]+)\\)/g,\n"
     "            '<a href=\"$2\" target=\"_blank\" rel=\"noopener noreferrer\">$1</a>');",
     "        s = s.replace(/\\[([^\\]]+)\\]\\(([^)\\s]+)\\)/g,\n"
     "            '<a href=\"$2\" target=\"_blank\" rel=\"noopener noreferrer\">$1</a>');", JS_W),

    ("fremdes Bild-Schema wird durchgelassen", JS,
     "            if (/^data:image\\/(png|jpe?g|gif|webp|bmp);base64,[A-Za-z0-9+/=]+$/.test(url)\n"
     "                || /^https?:\\/\\//.test(url)) {\n"
     "                return '<img src=\"' + url + '\" alt=\"' + alt + '\">';\n"
     "            }\n"
     "            return alt || '';   // alles andere: nur der Alt-Text",
     "            return '<img src=\"' + url + '\" alt=\"' + alt + '\">';", JS_W),

    ("⚠ Lookbehind wieder als LITERAL (stirbt auf Safari < 16.4 beim Parsen)", JS,
     "        _FETT = new RegExp('\\\\*\\\\*(?=\\\\S)([^\\\\n]+?)(?<=\\\\S)\\\\*\\\\*', 'g');",
     "        _FETT = /\\*\\*(?=\\S)([^\\n]+?)(?<=\\S)\\*\\*/g;", JS_W),

    # ── Frontend: Knopf und Uebernahme ─────────────────────────────────────
    ("Destillier-Knopf ist ohne Text bedienbar", JS,
     "            run.disabled = laeuft || !ta.value.trim();",
     "            run.disabled = false;", JS_W),

    ("Knopf gesperrt OHNE Grund (unerklaertes Zeichen)", JS,
     "            run.title = laeuft ? t('wissen.dest_running')\n"
     "                : (ta.value.trim() ? '' : t('wissen.dest_need_text'));",
     "            run.title = '';", JS_W),

    # ── Laufanzeige: Drehkreis statt Sanduhr (Vorgabe 2026-09-28) ──────────
    ("Lauf zeigt wieder Text ohne Drehkreis", JS,
     "        status('wi-dest-status', t('wissen.dest_running'), 'busy');\n",
     "        status('wi-dest-status', t('wissen.dest_running'));\n", JS_W),
    ("Uebernahme zeigt wieder Text ohne Drehkreis", JS,
     "        status('wi-dest-takestatus', t('wissen.dest_taking'), 'busy');\n",
     "        status('wi-dest-takestatus', t('wissen.dest_taking'));\n", JS_W),
    ("Sanduhr kehrt in den Text zurueck", I18N,
     "'wissen.dest_running': 'Das Modell", "'wissen.dest_running': '⏳ Das Modell", JS_W),
    ("Laufanzeige ohne CSS-Regel", HTML,
     "        .wi-dest-busy { display: inline-flex;", "        .wi-dest-busy-weg { display: inline-flex;", JS_W),

    ("Uebernahme sendet auch OHNE Wissensgruppe", JS,
     "        if (!groups.length) {\n",
     "        if (false) {\n", JS_W),

    ("Gruppen werden bei jedem Zeichnen neu gebaut (Haken gehen verloren)", JS,
     "        if (g && !g.innerHTML.trim()) g.innerHTML = gruppenBoxen();",
     "        if (g) g.innerHTML = gruppenBoxen();", JS_W),

    # ── Verdrahtung ────────────────────────────────────────────────────────
    # Callable statt fester Zeichenkette: der Cache-Buster zaehlt hoch, ein
    # Anker mit fester ?v=N verfehlte sein Ziel beim naechsten Deploy.
    ("⚠ Skript-Tag fehlt (Container bliebe STILL leer)", HTML, None,
     lambda s: re.sub(r'    <script src="/static/js/wissen_destillat\.js\?v=\d+"></script>\n',
                      "", s, count=1), JS_W),

    ("wissen.js ruft init nicht mehr", WJS,
     "                if (window.WissenDestillat) {\n"
     "                    window.WissenDestillat.init({ scope: SCOPE, token: token });\n"
     "                }",
     "", JS_W),

    ("Container nicht bei den Klapp-Containern registriert", WJS,
     "'wi-sec-destillat',", "", JS_W),

    ("Entwurfsliste wird nach der Uebernahme nicht nachgezogen", WJS,
     "    window.WissenPortal = { reloadPending: function () { loadPending(); } };",
     "", JS_W),

    # ── Bilder an der FUNDSTELLE (2026-09-27) ──────────────────────────────
    ("⚠ Bilder im Fliesstext werden ignoriert (landen wieder am Dateiende)", WD,
     "                elif el.tag == _A_BLIP:", "                elif False:", PY_W),

    ("extrahiere() benutzt den Fundstellen-Leser nicht", WD,
     "            eigen = docx_text_mit_bildern(inhalt, start=len(bilder),",
     "            eigen = None and docx_text_mit_bildern(inhalt, start=len(bilder),",
     PY_W),

    ("Tabellen gehen wieder verloren", WD,
     '                elif kind.tag == _W + "tbl":', "                elif False:", PY_W),

    ("Nummern zaehlen nicht ueber die Dateien weiter", WD,
     "                nummer[pfad] = start + len(bilder)",
     "                nummer[pfad] = len(bilder)", PY_W),

    ("DOCTYPE wird geparst (Entitaeten aus fremdem Archiv)", WD,
     '        raise ValueError("DOCTYPE im DOCX")', "        pass", PY_W),

    ("feste Bild-Regel fehlt im Block-Auftrag", WD,
     "        kopf += _BILD_REGEL", "        pass", PY_W),

    ("feste Bild-Regel fehlt in der Zusammenfuehrung", WD,
     '        + (_BILD_REGEL if _MARKER.search(inhalt) else "")', '        + ""', PY_W),

    ("i18n EN wieder mit der alten Regel 5", I18N,
     "Keep every marker unchanged and place it directly after the sentence or "
     "list item the image illustrates",
     "Keep these markers unchanged and in the same place", PY_W),

    # ── i18n ───────────────────────────────────────────────────────────────
    ("ein Schluessel fehlt im Englischen", I18N,
     "        'wissen.dest_take': 'Into the knowledge base',\n", "", JS_W),
    # ── Ordner als Quelle (2026-09-27) ─────────────────────────────────────
    ("Ordner-Eingang ohne webkitdirectory (Dialog waehlt nur Dateien)", HTML,
     'id="wi-dest-dir" webkitdirectory directory multiple',
     'id="wi-dest-dir" multiple', JS_W),

    ("Ordner-Knopf ohne stopPropagation (oeffnet zusaetzlich den Datei-Dialog)", JS,
     "                    e.stopPropagation();\n                    dirIn.click();",
     "                    dirIn.click();", JS_W),

    ("⚠ readEntries nur EINMAL gelesen (grosse Ordner verlieren den Rest)", JS,
     "                    kinder = kinder.concat(Array.prototype.slice.call(block));\n"
     "                    weiter();",
     "                    kinder = kinder.concat(Array.prototype.slice.call(block));\n"
     "                    Promise.all(kinder.map(function (k) { return eintragLesen(k, raus); }))\n"
     "                        .then(fertig);", JS_W),

    ("versteckte Dateien werden mitgeschickt", JS,
     "            if (versteckt(e.name)) { weg++; return; }\n", "", JS_W),

    ("Ordnerwahl verliert den relativen Pfad", JS,
     "return { datei: f, name: f.webkitRelativePath || f.name };",
     "return { datei: f, name: f.name };", JS_W),

    ("gezogener Ordner geht als leere Datei durch", JS,
     "                if (!mitOrdner) {", "                if (true) {", JS_W),

    ("uebersprungene Dateien werden verschwiegen", JS,
     "        if (weg) teile.push(t('wissen.dest_dir_skipped', { n: weg }));\n", "", JS_W),

    ("Ordnerinhalt unsortiert", JS,
     "        nehmen.sort(", "        [].sort(", JS_W),

    ("leerer Ordner schickt trotzdem eine Anfrage", JS,
     "        if (!nehmen.length) {", "        if (false) {", JS_W),

    # ── Lesefortschritt und Protokoll (2026-09-27) ─────────────────────────
    ("extrahiere() meldet keinen Fortschritt mehr", WD,
     "                melde(i, n, name)\n", "                pass\n", PY_W),
    ("⚠ Dateien hinter der Textgrenze verschwinden wieder spurlos", WD,
     '            protokoll.append({"name": name, "art": "uebersprungen",\n'
     '                              "grund": "Nicht mehr gelesen – Textgrenze erreicht."})\n', "", PY_W),
    ("Fehlergrund fehlt im Protokoll", WD,
     '            protokoll.append({"name": name, "art": "fehler", "grund": grund})',
     '            protokoll.append({"name": name, "art": "fehler"})', PY_W),
    ("ein werfender Rueckruf bricht die Extraktion ab", WD,
     "                melde(i, n, name)\n            except Exception:  # noqa: BLE001\n                pass\n",
     "                melde(i, n, name)\n            finally:\n                pass\n", PY_W),
    ("Strom-Extraktion laeuft im Event-Loop", MAIN,
     "asyncio.ensure_future(asyncio.to_thread(_wd.extrahiere, dateien, _melde))",
     "asyncio.ensure_future(asyncio.sleep(0, _wd.extrahiere(dateien, _melde)))", PY_W),
    ("Rueckruf fuellt die Queue direkt aus dem Thread", MAIN,
     "            schleife.call_soon_threadsafe(\n                schlange.put_nowait, ",
     "            (lambda f, x: f(x))(\n                schlange.put_nowait, ", PY_W),
    ("Client bittet nicht um den Strom", JS,
     "'/api/wissen/destillat/extract?stream=1'", "'/api/wissen/destillat/extract'", JS_W),
    ("⚠ Balken rechnet i/n statt (i-1)/n (steht bei der letzten Datei auf 100 %)", JS,
     "(i - 1) / n * 100", "i / n * 100", JS_W),
    ("halbe Zeile wird verworfen statt aufgehoben", JS,
     "            rest = schluss ? '' : teile.pop();", "            rest = ''; if (!schluss) teile.pop();", JS_W),
    ("⚠ abgerissener Strom sieht aus wie Erfolg", JS,
     "                if (!fertig) {\n", "                if (!fertig) { fertig = { ok: [], fehler: {} }; }\n                if (false) {\n", JS_W),
    ("zweiter Lauf parallel moeglich", JS,
     "        if (liest) { status(", "        if (false) { status(", JS_W),
    ("Ablage wird nach dem Lesen nicht freigegeben", JS,
     "        var drop = $('wi-dest-drop'); if (drop) drop.classList.remove('disabled');",
     "        var drop = $('wi-dest-drop');", JS_W),
    ("Drehkreis bleibt nach dem Ende stehen", JS,
     "        liest = false;\n        var drop = $('wi-dest-drop'); if (drop) drop.classList.remove('disabled');\n        leseText(null);",
     "        liest = false;\n        var drop = $('wi-dest-drop'); if (drop) drop.classList.remove('disabled');", JS_W),
    ("⚠ Protokoll maskiert den Dateinamen nicht (Einschleusung)", JS,
     "'<span class=\"nm\">' + esc(p.name) + '</span>'", "'<span class=\"nm\">' + p.name + '</span>'", JS_W),
    ("Protokoll zeigt den Fehlergrund nicht", JS,
     "                gr = p.grund || t('wissen.dest_unreadable');", "                gr = t('wissen.dest_unreadable');", JS_W),
    ("Protokoll-Knopf zieht data-i18n nicht mit (Sprachwechsel setzt ihn falsch)", JS,
     "        btn.setAttribute('data-i18n', key);\n", "", JS_W),
    ("Drehkreis fehlt im Markup", HTML,
     '<span class="wi-busy-spin"></span><span id="wi-dest-exbusy-text">',
     '<span id="wi-dest-exbusy-text">', JS_W),
    ("neuer Text fehlt im Englischen", I18N,
     "        'wissen.dest_log_hide': 'Hide log',\n", "", JS_W),

    # ── Dateifilter (Black-/Whitelist, 2026-09-27) ─────────────────────────
    ("Filter: ein String wird Zeichen fuer Zeichen zu Mustern", WD,
     "        if isinstance(werte, (str, bytes)) or not isinstance(werte, (list, tuple)):\n",
     "        if not isinstance(werte, (list, tuple, str)):\n", PY_W),
    ("Filter: zu langes Muster wird angenommen", WD,
     "            if len(m) > MUSTER_MAX or any(", "            if any(", PY_W),
    ("Filter: Dubletten bleiben stehen", WD,
     "            if m not in aus:\n                aus.append(m)\n", "            aus.append(m)\n", PY_W),
    ("⚠ Filter speichern ohne Rechtepruefung", MAIN,
     None, _erstes_recht_weg("wissen_destillat_filter_speichern"), PY_W),
    ("Filter lesen ohne Rechtepruefung", MAIN,
     None, _erstes_recht_weg("wissen_destillat_filter_lesen"), PY_W),
    ("⚠ Filter: Benutzer aus dem Rumpf (fremden Filter unterschieben)", MAIN,
     "        f = _destillat_filter_pfad(user)\n        f.parent.mkdir(",
     "        f = _destillat_filter_pfad(body.get(\"user\") or user)\n        f.parent.mkdir(", PY_W),
    ("Filter: der ungepruefte Rumpf wird gespeichert", MAIN,
     "        tmp.write_text(json.dumps(daten, ", "        tmp.write_text(json.dumps(body, ", PY_W),
    ("Filter: ein Pruef-Fehler speichert trotzdem", MAIN,
     "    except _wd.DestillatFehler as e:\n        return JSONResponse({\"ok\": False, \"error\": str(e)}, status_code=400)\n"
     "    try:\n        f = _destillat_filter_pfad(user)\n",
     "    except _wd.DestillatFehler as e:\n        daten = {}\n"
     "    try:\n        f = _destillat_filter_pfad(user)\n", PY_W),
    ("Filter-Ablage ohne pfad_teil (zwei Dateien je Mensch)", MAIN,
     "            / f\"{_benutzer.pfad_teil(user, 'unbekannt')}.json\")", "            / f\"{user}.json\")", PY_W),
    ("⚠ der Filter greift beim Hochladen nicht", JS,
     "            var grund = filterGrund(name);\n", "            var grund = '';\n", JS_W),
    ("⚠ die Blacklist wird ignoriert", JS,
     "            if (musterTrifft(schwarz[i], pfad)) return", "            if (false) return", JS_W),
    ("⚠ die Whitelist wird ignoriert", JS,
     "        if (weiss.length && !weiss.some(", "        if (false && !weiss.some(", JS_W),
    ("Muster trifft als Teilstring", JS,
     "        return new RegExp('^' + re + '$', 'i');", "        return new RegExp(re, 'i');", JS_W),
    ("Gross-/Kleinschreibung zaehlt", JS,
     "        return new RegExp('^' + re + '$', 'i');", "        return new RegExp('^' + re + '$');", JS_W),
    ("Ordnermuster greift nur am Pfadanfang", JS,
     "        for (var i = 0; i < teile.length; i++) {\n            if (re.test(",
     "        for (var i = 0; i < 1; i++) {\n            if (re.test(", JS_W),
    ("⚠ ausgelassene Dateien fehlen im Protokoll", JS,
     "        var prot = (gefiltert || []).concat(d.protokoll || []);", "        var prot = d.protokoll || [];", JS_W),
    ("ausgelassene Zeile ohne Grund", JS, "                gr = p.grund || '';\n", "                gr = '';\n", JS_W),
    ("alles ausgelassen: trotzdem eine Anfrage", JS,
     "        if (!neu.length) {\n            // Alles ausgelassen", "        if (false) {\n            // Alles ausgelassen", JS_W),
    ("alles ausgelassen: stilles Nichts", JS,
     "            status('wi-dest-exstatus', t('wissen.dest_filtered_all'",
     "            (function () {})('wi-dest-exstatus', t('wissen.dest_filtered_all'", JS_W),
    ("⚠ Laden ueberschreibt eine begonnene Eingabe", JS,
     "                    if (el && !el.dataset.beruehrt) el.value", "                    if (el) el.value", JS_W),
    ("Filter wird nie gespeichert", JS, "            e.addEventListener('change', filterSpeichern);\n", "", JS_W),
    ("Speicherfehler verschwindet von selbst", JS,
     "                    status('wi-dest-filterstatus', (d && d.error) || t('wissen.dest_filter_save_err'), 'err');\n"
     "                    return;\n",
     "                    status('wi-dest-filterstatus', (d && d.error) || t('wissen.dest_filter_save_err'), 'err');\n"
     "                    setTimeout(function () { status('wi-dest-filterstatus', ''); }, 2500);\n"
     "                    return;\n", JS_W),
    ("Filterkasten steht HINTER der Ablage", HTML, None, _filter_hinter_ablage, JS_W),
    ("Rueckfall-Markup des Filter-Hinweises weicht von DE ab", HTML,
     'data-i18n="wissen.dest_filter_hint">Ein Muster je Zeile:', 'data-i18n="wissen.dest_filter_hint">Muster je Zeile:', JS_W),
    ("Filter-Text fehlt im Englischen", I18N,
     "        'wissen.dest_filtered_all': 'All {n} file(s) were skipped by the file filter – nothing was uploaded.',\n",
     "", JS_W),
]


def main() -> int:
    print(f"\033[1mGegenproben Wissens-Destillat ({len(PROBEN)})\033[0m\n")
    sichern()
    atexit.register(aufraeumen)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(1))

    # ── Regel statt Pflege: jede angefasste Datei MUSS gesichert sein ──────
    unbekannt = {p[1] for p in PROBEN} - set(DATEIEN)
    if unbekannt:
        print(f"\033[31mABBRUCH: nicht gesichert: {sorted(unbekannt)}\033[0m")
        return 2

    # ── Basislauf. Ohne gruene Basis ist keine Gegenprobe deutbar. ─────────
    print("\033[1mBasislauf\033[0m")
    for cmd, name in ((PY_W, "Backend"), (JS_W, "UI")):
        rc, aus = lauf(cmd)
        bil = [z for z in aus.splitlines() if "Ergebnis:" in z]
        print(f"  {name}: {bil[-1].strip() if bil else 'KEINE BILANZ'}")
        if rc != 0:
            print(f"\033[31mABBRUCH: Basislauf {name} nicht gruen\033[0m")
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

    # Byte-Gleichheit nach dem Lauf – eine Wiederherstellung, deren Erfolg
    # niemand prueft, ist keine.
    aufraeumen()
    rest = [r for r in DATEIEN
            if (ROOT / r).read_bytes() != (ABL / r.replace("/", "__")).read_bytes()]
    print("Arbeitsbaum wiederhergestellt: "
          + ("\033[32mja\033[0m" if not rest else f"\033[31mNEIN: {rest}\033[0m"))
    return 0 if (not stumm and not kaputt and not rest) else 1


if __name__ == "__main__":
    sys.exit(main())
