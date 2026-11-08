"""Schema-Graph: Dateien eines Schemas – speichern, auflisten, loeschen.

Die EINE Stelle, die im Ablageordner eines Schemas
(``data/sql_schema_graph/<id>/``) schreibt oder loescht. Die Endpunkte in
``main.py`` pruefen Rechte und Rumpf und rufen nur hierher.

⚠ JEDER PFAD KOMMT AUS DEM BROWSER (relativer Pfad beim Ordner-Upload, Pfad
beim Loeschen). ``zielpfad`` ist deshalb streng: keine leeren Teile, kein
``.``/``..``, keine versteckten Teile, kein Backslash-Trick, und das Ziel muss
NACH dem Aufloesen im Schema-Ordner liegen. Eine Verknuepfung im Weg (ein
Symlink, den jemand auf dem Server angelegt hat) wird nicht verfolgt – sonst
waere "Ordner loeschen" ein ``rm -rf`` auf ein beliebiges Ziel.

Gespeichert wird als STROM in eine Nebendatei und dann per ``os.replace``
getauscht: ein abgebrochener Upload hinterlaesst keine halbe Datei, die der
naechste Erfassungslauf als Schema liest, und eine mehrere GB grosse Datei
liegt nie im Arbeitsspeicher. Ein gleichnamiger Upload ERSETZT die Datei
(wie die Referenzen in Short Tracks) – ein neues Schema-Dump soll den alten
ersetzen, nicht als ``_1`` daneben liegen und doppelt erfasst werden.
"""
from __future__ import annotations

import os
import shutil
import stat
import uuid
from pathlib import Path

from backend import schema_graph_einstellungen as E

MAX_TIEFE = 16
MAX_TEIL = 200
DIR_MODUS = 0o750
DATEI_MODUS = 0o640
BAUM_MAX = 2000
ZIP_MAX_EINTRAEGE = 100_000


class DateiFehler(ValueError):
    pass


def _basis(sid: str) -> Path:
    try:
        return E.ordner_fuer(sid)
    except ValueError as e:
        raise DateiFehler(str(e)) from None


def teile(rel: str) -> list[str]:
    """Relativen Pfad pruefen und in Teile zerlegen (wirft DateiFehler)."""
    # NICHT strip(): ein Ordnername darf auf Leerzeichen enden (auf DEV
    # 2026-11-08 gemessen: ein Exportordner "Export " – abgeschnitten liess er sich
    # nicht mehr loeschen, "nicht vorhanden").
    s = str(rel or "").replace("\\", "/")
    if not s.strip() or s.startswith("/") or "\0" in s or "\n" in s or "\r" in s:
        raise DateiFehler(f"ungültiger Pfad: {rel!r}")
    t = s.split("/")
    if len(t) > MAX_TIEFE:
        raise DateiFehler(f"Pfad zu tief (höchstens {MAX_TIEFE} Ebenen): {rel!r}")
    for x in t:
        if not x.strip() or x.strip() in (".", "..") or x.startswith(".") or len(x) > MAX_TEIL:
            raise DateiFehler(f"ungültiger Pfadteil {x!r} in {rel!r}")
    return t


def zielpfad(sid: str, rel: str) -> Path:
    """``<schema>/<rel>`` – garantiert innerhalb des Schema-Ordners, ohne
    Verknuepfung auf dem Weg."""
    basis = _basis(sid)
    ziel = basis.joinpath(*teile(rel))
    # Kein Symlink auf dem Weg (inkl. Ziel selbst) – lstat, nicht stat.
    p = basis
    for x in ziel.relative_to(basis).parts:
        p = p / x
        try:
            if stat.S_ISLNK(os.lstat(p).st_mode):
                raise DateiFehler(f"Verknüpfung im Pfad nicht erlaubt: {rel!r}")
        except FileNotFoundError:
            break
        except NotADirectoryError:
            raise DateiFehler(f"Ein Teil des Pfads ist eine Datei, kein Ordner: {rel}") from None
    aufgeloest = ziel.resolve(strict=False)
    if not str(aufgeloest).startswith(str(basis.resolve(strict=False)) + os.sep):
        raise DateiFehler(f"Pfad liegt außerhalb des Schemas: {rel!r}")
    return ziel


def ordner_anlegen(sid: str) -> Path:
    """Ablage (und ``data/sql_schema_graph``) anlegen.

    ⚠ GEHOERT DIE BASIS EINEM ANDEREN BENUTZER (auf DEV 2026-11-07 gemessen: von
    Hand per ``sudo mkdir`` angelegt, root, 0755), scheitert jedes Anlegen
    darunter. Das wird BENANNT – mit Eigentuemer und Abhilfe –, statt als
    nackter PermissionError in einem 500 zu enden.
    """
    basis = _basis(sid)
    for p in (E.BASIS, basis):
        try:
            p.mkdir(mode=DIR_MODUS, parents=True, exist_ok=True)
        except PermissionError:
            raise DateiFehler(_rechte_grund(p.parent if not p.exists() else p)) from None
        try:
            os.chmod(p, DIR_MODUS)
        except PermissionError:
            pass
    if not os.access(basis, os.W_OK | os.X_OK):
        raise DateiFehler(_rechte_grund(basis))
    return basis


