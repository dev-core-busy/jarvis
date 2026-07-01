"""Jira-Skill (Server/Data-Center).

Anbindung an die Atlassian-Jira-REST-API (v2) ohne zusaetzliche Abhaengigkeit.
Schwerpunkt: Ticketsuche nach Inhalten (Volltext/JQL). Die Request-/Auth-Logik
liegt im geteilten ``backend.jira_client`` (auch von den /api/jira/*-Endpoints
des Jira-Reiters genutzt).

Netzwerkaufrufe laufen ueber ``asyncio.to_thread`` (Event-Loop nicht blockieren).
"""

import asyncio

from backend.tools.base import BaseTool
from backend.jira_client import JiraClient, JiraError, html_to_text, issue_brief, crm_org_clause


def _client() -> JiraClient:
    return JiraClient()


def _max_results() -> int:
    """Vom Administrator zentral konfigurierte Obergrenze fuer Trefferzahlen
    (Skill-Config 'max_results'). Standard 50, Untergrenze 1, Sicherheits-Deckel
    1000 (Schutz vor versehentlich riesigen Abfragen)."""
    try:
        from backend.jira_client import get_jira_config
        v = int(get_jira_config().get("max_results") or 50)
    except Exception:
        v = 50
    return max(1, min(v, 1000))


async def _to_thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


def _fmt_err(e: JiraError) -> str:
    if e.status in (401, 403):
        return "❌ Authentifizierung fehlgeschlagen (HTTP %s). API-Token pruefen." % e.status
    if e.status == 404:
        return "❌ Nicht gefunden (HTTP 404). Issue-Key/Projekt pruefen."
    if e.status == 400:
        return "❌ Ungueltige Anfrage (HTTP 400) – evtl. fehlerhafte JQL: %s" % e
    if e.status == 0:
        return "❌ %s" % e
    return "❌ Jira-Fehler (HTTP %s): %s" % (e.status, e)


def _fmt_issue_line(b: dict) -> str:
    parts = ["%s — %s" % (b.get("key", "?"), b.get("summary", ""))]
    meta = []
    if b.get("status"):   meta.append(b["status"])
    if b.get("type"):     meta.append(b["type"])
    if b.get("priority"): meta.append("Prio %s" % b["priority"])
    if b.get("assignee"): meta.append("→ %s" % b["assignee"])
    line = "- " + parts[0]
    if meta:
        line += "  [%s]" % ", ".join(meta)
    if b.get("link"):
        line += "\n  " + b["link"]
    return line


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


class JiraOrgProfileTool(_Base):
    @property
    def name(self): return "jira_org_profile"

    @property
    def description(self):
        return ("Aggregiert ALLE Tickets einer Kunden-/Organisations-ID (z.B. 'crm-10408') "
                "seitenweise (Paginierung, umgeht das 100er-Seitenlimit) und liefert "
                "deterministische Kennzahlen ueber den GESAMTBESTAND: Gesamtzahl, Verteilung "
                "nach Prioritaet/Status/Typ, Anzahl unterschiedlicher Bearbeiter und Melder, "
                "Erstellzeitraum und Durchschnittsalter, plus die komplette Ticket-Liste. "
                "IMMER dieses Tool fuer vollstaendige Kunden-/Eskalationsprofile verwenden – "
                "es deckt ALLE Tickets ab (keine Stichprobe). Kommentar-Inhalte/Tonalitaet "
                "sind NICHT enthalten (dafuer einzelne Tickets per jira_get_issue nachladen).")

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
        issues = []
        total = None
        start = 0
        try:
            while len(issues) < cap:
                want = min(100, cap - len(issues))
                data = await _to_thread(c.search, jql, want, start)
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
        L.append("")
        L.append("HINWEIS: Kommentar-Anzahl sowie oeffentliche/interne Kommentar-INHALTE und "
                 "Tonalitaet sind hier NICHT enthalten – dafuer einzelne Tickets per "
                 "jira_get_issue nachladen (qualitative Bewertung).")
        L.append("")
        L.append("Alle %d Tickets (Key | Prioritaet | Status | Typ):" % len(issues))
        for it in issues:
            b = issue_brief(it, c.base)
            L.append("- %s | %s | %s | %s" % (b.get("key"), b.get("priority") or "—",
                                               b.get("status") or "—", b.get("type") or "—"))
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


def get_tools():
    return [
        JiraTestConnectionTool(),
        JiraSearchTool(),
        JiraGetIssueTool(),
        JiraOrgProfileTool(),
        JiraOrgAnalysisTool(),
        JiraListProjectsTool(),
        JiraAddCommentTool(),
        JiraCreateIssueTool(),
    ]
