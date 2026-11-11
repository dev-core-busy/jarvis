#!/usr/bin/env python3
"""Gegenprobe zu den Waechtern des SQL-Assistenten (Zugang, Ablage, Seite,
Reiter, Chat-Auswahl):
beisst jeder Waechter, wenn die Zusage zurueckgedreht wird?

⚠ IM WEGWERF-BAUM, nicht im Arbeitsbaum: der Betreiber arbeitet parallel an
``main.py``/``i18n.js``, und ein Zurueckstellen aus einer Sicherung
ueberschriebe seine Aenderung waehrend des Laufs (Register, Short-Tracks-
Fragen 2026-11-06). Kopiert werden ``backend``, ``frontend``, ``tests``,
``skills``; ``node_modules`` wird verlinkt. Jede Probe patcht EINE Datei der
Kopie, laesst den zugehoerigen Waechter laufen und stellt die Kopie wieder her.

Gruener Basislauf in der Kopie zuerst – ohne gruene Basis ist keine
Gegenprobe deutbar. Ohne Bytecode (eine gleich grosse Sabotage in derselben
Sekunde liesse sonst eine veraltete .pyc laden).
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.

Teillauf: ``--teil 2/6`` faehrt jede sechste Probe ab der zweiten – so lassen
sich mehrere Teile nebeneinander fahren (jeder im eigenen Wegwerf-Baum). Die
Bilanz nennt dann den Teil; "alle beissen" gilt erst, wenn JEDER Teil lief.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

W_ZUG = ["python", "tests/test_schema_graph_zugang.py"]
W_GR = ["python", "tests/test_schema_graph.py"]
W_UI = ["node", "tests/test_sql_ui.js"]
W_ADM = ["node", "tests/test_sql_admin_ui.js"]
W_SF = ["node", "tests/test_sql_schemafilter_ui.js"]
WAECHTER = [W_ZUG, W_GR, W_UI, W_ADM, W_SF]

RG = "backend/schema_graph_rag.py"
EI = "backend/schema_graph_einstellungen.py"
IX = "backend/schema_graph_index.py"
DI = "backend/schema_graph_dienst.py"
MA = "backend/main.py"
ST = "backend/schema_graph_store.py"
AG = "backend/agent.py"
SK = "skills/schema_graph/main.py"
SJ = "frontend/js/sql.js"
SA = "frontend/js/sql_admin.js"
FD = "backend/schema_graph_dateien.py"
SB = "backend/sandbox.py"
SF = "frontend/js/sqlschemafilter.js"
CJ = "frontend/js/chat.js"

PROBEN = [
    # ── Sichtbarkeit im Graphen (Auswahl = erlaubt)
    ("Filter im SQL wirkungslos", RG, W_ZUG,
     '    if erlaubt is None:\n        return "", []\n    werte = sorted(str(x) for x in erlaubt)\n    if not werte:\n        return " AND 0", []',
     '    if True:\n        return "", []\n    werte = sorted(str(x) for x in erlaubt)\n    if not werte:\n        return " AND 0", []'),
    ("Nachbarn ungefiltert (fremder Durchgang)", RG, W_ZUG,
     "        for n, _art in _nachbarn(con, k, erlaubt):", "        for n, _art in _nachbarn(con, k):"),
    ("Tabelle laden ignoriert Erlaubnis", RG, W_ZUG,
     '    if erlaubt is not None and (o["quelle"] or "") not in erlaubt:\n        return None\n', ""),
    ("Pruefung findet fremde Tabellen", RG, W_ZUG,
     "                    o = finde_objekt(con, name, erlaubt)", "                    o = finde_objekt(con, name)"),
    ("Zweites BRAUCHE bricht sofort ab", RG, W_GR,
     "            if not a[\"sql\"]:\n                if format_runde:",
     "            if not a[\"sql\"]:\n                if a[\"brauche\"] and brauche_runde:\n                    return {\"fehler\": \"x\"}\n                if format_runde:"),
    ("Leere Auswahl fragt trotzdem das Modell", RG, W_ZUG,
     "    if erlaubt is not None and not erlaubt:\n        return {\"fehler\"",
     "    if False:\n        return {\"fehler\""),
    ("Status zaehlt nicht gewaehlte Schemata", DI, W_ZUG,
     '        if erlaubt is not None and q["id"] not in erlaubt:\n            continue\n', ""),
    ("Detail: 'referenziert von' ungefiltert", DI, W_ZUG,
     '        f"JOIN objekt o ON o.id=k.von WHERE k.nach=?{filt}", [t["id"]] + werte)]',
     '        "JOIN objekt o ON o.id=k.von WHERE k.nach=?", [t["id"]])]'),
    # ── Einstellungen
    ("Kennung ohne Pruefung (Weg hinaus)", EI, W_ZUG,
     "    if not isinstance(sid, str) or not _KENNUNG_RE.fullmatch(sid):", "    if not isinstance(sid, str):"),
    ("Auswahl nicht mit vorhandenen Schemata geschnitten", EI, W_ZUG,
     "    return {x.strip() for x in roh if isinstance(x, str) and x.strip() in bekannt}",
     "    return {x.strip() for x in roh if isinstance(x, str)}"),
    ("Umbenennen vergibt eine neue Kennung (Ordner verwaist)", EI, W_ZUG,
     '        sid = str(s.get("id") or "").strip()', '        sid = ""'),
    ("Doppelter Name akzeptiert", EI, W_ZUG, "        if name.lower() in namen:", "        if False:"),
    # ── Dateiablage
    ("Pfadteile ungeprueft (..)", FD, W_ZUG,
     '        if not x.strip() or x.strip() in (".", "..") or x.startswith(".") or len(x) > MAX_TEIL:', "        if not x.strip():"),
    ("Verknuepfung im Pfad gefolgt", FD, W_ZUG, "            if stat.S_ISLNK(os.lstat(p).st_mode):", "            if False:"),
    ("Abgebrochener Upload laesst Nebendatei liegen", FD, W_ZUG,
     "        if tmp.exists():\n            tmp.unlink()", "        pass"),
    ("ZIP: Zip-Slip still statt benannt", FD, W_ZUG,
     '            if roh.startswith("/") or ".." in stuecke or (len(roh) > 1 and roh[1] == ":"):', "            if False:"),
    ("ZIP liest Eintraege in den Speicher", FD, W_ZUG,
     "                with zf.open(info) as f:\n                    gespeichert.append(datei_speichern(sid, rel, f, endungen))",
     '                gespeichert.append(datei_speichern(sid, rel, __import__("io").BytesIO(zf.read(info)), endungen))'),
    ("Fremder Eigentuemer der Ablage endet als nackter Fehler", FD, W_ZUG,
     "            raise DateiFehler(_rechte_grund(p.parent if not p.exists() else p)) from None", "            raise"),
    ("ZIP ohne Platzreserve", FD, W_ZUG,
     "                if min_frei and shutil.disk_usage(basis).free - info.file_size < min_frei:", "                if False:"),
    # ── Indexlauf
    ("Freie Ordner: fehlender Ordner wird ausgetragen", IX, W_ZUG,
     '            schutz = tuple(o.rstrip("/") + "/" for o in fehlend) if ordner_schutz else ()', "            schutz = ()"),
    ("Feste Ordner: Geloeschtes bleibt im Graphen", IX, W_ZUG,
     '            schutz = tuple(o.rstrip("/") + "/" for o in fehlend) if ordner_schutz else ()',
     '            schutz = tuple(o.rstrip("/") + "/" for o in fehlend) or ("/",)'),
    ("Umzuordnung leitet nicht neu ab", IX, W_ZUG,
     "                     or nur_ableiten or sig_alt != sig)", "                     or nur_ableiten)"),
    ("Parser-Fassungswechsel ignoriert", IX, W_ZUG,
     "        neu_lesen = bool(bekannt) and store.roh_fassung(con) != parser.FASSUNG", "        neu_lesen = False"),
    ("Parser-Fassung nie vermerkt (liest jedes Mal alles)", IX, W_ZUG,
     "            store.roh_fassung_setzen(con, parser.FASSUNG)", "            pass"),
    ("Anstoss waehrend eines Laufs verworfen", IX, W_ZUG,
     '            _nachlauf = neu\n            return "vorgemerkt"', '            return "vorgemerkt"'),
    ("Fehlschlag verliert den Nachlauf", IX, W_ZUG,
     '                print(f"[SchemaGraph] Erfassung fehlgeschlagen: {e}", flush=True)', "                return"),
    # ── Werkzeuge
    ("Werkzeug ohne Auftraggeber erlaubt", SK, W_GR,
     '    if not user:\n        return {"darf": False', '    if False:\n        return {"darf": False'),
    ("Werkzeug reicht die Sichtbarkeit nicht weiter", SK, W_GR,
     "        info = dienst.tabelle_info(con, name, erlaubt)", "        info = dienst.tabelle_info(con, name, None)"),
    ("Werkzeug schneidet die Auswahl nicht", SK, W_GR,
     '    z["erlaubt"] = set(z.get("erlaubt") or set()) & gewaehlt', '    z["erlaubt"] = set(z.get("erlaubt") or set())'),
    ("Erfassen aus dem Chat auch fuer Nicht-Admins", SK, W_GR,
     '            if not z.get("admin"):', "            if False:"),
    # ── main.py
    ("Endpunkt nur an require_auth", MA, W_ZUG,
     'async def sql_tabelle(name: str = "", schemata: str = "", user: str = Depends(require_schema_access)):',
     'async def sql_tabelle(name: str = "", schemata: str = "", user: str = Depends(require_auth)):'),
    ("Frage sieht alle Schemata statt der Auswahl", MA, W_ZUG,
     '    erlaubt = await asyncio.to_thread(_sql_auswahl, body.get("schemata"))',
     '    erlaubt = {s["id"] for s in cfg["schemata"]}'),
    ("Freigabe leer = alle", MA, W_ZUG,
     "    grp = config.get_setting(\"schema_allowed_group\", \"\").strip()\n    if not users_raw and not grp:\n        return False",
     "    grp = config.get_setting(\"schema_allowed_group\", \"\").strip()\n    if not users_raw and not grp:\n        return True"),
    ("/api/me ohne schema", MA, W_ZUG,
     '            "schema": _user_may_use_schema(user) and _skill_active(_SCHEMA_SKILL),',
     '            "schema": _skill_active(_SCHEMA_SKILL),'),
    ("schema_zugang ohne Freigabe-Schranke", MA, W_ZUG,
     '    ids = {s["id"] for s in _schema_cfg()["schemata"]} if darf else set()',
     '    ids = {s["id"] for s in _schema_cfg()["schemata"]}'),
    ("ZIP ueber den RAM-Entpacker von /wissen", MA, W_ZUG,
     "                gesp, abgl = await asyncio.to_thread(_sgf.zip_entpacken, sid, ordner_rel, f.file,",
     "                gesp, abgl = await asyncio.to_thread(_kb_unpack_zip, sid, ordner_rel, f.file,"),
    ("Feste Ordner mit Ordnerschutz erfasst", MA, W_ZUG,
     "                          ordner_schutz=False, nur=None if nur is None else set(nur))",
     "                          ordner_schutz=True, nur=None if nur is None else set(nur))"),
    ("Schema samt Dateien ohne Bestaetigung geloescht", MA, W_ZUG,
     '    if weg and body.get("loeschen_bestaetigt") is not True:', "    if False:"),
    ("WebSocket reicht die Auswahl nicht weiter", MA, W_ZUG, "                        sql_schemata=sql_schemata,\n", ""),
    ("Sitzung vergisst die Auswahl", MA, W_ZUG,
     '        cs.save_sql_schemata(user, sid, body.get("sql_schemata"))', "        pass"),
    # ── agent.py
    ("Werkzeugangebot ohne schema-Filter", AG, W_ZUG,
     '            if name.startswith("schema_") and not schema_ok:\n                continue\n', ""),
    ("Angebot auch ohne Auswahl", AG, W_ZUG,
     '        schema_ok = bool(getattr(self, "_current_sql_schemata", None))', "        schema_ok = True"),
    ("Modell darf die Auswahl erweitern (setdefault)", AG, W_ZUG,
     "                exec_args['_sql_schemata'] = list(getattr(self, '_current_sql_schemata', None) or [])",
     "                exec_args.setdefault('_sql_schemata', list(getattr(self, '_current_sql_schemata', None) or []))"),
    ("Sub-Agent erbt die Auswahl nicht", AG, W_ZUG, "            agent._current_sql_schemata = sql_schemata\n", ""),
    # ── Sandbox
    ("Ablage fuer Dateiwerkzeuge offen", SB, W_ZUG, '    "data/sql_schema_graph",\n    # Claude Subagent', "    # Claude Subagent"),
    ("Shell darf die Ablage lesen", SB, W_ZUG, "    r'sql_schema_graph\\b|'\n", ""),
    # ── Seite
    ("Seite maskiert nicht", SJ, W_UI,
     "    function esc(s) {\n        return String(s == null ? '' : s).replace(/[&<>\"]/g,",
     "    function esc(s) {\n        return String(s == null ? '' : s); String('').replace(/[&<>\"]/g,"),
    ("Seite: Fehler verschwindet von selbst", SJ, W_UI,
     "        if (art === 'ok') e._tm = setTimeout(", "        e._tm = setTimeout("),
    ("Rote Pille sieht gruen aus", SJ, W_UI,
     "            pill.className = 'sq-pill is-bad';", "            pill.className = 'sq-pill is-ok';"),
    ("Dialekt-Vorgabe geht wieder verloren", SJ, W_UI,
     "        var akt = _dialektGewaehlt ? sel.value : vorgabe;", "        var akt = sel.value || vorgabe;"),
    ("Knopf frei ohne Auswahl", SJ, W_UI,
     "        return !_laeuft && !!(f && f.value.trim()) && !!(_status && _status.vorhanden\n            && gewaehlt().length);",
     "        return !_laeuft && !!(f && f.value.trim()) && !!(_status && _status.vorhanden);"),
    ("Frage ohne Auswahl gesendet", SJ, W_UI,
     "dialekt: $('sq-dialekt').value, schemata: gewaehlt(), praefixe: praefixWahl() }) })",
     "dialekt: $('sq-dialekt').value, praefixe: praefixWahl() }) })"),
    # ── Schema-Praefix auf der Seite
    ("Frage ohne Praefix gesendet", SJ, W_UI,
     "schemata: gewaehlt(), praefixe: praefixWahl() }) })", "schemata: gewaehlt(), praefixe: [] }) })"),
    ("Praefix-Auswahl auch bei einem Schema", SJ, W_UI,
     "        var zeigen = liste.length > 1;", "        var zeigen = true;"),
    ("Abgewaehlte Ablage liefert Praefixe", SJ, W_UI,
     "            if (!_auswahl || !_auswahl.has(q.id)) return;\n", ""),
    ("Mischhinweis am Ausschnitt statt am SQL", SJ, W_UI,
     "        var pk = d.praefixe_sql || {};", "        var pk = d.praefixe_kontext || {};"),
    ("Mischhinweis fehlt", SJ, W_UI,
     "        } else if (namen.length > 1) {", "        } else if (false) {"),
    ("'nur X fragen' fragt nicht neu", SJ, W_UI,
     "                praefixSetzen(b.getAttribute('data-praefix'));\n                fragen();",
     "                praefixSetzen(b.getAttribute('data-praefix'));"),
    ("Zusammengelegtes unmaskiert", SJ, W_UI,
     "return esc(T('sql.same', '{s} zeigt alle Spalten von {t}', { s: g.sicht, t: g.tabelle }));",
     "return T('sql.same', '{s} zeigt alle Spalten von {t}', { s: g.sicht, t: g.tabelle });"),
    ("Gemerkte Auswahl ignoriert", SJ, W_UI,
     "        if (!Array.isArray(gemerkt)) return new Set(ids);", "        return new Set(ids);"),
    ("Abwahl nicht gemerkt", SJ, W_UI, "                auswahlMerken();\n", ""),
    ("Suche ohne Auswahl", SJ, W_UI,
     "encodeURIComponent(q) + '&limit=25' + schemataParam())", "encodeURIComponent(q) + '&limit=25')"),
    ("Seite ohne Freigabe sichtbar", SJ, W_UI,
     "                if (!d.permissions || !d.permissions.schema) { toPortal(); return; }", ""),
    # ── Reiter
    ("Reiter: Fehler verschwindet von selbst", SA, W_ADM,
     "        if (art === 'ok') el._tm = setTimeout(", "        el._tm = setTimeout("),
    ("Reiter maskiert nicht", SA, W_ADM,
     "    function esc(s) {\n        return String(s == null ? '' : s).replace(/[&<>\"]/g,",
     "    function esc(s) {\n        return String(s == null ? '' : s); String('').replace(/[&<>\"]/g,"),
    ("Versteckte Dateien hochgeladen", SA, W_ADM,
     "            if (teile.some(function (x) { return x.charAt(0) === '.'; })) { gefiltert++; return; }", ""),
    ("Kein Endungsfilter vor dem Hochladen", SA, W_ADM,
     "            if (passt) nehmen.push(g); else gefiltert++;", "            nehmen.push(g);"),
    ("Pakete unbegrenzt", SA, W_ADM,
     "            if (akt.length && (akt.length >= PAKET_DATEIEN || bytes + g.datei.size > PAKET_BYTES)) {",
     "            if (false) {"),
    ("Ordner nur ein Stueck gelesen", SA, W_ADM,
     "                    alle = alle.concat(Array.prototype.slice.call(stueck));\n                    weiter();",
     "                    alle = alle.concat(Array.prototype.slice.call(stueck));\n                    Promise.all(alle.map(function (e) { return eintragLesen(e, pfad + entry.name + '/', out); })).then(function () { fertig(); });"),
    ("Dateifeld IM Ablagefeld (Rueckklick)", SA, W_ADM,
     "                    + '</div>'\n                    + '<input type=\"file\" class=\"sqadm-fin\" data-sid=\"' + esc(sid) + '\" multiple hidden>'",
     "                    + '<input type=\"file\" class=\"sqadm-fin\" data-sid=\"' + esc(sid) + '\" multiple hidden>'\n                    + '</div>'"),
    ("Datei ohne Rueckfrage geloescht", SA, W_ADM, "            if (!window.confirm(frage)) return Promise.resolve();\n", ""),
    ("Schema-Loeschung ohne Rueckfrage bestaetigt", SA, W_ADM,
     "                    if (window.confirm(t('sqladm.confirm_del',", "                    if (true || window.confirm(t('sqladm.confirm_del',"),
    ("Ergebnis nach dem Upload verschwindet (Klassenname)", SA, W_ADM,
     "var st2 = teil('sqadm-up-status'), fe2 = teil('sqadm-up-fehler');",
     "var st2 = teil('sqladm-up-status'), fe2 = teil('sqladm-up-fehler');"),
    ("Kuerzung der Dateiliste nicht beziffert", SA, W_ADM, "var hinweis = d.gekappt ?", "var hinweis = false ?"),
    # ── Begleitdokumente, Netzfehler, Pfade, Anzeige (2026-11-08)
    ("Upload ohne Begleitdokumente", MA, W_ZUG, "    endungen = _sge.upload_endungen(_sge.schema_von(cfg, sid))",
     "    endungen = _sge.endungen(_sge.schema_von(cfg, sid))"),
    ("Erfassung ohne Begleitdokumente", EI, W_ZUG, '             "muster": erfassungs_muster(s), "fk_ableiten": s["fk_ableiten"]}',
     '             "muster": s["dateimuster"], "fk_ableiten": s["fk_ableiten"]}'),
    ("Erfassungsmuster ohne Dokumente", EI, W_ZUG, '        if "*" + e not in teile:\n            teile.append("*" + e)', "        pass"),
    ("Leerzeichen am Ende abgeschnitten", FD, W_ZUG, '    s = str(rel or "").replace("\\\\", "/")\n', '    s = str(rel or "").replace("\\\\", "/").strip()\n'),
    ("Leerraum-Pfadteil zugelassen", FD, W_ZUG, '        if not x.strip() or x.strip() in (".", "..") or x.startswith(".") or len(x) > MAX_TEIL:',
     '        if not x or x in (".", "..") or x.startswith(".") or len(x) > MAX_TEIL:'),
    ("Seite: Netzfehler roh ('Failed to fetch')", SJ, W_UI, "            .catch(netzfehler(url))\n", ""),
    ("Reiter: Netzfehler roh ('Failed to fetch')", SA, W_ADM,
     "        return fetch(url, opt).catch(function () { throw new Error(netzText(url)); });", "        return fetch(url, opt);"),
    ("Vorbehalt sieht gruen aus", SJ, W_UI, "            pill.className = 'sq-pill is-warn';", "            pill.className = 'sq-pill is-ok';"),
    ("Hauswissen unmaskiert", SJ, W_UI, "+ hw.map(function (h) { return esc(h.titel) + ' ('", "+ hw.map(function (h) { return h.titel + ' ('"),
    ("Reiter filtert mit dem Dateimuster statt mit den Server-Endungen", SA, W_ADM,
     "            if (Array.isArray(vom) && vom.length) return vom.slice();\n", ""),
    # ── Chat-Auswahl
    ("Chat-Auswahl: Vorgabe alle statt keins", SF, W_SF,
     "            if (_gewuenscht) { _an = new Set(_gewuenscht); _gewuenscht = null; }",
     "            _an = _gewuenscht ? new Set(_gewuenscht) : new Set(_schemata.map(function (s) { return s.id; })); _gewuenscht = null;"),
    ("Chat-Auswahl sichtbar ohne Freigabe", SF, W_SF,
     "            if (liste === null) { wrap.hidden = true;", "            if (liste === null) { wrap.hidden = false;"),
    ("Chat-Auswahl behaelt Unbekanntes", SF, W_SF,
     "            _an = new Set(Array.from(_an).filter(function (x) { return ids.has(x); }));", ""),
    ("Chat-Auswahl maskiert nicht", SF, W_SF,
     "    function esc(s) {\n        return String(s == null ? '' : s).replace(/[&<>\"]/g,",
     "    function esc(s) {\n        return String(s == null ? '' : s); String('').replace(/[&<>\"]/g,"),
    ("chat.js schickt die Auswahl nicht", CJ, W_ZUG, "            if (_sq.length) msg.sql_schemata = _sq;", ""),
    # Ordnerrechte (Pentest 2026-11-08: Zwischenordner auf ECHT 0755)
    ("Zwischenordner wieder per mkdir(parents=True)", FD, W_ZUG, "        _ordner_kette(basis, ziel.parent)\n",
     "        ziel.parent.mkdir(mode=DIR_MODUS, parents=True, exist_ok=True)\n"),
    ("Bestand: zu offene Rechte bleiben", FD, W_ZUG, "                if stat.S_IMODE(st.st_mode) & ~soll:",
     "                if False:"),
    ("Bestand: Heilung folgt Verknuepfungen", FD, W_ZUG,
     "                if stat.S_ISLNK(st.st_mode) or st.st_uid != ich", "                if st.st_uid != ich"),
    ("Altbestand-Ordner nicht nachgezogen", FD, W_ZUG, "            os.chmod(p, DIR_MODUS)   # auch einen Altbestand nachziehen\n", "            pass\n"),
    # ── Einstellungen und Erfassung AM SCHEMA (Vorgabe 2026-11-10)
    ("Schema-Feld auf oberster Ebene still verworfen", EI, W_ZUG, "    if veraltet:\n        fehler.append(", "    if False:\n        fehler.append("),
    ("Altfassung: Wert geht nicht in die Schemata", EI, W_ZUG,
     '    if alt and isinstance(roh.get("schemata"), list):', "    if False:"),
    ("Altfassung ueberschreibt das eigene Feld des Schemas", EI, W_ZUG,
     "[{**alt, **s} if isinstance(s, dict) else s", "[{**s, **alt} if isinstance(s, dict) else s"),
    ("Frage: kleinste statt groesste Hoechstzahl", EI, W_ZUG,
     '            "max_tabellen": max(s["max_tabellen"] for s in gewaehlt),', '            "max_tabellen": min(s["max_tabellen"] for s in gewaehlt),'),
    ("Frage: Dialekt des letzten statt des ersten Schemas", EI, W_ZUG,
     '    return {"dialekt": gewaehlt[0]["dialekt"],', '    return {"dialekt": gewaehlt[-1]["dialekt"],'),
    ("Frage: Auswahl ignoriert (alle Schemata zaehlen)", EI, W_ZUG,
     '    gewaehlt = [s for s in cfg.get("schemata") or [] if s.get("id") in ids]', '    gewaehlt = [s for s in cfg.get("schemata") or []]'),
    ("Lauf: EIN Muster fuer alle Quellen", IX, W_ZUG,
     '        plan = [(o, muster_liste(q.get("muster") or muster), str(q.get("id") or ""))',
     '        plan = [(o, muster_liste(muster), str(q.get("id") or ""))'),
    ("Lauf: Beschraenkung auf ein Schema wirkungslos", IX, W_ZUG,
     "    aktiv = None if (nur is None or not quellen) else {str(x) for x in nur}", "    aktiv = None"),
    ("Lauf: ruhendes Schema wird ausgetragen", IX, W_ZUG,
     "\n                   and not (ruhend and os.path.normpath(p).startswith(ruhend))]", "]"),
    ("Lauf: Ableiten-Schalter fehlt in der Signatur", IX, W_ZUG,
     '                              bool(q.get("fk_ableiten", fk_ableiten)))', "                              True)"),
    ("Lauf: Ableiten fuer alle statt je Quelle", IX, W_ZUG, "fk_quellen=fk_quellen)", "fk_quellen=None)"),
    ("Lauf: neue Parser-Fassung bleibt auf ein Schema beschraenkt", IX, W_ZUG,
     "            aktiv = None\n        # Nach der Entscheidung", "            pass\n        # Nach der Entscheidung"),
    ("Lauf: Ergebnis des anderen Schemas vergessen", IX, W_ZUG,
     '"je_schema": {k: v for k, v in (vorher if isinstance(vorher, dict) else {}).items()\n'
     '                                        if k in kennungen and isinstance(v, dict)}}', '"je_schema": {}}'),
    ("Lauf: Ergebnis steht nicht je Schema", IX, W_ZUG,
     '                zs["ergebnis"] = st["ergebnis"]\n', ""),
    ("Nachlauf: zweite Vormerkung verdraengt die erste", IX, W_ZUG,
     '                neu["nur"] = _nur_vereinen(_nachlauf.get("nur"), neu.get("nur"))', "                pass"),
    ("Ableiten Regel 1 (kunde_id) fuer alle Schemata", ST, W_ZUG,
     "        if (oid, name_l) in fk_spalten or (nur_oids is not None and oid not in nur_oids):\n            continue\n        m = _ID_ENDUNG",
     "        if (oid, name_l) in fk_spalten:\n            continue\n        m = _ID_ENDUNG"),
    ("Ableiten Regel 2 (gleicher Schluesselname) fuer alle Schemata", ST, W_ZUG,
     "        if not ziele or (oid, name_l) in fk_spalten or (nur_oids is not None and oid not in nur_oids):",
     "        if not ziele or (oid, name_l) in fk_spalten:"),
    ("Upload erfasst alle Schemata", MA, W_ZUG,
     "    erfassung = _sql_erfassen_anstossen(cfg, {sid}) if gespeichert else None",
     "    erfassung = _sql_erfassen_anstossen(cfg) if gespeichert else None"),
    ("Start am Schema erfasst alle", MA, W_ZUG,
     "    antwort = await asyncio.to_thread(_sql_erfassen_anstossen, cfg, {sid})",
     "    antwort = await asyncio.to_thread(_sql_erfassen_anstossen, cfg)"),
    ("Beschraenkung wird nicht durchgereicht", MA, W_ZUG,
     "                          ordner_schutz=False, nur=None if nur is None else set(nur))", "                          ordner_schutz=False)"),
    ("Frage (Seite) mit den Vorgaben statt mit dem Schema", MA, W_ZUG,
     "    vorgabe = _sge.fuer_frage(cfg, erlaubt)", "    vorgabe = dict(_sge.SCHEMA_VORGABEN)"),
    ("Chat: Start ohne Auswahl erfasst trotzdem", SK, W_GR,
     '            if not z["erlaubt"]:\n                return ("Kein SQL-Schema gewählt – erfasst wird je Schema.',
     '            if False:\n                return ("Kein SQL-Schema gewählt – erfasst wird je Schema.'),
    ("Chat: Start erfasst alle statt der gewaehlten", SK, W_GR,
     'asyncio.to_thread(_m._sql_erfassen_anstossen, cfg, set(z["erlaubt"]))', "asyncio.to_thread(_m._sql_erfassen_anstossen, cfg)"),
    ("Chat: Frage mit den Vorgaben statt mit dem Schema", SK, W_GR,
     '        vorgabe = sge.fuer_frage(cfg, z["erlaubt"])', "        vorgabe = dict(sge.SCHEMA_VORGABEN)"),
    ("Reiter: ein Lauf erscheint in JEDEM Schema", SA, W_ADM,
     "            var laeuft = !!st.laeuft && (!Array.isArray(st.schemata) || st.schemata.indexOf(sid) >= 0);",
     "            var laeuft = !!st.laeuft;"),
    ("Reiter: Start ohne Schema in der Adresse", SA, W_ADM,
     "            return holen('/api/sql/admin/schema/' + encodeURIComponent(sid) + '/index', { method: 'POST', headers: kopf() })",
     "            return holen('/api/sql/admin/index', { method: 'POST', headers: kopf() })"),
    ("Reiter: Vormerkung nicht gezeigt", SA, W_ADM,
     "            var wartet = !laeuft && !!vm && (vm.nur == null || vm.nur.indexOf(sid) >= 0);", "            var wartet = false;"),
    ("Reiter: Nachladen verwirft ungespeicherte Eingaben", SA, W_ADM,
     "                if (!halten) self._schemata = kopie(d.cfg.schemata || []);", "                self._schemata = kopie(d.cfg.schemata || []);"),
    ("Reiter: der Takt zeichnet die Container neu", SA, W_ADM,
     "                    self._zeichneErfassung();\n                    // Zum Ende Graph",
     "                    self._zeichneSchemata();\n                    // Zum Ende Graph"),
    ("Reiter: Dialekt des Schemas wird nicht gesammelt", SA, W_ADM,
     "                           dialekt: feld('sqadm-dialekt').value,\n", ""),
    ("Reiter: Hoechstzahl des Schemas wird nicht gesammelt", SA, W_ADM,
     "                           max_spalten: Number(feld('sqadm-maxsp').value),\n", ""),
    ("Reiter: Speichern-Meldung im alten (weggezeichneten) Element", SA, W_ADM,
     "            function melde(msg, art) { status(self._statusEl(ziel), msg, art); }",
     "            var fest = self._statusEl(ziel);\n            function melde(msg, art) { status(fest, msg, art); }"),
    ("Reiter: Klappzustand wird nicht gemerkt", SA, W_ADM,
     "            try { window.localStorage.setItem(klappSchluessel(sid), zu ? '1' : '0'); } catch (e) { /* nur Komfort */ }", ""),
    ("Reiter: neues Schema ohne die Vorgaben des Servers", SA, W_ADM,
     "                self._schemata.push(Object.assign({ id: '', name: '' }, kopie(self._vorgaben || {})));",
     "                self._schemata.push({ id: '', name: '' });"),
    ("Reiter: Speichern zeichnet nicht sofort (laufendes Nachladen stellt das alte Formular zurueck)", SA, W_ADM,
     "                self._zeichne(false);\n                // Zahlen und Graph neu holen", "                // Zahlen und Graph neu holen"),
    ("Reiter: Ergebniswort roh aus dem Status (ohne Umlaut)", SA, W_ADM,
     "{ e: ergebnisWort(L.je.ergebnis), d: L.je.ende || '?',", "{ e: L.je.ergebnis, d: L.je.ende || '?',"),
    ("Seite: Dialekt-Vorgabe nicht aus dem gewaehlten Schema", SJ, W_UI,
     "        return (gew[0] && gew[0].dialekt) || 'allgemein';", "        return 'allgemein';"),
    ("Seite: Dialekt-Vorgabe folgt der Auswahl nicht", SJ, W_UI,
     "                zeichneQuellen();\n                zeichneDialekte();\n                zeichnePraefixe();",
     "                zeichneQuellen();\n                zeichnePraefixe();"),
]

KOPIEREN = ["backend", "frontend", "tests", "skills"]


def lauf(baum: Path, w) -> tuple[int, int]:
    art, datei = w
    cmd = [PY, "-B", datei] if art == "python" else ["node", datei]
    r = subprocess.run(cmd, cwd=baum, capture_output=True, text=True, timeout=300,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    text = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)
    m = re.search(r"(?:Bilanz|Ergebnis): (\d+) OK, (\d+) FAIL", text)
    return (int(m.group(2)) if m and r.returncode != 2 else -1), r.returncode


def teil_auswahl(argv) -> tuple[list, str]:
    """``--teil i/n`` -> (Proben dieses Teils, Beschriftung). Ohne Angabe alle."""
    if "--teil" not in argv:
        return list(PROBEN), ""
    m = re.fullmatch(r"(\d+)/(\d+)", argv[argv.index("--teil") + 1] if argv.index("--teil") + 1 < len(argv) else "")
    if not m or not 1 <= int(m.group(1)) <= int(m.group(2)):
        print("ABBRUCH: --teil erwartet i/n mit 1 <= i <= n")
        raise SystemExit(2)
    i, n = int(m.group(1)), int(m.group(2))
    return [p for k, p in enumerate(PROBEN) if k % n == i - 1], " (Teil %d/%d)" % (i, n)


def main() -> int:
    proben, teil = teil_auswahl(sys.argv[1:])
    fehlt = {p[1] for p in PROBEN} - {p[1] for p in PROBEN if (ROOT / p[1]).exists()}
    if fehlt:
        print("ABBRUCH: Dateien fehlen: %s" % sorted(fehlt))
        return 2
    baum = Path(tempfile.mkdtemp(prefix="gegen_sql_", dir=str(Path.home())))
    try:
        for d in KOPIEREN:
            shutil.copytree(ROOT / d, baum / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        os.symlink(ROOT / "node_modules", baum / "node_modules")
        for w in WAECHTER:
            f, rc = lauf(baum, w)
            if f != 0:
                print(f"ABBRUCH: Basislauf {w[1]} nicht gruen (FAIL={f}, rc={rc})")
                return 2
        print("Basislauf gruen (%d Waechter, im Wegwerf-Baum).\n" % len(WAECHTER), flush=True)
        beissen = 0
        for name, datei, w, alt, neu in proben:
            p = baum / datei
            t = p.read_text(encoding="utf-8")
            if t.count(alt) != 1:
                print("  ???  %-48s Anker %dx gefunden" % (name, t.count(alt)), flush=True)
                continue
            p.write_text(t.replace(alt, neu), encoding="utf-8")
            try:
                f, rc = lauf(baum, w)
            finally:
                p.write_text(t, encoding="utf-8")
            if f > 0:
                beissen += 1
                print("  BISS %-48s %2d FAIL (%s)" % (name, f, w[1].split("/")[-1]))
            elif f < 0:
                print("  ABBR %-48s rc=%s (kein Biss: ohne Bilanz)" % (name, rc))
            else:
                print("  ZAHN %-48s 0 FAIL – beisst NICHT" % name)
            sys.stdout.flush()
        print("\n%d/%d Proben beissen%s (Arbeitsbaum unberuehrt)" % (beissen, len(proben), teil))
        return 0 if beissen == len(proben) else 1
    finally:
        shutil.rmtree(baum, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
