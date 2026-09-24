"""Lebensdauer der erzeugten Bilder in ``data/generated_images``.

**Warum es diese Datei gibt.** Bis 2026-09-24 gab es fuer diesen Ordner **kein
Aufraeumen** – kein TTL, keinen Startup-Hook, kein Skript (im ganzen Repo
gegengeprueft). Erzeugte Bilder blieben unbegrenzt liegen, waehrend jede
Nachbar-Ablage eine Frist hat: ``data/documents`` ueber ``documents.cleanup_old``
(15..90 Tage), die Anhang-Arbeitskopien ueber ``attachments.cleanup`` (30 min),
die Protokolle ueber ``log_retention`` (90 Tage). Auf DEV gemessen: 39 Dateien,
40 MB, die aelteste ueber drei Monate alt.

**Vier Schreibwege fuellen den Ordner**, alle mit 32 Hex + Endung:
``tools/image_gen`` (``uuid4``), ``tools/image_search`` (``uuid4``),
``tools/bild_text`` (``uuid4``) und ``agent._bilddaten_bergen``
(``sha256(inhalt)[:32]`` – inhaltsadressiert, damit die Bergung idempotent ist).

⚠ **WARUM EINE FRIST HIER UEBERHAUPT GEFAHRLOS IST – das ist die Voraussetzung,
nicht ein Nebenaspekt.** Anders als bei ``data/documents`` steht die Adresse des
Bildes **im gespeicherten Chat-Verlauf** (``![…](/api/generated/<hash>.png)``).
Ein geloeschtes Bild macht eine alte Nachricht also zur toten Referenz. Das
faengt ``agent._ohne_tote_bildrefs`` ab (seit 2026-08-29/09-15): die Referenz
wird beim Rendern entfernt und der Benutzer bekommt einen Hinweis statt eines
kaputten Bildes. **Ohne diesen vorhandenen Fix waere eine Retention hier nicht
vertretbar** – wer ihn entfernt, macht aus dieser Frist einen stillen
Bildverlust in alten Chats.

**DIE FOLGE IST TROTZDEM REAL und bewusst in Kauf genommen (Vorgabe des
Betreibers, 30 Tage):** ein Bild in einem zwei Monate alten Chat ist weg, und
die Nachricht daneben sagt dann, dass es nicht mehr vorliegt. Wer das nicht
will, setzt ``JARVIS_GENIMG_TTL_DAYS=0``.

**Was die Frist NICHT ist: eine Zugriffsschranke.** Die Zugangskontrolle ist der
Dateiname (``/api/generated/<32 Hex>`` kommt ohne Anmeldung aus), und den
schuetzt seit 2026-09-24 der Verzeichnismodus 0750 (``sandbox.PRIVATE_DIRS``) –
vorher war der Ordner auflistbar, womit ein Domain-Benutzer per Shell alle
Capability-Namen und damit alle URLs bekam. Die Frist ist Datenminimierung
obendrauf: was nicht mehr liegt, kann auch ueber eine weitergegebene Adresse
nicht mehr abgerufen werden.
"""
from __future__ import annotations

import os
import re
import stat as _stat
import time
from pathlib import Path

# ⚠ ENDUNGEN: GENAU DAS, WAS `/api/generated/{name}` AUCH AUSLIEFERT.
# Eine Datei, die der Endpunkt nicht ausliefern kann, wurde mit hoher
# Wahrscheinlichkeit nicht von uns erzeugt – und was dieses Modul nicht selbst
# erzeugt hat, loescht es nicht (gleiche Zurueckhaltung wie
# `attachments._NAME_RE`, das bewusst kein breites `anhang_*` nimmt).
# Die Liste steht damit an ZWEI Orten (hier und im Endpunkt in main.py); der
# Waechter prueft sie als DRIFT-SCHRANKE gegeneinander. Ein Import aus `main`
# ist kein Weg – er zieht fastapi und den halben Backend-Stack nach.
ENDUNGEN = ("png", "jpg", "jpeg", "gif", "webp")

