"""Privates ``/tmp`` pro Agent-Lauf – eine Stelle fuer Verzeichnis, Bindung, Aufloesung.

WARUM ES DAS GIBT
-----------------
Alle Domain-Benutzer fuehren Shell-Befehle als EIN OS-Benutzer aus
(``jarvis_sandbox``). Die Trennung Dienst <-> Sandbox ist intakt
(``data/documents`` und ``data/chats`` sind 0750), die Trennung Benutzer <->
Benutzer in ``/tmp`` gab es aber NICHT: ``/tmp`` ist 1777, eine Anhang-
Arbeitskopie entsteht 0644, und weil alle Laeufe dieselbe uid haben, konnte
jeder Lauf die Dateien jedes anderen lesen (auf DEV nachgestellt: ``cat`` auf
eine fremde Arbeitskopie liefert den Inhalt, ``ls /tmp`` listete 110 Eintraege).

**Dateirechte sind fuer dieses Problem die falsche Ebene** (gemessen): ein
Unterverzeichnis mit 0700 hilft nicht, weil der zweite Lauf dieselbe uid hat.
Ein OS-Benutzer je Person ist ausdruecklich verworfen – er loest es auch nicht,
``/tmp`` bliebe gemeinsam. Die Loesung ist ein MOUNT-NAMESPACE je Lauf.

DER KERN: EIN ARBEITSVERZEICHNIS JE BENUTZER WIRD AUF ``/tmp`` GEMOUNTET
------------------------------------------------------------------------
Der eigentliche Aufwand liegt nicht in der Isolation, sondern in den
UEBERGABEN – der Agent arbeitet strukturell in ``/tmp`` (Skripte, Ergebnis-
dateien, ``plt.savefig``), und der System-Prompt sagt ihm das an sieben
Stellen. Ein blosses ``--tmpfs /tmp`` wuerde jedes Ergebnis beim Prozessende
vernichten und den Download-Chip ausfallen lassen.

Deshalb: ``bwrap --bind <arbeitsverzeichnis> /tmp``. Innerhalb des Laufs IST
``/tmp`` das Arbeitsverzeichnis DIESES BENUTZERS.

* Der MODELL-Pfad bleibt ``/tmp/ergebnis.xlsx`` – kein Prompt muss sich aendern.
* Auf dem HOST liegt die Datei in ``/tmp/jarvis-arbeit/<kennung>/`` und ist
  damit fuer das Backend erreichbar (``_deliver_docs``).
* Fremde ``/tmp``-Inhalte sind im Lauf NICHT VORHANDEN – nicht "nicht lesbar",
  sondern nicht existent. Das ist der Unterschied zu jeder Rechte-Loesung.

**WARUM JE BENUTZER UND NICHT JE LAUF** (Vorgabe des Nutzers, 2026-08-23, nach
einer ersten Fassung mit einem Verzeichnis je Lauf): die Trennung, die FEHLTE,
war Benutzer gegen Benutzer. Zwei Laeufe DERSELBEN Person voreinander zu
verbergen loest kein Sicherheitsproblem, kostet aber etwas, das vorher ging –
ein Zwischenprodukt, das der Agent nicht als Ergebnis nennt, waere nach dem Lauf
weg, und "und jetzt filtere Spalte C" liefe in ``No such file or directory``.
Genau diese Fehlerklasse hat am 2026-08-12 einen Vorfall ausgeloest (Anhang in
der Folgefrage). Je Benutzer bleibt die Weiterarbeit erhalten UND die Grenze
gewahrt.

Der Preis ist ehrlich zu benennen: das Aufraeumen ist damit nicht mehr
deterministisch ("Lauf zu Ende, Verzeichnis weg"), sondern haengt an einer Frist
(``attachments.cleanup_arbeit`` bzw. dieselbe Broker-Op). Und ein Lauf kann
Dateien eines FRUEHEREN Laufs derselben Person sehen – so wie vor diesem Umbau
auch.

ANHAENGE GEHEN DEN ANDEREN WEG: HOST-PFAD = MODELL-PFAD
-------------------------------------------------------
Eine Arbeitskopie muss zwei Welten bedienen: die Shell IM Namespace und die
BACKEND-Werkzeuge (``xlsx_inspect``, ``pdf_formular_extrakt``, ``create_chart``,
``filesystem``), die im Dienstprozess laufen und den Pfad so oeffnen, wie das
Modell ihn nennt. Ein uebersetzter Pfad waere dort tot.

Deshalb liegen Anhaenge in ``/tmp/jarvis-anhaenge/<kennung>/`` und werden mit
``--ro-bind`` auf DENSELBEN Pfad in den Lauf gehaengt: eine Bindung je Lauf,
unabhaengig von der Anzahl der Dateien, und beide Welten sehen denselben Pfad.
Zwei Nebenwirkungen, beide gewollt:

* ``authorize_fs`` kann die Zugehoerigkeit am VERZEICHNIS pruefen und damit den
  Backend-Weg schliessen (vorher konnte ein Domain-Benutzer die Arbeitskopie
  eines anderen ueber ``office_read``/``xlsx_read_range`` oeffnen, sobald er den
  Namen kannte – und ``filesystem list /tmp`` nannte ihm die Namen).
* ``--ro-bind`` macht die Eingabedatei im Lauf unveraenderlich; der Agent kann
  den Upload des Benutzers nicht mehr beschaedigen.

FAIL-OPEN, ABER NICHT STILL
---------------------------
Fehlt ``bwrap``, laeuft alles wie vor dieser Aenderung weiter (gemeinsames
``/tmp``, kein Lauf-Verzeichnis) – mit einer Zeile im Journal. Fail-CLOSED waere
hier falsch: es wuerde auf einem Server ohne ``bubblewrap`` JEDEN Shell-Befehl
jedes Netzwerk-Benutzers abschalten, also die Anwendung fuer eine Verbesserung
opfern. Damit der Ausfall nicht unsichtbar bleibt (ein Schutz, der still
ausfaellt, ist kein Schutz), meldet ``bericht()`` den Zustand, und
``start_jarvis_root.sh`` installiert das Paket bei Bedarf nach.

ABSCHALTBAR mit ``JARVIS_LAUF_ISOLATION=0``.

WAS DAS NICHT LOEST
-------------------
Privilegierte Laeufe (lokaler ``jarvis``, Systemlaeufe) bekommen KEIN eigenes
Arbeitsverzeichnis: sie laufen als Dienstbenutzer, haben ohnehin Root-Wege und
brauchen das echte ``/tmp`` (Screenshot-Werkzeug, Chrome-Profil, Desktop).
Isolation zwischen Administratoren ist kein Ziel dieses Moduls. Ebenso nicht:
zwei gleichzeitige Laeufe derselben Person teilen ihr Arbeitsverzeichnis und
koennen sich gegenseitig eine Datei ueberschreiben – das war vorher genauso.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Alles liegt unter /tmp: es ist auf beiden Servern ein tmpfs (schnell, wird
# beim Reboot geleert) und der einzige Ort, den der Sandbox-Benutzer sicher
# beschreiben darf. Eigene Wurzeln, damit `filesystem list /tmp` im Lauf nicht
# ploetzlich Verwaltungsverzeichnisse zeigt.
TMP_ECHT = Path("/tmp")
ARBEIT_ROOT = TMP_ECHT / "jarvis-arbeit"
ANH_ROOT = TMP_ECHT / "jarvis-anhaenge"

# Ziel des matplotlib-Caches IM Lauf. Er liegt jetzt einfach IM Arbeits-
# verzeichnis – das ist je Benutzer und ueberlebt den Lauf, also braucht es
# weder eine eigene Wurzel noch eine Bindung. Wichtig ist nur, dass der Cache
# nicht je LAUF entsteht: der Schriftarten-Index kostet beim ersten Aufbau
# Sekunden, pro Shell-Befehl waere das ein Rueckschritt.
MPL_ZIEL = "/tmp/.mplcache"

BWRAP = "/usr/bin/bwrap"
SETPRIV = "/usr/bin/setpriv"

# Benutzer-Kennung: 8 Hex. Wird zum Verzeichnisnamen und ueber den Broker
# uebergeben – deshalb ein hartes Muster und keine Freitext-Uebernahme.
_KENNUNG_RE = re.compile(r"^[0-9a-f]{8}$")
# Zielpfad einer ro-Bindung: genau eine Datei/ein Verzeichnis unter /tmp.
_BIND_RE = re.compile(r"^/tmp/[A-Za-z0-9._\-/]{1,160}$")


def _log(msg: str) -> None:
    print(f"[LAUF-TMP] {msg}", flush=True)


# ── Zustand des Laufs ────────────────────────────────────────────────────────

class Lauf:
    """Der laufende Auftrag: Auftraggeber, Kennung, Arbeitsverzeichnis.

    Es gibt bewusst KEINE Lauf-Kennung mehr. Das Verzeichnis gehoert dem
    BENUTZER und wird von allen seinen Laeufen geteilt; eine Kennung je Lauf
    haette nur den Anschein einer Trennung erzeugt, die es nicht mehr gibt.
    """

    __slots__ = ("verzeichnis", "benutzer", "kennung")

    def __init__(self, verzeichnis: Path, benutzer: str, kennung: str):
        self.verzeichnis = verzeichnis
        self.benutzer = benutzer
        self.kennung = kennung


# ContextVar und NICHT ein Objekt-Attribut – genau wie bei der Actor-Bindung:
# der Hauptagent ist GETEILT, ein Cron-Lauf und ein Chat-Auftrag koennen
# gleichzeitig auf demselben Objekt liegen. Ein Attribut wuerde das
# Lauf-Verzeichnis des jeweils anderen Laufs mitregieren – und damit dessen
# Dateien sichtbar machen.
_lauf_cv: contextvars.ContextVar = contextvars.ContextVar("jarvis_lauf_tmp", default=None)


# Zusaetzliche BESCHREIBBARE Bindungen, die ein AUFRUFER fuer einen Lauf
# anmeldet – nicht das Modell. Gebraucht fuer Ablaeufe, deren Arbeitsverzeichnis
# den Lauf ueberlebt und die deshalb nicht im Lauf-Verzeichnis liegen koennen:
# der Claude-Subagent klont ein Repo nach /tmp/claude_subagent/<job>, sammelt
# danach den Diff ein und braucht das Verzeichnis ueber mehrere Laeufe.
#
# Ohne diese Klammer waere der Pfad im Namespace NICHT VORHANDEN und der Skill
# still kaputt – ein Beispiel dafuer, dass eine Isolation immer die Uebergaben
# mitdenken muss, nicht nur die Grenze.
_zusatz_cv: contextvars.ContextVar = contextvars.ContextVar("jarvis_lauf_zusatz", default=())


@contextlib.contextmanager
def zusatz_bind(*pfade):
    """Meldet Verzeichnisse an, die im Lauf BESCHREIBBAR sichtbar sein muessen.

    Um den Aufruf von ``run_task_headless`` legen, nicht um einzelne Werkzeuge:
    die Bindung gilt fuer den ganzen Lauf. Nur absolute Pfade unter ``/tmp``
    (der Broker prueft das noch einmal) – alles andere waere ein Weg, beliebige
    Verzeichnisse in einen unprivilegierten Lauf zu holen.
    """
    gut = tuple(str(p) for p in pfade if str(p or "").startswith("/tmp/"))
    token = _zusatz_cv.set(tuple(_zusatz_cv.get() or ()) + gut)
    try:
        yield
    finally:
        try:
            _zusatz_cv.reset(token)
        except Exception:  # noqa: BLE001
            pass


def zusatz_binds() -> tuple:
    """Die angemeldeten RW-Verzeichnisse dieses Laufs."""
    return tuple(_zusatz_cv.get() or ())


def aktueller_lauf():
    """Der Lauf dieses asyncio.Task – oder None (privilegiert / Isolation aus)."""
    return _lauf_cv.get()


def verzeichnis() -> Path | None:
    """Host-Verzeichnis des laufenden Auftrags – oder None."""
    lauf = _lauf_cv.get()
    return lauf.verzeichnis if lauf else None


def benutzer_kennung(benutzer: str) -> str:
    """Stabile, kurze Kennung eines Benutzers fuer Verzeichnisnamen.

    Aus dem NORMALISIERTEN Namen abgeleitet (klein, ohne Domaenen-Praefix und
    UPN-Suffix) – sonst haette dieselbe Person je Anmeldeform ein eigenes
    Anhang-Verzeichnis und wuerde ihre eigenen Dateien nicht mehr finden.
    Das ist dieselbe Lehre wie bei der Sperrliste und dem Cron-Filter.
    """
    norm = _norm_user(benutzer)
    if not norm:
        return ""
    return hashlib.sha256(norm.encode("utf-8", "replace")).hexdigest()[:8]


def _norm_user(benutzer: str) -> str:
    """Klein, ohne ``domaene\\`` und ohne ``@upn`` – wie in conv_log.norm_user."""
    s = (benutzer or "").strip().lower()
    if not s:
        return ""
    if "\\" in s:
        s = s.rsplit("\\", 1)[-1]
    if "@" in s and not s.startswith(("wa:", "tg:", "api:")):
        s = s.split("@", 1)[0]
    return s


# ── Verfuegbarkeit der Isolation ─────────────────────────────────────────────

_verf_cache: dict = {}
_VERF_TTL = 300.0


def isolation_gewuenscht() -> bool:
    """Schalter. Vorgabe AN; ``JARVIS_LAUF_ISOLATION=0`` schaltet ab."""
    return (os.environ.get("JARVIS_LAUF_ISOLATION", "1").strip().lower()
            not in ("0", "false", "aus", "no"))


def bwrap_verfuegbar(als_benutzer: str = "") -> bool:
    """Prueft mit GENAU DEM AUFRUF, den ``sandbox_befehl()`` spaeter baut.

    Die Lehre stammt aus dem MCP-Client: eine erste Fassung pruefte dort nur mit
    ``--ro-bind /usr /usr`` und meldete auf einem gesunden System ``False``,
    weil schon ``/bin/true`` an der fehlenden libc scheiterte. Und weil der
    Befehl spaeter als SANDBOX-Benutzer laeuft (nicht als root), wird auch der
    ``runuser``-Umweg mitgeprueft – sonst misst man die Rechte des Pruefers.
    """
    if not isolation_gewuenscht():
        return False
    schluessel = als_benutzer or "-"
    treffer = _verf_cache.get(schluessel)
    # Ein ERFOLG wird dauerhaft gemerkt (der Aufruf steht auf jedem Lauf-Start,
    # ein Unterprozess je Lauf waere Verschwendung); ein Fehlschlag nur auf
    # Frist, damit ein nachinstalliertes Paket ohne Dienst-Neustart greift.
    if treffer and (treffer[1] or (time.time() - treffer[0]) < _VERF_TTL):
        return bool(treffer[1])
    ok = False
    try:
        if os.path.exists(BWRAP):
            _wurzel_sicherstellen(ARBEIT_ROOT, 0o755)
            probe = ARBEIT_ROOT / ("probe_" + uuid.uuid4().hex[:8])
            probe.mkdir(parents=True, exist_ok=True)
            try:
                # Alle Argumente NAMENTLICH: eine Signaturaenderung hat hier
                # schon einmal ein Positionsargument auf `_pruefen` geschoben –
                # die Pruefung schlug dann mit TypeError fehl, die Isolation war
                # STILL AUS (fail-open), und kein Unit-Test sah es, weil sie
                # genau diese Funktion durch einen festen Wert ersetzen.
                befehl = sandbox_befehl(als_benutzer, "test -d /tmp && echo JA",
                                        lauf_dir=probe, ro_binds=(), _pruefen=True)
                res = subprocess.run(["/bin/bash", "-c", befehl], capture_output=True,
                                     text=True, timeout=20)
                ok = "JA" in (res.stdout or "")
                if not ok:
                    _log("Isolationspruefung fehlgeschlagen: "
                         f"rc={res.returncode} {(res.stderr or '').strip()[:200]}")
            finally:
                shutil.rmtree(probe, ignore_errors=True)
        else:
            _log("bwrap ist nicht installiert – Laeufe teilen /tmp wie bisher "
                 "(Abhilfe: apt-get install -y bubblewrap)")
    except Exception as e:  # noqa: BLE001
        _log(f"Isolationspruefung nicht moeglich: {e}")
        ok = False
    _verf_cache[schluessel] = (time.time(), ok)
    return ok


def bericht() -> dict:
    """Zustand fuer Journal und Statusanzeige – der Ausfall soll sichtbar sein."""
    gewuenscht = isolation_gewuenscht()
    return {
        "gewuenscht": gewuenscht,
        "bwrap": os.path.exists(BWRAP),
        "aktiv": gewuenscht and os.path.exists(BWRAP),
        "arbeit_root": str(ARBEIT_ROOT),
        "anhang_root": str(ANH_ROOT),
    }


# ── Verzeichnisse anlegen (root-Seite: Broker bzw. Alt-Betrieb) ──────────────

def _dienst_ids() -> tuple[int, int]:
    """(uid, gid) des Dienstbenutzers – abgeleitet vom Projektverzeichnis.

    Der Broker laeuft als root und darf die Wurzeln NICHT root:root anlegen,
    sonst kann das unprivilegierte Backend darin kein Lauf-Verzeichnis erzeugen
    (und legt eines an, sobald ein Werkzeug vor dem ersten Shell-Befehl nach
    /tmp schreibt). Der Eigentuemer von ``/opt/jarvis`` ist die verlaessliche
    Quelle – dieselbe Annahme, auf der `start_jarvis_root.sh` Schritt 6b beruht.
    """
    try:
        st = PROJECT_ROOT.stat()
        return st.st_uid, st.st_gid
    except Exception:  # noqa: BLE001
        return os.getuid(), os.getgid()


def _wurzel_sicherstellen(pfad: Path, modus: int = 0o755) -> None:
    """Legt eine Wurzel an; als root mit dem Dienstbenutzer als Eigentuemer."""
    pfad.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(pfad, modus)
        if os.geteuid() == 0:
            uid, gid = _dienst_ids()
            os.chown(pfad, uid, gid)
    except Exception as e:  # noqa: BLE001
        _log(f"Wurzel {pfad} nicht einstellbar: {e}")


def arbeit_bereitstellen(kennung: str, sandbox_user: str) -> Path | None:
    """ROOT-Seite: Arbeitsverzeichnis anlegen und Eigentuemer richtig setzen.

    Aufgerufen aus der Broker-Operation ``sandbox_exec`` (und im Alt-Betrieb
    direkt). Modus 0770 mit Eigentuemer ``jarvis_sandbox`` und Gruppe des
    DIENSTES – beide Seiten brauchen Schreibrecht:

    * der Lauf schreibt seine Ergebnisse hinein,
    * das Backend muss sie ausliefern (``_deliver_docs`` kopiert und raeumt auf)
      und ggf. vorher selbst etwas ablegen (``filesystem write /tmp/…``).

    Ein bereits vom Backend angelegtes Verzeichnis wird UEBERNOMMEN (chown), es
    ist also gleichgueltig, welche Seite zuerst kommt. Ohne diese Uebernahme
    haette die Reihenfolge entschieden, ob der Lauf schreiben darf – ein Fehler,
    der nur bei bestimmten Aufgaben auftritt und dann unerklaerlich aussieht.
    """
    if not kennung or not _KENNUNG_RE.match(kennung):
        return None
    if os.geteuid() != 0:
        return None
    import pwd
    try:
        pw = pwd.getpwnam(sandbox_user)
    except KeyError:
        _log(f"Sandbox-Benutzer fehlt: {sandbox_user}")
        return None
    if pw.pw_uid == 0:
        return None
    _wurzel_sicherstellen(ARBEIT_ROOT, 0o755)
    ziel = ARBEIT_ROOT / kennung
    try:
        ziel.mkdir(parents=True, exist_ok=True)
        _, gid = _dienst_ids()
        os.chown(ziel, pw.pw_uid, gid)
        os.chmod(ziel, 0o770)
        return ziel
    except Exception as e:  # noqa: BLE001
        _log(f"Arbeitsverzeichnis {ziel} nicht bereitstellbar: {e}")
        return None


# ── Lauf-Klammer ────────────────────────────────────────────────────────────

@contextlib.contextmanager
def lauf_scope(benutzer: str, privilegiert: bool):
    """Bindet einen Auftrag an das private ``/tmp`` seines Auftraggebers.

    Drei Entscheidungen stecken darin:

    * **Privilegierte Laeufe bekommen keines** (Rueckgabe None): sie laufen als
      Dienstbenutzer, brauchen das echte ``/tmp`` (Screenshots, Chrome-Profil)
      und haben ohnehin Root-Wege – Isolation zwischen Administratoren ist kein
      Ziel.
    * **Verschachtelte Klammern erben** statt neu zu binden. Ein Sub-Agent
      (``spawn_agent``, ``delegate``) ruft ``run_task`` erneut auf – mit einem
      anderen Verzeichnis saehe er die Dateien seines Eltern-Laufs nicht mehr,
      und "erzeuge die Datei, der Sub-Agent wertet sie aus" waere still kaputt.
      (Bei gleichem Benutzer waere es dasselbe Verzeichnis; die Klammer bleibt
      trotzdem verschachtelbar, weil ein Rollen-Lauf einen anderen Actor haben
      kann.)
    * **Beim Verlassen wird NICHTS geloescht.** Das Verzeichnis gehoert dem
      Benutzer, nicht dem Auftrag: eine Folgefrage soll das Zwischenprodukt noch
      finden. Abgeraeumt wird nach FRIST (``attachments.cleanup_arbeit`` bzw. die
      Broker-Op ``lauf_aufraeumen``) – wer das aendert, nimmt der Weiterarbeit
      genau die Datei weg, um die es geht.
    """
    lauf = _lauf_cv.get()
    if lauf is not None:                      # geerbt (Sub-Agent / Rolle)
        yield lauf
        return
    kennung = benutzer_kennung(benutzer)
    if privilegiert or not kennung or not bwrap_verfuegbar():
        yield None
        return
    neu = Lauf(ARBEIT_ROOT / kennung, benutzer, kennung)
    token = _lauf_cv.set(neu)
    try:
        yield neu
    finally:
        try:
            _lauf_cv.reset(token)
        except Exception:  # noqa: BLE001
            pass


def aufraeumen_root(kennung: str = "", alter_min: int = 0) -> list:
    """ROOT-Seite: Arbeitsverzeichnisse abraeumen – ein bestimmtes oder alte.

    Braucht root, weil der Agent im Lauf eigene Unterverzeichnisse anlegt
    (``mkdir /tmp/zwischen``, der matplotlib-Cache); die gehoeren dem
    Sandbox-Benutzer mit dessen eigener Gruppe, und das unprivilegierte Backend
    darf darin nichts loeschen – ``rmtree(ignore_errors=True)`` scheitert dann
    STILL. Auf DEV gemessen: genau daran blieben Verzeichnisse liegen.

    Ohne ``kennung`` werden alle Verzeichnisse entfernt, die seit ``alter_min``
    Minuten nicht mehr angefasst wurden. **Die Frist ist die einzige Schranke
    gegen einen laufenden Auftrag** – ein Verzeichnis, in dem gearbeitet wird,
    traegt eine frische mtime (jede angelegte oder geloeschte Datei aktualisiert
    sie), deshalb ist die Vorgabe bewusst gross.

    Die Kennung wird hart geprueft (8 Hex) und ausschliesslich unter
    ``ARBEIT_ROOT`` aufgeloest: ein Pfad aus einem Argument darf hier keine
    Loeschung an anderer Stelle ausloesen. ``lstat`` statt ``stat``, damit ein
    Symlink nicht verfolgt wird.
    """
    weg = []
    try:
        if not ARBEIT_ROOT.is_dir():
            return []
        import stat as _stat
        if kennung:
            if not _KENNUNG_RE.match(kennung):
                return []
            kandidaten = [ARBEIT_ROOT / kennung]
        else:
            grenze = time.time() - max(60, int(alter_min or 240)) * 60
            kandidaten = []
            for d in ARBEIT_ROOT.iterdir():
                try:
                    if _KENNUNG_RE.match(d.name) and d.lstat().st_mtime < grenze:
                        kandidaten.append(d)
                except OSError:
                    continue
        for d in kandidaten:
            try:
                if not _stat.S_ISDIR(d.lstat().st_mode):
                    continue
                shutil.rmtree(d, ignore_errors=True)
                if not d.exists():
                    weg.append(d.name)
            except FileNotFoundError:
                continue
            except Exception as e:  # noqa: BLE001
                _log(f"{d} nicht entfernbar: {e}")
    except Exception as e:  # noqa: BLE001
        _log(f"Aufraeumen fehlgeschlagen: {e}")
    return weg


def eigenes_verzeichnis_anlegen() -> Path | None:
    """BACKEND-Seite: legt das Arbeitsverzeichnis an, falls noch keiner es tat.

    Noetig, weil ein Werkzeug im DIENSTPROZESS (``filesystem write /tmp/x``)
    vor dem ersten Shell-Befehl schreiben kann. Der Broker uebernimmt das
    Verzeichnis danach per ``chown`` – die Reihenfolge ist damit gleichgueltig.
    """
    lauf = _lauf_cv.get()
    if not lauf:
        return None
    try:
        _wurzel_sicherstellen(ARBEIT_ROOT, 0o755)
        lauf.verzeichnis.mkdir(parents=True, exist_ok=True)
        # Modus nur setzen, wenn wir es SELBST angelegt haben. Hat der Broker das
        # Verzeichnis schon uebernommen (Eigentuemer jarvis_sandbox), scheitert
        # chmod als Dienstbenutzer mit EPERM – und die erste Fassung hat daraus
        # eine Fehlermeldung bei JEDEM weiteren Shell-Befehl gemacht, obwohl
        # alles in Ordnung war. Eine Meldung, die im Normalbetrieb erscheint,
        # entwertet das Journal.
        if lauf.verzeichnis.stat().st_uid == os.getuid():
            os.chmod(lauf.verzeichnis, 0o770)
    except Exception as e:  # noqa: BLE001
        _log(f"Arbeitsverzeichnis nicht anlegbar: {e}")
        return None
    return lauf.verzeichnis


# ── Anhaenge ────────────────────────────────────────────────────────────────

def anhang_verzeichnis(benutzer: str, anlegen: bool = False) -> Path | None:
    """Verzeichnis der Arbeitskopien EINES Benutzers – oder None ohne Isolation.

    Ohne Isolation gibt es kein eigenes Verzeichnis: die Kopie liegt dann wie
    bisher direkt in ``/tmp``. Das ist wichtig fuer die Rueckfall-Ebene – der
    Modell-Pfad muss in BEIDEN Betriebsarten gueltig sein, sonst zeigt der
    Hinweis im Chat auf eine Datei, die es nicht gibt.
    """
    kennung = benutzer_kennung(benutzer)
    if not kennung or not bwrap_verfuegbar():
        return None
    ziel = ANH_ROOT / kennung
    if anlegen:
        try:
            _wurzel_sicherstellen(ANH_ROOT, 0o755)
            ziel.mkdir(parents=True, exist_ok=True)
            os.chmod(ziel, 0o755)
        except Exception as e:  # noqa: BLE001
            _log(f"Anhang-Verzeichnis nicht anlegbar: {e}")
            return None
    return ziel


def anhang_ziel(benutzer: str, sicherer_name: str) -> Path:
    """Wohin die Arbeitskopie gehoert. Host-Pfad = Modell-Pfad (siehe Modul-Doku).

    Der Dateiname folgt weiter GENAU ``anhang_<12 Hex>_<name>`` – daran haengt
    das Abraeumen in ``backend/attachments.py`` (vier Schranken, u.a. das exakte
    Namensmuster). Ein eigenes Praefix wuerde dort nicht getroffen und die
    Kopien blieben bis zum Reboot liegen.
    """
    name = "anhang_%s_%s" % (uuid.uuid4().hex[:12], sicherer_name)
    verz = anhang_verzeichnis(benutzer, anlegen=True)
    return (verz / name) if verz else (TMP_ECHT / name)


def anhang_binds(benutzer: str) -> list:
    """Was in den Lauf gehaengt wird: EIN Verzeichnis, nicht N Dateien.

    Eine Bindung je Datei haette zwei Nachteile: die Zahl der bwrap-Argumente
    waechst mit den Anhaengen, und jede ``--ro-bind``-Bindung legt im
    Lauf-Verzeichnis eine 0-Byte-Attrappe als Einhaengepunkt ab – die dann als
    "Ergebnis" ausgeliefert werden koennte. Die Verzeichnis-Bindung zeigt
    ausserdem Dateien, die WAEHREND des Laufs dazukommen.
    """
    verz = anhang_verzeichnis(benutzer)
    if verz and verz.is_dir():
        return [str(verz)]
    return []


def gehoert_anhang(pfad, benutzer: str) -> bool | None:
    """Gehoert eine Datei unter ANH_ROOT diesem Benutzer?

    ``None`` = die Frage stellt sich nicht (Pfad liegt nicht dort). ``False``
    schliesst den BACKEND-Weg: ohne diese Pruefung konnte ein Domain-Benutzer
    die Arbeitskopie eines anderen ueber ``office_read``/``xlsx_read_range``
    oeffnen, sobald er den Namen kannte – und vor dieser Aenderung nannte
    ``filesystem list /tmp`` ihm alle Namen.

    Fail-closed: ein leerer Benutzer bekommt hier ``False``, wenn der Pfad in
    einem FREMDEN Kennungs-Verzeichnis liegt. Anders als bei
    ``may_see_document`` heisst "kein Benutzer" hier nicht "keine Schranke" –
    privilegierte Laeufe kommen ohnehin nicht in diesen Zweig, weil sie kein
    Lauf-Verzeichnis haben und ihre Anhaenge in ``/tmp`` liegen.
    """
    try:
        rp = Path(pfad).resolve()
    except Exception:  # noqa: BLE001
        return None
    root = ANH_ROOT.resolve()
    if rp == root or root not in rp.parents:
        return None
    try:
        eigen = rp.relative_to(root).parts[0]
    except Exception:  # noqa: BLE001
        return None
    return eigen == benutzer_kennung(benutzer)


# ── Pfad-Aufloesung fuer Werkzeuge im Dienstprozess ─────────────────────────

def aufloesen(pfad: str) -> str:
    """Uebersetzt einen MODELL-Pfad in den HOST-Pfad dieses Laufs.

    ``/tmp/ergebnis.xlsx`` -> ``/tmp/jarvis-laeufe/<lauf>/ergebnis.xlsx``.

    Gebraucht wird das an genau einer Sorte Stelle: Werkzeuge, die im
    DIENSTPROZESS laufen und einen vom Modell genannten Pfad oeffnen
    (``filesystem``, ``create_chart(source.file)``, ``xlsx_*``,
    ``pdf_formular_extrakt``). Ohne die Uebersetzung liefe das Modell in einen
    Widerspruch: die Shell schreibt ``/tmp/x.xlsx``, das naechste Werkzeug
    findet dort nichts – und niemand kann sich erklaeren, warum.

    NICHT uebersetzt werden die Verwaltungswurzeln selbst: ``ANH_ROOT`` ist
    bereits ein Host-Pfad (Host = Modell), und ``ARBEIT_ROOT`` ist es ohnehin.
    """
    lauf = _lauf_cv.get()
    if not lauf or not pfad:
        return pfad
    s = str(pfad)
    if not s.startswith("/tmp"):
        return pfad
    try:
        rp = Path(s)
        # Verwaltungswurzeln unveraendert lassen (Host-Pfad = Modell-Pfad).
        # Die ZUSATZ-Bindungen gehoeren dazu: der Claude-Subagent nennt dem
        # Modell den Pfad seines Wegwerf-Klons, und der ist im Lauf unter genau
        # diesem Pfad eingehaengt. Wuerde er hier umgeschrieben, suchten die
        # Backend-Werkzeuge (filesystem, xlsx_*) im Lauf-Verzeichnis – und der
        # Skill waere auf der anderen Seite kaputt.
        for wurzel in (ANH_ROOT, ARBEIT_ROOT):
            if rp == wurzel or str(rp).startswith(str(wurzel) + "/"):
                return pfad
        for zusatz in zusatz_binds():
            if s == zusatz or s.startswith(zusatz.rstrip("/") + "/"):
                return pfad
        if rp == TMP_ECHT:
            return str(lauf.verzeichnis)
        rest = rp.relative_to(TMP_ECHT)
    except Exception:  # noqa: BLE001
        return pfad
    return str(lauf.verzeichnis / rest)


def temp_verzeichnis() -> Path:
    """Wohin der DIENSTPROZESS ein Skript legt, das der Lauf ausfuehren soll.

    Mit Lauf-Isolation ist das das Lauf-Verzeichnis: der Lauf sieht es dort als
    ``/tmp/<name>``, es braucht also KEINE eigene Bindung. Ohne Isolation das
    echte ``/tmp`` wie bisher.

    Die Alternative – Datei im echten /tmp und per ``--ro-bind`` einhaengen –
    war die erste Fassung und hatte zwei Nachteile: jede Bindung legt im
    Lauf-Verzeichnis einen Einhaengepunkt an, und die Datei blieb 0600 (siehe
    ``temp_datei_freigeben``).
    """
    lauf = _lauf_cv.get()
    if lauf:
        try:
            eigenes_verzeichnis_anlegen()
            if lauf.verzeichnis.is_dir():
                return lauf.verzeichnis
        except Exception:  # noqa: BLE001
            pass
    return TMP_ECHT


def temp_datei_freigeben(pfad: str) -> None:
    """Macht ein vom Dienst geschriebenes Skript fuer den Lauf LESBAR (0644).

    ALTFEHLER, unabhaengig von der Isolation: ``tempfile.NamedTemporaryFile``
    legt mit 0600 an. Ein Domain-Benutzer fuehrt seine Befehle aber als
    ``jarvis_sandbox`` aus – ``python3 /tmp/jarvis_x.py`` scheiterte damit
    reproduzierbar mit ``Errno 13``, und zwar seit es den Sandbox-Benutzer gibt.
    Der Parameter ``code`` von ``shell_execute`` war fuer Netzwerk-Benutzer also
    nie benutzbar; sichtbar wurde es erst bei der Abnahme dieses Umbaus.

    Kein Geheimnis: der Inhalt ist der Code, den das Modell gerade selbst
    geschrieben hat. Fremde Laeufe sehen die Datei nicht – sie liegt im
    Lauf-Verzeichnis.
    """
    try:
        os.chmod(pfad, 0o644)
    except OSError as e:
        _log(f"Temp-Skript nicht freigebbar ({pfad}): {e}")


def gehoert_arbeitsbereich(pfad, benutzer: str) -> bool | None:
    """Gehoert ein Pfad unter ARBEIT_ROOT DIESEM Benutzer?

    ``None`` = Frage stellt sich nicht. ``False`` schliesst dieselbe Luecke wie
    ``gehoert_anhang`` fuer die Ergebnisdateien: der Namespace verbirgt fremde
    Arbeitsverzeichnisse nur vor der SHELL. Ein Backend-Werkzeug
    (``xlsx_read_range``, ``office_read``, ``filesystem read``) laeuft im
    Dienstprozess und koennte ``/tmp/jarvis-arbeit/<fremd>/ergebnis.xlsx`` sonst
    einfach oeffnen – und vor diesem Umbau nannte ``filesystem list /tmp`` ihm
    alle Namen.

    Geprueft wird gegen den BENUTZER, nicht gegen den laufenden Auftrag: die
    Grenze ist Benutzer gegen Benutzer, und so gilt sie auch fuer einen Aufruf
    ausserhalb eines Agentenlaufs. Fail-closed: ohne bekannten Benutzer ist
    jedes Arbeitsverzeichnis fremd.
    """
    try:
        rp = Path(pfad).resolve()
        root = ARBEIT_ROOT.resolve()
    except Exception:  # noqa: BLE001
        return None
    if rp == root or root not in rp.parents:
        return None
    eigen = benutzer_kennung(benutzer)
    if not eigen:
        return False
    try:
        return rp.relative_to(root).parts[0] == eigen
    except Exception:  # noqa: BLE001
        return False


def einhaengepunkte(lauf_dir, ziele, sandbox_user: str) -> None:
    """ROOT-Seite: Einhaengepunkte im Lauf-Verzeichnis VORBEREITEN.

    Ohne diesen Schritt legt ``bwrap`` sie selbst an – als Sandbox-Benutzer und
    mit dessen EIGENER Gruppe (auf DEV gemessen: ``drwx------
    jarvis_sandbox:jarvis_sandbox``). Danach kommt das Backend nicht mehr hinein
    und das Aufraeumen des Lauf-Verzeichnisses scheitert STILL (rmtree mit
    ignore_errors) – die Verzeichnisse blieben liegen, also genau der Zustand,
    den dieser Umbau beseitigt.

    Deshalb erzeugt sie root: Eigentuemer Sandbox-Benutzer, Gruppe des Dienstes,
    0770 – beide Seiten kommen hinein. ``ziele`` sind die ZIELPFADE im Lauf
    (Anhang-Verzeichnis, angemeldete Arbeitsverzeichnisse), nicht die Quellen.
    """
    if not lauf_dir or os.geteuid() != 0:
        return
    import pwd
    try:
        uid = pwd.getpwnam(sandbox_user).pw_uid
    except KeyError:
        return
    _, gid = _dienst_ids()
    for ziel in list(ziele or []):
        try:
            rel = str(ziel)
            if not rel.startswith("/tmp/"):
                continue
            innen = Path(lauf_dir) / rel[len("/tmp/"):]
            # Nur Verzeichnisse: eine Datei-Bindung braucht eine Datei als
            # Einhaengepunkt, die legt bwrap selbst an (sie stoert nicht, weil
            # sie im Lauf-Verzeichnis liegt und mit ihm verschwindet).
            if Path(rel).is_file():
                continue
            teil = Path(lauf_dir)
            for stueck in innen.relative_to(lauf_dir).parts:
                teil = teil / stueck
                teil.mkdir(exist_ok=True)
                os.chown(teil, uid, gid)
                os.chmod(teil, 0o770)
        except Exception as e:  # noqa: BLE001
            _log(f"Einhaengepunkt {ziel} nicht vorbereitbar: {e}")


def such_wurzeln() -> list:
    """Verzeichnisse, in denen Ergebnisdateien dieses Laufs liegen koennen.

    Bewusst BEIDE: das Lauf-Verzeichnis und das echte ``/tmp``. Letzteres,
    weil derselbe Code auf Servern ohne ``bwrap`` laeuft und weil privilegierte
    Laeufe weiterhin direkt in ``/tmp`` arbeiten. Ein Chip, der fehlt, ist der
    schlimmere Fehler – dann hat der Benutzer gar nichts.
    """
    lauf = _lauf_cv.get()
    if lauf and lauf.verzeichnis.is_dir():
        return [lauf.verzeichnis, TMP_ECHT]
    return [TMP_ECHT]


# ── Der bwrap-Aufruf ────────────────────────────────────────────────────────

def binds_pruefen(rohe) -> list:
    """Validiert die ro-Bindungen (ROOT-Seite, vor dem Ausfuehren).

    Die Liste kommt aus dem Backend, also aus demselben Vertrauensbereich – die
    Pruefung sitzt trotzdem hier, weil der Broker die Sicherheitsgrenze ist und
    ein Pfad aus einem Werkzeug-Argument stammen KOENNTE. Verlangt wird: unter
    ``/tmp``, vorhanden, kein Symlink-Umweg nach draussen und nicht fuer Fremde
    beschreibbar (sonst koennte ein zweiter Lauf die Quelle austauschen).
    """
    ok = []
    for eintrag in (rohe or []):
        try:
            p = Path(str(eintrag))
            if not str(p).startswith("/tmp/") or not _BIND_RE.match(str(p)):
                continue
            rp = p.resolve()
            if not str(rp).startswith("/tmp/") or not rp.exists():
                continue
            st = os.stat(rp)
            if st.st_mode & 0o002:          # world-writable Quelle: nein
                continue
            ok.append(str(rp))
        except Exception:  # noqa: BLE001
            continue
    return ok[:64]


def rw_binds_pruefen(rohe) -> list:
    """Validiert BESCHREIBBARE Bindungen (ROOT-Seite).

    Strenger als bei den ro-Bindungen, weil der Lauf hier schreiben darf: nur
    vorhandene VERZEICHNISSE unter /tmp, kein Symlink, und niemals die
    Verwaltungswurzeln – eine Bindung von ANH_ROOT waere ein Schreibrecht auf
    die Arbeitskopien ALLER Benutzer, eine auf ARBEIT_ROOT der Blick in fremde
    Arbeitsverzeichnisse.
    """
    ok = []
    tabu = {str(ANH_ROOT), str(ARBEIT_ROOT), "/tmp"}
    for eintrag in (rohe or []):
        try:
            p = Path(str(eintrag))
            if not str(p).startswith("/tmp/") or not _BIND_RE.match(str(p)):
                continue
            if p.is_symlink():
                continue
            rp = p.resolve()
            if str(rp) in tabu or not str(rp).startswith("/tmp/") or not rp.is_dir():
                continue
            if any(str(rp) == t or str(rp).startswith(t + "/") for t in
                   (str(ANH_ROOT), str(ARBEIT_ROOT))):
                continue
            ok.append(str(rp))
        except Exception:  # noqa: BLE001
            continue
    return ok[:8]


def sandbox_befehl(sandbox_user: str, command: str, lauf_dir=None,
                   ro_binds=(), _pruefen: bool = False, rw_binds=()) -> str:
    """Baut den vollstaendigen Aufruf: ``runuser`` -> ``setpriv`` -> ``bwrap``.

    EINE Fassung fuer beide Wege (Broker-Betrieb und Alt-Betrieb mit
    root-Backend). Zwei Feinheiten, die beide Geld gekostet haben:

    * **``--dev-bind / /`` und nicht ``--bind / /``.** Eine gewoehnliche
      Bindung mountet mit ``nodev``; damit scheitert ``2>/dev/null`` mit
      "Keine Berechtigung" – also genau die Umleitung, die 2026-08-05 vier
      Konten gesperrt hat, weil sie falsch bewertet wurde. Auf DEV gemessen.
    * **``setpriv`` davor.** ``jarvis.service`` gibt dem Backend
      ``CAP_NET_BIND_SERVICE`` als Ambient-Capability, und die wird an JEDES
      Kind vererbt – ``bwrap`` bricht dann mit "Unexpected capabilities but not
      setuid" ab. Dieselbe Falle wie beim MCP-Client; sie faellt bei einer
      Handprobe per ``runuser`` nicht auf, nur im Dienst.

    Ohne Lauf-Verzeichnis oder ohne ``bwrap`` entsteht der bisherige Aufruf –
    fail-open, aber im Journal vermerkt.
    """
    innen = ("runuser -u %s -- " % shlex.quote(sandbox_user)) if sandbox_user else ""
    if not lauf_dir or (not _pruefen and not bwrap_verfuegbar(sandbox_user)):
        return innen + "/bin/bash -c %s" % shlex.quote(command)
    teile = []
    if os.path.exists(SETPRIV):
        teile += [SETPRIV, "--inh-caps=-all", "--ambient-caps=-all", "--"]
    teile += [
        BWRAP,
        # Dateisystem bleibt wie es ist – die harte Grenze sind weiter die
        # OS-Rechte des Sandbox-Benutzers. Eine Whitelist waere hier falsch:
        # sie wuerde legitime Zugriffe (Wissens-Share, /mnt, /opt/jarvis/skills)
        # abschneiden, und der Gewinn waere gering, weil der Benutzer ohnehin
        # nur das lesen kann, was fuer alle lesbar ist.
        "--dev-bind", "/", "/",
        # DAS ist die Isolation: /tmp ist ab hier NUR das Arbeitsverzeichnis
        # dieses Benutzers. Der matplotlib-Cache liegt einfach darin (MPL_ZIEL) –
        # kein eigener Mount noetig, und er ueberlebt den Lauf.
        "--bind", str(lauf_dir), "/tmp",
    ]
    for q in rw_binds:
        teile += ["--bind", str(q), str(q)]
    for q in ro_binds:
        teile += ["--ro-bind", str(q), str(q)]
    teile += [
        "--proc", "/proc",
        # Kein Blick auf fremde Prozesse und keine Signale an sie. Genau der
        # Punkt, den die Rechte-Loesungen NICHT abdecken konnten (gemessen:
        # 288 sichtbare Prozesse ohne, 4 mit).
        "--unshare-pid",
        "--die-with-parent",
        "--new-session",
        "--chdir", "/tmp",
        "--", "/bin/bash", "-c", command,
    ]
    return innen + " ".join(shlex.quote(t) for t in teile)
