"""Geteilter VEMAS.NET-Client (REST).

Wird sowohl vom Skill (``skills/vemas/main.py``) als auch von den
``/api/vemas/*``-Endpunkten (``backend/main.py``, fuer den VEMAS-Reiter und den
Bereich ``/vemas``) benutzt – damit es nur EINE Implementierung der Auth- und
Request-Logik gibt (gleiche Aufteilung wie ``sap_client.py`` und
``confluence_client.py``).

**VEMAS.NET** (MS Consulting, ``msconsulting.de``) ist eine webbasierte
CRM-/ERP-Loesung. Der Zugang laeuft ueber den **REST-Webservice von
Vemas.NextGen** (JSON).

⚠ **DIE API IST NICHT OEFFENTLICH DOKUMENTIERT.** Geprueft am 2026-08-30:
``msconsulting.de/vemasnet/schnittstellen`` und der Blog-Eintrag zur REST-API
nennen weder Basis-URL noch Authentifizierung noch Endpunkte; der Hersteller
verweist auf Kontaktaufnahme. Deshalb ist dieser Client **bewusst generisch**
gebaut: der Administrator traegt Basis-URL, Anmeldeart und Ressourcenpfade ein,
der Client stellt nur den Transport. Eine fest verdrahtete Pfadliste waere ein
Ablaufdatum im Code (gleiche Lehre wie bei den hart codierten Imagen-Modellen
in ``GeminiProvider.generate_image``) – und auf einem Kundensystem mit anderer
Auspraegung schlicht falsch.

**Drei Anmeldearten**, weil keine belegt ist und alle drei ueblich sind:

* ``basic``  – Benutzer/Kennwort im ``Authorization``-Header (Vorgabe).
* ``bearer`` – statischer API-Token/Schluessel im Header.
* ``login``  – ``POST`` auf einen Anmelde-Endpunkt, die Antwort liefert ein
  Token, das fuer Folgeaufrufe benutzt und bei Ablauf erneuert wird.

**Nur-Lesen ist die VORGABE, aber hier – anders als bei SAP – ABSCHALTBAR**
(Entscheidung des Nutzers 2026-08-30). Der Schalter ``read_only`` liegt
ausschliesslich in der Administrator-Konfiguration; ein Benutzer kann ihn an
seinem persoenlichen Zugang NICHT setzen (siehe ``vemas_accounts.AENDERBAR``).
Zusaetzlich gilt: **geschrieben wird nur mit dem persoenlichen Zugang**, nie
ueber den Sammelzugang – siehe ``darf_schreiben()``. Begruendung dort.

Alle Netzwerk-Methoden sind synchron. Aufrufer im async-Kontext muessen sie ueber
``asyncio.to_thread`` ausfuehren, um den Event-Loop nicht zu blockieren (sonst
friert ein haengender VEMAS-Server den Dienst fuer ALLE Benutzer ein – dieselbe
Klasse Fehler wie das 20-Sekunden-``is_mount()`` von 2026-08-11).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from urllib.parse import urlparse, urljoin

import requests

# Standard-Zeitlimit fuer HTTP-Aufrufe. Bewusst grosszuegig: eine Auswertung
# ueber viele Projekte kann auf der VEMAS-Seite dauern.
_HTTP_TIMEOUT = 45

# Zeitlimit fuer die ANMELDUNG. Knapper als der Rest: wer sich nicht in zehn
# Sekunden anmelden kann, wird es auch in fuenfundvierzig nicht.
_LOGIN_TIMEOUT = 15

# Lesende HTTP-Methoden. Alles andere ist ein Schreibzugriff und faellt unter
# den Schalter ``read_only``.
_LESEN = ("GET", "HEAD", "OPTIONS")

# Schreibende Methoden, die ueberhaupt zugelassen sind, wenn der Administrator
# Schreiben freigeschaltet hat. **DELETE steht bewusst NICHT hier.** Ein
# Loeschvorgang ist nicht rueckholbar, und der Agent verarbeitet Fremdtext
# (Tickets, Mails, Anhaenge) – ein Loeschwerkzeug waere damit ueber eine
# Prompt-Injektion erreichbar. Wer wirklich loeschen will, tut das in VEMAS.
_SCHREIBEN = ("POST", "PUT", "PATCH")

# Uebliche Fundstellen einer Schnittstellenbeschreibung. Wird von
# ``beschreibung_suchen()`` der Reihe nach probiert – GEMESSEN statt geraten:
# was der Server wirklich ausliefert, entscheidet, nicht was hier steht.
_BESCHREIBUNG_PFADE = (
    "swagger/v1/swagger.json",
    "swagger/swagger.json",
    "openapi.json",
    "swagger.json",
    "api-docs",
    "v1/openapi.json",
)

# Schluessel, unter denen JSON-APIs ihre Datenzeilen ablegen. Reihenfolge ist
# Absicht: ``value`` (OData-Stil) vor den generischen Namen.
_ZEILEN_SCHLUESSEL = ("value", "items", "data", "results", "records", "rows",
                      "entries", "list")


def get_vemas_config() -> dict:
    """Liest die in der Skill-Config hinterlegten VEMAS-Werte (Sammelzugang)."""
    try:
        from backend.config import config
        return config.get_skill_states().get("vemas", {}).get("config", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


class VemasError(Exception):
    """Fehler bei einer VEMAS-Anfrage (mit optionalem HTTP-Status).

    ``status`` ist der HTTP-Status oder ``0`` fuer Netz-/Konfigurationsfehler.
    Die Unterscheidung ist nicht kosmetisch: ``vemas_accounts.ist_anmeldefehler``
    entscheidet daran, ob ein Fehlversuch gegen den Aussetzer zaehlt."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