# Alle vier Schreibwege erzeugen `<32 Hex>.<endung>`; der Endpunkt laesst auch
# nur das durch. `fullmatch` gegen den reinen Namen – ein Pfadtrenner kann darin
# also nicht vorkommen.
#
# ⚠ BEWUSST CASE-SENSITIV, und das ist EIN GEMESSENER UNTERSCHIED zum Endpunkt:
# der kleinschreibt die Endung (`ext.lower()`) und liefert `<hash>.PNG` damit
# aus – dieses Muster trifft es nicht. Das ist kein Loch, sondern die vierte
# Schranke: KEIN Schreibweg erzeugt Grossendungen (`image_gen` und `agent` aus
# den magischen Bytes, `image_search` aus der MIME-Tabelle, `bild_text` festes
# `.png`). Eine Datei `<hash>.PNG` haben wir also nicht erzeugt – und was wir
# nicht erzeugt haben, loeschen wir nicht. Wer hier `re.IGNORECASE` nachtraegt,
# weicht genau diese Zusage auf; der Waechter haelt den Unterschied fest.
_NAME_RE = re.compile(r"[0-9a-f]{32}\.(?:" + "|".join(ENDUNGEN) + r")\Z")

DEFAULT_TTL_DAYS = 30
_MAX_TTL_DAYS = 3650  # 10 Jahre – wie log_retention; darueber ist "dauerhaft" (0) gemeint


def bildordner() -> Path:
    """Der Ordner der erzeugten Bilder – lazy geholt, EINE Quelle.

    Der Pfad ist in ``tools/image_gen._IMG_DIR`` definiert und wird von
    ``image_search``, ``bild_text`` und ``agent`` von dort importiert. Ihn hier
    nachzubauen waere eine zweite Fassung, die beim naechsten Umzug auseinander
    laeuft – dann raeumte dieses Modul ein Verzeichnis auf, in das niemand mehr
    schreibt (oder schlimmer: ein fremdes).

    **Lazy, und ein Test biegt DIESE Funktion um** (gleiches Muster wie
    ``bild_text._bildordner``): ``image_gen`` zieht ueber ``backend.config`` den
    halben Backend-Stack samt dotenv nach, und ``backend.config`` in einem Test
    zu importieren schreibt die Live-``settings.json`` zurueck (Register).
    """
    from backend.tools.image_gen import _IMG_DIR
    return _IMG_DIR


def ttl_days() -> int:
    """Vorhaltezeit in Tagen (``JARVIS_GENIMG_TTL_DAYS``); 0 = dauerhaft.

    Eine FUNKTION, keine Modulkonstante – gleiche Begruendung wie
    ``documents.retention_days()`` und ``attachments.ttl_minutes()``: ein beim
    Import gelesener Wert waere bis zum naechsten Dienststart eingefroren.

    Bewusst ueber die Umgebung und nicht ueber eine Oberflaechen-Einstellung:
    ``attachments`` ist hier das Vorbild (auch dort steuert die Frist eine ENV).
    Eine UI waere ein eigener Auftrag – i18n in beiden Sprachen, Endpunkt,
    Verdrahtung und Cache-Buster an allen Einbindungen.

    Ein unbrauchbarer Wert ergibt die VORGABE, nicht 0: ein Tippfehler in der
    Umgebung darf das Aufraeumen nicht stillschweigend abschalten.
    """
    roh = os.environ.get("JARVIS_GENIMG_TTL_DAYS")
    if roh is None or str(roh).strip() == "":
        return DEFAULT_TTL_DAYS
    try:
        v = int(str(roh).strip())
    except Exception:  # noqa: BLE001
        print(f"[Bilder] JARVIS_GENIMG_TTL_DAYS={roh!r} ist keine Zahl – "
              f"es gilt die Vorgabe {DEFAULT_TTL_DAYS} Tage", flush=True)
        return DEFAULT_TTL_DAYS
    if v <= 0:
        return 0
    return min(v, _MAX_TTL_DAYS)