def _rechte_grund(p: Path) -> str:
    try:
        import pwd
        st = os.stat(p)
        wer = pwd.getpwuid(st.st_uid).pw_name
        modus = oct(stat.S_IMODE(st.st_mode))
    except (OSError, KeyError, ImportError):
        wer, modus = "?", "?"
    return (f"Der Dienst darf in {p} nicht schreiben (Eigentümer {wer}, Rechte {modus}). "
            f"Abhilfe auf dem Server: chown -R <Dienstbenutzer> {E.BASIS} und chmod 750 {E.BASIS}.")


def datei_speichern(sid: str, rel: str, quelle, endungen: set[str]) -> dict:
    """Eine Datei aus einem Datei-Objekt (``UploadFile.file``) als Strom ablegen.

    Rueckgabe ``{"pfad", "groesse", "ersetzt"}``; DateiFehler bei unzulaessigem
    Pfad oder Endung.
    """
    ziel = zielpfad(sid, rel)
    if ziel.suffix.lower() not in endungen:
        raise DateiFehler(f"Format „{ziel.suffix or '(ohne Endung)'}“ gehört nicht zu den Dateimustern "
                          f"({', '.join(sorted(endungen))}): {rel}")
    ordner_anlegen(sid)
    try:
        ziel.parent.mkdir(mode=DIR_MODUS, parents=True, exist_ok=True)
    except (FileExistsError, NotADirectoryError):
        raise DateiFehler(f"Ein Teil des Pfads ist eine Datei, kein Ordner: {rel}") from None
    # Zwischenordner ebenfalls ohne Verknuepfung (mkdir folgt keinen Links,
    # aber ein vorhandener Link waere in zielpfad schon abgewiesen).
    ersetzt = ziel.exists()
    if ersetzt and not ziel.is_file():
        raise DateiFehler(f"An dieser Stelle liegt ein Ordner: {rel}")
    tmp = ziel.with_name(f".{ziel.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.upload")
    try:
        with open(tmp, "wb") as f:
            shutil.copyfileobj(quelle, f, length=4 * 1024 * 1024)
        os.chmod(tmp, DATEI_MODUS)
        os.replace(tmp, ziel)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {"pfad": "/".join(ziel.relative_to(_basis(sid)).parts), "groesse": ziel.stat().st_size,
            "ersetzt": ersetzt}


def zip_entpacken(sid: str, rel_ordner: str, quelle, endungen: set[str], min_frei: int = 0,
                  max_eintraege: int = ZIP_MAX_EINTRAEGE) -> tuple[list, list]:
    """ZIP-Archiv (seekbares Datei-Objekt) in ``<schema>/<rel_ordner>`` entpacken.

    Rueckgabe ``(gespeichert, abgelehnt)`` – ``gespeichert`` wie bei
    ``datei_speichern``, ``abgelehnt`` als ``{"name", "grund"}``.

    Bewusst NICHT der Entpacker von /wissen (``main._kb_unpack_zip``): der liest
    jeden Eintrag ganz in den Speicher (ein Schema-Dump kann mehrere GB gross
    sein) und legt bei gleichem Namen ``_1`` daneben – hier ERSETZT ein
    gleichnamiger Eintrag die Datei, sonst erfasste der naechste Lauf jede
    Tabelle doppelt. Jeder Eintrag geht durch ``zielpfad`` (dieselbe strenge
    Pruefung wie ein Ordner-Upload: kein ``..``, kein absoluter Pfad, keine
    Verknuepfung, keine versteckten Teile) und wird als Strom geschrieben;
    gelesen wird hoechstens die im Archiv angegebene Groesse (``ZipExtFile``
    stoppt dort), und vor jedem Eintrag wird der freie Platz gegen diese
    Groesse geprueft.
    """
    import zipfile
    gespeichert, abgelehnt = [], []
    basis = ordner_anlegen(sid)
    praefix = teile(rel_ordner) if str(rel_ordner or "").strip() else []
    try:
        zf = zipfile.ZipFile(quelle)
    except (zipfile.BadZipFile, OSError) as e:
        return [], [{"name": "(Archiv)", "grund": f"Kein gültiges ZIP-Archiv ({e})"}]
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > max_eintraege:
            return [], [{"name": "(Archiv)", "grund": f"Zu viele Dateien im Archiv (> {max_eintraege})"}]
        for info in infos:
            roh = info.filename.replace("\\", "/")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                abgelehnt.append({"name": roh, "grund": "Verknüpfung im Archiv übersprungen"})
                continue
            stuecke = [x for x in roh.split("/") if x]
            # Zip-Slip ZUERST und BENANNT: ".." beginnt mit einem Punkt und
            # fiele sonst still unter "versteckt" – sicher, aber unerklaert.
            if roh.startswith("/") or ".." in stuecke or (len(roh) > 1 and roh[1] == ":"):
                abgelehnt.append({"name": roh, "grund": "Unzulässiger Pfad im Archiv"})
                continue
            if not stuecke or any(x.startswith(".") or x == "__MACOSX" for x in stuecke):
                continue  # Metadaten (.DS_Store, __MACOSX) still uebergehen
            rel = "/".join(praefix + stuecke)
            if Path(stuecke[-1]).suffix.lower() not in endungen:
                abgelehnt.append({"name": roh, "grund": f"Format „{Path(stuecke[-1]).suffix or '(ohne Endung)'}“ "
                                                        f"gehört nicht zu den Dateimustern"})
                continue
            try:
                if min_frei and shutil.disk_usage(basis).free - info.file_size < min_frei:
                    abgelehnt.append({"name": roh, "grund": "Zu wenig freier Speicher auf dem Server"})
                    continue
                with zf.open(info) as f:
                    gespeichert.append(datei_speichern(sid, rel, f, endungen))
            except DateiFehler as e:
                abgelehnt.append({"name": roh, "grund": str(e)})
            except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as e:
                # RuntimeError: verschluesselter Eintrag; NotImplementedError:
                # unbekanntes Kompressionsverfahren.
                abgelehnt.append({"name": roh, "grund": f"Entpacken fehlgeschlagen: {e}"})
    return gespeichert, abgelehnt


