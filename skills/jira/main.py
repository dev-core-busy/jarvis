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


def get_tools():
    return [
        JiraTestConnectionTool(),
        JiraSearchTool(),
        JiraGetIssueTool(),
        JiraListProjectsTool(),
        JiraAddCommentTool(),
        JiraCreateIssueTool(),
    ]
