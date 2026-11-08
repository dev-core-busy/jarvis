"""SQL-Assistent (Schema-Graph): Frage in Alltagssprache -> gepruefte SQL-Abfrage.

Die Werkzeuge sind duenn; die Logik liegt in ``backend.schema_graph_*``
(Parser, Ablage, Indexlauf, GraphRAG, Dienst). Grund: der Indexlauf braucht ein
importierbares Modul fuer seine Arbeitsprozesse, und der Skill-Loader laedt
nur ``main.py`` als Datei – Geschwistermodule waeren nicht importierbar.

SCHRANKE wie auf der Seite /sql (``main.schema_zugang``): die Freigabe
(Sicherheit → Berechtigungen, Spalte „SQL-Assistent"). Was ein Werkzeug sieht,
ist die SCHEMA-AUSWAHL des Benutzers im Chat (neben den Wissensgruppen); der
Dispatch gibt sie als ``_sql_schemata`` mit, und hier wird sie mit den
vorhandenen Schemata geschnitten (seit 2026-11-07 ohne Wissensgruppen).
Ohne Auswahl bietet der Agent die Werkzeuge gar nicht erst an; ruft das Modell
sie trotzdem, kommt eine Abweisung. Der Auftraggeber kommt aus der
lauf-isolierten Bindung des Agenten (``agent._actor_cv``), nicht aus einem
Attribut des geteilten Agenten – zwei parallele Laeufe saehen sonst die Rechte
des jeweils anderen. Ohne Bindung: abgewiesen (fail-closed).

Alle Graph-Zugriffe laufen ueber ``asyncio.to_thread`` (SQLite und die
Breitensuche sind synchron). Erzeugtes SQL wird NIE ausgefuehrt.
"""
import asyncio

from backend.tools.base import BaseTool


def _zugang(auswahl=None) -> dict:
    """{"darf", "erlaubt", "admin", "user", "grund"} des LAUFENDEN Auftrags.

    ``auswahl``: die vom Dispatch gesetzte Schema-Auswahl (``_sql_schemata``).
    ``erlaubt`` ist ihr Schnitt mit den vorhandenen Schemata – ohne Auswahl leer.
    """
    try:
        from backend.agent import _actor_cv  # noqa: PLC0415
        gebunden = _actor_cv.get()
    except Exception:  # noqa: BLE001
        gebunden = None
    user = (gebunden[0] if gebunden else "") or ""
    if not user:
        return {"darf": False, "erlaubt": set(), "admin": False, "user": "",
                "grund": "Dieser Lauf hat keinen angemeldeten Auftraggeber."}
    try:
        from backend import main as _m  # noqa: PLC0415
        z = dict(_m.schema_zugang(user))
    except Exception as e:  # noqa: BLE001
        return {"darf": False, "erlaubt": set(), "admin": False, "user": user,
                "grund": f"Berechtigung nicht bestimmbar ({e})."}
    z["user"] = user
    gewaehlt = {x for x in (auswahl or []) if isinstance(x, str)}
    z["erlaubt"] = set(z.get("erlaubt") or set()) & gewaehlt
    if not z.get("darf"):
        z["grund"] = ("Der SQL-Assistent ist für dich nicht freigeschaltet (Einstellungen → "
                      "Sicherheit → Berechtigungen, Spalte „SQL-Assistent“).")
    elif not z["erlaubt"]:
        z["grund"] = ("Kein SQL-Schema gewählt. Der Benutzer wählt es im Chat neben den "
                      "Wissensgruppen aus (Auswahl „SQL-Schema“).")
    return z


def _cfg() -> dict:
    from backend import main as _m  # noqa: PLC0415
    return _m._schema_cfg()


def _ohne_graph() -> str:
    return ("Es gibt noch keinen Schema-Graphen. Er entsteht beim Erfassen der Schema-Dateien "
            "(Einstellungen → SQL-Assistent).")


def _oeffnen():
    from backend import schema_graph_store as store  # noqa: PLC0415
    return store.graph_lesen()


def _abgewiesen(z: dict) -> str:
    return "Zugriff verweigert: " + (z.get("grund") or "kein Zugang.")


