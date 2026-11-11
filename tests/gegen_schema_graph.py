#!/usr/bin/env python3
"""Gegenprobe zu tests/test_schema_graph.py: beisst der Waechter?

Jede Probe dreht EINE Zusage im Produktcode zurueck und erwartet mindestens
einen FAIL. Gruener Basislauf vorher, Byte-Gleichheit danach (md5). Die
Sicherung liegt vor jeder Probe auf Platte (HOME, 0700) samt Laufmarke: wird
der Harness abgeschossen, nimmt der naechste Start den Rueckstand zurueck.
Laeuft ohne Bytecode (gleich grosse Sabotage in derselben Sekunde liesse
sonst eine veraltete .pyc laden).

Nie in einem Sammellauf mitlaufen lassen – die Proben patchen Dateien.
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_schema_graph.py"
SICHERUNG = Path.home() / ".jarvis_gegen_schema_graph"

PA = "backend/schema_graph_parser.py"
ST = "backend/schema_graph_store.py"
IX = "backend/schema_graph_index.py"
RG = "backend/schema_graph_rag.py"
MN = "skills/schema_graph/main.py"
EI = "backend/schema_graph_einstellungen.py"

PROBEN = [
    ("Blockgrenze darf hinter '-' liegen", PA,
     '                    while grenze > start and puf[grenze - 1] in "-/*$":',
     '                    while False:'),
    ("Kopf nach dem ersten Wort entschieden", PA,
     "    UNBEKANNT_AB = 80\n", "    UNBEKANNT_AB = 1\n"),
    ("Pufferanfang ohne Kontextzeichen", PA,
     "                puf = puf[pos - 1:]\n                start = 1\n",
     "                puf = puf[pos:]\n                start = 0\n"),
    ("Dollar-Lookbehind fehlt im Zweig 'str'", PA,
     r"""        |(?<![\w$])\$\$.*?\$\$|(?<![\w$])\$(?P<tag>[A-Za-z_]\w*)\$.*?\$(?P=tag)\$)""",
     r"""        |\$\$.*?\$\$|\$(?P<tag>[A-Za-z_]\w*)\$.*?\$(?P=tag)\$)"""),
    ("Dollar-Lookbehind fehlt im Zweig 'offen'", PA,
     r"""        |(?<![\w$])\$(?:[A-Za-z_]\w*)?\$.*\Z|(?<![\w$])\$[A-Za-z_]\w*\Z)""",
     r"""        |\$(?:[A-Za-z_]\w*)?\$.*\Z|\$[A-Za-z_]\w*\Z)"""),
    ("Ueberlese-Modus puffert", PA,
     '        if self.modus == "x":\n            return\n        self.teile.append(teil)',
     '        self.teile.append(teil)'),
    ("COPY-Datenblock nicht erkannt", PA,
     '                if anw.modus == "x" and anw.ist_copy_stdin():',
     '                if False:'),
    ("Abgeleitete Kante als fk ausgegeben", ST,
     '        kanten.append((oid, treffer, "abgeleitet", json.dumps([name]),',
     '        kanten.append((oid, treffer, "fk", json.dumps([name]),'),
    ("Abgeleitet trotz deklariertem FK", ST,
     "        if (oid, name_l) in fk_spalten or (nur_oids is not None and oid not in nur_oids):",
     "        if (nur_oids is not None and oid not in nur_oids):"),
    ("Mehrdeutiges wird geraten", ST,
     "        self.mehrdeutig += 1\n        return None\n",
     "        self.mehrdeutig += 1\n        return kand[0]\n"),
    ("Kein atomarer Tausch (direkt ins Ziel)", ST,
     '    neu = ziel.with_name(ziel.stem + ".neu.sqlite")\n',
     '    neu = ziel\n'),
    ("Hub zaehlt bei der Bereichsbildung mit", ST,
     "        if grad[von] > BEREICH_HUB_GRAD or grad[nach] > BEREICH_HUB_GRAD:\n            continue\n", ""),
    ("Negativ-Cache zaehlt nicht hoch", IX,
     '"THEN versuche+1 ELSE 1 END, groesse=excluded.groesse, "',
     '"THEN versuche ELSE 1 END, groesse=excluded.groesse, "'),
    ("Verschwundene Dateien bleiben", IX,
     "            for p in weg:\n                store.roh_entfernen(con, p)\n",
     "            for p in weg[:0]:\n                store.roh_entfernen(con, p)\n"),
    ("Hub wird ausgebreitet", RG,
     "            continue   # Hub: erreichbar, aber nicht ausbreiten\n",
     "            pass\n"),
    ("Steiner: kein Join-Glied", RG,
     "                if k not in anker:\n                    verbinder.append(k)\n",
     "                pass\n"),
    ("Kuerzungshinweis entfaellt", RG,
     '            zeilen.append(f"  Spalten ({len(gewaehlt)} von {len(sp)} gezeigt',
     '            zeilen.append(f"  Spalten: #({len(gewaehlt)} gezeigt'),
    ("Verbotene Schluesselwoerter nicht geprueft", RG,
     "    m = _VERBOTEN.search(ohne_namen)\n", "    m = None\n"),
    ("Namen in Anfuehrungszeichen als Schluesselwort", RG,
     "    m = _VERBOTEN.search(ohne_namen)\n", "    m = _VERBOTEN.search(s)\n"),
    ("Mehrere Anweisungen erlaubt", RG,
     '    if ";" in s:\n', '    if False:\n'),
    ("Spalten nicht geprueft", RG,
     "        if sp not in bekannt:\n", "        if False:\n"),
    ("Tabellenname als Alias.Spalte gelesen", RG,
     '        if stelle in tabellen_stellen or "." not in t or t.endswith(".*"):',
     '        if "." not in t or t.endswith(".*"):'),
    ("FROM in EXTRACT(...) als Tabellenquelle", RG,
     '        if low[i] in ("from", "join") and ebene_von[i] == "abfrage":',
     '        if low[i] in ("from", "join"):'),
    ("Unterabfrage-Ebene nicht erkannt", RG,
     '            stapel.append("abfrage" if nxt in ("select", "with") or vor in ("from", "join")',
     '            stapel.append("ausdruck" if nxt in ("select", "with") or vor in ("from", "join")'),
    ("Keine Reparaturrunde", RG,
     "            if pr[\"ok\"] or reparaturen >= MAX_REPARATUR:\n",
     "            if True:\n"),
    ("Reparaturen ungedeckelt (eine zu viel)", RG,
     "            if pr[\"ok\"] or reparaturen >= MAX_REPARATUR:\n",
     "            if pr[\"ok\"] or reparaturen > MAX_REPARATUR:\n"),
    ("BRAUCHE ohne Neues bricht ab", RG,
     "                if neu:\n                    ids = ids + neu",
     "                if not neu:\n                    return {\"fehler\": \"x\"}\n                if neu:\n                    ids = ids + neu"),
    ("Pruefstatus GEPRUEFT auch bei Befund", MN,
     '    elif pr.get("ok"):\n        kopf = (f"SQL ({dialekt}) – GEPRÜFT',
     '    elif True:\n        kopf = (f"SQL ({dialekt}) – GEPRÜFT'),
    ("Erfassen aus dem Chat ohne Schalter", MN,
     '            if cfg.get("index_aus_chat") is not True:\n',
     '            if False:\n'),
    # ── YAML (2026-11-07)
    ("YAML-Weg fehlt", PA, "    if str(pfad).lower().endswith(YAML_ENDUNGEN):", "    if False:"),
    ("YAML-Fremdschluessel ohne Schema", PA,
     '            fks.append({"von": _liste(f.get("columns")), "ziel": f"{zs}.{zt}" if zs else zt,',
     '            fks.append({"von": _liste(f.get("columns")), "ziel": zt,'),
    ("YAML-PK aus constraints ignoriert", PA, '                pk = _liste(c.get("columns"))', "                pk = []"),
    ("YAML-Typ ohne Laenge", PA, '            return f"{typ}({n})"', "            return typ[:80]"),
    ("Ausdruck ohne Alias uebergangen (halbe Liste)", PA, "        if not name:\n            return []",
     "        if not name:\n            continue"),
    ("END als Alias genommen", PA, "        if kand and kand.upper() not in _KEIN_ALIAS:", "        if kand:"),
    ("Alias-Baum wird geladen", PA,
     '                    raise yaml.YAMLError("YAML-Aliase (*name) werden nicht verarbeitet")', "                    pass"),
    ("YAML ohne Groessengrenze", PA, "    if groesse > YAML_MAX:", "    if False:"),
    ("Verzeichnisdatei nicht erkannt", PA,
     '    if "index_version" in d or ("object_type" not in d and isinstance(d.get("tables"), list)):', "    if False:"),
    ("Sequenz als Tabelle", PA, "    if typ in _OBJEKT_TABELLE:", '    if typ in _OBJEKT_TABELLE or typ == "SEQUENCE":'),
    ("Gleicher PK: allgemeine Namen zugelassen", ST, "        if _PK_ZUSAMMENGESETZT.fullmatch(pk.lower()):", "        if True:"),
    ("Gleicher PK: Mehrdeutiges geraten", ST, "        if len(andere) != 1:\n            continue\n",
     "        if not andere:\n            continue\n"),
    ("Gleicher PK: eigener PK verweist weiter", ST,
     '        if ist_pk and pk_ein.get(oid, "").lower() == name_l:\n            continue\n', ""),
    ("Gleicher PK: deklarierter FK doppelt", ST,
     "        if not ziele or (oid, name_l) in fk_spalten or (nur_oids is not None and oid not in nur_oids):",
     "        if not ziele or (nur_oids is not None and oid not in nur_oids):"),
    ("Gleicher PK: Sichten einbezogen", ST, '"WHERE o.art = \'tabelle\'").fetchall():', '"WHERE 1=1").fetchall():'),
    # ── Join-Pruefung (2026-11-07)
    ("Join-Pruefung fehlt", RG, "    _joins_pruefen(con, toks, aliase, tabellen, erg)\n", ""),
    ("Join-Beleg nur in einer Richtung", RG,
     "            if (von, nach) == (o2, o1) and (c2, c1) in paare:\n                return True\n", ""),
    ("Gleichnamige Schluesselspalte nicht als Beleg", RG,
     "        if c1 == c2 and (c1 in pk_cache.get(o1, set()) or c2 in pk_cache.get(o2, set())):", "        if False:"),
    # ── Joins ueber Sichten (2026-11-08)
    ("Sichten wieder ungeprueft (keine Herkunft)", RG,
     '        if a != "sicht" or tiefe >= 5:', "        if True:"),
    ("Unaufgeloeste Sichtspalte als unbelegt", RG,
     "        if b1 is None or b2 is None:\n            erg[\"joins_ungeprueft\"] += 1\n            continue\n",
     "        b1, b2 = b1 or (o1, c1), b2 or (o2, c2)\n"),
    ("Sicht gegen eigene Basisspalte nicht belegt", RG,
     "        if (p1 == p2 and d1 == d2) or belegt(p1, d1, p2, d2):", "        if belegt(p1, d1, p2, d2):"),
    ("Zwei Sterne ohne Spaltenfilter", RG,
     "            stern = [b for b in stern if hat_spalte(b, c)]\n", "            stern = list(stern)\n"),
    ("Stern ohne Pruefung der Basisspalte", RG,
     "        if len(stern) != 1 or hat_spalte(stern[0], c) is False:", "        if len(stern) != 1:"),
    ("Kein Schutz gegen Sicht-Kreise", RG,
     '        if a != "sicht" or tiefe >= 5:', '        if a != "sicht":'),
    ("Alter Graph ohne Herkunft stuerzt ab", RG,
     "                herkunft_cache[oid] = []   # Graph vor Fassung 4: keine Herkunft", "                raise"),
    ("Herkunft nicht in den Graphen geschrieben", ST,
     '    g.executemany("INSERT INTO herkunft VALUES (?,?,?,?)", herkunft_zeilen)\n', ""),
    ("Komma-Tabellen fehlen in 'nutzt' (YAML)", PA,
     '        nutzt = sorted((set(nutzt) | set(herkunft.pop("tabellen"))) - {voll})',
     '        herkunft.pop("tabellen")'),
    ("Komma-Tabellen fehlen in 'nutzt' (DDL)", PA,
     '        nutzt = sorted(set(nutzt) | set(herkunft.pop("tabellen")))', '        herkunft.pop("tabellen")'),
    ("Herkunft trotz UNION", PA, "    if _MENGE.search(flach):\n        return leer\n", ""),
    ("Herkunft trotz CTE", PA, '    if re.match(r"[\\s(]*WITH\\b", roh, re.I):\n        return leer\n', ""),
    ("Herkunft aus Ausdruecken", PA,
     "        if not re.fullmatch(_ID, ausdruck.strip()):\n            continue\n", ""),
    ("Unterabfrage zaehlt nicht als FROM-Eintrag", PA,
     '            tabellen.append("")   # Unterabfrage: zaehlt, ist aber keine Tabelle\n', ""),
    # Begriffsrunde und Zeiten (2026-11-08)
    ("Rueckfall der Begriffsrunde wieder still", RG, "        grund.append(warum)\n", "        pass\n"),
    ("JSON nur ab der ersten Klammer", RG, '        i = t.find("{", i + 1)\n', "        i = -1\n"),
    ("Begriffe als Zeichenkette verworfen", RG,
     '    if isinstance(wert, str):\n        wert = re.split(r"[,;\\n]", wert)\n', ""),
    ("Nackte Liste verworfen", RG, "    if wert is None:\n        m = re.search", "    if False:\n        m = re.search"),
    ("Modellzeit je Runde fehlt", RG, '            zeiten["modell"].append(round(time.monotonic() - t0, 2))\n', ""),
    ("DDL-Spaltenliste behaelt die Herkunft", PA,
     '            herkunft = {"spalten": {}, "stern": []}   # (die FROM-Liste ist oben schon uebernommen)\n', ""),
    ("Keine Runde fuer unbelegte Joins", RG,
     '            if pr["ok"] and pr["unbelegte_joins"] and not join_runde:', "            if False:"),
    ("Join-Runde ohne Deckel", RG,
     '            if pr["ok"] and pr["unbelegte_joins"] and not join_runde:', '            if pr["ok"] and pr["unbelegte_joins"]:'),
    ("Join-Runde darf verschlechtern", RG,
     '        if gueltig_vor_join is not None and (ergebnis is None or not ergebnis["pruefung"]["ok"]):',
     "        if False:"),
    ("Prompt erlaubt erfundene Joins", RG, '"VERMUTET markierte Beziehung nur, wenn nötig – dann nennst du sie unter ANNAHMEN. ERFINDE KEINE "',
     '"VERMUTET markierte Beziehung nur, wenn nötig – dann nennst du sie unter ANNAHMEN. "'),
    ("Vorbehalt fehlt in der Werkzeugausgabe", MN, "    if pr.get(\"ok\") and unbelegt:", "    if False:"),
    # ── Begleitdokumente / Hauswissen (2026-11-08)
    ("Dokumente als SQL gelesen", PA, "    if str(pfad).lower().endswith(DOK_ENDUNGEN):", "    if False:"),
    ("Markdown-Ueberschrift nur mit Leerzeile erkannt", PA,
     '            if not im_code and re.match(r"#{1,6}\\s", z):', "            if False:"),
    ("'#' im Codeblock als Ueberschrift", PA,
     '            if not im_code and re.match(r"#{1,6}\\s", z):', '            if re.match(r"#{1,6}\\s", z):'),
    ("Dokument ohne Text still angenommen", PA,
     '        raise ValueError("kein lesbarer Text (gescanntes PDF oder nur Bilder?)")', "        return []"),
    ("Abschnitte ungedeckelt", PA, "        while len(t) > DOK_TEIL:", "        while False:"),
    ("Dokument ohne Schema-Zuordnung", ST,
     '            q = quelle_von(datei) or ""\n            teile = [t for t in', '            q = ""\n            teile = [t for t in'),
    ("Hauswissen ungefiltert (fremde Schemata)", RG, '    filt, werte = _filter(erlaubt, "d.quelle")', '    filt, werte = "", []'),
    ("Alter Graph ohne Dokument-Tabelle wirft", RG,
     'f"WHERE dokument_fts MATCH ?{filt} ORDER BY s LIMIT ?", [ausdruck] + werte + [limit]).fetchall()\n    except sqlite3.OperationalError:',
     'f"WHERE dokument_fts MATCH ?{filt} ORDER BY s LIMIT ?", [ausdruck] + werte + [limit]).fetchall()\n    except KeyError:'),
    ("Codezaun im Hauswissen nicht entschaerft", RG, '        text = a["text"].replace(_ZAUN, "\'" * 3)', '        text = a["text"]'),
    ("Genannte Tabellen kein Anker", RG,
     "            treffer = [(o, oben) for o in genannt if o not in vorhanden] + treffer", "            treffer = treffer"),
    ("Begriffsrunde ohne Hauswissen", RG,
     "        begriffe, quelle = await begriffe_ermitteln(con, frage, modell_begriffe, erlaubt, hauswissen_text(hw_frage),",
     "        begriffe, quelle = await begriffe_ermitteln(con, frage, modell_begriffe, erlaubt, '',"),
    ("Begriffsrunde wieder mit Denken", RG,
     "    if not denken and isinstance(provider, llm.OpenAICompatibleProvider):", "    if False:"),
    ("Begriffs-Weiche denkt doch", RG, "    return await _modell(auftrag, system, denken=False)",
     "    return await _modell(auftrag, system, denken=True)"),
    ("SQL-Runde ohne Denken", RG, "async def _modell(auftrag: str, system: str, denken: bool = True) -> str:",
     "async def _modell(auftrag: str, system: str, denken: bool = False) -> str:"),
    ("Kette nimmt fuer Begriffe das denkende Modell", RG,
     "        modell_begriffe = _modell_ohne_denken if modell is _modell else modell",
     "        modell_begriffe = modell"),
    ("SQL-Runde ohne Hauswissen", RG, '        hw_text = ("\\n\\n" + hauswissen_text(hw)) if hw else ""', '        hw_text = ""'),
    ("Ergebnis verschweigt das Hauswissen", RG,
     '                "hauswissen": [{"titel": a["titel"], "nr": a["nr"]} for a in hw],', '                "hauswissen": [],'),
    ("Endungslisten laufen auseinander", EI, 'DOK_ENDUNGEN = (".md", ".docx", ".pdf")', 'DOK_ENDUNGEN = (".md", ".docx")'),
    # Gleichwertige Objekte (Sicht 1:1 ueber einer Tabelle)
    ("Gleichwertig ohne volle Spaltenabdeckung", RG,
     "            if stern or (v_spalten and woher >= v_spalten and aus_t >= t_spalten):",
     "            if stern or (v_spalten and woher >= v_spalten):"),
    ("Gleichwertig trotz Ausdrucksspalte", RG,
     "            if stern or (v_spalten and woher >= v_spalten and aus_t >= t_spalten):",
     "            if stern or (v_spalten and aus_t >= t_spalten):"),
    ("Gleichwertig ueber die Schemagrenze", RG,
     """            "AND t.art='tabelle' AND COALESCE(v.schema,'')=COALESCE(t.schema,'')", menge + menge).fetchall()""",
     """            "AND t.art='tabelle'", menge + menge).fetchall()"""),
    ("Zwei Sichten auf eine Tabelle: geraten", RG,
     "    return {t: vs[0] for t, vs in kandidaten.items() if len(vs) == 1}",
     "    return {t: vs[0] for t, vs in kandidaten.items()}"),
    ("Gleichwertig auch mit ungesuchter Sicht", RG,
     '            f"WHERE k.art=\'sicht\' AND k.von IN ({ph}) AND k.nach IN ({ph}) AND v.art=\'sicht\' "',
     '            f"WHERE k.art=\'sicht\' AND (k.von IN ({ph}) OR 1) AND k.nach IN ({ph}) AND v.art=\'sicht\' "'),
    ("Zusammenlegen: Sicht behaelt ihren eigenen Platz", RG,
     "        ziel = paar.get(o, o)\n        if ziel in gesehen:",
     "        if o in paar:\n            continue\n        ziel = o\n        if ziel in gesehen:"),
    ("Ausschnitt verschweigt die Gleichwertigkeit", RG,
     "        if gt:\n            zeilen.append(f\"  Sicht {t['name']} zeigt ALLE",
     "        if False:\n            zeilen.append(f\"  Sicht {t['name']} zeigt ALLE"),
    ("Nachforderung legt nicht zusammen", RG,
     "                    ids = [i for i in ids if i not in paar]\n", ""),
    # Schema-Praefix
    ("Praefix wirkt nicht auf die Suche", RG,
     "    pf, pw = _praefix_filter(praefixe)\n    filt, werte = filt + pf, werte + pw\n    try:",
     "    try:"),
    ("Praefix wirkt nicht auf genannte Tabellen", RG,
     "    pf, pw = _praefix_filter(praefixe)\n    filt, werte = filt + pf, werte + pw\n    # Wortanfang",
     "    # Wortanfang"),
    ("Kette reicht den Praefix nicht an die Suche", RG,
     "        treffer = await asyncio.to_thread(suche, con, begriffe, MAX_TREFFER, erlaubt, praefixe)",
     "        treffer = await asyncio.to_thread(suche, con, begriffe, MAX_TREFFER, erlaubt)"),
    ("Ungueltiger Praefix wird still zu 'alle'", RG,
     '            raise ValueError("Ungültige Auswahl des Schema-Präfixes.")\n        out.add',
     '            return None\n        out.add'),
    ("Kette meldet die Schemamischung nicht", RG,
     '                "praefixe_kontext": dict(sorted(Counter(t["schema"] for t in tabs.values()).items())),',
     '                "praefixe_kontext": {},'),
    ("Mischung im SQL nicht gezaehlt", RG,
     '                "praefixe_sql": praefixe_im_sql(con, (ergebnis.get("pruefung") or {}).get("tabellen") or [], erlaubt),',
     '                "praefixe_sql": {},'),
    ("Mischung im SQL: nur die erste Tabelle gezaehlt", RG,
     "            zaehl[r[0]] += 1\n    return dict(sorted(zaehl.items()))",
     "            zaehl[r[0]] += 1\n            break\n    return dict(sorted(zaehl.items()))"),
    ("Werkzeug: Hinweis am Ausschnitt statt am SQL", MN,
     '    pk = erg.get("praefixe_sql") or {}', '    pk = erg.get("praefixe_kontext") or {}'),
    ("Werkzeug: Mischhinweis fehlt", MN,
     "    if len(pk) > 1 and not erg.get(\"praefixe\"):", "    if False:"),
    ("Werkzeug: Praefix nicht geprueft", MN,
     "            praefixe = rag.praefixe_normal(praefix or None)\n        except ValueError as e:\n            return str(e)",
     "            praefixe = None\n        except ValueError as e:\n            return str(e)"),
    # Namensnaehe im Hauswissen
    ("Namensnaehe: wieder die ersten sechs", RG,
     "        if len(eindeutig) <= limit:\n", "        if True:\n"),
    ("Namensnaehe: Name ohne Begriff zaehlt doch", RG,
     "        gesamt.extend((o, pkt) for o, pkt in sorted(punkte.items(), key=lambda kv: -kv[1]) if pkt > 0)",
     "        gesamt.extend((o, pkt) for o, pkt in sorted(punkte.items(), key=lambda kv: -kv[1]))"),
    # Kodierung (ECHT 2026-11-11: UTF-16-Export als UTF-8 gelesen)
    ("Kodierung: SQL fest als UTF-8 gelesen", PA,
     '    dec = codecs.getincrementaldecoder(kodierung(pfad))(errors="replace")',
     '    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")'),
    ("Kodierung: YAML fest als UTF-8 gelesen", PA,
     '    with open(pfad, encoding=kodierung(pfad), errors="replace") as f:\n        text = f.read()',
     '    with open(pfad, encoding="utf-8", errors="replace") as f:\n        text = f.read()'),
    ("Kodierung: Markdown fest als UTF-8 gelesen", PA,
     '        with open(pfad, encoding=kodierung(pfad), errors="replace") as f:\n            zeilen',
     '        with open(pfad, encoding="utf-8", errors="replace") as f:\n            zeilen'),
    ("Kodierung: UTF-16-Marke nicht ausgewertet", PA,
     "    if kopf.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):", "    if False:"),
    ("Kodierung: UTF-8-Marke bleibt im Text", PA,
     "    if kopf.startswith(codecs.BOM_UTF8):", "    if False:"),
    ("Kodierung: UTF-16-LE ohne Marke nicht erkannt", PA,
     "        if ungerade * 2 >= paare and gerade * 20 <= paare:", "        if False:"),
    ("Kodierung: UTF-16-BE ohne Marke nicht erkannt", PA,
     "        if gerade * 2 >= paare and ungerade * 20 <= paare:", "        if False:"),
    ("Parser-Fassung nicht hochgezaehlt", PA, "FASSUNG = 6\n", "FASSUNG = 5\n"),
    # Trenner
    ("GO am Fensteranfang wird ueberlesen", PA,
     '                    if not (pos > 0 and puf[pos - 1] == "\\n" and _GO_ZEILE.match(puf, pos, grenze)):',
     '                    if True:'),
    ("Zeilenkommentar verschluckt die GO-Zeile dahinter", PA,
     r"""|--[^\n]*+\n(?![ \t]*GO\b)|/\*.*?\*/|-(?!-)""", r"""|--[^\n]*+\n|/\*.*?\*/|-(?!-)"""),
    ("Kommentar fuellt den Kopf", PA,
     '            stueck = " " if kommentar else teil\n', '            stueck = teil\n'),
    ("Fuehrender Leerraum fuellt den Kopf", PA,
     "            if not self.kopf:\n                stueck = stueck.lstrip()\n", ""),
    # Hinweis "gelesen, aber ohne Struktur"
    ("Ohne Struktur: nicht ans Schema geschrieben", IX,
     'je[k]["ohne_struktur"] = leer.get(k, [])', 'je[k]["ohne_struktur"] = []'),
    ("Ohne Struktur: auch Dateien ohne jede Anweisung", IX,
     "        if n > 0:\n            aus.setdefault(finder(p), []).append(p)",
     "        if True:\n            aus.setdefault(finder(p), []).append(p)"),
    ("Ohne Struktur: Gesamtliste nennt ruhende Schemata", IX,
     '                               if not quellen or k in st["schemata"]]', '                               ]'),
    ("Ohne Struktur: aus dem Lauf statt aus dem Bestand", IX,
     "        leer = ohne_struktur(con, finder)\n", "        leer = ohne_struktur(con, finder) if todo else {}\n"),
]
DATEIEN = [PA, ST, IX, RG, MN, EI, "tests/test_schema_graph.py"]


def md5(p):
    return hashlib.md5((ROOT / p).read_bytes()).hexdigest()


def lauf():
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=600, cwd=str(ROOT), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    m = re.search(r"Bilanz: (\d+) OK, (\d+) FAIL", r.stdout)
    return (int(m.group(2)) if m and r.returncode != 2 else -1), r.returncode


def sichern():
    SICHERUNG.mkdir(mode=0o700, exist_ok=True)
    for d in DATEIEN:
        ziel = SICHERUNG / d.replace("/", "__")
        ziel.write_bytes((ROOT / d).read_bytes())
    (SICHERUNG / "laufmarke.json").write_text(json.dumps(DATEIEN))


def zurueck(grund: str) -> None:
    marke = SICHERUNG / "laufmarke.json"
    if not marke.exists():
        return
    for d in json.loads(marke.read_text()):
        q = SICHERUNG / d.replace("/", "__")
        if q.exists() and q.read_bytes() != (ROOT / d).read_bytes():
            (ROOT / d).write_bytes(q.read_bytes())
            print(f"  zurueckgenommen ({grund}): {d}")
    marke.unlink()


def main():
    fehlt = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlt:
        print("ABBRUCH: Proben fassen ungesicherte Dateien an: %s" % sorted(fehlt))
        return 2
    zurueck("Rueckstand eines abgebrochenen Laufs")
    vorher = {d: md5(d) for d in DATEIEN}
    f, rc = lauf()
    if f != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (f, rc))
        return 2
    print("Basislauf gruen.\n")
    sichern()
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            p = ROOT / datei
            t = p.read_text(encoding="utf-8")
            if t.count(alt) != 1:
                print("  ???  %-50s Anker %dx gefunden" % (name, t.count(alt)))
                continue
            p.write_text(t.replace(alt, neu), encoding="utf-8")
            try:
                f, rc = lauf()
            finally:
                p.write_bytes((SICHERUNG / datei.replace("/", "__")).read_bytes())
            if f > 0:
                beissen += 1
                print("  BISS %-50s %d FAIL" % (name, f))
            elif f < 0:
                print("  ABBR %-50s rc=%s (kein Biss: Lauf ohne Bilanz)" % (name, rc))
            else:
                print("  ZAHN %-50s 0 FAIL – beisst NICHT" % name)
    finally:
        zurueck("Ende")
    if {d: md5(d) for d in DATEIEN} != vorher:
        print("ABBRUCH: Dateien nicht byte-gleich")
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)" % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
