"""Jira-Skill (Server/Data-Center).

Anbindung an die Atlassian-Jira-REST-API (v2) ohne zusaetzliche Abhaengigkeit.
Schwerpunkt: Ticketsuche nach Inhalten (Volltext/JQL) inkl. der CRM-Kunden-
Auswertungen (Profile, Eskalations-Analyse, Diagramme) auf Jira-Basis.
Die Request-/Auth-Logik liegt im geteilten ``backend.jira_client`` (auch von
den /api/jira/*-Endpoints des Jira-Reiters genutzt).

Netzwerkaufrufe laufen ueber ``asyncio.to_thread`` (Event-Loop nicht blockieren).
"""

import asyncio

from backend.tools.base import BaseTool
from backend.jira_client import (
    JiraClient, JiraError, html_to_text, issue_brief, crm_org_clause,
    fmt_err as _fmt_err, fmt_issue_line as _fmt_issue_line,
    max_results_cap as _max_results,
)


def _client() -> JiraClient:
    return JiraClient()


async def _to_thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


class _Base(BaseTool):
    def _guard(self) -> JiraClient | None:
        c = _client()
        return c if c.configured else None


class JiraTestConnectionTool(_Base):
    @property
    def name(self): return "jira_test_connection"

    @property
    def description(self):
        return "Prueft die Jira-Verbindung und meldet den angemeldeten Benutzer."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert. Bitte URL und API-Token im Jira-Reiter eintragen."
        try:
            me = await _to_thread(c.myself)
        except JiraError as e:
            return _fmt_err(e)
        return "✅ Verbunden mit %s als %s (%s)." % (
            c.base, me.get("displayName", me.get("name", "?")), me.get("emailAddress", ""))


class JiraSearchTool(_Base):
    @property
    def name(self): return "jira_search"

    @property
    def description(self):
        return ("Sucht Jira-Tickets. Volltext ueber Zusammenfassung/Beschreibung/Kommentare, "
                "ODER – wenn die Query eine KUNDEN-/ORGANISATIONS-ID wie 'crm-10550' ist – "
                "alle diesem Kunden zugeordneten Tickets (Organisationsfeld). Genau hierfuer "
                "verwenden bei Fragen wie 'Tickets von/zu crm-XXXX'. Optional gefiltert nach "
                "Projekt, Status, Typ, Bearbeiter; oder vollstaendige JQL. Liefert Key, Titel, "
                "Status, Typ, Link.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "query": {"type": "STRING", "description": "Suchbegriff (Volltext in Titel/Beschreibung/Kommentaren)."},
            "project": {"type": "STRING", "description": "Optional: Projekt-Key (z.B. 'PROJ')."},
            "status": {"type": "STRING", "description": "Optional: Status (z.B. 'Open', 'In Progress', 'Closed')."},
            "issuetype": {"type": "STRING", "description": "Optional: Vorgangstyp (z.B. 'Bug', 'Task')."},
            "assignee": {"type": "STRING", "description": "Optional: Bearbeiter (Benutzername)."},
            "jql": {"type": "STRING", "description": "Optional: vollstaendige JQL-Query (ueberschreibt die obigen Filter)."},
            "limit": {"type": "INTEGER", "description": "Max. Trefferzahl. Standard 15. Fuer vollstaendige Auswertungen (z.B. 'alle Tickets von crm-XXXX') hoch setzen – die zentrale Admin-Obergrenze wird automatisch durchgesetzt."},
        }, "required": []}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert."
        cap = _max_results()
        try:
            limit = max(1, min(int(kwargs.get("limit") or 15), cap))
        except (TypeError, ValueError):
            limit = min(15, cap)
        jql = (kwargs.get("jql") or "").strip()
        if not jql:
            query = (kwargs.get("query") or "").strip()
            project = (kwargs.get("project") or "").strip() or None
            status = (kwargs.get("status") or "").strip() or None
            issuetype = (kwargs.get("issuetype") or "").strip() or None
            assignee = (kwargs.get("assignee") or "").strip() or None
            if not (query or project or status or issuetype or assignee):
                return "Bitte query, einen Filter oder eine vollstaendige jql angeben."
            jql = c.build_jql(query, project, status, issuetype, assignee)
        try:
            data = await _to_thread(c.search, jql, limit)
        except JiraError as e:
            return _fmt_err(e)
        issues = data.get("issues", [])
        total = data.get("total", len(issues))
        if not issues:
            return "Keine Tickets gefunden.\nJQL: %s" % jql
        lines = [_fmt_issue_line(issue_brief(it, c.base)) for it in issues]
        header = "%d Treffer (Anzeige %d)\nJQL: %s\n" % (total, len(issues), jql)
        return header + "\n".join(lines)


