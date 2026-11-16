"""Confluence-Skill.

Anbindung an die Atlassian-Confluence-REST-API (Cloud + Server) ohne
zusaetzliche Abhaengigkeit. Die eigentliche Request-/Auth-Logik liegt im
geteilten ``backend.confluence_client`` (auch von den /api/confluence/*-
Endpoints des Confluence-Reiters genutzt).

Netzwerkaufrufe laufen ueber ``asyncio.to_thread`` (Event-Loop nicht blockieren).
"""

import asyncio
import re

from backend.tools.base import BaseTool
from backend.confluence_client import ConfluenceClient, ConfluenceError, html_to_text

# Hoechstzahl der Bereiche, die eine Liste abruft (in Seiten zu 50). Auf ECHT
# sieht ein Zugang je nach Rechten 27 bis knapp 500 Bereiche; die Grenze ist
# nur ein Netz gegen einen Server, der endlos weiterzaehlt. Wird sie erreicht,
# sagt die Ausgabe "mindestens" – eine Zahl, die vollstaendig klingt und es
# nicht ist, war der Kern des NXPT-Vorfalls (2026-11-13).
MAX_SPACES_ABRUF = 5000
# Unter dieser Laenge gilt der Seitentext als "kaum Inhalt": dann werden die
# Makros benannt und die Unterseiten mitgeliefert, damit das Modell einen Weg
# zum eigentlichen Inhalt hat.
KURZ_INHALT = 200
MAX_UNTERSEITEN = 50
# Makro-Parameter sind Einstellungen (Breite, Tiefe, Sortierung), kein Inhalt.
# html_to_text liesse ihren Wert als Text stehen – eine Startseite aus Makros
# wurde dadurch zu einem nackten "400", das das Modell als HTTP-Fehler las.
_RE_MAKRO_PARAM = re.compile(r"<ac:parameter\b[^>]*>.*?</ac:parameter\s*>", re.I | re.S)
_RE_MAKRO_NAME = re.compile(r"<ac:structured-macro\b[^>]*?\bac:name=\"([^\"]+)\"", re.I)


def _client() -> ConfluenceClient:
    """Der Zugang fuer DIESEN Lauf – persoenlicher Token, sonst Sammelzugang.

    Seit 2026-09-29 ist der in der Skill-Config hinterlegte Token nur noch der
    RUECKFALL: wer unter *Mein Confluence-Zugang* (``/confluence-addon``) einen
    eigenen PAT hinterlegt, arbeitet damit – und sieht genau seine eigenen
    Bereiche. Seit 2026-11-05 liest der Skill nur noch (Nur-Lesen im
    ``confluence_client``). Begruendung und Reichweite: Docstring von
    ``backend.confluence_accounts``.

    Der Benutzer kommt aus einem ContextVar, den der Dispatch je Werkzeug-Aufruf
    setzt – NIE aus einem Werkzeug-Argument: sonst koennte das Modell waehlen,
    mit wessen Token es liest.

    DIES IST DIE EINZIGE Konstruktionsstelle des Skills (auch ``_Base._guard``
    laeuft darueber). Waere sie nur halb umgestellt, lieferten zwei Werkzeuge
    desselben Auftrags verschiedene Ergebnisse und niemand koennte erklaeren
    warum – genau der Fehler, der beim Jira-Zugang vier Stellen gekostet hat.
    """
    from backend import confluence_accounts  # noqa: PLC0415 – Zirkelimport
    return confluence_accounts.client_fuer_lauf()


