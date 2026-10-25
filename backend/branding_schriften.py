"""Schriftdateien aus dem Branding-Reiter (TTF/OTF) fuer die Dokument-Ausgabe.

WOZU: Die Office-Vorlagen tragen die CI-Schrift (``skills/office/vorlage.py``,
``SCHRIFT_TITEL``/``SCHRIFT_TEXT``). Auf dem Server ist sie in der Regel nicht
installiert – der PDF-Export ueber LibreOffice setzt dann eine Ersatzschrift
(Noto Sans / DejaVu Sans), und Zeilenumbrueche weichen vom Original ab. Wer eine
Lizenz fuer den Server hat, laedt die Schrift hier hoch.

WO DIE DATEIEN LIEGEN: ``data/branding/fonts``. ``data/`` ist gitignored – eine
lizenzierte Schrift darf nie ins (oeffentliche) Repo. Gesichert wird sie mit
dem uebrigen Datenbestand.

WIE FONTCONFIG SIE FINDET: Der Ordner liegt nicht in einem Standard-Suchpfad.
``sicherstellen()`` legt deshalb beim Dienstbenutzer
``~/.config/fontconfig/conf.d/60-jarvis-branding.conf`` mit einem ``<dir>``
an; Debian bindet dieses Verzeichnis ueber ``/etc/fonts/conf.d/50-user.conf``
ein. LibreOffice liest Schriften ueber fontconfig – ein ``systemctl restart``
ist nicht noetig, jeder PDF-Export startet ein frisches ``soffice``.
Bewusst KEIN Systemordner (/usr/local/share/fonts): der Dienst laeuft
unprivilegiert unter ProtectSystem=strict und kann dort nicht schreiben.

GRENZE: Sandbox-Laeufe (shell_execute eingeschraenkter Benutzer) sehen ein
anderes HOME und damit diese Konfiguration nicht. Der PDF-Export
(``office_to_pdf``) laeuft im Dienstprozess und ist nicht betroffen.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent.parent / "data" / "branding" / "fonts"

ENDUNGEN = {"ttf", "otf", "ttc", "otc"}
# 30 MB: eine lateinische Schrift hat wenige hundert KB, eine CJK-Sammlung
# erreicht 20 MB. Mehr ist keine einzelne Schrift.
MAX_BYTES = 30 * 1024 * 1024

# Der Inhalt entscheidet, nicht die Endung: eine umbenannte PDF-Datei wuerde
# sonst abgelegt und fontconfig ueberginge sie stumm – der Administrator saehe
# "hochgeladen" und wunderte sich ueber die Ersatzschrift im PDF.
_KENNUNGEN = {
    b"\x00\x01\x00\x00": "TrueType",
    b"true": "TrueType",
    b"OTTO": "OpenType",
    b"ttcf": "Schriftsammlung",
}

_CONF_NAME = "60-jarvis-branding.conf"
_FC_TIMEOUT = 20


def _conf_pfad() -> Path:
    """Konfigurationsdatei im XDG-Konfigurationsordner des Dienstbenutzers."""
    basis = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(basis) / "fontconfig" / "conf.d" / _CONF_NAME


def _conf_inhalt() -> str:
    return (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">\n'
        "<fontconfig>\n"
        "  <!-- Von Jarvis angelegt (Branding-Reiter, Schriften). -->\n"
        f"  <dir>{FONT_DIR}</dir>\n"
        "</fontconfig>\n"
    )


def sicherstellen() -> bool:
    """Legt Schriftordner und fontconfig-Eintrag an. True, wenn der Eintrag stimmt.

    Wird bei jedem Upload und beim Dienststart gerufen – ein aus der
    Sicherung zurueckgespielter Server hat die Dateien in data/, aber nicht
    die Konfiguration im HOME."""
    try:
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        conf = _conf_pfad()
        soll = _conf_inhalt()
        if not conf.exists() or conf.read_text(encoding="utf-8") != soll:
            conf.parent.mkdir(parents=True, exist_ok=True)
            tmp = conf.with_suffix(".tmp")
            tmp.write_text(soll, encoding="utf-8")
            tmp.replace(conf)
        return True
    except OSError:
        return False


def _fc(werkzeug: str, *argumente: str) -> str | None:
    """Ruft ein fontconfig-Werkzeug. None, wenn es fehlt oder scheitert."""
    pfad = shutil.which(werkzeug)
    if not pfad:
        return None
    try:
        proc = subprocess.run([pfad, *argumente], capture_output=True, text=True,
                              timeout=_FC_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def cache_erneuern() -> None:
    """Baut den fontconfig-Cache fuer den Schriftordner neu.

    Ohne diesen Schritt findet fontconfig neue Dateien auch, prueft dafuer aber
    bei jedem Start die Verzeichniszeit – der Cache macht es nur schneller."""
    _fc("fc-cache", "-f", str(FONT_DIR))


def _familien(text: str) -> list[str]:
    """fontconfig trennt mehrere Familiennamen mit Komma (Escape: \\,)."""
    teile = re.split(r"(?<!\\),", text or "")
    return [t.replace("\\,", ",").strip() for t in teile if t.strip()]


def _erster(text: str) -> str:
    werte = _familien(text)
    return werte[0] if werte else ""


def scan(pfad: Path) -> list[dict] | None:
    """Liest die Schriften einer Datei ueber fc-scan.

    Rueckgabe: je Schnitt {familien, stil, name}; leere Liste = Datei ist keine
    lesbare Schrift; None = fc-scan fehlt (dann kann nichts gemessen werden)."""
    aus = _fc("fc-scan", "--format", "%{family}\t%{style}\t%{fullname}\n", str(pfad))
    if aus is None:
        return None if not shutil.which("fc-scan") else []
    schnitte = []
    for zeile in aus.splitlines():
        teile = zeile.split("\t")
        if len(teile) < 3 or not teile[0].strip():
            continue
        schnitte.append({
            "familien": _familien(teile[0]),
            "stil": _erster(teile[1]),
            "name": _erster(teile[2]),
        })
    return schnitte


def sicherer_name(dateiname: str) -> tuple[str, str]:
    """Dateiname -> (gereinigter Name, Endung). Endung leer = nicht erlaubt.

    Nur der Basisname zaehlt; Pfadbestandteile, Steuerzeichen und fuehrende
    Punkte fallen weg – der Name stammt vom Browser des Hochladenden."""
    basis = Path((dateiname or "").replace("\\", "/")).name
    stamm, _, endung = basis.rpartition(".")
    endung = endung.lower()
    if not stamm or endung not in ENDUNGEN:
        return "", ""
    stamm = re.sub(r"[^A-Za-z0-9._-]+", "_", stamm).strip("._-")[:80] or "schrift"
    return f"{stamm}.{endung}", endung


def pruefen(daten: bytes, dateiname: str) -> tuple[bool, str, dict]:
    """Prueft einen Upload. Rueckgabe (ok, fehler, infos)."""
    name, endung = sicherer_name(dateiname)
    if not endung:
        return False, ("Format nicht erlaubt – erlaubt sind "
                       + ", ".join("." + e for e in sorted(ENDUNGEN))), {}
    if not daten:
        return False, "Datei ist leer", {}
    if len(daten) > MAX_BYTES:
        return False, (f"Datei ist zu gross ({len(daten) // (1024 * 1024)} MB, "
                       f"erlaubt {MAX_BYTES // (1024 * 1024)} MB)"), {}
    art = _KENNUNGEN.get(daten[:4])
    if not art:
        return False, "Keine Schriftdatei (TrueType/OpenType-Kennung fehlt)", {}
    return True, "", {"name": name, "art": art}


def speichern(daten: bytes, dateiname: str) -> tuple[bool, str, dict]:
    """Prueft, legt ab und meldet die erkannten Schnitte. Rueckgabe (ok, fehler, infos).

    Erst in eine Zwischendatei AUSSERHALB des Schriftordners schreiben und
    pruefen: eine kaputte Datei im Ordner wuerde fontconfig bei jedem Lauf
    erneut anfassen."""
    ok, fehler, infos = pruefen(daten, dateiname)
    if not ok:
        return ok, fehler, infos
    if not sicherstellen():
        return False, "Schriftordner oder fontconfig-Eintrag nicht anlegbar", {}
    tmp = FONT_DIR.parent / (".upload-" + infos["name"])
    try:
        tmp.write_bytes(daten)
        schnitte = scan(tmp)
        if schnitte is not None and not schnitte:
            return False, "Die Datei ist keine lesbare Schrift", {}
        ziel = FONT_DIR / infos["name"]
        tmp.replace(ziel)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    cache_erneuern()
    infos["schnitte"] = schnitte or []
    infos["gemessen"] = schnitte is not None
    infos["size"] = len(daten)
    return True, "", infos


def _in_ordner(name: str) -> Path | None:
    """Pfad einer abgelegten Schrift – nur Basisnamen im Schriftordner."""
    if not name or name != Path(name).name or name.startswith("."):
        return None
    if name.rpartition(".")[2].lower() not in ENDUNGEN:
        return None
    pfad = FONT_DIR / name
    try:
        if pfad.resolve().parent != FONT_DIR.resolve():
            return None
    except OSError:
        return None
    return pfad


def entfernen(name: str) -> tuple[bool, str]:
    """Entfernt eine abgelegte Schrift. Rueckgabe (ok, fehler)."""
    pfad = _in_ordner(name)
    if pfad is None:
        return False, "Ungueltiger Name"
    if not pfad.is_file():
        return False, "Schrift nicht gefunden"
    try:
        pfad.unlink()
    except OSError as e:
        return False, f"Entfernen fehlgeschlagen ({e})"
    cache_erneuern()
    return True, ""


def liste() -> list[dict]:
    """Abgelegte Schriften mit Groesse, Datum und erkannten Schnitten."""
    if not FONT_DIR.is_dir():
        return []
    eintraege = []
    for pfad in sorted(FONT_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not pfad.is_file() or pfad.name.startswith("."):
            continue
        if pfad.suffix.lstrip(".").lower() not in ENDUNGEN:
            continue
        st = pfad.stat()
        eintraege.append({"name": pfad.name, "size": st.st_size, "mtime": int(st.st_mtime),
                          "schnitte": scan(pfad) or []})
    return eintraege


def abdeckung(namen: list[str]) -> list[dict]:
    """Welche Schrift bekommt ein Dokument, das ``name`` verlangt?

    Gemessen mit fc-match – derselben Aufloesung, die LibreOffice benutzt.
    ``gefunden`` heisst: der verlangte Name ist einer der Familiennamen der
    gelieferten Schrift; sonst steht in ``ersatz``, was stattdessen gedruckt
    wird. ``gemessen`` False = fc-match fehlt."""
    ergebnis = []
    for name in namen:
        aus = _fc("fc-match", "--format", "%{family}\t%{file}", name)
        if aus is None:
            ergebnis.append({"name": name, "gemessen": False, "gefunden": False,
                             "ersatz": "", "datei": ""})
            continue
        familie, _, datei = aus.partition("\t")
        familien = _familien(familie)
        gefunden = name.casefold() in {f.casefold() for f in familien}
        ergebnis.append({
            "name": name, "gemessen": True, "gefunden": gefunden,
            "ersatz": "" if gefunden else (familien[0] if familien else ""),
            # Nur der Dateiname: der Pfad des Servers geht den Browser nichts an.
            "datei": Path(datei.strip()).name,
            "eigene": bool(datei.strip()) and Path(datei.strip()).parent == FONT_DIR,
        })
    return ergebnis


def zustand(vorlagen_schriften: list[str]) -> dict:
    """Antwort fuer den Branding-Reiter."""
    konfiguriert = sicherstellen()
    return {
        "fonts": liste(),
        "vorlagen": abdeckung(vorlagen_schriften),
        "fontconfig": konfiguriert and shutil.which("fc-match") is not None,
    }