class SchemaSqlTool(BaseTool):
    @property
    def name(self):
        return "schema_sql"

    @property
    def description(self):
        return ("Wandelt eine Frage zu Daten der erfassten Datenbank in EINE geprüfte, lesende "
                "SQL-Abfrage um (GraphRAG über das Schema: passende Tabellen, Join-Pfade, Prüfung "
                "gegen Tabellen und Spalten). Die Abfrage wird nicht ausgeführt. Gib die Frage "
                "möglichst vollständig weiter (Zeitraum, Gruppierung, Filter).")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "frage": {"type": "STRING", "description": "Die Frage in Alltagssprache."},
            "dialekt": {"type": "STRING", "description": "Optional: SQL-Dialekt, wenn abweichend von der "
                        "Einstellung (postgresql, mysql, oracle, mssql, sqlite, db2, hana, …)."},
            "praefix": {"type": "STRING", "description": "Optional: nur Tabellen dieser Datenbankschemata als "
                        "Ausgangspunkt (Schema-Präfix, kommagetrennt, z. B. eines von zwei Schemata im selben "
                        "Export). Nur setzen, wenn der Benutzer es nennt oder eine vorige Antwort Tabellen "
                        "aus mehreren Präfixen meldete."},
        }, "required": ["frage"]}

    async def execute(self, frage: str = "", dialekt: str = "", praefix: str = "", _sql_schemata=None, **kwargs):
        from backend import schema_graph_rag as rag  # noqa: PLC0415
        if kwargs:
            return "Unbekannte Parameter: " + ", ".join(sorted(kwargs))
        frage = (frage or "").strip()
        if not frage:
            return "Keine Frage angegeben."
        try:
            praefixe = rag.praefixe_normal(praefix or None)
        except ValueError as e:
            return str(e)
        z = await asyncio.to_thread(_zugang, _sql_schemata)
        if not z.get("darf") or not z.get("erlaubt"):
            return _abgewiesen(z)
        cfg = await asyncio.to_thread(_cfg)
        d = (dialekt or cfg.get("dialekt") or "allgemein").strip().lower()
        if d not in rag.DIALEKTE:
            d = "allgemein"
        con = await asyncio.to_thread(_oeffnen)
        if con is None:
            return _ohne_graph()
        try:
            erg = await rag.sql_erzeugen(frage, dialekt=d, con=con, erlaubt=z["erlaubt"],
                                         max_tabellen=cfg["max_tabellen"], max_spalten=cfg["max_spalten"],
                                         praefixe=praefixe)
        finally:
            con.close()
        return ausgabe(erg, d)


def ausgabe(erg: dict, dialekt: str) -> str:
    """Ergebnis von ``sql_erzeugen`` als Text fuer das Modell.

    Der Pruefstatus steht in der ERSTEN Zeile: steht er am Ende, schneidet ihn
    eine spaetere Kappung weg, und ein ungeprueftes SQL sieht wie ein
    geprueftes aus.
    """
    if erg.get("fehler"):
        z = ["Keine SQL-Abfrage erzeugt: " + erg["fehler"]]
        if erg.get("begriffe"):
            z.append("Gesuchte Begriffe: " + ", ".join(erg["begriffe"][:25]))
        if erg.get("tabellen"):
            z.append("Betrachtete Tabellen: " + ", ".join(erg["tabellen"][:20]))
        return "\n".join(z)
    pr = erg.get("pruefung") or {}
    unbelegt = [u.get("bedingung", "") for u in pr.get("unbelegte_joins") or []]
    if pr.get("ok") and unbelegt:
        # Der Vorbehalt steht in der ERSTEN Zeile (dieselbe Begruendung wie der
        # Pruefstatus selbst: am Ende schnitte ihn eine Kappung weg).
        kopf = (f"SQL ({dialekt}) – GEPRÜFT MIT VORBEHALT: gültig und nur lesend, aber verbunden über "
                f"{len(unbelegt)} Join-Bedingung(en) OHNE Beleg im Schema: {'; '.join(unbelegt)}. Dem Benutzer "
                "diese Verknüpfung ausdrücklich als ANNAHME nennen, nicht als gesichert. Nicht ausgeführt.")
    elif pr.get("ok"):
        kopf = (f"SQL ({dialekt}) – GEPRÜFT: nur lesend, {len(pr.get('tabellen') or [])} Tabellen und "
                f"{pr.get('spalten_geprueft', 0)} qualifizierte Spalten im Schema vorhanden. Nicht ausgeführt.")
    else:
        kopf = (f"SQL ({dialekt}) – PRÜFUNG NICHT BESTANDEN nach {erg.get('runden', 1)} Versuchen. Dem "
                "Benutzer NICHT als fertige Abfrage geben, sondern die Befunde nennen:\n- "
                + "\n- ".join(pr.get("fehler") or ["unbekannt"]))
    z = [kopf, "```sql", erg.get("sql") or "", "```"]
    if erg.get("erklaerung"):
        z.append("Erklärung: " + erg["erklaerung"])
    if erg.get("annahmen") and erg["annahmen"].strip().lower() not in ("keine", "- keine"):
        z.append("Annahmen: " + erg["annahmen"])
    tab = erg.get("tabellen_kontext") or []
    grundlage = f"Grundlage: {len(tab)} Tabellen aus dem Schema-Graphen"
    if erg.get("verbinder"):
        grundlage += " (als Join-Glieder ergänzt: " + ", ".join(erg["verbinder"]) + ")"
    z.append(grundlage + ".")
    if erg.get("unverbunden"):
        z.append("Ohne Join-Pfad (höchstens 4 Schritte) zu den übrigen: " + ", ".join(erg["unverbunden"]))
    if erg.get("hauswissen"):
        z.append("Hintergrund aus den Hausdokumenten: " + ", ".join(
            f"{h['titel']} (Abschnitt {h['nr']})" for h in erg["hauswissen"][:6]))
    pk = erg.get("praefixe_sql") or {}
    if len(pk) > 1 and not erg.get("praefixe"):
        z.append("Hinweis: Die Abfrage verbindet Tabellen aus mehreren Datenbankschemata ("
                 + ", ".join(f"{k} {v}" for k, v in pk.items()) + "). Ist eines gemeint, die Frage mit "
                 "praefix erneut stellen – dem Benutzer die Wahl nennen.")
    if erg.get("gleichwertig"):
        z.append("Zusammengelegt (Sicht zeigt alle Spalten der Tabelle): " + ", ".join(
            f"{g['sicht']} statt {g['tabelle']}" for g in erg["gleichwertig"][:8]))
    if erg.get("begriffe_quelle") == "frage":
        z.append("Hinweis: Suchbegriffe nur aus der Frage (die Begriffserweiterung durch das Modell fiel aus).")
    return "\n".join(z)


