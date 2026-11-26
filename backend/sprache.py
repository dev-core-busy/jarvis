"""Servertexte in der Sprache der Oberflaeche (de/en/fr/nl).

WARUM (gemeldet 2026-11-24): Die Oberflaeche war vollstaendig dreisprachig,
aber was der SERVER sagte – Fehler, Hinweise, Ablehnungen –, kam als fester
deutscher Satz. Bei FR stand dann "Échec : Keine gültige Absenderadresse".
Gezaehlt: rund 430 solcher Saetze in main.py.

WIE DIE SPRACHE ZUM SERVER KOMMT: ``i18n.js`` legt die gewaehlte Sprache als
Cookie ``jarvis_lang`` ab (bei jedem Laden und bei jedem Wechsel). Ein Cookie
geht bei JEDER Anfrage derselben Herkunft mit – auch bei Downloads, Formularen
und WebSockets, ohne dass eines der rund 70 Frontend-Module etwas dafuer tun
muss. Eine fetch-Huelle oder ein Kopfzeilen-Feld haette jedes Modul einzeln
erreichen muessen. Ein ausdrueckliches ``?lang=`` (aeltere Endpunkte) gewinnt.

WIE UEBERSETZT WIRD: die Middleware in main.py reicht jede JSON-Antwort an
``antwort_uebersetzen``. Textfelder (``FELDER``) mit einem deutschen Satz, zu
dem ``backend/server_texte.json`` einen Eintrag hat, werden ersetzt. Der Satz
im Code IST der Schluessel – kein Endpunkt muss dafuer geaendert werden. Saetze
mit Werten (f-Strings) stehen dort mit ``{w1}``, ``{w2}`` … und werden als
Muster erkannt. Fehlt eine Uebersetzung: fr/nl -> en -> der deutsche Satz.
Die Datei ist bewusst NICHT i18n.js: diese Saetze braucht nur der Server, im
Browser kosteten sie jeden Seitenaufruf ~60 KB.

STANDARDSPRACHE DER INSTALLATION (2026-11-26): ein Browser, der noch nie eine
Sprache gewaehlt hat, bekam bisher immer Deutsch – auch auf einem Server, der
in Franzoesisch installiert wurde. ``extra.standard_sprache`` in settings.json
(``vorgabe()``) gilt jetzt fuer Anfragen ohne Cookie, und die Middleware gibt
sie einem solchen Browser mit der HTML-Seite als Cookie mit
(``cookie_vorgabe``) – i18n.js liest dieses Cookie, solange im Browser keine
eigene Wahl gespeichert ist. Bewusst unter ``extra``: settings.json behaelt
beim Speichern nur bekannte Schluessel und diesen Abschnitt.
Waechter ``tests/test_standard_sprache.py`` + ``test_standard_sprache_ui.js``.

Waechter: ``tests/test_server_sprache.py`` (Wirkung + Regel: jeder deutsche
Antwortsatz in main.py hat EN/FR), Gegenprobe ``tests/gegen_server_sprache.py``.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
from pathlib import Path

SPRACHEN = ("de", "en", "fr", "nl")
COOKIE = "jarvis_lang"
_RUECKFALL = {"de": ("de",), "en": ("en", "de"), "fr": ("fr", "en", "de"), "nl": ("nl", "en", "de")}

_aktuell: contextvars.ContextVar = contextvars.ContextVar("jarvis_sprache", default="de")
_cache: dict = {}


def normieren(wert) -> str:
    w = str(wert or "").strip().lower()[:5]
    return w if w in SPRACHEN else ""


# settings.json des Dienstes (DATA_DIR wie backend/config.py). In der
# root-eigenen Broker-Kopie gibt es die Datei dort nicht – vorgabe() ist dann leer.
EINSTELLUNGEN = Path(os.getenv("DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))) \
    / "settings.json"
_vorgabe_cache: dict = {}


def vorgabe() -> str:
    """Standardsprache der Installation (``extra.standard_sprache``), "" = keine.

    Liest die Datei direkt (kein Import von backend.config: dieses Modul laeuft
    auch in der Broker-Kopie) und merkt sich den Wert je Aenderungszeit."""
    try:
        stempel = EINSTELLUNGEN.stat().st_mtime_ns
    except OSError:
        return ""
    if _vorgabe_cache.get("stempel") == stempel:
        return _vorgabe_cache["wert"]
    try:
        extra = json.loads(EINSTELLUNGEN.read_text(encoding="utf-8")).get("extra") or {}
        wert = normieren(extra.get("standard_sprache")) if isinstance(extra, dict) else ""
    except (OSError, ValueError, AttributeError):
        wert = ""
    _vorgabe_cache.update(stempel=stempel, wert=wert)
    return wert


def aus_anfrage(request) -> str:
    """Sprache einer Anfrage: ``?lang=`` > Cookie ``jarvis_lang`` > Vorgabe der Installation > de."""
    try:
        q = normieren(request.query_params.get("lang"))
        if q:
            return q
        return normieren(request.cookies.get(COOKIE)) or vorgabe() or "de"
    except Exception:  # noqa: BLE001
        return "de"


def cookie_vorgabe(request) -> str:
    """Sprache, die einer Anfrage OHNE gueltiges Sprach-Cookie als Cookie
    mitgegeben wird – "" = nichts setzen (Cookie da oder keine Vorgabe).

    Eine eigene Wahl des Browsers wird nie ueberschrieben: liegt ein gueltiges
    Cookie vor, bleibt es."""
    try:
        if normieren(request.cookies.get(COOKIE)):
            return ""
    except Exception:  # noqa: BLE001
        return ""
    return vorgabe()


def setzen(sprache: str):
    """ContextVar fuer die laufende Anfrage setzen; liefert das Token zum Zuruecksetzen."""
    return _aktuell.set(normieren(sprache) or "de")


def zuruecksetzen(token) -> None:
    try:
        _aktuell.reset(token)
    except (ValueError, LookupError):
        pass


def aktuell() -> str:
    return _aktuell.get()


TEXTE = Path(__file__).resolve().parent / "server_texte.json"


def texte() -> list:
    """Eintraege [{"de":…, "en":…, "fr":…, "nl":…}] aus server_texte.json (Cache nach mtime)."""
    try:
        stempel = TEXTE.stat().st_mtime
    except OSError:
        return []
    if _cache.get("stempel") == stempel:
        return _cache["texte"]
    try:
        roh = json.loads(TEXTE.read_text(encoding="utf-8"))
        erg = [e for e in roh.get("saetze", []) if isinstance(e, dict) and e.get("de")]
    except (OSError, ValueError, AttributeError):
        return []
    _cache.update(stempel=stempel, texte=erg)
    return erg


# Diese Felder einer JSON-Antwort sind Saetze fuer Menschen (oberste Ebene).
FELDER = ("error", "detail", "meldung", "message", "grund", "hinweis", "fehler", "msg",
          # Lizenz-Warnung im Portal (/api/me, nur Admins)
          "license_banner")
ANTWORT_MAX = 256 * 1024
_index: dict = {}


def _index_bauen() -> dict:
    """{"genau": {de: eintrag}, "muster": [(regex, eintrag, namen)]}."""
    alle = texte()
    if _index.get("quelle") is alle:
        return _index
    genau, muster = {}, []
    for e in alle:
        de = e["de"]
        namen = re.findall(r"\{(w\d+)\}", de)
        if namen:
            teile = re.split(r"\{w\d+\}", de)
            rx = "^" + "(.+?)".join(re.escape(t) for t in teile) + "$"
            muster.append((re.compile(rx, re.S), e, namen))
        else:
            genau[de] = e
    # laengere Muster zuerst: das spezifischere gewinnt
    muster.sort(key=lambda m: -len(m[0].pattern))
    _index.clear()
    _index.update(quelle=alle, genau=genau, muster=muster)
    return _index


def _in_sprache(e: dict, sprache: str) -> str:
    for s_ in _RUECKFALL.get(sprache, ("de",)):
        if e.get(s_):
            return e[s_]
    return e["de"]


def satz_uebersetzen(satz, sprache: str) -> str | None:
    """Uebersetzung eines deutschen Satzes aus dem Code – oder None (unbekannt/de)."""
    if not isinstance(satz, str) or not satz or normieren(sprache) in ("", "de"):
        return None
    idx = _index_bauen()
    e = idx.get("genau", {}).get(satz)
    if e:
        aus = _in_sprache(e, sprache)
        return aus if aus != satz else None
    for rx, e, namen in idx.get("muster", []):
        m = rx.match(satz)
        if m:
            werte = dict(zip(namen, m.groups()))
            aus = re.sub(r"\{(w\d+)\}", lambda x: werte.get(x.group(1), x.group(0)), _in_sprache(e, sprache))
            return aus if aus != satz else None
    return None


def satz(de: str, /, **werte) -> str:
    """Ausdruecklich uebersetzen (fuer Texte ausserhalb einer JSON-Antwort):
    ``satz("Konto {w1} gesperrt", w1=name)`` in der Sprache der Anfrage."""
    text = de
    for k, v in werte.items():
        text = text.replace("{%s}" % k, str(v))
    return satz_uebersetzen(text, aktuell()) or text


def antwort_uebersetzen(roh: bytes, sprache: str) -> bytes | None:
    """JSON-Antwort mit uebersetzten Textfeldern – oder None (nichts geaendert)."""
    if not roh or len(roh) > ANTWORT_MAX:
        return None
    try:
        daten = json.loads(roh)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(daten, dict):
        return None
    geaendert = False
    for feld in FELDER:
        neu = satz_uebersetzen(daten.get(feld), sprache)
        if neu is not None:
            daten[feld] = neu
            geaendert = True
    if not geaendert:
        return None
    return json.dumps(daten, ensure_ascii=False).encode("utf-8")