class JiraGetIssueTool(_Base):
    @property
    def name(self): return "jira_get_issue"

    @property
    def description(self):
        return ("Ruft EIN Jira-Ticket per Issue-Key ab (z.B. NXCIS-1234). "
                "NICHT fuer Kunden-/Organisations-IDs wie 'crm-10550' verwenden – dafuer "
                "jira_search nutzen (das findet alle Tickets des Kunden).")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "key": {"type": "STRING", "description": "Echter Issue-Key, z.B. 'NXCIS-1234' (Projektkuerzel-Nummer). NICHT 'crm-…'."},
        }, "required": ["key"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert."
        key = (kwargs.get("key") or "").strip()
        if not key:
            return "key ist erforderlich."
        try:
            it = await _to_thread(c.get_issue, key)
        except JiraError as e:
            # Kein echter Issue-Key (z.B. Kunden-ID 'crm-10550')? -> Volltextsuche
            # nach Tickets, die diese ID referenzieren (wie der Support-Assistent).
            if e.status == 404:
                try:
                    # CRM-Kunden-ID -> Organisationsfeld (alle Tickets des Kunden),
                    # sonst Volltextsuche.
                    org = crm_org_clause(key)
                    jql = (org if org else 'text ~ "%s"' % key.replace('"', "'")) + " ORDER BY updated DESC"
                    data = await _to_thread(c.search, jql, _max_results())
                    issues = data.get("issues", [])
                    if issues:
                        total = data.get("total", len(issues))
                        lines = [_fmt_issue_line(issue_brief(i, c.base)) for i in issues]
                        ku = key.upper()
                        return ("HINWEIS: '%s' ist KEIN Ticket, sondern eine Kunden-/Organisations-ID. "
                                "Dieser Kunde hat %d zugeordnete Tickets (neueste %d unten). "
                                "Fasse diese Tickets zusammen – melde NICHT, dass ein Ticket fehlt:\n%s"
                                % (ku, total, len(issues), "\n".join(lines)))
                except Exception:
                    pass  # Fallback-Suche fehlgeschlagen -> sauber den 404 melden
            return _fmt_err(e)
        b = issue_brief(it, c.base)
        f = it.get("fields", {}) or {}
        desc = html_to_text(f.get("description") or "", 2500)
        out = ["🎫 %s — %s" % (b["key"], b.get("summary", ""))]
        meta = []
        if b.get("status"):   meta.append("Status: %s" % b["status"])
        if b.get("type"):     meta.append("Typ: %s" % b["type"])
        if b.get("priority"): meta.append("Prio: %s" % b["priority"])
        if b.get("assignee"): meta.append("Bearbeiter: %s" % b["assignee"])
        if meta:
            out.append(" | ".join(meta))
        if b.get("link"):
            out.append(b["link"])
        out.append("\n" + (desc or "(keine Beschreibung)"))
        comments = ((f.get("comment") or {}).get("comments")) or []
        if comments:
            out.append("\n💬 Kommentare (%d, letzte 3):" % len(comments))
            for cm in comments[-3:]:
                author = (cm.get("author") or {}).get("displayName", "?")
                out.append("- %s: %s" % (author, html_to_text(cm.get("body") or "", 400)))
        return "\n".join(out)


class JiraListProjectsTool(_Base):
    @property
    def name(self): return "jira_list_projects"

    @property
    def description(self):
        return "Listet sichtbare Jira-Projekte (Key und Name)."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert."
        try:
            projs = await _to_thread(c.projects, 200)
        except JiraError as e:
            return _fmt_err(e)
        if not projs:
            return "Keine Projekte gefunden."
        projs.sort(key=lambda p: (p.get("key") or ""))
        return "%d Projekt(e):\n" % len(projs) + "\n".join(
            "- %s — %s" % (p.get("key", "?"), p.get("name", "")) for p in projs[:100])


class JiraAddCommentTool(_Base):
    @property
    def name(self): return "jira_add_comment"

    @property
    def description(self):
        return "Fuegt einem Ticket einen Kommentar hinzu."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "key": {"type": "STRING", "description": "Issue-Key."},
            "body": {"type": "STRING", "description": "Kommentartext."},
        }, "required": ["key", "body"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert."
        key = (kwargs.get("key") or "").strip()
        body = (kwargs.get("body") or "").strip()
        if not key or not body:
            return "key und body sind erforderlich."
        try:
            res = await _to_thread(c.add_comment, key, body)
        except JiraError as e:
            return _fmt_err(e)
        return "💬 Kommentar an %s hinzugefuegt (ID %s)." % (key, res.get("id", "?"))


class JiraCreateIssueTool(_Base):
    @property
    def name(self): return "jira_create_issue"

    @property
    def description(self):
        return "Legt ein neues Ticket an (Projekt-Key, Titel, optional Beschreibung und Typ)."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "project": {"type": "STRING", "description": "Projekt-Key (z.B. 'PROJ')."},
            "summary": {"type": "STRING", "description": "Titel/Zusammenfassung."},
            "description": {"type": "STRING", "description": "Optional: Beschreibung."},
            "issuetype": {"type": "STRING", "description": "Optional: Vorgangstyp (Standard 'Task')."},
        }, "required": ["project", "summary"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert."
        project = (kwargs.get("project") or "").strip()
        summary = (kwargs.get("summary") or "").strip()
        if not project or not summary:
            return "project und summary sind erforderlich."
        try:
            res = await _to_thread(c.create_issue, project, summary,
                                   (kwargs.get("description") or "").strip(),
                                   (kwargs.get("issuetype") or "Task").strip() or "Task")
        except JiraError as e:
            return _fmt_err(e)
        key = res.get("key", "?")
        return "✅ Ticket angelegt: %s\n%s" % (key, c.browse_url(key))


class JiraCustomerTicketsTool(_Base):
    @property
    def name(self): return "jira_customer_tickets"

    @property
    def description(self):
        return ("Findet die zu SCHLAGWORTEN passenden Tickets EINES CRM-Kunden "
                "(z.B. 'crm-10550') – OFFENE UND ABGESCHLOSSENE. GENAU DIESES Tool bei "
                "Fragen wie 'Tickets von crm-XXXX, die A und B enthalten' oder "
                "'Tickets von Kunde X zum Thema Y'. Verbindet die exakte Kunden-"
                "Organisationssuche mit 2-5 Schlagworten im Volltext und liefert eine "
                "kompakte, begrenzte Trefferliste (Key, Titel, Status, offen/abgeschlossen, "
                "Link). NICHT jira_org_profile dafuer verwenden – das zieht ALLE Tickets "
                "des Kunden und ist fuer Schlagwort-Filter ungeeignet.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "crm": {"type": "STRING", "description": "CRM-Kundennummer, z.B. 'crm-10550'."},
            "keywords": {"type": "ARRAY", "items": {"type": "STRING"},
                         "description": "2 bis 5 Schlagworte (z.B. ['LDT','Anbindung']). Auch als komma-/leerzeichengetrennter String moeglich."},
            "match": {"type": "STRING", "description": "'all' (Default) = Ticket muss ALLE Schlagworte enthalten (bei 'A und B'); 'any' = irgendeines (bei 'A oder B')."},
            "limit": {"type": "INTEGER", "description": "Max. Trefferzahl. Standard 25 (Admin-Obergrenze wird durchgesetzt)."},
        }, "required": ["crm", "keywords"]}

    async def execute(self, **kwargs):
        from backend.jira_client import crm_keyword_jql, normalize_keywords
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert."
        crm = (kwargs.get("crm") or kwargs.get("query") or kwargs.get("kunde") or "").strip()
        if not crm:
            return "Bitte eine CRM-Kundennummer angeben (z.B. crm-10550)."
        terms = normalize_keywords(kwargs.get("keywords"))
        if len(terms) < 2:
            return "Bitte mindestens 2 Schlagworte angeben (z.B. keywords=['LDT','Anbindung'])."
        if len(terms) > 5:
            return "Bitte hoechstens 5 Schlagworte angeben."
        match = (kwargs.get("match") or "all").strip().lower()
        jql = crm_keyword_jql(crm, terms, match)
        if not jql:
            return "Keine gueltige CRM-Nummer (erwartet z.B. 'crm-10550')."
        try:
            limit = max(1, min(int(kwargs.get("limit") or 25), _max_results()))
        except (TypeError, ValueError):
            limit = min(25, _max_results())
        try:
            data = await _to_thread(c.search, jql, limit, 0, c._SEARCH_FIELDS + ",resolution")
        except JiraError as e:
            return _fmt_err(e)
        issues = data.get("issues", [])
        total = data.get("total", len(issues))
        mode = "any" if match in ("any", "or", "oder") else "all"
        verb = "irgendeines der" if mode == "any" else "ALLE"
        if not issues:
            return ("Keine Tickets fuer %s mit %s Schlagworte(n) %s gefunden.\nJQL: %s"
                    % (crm.upper(), verb, terms, jql))
        n_open = sum(1 for it in issues if not (it.get("fields", {}) or {}).get("resolution"))
        lines = []
        for it in issues:
            b = issue_brief(it, c.base)
            resolved = bool((it.get("fields", {}) or {}).get("resolution"))
            b["status"] = (b.get("status") or "?") + (" – abgeschlossen" if resolved else " – offen")
            lines.append(_fmt_issue_line(b))
        header = ("%s: %d Treffer (%s Schlagworte: %s), davon %d offen / %d abgeschlossen. "
                  "Anzeige %d, neueste zuerst:\n"
                  % (crm.upper(), total, verb, ", ".join(terms), n_open, len(issues) - n_open, len(issues)))
        return header + "\n".join(lines)