class SchemaSucheTool(BaseTool):
    @property
    def name(self):
        return "schema_suche"

    @property
    def description(self):
        return ("Sucht im erfassten Datenbankschema Tabellen und Sichten zu Begriffen (Tabellenname, "
                "Beschreibung, Spaltennamen). Für Fragen wie 'wo stehen die Lieferadressen?'.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "begriffe": {"type": "STRING", "description": "Ein oder mehrere Suchbegriffe, kommagetrennt."},
            "limit": {"type": "INTEGER", "description": "Höchstzahl Treffer (Standard 15, höchstens 50)."},
        }, "required": ["begriffe"]}

    async def execute(self, begriffe: str = "", limit: int = 15, _sql_schemata=None, **kwargs):
        if kwargs:
            return "Unbekannte Parameter: " + ", ".join(sorted(kwargs))
        liste = [b.strip() for b in str(begriffe or "").replace(";", ",").split(",") if b.strip()]
        if not liste:
            return "Keine Suchbegriffe angegeben."
        try:
            n = max(1, min(50, int(limit)))
        except (TypeError, ValueError):
            n = 15
        z = await asyncio.to_thread(_zugang, _sql_schemata)
        if not z.get("darf") or not z.get("erlaubt"):
            return _abgewiesen(z)
        return await asyncio.to_thread(_suche_text, liste, n, z["erlaubt"])


def _suche_text(liste: list, n: int, erlaubt) -> str:
    from backend import schema_graph_dienst as dienst  # noqa: PLC0415
    con = _oeffnen()
    if con is None:
        return _ohne_graph()
    try:
        tr = dienst.suche_info(con, liste, n, erlaubt)
    finally:
        con.close()
    if not tr:
        return "Keine Tabelle zu: " + ", ".join(liste)
    z = [f"{len(tr)} Treffer zu {', '.join(liste)} (bester zuerst):"]
    for t in tr:
        zeile = f"- {t['name']} ({'Sicht' if t['art'] == 'sicht' else 'Tabelle'}, {t['spalten_n']} Spalten"
        if t["bereich"]:
            zeile += f", Bereich: {t['bereich']}"
        zeile += ")"
        if t["kommentar"]:
            zeile += " – " + t["kommentar"][:160]
        z.append(zeile)
    return "\n".join(z)


class SchemaTabelleTool(BaseTool):
    @property
    def name(self):
        return "schema_tabelle"

    @property
    def description(self):
        return "Zeigt eine Tabelle/Sicht des erfassten Schemas mit allen Spalten und ihren Beziehungen."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "name": {"type": "STRING", "description": "Tabellenname, gern mit Schema (schema.tabelle)."},
        }, "required": ["name"]}

    async def execute(self, name: str = "", _sql_schemata=None, **kwargs):
        if kwargs:
            return "Unbekannte Parameter: " + ", ".join(sorted(kwargs))
        if not (name or "").strip():
            return "Kein Tabellenname angegeben."
        z = await asyncio.to_thread(_zugang, _sql_schemata)
        if not z.get("darf") or not z.get("erlaubt"):
            return _abgewiesen(z)
        return await asyncio.to_thread(_tabelle_text, name.strip(), z["erlaubt"])


