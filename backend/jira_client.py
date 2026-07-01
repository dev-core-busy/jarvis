"""Geteilter Jira-REST-Client (Server/Data-Center).

Wird vom Skill (``skills/jira/main.py``) und den ``/api/jira/*``-Endpoints
(``backend/main.py``, fuer den Jira-Reiter) genutzt – eine einzige Auth-/
Request-Implementierung. Schwerpunkt: Ticketsuche nach Inhalten (JQL).

Auth: Personal Access Token wird IMMER als Bearer gesendet (Server/DC; PAT ist
nicht an einen Benutzer gebunden). Spiegelt bewusst ``backend.confluence_client``.

Alle Methoden sind synchron (``requests``). Aufrufer im async-Kontext muessen
sie via ``asyncio.to_thread`` ausfuehren, um den Event-Loop nicht zu blockieren.
"""

from __future__ import annotations

import html
import re

import requests


def get_jira_config() -> dict:
    """Liest die in der Skill-Config hinterlegten Jira-Werte."""
    try:
        from backend.config import config
        return config.get_skill_states().get("jira", {}).get("config", {}) or {}
    except Exception:
        return {}


def html_to_text(s: str, limit: int = 4000) -> str:
    """Reduziert HTML/Markup auf lesbaren Text."""
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"</li\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) > limit:
        s = s[:limit] + " …[gekuerzt]"
    return s


def _q(v: str) -> str:
    """Maskiert Anfuehrungszeichen fuer JQL-String-Literale."""
    return (v or "").replace('"', "'")


# Insight/Assets-Feld, das die CRM-Kunden-ID traegt (Wert z.B. "Name (CRM-10550)").
# Exakte Suche '<Feld> = "CRM-10550"' findet ALLE Tickets dieses Kunden. Der Feldname
# ist instanzspezifisch -> per Jira-Skill-Config 'org_field' ueberschreibbar.
_ORG_FIELD_DEFAULT = "Organisation"
_CRM_RE = re.compile(r"(?i)^\s*crm-\d+\s*$")


def _org_field() -> str:
    try:
        from backend.config import config
        f = (config.get_skill_states().get("jira", {}).get("config", {}) or {}).get("org_field")
        return (f or "").strip() or _ORG_FIELD_DEFAULT
    except Exception:
        return _ORG_FIELD_DEFAULT


def crm_org_clause(term: str) -> str | None:
    """Ist `term` eine CRM-Kunden-ID (z.B. 'crm-10550'), liefert die JQL-Klausel
    fuer das Insight-Organisationsfeld, sonst None. CRM-IDs sind KEINE Issue-Keys
    und stehen nicht im Volltext – nur dieses Feld findet alle zugeordneten Tickets."""
    t = (term or "").strip()
    return ('%s = "%s"' % (_org_field(), t.upper())) if _CRM_RE.match(t) else None