def baum(sid: str, limit: int = BAUM_MAX) -> dict:
    """Ordner und Dateien eines Schemas (sortiert, Ordner vor ihrem Inhalt).

    Bei mehr als ``limit`` Eintraegen wird gekappt und die Gesamtzahl GENANNT –
    ein Bestand mit 8000 Dateien darf die Seite nicht lahmlegen, aber eine
    gekuerzte Liste darf sich nicht fuer vollstaendig ausgeben.
    """
    basis = _basis(sid)
    out, dateien, bytes_ = [], 0, 0
    if not basis.is_dir():
        return {"eintraege": [], "dateien": 0, "ordner": 0, "bytes": 0, "gekappt": False, "gesamt": 0}
    ordner = 0
    alle = []
    for dp, dn, fn in os.walk(basis, followlinks=False):
        dn[:] = sorted(d for d in dn if not d.startswith("."))
        rel_dir = Path(dp).relative_to(basis)
        if rel_dir.parts:
            ordner += 1
            alle.append({"pfad": "/".join(rel_dir.parts), "art": "ordner", "groesse": 0})
        for name in sorted(fn):
            if name.startswith("."):
                continue
            p = Path(dp) / name
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            dateien += 1
            bytes_ += st.st_size
            alle.append({"pfad": "/".join((rel_dir / name).parts), "art": "datei", "groesse": st.st_size})
    alle.sort(key=lambda e: tuple(x.lower() for x in e["pfad"].split("/")))
    out = alle[:limit]
    return {"eintraege": out, "dateien": dateien, "ordner": ordner, "bytes": bytes_,
            "gekappt": len(alle) > limit, "gesamt": len(alle)}


def loeschen(sid: str, rel: str) -> dict:
    """Datei oder Ordner (samt Inhalt) im Schema loeschen. Das Schema selbst
    wird hierueber NICHT geloescht (``rel`` darf nicht leer sein)."""
    ziel = zielpfad(sid, rel)
    if not os.path.lexists(ziel):
        raise DateiFehler(f"nicht vorhanden: {rel}")
    if ziel.is_dir():
        n = sum(len(fn) for _dp, _dn, fn in os.walk(ziel, followlinks=False))
        shutil.rmtree(ziel)
        return {"art": "ordner", "dateien": n}
    ziel.unlink()
    return {"art": "datei", "dateien": 1}


def schema_loeschen(sid: str) -> int:
    """Ganzen Ablageordner eines Schemas entfernen. Rueckgabe: Anzahl Dateien."""
    basis = _basis(sid)
    if not basis.exists():
        return 0
    if basis.is_symlink():
        raise DateiFehler(f"Ablageordner ist eine Verknüpfung: {sid}")
    n = sum(len(fn) for _dp, _dn, fn in os.walk(basis, followlinks=False))
    shutil.rmtree(basis)
    return n