def _paare(k: dict) -> str:
    if k["art"] == "sicht":
        return "(Sicht beruht darauf)"
    bed = ", ".join(f"{x}={y}" for x, y in k["paare"]) or "?"
    return f"[{bed}{'' if k['art'] == 'fk' else ', vermutet'}]"


def _tabelle_text(name: str, erlaubt) -> str:
    from backend import schema_graph_dienst as dienst  # noqa: PLC0415
    con = _oeffnen()
    if con is None:
        return _ohne_graph()
    try:
        info = dienst.tabelle_info(con, name, erlaubt)
    finally:
        con.close()
    if info.get("fehler") == "mehrdeutig":
        return f"{name} ist mehrdeutig – bitte mit Schema angeben: " + ", ".join(info["vorschlaege"])
    if info.get("fehler"):
        v = info.get("vorschlaege") or []
        return f"Tabelle {name} nicht gefunden." + (" Ähnlich: " + ", ".join(v) if v else "")
    t = info["tabelle"]
    z = [f"{'Sicht' if t['art'] == 'sicht' else 'Tabelle'} {t['name']}"
         + (f" – {t['kommentar']}" if t["kommentar"] else "")]
    if t["bereich"]:
        z.append(f"Bereich: {t['bereich']}")
    if t["spalten_gesamt"] > len(t["spalten"]):
        z.append(f"Spalten ({len(t['spalten'])} von {t['spalten_gesamt']} gezeigt, in Tabellenreihenfolge):")
    else:
        z.append(f"Spalten ({t['spalten_gesamt']}):")
    for s in t["spalten"]:
        zeile = f"  {s['name']} {s['typ']}".rstrip()
        if s["pk"]:
            zeile += " PK"
        if not s["nullable"]:
            zeile += " NOT NULL"
        if s["kommentar"]:
            zeile += f" – {s['kommentar'][:120]}"
        z.append(zeile)
    if t["raus"]:
        z.append(f"Verweist auf ({t['raus_gesamt']}"
                 + (f", {len(t['raus'])} gezeigt" if t["raus_gesamt"] > len(t["raus"]) else "") + "):")
        z.extend(f"  {_paare(k)} → {k['ziel']}" for k in t["raus"])
    if t["rein"]:
        z.append(f"Wird referenziert von ({t['rein_gesamt']}"
                 + (f", {len(t['rein'])} gezeigt" if t["rein_gesamt"] > len(t["rein"]) else "") + "):")
        z.extend(f"  {k['quelle']} {_paare(k)}" for k in t["rein"])
    return "\n".join(z)


class SchemaVerbindungTool(BaseTool):
    @property
    def name(self):
        return "schema_verbindung"

    @property
    def description(self):
        return ("Findet im erfassten Schema den kürzesten Join-Pfad zwischen zwei Tabellen und nennt die "
                "Join-Bedingungen je Schritt.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "von": {"type": "STRING", "description": "Erste Tabelle (schema.tabelle)."},
            "nach": {"type": "STRING", "description": "Zweite Tabelle (schema.tabelle)."},
        }, "required": ["von", "nach"]}

    async def execute(self, von: str = "", nach: str = "", _sql_schemata=None, **kwargs):
        if kwargs:
            return "Unbekannte Parameter: " + ", ".join(sorted(kwargs))
        if not (von or "").strip() or not (nach or "").strip():
            return "Bitte beide Tabellen angeben."
        z = await asyncio.to_thread(_zugang, _sql_schemata)
        if not z.get("darf") or not z.get("erlaubt"):
            return _abgewiesen(z)
        return await asyncio.to_thread(_verbindung_text, von.strip(), nach.strip(), z["erlaubt"])


