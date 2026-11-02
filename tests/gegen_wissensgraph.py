#!/usr/bin/env python3
"""Gegenproben zu den Wissensgraph-Waechtern (Isolation, Extraktion, Pflege,
Warteschlange, Endpunkt-Rechte).

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der genannte Waechter
das meldet. Eine Probe, die nicht beisst, ist ein Testmangel – oder die Zusage
existiert gar nicht (dann gehoert die Probe gestrichen, nicht der Waechter
geschaerft).

EIN Harness statt einem je Waechter (Plan: gegen_wissensgraph_isolation und
gegen_wissensgraph_extraktion): die Proben teilen Sicherung, Laufmarke und
Basislauf, und die Pflege-/Warteschlangen-Waechter haetten sonst keinen.

Wie in den uebrigen Harnessen: jede angefasste Datei steht geprueft in der
Sicherung (Exit 2), eine Laufmarke nimmt den Rueckstand eines abgeschossenen
Laufs beim naechsten Start zurueck, ein gruener Basislauf ist Bedingung, und
gelaufen wird ohne Bytecode.

    python3 tests/gegen_wissensgraph.py
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-wissensgraph"
MARKE = ABL / "LAUF"

WG = "backend/wissensgraph.py"
WGX = "backend/wissensgraph_extraktion.py"
VS = "backend/tools/vector_store.py"
KN = "backend/tools/knowledge.py"
LLM = "backend/llm.py"
MAIN = "backend/main.py"
WGJS = "frontend/js/wissensgraph.js"
WGHTML = "frontend/wissensgraph.html"
WGCSS = "frontend/css/wissensgraph.css"
THEME = "frontend/css/theme.css"
PORTAL = "frontend/portal.html"
CHATV = "frontend/js/chat_vorlage.js"
ZR = "backend/zugang_regel.py"
WW = "backend/wissensgraph_widerspruch.py"
WIKI = "backend/wissensgraph_wiki.py"
PORTALJS = "frontend/js/portal_seite.js"
UEB = "deploy/wissensgraph_uebernahme.py"
WGST = "frontend/js/wissensgraph_steuerung.js"
APPJS = "frontend/js/app.js"
DATEIEN = [WG, WGX, VS, KN, LLM, MAIN, WGJS, WGHTML, WGCSS, THEME, PORTAL, CHATV, ZR, WW, WIKI, PORTALJS, UEB, WGST, APPJS]

UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def w(name):
    return [sys.executable, str(ROOT / "tests" / f"{name}.py")]


ISO, EXT, PFL, WS, RECHTE, API = (w("test_wissensgraph_isolation"), w("test_wissensgraph_extraktion"),
                                  w("test_wissensgraph_pflege"), w("test_wissensgraph_warteschlange"),
                                  w("test_endpoint_rights"), w("test_wissensgraph_api"))
UI = ["node", str(ROOT / "tests" / "test_wissensgraph_ui.js")]
REL = w("test_wissensgraph_relevanz")
PH6 = w("test_wissensgraph_phase6")
RT = w("test_wissensgraph_rechte")
UBT = w("test_wissensgraph_uebernahme")
STUI = ["node", str(ROOT / "tests" / "test_wissensgraph_steuerung_ui.js")]


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
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300, env=UMG)
    return p.returncode, p.stdout + p.stderr


def bilanz(aus: str) -> list[str]:
    return [z for z in aus.splitlines() if "ergebnis:" in z.lower()]


def bewerte(cmd) -> tuple[bool, str]:
    rc, aus = lauf(cmd)
    b = bilanz(aus)
    if not b:
        # Ein Abbruch ohne Bilanz ist KEIN Biss (Register).
        return False, f"ABGEBROCHEN rc={rc} (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if "✗" in z)
    return (rc == 1 and fails > 0), f"{fails} FAIL · {b[-1].strip()}"


PROBEN = [
    # ── Isolation ──
    ("Isolation: _erlaubt prueft den Praefix nicht", WG,
     "    if not m.startswith(ERLAUBT):\n        return False\n", "", ISO),
    ("Isolation: Praefix ohne Schraegstrich (data/rag2 gilt)", WG,
     'ERLAUBT = ("data/rag/", "mnt/rag/")', 'ERLAUBT = ("data/rag", "mnt/rag")', ISO),
    ("Isolation: '..' im Pfad wird nicht abgewiesen", WG,
     '    if any(t in ("", ".", "..") for t in teile):\n        return False\n', "", ISO),
    ("Isolation: quelle_schreiben ohne Pruefung", WG,
     "    m = manifest_form(pfad)\n    if not _erlaubt(m):\n        return False\n    daten =",
     "    m = manifest_form(pfad)\n    daten =", ISO),
    ("Isolation: einreihen ohne Pruefung", WG,
     "    m = manifest_form(pfad)\n    if not _erlaubt(m):\n        return False\n    with _sperre:\n        wq = _queue()",
     "    m = manifest_form(pfad)\n    with _sperre:\n        wq = _queue()", ISO),
    ("Isolation: Umbenennen ins Verbotene verschiebt statt zu entfernen", WG,
     "        if not _erlaubt(n):\n            return quellen_entfernen([a])\n", "", ISO),
    ("Isolation: manifest_form weicht von knowledge_groups._rel ab", WG,
     "            return p.relative_to(PROJECT_ROOT).as_posix()\n        except ValueError:\n            return p.as_posix().lstrip(\"/\")",
     "            return p.relative_to(PROJECT_ROOT).as_posix()\n        except ValueError:\n            return p.as_posix()", ISO),
    ("Loeschschutz: leere Ordnerliste ohne Meldung", WGX,
     '        erg["bereinigen"] = "uebersprungen: keine Wissensordner konfiguriert"',
     '        erg["bereinigen"] = ""', ISO),
    ("Loeschschutz: laufendes Neu-Indizieren wird ignoriert", WGX,
     'elif getattr(k, "_reindex_lock", None) is not None and k._reindex_lock.locked():\n        erg["bereinigen"]',
     'elif False:\n        erg["bereinigen"]', ISO),
    ("Loeschschutz: leerer Index wird ignoriert", WGX,
     "    elif not indexed:\n", "    elif False:\n", ISO),
    ("Loeschschutz: Abgehaengt-Pruefung aus (streng=False)", WGX,
     "alive = k._nutzbare_ordner(folders, quellen_abs, streng=True)",
     "alive = k._nutzbare_ordner(folders, quellen_abs, streng=False)", ISO),
    # ── Extraktion ──
    ("Extraktion: tools=None statt []", WGX,
     'tools=[], reasoning_effort="low")', 'tools=None, reasoning_effort="low")', EXT),
    ("Extraktion: Dokumenttext nicht entschaerft", WGX,
     "text=fremdtext.entschaerfen(block, _struktur()))", "text=block)", EXT),
    ("Extraktion: feste Marke statt einer je Aufruf", WGX,
     "    marke = marke or secrets.token_hex(6)\n", '    marke = marke or "marke"\n', EXT),
    ("Extraktion: ungueltiges JSON wird repariert", WGX,
     '    return None, "ungueltig"\n',
     '    m2 = re.search(r"\\{.*\\}", t, re.S)\n'
     '    if m2:\n        try:\n            return json.loads(m2.group(0)), "repariert"\n'
     '        except Exception:  # noqa: BLE001\n            pass\n    return None, "ungueltig"\n', EXT),
    ("Extraktion: Relationen auf fremde Namen", WGX,
     'r.get("von") in namen and r.get("nach") in namen', "True", EXT),
    ("Extraktion: Normierung auf nicht angebotene Namen", WGX,
     'and z.get("kanonisch") in k and', "and", EXT),
    ("Extraktion: kein zweiter Versuch je Block", WGX,
     "        for _versuch in range(2):\n", "        for _versuch in range(1):\n", EXT),
    ("Extraktion: Datei scheitert nie (Schwelle aus)", WGX,
     "    if verworfen_bloecke * 2 > len(teile):\n", "    if False:\n", EXT),
    ("Extraktion: denken_aus setzt kein chat_template_kwargs", LLM,
     '            payload["chat_template_kwargs"] = {"enable_thinking": False}\n',
     "            pass\n", EXT),
    ("Extraktion: Rueckfall nimmt chat_template_kwargs nicht mit", LLM,
     'return ("reasoning_effort", "chat_template_kwargs")', 'return ("reasoning_effort",)', EXT),
    ("Extraktion: provider_holen setzt denken_aus nicht", WGX,
     "        provider.denken_aus = True\n", "        pass\n", EXT),
    ("Extraktion: Laufprofil wird nicht zurueckgesetzt", WGX,
     "            llm.current_agent_profile.reset(marke)\n", "            pass\n", EXT),
    ("Extraktion: Importer-Kopf geht ins Modell", WGX,
     "    text = kopf_entfernen(text_aus_chunks(chunks))\n", "    text = text_aus_chunks(chunks)\n", EXT),
    ("Extraktion: Kopf wird ueberall gesucht, nicht nur am Anfang", WGX,
     "    m = _CONFLUENCE_KOPF.search(text[:800])\n", "    m = _CONFLUENCE_KOPF.search(text)\n", EXT),
    ("Ableitung: Kantenart nicht vereinheitlicht", WG,
     '            kante(von, nach, norm_art(r.get("art") or ""), src)',
     '            kante(von, nach, str(r.get("art") or "bezug")[:60], src)', EXT),
    ("Einstellungen: Vorgaben werden mitgespeichert", WGX,
     "    config.save_setting(EINSTELLUNG, {k: v for k, v in st.items()\n"
     "                                      if k in VORGABEN and v != VORGABEN[k]})\n",
     "    config.save_setting(EINSTELLUNG, st)\n", EXT),
    # ── Pflege ──
    ("Pflege: remove_files meldet dem Graphen nichts", VS,
     '        _graph_melden("pflege_entfernt", sorted(drop))\n', "", PFL),
    ("Pflege: rename_file_path meldet dem Graphen nichts", VS,
     '        _graph_melden("pflege_umbenannt", old_path, new_path)\n', "", PFL),
    ("Pflege: Graph-Praefix ohne Trenner (share_1 trifft share_10)", WG,
     '    return manifest_form(pfad).rstrip("/") + "/"\n',
     '    return manifest_form(pfad).rstrip("/")\n', PFL),
    ("Pflege: Indexlauf reiht nicht mehr ein", KN,
     "                _graph_einreihen(path_str, mtime)\n", "", PFL),
    ("Pflege: Einreihen VOR der Gruppenzuordnung", KN,
     "    if changed or force:\n        try:\n            from backend import knowledge_groups as _kg\n",
     "    _graph_einreihen_abschliessen()\n    if changed or force:\n        try:\n"
     "            from backend import knowledge_groups as _kg\n", PFL),
    ("Pflege: Vormerken reiht sofort in die Schlange", KN,
     "            with _graph_vorgemerkt_lock:\n                _graph_vorgemerkt.append((path_str, mtime))\n",
     "            from backend import wissensgraph as _wg2\n            _wg2.einreihen(path_str, mtime)\n", PFL),
    ("Pflege: Umbenennen extrahiert neu (Zeitpunkt neu)", WG,
     '            q["pfad"] = n\n', '            q["pfad"] = n\n            q["zeitpunkt"] = time.time()\n', PFL),
    # ── Warteschlange ──
    ("Warteschlange: gibt nie auf (kein Negativ-Cache)", WG,
     '        aufgegeben = e["versuche"] >= max_versuche\n', "        aufgegeben = False\n", WS),
    ("Warteschlange: erledigt ignoriert die mtime", WG,
     '        if e and float(e.get("mtime") or 0) == float(mtime):\n', "        if e:\n", WS),
    ("Warteschlange: wird nicht auf Platte gesichert", WG,
     '        _json_schreiben(_o() / "queue.json", {"eintraege": _queue_cache})\n', "        pass\n", WS),
    ("Warteschlange: Mindestabstand der Drossel aus", WGX,
     "                warte = max(warte, self._zeiten[-1] + float(min_abstand) - jetzt)\n",
     "                pass\n", WS),
    ("Warteschlange: Abgleich reiht bekannt Unlesbares ein", WGX,
     "        if not voll and wg.unlesbar_trifft(m, mtime):\n", "        if False:\n", WS),
    ("Warteschlange: geaenderte Datei wird mit altem Stand extrahiert", WGX,
     "    if idx_mtime is not None and float(idx_mtime) != mtime:\n", "    if False:\n", WS),
    # ── Rechte ──
    # ── Meilenstein 3: Ansicht, Entscheidungen, Seite ──
    ("Ansicht: Suche ohne Nachbarn", WG,
     '        knoten = [k for k in knoten if k["id"] in treffer | nachbarn]',
     '        knoten = [k for k in knoten if k["id"] in treffer]', API),
    ("Ansicht: Kanten ins Leere", WG,
     '    kanten = [e for e in g["kanten"] if e["von"] in ids and e["nach"] in ids]',
     '    kanten = [e for e in g["kanten"] if e["von"] in ids or e["nach"] in ids]', API),
    ("Ansicht: Ordner-Praefix ohne Trenner", WG,
     '        pref = manifest_form(ordner).rstrip("/") + "/"\n        knoten = [k for k in knoten if _im_ordner',
     '        pref = manifest_form(ordner).rstrip("/")\n        knoten = [k for k in knoten if _im_ordner', API),
    ("Entscheidung: Kreis wird nicht abgewiesen", WG,
     '        if _aufloesen(b, d["zusammen"]) == a:\n            raise ValueError("Das Ziel ist bereits in die Quelle zusammengefuehrt")\n',
     '', API),
    ("Entscheidung: Trennen nimmt die Zusammenfuehrung nicht zurueck", WG,
     '        for x in zurueck:\n            d["zusammen"].pop(x, None)\n', '', API),
    ("Pruefliste: getrennte Paare kommen wieder", WG,
     '        if tuple(sorted([a["id"][2:], b["id"][2:]])) in getrennt:\n            continue\n', '', API),
    ("Rechte: Pruefliste ohne Admin-Schranke", MAIN,
     "async def wissensgraph_pruefliste(limit: int = 50, user: str = Depends(require_knowledge_editor)):",
     "async def wissensgraph_pruefliste(limit: int = 50, user: str = Depends(require_auth)):", API),
    ("Seite: Kachel ist ohne Admin sichtbar", PORTAL,
     '<a class="pt-card hidden" id="pt-card-wissensgraph"', '<a class="pt-card" id="pt-card-wissensgraph"', UI),
    ("Seite: ohne sigma bricht alles ab", WGJS,
     "return !!(window.JarvisGraphology && window.JarvisFA2 && window.JarvisLouvain);",
     "return !!(window.JarvisGraphology && window.JarvisFA2 && window.JarvisLouvain && window.JarvisSigma);", UI),
    ("Seite: Sprachwechsel auf document (feuert nie)", WGJS,
     "window.addEventListener('jarvis-lang-changed'", "document.addEventListener('jarvis-lang-changed'", UI),
    ("Auffaelligkeiten: Ausblenden wirkt nicht", WGJS,
     "if (weg.indexOf(k.getAttribute('data-schluessel')) >= 0) { versteckt++; return; }", "", UI),
    ("Auffaelligkeiten: Dokumentkante zaehlt als Verbindung", WGJS,
     "if (am.typ !== 'quelle') { begriffe++; inseln[am.insel] = true; }", "begriffe++; inseln[am.insel] = true;", UI),
    ("Auffaelligkeiten: auch innerhalb einer Insel 'ueberraschend'", WGJS,
     "            if (av.insel === an.insel) { return; }\n", "", UI),
    ("Inseln: Kennung als Zeichenkette (=== trifft nie)", WGJS,
     "            _inseln.push({ id: G.getNodeAttribute(mitglieder[0], 'insel'),",
     "            _inseln.push({ id: c,", UI),
    ("Kamera: Methode aus sigma 2/3 (gibt es in 4 nicht)", WGJS,
     "if (R) { R.getCamera().zoomIn({ duration: 250 }); }", "if (R) { R.getCamera().animatedZoom({ duration: 250 }); }", UI),
    ("Seite: .hidden-Regel fehlt (Elemente bleiben sichtbar)", WGCSS,
     ".hidden { display: none !important; }\n", "", UI),
    ("sigma 4: Reduzierer liest das zweite Argument", WGJS,
     "    function knotenReduzierer(n, anzeige, a) {", "    function knotenReduzierer(n, a) {", UI),
    ("sigma 4: Feld aus sigma 2/3 (still ignoriert)", WGJS,
     "{ r.visibility = 'hidden'; }", "{ r.hidden = true; }", UI),
    ("Chat-Vorlage: schickt selbst ab", CHATV,
     "        feld.focus();\n", "        feld.focus();\n        fetch('/api/chat', { method: 'POST' });\n", UI),
    ("Chat-Vorlage: wird nicht geloescht", CHATV,
     "            localStorage.removeItem(SCHLUESSEL);\n", "", UI),
    ("Chat-Vorlage: verfaellt nicht", CHATV,
     "        if (typeof v.zeit !== 'number' || Date.now() - v.zeit > GUELTIG_MS) { return null; }\n", "", UI),
    ("Regel: Farbliteral im Seiten-CSS", WGCSS,
     "    background: var(--bg-primary);\n    overflow: hidden;", "    background: #0a0e17;\n    overflow: hidden;", UI),
    ("Regel: Graphfarbe fehlt im hellen Thema", THEME,
     "    --graph-kante-stark: rgba(26, 34, 51, 0.6);\n", "", UI),
    ("Regel: Inline-Handler in der Seite", WGHTML,
     '<button type="button" class="ja-btn" id="wg-einpassen"',
     '<button type="button" class="ja-btn" id="wg-einpassen" onclick="x()"', UI),
    ("Zugang: Seitenrahmen fehlt in der BSI-M10-Regel", ZR,
     '    ("GET", "/wissensgraph"): ("seite", "Seitenrahmen (Daten nur fuer Admins)"),\n', '', API),
    # ── Meilenstein 4: Relevanzmodell und vierter Kanal ──
    ("Relevanz: nicht erlaubtes Dokument zaehlt (Filter raus)", WG,
     "        docs = [d for d in idx[\"ent_docs\"].get(e, ()) if erl is None or d in erl]\n",
     "        docs = list(idx[\"ent_docs\"].get(e, ()))\n", REL),
    ("Relevanz: Seltenheit ueber alle statt erlaubte Dokumente", WG,
     '    n = idx["n_docs"] if erl is None else max(1, len(erl & set(idx["doc_ents"])))\n',
     '    n = idx["n_docs"]\n', REL),
    ("Relevanz: Hubs zaehlen wieder", WG,
     "        if 0 < n <= grenze:\n", "        if 0 < n:\n", REL),
    ("Relevanz: Startdokumente im Ergebnis", WG,
     "            if d in starts:\n                continue\n", "", REL),
    ("Relevanz: Seltenheit nicht gewichtet", WG,
     "        gewicht = math.log(1 + n / len(docs))\n", "        gewicht = 1.0\n", REL),
    ("Relevanz: ein Wort des Namens genuegt", WG,
     "        if not all(_wort_passt(x, w) for x in worte):", "        if not any(_wort_passt(x, w) for x in worte):", REL),
    ("Relevanz: Beugung bei kurzen Woertern", WG,
     "    return any(len(q) >= 5 and q[:5] == w[:5] and (q.startswith(w) or w.startswith(q))",
     "    return any((q.startswith(w) or w.startswith(q))", REL),
    ("Relevanz: Fuellwoerter zaehlen", WG,
     "    return [w for w in norm_name(text).split() if w not in _FUELLWOERTER]",
     "    return norm_name(text).split()", REL),
    ("Kanal: Frage geht nicht an das Modell", VS,
     "            docs = graph_rangliste(start, allow_paths, query) or []",
     "            docs = graph_rangliste(start, allow_paths, \"\") or []", REL),
    ("Kanal: volles Gewicht in der Fusion", VS, "GRAPH_GEWICHT = 0.5\n", "GRAPH_GEWICHT = 1.0\n", REL),
    ("Beschriftung: alle Nachbarn erzwungen", WGJS,
     "                if (n === _hover || _hoverAuswahl.knoten[n]) { r.labelVisibility = 'visible'; }",
     "                r.labelVisibility = 'visible';", UI),
    ("Beschriftung: alle Kantentexte", WGJS,
     "                r.label = _hoverAuswahl.kanten[k] ? relevanzText(a) : '';",
     "                r.label = relevanzText(a);", UI),
    ("Beschriftung: Auswahl nicht nach Belegen geordnet", WGJS,
     "            return (y.g - x.g) || (y.s - x.s) || (x.m < y.m ? -1 : (x.m > y.m ? 1 : 0));",
     "            return (x.m < y.m ? -1 : (x.m > y.m ? 1 : 0));", UI),
    ("Beschriftung: Ueberlappung nicht geprueft", WGJS,
     "            if (k && stehen.some(function (b) { return schneidet(k, b); })) { continue; }\n", "", UI),
    ("Beschriftung: Hover-Kasten wieder fest weiss", WGJS,
     "                  labelColor: _farben.text, backdropColor: _farben.grund };",
     "                  labelColor: _farben.text };", UI),
    ("Beschriftung: Hervorheben ungedeckelt", WGJS,
     "        freiAuswaehlen(liste, beschriftungsKasten, MAX_BESCHRIFTUNGEN, [])",
     "        freiAuswaehlen(liste, beschriftungsKasten, 99999, [])", UI),
    ("Zusammenhaenge: Beleg ausserhalb der Erlaubnis zaehlt", WG,
     '        belege = [b for b in e["sources"] if erl is None or b in erl]',
     '        belege = list(e["sources"])', REL),
    ("Kanal: unbegrenzt viele Chunks je Dokument", VS,
     "if fp not in rang or je[fp] >= GRAPH_CHUNKS_JE_DOKUMENT:", "if fp not in rang or je[fp] >= 99:", REL),
    ("Kanal: Erlaubnis ignoriert", VS,
     "            if p not in rang and (allow_paths is None or p in allow_paths):",
     "            if p not in rang:", REL),
    ("Kanal: Graphfehler kippt die Suche", VS,
     "        except Exception as e:  # noqa: BLE001\n            _log.warning(\"Graph-Kanal uebersprungen: %s\", e)\n            return []\n",
     "        except ZeroDivisionError:\n            return []\n", REL),
    ("Schalter: Vorgabe AN", WGX, '    "expansion": False,', '    "expansion": True,', REL),
    ("Schalter: Kanal ohne Schalter aktiv", KN,
     '        if not (st.get("aktiv") and st.get("expansion")):', '        if False:', REL),
    # ── Phase 6: Widersprueche, Wiki, Export, Rueckkopplung, Beschriftung ──
    ("Widerspruch: ohne Bestaetigung gemeldet", WW,
     "            if not isinstance(beleg, dict):\n                continue\n", "", PH6),
    ("Widerspruch: ohne Dokumentnamen (Datum nicht erkennbar)", WW,
     "                                                           dokumente=[m for m, _t in texte]),",
     "                                                           dokumente=None),", PH6),
    ("Widerspruch: zwei datierte Staende gemeldet", WW,
     "            if zwei_staende(ma, mb):\n                continue\n", "", PH6),
    ("Widerspruch: nur eine Bestaetigung", WW, "BESTAETIGUNGEN = 2 ", "BESTAETIGUNGEN = 1 ", PH6),
    ("Widerspruch: Zitat ungeprueft", WW,
     "    if not zitat_belegt(za, text_a) or not zitat_belegt(zb, text_b):\n        return False\n", "", PH6),
    ("Widerspruch: Ja ohne gemeinsame Frage", WW,
     "    if not frage or not za or not zb or _flach(za) == _flach(zb):",
     "    if not za or not zb or _flach(za) == _flach(zb):", PH6),
    ("Widerspruch: gilt trotz geaenderter Quelle", WG,
     '        if (a in stand and z in stand and stand[a] == float(b.get("mtime_a") or -1)\n'
     '                and stand[z] == float(b.get("mtime_b") or -1)):',
     "        if a in stand and z in stand:", PH6),
    ("Widerspruch: Umbenennen zieht die Befunde nicht mit", WG,
     "            _nebenablagen_umschreiben(a, n)\n", "", PH6),
    ("Widerspruch: Fremdtext nicht entschaerft", WW,
     "{fremdtext.entschaerfen(t, s)}", "{t}", PH6),
    ("Widerspruch: Fehlversuche ruhen nie", WW,
     '        if alt.get("quellen") == q and (not alt.get("fehler") or int(alt.get("versuche") or 0) >= MAX_VERSUCHE):',
     '        if alt.get("quellen") == q and not alt.get("fehler"):', PH6),
    ("Widerspruch: Paar mit sich selbst", WW,
     "        if not (1 <= a <= n and 1 <= b <= n) or a == b:", "        if not (1 <= a <= n and 1 <= b <= n):", PH6),
    ("Widerspruch: keine Kante im Graphen", WG,
     '            kante(von, nach, KANTE_WIDERSPRUCH, b["a"])\n            kante(von, nach, KANTE_WIDERSPRUCH, b["b"])\n',
     "            pass\n", PH6),
    ("Wiki: erfundener Verweis bleibt stehen", WIKI,
     '        return f"[[{ziel}]]" if ziel else anzeige', "        return mt.group(0)", PH6),
    ("Wiki: Ueberschrift erster Ebene bleibt", WIKI,
     '    t = "\\n".join(z for z in t.splitlines() if not re.match(r"^#\\s", z))\n', "", PH6),
    ("Wiki: Fehlschlag verwirft die alte Seite", WIKI,
     '            wi[kid] = {**alt, "quellen": alt.get("quellen", {}), "fehler": fehler[:300],',
     '            wi[kid] = {"quellen": {}, "fehler": fehler[:300],', PH6),
    ("Wiki: Seite gilt trotz geaenderter Quelle als aktuell", WIKI,
     '            "veraltet": k is None or e.get("quellen") != _stand(k)}', '            "veraltet": k is None}', PH6),
    ("Export: Namensgleichheit nicht aufgeloest", WIKI,
     "    while n.casefold() in belegt:", "    while False:", PH6),
    ("Export: verbotene Zeichen im Dateinamen", WIKI,
     "_VERBOTEN = re.compile(r'[\\[\\]#^|\\\\/:*?\"<>\\x00-\\x1f]')", "_VERBOTEN = re.compile(r'[\\x00-\\x1f]')", PH6),
    ("Nachlauf: Abbrechen haelt ihn nicht an", WGX,
     "    if _nachlauf_pause:\n        return False\n", "", PH6),
    ("Rueckmeldung: fremde Art angenommen", WG,
     '    if art not in RUECKMELDUNG_ARTEN:\n        raise ValueError("art: unbekannt")\n', "", PH6),
    ("Rueckmeldung: nicht gedeckelt", WG,
     "        alle[str(benutzer)] = liste[-RUECKMELDUNG_MAX:]\n", "        alle[str(benutzer)] = liste\n", PH6),
    ("Seite: Ausblenden erreicht den Server nicht", WGJS,
     "            sende('/api/wissensgraph/rueckmeldung', 'POST', {", "            sende('/api/wissensgraph/rueckmeldungX', 'POST', {", UI),
    ("Seite: Rueckkopplung gewichtet nicht", WGJS,
     "    function rueckFaktor(art, knoten, typen) { return 1 - RUECK_GEWICHT * aehnlichkeit(art, knoten, typen); }",
     "    function rueckFaktor(art, knoten, typen) { return 1; }", UI),
    ("Seite: Wiki-Text als HTML eingesetzt", WGJS,
     "            if (pos < text.length) { wohin.appendChild(document.createTextNode(text.slice(pos))); }",
     "            if (pos < text.length) { wohin.insertAdjacentHTML('beforeend', text.slice(pos)); }", UI),
    ("Seite: abgelehnter Schalter bleibt umgelegt", WGST,
     "            if (typeof e[k] === 'boolean' && !h.disabled) { h.checked = e[k]; }",
     "            if (typeof e[k] === 'boolean' && !h.disabled && !h.dataset.gesetzt) { h.checked = e[k]; h.dataset.gesetzt = '1'; }", STUI),
    ("Rechte: Export ohne Admin-Schranke", MAIN,
     "async def wissensgraph_export(user: str = Depends(require_knowledge_editor)):",
     "async def wissensgraph_export(user: str = Depends(require_auth)):", RECHTE),
    ("Rechte: Wiki erzeugen ohne Admin-Schranke", MAIN,
     "async def wissensgraph_wiki_erzeugen(kid: str, user: str = Depends(require_wissensgraph_leser)):",
     "async def wissensgraph_wiki_erzeugen(kid: str, user: str = Depends(require_auth)):", RECHTE),
    # ── Rechte nach Wissensrollen (2026-10-31) ──
    ("Rollen: Teilgraph aus ALLEN Quellen (fremde Inhalte sichtbar)", WG,
     '    t = ableiten([q for q in quellen_alle() if q["pfad"] in erl])\n', "    t = ableiten()\n", RT),
    ("Rollen: Widersprueche ungefiltert", WW,
     '        if erl is not None and not (b["a"] in erl and b["b"] in erl):\n            continue\n', "", RT),
    ("Rollen: Wiki-Seite trotz fremder Quellen sichtbar", WIKI,
     "    return bool(q) and set(q) <= erl\n", "    return bool(q)\n", RT),
    ("Rollen: Wiki erzeugen trotz fremder Quellen", WIKI,
     '    return bool(k) and set(k["sources"]) <= erl\n', "    return bool(k)\n", RT),
    ("Rollen: Admin gilt als globaler Wissenseditor", MAIN,
     "    glob = _may_edit_knowledge(user)\n    try:\n        gruppen = _editable_groups_for(user)",
     "    glob = _may_edit_knowledge(user) or bool(_is_admin_user(user))\n    try:\n        gruppen = _editable_groups_for(user)", RT),
    ("Rollen: Fehler beim Ermitteln oeffnet alles", MAIN,
     "    except Exception:  # noqa: BLE001 – ohne Gruppenliste kein Gruppenzugang\n        gruppen = []\n",
     "    except Exception:  # noqa: BLE001 – ohne Gruppenliste kein Gruppenzugang\n        return {\"stufe\": \"global\", \"gruppen\": [], \"pflegen\": True, \"steuern\": False}\n", RT),
    ("Rollen: Graph-Route ohne Ausschnitt", MAIN,
     '        wg.ansicht, q[:200], typ, ordner, gruppen[0] if gruppen else "", dokumente, limit, offset, teil))',
     '        wg.ansicht, q[:200], typ, ordner, gruppen[0] if gruppen else "", dokumente, limit, offset))', RT),
    ("Rollen: Widerspruchs-Route ohne Ausschnitt", MAIN,
     '    return JSONResponse({"befunde": await asyncio.to_thread(ww.liste, erlaubt)})',
     '    return JSONResponse({"befunde": await asyncio.to_thread(ww.liste)})', RT),
    ("Rollen: Export fuer jeden Leser", MAIN,
     "async def wissensgraph_export(user: str = Depends(require_knowledge_editor)):",
     "async def wissensgraph_export(user: str = Depends(require_wissensgraph_leser)):", RECHTE),
    ("Rollen: Pflege fuer jeden Leser", MAIN,
     "async def wissensgraph_zusammenfuehren(request: Request, user: str = Depends(require_knowledge_editor)):",
     "async def wissensgraph_zusammenfuehren(request: Request, user: str = Depends(require_wissensgraph_leser)):", RECHTE),
    ("Rollen: Inhalte ohne Schranke", MAIN,
     "async def wissensgraph_knoten(kid: str, user: str = Depends(require_wissensgraph_leser)):",
     "async def wissensgraph_knoten(kid: str, user: str = Depends(require_auth)):", RECHTE),
    ("Seite: Filterwechsel legt neuen Graphen an (Grafik am alten)", WGJS,
     "        } else if (!anhaengen) {\n            G.clear();\n        }",
     "        } else if (!anhaengen) {\n            G = new window.JarvisGraphology.Graph({ type: 'undirected', multi: false });\n        }", UI),
    ("Rollen: Zwischenspeicher rechnet trotzdem jedes Mal", MAIN,
     "    if hit and time.monotonic() - hit[0] < _WG_ZUGANG_TTL:\n        return {**hit[1], \"gruppen\": list(hit[1][\"gruppen\"])}\n", "", RT),
    ("Rollen: Zwischenspeicher gibt sein Original heraus", MAIN,
     "        return {**hit[1], \"gruppen\": list(hit[1][\"gruppen\"])}", "        return hit[1]", RT),
    ("Pruefliste: Selbstpaare (Diagonale) nicht ausgeschlossen", WG,
     "        S = np.where(spalten[None, :] > zeilen[:, None], S, -2.0)   # nur j > i\n", "", API),
    ("Pruefliste: Vorrat ohne Platz fuer getrennte Paare", WG,
     "    bedarf = max(1, int(limit)) + len(getrennt)\n", "    bedarf = max(1, int(limit))\n", API),
    ("Pruefliste: Stand behaelt getrennte Paare", WG,
     "                 and tuple(sorted([p[\"quelle\"][\"id\"][2:], p[\"ziel\"][\"id\"][2:]])) not in getrennt]",
     "]", API),
    ("Pruefliste: mehrere Hintergrundlaeufe zugleich", WG,
     "        anstossen = not aktuell and not _pruef[\"laeuft\"]", "        anstossen = not aktuell", API),
    ("Pruefliste: Route rechnet wieder im Request", MAIN,
     "    return JSONResponse(await asyncio.to_thread(wg.pruefliste_stand, limit))",
     "    return JSONResponse({\"paare\": await asyncio.to_thread(wg.pruefliste, limit)})", API),
    ("Seite: Pruefliste fragt nicht nach", WGJS,
     "                _pruefTimer = setTimeout(function () { prueflisteLaden(true); }, PRUEF_NACHFRAGE_MS);\n", "", UI),
    ("Seite: Ladeanzeige ohne Kreis", WGJS,
     "        ziel.appendChild(k);\n", "", UI),
    ("Seite: 'Nichts zu pruefen' waehrend der Rechnung", WGJS,
     "                if (!d.laeuft) { box.appendChild(el('p', 'ja-note', t('wissensgraph.review_none', 'Nichts zu prüfen.'))); }",
     "                box.appendChild(el('p', 'ja-note', t('wissensgraph.review_none', 'Nichts zu prüfen.')));", UI),
    ("Seite: Kachel wieder an is_admin", PORTALJS,
     "        if (d.permissions && d.permissions.wissensgraph) {", "        if (d.is_admin) {", UI),
    ("Seite: ohne Recht keine Umleitung", WGJS,
     "            if (_zugang.stufe === 'keine') { location.replace('/portal'); return; }\n", "", UI),
    ("Seite: Admin allein bekommt die Seite (alte Regel)", WGJS,
     "            if (_zugang.stufe === 'keine') { location.replace('/portal'); return; }",
     "            if (_zugang.stufe === 'keine' && !_zugang.steuern) { location.replace('/portal'); return; }", UI),
    ("Seite: Pruefliste und Export fuer jeden", WGJS,
     "        if (pf) { pf.classList.toggle('hidden', !_zugang.pflegen); }",
     "        if (pf) { pf.classList.toggle('hidden', false); }", UI),
    ("Seite: Entfernen fuer jeden Leser", WGJS,
     "            if (d.typ !== 'quelle' && _zugang.pflegen) {", "            if (d.typ !== 'quelle') {", UI),
    ("Seite: holt die Liste ALLER Gruppen", WGJS,
     "        optionenSetzen('wg-gruppe', _zugang.gruppen || []);\n        return Promise.resolve();",
     "        optionenSetzen('wg-gruppe', _zugang.gruppen || []);\n        return holeJson('/api/knowledge/groups');", UI),
    ("Seite: gesperrte Wiki-Seite als Ladefehler", WGJS,
     "                if (r.status === 403) { return { gesperrt: fehlertext(j, 'HTTP 403') }; }\n", "", UI),
    ("Rechte: Status ohne Admin-Schranke", MAIN,
     "async def wissensgraph_status(user: str = Depends(require_local_auth)):",
     "async def wissensgraph_status(user: str = Depends(require_auth)):", RECHTE),
    ("Rechte: Neuaufbau ohne Admin-Schranke", MAIN,
     "async def wissensgraph_neuaufbau(request: Request, user: str = Depends(require_local_auth)):",
     "async def wissensgraph_neuaufbau(request: Request, user: str = Depends(require_auth)):", RECHTE),
    # Gemerkte Container-Zustaende (2026-10-31)
    ("Klapp: Zustand wird nicht gespeichert", WGJS,
     "        speicherSchreiben(KLAPP_SPEICHER, liste);\n", "", UI),
    ("Klapp: gespeichert werden die OFFENEN statt der zugeklappten", WGJS,
     "        if (zu) { liste.push(id); }", "        if (!zu) { liste.push(id); }", UI),
    ("Klapp: gespeicherter Zustand wird beim Laden nicht angewandt", WGJS,
     "            var istZu = zu.indexOf(karte.getAttribute('data-klapp')) >= 0;",
     "            var istZu = false;", UI),
    ("Klapp: kaputter Speicherstand wirft", WGJS,
     "            // Ein kaputter Speicherstand darf nicht dazu fuehren, dass nichts aufklappt.\n            return [];",
     "            throw e;", UI),
    ("Klapp: zugeklappte Grafik baut trotzdem den Renderer", WGJS,
     "            if (!R && grafikMoeglich() && !grafikZu()) { rendererBauen(); }",
     "            if (!R && grafikMoeglich()) { rendererBauen(); }", UI),
    ("Klapp: Aufklappen baut den Renderer nicht", WGJS,
     "            else if (G && G.order && grafikMoeglich()) { rendererBauen(); }\n", "", UI),
    # Drehender Kreis an Zustand und Wartestellen (2026-10-31)
    ("Kreis: arbeitet liest nur laeuft (Nachlauf gilt als wartend)", WGST,
     "        return !!(st && st.aktiv && (st.laeuft || st.aktuell));",
     "        return !!(st && st.aktiv && st.laeuft);", STUI),
    ("Kreis: keine Zeile traegt den Kreis", WGST,
     "            if (teil && p[2] === teil) { ladeText(dd, p[1]); } else { dd.textContent = p[1]; }",
     "            dd.textContent = p[1];", STUI),
    ("Kreis: wieder pauschal bei Zustand", WGST,
     "                : t('wissensgraph.st_off', 'aus'), 'state'],",
     "                : t('wissensgraph.st_off', 'aus'), teil],", STUI),
    ("Kreis: Wiki zaehlt als Widerspruch", WGST,
     "        if (m) { return m[1] === 'wiki' ? 'wiki' : 'contra'; }",
     "        if (m) { return 'contra'; }", STUI),
    ("Kreis: Meldung kennt 'lade' nicht", WGST,
     "        if (art === 'lade') { ladeText(m, text); } else { m.textContent = text || ''; }",
     "        m.textContent = text || '';", STUI),
    ("Kreis: erster Statusabruf ohne Kreis", WGST,
     "        if (sb && !sb.childNodes.length) { ladeText(sb, t('wissensgraph.loading', 'Lade …')); }\n", "", STUI),
    ("Kreis: Zusammenfuehren ohne Kreis im Knopf", WGJS,
     "                    ladeText(knopf, text);\n", "", UI),
    # Befunde des Vergleichsberichts DEV/ECHT (2026-11-01)
    ("Ableitung: jedes Schreiben der Widerspruchsablage leitet neu ab", WG,
     "        if _widerspruch_kanten(d.get(\"befunde\")) != vorher:\n            _veraltet_markieren()",
     "        _veraltet_markieren()", PH6),
    ("Ableitung: Zeitstempel eines Befunds zaehlt als Kante", WG,
     "    return {(b.get(\"a\"), b.get(\"b\"), b.get(\"mtime_a\"), b.get(\"mtime_b\"))",
     "    return {(b.get(\"a\"), b.get(\"b\"), b.get(\"mtime_a\"), b.get(\"mtime_b\"), b.get(\"zeit\"))", PH6),
    ("Ableitung: neuer Befund leitet NICHT neu ab", WG,
     "        if _widerspruch_kanten(d.get(\"befunde\")) != vorher:\n            _veraltet_markieren()",
     "        if _widerspruch_kanten(d.get(\"befunde\")) != vorher:\n            pass", PH6),
    ("Zaehler: pflege_aufruf zaehlt keine Aufrufe", WGX,
     "    z[\"pflege_aufrufe\"] = z.get(\"pflege_aufrufe\", 0) + 1\n", "", PH6),
    ("Zaehler: Wiki ruft das Modell direkt", WIKI,
     "        roh, _u = await wgx.pflege_aufruf(provider, modell, auftrag_wiki(k, text, verwandt), system=SYSTEM)",
     "        roh, _u = await wgx.modell_aufruf(provider, modell, auftrag_wiki(k, text, verwandt), system=SYSTEM)", PH6),
    ("Zaehler: Bestaetigung der Widersprueche ruft direkt", WW,
     "                roh2, _u = await wgx.pflege_aufruf(provider, modell,\n",
     "                roh2, _u = await wgx.modell_aufruf(provider, modell,\n", PH6),
    ("Zaehler: Status ohne Zeile fuer Widersprueche und Wiki", WGST,
     "            [t('wissensgraph.st_calls_care', 'Widersprüche und Wiki · Modellaufrufe · Token ein/aus'),\n"
     "             (z.pflege_aufrufe || 0) + ' · ' + (z.pflege_token_ein || 0) + ' / ' + (z.pflege_token_aus || 0)],\n", "", STUI),
    ("Kachel: Schalter wird nicht beachtet", MAIN,
     "        if not _wgx.einstellungen().get(\"aktiv\"):\n            return False\n", "", RT),
    ("Kachel: Fehler beim Lesen des Schalters zeigt sie", MAIN,
     "    except Exception:  # noqa: BLE001\n        return False\n    return _wissensgraph_zugang(user)",
     "    except Exception:  # noqa: BLE001\n        pass\n    return _wissensgraph_zugang(user)", RT),
    ("Kachel: /api/me mit der alten Regel", MAIN,
     "            \"wissensgraph\": _wissensgraph_kachel(user),",
     "            \"wissensgraph\": ist_admin or _wissensgraph_kachel(user),", RT),
    # Steuerung in Einstellungen → Wissen (2026-11-01)
    ("Steuerung: fragt auch zugeklappt ab", WGST,
     "        return !!b && b.style.display !== 'none' && !!tab && tab.style.display !== 'none';",
     "        return true;", STUI),
    ("Steuerung: app.js ruft onShow nicht", APPJS,
     "                    if (window.WissensgraphSteuerung) window.WissensgraphSteuerung.onShow();\n", "", STUI),
    ("Steuerung: Abschnitt nicht klappbar registriert", APPJS,
     "                { hdr: 'kb-sect-wg-hdr',     body: 'kb-sect-wg-body',     tog: 'kb-sect-wg-tog'     },\n", "", STUI),
    ("Steuerung: Aufklappen holt keinen Status", WGST,
     "        if (kopf) { kopf.addEventListener('click', function () { setTimeout(onShow, 0); }); }\n", "", STUI),
    ("Steuerung: Aufbau trotz ausgeschaltetem Graphen frei", WGST,
     "            start.disabled = !st.aktiv;\n", "", STUI),
    ("Steuerung: Gruppenliste mit 'ungrouped'", WGST,
     "            (d.groups || []).filter(function (g) { return g && g.id && g.id !== 'ungrouped'; }).forEach(",
     "            (d.groups || []).filter(function (g) { return g && g.id; }).forEach(", STUI),
    ("Kachel: Admin-Bypass zurueck", MAIN,
     "    try:\n        from backend import wissensgraph_extraktion as _wgx\n        if not _wgx",
     "    if _is_admin_user(user):\n        return True\n    try:\n        from backend import wissensgraph_extraktion as _wgx\n        if not _wgx", RT),
    # Modell-Last in Einstellungen → Wissen (2026-11-02)
    ("Drossel: Statusabfrage ueberschreibt die Eingabe", WGST,
     "            if (!h.disabled && !h.hasAttribute('data-wg-tippt')) { h.value = String(e[k]); }",
     "            if (!h.disabled) { h.value = String(e[k]); }", STUI),
    ("Drossel: Grenzen im Feld nicht geprueft", WGST,
     "v < Number(h.min) || v > Number(h.max)", "false", STUI),
    ("Drossel: Kommazahl bei ganzer Zahl angenommen", WGST,
     "                || (h.step === '1' && v % 1 !== 0)) {", "                ) {", STUI),
    ("Drossel: ungueltiger Wert bleibt im Feld stehen", WGST,
     "            if (k in _zahlStand) { h.value = String(_zahlStand[k]); }\n", "", STUI),
    ("Drossel: unveraenderter Wert wird gespeichert", WGST,
     "        if (v === _zahlStand[k]) { return; }\n", "", STUI),
    ("Drossel: Wert geht als Text an den Server", WGST,
     "        rumpf[k] = v;\n", "        rumpf[k] = roh;\n", STUI),
    ("Drossel: NaN und Unendlich angenommen", WGX,
     "            if not v <= ZAHL_MAX:\n", "            if False:\n", EXT),
    ("Drossel: Kommazahl still abgeschnitten", WGX,
     "            if isinstance(vorgabe, int) and v != int(v):\n", "            if False:\n", EXT),
    ("Drossel: Abstand ohne Obergrenze", WGX,
     '    if float(st["rate_min_abstand_s"]) > RATE_ABSTAND_MAX_S:\n', "    if False:\n", EXT),
    ("Drossel: Aufrufe ohne Obergrenze", WGX,
     '    if int(st["rate_max_pro_stunde"]) > RATE_STUNDE_MAX:\n', "    if False:\n", EXT),
    # Uebernahme eines fertigen Graphen (Option C)
    ("Uebernahme: mtime nicht verglichen", UEB, "        if mt == q[\"mtime\"]:", "        if True:", UBT),
    ("Uebernahme: laeuft als root", UEB, "    if (os.geteuid() if euid is None else euid) == 0:", "    if False:", UBT),
    ("Uebernahme: Abweichungen ohne --trotzdem uebernommen", UEB, "    if abw and not trotzdem:", "    if False:", UBT),
    ("Uebernahme: Widersprueche immer dabei", UEB,
     "    teile = [\"aliasse.json\"] + ([\"widersprueche.json\"] if mit_widerspruechen else [])",
     "    teile = [\"aliasse.json\", \"widersprueche.json\"]", UBT),
    ("Uebernahme: vorhandener Graph ungeschuetzt", UEB, "    if vorhanden and not ersetzen:", "    if False:", UBT),
    ("Uebernahme: unlesbare zaehlen nicht zur Gesamtzahl", UEB,
     "\"gesamt\": len(qs) + len(kaputt)}", "\"gesamt\": len(qs)}", UBT),
    ("Uebernahme: Pfad mit '..' angenommen", UEB,
     "        if not isinstance(pfad, str) or \"..\" in Path(pfad).parts or pfad.startswith(\"/\"):",
     "        if not isinstance(pfad, str):", UBT),
]

# Optional nur Proben, deren Name den Text enthaelt (der Basislauf bleibt vollstaendig).
if len(sys.argv) > 1:
    PROBEN = [p for p in PROBEN if sys.argv[1] in p[0]]
    if not PROBEN:
        print(f"ABBRUCH: keine Probe enthaelt '{sys.argv[1]}'")
        sys.exit(2)

fehlt = {p[1] for p in PROBEN} - set(DATEIEN)
if fehlt:
    print(f"ABBRUCH: nicht gesicherte Dateien in den Proben: {sorted(fehlt)}")
    sys.exit(2)

sichern()
atexit.register(aufraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

print("Basislauf")
for cmd in (ISO, EXT, PFL, WS, RECHTE, API, UI, REL, PH6, RT, UBT, STUI):
    rc, aus = lauf(cmd)
    b = bilanz(aus)
    print(f"  {Path(cmd[1]).stem}: {b[-1].strip() if b else 'KEINE BILANZ'}")
    if rc != 0 or not b:
        print("ABBRUCH: Basis nicht gruen – Gegenproben waeren nicht deutbar")
        sys.exit(2)

print(f"\n{len(PROBEN)} Gegenproben")
beissen, stumm = 0, []
for name, rel, alt, neu, cmd in PROBEN:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    if s.count(alt) != 1:
        print(f"  ⚠ {name}: SABOTAGE TRIFFT NICHT ({s.count(alt)}x) – Probe unbrauchbar")
        stumm.append(name + " (trifft nicht)")
        continue
    p.write_text(s.replace(alt, neu, 1), encoding="utf-8")
    try:
        gemeldet, info = bewerte(cmd)
    finally:
        zurueck()
    if gemeldet:
        beissen += 1
        print(f"  ✓ {name} → {info}")
    else:
        stumm.append(name)
        print(f"  ✗ {name} → BEISST NICHT ({info})")

abweichend = [rel for rel in DATEIEN
              if (ROOT / rel).read_bytes() != (ABL / rel.replace("/", "__")).read_bytes()]
print(f"\nErgebnis: {beissen}/{len(PROBEN)} Proben beissen")
print(f"Arbeitsbaum wiederhergestellt: {'ja' if not abweichend else 'NEIN – ' + str(abweichend)}")
if stumm:
    print("Stumm: " + "; ".join(stumm))
sys.exit(1 if (stumm or abweichend) else 0)