class JiraOrgProfileTool(_Base):
    @property
    def name(self): return "jira_org_profile"

    @property
    def description(self):
        return ("Aggregiert ALLE Tickets einer Kunden-/Organisations-ID (z.B. 'crm-10408') "
                "seitenweise (Paginierung, umgeht das 100er-Seitenlimit) und liefert "
                "deterministische Kennzahlen ueber den GESAMTBESTAND: Gesamtzahl, Verteilung "
                "nach Prioritaet/Status/Typ, Anzahl unterschiedlicher Bearbeiter und Melder, "
                "Erstellzeitraum, Durchschnittsalter und Ø-Bearbeitungsdauer, plus die "
                "komplette Ticket-Liste MIT Anlagedatum, Schliessdatum und Dauer[Tage] pro "
                "Ticket. Genau diese Einzeldaten fuer Diagramme/Auswertungen ueber Ticket-"
                "Zeitverlaeufe verwenden (z.B. Anlagedatum vs. Bearbeitungsdauer). "
                "IMMER dieses Tool fuer vollstaendige Kunden-/Eskalationsprofile verwenden – "
                "es deckt ALLE Tickets ab (keine Stichprobe). Kommentar-Inhalte/Tonalitaet "
                "sind NICHT enthalten (dafuer einzelne Tickets per jira_get_issue nachladen). "
                "NICHT verwenden, wenn nur die zu bestimmten SCHLAGWORTEN passenden Tickets "
                "eines Kunden gefragt sind (z.B. 'Tickets von crm-X, die A und B enthalten') – "
                "dafuer jira_customer_tickets nutzen (klein, gefiltert; dieses Tool wuerde "
                "unnoetig ALLE Tickets laden).")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "query": {"type": "STRING", "description": "Kunden-/Organisations-ID, z.B. 'crm-10408'."},
        }, "required": ["query"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert."
        term = (kwargs.get("query") or kwargs.get("key") or "").strip()
        if not term:
            return "Bitte eine Kunden-/Organisations-ID angeben (z.B. crm-10408)."
        org = crm_org_clause(term)
        jql = (org if org else 'text ~ "%s"' % term.replace('"', "'")) + " ORDER BY created ASC"
        cap = _max_results()
        # resolutiondate zusaetzlich laden – fuer "Dauer bis zum Schliessen" pro Ticket
        # (ermoeglicht z.B. ein Diagramm Anlagedatum vs. Bearbeitungsdauer).
        fields = ("summary,status,project,issuetype,priority,assignee,reporter,"
                  "updated,created,resolutiondate")
        issues = []
        total = None
        start = 0
        try:
            while len(issues) < cap:
                want = min(100, cap - len(issues))
                data = await _to_thread(c.search, jql, want, start, fields)
                if total is None:
                    total = data.get("total", 0)
                batch = data.get("issues", [])
                if not batch:
                    break
                issues.extend(batch)
                start += len(batch)
                if start >= (total or 0):
                    break
        except JiraError as e:
            return _fmt_err(e)
        if not issues:
            return "Keine Tickets gefunden.\nJQL: %s" % jql

        import datetime as _dt
        from collections import Counter

        def _nm(f, k):
            v = (f or {}).get(k)
            return (v or {}).get("name") if isinstance(v, dict) else v

        def _parse(s):
            if not s:
                return None
            try:
                return _dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                return None

        prio, status, typ = Counter(), Counter(), Counter()
        assignees, reporters = set(), set()
        created, updated = [], []
        for it in issues:
            f = it.get("fields", {}) or {}
            prio[_nm(f, "priority") or "—"] += 1
            status[_nm(f, "status") or "—"] += 1
            typ[_nm(f, "issuetype") or "—"] += 1
            a = f.get("assignee")
            if a and a.get("displayName"):
                assignees.add(a["displayName"])
            r = f.get("reporter")
            if r and r.get("displayName"):
                reporters.add(r["displayName"])
            cd = _parse(f.get("created"))
            if cd:
                created.append(cd)
            ud = _parse(f.get("updated"))
            if ud:
                updated.append(ud)

        now = _dt.datetime.utcnow()
        ages = [(now - d).days for d in created]
        avg_age = round(sum(ages) / len(ages)) if ages else 0

        def _c(cnt):
            return ", ".join("%s: %d" % (k, v) for k, v in cnt.most_common())

        L = []
        L.append("KUNDEN-TICKET-PROFIL – vollstaendig aggregiert ueber ALLE Tickets (deterministisch)")
        L.append("Organisation/ID: %s" % term.upper())
        L.append("Tickets gesamt (Jira 'total'): %s | tatsaechlich ausgewertet: %d%s" % (
            total, len(issues),
            "" if len(issues) >= (total or 0) else " ⚠️ durch Obergrenze max_results=%d begrenzt" % cap))
        L.append("Prioritaeten: %s" % _c(prio))
        L.append("Status: %s" % _c(status))
        L.append("Typen: %s" % _c(typ))
        L.append("Unterschiedliche Bearbeiter: %d | unterschiedliche Melder: %d" % (len(assignees), len(reporters)))
        if created:
            L.append("Erstellzeitraum: %s bis %s | Durchschnittsalter: %d Tage" % (
                min(created).date(), max(created).date(), avg_age))
        if updated:
            L.append("Letzte Aktivitaet (spaetestes 'updated'): %s" % max(updated).date())
        # Bearbeitungsdauer (created -> resolutiondate) ueber alle geschlossenen Tickets
        durations = []
        for it in issues:
            f = it.get("fields", {}) or {}
            cd = _parse(f.get("created"))
            rd = _parse(f.get("resolutiondate"))
            if cd and rd:
                durations.append((rd - cd).days)
        if durations:
            L.append("Geschlossene Tickets: %d | Ø-Bearbeitungsdauer: %d Tage (min %d / max %d)" % (
                len(durations), round(sum(durations) / len(durations)),
                min(durations), max(durations)))
        L.append("")
        L.append("HINWEIS: Kommentar-Anzahl sowie oeffentliche/interne Kommentar-INHALTE und "
                 "Tonalitaet sind hier NICHT enthalten – dafuer einzelne Tickets per "
                 "jira_get_issue nachladen (qualitative Bewertung).")
        L.append("")
        L.append("Alle %d Tickets (Key | Prioritaet | Status | Typ | angelegt | geschlossen | "
                 "Dauer[Tage]):" % len(issues))
        for it in issues:
            b = issue_brief(it, c.base)
            f = it.get("fields", {}) or {}
            cd = _parse(f.get("created"))
            rd = _parse(f.get("resolutiondate"))
            c_s = cd.date().isoformat() if cd else "—"
            r_s = rd.date().isoformat() if rd else "offen"
            dur = str((rd - cd).days) if (cd and rd) else "—"
            L.append("- %s | %s | %s | %s | %s | %s | %s" % (
                b.get("key"), b.get("priority") or "—", b.get("status") or "—",
                b.get("type") or "—", c_s, r_s, dur))
        return "\n".join(L)


async def _jira_llm(system_prompt: str, user_text: str) -> str:
    """Ein LLM-Aufruf über das aktive Profil (fuer die Map-Reduce-Analyse)."""
    from backend.config import config
    from backend.llm import get_provider
    from google.genai import types
    provider = get_provider(
        config.LLM_PROVIDER, config.current_api_key, config.current_api_url,
        auth_method=config.current_auth_method,
        session_key=config.current_session_key, prompt_tool_calling=False)
    resp = await provider.generate_response(
        model=config.current_model, system_prompt=system_prompt,
        contents=[types.Content(role="user", parts=[types.Part.from_text(text=user_text)])],
        tools=[])
    return "".join(p.text for p in (resp.parts or []) if getattr(p, "text", None)).strip()


class JiraOrgAnalysisTool(_Base):
    supports_streaming = True

    @property
    def name(self): return "jira_org_analysis"

    @property
    def description(self):
        return ("Vollständige Kunden-/Eskalationsprofil-Analyse einer Organisations-/CRM-ID "
                "(z.B. 'crm-10408') über ALLE Tickets per serverseitigem Map-Reduce: holt "
                "paginiert alle Tickets inkl. Beschreibung und Kommentaren, wertet sie "
                "batchweise mit dem LLM aus und erzeugt am Ende ein zusammenfassendes JSON "
                "(Scores 0–10 für Kommunikation/Eskalation/Tonalität/Kooperation/Geduld/"
                "Kritikalität/Komplexität/Supportaufwand, Auffälligkeiten, Zusammenfassung). "
                "Schritt-/kontextunabhängig – die einzige Methode, die WIRKLICH alle Tickets "
                "berücksichtigt. Für 'analysiere alle Tickets von crm-XXXX' immer dieses Tool "
                "verwenden und das gelieferte JSON unverändert zurückgeben.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "query": {"type": "STRING", "description": "Kunden-/Organisations-ID, z.B. 'crm-10408'."},
        }, "required": ["query"]}

    async def execute(self, _status_callback=None, **kwargs):
        async def _emit(msg):
            if _status_callback:
                try:
                    await _status_callback(msg)
                except Exception:
                    pass
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert."
        term = (kwargs.get("query") or kwargs.get("key") or "").strip()
        if not term:
            return "Bitte eine Kunden-/Organisations-ID angeben (z.B. crm-10408)."
        org = crm_org_clause(term)
        jql = (org if org else 'text ~ "%s"' % term.replace('"', "'")) + " ORDER BY created ASC"
        cap = _max_results()
        fields = "summary,status,issuetype,priority,assignee,reporter,updated,created,description,comment,resolutiondate"
        await _emit("📊 %s: lade alle Tickets aus Jira …" % term.upper())
        issues, total, start = [], None, 0
        try:
            while len(issues) < cap:
                want = min(50, cap - len(issues))
                data = await _to_thread(c.search, jql, want, start, fields)
                if total is None:
                    total = data.get("total", 0)
                batch = data.get("issues", [])
                if not batch:
                    break
                issues.extend(batch)
                start += len(batch)
                await _emit("📊 %s: %d/%s Tickets geladen …" % (term.upper(), len(issues), total))
                if start >= (total or 0):
                    break
        except JiraError as e:
            return _fmt_err(e)
        if not issues:
            return "Keine Tickets gefunden.\nJQL: %s" % jql

        import datetime as _dt
        from collections import Counter

        def _nm(f, k):
            v = (f or {}).get(k)
            return (v or {}).get("name") if isinstance(v, dict) else v

        # ── Quantitative Aggregation (deterministisch, über ALLE) ──
        prio, status, typ = Counter(), Counter(), Counter()
        assignees, reporters = set(), set()
        total_comments = 0
        blobs = []
        for it in issues:
            f = it.get("fields", {}) or {}
            prio[_nm(f, "priority") or "—"] += 1
            status[_nm(f, "status") or "—"] += 1
            typ[_nm(f, "issuetype") or "—"] += 1
            a = f.get("assignee");  r = f.get("reporter")
            if a and a.get("displayName"): assignees.add(a["displayName"])
            if r and r.get("displayName"): reporters.add(r["displayName"])
            cmts = ((f.get("comment") or {}).get("comments")) or []
            total_comments += len(cmts)
            # kompakter Ticket-Blob fuer die qualitative Analyse
            parts = ["[%s | %s | %s | %s]" % (it.get("key"), _nm(f, "priority") or "—",
                                              _nm(f, "status") or "—", _nm(f, "issuetype") or "—")]
            parts.append("Titel: " + (f.get("summary") or ""))
            desc = html_to_text(f.get("description") or "", 350)
            if desc:
                parts.append("Beschreibung: " + desc)
            for cm in cmts[:6]:
                who = ((cm.get("author") or {}).get("displayName")) or "?"
                vis = "intern" if cm.get("jsdPublic") is False else "öffentlich"
                body = html_to_text(cm.get("body") or "", 200)
                parts.append("Kommentar (%s, %s): %s" % (who, vis, body))
            blobs.append("\n".join(parts)[:1500])

        def _c(cnt):
            return ", ".join("%s: %d" % (k, v) for k, v in cnt.most_common())

        quant = (
            "Organisation: %s\nTickets gesamt: %s (ausgewertet: %d%s)\n"
            "Prioritäten: %s\nStatus: %s\nTypen: %s\n"
            "Kommentare gesamt: %d\nUnterschiedliche Bearbeiter: %d | Melder: %d"
        ) % (term.upper(), total, len(issues),
             "" if len(issues) >= (total or 0) else ", durch max_results begrenzt",
             _c(prio), _c(status), _c(typ), total_comments, len(assignees), len(reporters))

        # ── MAP: batchweise qualitative Signale extrahieren ──
        import asyncio as _aio
        BATCH = 40
        batches = [blobs[i:i + BATCH] for i in range(0, len(blobs), BATCH)]
        map_sys = ("Du analysierst Support-Tickets EINES Kunden. Extrahiere NUR beobachtbare "
                   "Signale aus den folgenden Tickets (keine Spekulation). Fasse knapp zusammen: "
                   "1) Eskalationen (Management gefordert, Fristen, Beschwerden, Druck, Drohungen, "
                   "Kündigungs-/Rechtshinweise) mit Ticket-Key; 2) Tonalität (freundlich/sachlich/"
                   "konfrontativ) mit kurzen Zitaten; 3) Kooperationsbereitschaft; 4) Geduld "
                   "(schnelle Nachfragen?); 5) wiederkehrende Themen/Parallelthemen; 6) positive "
                   "Aspekte/Lob. Nur was belegbar ist. Antworte kompakt in Stichpunkten.")
        sem = _aio.Semaphore(5)
        _done = [0]
        _nb = len(batches)
        await _emit("🧠 %s: %d Tickets in %d Batches – werte Inhalte/Kommentare aus …" % (
            term.upper(), len(issues), _nb))

        async def _map_one(idx, chunk):
            async with sem:
                try:
                    r = await _jira_llm(map_sys, ("Tickets (Batch %d):\n\n" % (idx + 1)) + "\n\n---\n\n".join(chunk))
                except Exception as e:
                    r = "(Batch %d fehlgeschlagen: %s)" % (idx + 1, e)
                _done[0] += 1
                await _emit("🧠 %s: Batch %d/%d ausgewertet …" % (term.upper(), _done[0], _nb))
                return r

        partials = await _aio.gather(*[_map_one(i, ch) for i, ch in enumerate(batches)])
        await _emit("🧩 %s: erstelle Gesamtprofil (JSON) …" % term.upper())
        map_summary = "\n\n".join("### Batch %d\n%s" % (i + 1, p) for i, p in enumerate(partials))

        # ── REDUCE: finales JSON exakt nach Schema ──
        schema = (
            '{\n  "crm_id": "", "organisation": "",\n'
            '  "scores": {"kommunikation":0,"eskalation":0,"tonalitaet":0,"kooperation":0,'
            '"geduld":0,"kritikalitaet":0,"komplexitaet":0,"supportaufwand":0},\n'
            '  "gesamteindruck": "unkritisch | aufmerksam beobachten | anspruchsvoll | '
            'eskalationsgefährdet | Hochrisikokunde",\n'
            '  "auffaelligkeiten": [], "positive_aspekte": [], "kritische_aspekte": [],\n'
            '  "begruendung": "", "zusammenfassung": ""\n}'
        )
        reduce_sys = (
            "Du erstellst ein Kunden-Eskalationsprofil. Nutze AUSSCHLIESSLICH die gelieferten "
            "quantitativen Kennzahlen (über ALLE Tickets) und die qualitativen Batch-Signale. "
            "Keine Spekulation; fehlende Daten ausdrücklich in 'begruendung' erwähnen. Bewertungen "
            "0–10, vergleichbar. Antworte AUSSCHLIESSLICH mit folgendem JSON (kein weiterer Text):\n"
            + schema)
        reduce_user = ("QUANTITATIVE KENNZAHLEN (deterministisch, alle Tickets):\n" + quant
                       + "\n\nQUALITATIVE SIGNALE (Batch-Auswertung aller Tickets):\n" + map_summary
                       + "\n\ncrm_id = " + term.upper())
        try:
            final = await _jira_llm(reduce_sys, reduce_user[:120000])
        except JiraError as e:
            return _fmt_err(e)
        except Exception as e:
            return "Analyse fehlgeschlagen (Reduce): %s\n\nKennzahlen:\n%s" % (e, quant)
        # nur den JSON-Block zurueckgeben
        s = final.strip()
        if "```" in s:
            import re as _re
            m = _re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, _re.S)
            if m:
                s = m.group(1)
        return s