def _verbindung_text(von: str, nach: str, erlaubt) -> str:
    from backend import schema_graph_dienst as dienst  # noqa: PLC0415
    con = _oeffnen()
    if con is None:
        return _ohne_graph()
    try:
        info = dienst.verbindung_info(con, von, nach, erlaubt)
    finally:
        con.close()
    if info.get("fehler") == "nicht_gefunden":
        return f"Tabelle {info['name']} nicht gefunden."
    if info.get("fehler") == "mehrdeutig":
        return f"{info['name']} ist mehrdeutig – bitte mit Schema angeben."
    if info.get("fehler") == "kein_pfad":
        return (f"Kein Join-Pfad zwischen {info['von']} und {info['nach']} in höchstens "
                f"{info['max_tiefe']} Schritten.")
    z = [f"Join-Pfad {info['von']} → {info['nach']} ({len(info['schritte'])} Schritte):"]
    for s in info["schritte"]:
        if s["art"] == "sicht":
            z.append(f"  {s['von']} – {s['nach']} (nur über eine Sicht verbunden)")
        else:
            z.append(f"  {s['bedingung']}" + ("" if s["art"] == "fk" else "   [vermutet aus Spaltennamen]"))
    return "\n".join(z)


class SchemaIndexTool(BaseTool):
    @property
    def name(self):
        return "schema_index"

    @property
    def description(self):
        return ("Stand der Erfassung des Datenbankschemas (Aktion 'status'). 'starten'/'abbrechen' nur für "
                "Administratoren und nur, wenn das Erfassen aus dem Chat in den Einstellungen erlaubt ist.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "aktion": {"type": "STRING", "enum": ["status", "starten", "abbrechen"],
                       "description": "status (Standard), starten oder abbrechen."},
        }, "required": []}

    async def execute(self, aktion: str = "status", _sql_schemata=None, **kwargs):
        from backend import schema_graph_index as idx  # noqa: PLC0415
        if kwargs:
            return "Unbekannte Parameter: " + ", ".join(sorted(kwargs))
        aktion = (aktion or "status").strip().lower()
        z = await asyncio.to_thread(_zugang, _sql_schemata)
        if not z.get("darf"):
            return _abgewiesen(z)
        cfg = await asyncio.to_thread(_cfg)
        if aktion in ("starten", "abbrechen"):
            if not z.get("admin"):
                return "Das Erfassen steuern nur Administratoren (Einstellungen → SQL-Assistent)."
            if cfg.get("index_aus_chat") is not True:
                return ("Das Erfassen aus dem Chat ist in den Einstellungen des SQL-Assistenten "
                        "ausgeschaltet (Vorgabe, weil ein Lauf über viele Gigabyte den Server lange "
                        "belastet). Gestartet wird unter Einstellungen → SQL-Assistent oder auf dem "
                        "Server: bash deploy/als_dienst.sh venv/bin/python -m backend.schema_graph_index")
            if aktion == "abbrechen":
                return "Erfassung: " + idx.abbrechen()
            from backend import main as _m  # noqa: PLC0415
            if not cfg["schemata"]:
                return "Noch kein Schema angelegt (Einstellungen → SQL-Assistent)."
            antwort = await asyncio.to_thread(_m._sql_erfassen_anstossen, cfg)
            return "Erfassung: " + antwort
        if aktion != "status":
            return f"Unbekannte Aktion '{aktion}' (erlaubt: status, starten, abbrechen)."
        return await asyncio.to_thread(_status_text, z["erlaubt"], cfg)


def _status_text(erlaubt, cfg) -> str:
    """Nur GEWAEHLTE Schemata mit Namen und Zahlen; vom Lauf nur Fortschritt –
    keine Pfade und keine Fehlertexte (die stammen aus allen Schemata)."""
    from backend import schema_graph_dienst as dienst  # noqa: PLC0415
    from backend import schema_graph_index as idx  # noqa: PLC0415
    info = dienst.graph_info(erlaubt, cfg["schemata"])
    z = []
    if not info["vorhanden"]:
        z.append("Noch kein Schema-Graph vorhanden.")
    elif not info["schemata"]:
        z.append(f"Schema-Graph vom {info['stand']}; kein SQL-Schema gewählt.")
    else:
        z.append(f"Schema-Graph vom {info['stand']}:")
        for q in info["schemata"]:
            z.append(f"- {q['name']}: {q['tabellen']} Tabellen, {q['sichten']} Sichten, {q['spalten']} Spalten")
    st = idx.status()
    if st.get("laeuft"):
        z.append(f"Erfassung läuft seit {st.get('begonnen')}: {st.get('dateien_fertig', 0)} von "
                 f"{st.get('dateien_neu', 0)} Dateien"
                 + (f", noch etwa {int(st['rest_s'] // 60)} min" if st.get("rest_s") else "") + ".")
    elif st:
        z.append(f"Letzte Erfassung: {st.get('ergebnis') or '?'} am {st.get('ende') or '?'}.")
    return "\n".join(z)


def get_tools():
    return [SchemaSqlTool(), SchemaSucheTool(), SchemaTabelleTool(), SchemaVerbindungTool(),
            SchemaIndexTool()]
