"""Einmaliger Umzug der Wissensordner nach ``data/rag`` bzw. ``/mnt/rag``.

Laeuft bei jedem Backend-Start, ist idempotent und auf einem umgezogenen System
**still** – eine Zeile, die bei jedem Start dasselbe sagt, wird nach zwei Tagen
nicht mehr gelesen.

Was der Umzug anfasst, und in dieser Reihenfolge:

1. ``data/<name>``  → ``data/rag/<name>`` (Verzeichnis verschieben, Index und
   Gruppen-Zuordnungen ueber ``relocate_folder_index`` mitziehen).
2. ``data/knowledge`` – **Sonderfall, und er legt NICHTS an.** Der Ordner ist
   seit dem Umzug reine Infrastruktur (``pending/``, ``.groups.json``,
   WebDAV-Wurzel); sein Eintrag verschwindet aus der Ordnerliste, der Ordner
   selbst bleibt unangetastet.
   ⚠ EIN ``data/rag/knowledge`` ENTSTEHT NICHT – ausdrueckliche Vorgabe des
   Betreibers: die Wurzel ist ``data/rag``, ein Unterordner ``knowledge`` war
   nicht gewollt. Liegt in ``data/knowledge`` trotzdem Wissen, wird es
   **benannt und bleibt liegen**; wohin es gehoert, entscheidet der
   Administrator (Ordner anlegen, Dateien hineinlegen). Es still in einen
   erfundenen Ordner zu schieben waere eine Entscheidung ohne Entscheider.
3. ``/mnt/jarvis-kb/share_N`` → ``/mnt/rag/share_N`` in der Ordnerliste UND in
   den Mount-Eintraegen.
4. Spiegel-Ziele der Standort-Synchronisation (``target_folder``).

⚠ EIN LAUFENDER MOUNT WIRD NICHT UMGEHAENGT. Das braeuchte Root ueber den
Broker, mitten im Dienststart, fuer ein fremdes Dateisystem – ein Eingriff, der
schiefgehen kann, waehrend der Fehlerfall billig ist: die Freigabe erscheint als
"nicht verbunden", ein Klick auf *Verbinden* haengt sie am neuen Ort ein. Der
alte Einhaengepunkt wird dabei im Journal **benannt**, samt Befehl zum
Abraeumen – ein Rueckstand, von dem niemand weiss, ist schlimmer als einer, der
in der Zeile darueber steht.

Fail-safe in die bewahrende Richtung: jeder Schritt ist einzeln abgesichert.
Scheitert einer, bleibt der alte Zustand stehen und der Grund steht im Journal –
ein halb umgezogener Bestand waere schlimmer als ein nicht umgezogener.
"""
from __future__ import annotations

import os
from pathlib import Path

from backend import rag_pfad as rp

PROJECT_ROOT = rp.PROJECT_ROOT


def _log(msg: str) -> None:
    print(f"[RAG-Umzug] {msg}", flush=True)


def _skill_cfg() -> tuple[dict, dict]:
    """(state, config) des Knowledge-Skills. Bewusst ueber ``config`` und nicht
    ueber den SkillManager: der haengt an main.py, ein Gegenimport waere zirkulaer."""
    from backend.config import config
    states = config.get_skill_states()
    state = states.get("knowledge", {})
    return state, dict(state.get("config", {}))


def _speichern(state: dict, cfg: dict) -> None:
    from backend.config import config
    state["config"] = cfg
    state.setdefault("enabled", True)
    config.save_skill_state("knowledge", state)


def _wissensdateien(ordner: Path) -> list[Path]:
    """Alles in ``data/knowledge``, was WISSEN ist – ohne die Infrastruktur.

    Ausgenommen: ``pending/`` (Entwurfs-Speicher), alles Versteckte
    (``.groups.json``) und die Archive der Verdichtung (``*.tgz``), die
    ausdruecklich ausserhalb des Index liegen sollen.
    """
    out = []
    try:
        for e in sorted(ordner.iterdir(), key=lambda x: x.name.lower()):
            if e.name.startswith(".") or e.name == "pending":
                continue
            if e.is_file() and e.suffix.lower() in (".tgz", ".tar", ".gz"):
                continue
            out.append(e)
    except OSError:
        return []
    return out


