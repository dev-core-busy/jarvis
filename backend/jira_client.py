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


def normalize_keywords(keywords) -> list[str]:
    """Zerlegt Schlagworte aus einer Liste ODER einem komma-/leerzeichengetrennten
    String, trimmt und dedupliziert (case-insensitiv, Reihenfolge stabil)."""
    if isinstance(keywords, (list, tuple)):
        raw = [str(x) for x in keywords]
    else:
        s = str(keywords or "")
        raw = s.split(",") if "," in s else s.split()
    seen, out = set(), []
    for p in raw:
        p = p.strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def crm_keyword_jql(crm_term: str, terms: list[str], match: str = "all") -> str | None:
    """JQL fuer 'Tickets eines CRM-Kunden, die zu Schlagworten passen'. Verbindet die
    exakte Organisationsfeld-Klausel des Kunden (alle zugeordneten Tickets, OFFEN wie
    ABGESCHLOSSEN – KEIN Resolution-Filter) per AND mit den Schlagworten im Volltext.
    ``match='all'`` -> alle Begriffe (AND), ``match='any'`` -> irgendein Begriff (OR).
    Gibt None zurueck, wenn ``crm_term`` keine gueltige CRM-ID ist."""
    org = crm_org_clause(crm_term)
    if not org:
        return None
    op = " OR " if str(match).lower() in ("any", "or", "oder") else " AND "
    clause = ""
    if terms:
        clause = " AND (" + op.join('text ~ "%s"' % t.replace('"', "'") for t in terms) + ")"
    return org + clause + " ORDER BY updated DESC"