class JiraTicketChartTool(_Base):
    """Erzeugt ein FERTIGES Diagramm (chartjs-Block) ueber die Tickets eines Kunden.

    Aggregiert serverseitig (vertraegt beliebig viele Tickets) und liefert den
    fertigen chartjs-JSON-Block. So muss das LLM NICHT hunderte Rohpunkte selbst
    konstruieren (woran kleinere lokale Modelle scheitern) – es gibt den Block
    nur unveraendert aus.
    """

    @property
    def name(self): return "jira_ticket_chart"

    @property
    def description(self):
        return ("Erzeugt ein FERTIGES Liniendiagramm (chartjs-Block) ueber die Tickets einer "
                "Kunden-/Organisations-ID (z.B. 'crm-10550'): x-Achse = Zeit nach Anlagedatum "
                "(monatlich/quartalsweise/jaehrlich aggregiert), y-Achse = durchschnittliche "
                "Bearbeitungsdauer in Tagen plus Ticket-Anzahl. Serverseitig aggregiert (vertraegt "
                "beliebig viele Tickets) und liefert den FERTIGEN chartjs-JSON-Block. IMMER dieses "
                "Tool fuer 'Diagramm/Chart der Tickets von crm-XXXX (Anlagedatum vs. Dauer)' "
                "verwenden und den gelieferten chartjs-Block UNVERAENDERT an den Nutzer ausgeben – "
                "NICHT die Rohdaten selbst zeichnen.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "query": {"type": "STRING", "description": "Kunden-/Organisations-ID, z.B. 'crm-10550'."},
            "bucket": {"type": "STRING", "description": "Zeitraster: 'month' (Standard), 'quarter' oder 'year'."},
        }, "required": ["query"]}

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return "Jira ist nicht konfiguriert."
        term = (kwargs.get("query") or kwargs.get("key") or "").strip()
        if not term:
            return "Bitte eine Kunden-/Organisations-ID angeben (z.B. crm-10550)."
        bucket = (kwargs.get("bucket") or "month").strip().lower()
        if bucket not in ("month", "quarter", "year"):
            bucket = "month"
        org = crm_org_clause(term)
        jql = (org if org else 'text ~ "%s"' % term.replace('"', "'")) + " ORDER BY created ASC"
        cap = _max_results()
        fields = "created,resolutiondate"
        issues, total, start = [], None, 0
        try:
            while len(issues) < cap:
                want = min(100, cap - len(issues))
                data = await _to_thread(c.search, jql, want, start, fields)
                if total is None:
                    total = data.get("total", 0)
                batch = data.get("issues", [])
                if not batch:
                    break
                issues.extend(batch)
                start += len(batch)
                if start >= (total or 0):
                    break
        except JiraError as e:
            return _fmt_err(e)
        if not issues:
            return "Keine Tickets gefunden.\nJQL: %s" % jql

        import datetime as _dt
        import json as _json
        from collections import OrderedDict

        def _parse(s):
            if not s:
                return None
            try:
                return _dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                return None

        def _key(d):
            if bucket == "year":
                return "%04d" % d.year
            if bucket == "quarter":
                return "%04d-Q%d" % (d.year, (d.month - 1) // 3 + 1)
            return "%04d-%02d" % (d.year, d.month)

        # key -> [sum_dauer, n_geschlossen, n_angelegt]
        buckets = OrderedDict()
        for it in issues:
            f = it.get("fields", {}) or {}
            cd = _parse(f.get("created"))
            if not cd:
                continue
            b = buckets.setdefault(_key(cd), [0.0, 0, 0])
            b[2] += 1
            rd = _parse(f.get("resolutiondate"))
            if rd:
                b[0] += max(0, (rd - cd).days)
                b[1] += 1
        labels = list(buckets.keys())
        avg_dur = [round(buckets[k][0] / buckets[k][1], 1) if buckets[k][1] else None for k in labels]
        counts = [buckets[k][2] for k in labels]

        spec = {
            "type": "line",
            "data": {"labels": labels, "datasets": [
                {"label": "Ø Dauer bis Schließen [Tage]", "data": avg_dur,
                 "borderColor": "#2563eb", "backgroundColor": "rgba(37,99,235,0.1)",
                 "fill": False, "tension": 0.2, "spanGaps": True, "yAxisID": "y"},
                {"label": "Tickets angelegt", "data": counts,
                 "borderColor": "#f59e0b", "backgroundColor": "rgba(245,158,11,0.1)",
                 "fill": False, "tension": 0.2, "yAxisID": "y1"},
            ]},
            "options": {
                "plugins": {"title": {"display": True,
                            "text": "Tickets %s – Ø Bearbeitungsdauer & Anzahl (%s)" % (term.upper(), bucket)}},
                "scales": {
                    "y": {"title": {"display": True, "text": "Ø Dauer [Tage]"}, "beginAtZero": True},
                    "y1": {"position": "right", "title": {"display": True, "text": "Anzahl"},
                           "beginAtZero": True, "grid": {"drawOnChartArea": False}},
                },
            },
        }
        block = "```chartjs\n" + _json.dumps(spec, ensure_ascii=False) + "\n```"
        n_closed = sum(buckets[k][1] for k in labels)
        return ("Diagramm für %s fertig aggregiert: %d Tickets über %d %s-Buckets "
                "(%d geschlossen, mit Bearbeitungsdauer). Gib den folgenden chartjs-Block "
                "UNVERÄNDERT und ohne weiteren Text an den Nutzer aus:\n\n%s"
                % (term.upper(), len(issues), len(labels), bucket, n_closed, block))


def get_tools():
    return [
        JiraTestConnectionTool(),
        JiraSearchTool(),
        JiraCustomerTicketsTool(),
        JiraGetIssueTool(),
        JiraOrgProfileTool(),
        JiraOrgAnalysisTool(),
        JiraTicketChartTool(),
        JiraListProjectsTool(),
        JiraAddCommentTool(),
        JiraCreateIssueTool(),
    ]