def _verschiebe_ordner(alt: Path, neu: Path) -> dict | None:
    """Ein Verzeichnis umhaengen und das indizierte Wissen mitziehen.

    ``rename`` und nicht ``copy``: es laesst die mtime unveraendert, und genau
    die vergleicht der inkrementelle Reindex – kopiert waere jede Datei
    "geaendert" und muesste neu eingebettet werden.
    """
    from backend.tools.knowledge import relocate_folder_index
    neu.parent.mkdir(parents=True, exist_ok=True)
    if alt.exists():
        # ⚠ DIESE PRUEFUNG IST NICHT REDUNDANT, auch wenn sie so aussieht:
        # `rename` auf ein NICHT-LEERES Ziel scheitert zwar von selbst
        # (gemessen: OSError 39 "Directory not empty"), auf ein LEERES Ziel
        # gelingt es aber – und ersetzt es. Ein leerer Ordner in der
        # Konfiguration ist der Normalfall (frisch angelegt, noch nichts
        # hochgeladen), und ihn stillschweigend durch einen anderen zu ersetzen
        # waere ein Zustand, den niemand erklaeren kann.
        #
        # Der zweite Gewinn ist die MELDUNG: ohne diesen Zweig liest der
        # Administrator "[Errno 39] Directory not empty" statt der Ursache.
        if neu.exists():
            _log(f"⚠ Ziel '{neu}' existiert bereits – '{alt}' bleibt stehen")
            return None
        try:
            alt.rename(neu)
        except OSError as e:
            _log(f"⚠ '{alt}' → '{neu}' fehlgeschlagen: {e}")
            return None
    else:
        neu.mkdir(parents=True, exist_ok=True)
    try:
        return relocate_folder_index(alt, neu)
    except Exception as e:  # noqa: BLE001
        _log(f"⚠ Index-Umschreibung fuer '{neu}' fehlgeschlagen: {e}")
        return {}


def _restwissen_zaehlen() -> list[str]:
    """Namen der Dateien/Ordner in ``data/knowledge``, die WISSEN sein koennten.

    ⚠ ES WIRD NICHTS VERSCHOBEN. Der Umzug legt ausdruecklich KEIN
    ``data/rag/knowledge`` an (Vorgabe des Betreibers: die Wurzel ist
    ``data/rag``, ein Unterordner ``knowledge`` war nicht gewollt). Was hier
    gezaehlt wird, bleibt liegen und wird im Journal BENANNT – wohin es gehoert,
    entscheidet der Administrator.

    Ein Wissensverlust entsteht dadurch nicht: die Dateien bleiben auf der
    Platte. Sie sind nur nicht mehr indiziert, und genau das steht in der
    Meldung.
    """
    quelle = PROJECT_ROOT / rp.INFRA_REL
    if not quelle.exists():
        return []
    return [e.name for e in _wissensdateien(quelle)]


def _mount_hinweis(alt: Path) -> None:
    """Einen Rueckstand unter dem alten Einhaengepunkt BENENNEN, nicht loesen."""
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as fh:
            for zeile in fh:
                teile = zeile.split()
                if len(teile) > 1 and teile[1] == str(alt):
                    _log(f"⚠ Unter '{alt}' haengt noch ein Mount. Er wird NICHT "
                         f"automatisch geloest (das braeuchte Root mitten im "
                         f"Dienststart). Die Freigabe erscheint als 'nicht "
                         f"verbunden' – ein Klick auf 'Verbinden' haengt sie am "
                         f"neuen Ort ein. Rueckstand abraeumen: umount '{alt}'")
                    return
    except OSError:
        pass


def _mounts_umziehen(cfg: dict) -> int:
    """Einhaengepunkte in den Mount-Eintraegen auf ``/mnt/rag`` umschreiben."""
    mounts = cfg.get("mounts")
    if not isinstance(mounts, list):
        return 0
    alt_praefix = str(rp.ALT_MOUNT_BASIS) + "/"
    geaendert = 0
    for m in mounts:
        if not isinstance(m, dict):
            continue
        mp = str(m.get("mountpoint") or "")
        if not mp.startswith(alt_praefix):
            continue
        neu = str(rp.MOUNT_BASIS / mp[len(alt_praefix):])
        _mount_hinweis(Path(mp))
        m["mountpoint"] = neu
        geaendert += 1
    return geaendert


