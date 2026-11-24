"""Schalter "sensible Daten": ein Lauf, der bei uns nichts hinterlaesst.

WARUM (Festlegung des Betreibers 2026-11-24): Fuer Chat und Short Tracks soll
es einen Schalter geben, der sicherstellt, dass KEINE Inhalte in Protokollen
erscheinen und erzeugte Dateien – auch temporaere – sofort geloescht werden.
Vorher landeten Inhalte eines Laufs an mindestens acht Stellen dauerhaft:
LLM-Verlauf (``conv_log``, ganzer Prompt samt Werkzeug-Ergebnissen),
Audit-Log (Werkzeug-Argumente im Klartext), Lernnotizen und Gedaechtnis (ohne
Frist), Anhaenge und Ergebnisse 30 Tage in ``data/documents``, das private
``/tmp`` 4 h, der Chatverlauf auf dem Server und im Browser, das
Short-Tracks-Protokoll, Journalzeilen und das Broker-Journal.

Entscheidungen des Betreibers (2026-11-24):

* **Nur Metadaten bleiben** – wer, wann, Kanal, Werkzeugname, Dauer, Token,
  Erfolg/Fehler. Jeder INHALT faellt weg (Auftrag, Argumente, Ergebnisse,
  Dateinamen, Fehlertexte mit Inhalt). Der Nachweis "wer hat wann was
  ausgeloest" bleibt damit fuer Sicherheit und BSI erhalten.
* **Externe LLM-Anbieter bleiben erlaubt** – der Schalter regelt, was BEI UNS
  liegen bleibt; die Oberflaeche sagt das dazu.
* **Ein sensibler Chat lebt nur im offenen Tab** (Frontend), der
  Gespraechszusammenhang nur im Arbeitsspeicher.
* **Ergebnisdateien**: geloescht nach dem ersten Download, spaetestens nach
  ``ERGEBNIS_FRIST_S``. Alles andere (Eingaben, Arbeitskopien, Zwischendateien)
  am Laufende.

WIE: EIN Merkmal je Lauf (ContextVar), ausgewertet an den SENKEN – nicht an
den hundert Aufrufstellen. ``asyncio.create_task`` und ``to_thread`` kopieren
den Kontext; jeder Unter-Agent, jedes Hintergrund-Lernen und jeder
Broker-Aufruf aus dem Lauf erbt das Merkmal also von selbst. Eine Senke, die
das Merkmal nicht prueft, ist eine Luecke – die Liste der Senken steht im
Waechter ``tests/test_sensibel.py``.

Der Wert der ContextVar ist ein VERAENDERLICHES dict, das alle Kopien des
Kontexts teilen: eine Datei, die ein Werkzeug in einem Thread anmeldet, ist im
Aufraeumen des Laufs sichtbar.
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import secrets
import time
from pathlib import Path

# Platzhalter fuer jeden unterdrueckten Inhalt – fest, damit man im Journal
# und in den Protokollen danach suchen kann.
MARKE = "[sensibel]"

# Ergebnisdateien: so lange darf ein Download-Chip funktionieren. Gleich der
# Gueltigkeit eines Download-Schluessels (``download_key``, 15 min).
ERGEBNIS_FRIST_S = 15 * 60

# Rueckfall nach einem Absturz: eine als sensibel vermerkte Ablage ohne
# Ergebnisfrist gehoert zu einem Lauf, der nie zu Ende kam. Gross genug fuer
# den laengsten Lauf (Short Tracks laufen Minuten, nicht Stunden).
WAISEN_FRIST_S = 4 * 3600

_cv: contextvars.ContextVar = contextvars.ContextVar("jarvis_sensibel", default=None)


def _neu() -> dict:
    return {
        "beginn": time.time(),
        "dateien": set(),      # Host-Pfade (Arbeitskopien in /tmp)
        "ablagen": set(),      # Namen in data/documents
        "ergebnisse": set(),   # davon als Ergebnis ausgeliefert
        "kennungen": set(),    # eigene Arbeitsverzeichnisse (8 Hex)
    }


def aktiv() -> bool:
    """Laeuft der aktuelle Code in einem sensiblen Lauf?"""
    return _cv.get() is not None


@contextlib.contextmanager
def scope(an: bool = True):
    """``with sensibel.scope(flag):`` – Merkmal fuer alles darin.

    ``an=False`` ist ein Leerlauf (kein Zweig am Aufrufer noetig). Ein
    verschachtelter Aufruf ERBT den offenen Lauf, statt einen neuen
    anzulegen – sonst saehe das Aufraeumen des aeusseren Laufs die Dateien des
    inneren nicht."""
    if not an or _cv.get() is not None:
        yield
        return
    token = _cv.set(_neu())
    try:
        yield
    finally:
        try:
            _cv.reset(token)
        except (ValueError, RuntimeError):
            pass


def text(s):
    """Inhalt fuer ein Protokoll: im sensiblen Lauf die Marke, sonst ``s``."""
    return MARKE if aktiv() else s


def _lauf() -> dict | None:
    return _cv.get()


def datei_merken(pfad) -> None:
    """Host-Datei, die am Laufende geloescht wird (Arbeitskopie eines Anhangs)."""
    d = _lauf()
    if d is not None and pfad:
        d["dateien"].add(str(pfad))


def ablage_merken(name: str) -> None:
    """Datei in ``data/documents`` (aus ``documents.register*``)."""
    d = _lauf()
    if d is not None and name:
        d["ablagen"].add(os.path.basename(str(name)))


def ergebnis_merken(name: str) -> None:
    """Diese Ablage ging als Download an den Benutzer – sie bleibt bis zum
    ersten Download bzw. ``ERGEBNIS_FRIST_S`` statt am Laufende zu fallen."""
    d = _lauf()
    if d is not None and name:
        n = os.path.basename(str(name))
        d["ablagen"].add(n)
        d["ergebnisse"].add(n)


def arbeit_kennung() -> str:
    """Eigenes Arbeitsverzeichnis fuer diesen Lauf (8 Hex, wie
    ``lauf_tmp.benutzer_kennung``) – das gemeinsame Verzeichnis des Benutzers
    wuerde Zwischenprodukte anderer Laeufe mitloeschen oder ueberleben lassen.
    Einmal je Lauf, damit Unter-Agenten dasselbe sehen."""
    d = _lauf()
    if d is None:
        return ""
    if not d["kennungen"]:
        d["kennungen"].add(secrets.token_hex(4))
    return next(iter(d["kennungen"]))


def vorhandene_kennung() -> str:
    """Wie ``arbeit_kennung``, legt aber keine an (fuer Zugehoerigkeitsfragen)."""
    d = _lauf()
    if d is None or not d["kennungen"]:
        return ""
    return next(iter(d["kennungen"]))


# ── Aufraeumen am Laufende ─────────────────────────────────────────────────

def _dateien_loeschen(pfade) -> int:
    n = 0
    for p in list(pfade):
        try:
            Path(p).unlink()
            n += 1
        except FileNotFoundError:
            continue
        except Exception:  # noqa: BLE001
            # Bewusst ohne Pfad im Journal: der Dateiname ist Inhalt.
            print(f"[sensibel] Arbeitskopie nicht loeschbar ({MARKE})", flush=True)
    return n


async def aufraeumen(d: dict | None = None) -> dict:
    """Am Laufende: Arbeitskopien und Zwischenablagen loeschen, Ergebnisse
    unter Frist stellen, eigenes Arbeitsverzeichnis ueber den Broker abraeumen.

    Rueckgabe: Zaehler (fuer Waechter und Journal) – OHNE Namen."""
    import asyncio
    d = d if d is not None else _lauf()
    erg = {"dateien": 0, "ablagen": 0, "ergebnisse": 0, "verzeichnisse": 0}
    if d is None:
        return erg
    erg["dateien"] = _dateien_loeschen(d["dateien"])
    d["dateien"].clear()
    try:
        from backend import documents as _docs
        for name in list(d["ablagen"]):
            if name in d["ergebnisse"]:
                if _docs.ergebnisfrist_setzen(name, ERGEBNIS_FRIST_S):
                    erg["ergebnisse"] += 1
            elif _docs.entfernen(name):
                erg["ablagen"] += 1
        d["ablagen"].clear()
        d["ergebnisse"].clear()
    except Exception as e:  # noqa: BLE001
        print(f"[sensibel] Ablagen nicht vollstaendig geloescht: {type(e).__name__}", flush=True)
    for kennung in list(d["kennungen"]):
        try:
            if await asyncio.to_thread(_verzeichnis_entfernen, kennung):
                erg["verzeichnisse"] += 1
        except Exception as e:  # noqa: BLE001
            print(f"[sensibel] Arbeitsverzeichnis nicht entfernt: {type(e).__name__}", flush=True)
    d["kennungen"].clear()
    print(f"[sensibel] Lauf aufgeraeumt: {erg['dateien']} Arbeitskopien, "
          f"{erg['ablagen']} Zwischenablagen, {erg['verzeichnisse']} Arbeitsverzeichnisse "
          f"geloescht; {erg['ergebnisse']} Ergebnisse bis Download "
          f"(hoechstens {ERGEBNIS_FRIST_S // 60} min)", flush=True)
    return erg


def _verzeichnis_entfernen(kennung: str) -> bool:
    """Eigenes Arbeitsverzeichnis entfernen – als root ueber den Broker, weil
    darin Dateien des Sandbox-Benutzers liegen (``lauf_tmp.aufraeumen_root``)."""
    from backend import lauf_tmp as _lt
    # Das Anhang-Verzeichnis derselben Kennung legt das Backend selbst an; die
    # Kopien darin sind schon geloescht (``datei_merken``), uebrig ist es leer.
    try:
        os.rmdir(_lt.ANH_ROOT / kennung)
    except OSError:
        pass
    if os.geteuid() == 0:
        return bool(_lt.aufraeumen_root(kennung))
    from backend import broker_client as _bc
    r = _bc.call_sync("lauf_aufraeumen", {"arbeit": kennung}, user="system", timeout=60)
    return bool(((r or {}).get("result") or {}).get("entfernt"))


@contextlib.asynccontextmanager
async def anfrage(an: bool = True):
    """Klammer um eine EINGEHENDE Anfrage (WebSocket-Nachricht, Track-Drop).

    Legt den sensiblen Lauf an. Gibt die Anfrage die Arbeit an einen
    Hintergrundlauf ab (``uebergeben``), raeumt DIESER am Ende auf – die
    Klammer kehrt ja zurueck, bevor der Lauf fertig ist. Sonst (Abweisung,
    Fehler vor dem Laufstart) raeumt die Klammer selbst auf: ein schon
    abgelegter Anhang darf nicht liegen bleiben, nur weil der Lauf nie begann.
    """
    if not an or _cv.get() is not None:
        yield
        return
    d = _neu()
    token = _cv.set(d)
    try:
        yield
    finally:
        try:
            _cv.reset(token)
        except (ValueError, RuntimeError):
            pass
        if not d.get("uebergeben"):
            await aufraeumen(d)


def uebergeben(coro):
    """Hintergrundlauf uebernimmt das Aufraeumen (siehe ``anfrage``).

    ``_hintergrund(sensibel.uebergeben(lauf()), ...)`` – ohne offenen Lauf
    kommt die Coroutine unveraendert zurueck (Byte-gleich im Normalfall)."""
    d = _lauf()
    if d is None:
        return coro
    d["uebergeben"] = True
    return mit_aufraeumen(coro)


def abzweigen(ablagen=()) -> dict:
    """Eigener Lauf fuer einen SPAETER startenden Auftrag (Short Tracks).

    Die Anfrage legt die Dateien ab und kehrt zurueck, der Auftrag laeuft
    Minuten spaeter aus einer Warteschlange – und bei "jede Datei einzeln"
    sind es mehrere. Jeder bekommt deshalb einen EIGENEN Lauf mit genau
    seinen Ablagen; sie werden aus der Anfrage herausgenommen, damit deren
    Aufraeumen sie nicht loescht, bevor der Auftrag sie liest. Was in der
    Anfrage uebrig bleibt (abgewiesene Dateien), raeumt die Anfrage weg."""
    d = _neu()
    eigene = {os.path.basename(str(a)) for a in (ablagen or ()) if a}
    d["ablagen"] |= eigene
    anfrage_d = _lauf()
    if anfrage_d is not None:
        anfrage_d["ablagen"] -= eigene
    return d


@contextlib.asynccontextmanager
async def fortsetzen(d: dict | None):
    """Einen abgezweigten Lauf ausfuehren und danach aufraeumen.

    Setzt das Merkmal AUSDRUECKLICH – auch auf "nicht sensibel" (``d=None``).
    Ein Warteschlangen-Task erbt den Kontext dessen, der ihn startete; ohne
    das liefe ein normaler Auftrag, den ein sensibler am Ende nachzieht, im
    sensiblen Lauf weiter (und umgekehrt)."""
    token = _cv.set(d)
    try:
        yield
    finally:
        try:
            _cv.reset(token)
        except (ValueError, RuntimeError):
            pass
        if d is not None:
            await aufraeumen(d)


async def mit_aufraeumen(coro):
    """``await sensibel.mit_aufraeumen(lauf())`` – raeumt danach IMMER auf,
    auch nach Abbruch oder Fehler (``finally``). Ohne offenen Lauf ein
    reines ``await``."""
    try:
        return await coro
    finally:
        d = _lauf()
        if d is not None:
            # Aufraeumen AUSSERHALB des Merkmals (wie ``anfrage``/``fortsetzen``):
            # die Abschlusszeile traegt nur Zaehler und soll im Journal stehen.
            token = _cv.set(None)
            try:
                await aufraeumen(d)
            except Exception as e:  # noqa: BLE001
                print(f"[sensibel] Aufraeumen fehlgeschlagen: {type(e).__name__}", flush=True)
            finally:
                try:
                    _cv.reset(token)
                except (ValueError, RuntimeError):
                    pass


# ── Fristen (unabhaengig vom Lauf) ──────────────────────────────────────────

def fristen_abraeumen() -> int:
    """Abgelaufene Ergebnisse und Waisen loeschen. Aufgerufen vom Wecker im
    Dienst (``main.py``), alle 60 s."""
    try:
        from backend import documents as _docs
        return _docs.sensible_abraeumen(time.time(), WAISEN_FRIST_S)
    except Exception as e:  # noqa: BLE001
        print(f"[sensibel] Fristen: {type(e).__name__}", flush=True)
        return 0