def cleanup(days: int | None = None, now: float | None = None) -> tuple[int, int]:
    """Loescht erzeugte Bilder, die aelter als die Frist sind.

    Rueckgabe ``(Anzahl, Bytes)``.

    **Vier Schranken, damit nie etwas Fremdes getroffen wird** – wortgleich zu
    ``attachments.cleanup``, und jede hat ihren eigenen Grund:

    * **Name muss ``_NAME_RE`` entsprechen.** Kein breites ``*``: in dem Ordner
      koennte etwas liegen, das wir nicht erzeugt haben, und was der Endpunkt
      nicht ausliefern kann, ist auch nicht unser Bild.
    * **Nur direkte Kinder** – kein Abstieg in Unterverzeichnisse.
    * **``lstat`` statt ``stat``, und nur regulaere Dateien.** Ein Symlink auf
      ``/etc/passwd`` wuerde ueber ``stat`` als "alte Datei" gemeldet und
      entfernt; ``lstat`` sieht den Symlink selbst.
    * **Eigentuemer muss der eigene Benutzer sein.** Der Ordner gehoert dem
      Dienst; eine fremde Datei darin ist ein Rueckstand, den wir nicht
      anfassen (und in der Regel ohnehin nicht loeschen koennten).

    Fehler je Datei werden protokolliert und ueberSPRUNGEN, nicht geworfen: ein
    Lauf, der beim ersten Problem abbricht, laesst genau den Bestand stehen, um
    den es geht (gleiche Haltung wie ``log_retention.run_all``).
    """
    tage = ttl_days() if days is None else int(days)
    if tage <= 0:
        return 0, 0
    try:
        ordner = bildordner()
    except Exception as e:  # noqa: BLE001
        print(f"[Bilder] Ordner nicht bestimmbar: {e}", flush=True)
        return 0, 0
    if not ordner.is_dir():
        return 0, 0

    grenze = (time.time() if now is None else now) - tage * 86400
    uid = os.getuid()
    weg, frei = 0, 0
    try:
        eintraege = list(ordner.iterdir())
    except Exception as e:  # noqa: BLE001
        print(f"[Bilder] {ordner} nicht lesbar: {e}", flush=True)
        return 0, 0

    for p in eintraege:
        if not _NAME_RE.fullmatch(p.name):
            continue
        try:
            st = p.lstat()
            if not _stat.S_ISREG(st.st_mode):      # Symlink/Verzeichnis/FIFO
                continue
            if st.st_uid != uid:
                continue
            if st.st_mtime >= grenze:
                continue
            groesse = st.st_size
            p.unlink()
            weg += 1
            frei += groesse
        except FileNotFoundError:
            continue                               # parallel schon weg
        except Exception as e:  # noqa: BLE001
            print(f"[Bilder] {p.name} nicht entfernbar: {e}", flush=True)
    if weg:
        print(f"[Bilder] Vorhaltezeit {tage} Tage: {weg} Bild(er) entfernt, "
              f"{frei / 1024 / 1024:.1f} MB frei", flush=True)
    return weg, frei


def stats() -> dict:
    """Kennzahlen fuer Diagnose (keine Dateinamen – die SIND die Zugangsdaten).

    ⚠ Bewusst ohne Namensliste: ein Dateiname ist hier die vollstaendige
    Capability-URL. Eine Diagnose-Ausgabe, die sie nennt, waere genau die
    Enumeration, die der Verzeichnismodus 0750 seit 2026-09-24 schliesst.
    """
    anzahl, bytes_ = 0, 0
    aeltestes = None
    try:
        ordner = bildordner()
        if ordner.is_dir():
            for p in ordner.iterdir():
                if not _NAME_RE.fullmatch(p.name):
                    continue
                try:
                    st = p.lstat()
                    if not _stat.S_ISREG(st.st_mode):
                        continue
                    anzahl += 1
                    bytes_ += st.st_size
                    if aeltestes is None or st.st_mtime < aeltestes:
                        aeltestes = st.st_mtime
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        pass
    return {"bilder": anzahl, "bytes": bytes_, "aeltestes": aeltestes,
            "ttl_days": ttl_days()}