# ── Nur-Lesen-Wache ─────────────────────────────────────────────────────────

def assert_read_only(method: str, read_only: bool = True) -> str:
    """Wirft ``VemasError``, wenn ``method`` bei aktivem Nur-Lesen schreibt.

    Gibt die normalisierte Methode zurueck. Ein unbekanntes Verb wird
    **abgelehnt, nicht durchgereicht** (fail-closed): ``requests`` schickt
    klaglos jedes Wort als Methode, und ein Tippfehler soll nicht an der
    Schranke vorbeilaufen."""
    m = (method or "GET").strip().upper()
    if m in _LESEN:
        return m
    if m not in _SCHREIBEN:
        raise VemasError(0, "HTTP-Methode '%s' ist nicht zugelassen (erlaubt: %s)."
                            % (m, ", ".join(_LESEN + _SCHREIBEN)))
    if read_only:
        raise VemasError(0, "Nur-Lesen ist aktiv – '%s' ist gesperrt. Ein "
                            "Administrator kann Schreibzugriffe unter "
                            "Einstellungen → Vemas freigeben." % m)
    return m


def _pfad_sauber(pfad: str) -> str:
    """Entschaerft einen vom Modell gelieferten Ressourcenpfad.

    Verworfen wird alles, was die Basis-URL VERLASSEN wuerde: ein absoluter
    ``http(s)://``-Pfad (das waere die SSRF-Flaeche, gegen die es die
    Host-Freigabeliste ueberhaupt gibt), ein Wechsel auf einen anderen Host per
    ``//host`` und ``..``-Anteile. **Das Modell darf den Pfad bestimmen, aber
    nicht den Server** – sonst waere jedes Werkzeug ein Portscanner."""
    p = (pfad or "").strip()
    if not p:
        raise VemasError(0, "Kein Pfad angegeben.")
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", p):
        raise VemasError(0, "Vollstaendige URLs sind nicht erlaubt – gib nur den "
                            "Pfad relativ zur Basis-URL an (z.B. 'projekte').")
    if p.startswith("//"):
        raise VemasError(0, "Ein Pfad darf nicht mit '//' beginnen (das waere ein "
                            "anderer Server).")
    if any(teil == ".." for teil in p.replace("\\", "/").split("/")):
        raise VemasError(0, "'..' ist im Pfad nicht erlaubt.")
    return p.lstrip("/")