def phone_search_variants(phone: str) -> list[str]:
    """Erzeugt aus einer Telefonnummer Such-Varianten fuer die CRM-Objektsuche.
    Nummern koennen je nach Eingabe mit/ohne Laendervorwahl bzw. fuehrender 0 kommen –
    wir liefern reine Ziffernfolgen, absteigend nach Laenge sortiert (praeziseste zuerst,
    z.B. voll international '4920562611' vor der kurzen Teilnehmernummer). Der Aufrufer
    probiert sie in dieser Reihenfolge, damit der laengste (eindeutigste) Match gewinnt."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 5:
        return []
    variants = {digits}
    if digits.startswith("00"):          # 0049… -> 49… (VOR der CC-Pruefung normalisieren,
        digits = digits[2:]              # sonst greift startswith(cc) nie)
        variants.add(digits)
    for cc in _insight_phone_ccs():      # Laendervorwahlen (konfigurierbar): 49… -> 0… (national)
        if digits.startswith(cc) and len(digits) > len(cc) + 3:
            variants.add("0" + digits[len(cc):])
            variants.add(digits[len(cc):])
    if digits.startswith("0"):           # 0… -> ohne fuehrende 0
        variants.add(digits[1:])
    return sorted((v for v in variants if len(v) >= 5), key=len, reverse=True)


# ── CRM-Objektschema (Jira Insight/Assets) ────────────────────────────
# Die CRM-xxxx-Eintraege sind Insight-Objekte im Objektschema 'CRM' (Standard-Schema-ID
# 21) – der Objekt-Key IST die CRM-Kundennummer. Telefonnummern stehen dort international
# und zusammenhaengend (z.B. '+4920562611', ohne Trennzeichen). Alle Werte per
# jira-Skill-Config ueberschreibbar (insight_api_base / insight_schema_id / insight_phone_attrs).
_INSIGHT_API_BASE_DEFAULT = "/rest/insight/1.0"
_INSIGHT_SCHEMA_ID_DEFAULT = 21
_INSIGHT_PHONE_ATTRS_DEFAULT = [
    "Zentrale Rufnummer", "Mobile Rufnummer", "vertrauliche Rufnummer",
    "Telefonnummer", "Telefonnummer 2", "Mobil Nummer", "Telefon",
]
# Reihenfolge der Treffer nach Objekttyp: Organisationen (der Kunde selbst) zuerst,
# dann Produktgruppen, danach Kontaktpersonen. Nicht gelistete Typen behalten ihre
# Insight-Reihenfolge und landen hinter den priorisierten.
_INSIGHT_TYPE_PRIORITY_DEFAULT = ["Organisationen", "Organisationen Produktgruppen"]
# Laendervorwahlen, fuer die nationale Nummern-Varianten (fuehrende 0 / ohne Vorwahl)
# gebildet werden. Default DACH + ES (spanisches Schema NXSPCRM existiert); per
# Skill-Config 'insight_phone_ccs' erweiterbar.
_INSIGHT_PHONE_CCS_DEFAULT = ["49", "43", "41", "34"]


def _insight_api_base() -> str:
    return ((get_jira_config().get("insight_api_base") or "").strip().rstrip("/")) or _INSIGHT_API_BASE_DEFAULT


def _insight_schema_id() -> int:
    try:
        return int(get_jira_config().get("insight_schema_id") or _INSIGHT_SCHEMA_ID_DEFAULT)
    except (TypeError, ValueError):
        return _INSIGHT_SCHEMA_ID_DEFAULT


def _insight_list_cfg(key: str, default: list[str]) -> list[str]:
    """Liest eine Liste aus der Jira-Config (Komma-String ODER JSON-Array), sonst Default."""
    raw = get_jira_config().get(key)
    if isinstance(raw, str):
        vals = [a.strip() for a in raw.split(",") if a.strip()]
    elif isinstance(raw, (list, tuple)):
        vals = [str(a).strip() for a in raw if str(a).strip()]
    else:
        vals = []
    return vals or list(default)


def _insight_phone_attrs() -> list[str]:
    return _insight_list_cfg("insight_phone_attrs", _INSIGHT_PHONE_ATTRS_DEFAULT)


def _insight_phone_ccs() -> list[str]:
    return [re.sub(r"\D", "", c) for c in
            _insight_list_cfg("insight_phone_ccs", _INSIGHT_PHONE_CCS_DEFAULT) if re.sub(r"\D", "", c)]


def _insight_type_priority() -> list[str]:
    return _insight_list_cfg("insight_type_priority", _INSIGHT_TYPE_PRIORITY_DEFAULT)


def _iql_str(v: str) -> str:
    """Maskiert Backslash und Anfuehrungszeichen fuer IQL-String-Literale."""
    return (v or "").replace("\\", "\\\\").replace('"', '\\"')


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

    def insight_search(self, iql: str, schema_id: int | None = None,
                       limit: int = 25, page: int = 1) -> dict:
        """IQL-Suche im Insight/Assets-CRM-Objektschema (Standard-Schema-ID 21).
        Liefert das rohe API-Objekt inkl. ``objectEntries`` (mit ``objectKey`` =
        CRM-Nummer und ``label``) sowie ``totalFilterCount``."""
        return self._request("GET", _insight_api_base() + "/iql/objects", params={
            "objectSchemaId": schema_id or _insight_schema_id(),
            "iql": iql, "resultPerPage": limit, "page": page,
            "includeAttributes": "true", "includeTypeAttributes": "true"})

    _EMPTY_PHONE_RESULT = {"crm": None, "matches": [], "total": 0, "iql": "", "variant": None}

    def find_crm_by_phone(self, phone: str, limit: int = 25) -> dict:
        """Ermittelt die CRM-Kundennummer(n) (Objekt-Key 'CRM-xxxxxx') zu einer
        Telefonnummer ueber das Insight-CRM-Objektschema. Alle Nummern-Varianten
        (international/national/ohne Vorwahl) werden in EINER OR-verknuepften
        IQL-Abfrage gesucht (ein HTTP-Roundtrip). Da IQL ``like`` ein Substring-
        Match ist, wird jeder Treffer nachvalidiert: eine seiner Telefon-Attribut-
        Werte muss – auf Ziffern normalisiert – auf eine der Varianten ENDEN
        (verhindert Fehltreffer, bei denen die Ziffernfolge nur mitten in einer
        fremden Nummer vorkommt). Treffer werden nach Objekttyp priorisiert
        (Organisationen zuerst; konfigurierbar via ``insight_type_priority``).
        Liefert {crm, matches:[{key, name, type}], total, iql, variant}."""
        variants = phone_search_variants(phone)
        if not variants:
            return dict(self._EMPTY_PHONE_RESULT)
        attrs = _insight_phone_attrs()
        prio = _insight_type_priority()

        def _rank(m: dict) -> int:
            t = m.get("type") or ""
            return prio.index(t) if t in prio else len(prio)

        iql = " OR ".join('"%s" like "%s"' % (_iql_str(a), _iql_str(v))
                          for a in attrs for v in variants)
        data = self.insight_search(iql, limit=limit)
        entries = data.get("objectEntries") or []
        if not entries:
            return dict(self._EMPTY_PHONE_RESULT, iql=iql)

        # Attribut-ID -> Anzeigename (aus expand der Typ-Attribute), um die
        # Telefon-Attributwerte der Treffer fuer die Nachvalidierung zu lesen.
        attr_names = {ta.get("id"): ta.get("name")
                      for ta in (data.get("objectTypeAttributes") or [])}
        phone_attr_set = set(attrs)

        def _phone_digits(obj: dict):
            """Alle Telefon-Attributwerte eines Treffers als Ziffernfolgen."""
            for av in obj.get("attributes") or []:
                if attr_names.get(av.get("objectTypeAttributeId")) in phone_attr_set:
                    for val in av.get("objectAttributeValues") or []:
                        d = re.sub(r"\D", "", str(val.get("displayValue") or val.get("value") or ""))
                        if d:
                            yield d

        def _matched_variant(obj: dict) -> str | None:
            """Laengste Variante, auf die eine gespeicherte Nummer endet, sonst None."""
            nums = list(_phone_digits(obj))
            for v in variants:  # laengste zuerst
                if any(n.endswith(v) for n in nums):
                    return v
            return None

        matches, best_variant = [], None
        for o in entries:
            v = _matched_variant(o)
            if v is None:
                continue  # reiner Substring-Fehltreffer (Ziffernfolge mitten in fremder Nummer)
            matches.append({"key": o.get("objectKey"), "name": o.get("label"),
                            "type": (o.get("objectType") or {}).get("name")})
            if best_variant is None or len(v) > len(best_variant):
                best_variant = v
        if not matches:
            return dict(self._EMPTY_PHONE_RESULT, iql=iql)
        matches.sort(key=_rank)  # stabil -> Insight-Reihenfolge innerhalb gleicher Prioritaet
        return {"crm": matches[0]["key"], "matches": matches,
                "total": len(matches), "iql": iql, "variant": best_variant}

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
        "created": f.get("created"),
        "updated": f.get("updated"),
        "link": ("%s/browse/%s" % (base.rstrip("/"), it.get("key"))) if base and it.get("key") else "",
    }