def _spiegel_umziehen(abbildung: dict) -> int:
    """Spiegel-Ziele der Standort-Synchronisation nachziehen.

    Ohne das zeigt der Standort-Eintrag auf einen Ordner, den es nicht mehr
    gibt: der naechste Lauf legte ihn erneut an und der umgezogene Bestand
    stuende verwaist daneben.
    """
    if not abbildung:
        return 0
    try:
        from backend import knowledge_sync as ks
    except Exception:  # noqa: BLE001
        return 0
    try:
        daten = ks._laden()
        geaendert = 0
        for p in daten.get("peers", []):
            alt = str(p.get("target_folder") or "").strip().strip("/")
            if alt in abbildung:
                p["target_folder"] = abbildung[alt]
                geaendert += 1
        if geaendert:
            # `_speichern()` nimmt kein Argument: es schreibt den
            # Modul-Zustand, und `_laden()` gibt genau den zurueck –
            # die Mutation oben wirkt also bereits darauf.
            ks._speichern()
        return geaendert
    except Exception as e:  # noqa: BLE001
        _log(f"⚠ Spiegel-Ziele nicht nachgezogen: {e}")
        return 0


def migriere() -> dict:
    """Den Umzug ausfuehren. Idempotent; auf einem umgezogenen System still."""
    # Zwei getrennte Zaehler: eine Freigabe steht in der ORDNERLISTE und als
    # MOUNT-EINTRAG. Beide zusammenzuzaehlen ergab live "6 Freigabe(n)" fuer drei
    # – eine Zahl, die niemand nachrechnen kann, ist schlechter als keine.
    ergebnis = {"ordner": 0, "mounts": 0, "mount_eintraege": 0,
                "infra_dateien": 0, "spiegel": 0, "still": True}
    try:
        rp.rag_wurzel().mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _log(f"⚠ '{rp.RAG_REL}' nicht anlegbar: {e}")
        return ergebnis

    try:
        state, cfg = _skill_cfg()
    except Exception as e:  # noqa: BLE001
        _log(f"⚠ Konfiguration nicht lesbar: {e}")
        return ergebnis

    roh = str(cfg.get("folders") or "")
    liste = [f.strip() for f in roh.split(",") if f.strip()]
    neu_liste: list[str] = []
    abbildung: dict[str, str] = {}

    for eintrag in liste:
        rel = eintrag.replace("\\", "/").strip().rstrip("/")

        # (a) Bereits am Ziel – nichts zu tun.
        if rp.ist_rag_ordner(rel) or rel.startswith(str(rp.MOUNT_BASIS) + "/"):
            neu_liste.append(rel)
            continue

        # (b) Einhaengepunkt am alten Ort.
        if rel.startswith(str(rp.ALT_MOUNT_BASIS) + "/"):
            neu = str(rp.MOUNT_BASIS / rel[len(str(rp.ALT_MOUNT_BASIS)) + 1:])
            # ⚠ DAS VERZEICHNIS ANZULEGEN IST NICHT UNSERE AUFGABE – und der
            # Versuch darf den Umzug NICHT halbieren. `/mnt` gehoert root, das
            # Backend laeuft unprivilegiert: live auf DEV scheiterte das mkdir
            # mit EACCES, der Eintrag blieb in der Ordnerliste stehen, WAEHREND
            # der Mount-Eintrag daneben schon umgeschrieben war – zwei Seiten,
            # die auf verschiedene Pfade zeigen. Genau der halb migrierte
            # Zustand, der schlimmer ist als gar keiner.
            #
            # Den Einhaengepunkt legt der Broker beim Verbinden selbst an
            # (`_op_mount_share`, als root); der Bootstrap legt die Wurzel
            # ohnehin an (start_jarvis_root.sh). Hier wird deshalb nur
            # VERSUCHT – schlaegt es fehl, zieht der Pfad trotzdem um.
            try:
                Path(neu).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            abbildung[rel] = neu
            neu_liste.append(neu)
            ergebnis["mounts"] += 1
            ergebnis["still"] = False
            _log(f"Freigabe: {rel} → {neu}")
            continue

        # (c) Der Infrastruktur-Ordner: der Eintrag faellt weg, der Ordner bleibt.
        # ⚠ HIER ENTSTEHT KEIN data/rag/knowledge (Vorgabe des Betreibers).
        if rp.norm(rel) == rp.INFRA_REL:
            rest = _restwissen_zaehlen()
            ergebnis["infra_dateien"] = len(rest)
            ergebnis["still"] = False
            if rest:
                _log(f"⚠ {rp.INFRA_REL} ist kein Wissensordner mehr und aus der "
                     f"Liste genommen – dort liegen aber noch "
                     f"{len(rest)} Eintrag/Eintraege ({', '.join(rest[:5])}"
                     f"{' …' if len(rest) > 5 else ''}). Sie bleiben auf der "
                     f"Platte, sind aber NICHT mehr indiziert. Bitte unter "
                     f"Einstellungen → Wissen einen Ordner anlegen und sie "
                     f"dorthin verschieben.")
            else:
                _log(f"{rp.INFRA_REL} ist kein Wissensordner mehr – aus der Liste "
                     f"genommen (dort lag kein Wissen; pending/ und .groups.json "
                     f"bleiben unangetastet)")
            continue

        # (d) ⚠ SYSTEMORDNER WERDEN NIE VERSCHOBEN. Stuende `data/logs` oder
        # `data/chats` in der Wissens-Ordnerliste (Altbestand, Handarbeit in der
        # settings.json), machte der Umzug aus einem Konfigurationsfehler einen
        # Datenverlust. Der Eintrag bleibt stehen und wird BENANNT – still
        # auszulassen hiesse, dass niemand von dem Fehler erfaehrt.
        if rp.ist_systemordner(rel):
            _log(f"⚠ '{rel}' ist ein Systemordner und bleibt, wo er ist. Er "
                 f"gehoert nicht in die Wissens-Ordnerliste – bitte dort entfernen.")
            neu_liste.append(rel)
            continue

        # (e) ⚠ NUR RELATIVE data/-ORDNER WERDEN VERSCHOBEN. Ein ABSOLUTER
        # Fremdpfad (`/srv/wissen`, ein Netzlaufwerk ausserhalb der Mount-Wurzel)
        # konnte bis 2026-09-13 ueber den alten "Hinzufuegen"-Knopf in die Liste
        # kommen. `zu_rag()` machte daraus `data/rag/srv/wissen` – der Umzug
        # haette also fremde Verzeichnisse in den Wissensbaum GESCHOBEN. Vom
        # eigenen Waechter gefunden, nicht beim Lesen.
        #
        # Solche Eintraege bleiben stehen und werden BENANNT: sie sind eine
        # bewusste Altkonfiguration, und was der Umzug nicht anfassen darf, soll
        # der Administrator sehen.
        if rel.startswith("/") or not rp.norm(rel).startswith("data/"):
            _log(f"⚠ '{rel}' liegt ausserhalb von data/ und bleibt unangetastet. "
                 f"Wissens-Ordner gehoeren unter {rp.RAG_REL}/ – bitte Inhalt von "
                 f"Hand dorthin bringen und den Eintrag ersetzen.")
            neu_liste.append(rel)
            continue

        ziel_rel = rp.zu_rag(rel)
        if not ziel_rel:
            _log(f"⚠ '{rel}' ist kein brauchbarer Ordnername und bleibt stehen.")
            neu_liste.append(rel)
            continue
        alt_abs = PROJECT_ROOT / rp.norm(rel)
        neu_abs = PROJECT_ROOT / ziel_rel
        moved = _verschiebe_ordner(alt_abs, neu_abs)
        if moved is None:
            neu_liste.append(rel)
            continue
        abbildung[rel] = ziel_rel
        neu_liste.append(ziel_rel)
        ergebnis["ordner"] += 1
        ergebnis["still"] = False
        chunks = (moved or {}).get("vector_chunks", 0)
        _log(f"Ordner: {rel} → {ziel_rel} ({chunks} Chunk(s) umgeschrieben)")

    if abbildung or neu_liste != liste:
        cfg["folders"] = ",".join(neu_liste)
        ergebnis["mount_eintraege"] = _mounts_umziehen(cfg)
        try:
            _speichern(state, cfg)
        except Exception as e:  # noqa: BLE001
            _log(f"⚠ Ordnerliste nicht gespeichert: {e}")
            return ergebnis
        ergebnis["spiegel"] = _spiegel_umziehen(abbildung)

    if not ergebnis["still"]:
        _log(f"✓ fertig: {ergebnis['ordner']} Ordner, {ergebnis['mounts']} Freigabe(n) "
             f"(davon {ergebnis['mount_eintraege']} Eintrag/Eintraege nachgezogen), "
             f"{ergebnis['infra_dateien']} unverschobene(r) Eintrag/Eintraege in "
             f"{rp.INFRA_REL}, "
             f"{ergebnis['spiegel']} Spiegel-Ziel(e)")
    return ergebnis
