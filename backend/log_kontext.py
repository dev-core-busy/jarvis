"""Wer und wodurch: Herkunft an JEDER Protokollzeile (Festlegung 2026-11-23).

WARUM: ECHT 2026-11-23 11:21 – das Fehlerlog zeigte fuer einen abgebrochenen
Chat-Auftrag nur ``agent:Hauptagent`` / ``ReadTimeout`` und einen Traceback.
Wer den Auftrag gestellt hatte, ueber welchen Kanal und von welcher Adresse,
welcher LLM-Server, welches Modell und welches Zeitlimit gerissen war: nichts
davon stand im Eintrag, obwohl der Prozess alles wusste. Im Journal sah es
nicht besser aus – ``[AGENT 606f997a] EXCEPTION:`` und darunter ein Traceback
ohne Meldungstext (``str(httpx.ReadTimeout())`` ist leer).

Vorgabe des Betreibers: aus JEDEM Protokoll muss nachvollziehbar sein, durch
was und von wem ein Problem verursacht wurde.

LOESUNG an EINER Stelle statt an rund tausend Ausgaben:

* Ein Lauf-Kontext (ContextVar) mit Wer / IP / Kanal / Weg / Auftrag / Chat /
  Agent. Er wird an den EINSTIEGEN gesetzt (HTTP- und WebSocket-Anfrage,
  Chat-Auftrag, Lauf ohne Oberflaeche) und von allem geerbt, was darin
  laeuft – auch von ``asyncio.create_task`` und ``to_thread`` (beide kopieren
  den Kontext). Der Kontext ist ein VERAENDERLICHES dict: ``verify_token``
  traegt den Benutzer nach, sobald er feststeht, und das wirkt auch fuer die
  Middleware draussen und fuer Threads, die den Kontext schon kopiert haben.
* ``stdout`` bekommt eine duenne Huelle: jede Zeile, die innerhalb eines
  Kontexts BEGINNT, traegt vorne ``[wer=… ip=… kanal=…]``. Damit sind alle
  ``print``-Zeilen erfasst, ohne sie einzeln anzufassen.
* Ein ``logging.Filter`` haengt dieselbe Kennzeichnung an Logger-Zeilen.
* ``telemetry.TraceSpan`` nimmt den Kontext beim Start mit – jeder Eintrag
  im Fehlerlog traegt ihn.
* ``fehlertext(exc)`` macht aus einer Ausnahme ohne Meldung eine lesbare
  Ursache, ``llm_aufruf_vermerken`` haengt an jede LLM-Ausnahme Anbieter,
  Endpunkt, Modell, Profil, Dauer und Zeitlimit (``add_note`` – der Typ
  bleibt, die Fehlerbehandlung dahinter merkt nichts).

Eine Zeile OHNE Kennzeichnung stammt aus keinem Benutzer-Einstieg: Start,
Zeitplaner, Hintergrund-Indizierung. Das ist selbst eine Aussage („System").

KEINE Geheimnisse: Werte werden gekuerzt und von Leerraum befreit, der Weg
traegt nur Methode und Pfad (kein Query-String) und laeuft zusaetzlich durch
``url_geheimnis.schwaerzen``; Endpunkte nennen nur Rechner und Port.
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import re
import sys
import threading
from urllib.parse import urlsplit

# Reihenfolge der Felder in der Kennzeichnung – fest, damit man im Journal
# danach greppen kann (``grep 'wer=max.muster'``).
FELDER = ("wer", "ip", "kanal", "weg", "auftrag", "chat", "agent")

_MAX_WERT = 80

_kv: contextvars.ContextVar = contextvars.ContextVar("jarvis_log_kontext", default=None)

_LEER = re.compile(r"\s+")


def _wert(v) -> str:
    """Ein Feldwert fuer die Zeile: ohne Leerraum (sonst zerfaellt die
    Kennzeichnung beim Greppen), ohne eckige Klammern, gekuerzt."""
    s = _LEER.sub("_", str(v if v is not None else "").strip())
    s = s.replace("[", "(").replace("]", ")")
    return s[:_MAX_WERT]


def _bereinigt(felder: dict) -> dict:
    return {k: _wert(v) for k, v in felder.items() if k in FELDER and _wert(v)}


# ─── Kontext setzen und lesen ────────────────────────────────────────────────

def oeffnen(**felder) -> contextvars.Token:
    """Neuen Kontext auf den geerbten setzen (leere Werte erben). Rueckgabe ist
    das Token fuer ``schliessen``. Ein NEUES dict – ein Unter-Lauf veraendert
    den Kontext seines Auftraggebers nicht."""
    alt = _kv.get() or {}
    neu = dict(alt)
    neu.update(_bereinigt(felder))
    return _kv.set(neu)


def schliessen(token) -> None:
    if token is None:
        return
    try:
        _kv.reset(token)
    except (ValueError, RuntimeError):
        # Token aus einem anderen Kontext (z. B. Generator ueber Tasks hinweg):
        # nicht werfen – ein Protokoll-Hilfsmittel darf keinen Lauf abbrechen.
        pass


@contextlib.contextmanager
def lauf(**felder):
    """``with log_kontext.lauf(wer=…, kanal=…):`` – oeffnen + schliessen."""
    token = oeffnen(**felder)
    try:
        yield
    finally:
        schliessen(token)


def ergaenzen(**felder) -> None:
    """Fehlende Felder im LAUFENDEN Kontext nachtragen (Benutzer steht erst
    nach der Token-Pruefung fest). Ohne Kontext wirkungslos – ausserhalb
    einer Anfrage soll ein ``verify_token`` keinen anlegen."""
    d = _kv.get()
    if d is None:
        return
    for k, v in _bereinigt(felder).items():
        d.setdefault(k, v)


def aktuell() -> dict:
    """Kopie des laufenden Kontexts; ``wer`` notfalls aus den Auftraggeber-
    Quellen, die die Token-Erfassung ohnehin kennt (Agent-Actor, Werkzeug-
    Benutzer, Sitzung)."""
    d = dict(_kv.get() or {})
    if "wer" not in d:
        try:
            tv = sys.modules.get("backend.token_verbrauch")
            wer = tv._benutzer() if tv is not None else ""
            if wer:
                d["wer"] = _wert(wer)
        except Exception:  # noqa: BLE001
            pass
    return d


def kennzeichen(d: dict | None = None) -> str:
    """``[wer=a ip=b kanal=c]`` oder leer, wenn nichts bekannt ist."""
    d = aktuell() if d is None else d
    teile = [f"{k}={d[k]}" for k in FELDER if d.get(k)]
    return "[" + " ".join(teile) + "]" if teile else ""


def weg_aus_scope(scope) -> str:
    """``POST /api/x`` bzw. ``WS /ws`` aus einem ASGI-Scope – ohne Query."""
    try:
        pfad = str(scope.get("path") or "")
        try:
            from backend.url_geheimnis import schwaerzen
            pfad = schwaerzen(pfad)
        except Exception:  # noqa: BLE001
            pass
        methode = "WS" if scope.get("type") == "websocket" else str(scope.get("method") or "")
        return f"{methode} {pfad}".strip()
    except Exception:  # noqa: BLE001
        return ""


def ip_aus_scope(scope) -> str:
    try:
        c = scope.get("client")
        return str(c[0]) if c else ""
    except Exception:  # noqa: BLE001
        return ""


# ─── Ursache einer Ausnahme ──────────────────────────────────────────────────

# Ausnahmen, deren str() LEER ist – ohne Deutung stuende im Protokoll nur der
# Typname, und der sagt einem Administrator nicht, was passiert ist.
_DEUTUNG = {
    "ReadTimeout": "Gegenstelle hat innerhalb des Lese-Zeitlimits nicht geantwortet",
    "WriteTimeout": "Anfrage konnte innerhalb des Zeitlimits nicht gesendet werden",
    "ConnectTimeout": "Verbindungsaufbau innerhalb des Zeitlimits nicht gelungen",
    "PoolTimeout": "keine freie Verbindung innerhalb des Zeitlimits",
    "TimeoutException": "Zeitlimit ueberschritten",
    "TimeoutError": "Zeitlimit ueberschritten",
    "CancelledError": "Lauf wurde abgebrochen",
    "ConnectError": "Gegenstelle nicht erreichbar (Verbindung abgelehnt oder Name nicht aufloesbar)",
    "RemoteProtocolError": "Gegenstelle hat die Verbindung ohne vollstaendige Antwort geschlossen",
    "ReadError": "Verbindung beim Lesen der Antwort abgerissen",
}


def fehlertext(exc: BaseException) -> str:
    """Lesbare Ursache: eigene Meldung, sonst die der Ursache (``raise … from``),
    sonst eine Deutung des Typs – plus angehaengte Vermerke (``add_note``).
    Nie leer."""
    try:
        msg = str(exc).strip()
        if not msg:
            ursache = exc.__cause__ or exc.__context__
            if ursache is not None:
                msg = str(ursache).strip()
        if not msg:
            for kl in type(exc).__mro__:
                if kl.__name__ in _DEUTUNG:
                    msg = _DEUTUNG[kl.__name__]
                    break
        if not msg:
            msg = type(exc).__name__
        notizen = [str(n).strip() for n in (getattr(exc, "__notes__", None) or []) if str(n).strip()]
        if notizen:
            msg = msg + " – " + " – ".join(notizen)
        return msg
    except Exception:  # noqa: BLE001
        return type(exc).__name__


def _endpunkt(provider) -> str:
    """Rechner:Port des LLM-Servers – ohne Benutzer, Kennwort, Pfad, Query."""
    url = str(getattr(provider, "base_url", "") or "")
    if not url:
        return ""
    try:
        t = urlsplit(url)
        host = t.hostname or ""
        return f"{host}:{t.port}" if t.port else host
    except Exception:  # noqa: BLE001
        return ""


def _zeitlimit_s(provider):
    try:
        fn = getattr(provider, "_get_timeout", None)
        to = fn() if callable(fn) else None
        read = getattr(to, "read", None)
        return float(read) if read else None
    except Exception:  # noqa: BLE001
        return None


def _profilname() -> str:
    try:
        llm = sys.modules.get("backend.llm")
        p = llm.current_agent_profile.get() if llm is not None else None
        if isinstance(p, dict):
            return str(p.get("name") or p.get("id") or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def llm_aufruf_vermerken(exc: BaseException, provider, modell: str, dauer_s: float) -> None:
    """Haengt an eine Ausnahme aus einem LLM-Aufruf, WAS gerufen wurde.

    Einmal je Ausnahme (Unter-Aufrufe reichen dieselbe Ausnahme durch).
    ``CancelledError`` bleibt unberuehrt – ein Stopp ist keine Stoerung."""
    try:
        import asyncio
        if isinstance(exc, asyncio.CancelledError) or getattr(exc, "_jarvis_llm_vermerkt", False):
            return
        anbieter = str(getattr(provider, "anbieter_kennung", "") or type(provider).__name__)
        teile = [f"Anbieter {anbieter}"]
        ep = _endpunkt(provider)
        if ep:
            teile.append(f"Server {ep}")
        if modell:
            teile.append(f"Modell {modell}")
        prof = _profilname()
        if prof:
            teile.append(f"Profil '{prof}'")
        teil = f"abgebrochen nach {dauer_s:.1f} s"
        zl = _zeitlimit_s(provider)
        if zl:
            teil += f" (Lese-Zeitlimit {zl:.0f} s)"
        teile.append(teil)
        exc.add_note("LLM-Aufruf: " + ", ".join(teile))
        exc._jarvis_llm_vermerkt = True
    except Exception:  # noqa: BLE001
        pass


# ─── Ausgabe: stdout-Huelle und Logging-Filter ───────────────────────────────

# Ersatz fuer jede Zeile, die in einem sensiblen Lauf entsteht
# (``backend/sensibel.py``, Festlegung 2026-11-24): die Kennzeichnung davor
# (wer/Kanal/Chat) ist Metadatum und bleibt, der Text ist Inhalt und faellt weg.
UNTERDRUECKT = "[sensibel] Inhalt nicht protokolliert"


def _sensibel() -> bool:
    """Liest das Lauf-Merkmal, ohne ``backend.sensibel`` zu importieren
    (dieses Modul wird sehr frueh installiert). Fehler = nicht sensibel: eine
    Protokoll-Huelle darf keinen Lauf abbrechen – das Merkmal ist eine
    ContextVar, ein Lesefehler ist praktisch ausgeschlossen."""
    try:
        m = sys.modules.get("backend.sensibel")
        return bool(m is not None and m.aktiv())
    except Exception:  # noqa: BLE001
        return False


class _KontextStrom:
    """Huelle um ``sys.stdout``: setzt die Kennzeichnung vor jede Zeile, die
    innerhalb eines Kontexts BEGINNT. Folgezeilen einer mehrzeiligen Ausgabe
    (Traceback) bleiben unveraendert – die erste Zeile traegt die Herkunft,
    hundert Wiederholungen davon waeren Laerm.

    In einem SENSIBLEN Lauf wird jede Ausgabe verschluckt; je begonnener
    Zeile erscheint einmal ``UNTERDRUECKT`` samt Kennzeichnung. Das gilt auch
    fuer Folgezeilen und mehrteilige ``print``-Aufrufe (``print(a, b)``
    schreibt viermal) – die Entscheidung faellt je ``write``, nicht je Zeile.

    ``kennzeichnen=False`` (stderr): nur die Unterdrueckung, keine
    Kennzeichnung – stderr trug sie nie, und Fremdbibliotheken schreiben
    dort Formate, die niemand umgebaut haben will."""

    _jarvis_kontext_strom = True

    def __init__(self, ziel, kennzeichnen: bool = True):
        self._ziel = ziel
        self._kennzeichnen = kennzeichnen
        self._zeilenanfang = True
        self._lock = threading.Lock()

    def write(self, s):
        if not isinstance(s, str) or not s:
            return self._ziel.write(s)
        if _sensibel():
            with self._lock:
                if self._zeilenanfang and s != "\n":
                    try:
                        kz = kennzeichen() if self._kennzeichnen else ""
                    except Exception:  # noqa: BLE001
                        kz = ""
                    self._ziel.write((kz + " " if kz else "") + UNTERDRUECKT + "\n")
                    # Die Zeile ist "erledigt": der Rest dieses print (und die
                    # Folgezeilen) beginnen keine neue Marke, bis ein Text mit
                    # Zeilenende vorbeikam.
                self._zeilenanfang = s.endswith("\n")
                return len(s)
        if not self._kennzeichnen:
            return self._ziel.write(s)
        with self._lock:
            if self._zeilenanfang and s != "\n":
                try:
                    kz = kennzeichen()
                except Exception:  # noqa: BLE001
                    kz = ""
                if kz:
                    s = kz + " " + s
            self._zeilenanfang = s.endswith("\n")
            return self._ziel.write(s)

    def writelines(self, zeilen):
        for z in zeilen:
            self.write(z)

    def __getattr__(self, name):
        return getattr(self._ziel, name)


class KontextFilter(logging.Filter):
    """Setzt ``record.kontext`` (mit fuehrendem Leerzeichen oder leer) – das
    Format nutzt ``%(kontext)s``. Fehlt das Feld, weil ein fremder Handler
    ohne Filter formatiert, bleibt die Zeile wie bisher."""

    def filter(self, record):
        try:
            kz = kennzeichen()
        except Exception:  # noqa: BLE001
            kz = ""
        record.kontext = (" " + kz) if kz else ""
        if _sensibel():
            # Stufe und Logger-Name bleiben (Metadaten), Text, Argumente und
            # Traceback fallen weg – ein Traceback zitiert Werte und Zeilen.
            record.msg = UNTERDRUECKT
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


LOG_FORMAT = "[%(levelname)s] %(name)s:%(kontext)s %(message)s"


def installieren() -> None:
    """stdout umhuellen und den Filter an die Handler des Wurzel-Loggers
    haengen. Mehrfach aufrufbar (Neuimport in Tests)."""
    if not getattr(sys.stdout, "_jarvis_kontext_strom", False):
        sys.stdout = _KontextStrom(sys.stdout)
    # stderr: nur die Unterdrueckung sensibler Laeufe (``traceback.print_exc``
    # und Warnungen schreiben dorthin).
    if not getattr(sys.stderr, "_jarvis_kontext_strom", False):
        sys.stderr = _KontextStrom(sys.stderr, kennzeichnen=False)
    filt = None
    for h in logging.getLogger().handlers:
        if not any(isinstance(f, KontextFilter) for f in h.filters):
            filt = filt or KontextFilter()
            h.addFilter(filt)
        # ``defaults``: formatiert ein Datensatz ohne Filterlauf (anderer Weg in
        # den Handler), fehlt ``kontext`` nicht – sonst warf das Format KeyError.
        h.setFormatter(logging.Formatter(LOG_FORMAT, defaults={"kontext": ""}))