# ── Anmelde-Token-Speicher (nur fuer auth_kind='login') ─────────────────────
#
# WARUM ES DEN SPEICHER BRAUCHT: der Client wird pro Werkzeug-Aufruf neu gebaut
# (``_Base.execute`` loest den Zugang jedes Mal auf). Ohne Speicher meldete sich
# JEDER Aufruf neu an – bei einer Auswertung ueber zehn Werkzeug-Schritte sind
# das zehn Anmeldungen. Das ist nicht nur langsam: viele Systeme zaehlen
# Anmeldungen mit, und eine Auswertung saehe von aussen wie ein Angriff aus.
#
# Der Schluessel enthaelt den HASH der Zugangsdaten, nicht die Daten selbst –
# ein geaendertes Kennwort erzeugt damit von selbst einen neuen Eintrag, und im
# Speicher steht nie ein Klartext-Kennwort.
_TOKEN_CACHE: dict = {}
_TOKEN_LOCK = threading.Lock()

# Sicherheitsabstand vor dem Ablauf: ein Token, das in zwei Sekunden verfaellt,
# ist fuer eine Anfrage, die 45 Sekunden dauern darf, bereits wertlos.
_TOKEN_PUFFER_S = 60


def _cache_key(base: str, user: str, secret: str, pfad: str) -> str:
    roh = "%s|%s|%s|%s" % (base, user, pfad, secret)
    return hashlib.sha256(roh.encode("utf-8", "replace")).hexdigest()


def token_cache_leeren() -> None:
    """Alle gespeicherten Anmelde-Token verwerfen.

    Wird nach dem Speichern einer Konfiguration gerufen: sonst arbeitete der
    naechste Aufruf noch Minuten mit dem Token der ALTEN Zugangsdaten und der
    Administrator haelt seine Aenderung fuer wirkungslos."""
    with _TOKEN_LOCK:
        _TOKEN_CACHE.clear()


def _json_pfad(daten, pfad: str):
    """Holt einen Wert aus verschachteltem JSON ueber ``a.b.c``.

    Gibt ``None`` zurueck, wenn der Pfad nicht existiert – der Aufrufer meldet
    dann einen Klartext-Fehler mit den tatsaechlich vorhandenen Schluesseln.
    Das ist der Unterschied zwischen 'Anmeldung fehlgeschlagen' und 'ich habe
    das Token an der erwarteten Stelle nicht gefunden, hier ist, was da war'."""
    cur = daten
    for teil in [t for t in (pfad or "").split(".") if t]:
        if not isinstance(cur, dict) or teil not in cur:
            return None
        cur = cur[teil]
    return cur