class JiraError(Exception):
    """Fehler bei einer Jira-Anfrage (mit HTTP-Status)."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


class JiraClient:
    """Minimaler, geteilter Jira-REST-Client (API v2)."""

    def __init__(self, cfg: dict | None = None):
        cfg = cfg if cfg is not None else get_jira_config()
        self.base = (cfg.get("base_url") or "").strip().rstrip("/")
        self.token = (cfg.get("api_token") or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.base and self.token)

    # ── intern ────────────────────────────────────────────────────
    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Accept": "application/json", "Authorization": "Bearer " + self.token}
        if extra:
            h.update(extra)
        return h

    def _request(self, method: str, path: str, *, params=None, json=None, headers=None):
        if not self.configured:
            raise JiraError(0, "Jira ist nicht konfiguriert (URL/Token fehlen).")
        url = self.base + path
        r = requests.request(method, url, params=params or {}, json=json,
                             headers=self._headers(headers), timeout=20)
        if r.status_code >= 400:
            msg = ""
            try:
                j = r.json()
                errs = j.get("errorMessages") or []
                if errs:
                    msg = "; ".join(errs)
                elif j.get("errors"):
                    msg = "; ".join("%s: %s" % (k, v) for k, v in j["errors"].items())
            except ValueError:
                msg = (r.text or "")[:200]
            raise JiraError(r.status_code, msg or ("HTTP %s" % r.status_code))
        try:
            return r.json()
        except ValueError:
            return {}

    # ── High-Level ────────────────────────────────────────────────
    def myself(self) -> dict:
        return self._request("GET", "/rest/api/2/myself")

    def browse_url(self, key: str) -> str:
        return ("%s/browse/%s" % (self.base, key)) if key else ""

    def build_jql(self, query: str = "", project: str | None = None,
                  status: str | None = None, issuetype: str | None = None,
                  assignee: str | None = None) -> str:
        """Baut aus einfachen Filtern eine JQL-Query (Volltext + Felder)."""
        clauses: list[str] = []
        if query:
            # CRM-Kunden-ID (crm-10550) -> exakte Suche im Organisationsfeld (findet
            # ALLE Tickets des Kunden). Sonst Volltextsuche. Echte Issue-Keys liest
            # man ueber jira_get_issue.
            org = crm_org_clause(query)
            clauses.append(org if org else 'text ~ "%s"' % _q(query))
        if project:
            clauses.append('project = "%s"' % _q(project))
        if status:
            clauses.append('status = "%s"' % _q(status))
        if issuetype:
            clauses.append('issuetype = "%s"' % _q(issuetype))
        if assignee:
            clauses.append('assignee = "%s"' % _q(assignee))
        jql = " AND ".join(clauses)
        return (jql + " ORDER BY updated DESC") if jql else "ORDER BY updated DESC"

    _SEARCH_FIELDS = "summary,status,project,issuetype,priority,assignee,reporter,updated,created"

    def search(self, jql: str, limit: int = 25, start: int = 0, fields: str | None = None) -> dict:
        """JQL-Suche. Liefert {total, issues:[…]}. ``fields`` optional (Default:
        Kernfelder); z.B. um Beschreibung/Kommentare gebündelt mitzuladen."""
        return self._request("GET", "/rest/api/2/search", params={
            "jql": jql, "startAt": start, "maxResults": limit,
            "fields": fields or self._SEARCH_FIELDS})

    def get_issue(self, key: str) -> dict:
        """Einzelnes Issue inkl. Beschreibung und Kommentaren.
        Jira-Keys sind GROSSGESCHRIEBEN -> normalisieren, damit z.B. 'crm-10550'
        nicht in einen 404 laeuft."""
        key = (key or "").strip().upper()
        return self._request("GET", "/rest/api/2/issue/%s" % key, params={
            "fields": self._SEARCH_FIELDS + ",description,comment,labels,resolution"})

    def projects(self, limit: int = 200) -> list[dict]:
        """Sichtbare Projekte (Key + Name)."""
        d = self._request("GET", "/rest/api/2/project", params={"maxResults": limit})
        # /project liefert je nach Version eine Liste oder {values:[…]}
        if isinstance(d, list):
            return d
        return d.get("values", [])

    def add_comment(self, key: str, body: str) -> dict:
        return self._request("POST", "/rest/api/2/issue/%s/comment" % key,
                            json={"body": body or ""})

    def create_issue(self, project: str, summary: str, description: str = "",
                     issuetype: str = "Task") -> dict:
        payload = {"fields": {
            "project": {"key": project},
            "summary": summary,
            "description": description or "",
            "issuetype": {"name": issuetype or "Task"},
        }}
        return self._request("POST", "/rest/api/2/issue", json=payload)


def issue_brief(it: dict, base: str = "") -> dict:
    """Reduziert ein Jira-Issue auf die wichtigsten Felder (fuer Listen/UI)."""
    f = it.get("fields", {}) or {}
    def _n(x):
        return (x or {}).get("name") if isinstance(x, dict) else x
    return {
        "key": it.get("key"),
        "summary": f.get("summary"),
        "status": _n(f.get("status")),
        "type": _n(f.get("issuetype")),
        "priority": _n(f.get("priority")),
        "project": (f.get("project") or {}).get("key"),
        "assignee": (f.get("assignee") or {}).get("displayName") if f.get("assignee") else None,
        "updated": f.get("updated"),
        "link": ("%s/browse/%s" % (base.rstrip("/"), it.get("key"))) if base and it.get("key") else "",
    }