async def _to_thread(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


def _fmt_err(e: ConfluenceError) -> str:
    if e.status in (401, 403):
        return "❌ Authentifizierung fehlgeschlagen (HTTP %s). Benutzer/API-Token pruefen." % e.status
    if e.status == 404:
        # Confluence antwortet auch bei fehlender LESEBERECHTIGUNG mit 404 –
        # "nicht gefunden" allein schickt die Suche zur falschen Ursache.
        return ("❌ Nicht gefunden (HTTP 404): existiert nicht ODER der verwendete "
                "Confluence-Zugang darf es nicht lesen – Confluence unterscheidet das "
                "nicht. ID/Schluessel/Titel pruefen (Cloud-URL meist mit /wiki).")
    if e.status == 0:
        return "❌ %s" % e
    return "❌ Confluence-Fehler (HTTP %s): %s" % (e.status, e)


def _alle_spaces(c: ConfluenceClient) -> tuple[list[dict], bool]:
    """(Bereiche, vollstaendig) – EINE Quelle fuer Liste UND Verbindungstest.

    Vorher fragte der Test 25 ab und die Liste 50, beide ohne weiterzublaettern:
    im selben Lauf stand "25 Space(s)" neben "50 Space(s)", und keine der beiden
    Zahlen war die wahre (489)."""
    alle = c.spaces_detailed(MAX_SPACES_ABRUF)
    return alle, len(alle) < MAX_SPACES_ABRUF


def _anzahl_text(n: int, vollstaendig: bool) -> str:
    return ("%d" % n) if vollstaendig else ("mindestens %d" % n)


def _seitentext(storage: str) -> str:
    """Lesbarer Seitentext ohne Makro-Parameter (siehe ``_RE_MAKRO_PARAM``)."""
    return html_to_text(_RE_MAKRO_PARAM.sub("", storage or "")).strip()


def _zugang_kopf(c) -> str:
    """Erste Zeile jedes Ergebnisses: MIT WELCHEM Zugang es entstand.

    Anlass ECHT 2026-11-16: "kein Zugriff auf NXPT" war nicht einzuordnen –
    fehlte dem Benutzer das Recht, oder lief der Abruf ueber den gemeinsamen
    Zugang, weil er nicht persoenlich angemeldet war? ``aufloesen`` kannte die
    Antwort (``hinweis``), sie wurde aber verworfen. Ohne Angabe am Client
    (Attrappe, aelterer Aufrufer) gibt es keine Zeile – nichts zu behaupten
    ist besser als etwas Geratenes."""
    z = getattr(c, "zugang", None)
    if not isinstance(z, dict) or not z.get("quelle"):
        return ""
    benutzer = str(z.get("benutzer") or "")
    person = bool(benutzer) and ":" not in benutzer
    if z["quelle"] == "persoenlich":
        return ("ℹ Confluence-Zugang: persoenlicher Zugang von '%s' – Ergebnisse zeigen "
                "SEINE Rechte." % benutzer)
    if not person:
        return "ℹ Confluence-Zugang: gemeinsamer Zugang."
    grund = str(z.get("hinweis") or "").strip()
    return ("ℹ Confluence-Zugang: GEMEINSAMER Zugang, nicht der von '%s'.%s Ergebnisse "
            "zeigen die Rechte des gemeinsamen Zugangs – was hier fehlt oder gesperrt "
            "ist, kann der Benutzer mit eigener Confluence-Anmeldung (persoenlicher "
            "Token) womoeglich sehen." % (benutzer, (" Grund: " + grund) if grund else ""))


class _Base(BaseTool):
    """Gemeinsame Hilfen fuer alle Confluence-Tools.

    ``execute`` ist fuer ALLE Werkzeuge dieselbe: Zugang aufloesen (``_guard``),
    Werkzeug ausfuehren (``_ausfuehren``), Zugangszeile davor. Je Werkzeug
    eine eigene Fassung haette die Zeile an einer Stelle vergessen."""

    NICHT_KONFIGURIERT = "Confluence ist nicht konfiguriert."

    def _guard(self) -> ConfluenceClient | None:
        c = _client()
        return c if c.configured else None

    async def execute(self, **kwargs):
        c = self._guard()
        if not c:
            return self.NICHT_KONFIGURIERT
        ergebnis = await self._ausfuehren(c, **kwargs)
        kopf = _zugang_kopf(c)
        return (kopf + "\n\n" + ergebnis) if kopf else ergebnis

    async def _ausfuehren(self, c, **kwargs):  # pragma: no cover – je Werkzeug ueberschrieben
        raise NotImplementedError


class ConfluenceTestConnectionTool(_Base):
    @property
    def name(self): return "confluence_test_connection"

    @property
    def description(self):
        return ("Prueft die Confluence-Verbindung und meldet, als WER verbunden ist und "
                "wie viele Bereiche (Spaces) dieser Zugang sieht. Ob ein BESTIMMTER "
                "Bereich sichtbar ist, beantwortet confluence_list_spaces mit 'key'.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}, "required": []}

    NICHT_KONFIGURIERT = ("Confluence ist nicht konfiguriert. Bitte URL und API-Token "
                          "im Confluence-Reiter eintragen.")

    async def _ausfuehren(self, c, **kwargs):
        try:
            spaces, vollstaendig = await _to_thread(_alle_spaces, c)
        except ConfluenceError as e:
            return _fmt_err(e)
        # Wer ist verbunden? Ohne diese Angabe ist "kein Zugriff" nicht
        # einzuordnen (eigener Token oder gemeinsamer?). /user/current kennt
        # nicht jede Fassung – fehlt es, entfaellt nur die Angabe.
        konto = ""
        try:
            ich = await _to_thread(c.current_user) or {}
            name = str(ich.get("displayName") or "").strip()
            kennung = str(ich.get("username") or ich.get("userKey") or "").strip()
            wer = ("%s (%s)" % (name, kennung)) if (name and kennung) else (name or kennung)
            konto = (" als " + wer) if wer else ""
        except Exception:  # noqa: BLE001
            konto = ""
        keys = ", ".join(str(s.get("key") or "?") for s in spaces[:10])
        return ("✅ Verbindung erfolgreich zu %s%s – %s Bereich(e) sichtbar.%s\n"
                "Ob ein bestimmter Bereich sichtbar ist: confluence_list_spaces(key=\"…\")." % (
                    c.base, konto, _anzahl_text(len(spaces), vollstaendig),
                    (" Beispiele: " + keys) if keys else ""))


class ConfluenceListSpacesTool(_Base):
    @property
    def name(self): return "confluence_list_spaces"

    @property
    def description(self):
        return ("Listet die Confluence-Bereiche (Spaces), die der verwendete Zugang sieht – "
                "mit Gesamtzahl. Ob ein BESTIMMTER Bereich sichtbar ist (\"habe ich Zugriff "
                "auf NXPT?\"): 'key' angeben, das prueft genau diesen Bereich direkt. "
                "'suche' filtert nach Schluessel oder Name. Die Liste zeigt hoechstens "
                "'limit' Eintraege – fehlt ein Bereich in einer gekuerzten Liste, ist das "
                "KEIN Beleg, dass er nicht sichtbar ist. Die Antwort gilt fuer JETZT; ein "
                "frueheres Ergebnis im Verlauf kann nach einer Zugangsaenderung veraltet sein.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "key": {"type": "STRING",
                    "description": "Schluessel EINES Bereichs (z. B. NXPT) – prueft gezielt, "
                                   "ob genau dieser Bereich sichtbar ist."},
            "suche": {"type": "STRING",
                      "description": "Optional: Teil von Schluessel oder Name zum Filtern."},
            "limit": {"type": "INTEGER",
                      "description": "Max. Anzahl gezeigter Eintraege (Standard 50, hoechstens 200)."},
        }, "required": []}

    async def _ausfuehren(self, c, **kwargs):
        key = str(kwargs.get("key") or "").strip()
        if key:
            return await self._ein_bereich(c, key)
        suche = str(kwargs.get("suche") or "").strip()
        try:
            limit = max(1, min(int(kwargs.get("limit") or 50), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            alle, vollstaendig = await _to_thread(_alle_spaces, c)
        except ConfluenceError as e:
            return _fmt_err(e)
        if suche:
            s_cf = suche.casefold()
            treffer = [s for s in alle
                       if s_cf in str(s.get("key") or "").casefold()
                       or s_cf in str(s.get("name") or "").casefold()]
        else:
            treffer = alle
        gezeigt = treffer[:limit]
        kopf = ["%s Bereich(e) mit dem verwendeten Zugang sichtbar." % _anzahl_text(
            len(alle), vollstaendig)]
        if suche:
            kopf.append("Treffer fuer '%s': %d." % (suche, len(treffer)))
        if not treffer:
            kopf.append("Kein Bereich passt." if suche else "Keine Bereiche gefunden.")
            return " ".join(kopf)
        # Der Kuerzungshinweis steht VOR der Liste: am Ende schnitte ihn die
        # naechste Kappung weg, und ein Ausschnitt ohne Hinweis liest sich als
        # vollstaendig (Register: "jede Kuerzung beziffern").
        if len(gezeigt) < len(treffer):
            kopf.append("⚠ GEKUERZT: gezeigt %d von %d – %d weitere sind sichtbar, aber "
                        "nicht aufgefuehrt. Fehlt ein Bereich hier, ist er deshalb NICHT "
                        "unsichtbar: mit key=\"…\" gezielt pruefen oder 'suche' verwenden." % (
                            len(gezeigt), len(treffer), len(treffer) - len(gezeigt)))
        else:
            kopf.append("Gezeigt: alle %d." % len(gezeigt))
        return "\n".join(kopf) + "\n" + "\n".join(
            "- %s — %s" % (s.get("key") or "?", s.get("name") or "") for s in gezeigt)

    @staticmethod
    async def _ein_bereich(c: ConfluenceClient, key: str) -> str:
        try:
            s = await _to_thread(c.space, key)
        except ConfluenceError as e:
            if e.status == 404:
                return ("❌ Bereich '%s' ist mit dem verwendeten Confluence-Zugang NICHT "
                        "sichtbar (HTTP 404). Confluence unterscheidet dabei nicht zwischen "
                        "\"gibt es nicht\" und \"keine Leseberechtigung\"." % key)
            return _fmt_err(e)
        teile = ["✅ Bereich %s — %s ist mit dem verwendeten Confluence-Zugang sichtbar." % (
            s.get("key") or key, s.get("name") or "")]
        if s.get("homepage"):
            teile.append("Startseite: ID %s (confluence_get_page)." % s["homepage"])
        if s.get("link"):
            teile.append("Link: %s" % s["link"])
        return "\n".join(teile)


class ConfluenceSearchTool(_Base):
    @property
    def name(self): return "confluence_search"

    @property
    def description(self):
        return ("Sucht Seiten in Confluence (Volltext), optional gefiltert nach "
                "Space-Key und Label. Liefert Titel, ID und Link.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "query": {"type": "STRING", "description": "Suchbegriff (Volltext)."},
            "space": {"type": "STRING", "description": "Optional: Space-Key zum Einschraenken."},
            "label": {"type": "STRING", "description": "Optional: Label zum Einschraenken."},
            "limit": {"type": "INTEGER", "description": "Max. Trefferzahl (Standard 10)."},
        }, "required": []}

    async def _ausfuehren(self, c, **kwargs):
        query = (kwargs.get("query") or "").strip()
        space = (kwargs.get("space") or "").strip() or None
        label = (kwargs.get("label") or "").strip() or None
        if not query and not space and not label:
            return "Bitte query, space oder label angeben."
        try:
            limit = max(1, min(int(kwargs.get("limit") or 10), 50))
        except (TypeError, ValueError):
            limit = 10
        try:
            data = await _to_thread(c.search, query, space, label, limit)
        except ConfluenceError as e:
            return _fmt_err(e)
        results = data.get("results", [])
        if not results:
            return "Keine Treffer."
        lines = []
        for r in results:
            link = c.link_for(data, r)
            lines.append("- %s (ID %s)%s" % (
                r.get("title", "?"), r.get("id", "?"), ("\n  " + link) if link else ""))
        return "%d Treffer:\n%s" % (len(results), "\n".join(lines))


class ConfluenceGetPageTool(_Base):
    @property
    def name(self): return "confluence_get_page"

    @property
    def description(self):
        return "Ruft den Inhalt einer Seite ab – per Seiten-ID oder Titel (+ Space-Key)."

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "Seiten-ID (bevorzugt)."},
            "title": {"type": "STRING", "description": "Seitentitel (alternativ)."},
            "space_key": {"type": "STRING", "description": "Space-Key (zusammen mit title)."},
        }, "required": []}

    async def _ausfuehren(self, c, **kwargs):
        page_id = (kwargs.get("page_id") or "").strip() or None
        title = (kwargs.get("title") or "").strip() or None
        space = (kwargs.get("space_key") or "").strip() or None
        if not page_id and not title:
            return "Bitte page_id ODER title (optional mit space_key) angeben."
        try:
            page = await _to_thread(c.get_page, page_id, title, space)
        except ConfluenceError as e:
            return _fmt_err(e)
        body = (((page.get("body") or {}).get("storage") or {}).get("value")) or ""
        sp = ((page.get("space") or {}).get("key")) or "?"
        pid = str(page.get("id") or page_id or "")
        text = _seitentext(body)
        # "Erfolgreich" steht ausdruecklich da, und der Inhalt traegt eine
        # Ueberschrift mit Laenge: ein nackter Text wie "400" direkt unter dem
        # Titel wurde als HTTP-Fehler gelesen (ECHT 2026-11-13).
        teile = ["📄 %s (ID %s, Space %s) – Seite erfolgreich abgerufen." % (
            page.get("title", "?"), pid or "?", sp)]
        if text:
            teile.append("Seiteninhalt (%d Zeichen):\n%s" % (len(text), text))
        else:
            teile.append("Seiteninhalt: KEIN Fliesstext.")
        if len(text) < KURZ_INHALT:
            makros = []
            for m in _RE_MAKRO_NAME.findall(body):
                if m not in makros:
                    makros.append(m)
            if makros:
                teile.append("Die Seite besteht ueberwiegend aus Confluence-Makros (%s). "
                             "Deren Inhalt erzeugt Confluence erst beim Anzeigen – er ist "
                             "hier nicht enthalten." % ", ".join(makros[:10]))
            if pid:
                teile.append(await self._unterseiten(c, pid))
        return "\n\n".join(teile)

    @staticmethod
    async def _unterseiten(c: ConfluenceClient, pid: str) -> str:
        try:
            kinder = await _to_thread(c.get_child_pages, pid, MAX_UNTERSEITEN)
        except ConfluenceError as e:
            return "Unterseiten konnten nicht gelesen werden: %s" % _fmt_err(e)
        if not kinder:
            return "Unterseiten: keine."
        zeilen = ["- %s (ID %s)" % (k.get("title") or "?", k.get("id") or "?")
                  for k in kinder[:MAX_UNTERSEITEN]]
        mehr = (" (hoechstens %d gezeigt – es kann weitere geben)" % MAX_UNTERSEITEN
                if len(kinder) >= MAX_UNTERSEITEN else "")
        return ("Unterseiten (%d)%s – einzeln mit confluence_get_page(page_id=…) "
                "abrufen:\n%s" % (len(zeilen), mehr, "\n".join(zeilen)))