class VemasClient:
    """Lesender (und optional schreibender) REST-Zugriff auf VEMAS.NET."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg if cfg is not None else get_vemas_config()
        c = self.cfg
        self.base = (c.get("base_url") or "").strip().rstrip("/")
        self.auth_kind = (c.get("auth_kind") or "basic").strip().lower()
        self.user = (c.get("username") or "").strip()
        self.password = c.get("password") or ""
        self.token = (c.get("api_token") or "").strip()
        # Nur-Lesen: Vorgabe AN. ``is not False`` und nicht ``bool()`` – ein
        # fehlendes Feld (Altbestand, handgeschriebene settings.json) muss die
        # SICHERE Seite treffen, nicht die offene.
        self.read_only = c.get("read_only") is not False
        self.verify = c.get("verify_ssl") is not False
        self.produkt = (c.get("vemas_product") or "").strip()
        # Anmelde-Endpunkt (nur bei auth_kind='login')
        self.login_path = (c.get("login_path") or "").strip()
        self.login_user_field = (c.get("login_user_field") or "username").strip()
        self.login_pass_field = (c.get("login_pass_field") or "password").strip()
        self.token_json_path = (c.get("token_json_path") or "token").strip()
        self.token_header = (c.get("token_header") or "Authorization").strip()
        self.token_prefix = c.get("token_prefix")
        if self.token_prefix is None:
            self.token_prefix = "Bearer "
        self.mandant = (c.get("mandant") or "").strip()
        self.mandant_param = (c.get("mandant_param") or "").strip()

    # ── Zustand ────────────────────────────────────────────────────────────
    @property
    def configured(self) -> bool:
        """Reicht die Konfiguration, um ueberhaupt eine Anfrage zu stellen?

        Die Basis-URL allein genuegt: ein VEMAS-System kann auch anonym lesbare
        Endpunkte haben, und ein 401 ist eine bessere Auskunft als 'nicht
        konfiguriert' (letzteres schickt den Benutzer an die falsche Stelle)."""
        return bool(self.base)

    @property
    def host(self) -> str:
        try:
            return (urlparse(self.base).hostname or "").lower()
        except Exception:  # noqa: BLE001
            return ""

    def darf_schreiben(self) -> bool:
        """Nur wenn der Administrator es freigeschaltet hat."""
        return not self.read_only

    # ── Anmeldung ──────────────────────────────────────────────────────────
    def _login_token(self) -> str:
        """Token ueber den Anmelde-Endpunkt holen (mit Zwischenspeicher)."""
        if not self.login_path:
            raise VemasError(0, "Anmeldeart 'login' ist gewaehlt, aber kein "
                                "Anmelde-Pfad hinterlegt (Feld 'login_path', "
                                "z.B. 'auth/login').")
        if not self.user:
            raise VemasError(0, "Anmeldeart 'login' braucht einen Benutzernamen.")
        key = _cache_key(self.base, self.user, self.password, self.login_path)
        jetzt = time.time()
        with _TOKEN_LOCK:
            eintrag = _TOKEN_CACHE.get(key)
            if eintrag and eintrag[1] > jetzt + _TOKEN_PUFFER_S:
                return eintrag[0]

        url = self._url(_pfad_sauber(self.login_path))
        rumpf = {self.login_user_field: self.user, self.login_pass_field: self.password}
        try:
            r = requests.post(url, json=rumpf, verify=self.verify,
                              headers={"Accept": "application/json"},
                              timeout=_LOGIN_TIMEOUT)
        except requests.RequestException as e:
            raise VemasError(0, "Netzwerkfehler bei der Anmeldung: %s" % e) from None
        if r.status_code in (401, 403):
            # Als ANMELDEFEHLER kenntlich (Status bleibt erhalten) – nur so
            # zaehlt der Aussetzer richtig.
            raise VemasError(r.status_code,
                             "Anmeldung abgelehnt (HTTP %s). Benutzer/Kennwort pruefen."
                             % r.status_code)
        if r.status_code >= 400:
            raise VemasError(r.status_code, "Anmeldung fehlgeschlagen: %s"
                                            % ((r.text or "")[:300] or r.status_code))
        try:
            daten = r.json()
        except ValueError:
            raise VemasError(0, "Der Anmelde-Endpunkt hat kein JSON geliefert.") from None
        wert = _json_pfad(daten, self.token_json_path)
        if not isinstance(wert, str) or not wert.strip():
            vorhanden = ", ".join(sorted(daten.keys())) if isinstance(daten, dict) else "(kein Objekt)"
            raise VemasError(0, "Im Anmelde-Ergebnis steht unter '%s' kein Token. "
                                "Vorhandene Felder: %s. Feld 'token_json_path' anpassen."
                             % (self.token_json_path, vorhanden))
        # Gueltigkeit: was der Server sagt, sonst eine halbe Stunde. Bewusst
        # KONSERVATIV – ein zu lange gehaltenes Token laesst jede Anfrage mit
        # 401 scheitern, ein zu kurz gehaltenes kostet nur eine Anmeldung.
        dauer = 1800
        for feld in ("expires_in", "expiresIn", "expires", "ttl"):
            v = _json_pfad(daten, feld) if isinstance(daten, dict) else None
            try:
                if v is not None and int(v) > 0:
                    dauer = min(int(v), 86400)
                    break
            except (TypeError, ValueError):
                continue
        with _TOKEN_LOCK:
            _TOKEN_CACHE[key] = (wert.strip(), jetzt + dauer)
        return wert.strip()

    def _auth(self):
        """Tupel fuer ``requests``-Basic-Auth (oder ``None``)."""
        if self.auth_kind == "basic" and self.user:
            return (self.user, self.password)
        return None

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Accept": "application/json"}
        if self.auth_kind == "bearer" and self.token:
            h[self.token_header] = "%s%s" % (self.token_prefix, self.token)
        elif self.auth_kind == "login":
            h[self.token_header] = "%s%s" % (self.token_prefix, self._login_token())
        h.update(extra or {})
        return h

    def _url(self, pfad: str) -> str:
        """Absolute URL aus Basis + Pfad.

        ZWEI Fallen, beide vom Test gefunden:
        ``urljoin('https://h/api', 'x')`` ergibt ``https://h/x`` – der
        Basis-Pfad faellt weg, deshalb der abschliessende Schraegstrich. Und ein
        Pfad, der SELBST mit ``/`` beginnt, gilt urljoin als absolut und
        ueberschreibt den Basis-Pfad genauso (``https://h/projekte`` statt
        ``https://h/api/projekte``). Das Abstreifen gehoert deshalb HIERHER und
        nicht in den Aufrufer: sonst haengt die Richtigkeit daran, dass jeder
        kuenftige Aufrufer daran denkt."""
        return urljoin(self.base + "/", (pfad or "").lstrip("/"))

    def _params(self, params: dict | None) -> dict:
        p = dict(params or {})
        if self.mandant and self.mandant_param:
            p.setdefault(self.mandant_param, self.mandant)
        return p

    # ── Anfragen ───────────────────────────────────────────────────────────
    def anfrage(self, method: str, pfad: str, params: dict | None = None,
                rumpf=None) -> dict:
        """Fuehrt eine Anfrage aus und liefert JSON (oder wirft ``VemasError``).

        **Die Nur-Lesen-Pruefung sitzt HIER**, nicht beim Aufrufer: so kann kein
        Werkzeug und kein Endpunkt sie umgehen, und Sammelzugang wie
        persoenlicher Zugang teilen sich dieselbe Entscheidung (gleiche
        Begruendung wie beim Zertifikats-Ziel im ``sap_client``)."""
        if not self.configured:
            raise VemasError(0, "VEMAS ist nicht konfiguriert (Basis-URL fehlt).")
        m = assert_read_only(method, self.read_only)
        url = self._url(_pfad_sauber(pfad))
        try:
            r = requests.request(m, url, params=self._params(params),
                                 json=rumpf if m in _SCHREIBEN else None,
                                 headers=self._headers(
                                     {"Content-Type": "application/json"}
                                     if m in _SCHREIBEN else None),
                                 auth=self._auth(), verify=self.verify,
                                 timeout=_HTTP_TIMEOUT)
        except requests.RequestException as e:
            raise VemasError(0, "Netzwerkfehler: %s" % e) from None
        if r.status_code >= 400:
            raise VemasError(r.status_code, self._fehlertext(r))
        if not (r.text or "").strip():
            return {}
        try:
            daten = r.json()
        except ValueError:
            # Kein JSON – der haeufigste Fall ist eine HTML-Anmeldeseite, und
            # die als "Ergebnis" durchzureichen waere schlimmer als ein Fehler:
            # das Modell wuerde daraus Zahlen erfinden.
            kopf = (r.headers.get("Content-Type") or "").lower()
            if "html" in kopf or (r.text or "").lstrip()[:1] == "<":
                raise VemasError(0, "Der Server hat HTML statt JSON geliefert – "
                                    "vermutlich eine Anmeldeseite. Basis-URL und "
                                    "Anmeldeart pruefen.") from None
            raise VemasError(0, "Antwort ist kein JSON (Content-Type: %s)."
                             % (kopf or "unbekannt")) from None
        return daten if isinstance(daten, (dict, list)) else {}

    @staticmethod
    def _fehlertext(r) -> str:
        """Lesbare Meldung aus einer Fehlerantwort ziehen."""
        try:
            j = r.json()
        except ValueError:
            return (r.text or "")[:300] or ("HTTP %s" % r.status_code)
        if isinstance(j, dict):
            for feld in ("message", "error_description", "error", "detail",
                         "title", "Message"):
                v = j.get(feld)
                if isinstance(v, str) and v.strip():
                    return v.strip()[:300]
                if isinstance(v, dict):
                    m = v.get("value") or v.get("message")
                    if isinstance(m, str) and m.strip():
                        return m.strip()[:300]
        return json.dumps(j)[:300] if j else ("HTTP %s" % r.status_code)

    def get(self, pfad: str, params: dict | None = None):
        return self.anfrage("GET", pfad, params)

    @staticmethod
    def zeilen_aus(payload) -> list:
        """Extrahiert die Datenzeilen aus einer JSON-Antwort.

        Bewusst tolerant: ohne Schnittstellenbeschreibung ist nicht bekannt, wie
        VEMAS seine Listen verpackt. Eine Liste an der Wurzel, ein bekannter
        Sammel-Schluessel, sonst das Objekt selbst als EINE Zeile – ein leeres
        Ergebnis waere hier die schlechtere Antwort, weil das Modell daraus
        'keine Daten vorhanden' schliesst."""
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for s in _ZEILEN_SCHLUESSEL:
            v = payload.get(s)
            if isinstance(v, list):
                return v
            # Eine Ebene tiefer (haeufig: {"data": {"items": [...]}}).
            if isinstance(v, dict):
                for s2 in _ZEILEN_SCHLUESSEL:
                    v2 = v.get(s2)
                    if isinstance(v2, list):
                        return v2
        return [payload]

    def abfragen(self, pfad: str, params: dict | None = None,
                 top: int = 50) -> list:
        """Liest Zeilen einer Ressource; ``top`` begrenzt die Rueckgabe.

        Die Begrenzung wird ZUSAETZLICH lokal angewandt: ob der Server einen
        ``$top``/``limit``-Parameter versteht, ist unbekannt – verlaesst man
        sich darauf, kommt im Zweifel der ganze Bestand zurueck und sprengt das
        Kontextfenster."""
        try:
            n = max(1, min(int(top or 50), 5000))
        except (TypeError, ValueError):
            n = 50
        p = dict(params or {})
        # Beide gaengigen Schreibweisen anbieten, aber keine erzwingen: ein
        # unbekannter Parameter wird von den meisten Servern ignoriert.
        p.setdefault("$top", n)
        p.setdefault("limit", n)
        return self.zeilen_aus(self.get(pfad, p))[:n]

    # ── Beschreibung der Schnittstelle ─────────────────────────────────────
    def beschreibung_suchen(self) -> dict:
        """Sucht eine OpenAPI-/Swagger-Beschreibung und listet die Endpunkte.

        **Das ist der ehrliche Ersatz fuer die fehlende Doku:** statt Pfade zu
        raten, wird gemessen, was der Server ueber sich selbst sagt. Findet sich
        nichts, sagt das Ergebnis genau das – und nennt die Pfade, die probiert
        wurden. Eine erfundene Endpunktliste waere hier der teuerste Fehler:
        das Modell probierte sie der Reihe nach durch, jeder Fehlgriff kostet
        einen Schritt und (bei aktivem Aussetzer) einen Fehlversuch."""
        versucht = []
        for p in _BESCHREIBUNG_PFADE:
            versucht.append(p)
            try:
                daten = self.get(p)
            except VemasError:
                continue
            if isinstance(daten, dict) and isinstance(daten.get("paths"), dict):
                pfade = []
                for pfad, ops in sorted(daten["paths"].items()):
                    methoden = sorted(k.upper() for k in (ops or {})
                                      if k.lower() in ("get", "post", "put",
                                                       "patch", "delete"))
                    kurz = ""
                    if isinstance(ops, dict):
                        g = ops.get("get") or {}
                        if isinstance(g, dict):
                            kurz = (g.get("summary") or g.get("description") or "")[:120]
                    pfade.append({"pfad": pfad, "methoden": methoden, "info": kurz})
                info = daten.get("info") or {}
                return {"gefunden": True, "quelle": p,
                        "titel": (info.get("title") or "") if isinstance(info, dict) else "",
                        "version": (info.get("version") or "") if isinstance(info, dict) else "",
                        "pfade": pfade}
        return {"gefunden": False, "versucht": versucht, "pfade": []}

    # ── Vom Administrator gepflegte Ressourcen ─────────────────────────────
    def ressourcen(self) -> list[dict]:
        """Die im Reiter hinterlegte Zuordnung ``Name = Pfad``.

        Ohne oeffentliche Doku ist DAS die verlaessliche Quelle: der
        Administrator traegt einmal ein, unter welchem Pfad die Projekte, die
        Kunden und die Zeiten liegen, und alle Werkzeuge arbeiten damit.
        Format je Zeile ``anzeigename = pfad`` oder nur ``pfad``."""
        roh = self.cfg.get("resources") or ""
        if isinstance(roh, (list, tuple)):
            zeilen = [str(x) for x in roh]
        else:
            zeilen = str(roh).splitlines()
        out = []
        for z in zeilen:
            s = z.strip()
            if not s or s.startswith("#"):
                continue
            if "=" in s:
                name, _, pfad = s.partition("=")
                name, pfad = name.strip(), pfad.strip()
            else:
                name, pfad = s.strip("/").split("/")[-1] or s, s
            if not pfad:
                continue
            out.append({"name": name or pfad, "pfad": pfad.lstrip("/")})
        return out

    def ressource_pfad(self, name_oder_pfad: str) -> str:
        """Loest einen Ressourcen-NAMEN auf; ein Pfad bleibt unveraendert.

        Damit darf das Modell 'Projekte' sagen und muss den technischen Pfad
        nicht kennen. Gross-/Kleinschreibung ist egal – ein Modell schreibt
        denselben Namen selten zweimal gleich."""
        s = (name_oder_pfad or "").strip()
        if not s:
            raise VemasError(0, "Keine Ressource angegeben.")
        klein = s.lower()
        for r in self.ressourcen():
            if r["name"].lower() == klein or r["pfad"].lower() == klein:
                return r["pfad"]
        return s

    # ── Verbindungstest ────────────────────────────────────────────────────
    def test(self) -> dict:
        """Prueft die Verbindung und liefert ``{ok, detail, ...}``.

        Reihenfolge ist Absicht: erst der vom Administrator hinterlegte
        Test-Pfad (der weiss am besten, was auf DIESEM System existiert), dann
        die erste konfigurierte Ressource, dann die Schnittstellenbeschreibung,
        zuletzt die nackte Basis-URL. Ohne diese Kette meldete der Test auf
        einem gesunden System '404' und sieht wie ein Fehler aus."""
        if not self.configured:
            raise VemasError(0, "VEMAS ist nicht konfiguriert (Basis-URL fehlt).")
        kandidaten = []
        tp = (self.cfg.get("test_path") or "").strip()
        if tp:
            kandidaten.append(tp)
        res = self.ressourcen()
        if res:
            kandidaten.append(res[0]["pfad"])
        kandidaten.extend(_BESCHREIBUNG_PFADE[:2])
        kandidaten.append("")

        letzter = None
        for p in kandidaten:
            try:
                if p:
                    daten = self.get(p, {"$top": 1, "limit": 1})
                else:
                    daten = self.get("")
            except VemasError as e:
                # 401/403 sind ein ERGEBNIS, kein Grund weiterzuprobieren: der
                # Server antwortet, die Anmeldung stimmt nicht. Weiterprobieren
                # wuerde nur weitere Fehlversuche erzeugen.
                if e.status in (401, 403):
                    raise
                letzter = e
                continue
            n = len(self.zeilen_aus(daten))
            return {"ok": True, "pfad": p or "/",
                    "detail": "Antwort von '%s' (%d Datensatz/Datensaetze)"
                              % (p or "/", n),
                    "zeilen": n}
        raise letzter or VemasError(0, "Keine Antwort von der Basis-URL.")