class ConfluenceListAttachmentsTool(_Base):
    @property
    def name(self): return "confluence_list_attachments"

    @property
    def description(self):
        return ("Listet die Anhaenge einer Seite (Dateiname und Groesse). Zum HERUNTERLADEN "
                "confluence_download_attachment benutzen – NICHT curl/wget.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "ID der Seite."}}, "required": ["page_id"]}

    async def _ausfuehren(self, c, **kwargs):
        page_id = (kwargs.get("page_id") or "").strip()
        if not page_id:
            return "page_id ist erforderlich."
        try:
            atts = await _to_thread(c.list_attachments, page_id)
        except ConfluenceError as e:
            return _fmt_err(e)
        if not atts:
            return "Keine Anhaenge an Seite %s." % page_id
        # Der Download-Link wird ABSICHTLICH nicht mehr ausgegeben: er ist ohne den
        # PAT nutzlos, und solange er dastand, hat das Modell zuverlaessig curl darauf
        # angesetzt – Ergebnis waren 0-Byte-Dateien ohne Fehlermeldung (2026-07-30).
        # Stattdessen Groesse + der ausdrueckliche Hinweis auf das Download-Tool.
        lines = []
        for a in atts:
            size = ((a.get("extensions", {}) or {}).get("fileSize")
                    or (a.get("metadata", {}) or {}).get("fileSize"))
            try:
                size_txt = " (%s Byte)" % int(size) if size is not None else ""
            except (TypeError, ValueError):
                size_txt = ""
            lines.append("- %s%s" % (a.get("title", "?"), size_txt))
        return ("%d Anhang/Anhaenge:\n%s\n\nHerunterladen mit "
                "confluence_download_attachment(page_id=\"%s\", filename=\"…\") – "
                "ohne filename werden alle geladen." % (len(atts), "\n".join(lines), page_id))


class ConfluenceDownloadAttachmentTool(_Base):
    @property
    def name(self): return "confluence_download_attachment"

    @property
    def description(self):
        return ("Laedt einen Anhang einer Seite nach /tmp und gibt den lokalen Pfad zurueck – "
                "zum Weiterverarbeiten mit pandas/shell. Ohne 'filename' werden ALLE Anhaenge "
                "der Seite geladen. NUR dieses Tool benutzen, NIE curl/wget auf den Anhang-Link: "
                "der Link ist eine Web-Route, die ohne Anmeldung eine leere oder eine "
                "HTML-Datei liefert. Meldet dieses Tool, dass die Zwei-Faktor-Pruefung den "
                "Download blockiert, ist der Anhang NICHT abrufbar – dann NICHT mit curl/wget "
                "weiterprobieren (scheitert genauso), sondern dem Benutzer sagen, dass ein "
                "Administrator den Download-Pfad freischalten muss.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "page_id": {"type": "STRING", "description": "ID der Seite."},
            "filename": {"type": "STRING",
                         "description": "Dateiname des Anhangs (wie in confluence_list_attachments). "
                                        "Leer = alle Anhaenge der Seite."},
        }, "required": ["page_id"]}

    async def _ausfuehren(self, c, **kwargs):
        page_id = (kwargs.get("page_id") or "").strip()
        if not page_id:
            return "page_id ist erforderlich."
        filename = (kwargs.get("filename") or "").strip()

        names = [filename]
        if not filename:
            try:
                atts = await _to_thread(c.list_attachments, page_id)
            except ConfluenceError as e:
                return _fmt_err(e)
            names = [(a.get("title") or "") for a in atts if a.get("title")]
            if not names:
                return "Keine Anhaenge an Seite %s." % page_id

        # Zielverzeichnis des LAUFS. Der Download passiert im Backend, gelesen
        # wird der Anhang aber meist per Shell IM Lauf – und dort ist /tmp
        # ausschliesslich das Lauf-Verzeichnis (backend/lauf_tmp.py). Ohne diese
        # Zeile laege die Datei im echten /tmp und waere im Lauf nicht vorhanden.
        # Gemeldet wird deshalb der Pfad, den der Lauf SIEHT.
        import os as _os
        try:
            from backend import lauf_tmp as _lt
            ziel_verz = str(_lt.temp_verzeichnis())
        except Exception:  # noqa: BLE001
            ziel_verz = "/tmp"

        ok, failed = [], []
        for nm in names:
            try:
                path, size = await _to_thread(c.download_attachment, page_id, nm, ziel_verz)
                # Als EINGABE anmelden (Host-Pfad, vor der Umschreibung): sonst
                # haelt die Auslieferung den /tmp-Pfad im Ergebnis fuer eine
                # Ergebnisdatei und verschiebt sie nach data/documents, bevor
                # der naechste Schritt sie lesen kann (ECHT 2026-11-09).
                try:
                    _lt.eingabe_merken(path)
                except Exception:  # noqa: BLE001
                    pass
                path = "/tmp/" + _os.path.basename(path)
                ok.append((nm, path, size))
            except ConfluenceError as e:
                failed.append((nm, _fmt_err(e)))
            except Exception as e:  # noqa: BLE001
                failed.append((nm, str(e)[:200]))

        lines = []
        for nm, path, size in ok:
            lines.append("- %s -> %s (%d Byte)" % (nm, path, size))
        for nm, why in failed:
            lines.append("- %s -> FEHLER: %s" % (nm, why))
        head = "%d von %d Anhang/Anhaengen geladen:" % (len(ok), len(names))
        return head + "\n" + "\n".join(lines)



def get_tools():
    return [
        ConfluenceTestConnectionTool(),
        ConfluenceListSpacesTool(),
        ConfluenceSearchTool(),
        ConfluenceGetPageTool(),
        ConfluenceListAttachmentsTool(),
        ConfluenceDownloadAttachmentTool(),
    ]