def reporting_hinweis(base: str) -> list[dict]:
    """Anbindungsangaben fuer die gaengigen Auswertungs-Werkzeuge.

    Bewusst knapp und ehrlich: ohne dokumentierte API laesst sich nur der
    allgemeine Weg nennen (JSON ueber HTTP), nicht ein fertiger Connector."""
    b = (base or "").rstrip("/") or "https://<vemas-server>/api"
    return [
        {"id": "powerbi", "name": "Power BI",
         "hinweis": "Daten abrufen → Web → '%s/<ressource>' (JSON). "
                    "Authentifizierung wie im Reiter hinterlegt." % b},
        {"id": "excel", "name": "Excel (Power Query)",
         "hinweis": "Daten → Aus dem Web → '%s/<ressource>'; anschliessend "
                    "'In Tabelle konvertieren'." % b},
        {"id": "tableau", "name": "Tableau",
         "hinweis": "Web Data Connector bzw. JSON-Datei ueber '%s/<ressource>'." % b},
        {"id": "qlik", "name": "Qlik",
         "hinweis": "REST-Connector auf '%s/<ressource>'." % b},
    ]


__all__ = ["VemasClient", "VemasError", "get_vemas_config", "assert_read_only",
           "reporting_hinweis", "token_cache_leeren"]
