#!/usr/bin/env python3
"""Ergebnisdateien: Download-Chip statt /tmp-Pfad.

DER VORFALL (2026-08-12, ECHT, zum wiederholten Mal): Der Agent hat ein PDF
ausgewertet, das Ergebnis per Shell als CSV geschrieben und geantwortet
"Das Ergebnis liegt als CSV-Datei vor unter: /tmp/KIM_Adressen_2026.csv".

Dieser Pfad ist fuer den Benutzer WERTLOS: /tmp liegt auf dem Server und gehoert
dem Sandbox-Benutzer (auf ECHT nachgesehen: jarvis_sandbox_noinet, 3823 Byte).

URSACHE: _deliver_docs (Pfade und blosse Dateinamen) UND _clean_doc_refs
benutzten dieselbe ENGE Endungsliste "docx|xlsx|pptx|pdf". Ein CSV wurde deshalb
weder als Chip ausgeliefert noch aus dem Anzeigetext entfernt. Fuer alle anderen
Typen verlangte der System-Prompt den Marker [[JARVIS_DELIVER:…]] – ein
Mechanismus, der davon abhaengt, dass das Modell daran denkt. Tut es das nicht,
bekommt der Benutzer nichts.

DIE ZUSAGE, die dieser Test festschreibt: fuer JEDEN ueblichen Ergebnistyp gilt
  1. es entsteht ein Download-Chip (/api/documents/<32 Hex>__name.ext), UND
  2. im Anzeigetext bleibt KEIN lokaler Pfad stehen.
Beide Haelften gehoeren zusammen: ein Pfad ohne Chip ist genau der gemeldete
Fehler, ein Chip ohne Bereinigung ergibt zwei konkurrierende Angebote.

Kein Import von backend.agent (zieht fastapi/config und wuerde die
Live-settings.json anfassen): die beiden Methoden werden per Quelltext
herausgeschnitten und gegen ein Stub-Objekt ausgefuehrt.

Lauf:  python3 tests/test_doc_delivery.py
"""
import asyncio
import os
import re
import sys
import tempfile
import textwrap
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "backend" / "agent.py"

ok = 0
fehler = 0


def pruefe(was, bedingung, detail=""):
    global ok, fehler
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {was}")
    else:
        fehler += 1
        print(f"  \033[31m✗\033[0m {was}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n\033[1m{t}\033[0m")


QUELLE = AGENT.read_text(encoding="utf-8")


def hole(name: str) -> str:
    """Schneidet eine Methode per Quelltext heraus (mit oder ohne async)."""
    zeilen = QUELLE.split("\n")
    start = next(i for i, z in enumerate(zeilen)
                 if z.strip().startswith(f"def {name}(") or z.strip().startswith(f"async def {name}("))
    tiefe = len(zeilen[start]) - len(zeilen[start].lstrip())
    raus = [zeilen[start]]
    for z in zeilen[start + 1:]:
        if z.strip() and (len(z) - len(z.lstrip())) <= tiefe:
            break
        raus.append(z)
    return textwrap.dedent("\n".join(raus))


def hole_liefer_ext() -> tuple:
    """Die ECHTE Liste aus agent.py – nicht nachgebaut."""
    i = QUELLE.index("_LIEFER_EXT = (")
    j = QUELLE.index("\n    )", i) + len("\n    )")
    u = {}
    exec(textwrap.dedent(QUELLE[i:j]), u)
    return u["_LIEFER_EXT"]


def hole_konstante(name: str):
    """Eine modulweite Konstante aus agent.py – ECHT, nicht abgetippt.

    `_clean_doc_refs` benutzt `_GENERATED_URL_RE`. Wer die Regex hier nachbaut,
    prueft beim naechsten Feinschliff eine andere als die laufende.
    """
    m = re.search(r"^%s = re\.compile\(" % re.escape(name), QUELLE, re.M)
    if not m:
        raise AssertionError(f"Konstante {name} nicht in agent.py gefunden")
    i = m.start()
    j = QUELLE.index("\n", QUELLE.index(")\n", i))
    u = {"re": re}
    exec(QUELLE[i:j], u)
    return u[name]


class DokStub:
    """Ersatz fuer backend.documents – merkt sich die Eigentuemer-Eintraege."""

    def __init__(self):
        self.eintraege = []

    def register(self, name, benutzer):
        self.eintraege.append((name, benutzer))


class AgentStub:
    """Nur das, was _deliver_docs von `self` braucht."""
    is_sub_agent = False
    _DELIVER_TOLERANCE_SEC = 120

    def __init__(self, ext):
        self._ext = ext
        self.gesendet = []

    def _liefer_ext_re(self):
        return "|".join(re.escape(e) for e in self._ext)

    async def _send_status(self, ws, msg, highlight=False):
        self.gesendet.append(msg)


class LaufTmpStub:
    """Ersatz fuer backend.lauf_tmp – die Uebersetzung ist HIER umschaltbar.

    Ohne sie war dieser Test seit dem /tmp-Umbau (2026-08-23) rot: `_hostpfad`
    ruft `_lauf_tmp.aufloesen`, und in der Attrappen-Umgebung gab es das Modul
    nicht (NameError mitten im Lauf). Mit `arbeit` laesst sich der Vorfall vom
    2026-08-24 nachstellen – Backend uebersetzt, die Datei liegt aber im echten
    /tmp.
    """

    def __init__(self, arbeit=None):
        self.arbeit = Path(arbeit) if arbeit else None

    def such_wurzeln(self):
        return [self.arbeit] if self.arbeit else []

    def aufloesen(self, pfad):
        s = str(pfad)
        if self.arbeit and s.startswith("/tmp/"):
            return str(self.arbeit / s[len("/tmp/"):])
        return pfad


def baue(tmpdir: Path, dok: DokStub, lauf=None):
    """Liefert (deliver, clean) – beide gegen ein gefaelschtes Projektverzeichnis."""
    umg = {
        "re": re, "os": os, "time": time, "uuid": uuid, "asyncio": asyncio,
        "_documents": dok,
        "_log": lambda *a, **k: None,
        "_lauf_tmp": lauf or LaufTmpStub(),
        "_GENERATED_URL_RE": hole_konstante("_GENERATED_URL_RE"),
        "__file__": str(tmpdir / "backend" / "agent.py"),
    }
    exec(hole("_deliver_docs"), umg)
    exec(hole("_clean_doc_refs"), umg)
    return umg["_deliver_docs"], umg["_clean_doc_refs"]


def chip_url(nachrichten):
    for m in nachrichten:
        t = re.search(r"/api/documents/([0-9a-f]{32}__[^\s)]+)", m)
        if t:
            return t.group(1)
    return None


def main() -> int:
    EXT = hole_liefer_ext()

    abschnitt("1) Die Liste selbst")
    pruefe("csv ist dabei (der gemeldete Fall)", "csv" in EXT)
    for e in ("txt", "json", "zip", "xlsx", "pdf", "png", "mp4", "md", "xml"):
        pruefe(f"{e} ist dabei", e in EXT)
    # Der Agent legt seine Zwischenschritte als Skripte in /tmp ab (auf ECHT lagen
    # extract_v4.py … extract_v17.py). Als Chips waeren sie Rauschen.
    for e in ("py", "sh", "exe", "ps1", "pyc"):
        pruefe(f"{e} ist NICHT dabei (Zwischenschritt, kein Ergebnis)", e not in EXT)
    # Nur CODE pruefen: der Begruendungs-Kommentar in agent.py nennt die alte
    # Liste woertlich. Beim ersten Lauf hat der Waechter genau daran angeschlagen -
    # dieselbe Falle wie beim Prompt-Waechter (2026-08-10) und der Ordner-Marke
    # (2026-08-11). Also Kommentarzeilen entfernen, dann suchen.
    nur_code = "\n".join(z for z in QUELLE.split("\n")
                         if not z.strip().startswith(("#", "*", '"""')))
    pruefe("eine gemeinsame Quelle fuer alle Stellen",
           QUELLE.count("_liefer_ext_re()") >= 2
           and "docx|xlsx|pptx|pdf" not in nur_code,
           "alte enge Liste noch im Code")

    # Secret-Sperre muss in ALLEN Zweigen greifen, nicht nur beim Marker.
    pruefe("Secret-Sperre wird mehrfach angewandt", QUELLE.count("_ist_geheim(") >= 4)
    # Geprueft wird die EIGENSCHAFT, nicht der Wortlaut: die Suchorte fuer blosse
    # Dateinamen sind data/documents und die Arbeitswurzeln – niemals `proj`
    # (dort liegen .env und settings.json). Die frueher hier fest verdrahtete
    # Zeile "[docs_dir, _tmp_root]" hiess nach dem /tmp-Umbau
    # "[docs_dir] + _arb_roots" und liess den Test rot stehen, obwohl die Zusage
    # unveraendert gilt – eine Zeichenkette als Testkriterium ist eine
    # Zeitbombe.
    _sd = re.search(r"_search_dirs\s*=\s*(.+)", QUELLE)
    pruefe("Projektverzeichnis ist kein Suchort mehr fuer blosse Dateinamen",
           bool(_sd) and "docs_dir" in _sd.group(1) and "proj" not in _sd.group(1),
           _sd.group(1) if _sd else "_search_dirs fehlt")

    dok = DokStub()
    # Das gefaelschte Projektverzeichnis MUSS ausserhalb von /tmp liegen:
    # tempfile.TemporaryDirectory() legt es sonst genau dort an, und dann ist die
    # Ortsschranke ("nur /tmp oder data/documents") trivial erfuellt - der Test
    # haette sie nicht geprueft, sondern nur behauptet.
    _basis = "/var/tmp" if Path("/var/tmp").is_dir() else str(Path.home())
    with tempfile.TemporaryDirectory(dir=_basis) as td:
        tmpdir = Path(td)
        (tmpdir / "backend").mkdir()
        deliver, clean = baue(tmpdir, dok)
        docs = tmpdir / "data" / "documents"
        stub = AgentStub(EXT)
        jetzt = time.time()
        aufraeumen = []

        abschnitt("2) DER GEMELDETE FALL, wortgleich")
        quelle_datei = Path("/tmp") / f"KIM_Adressen_2026_{uuid.uuid4().hex[:6]}.csv"
        quelle_datei.write_text("plz;ort\n66111;Saarbruecken\n", encoding="utf-8")
        aufraeumen.append(quelle_datei)
        antwort = f"Das Ergebnis liegt als CSV-Datei vor unter: {quelle_datei.as_posix()}"
        asyncio.run(deliver(stub, None, antwort, set(), "nexus\\andrea.ladd", jetzt))
        url = chip_url(stub.gesendet)
        pruefe("ein Download-Chip wurde gesendet", url is not None, str(stub.gesendet))
        pruefe("die Datei liegt jetzt in data/documents",
               url is not None and (docs / url).is_file())
        pruefe("Inhalt unveraendert",
               url is not None and (docs / url).read_text(encoding="utf-8").startswith("plz;ort"))
        pruefe("Eigentuemer vermerkt",
               dok.eintraege and dok.eintraege[-1][1] == "nexus\\andrea.ladd", str(dok.eintraege))
        sichtbar = clean(stub, antwort)
        pruefe("im Anzeigetext steht KEIN /tmp-Pfad mehr", "/tmp/" not in sichtbar, repr(sichtbar))
        pruefe("kein Dateiname-Fragment uebrig", ".csv" not in sichtbar, repr(sichtbar))

        abschnitt("3) Jeder uebliche Ergebnistyp – Chip UND sauberer Text")
        for e in ("csv", "tsv", "txt", "json", "xml", "md", "zip", "xlsx", "docx",
                  "pdf", "html", "ics", "mp3"):
            p = Path("/tmp") / f"ergebnis_{uuid.uuid4().hex[:6]}.{e}"
            p.write_bytes(b"x" * 32)
            aufraeumen.append(p)
            s2 = AgentStub(EXT)
            t = f"Fertig. Die Datei liegt unter {p.as_posix()} bereit."
            asyncio.run(deliver(s2, None, t, set(), "u", jetzt))
            u = chip_url(s2.gesendet)
            rein = clean(s2, t)
            pruefe(f".{e}: Chip vorhanden und Pfad entfernt",
                   u is not None and "/tmp/" not in rein,
                   f"chip={u} text={rein!r}")

        abschnitt("4) Skripte bleiben Zwischenschritte")
        for e in ("py", "sh"):
            p = Path("/tmp") / f"extract_{uuid.uuid4().hex[:6]}.{e}"
            p.write_text("print(1)\n", encoding="utf-8")
            aufraeumen.append(p)
            s3 = AgentStub(EXT)
            asyncio.run(deliver(s3, None, f"Skript {p.as_posix()} geschrieben.", set(), "u", jetzt))
            pruefe(f".{e}: KEIN Chip", chip_url(s3.gesendet) is None, str(s3.gesendet))

        abschnitt("5) Die Schranken von 2026-07-28 gelten weiter")
        alt = Path("/tmp") / f"alt_{uuid.uuid4().hex[:6]}.csv"
        alt.write_text("a;b\n", encoding="utf-8")
        aufraeumen.append(alt)
        os.utime(alt, (time.time() - 8000, time.time() - 8000))
        s4 = AgentStub(EXT)
        asyncio.run(deliver(s4, None, f"siehe {alt.as_posix()}", set(), "u", jetzt))
        pruefe("Datei aus einem FRUEHEREN Lauf wird nicht ausgeliefert (mtime-Fenster)",
               chip_url(s4.gesendet) is None, str(s4.gesendet))

        fremd = tmpdir / "geheim.csv"   # im Projektverzeichnis, also ausserhalb /tmp
        fremd.write_text("a;b\n", encoding="utf-8")
        s5 = AgentStub(EXT)
        asyncio.run(deliver(s5, None, f"siehe {fremd.as_posix()}", set(), "u", jetzt))
        pruefe("Datei ausserhalb /tmp und data/documents wird nicht ausgeliefert",
               chip_url(s5.gesendet) is None, str(s5.gesendet))

        env = Path("/tmp") / f"cfg_{uuid.uuid4().hex[:6]}.env"
        env.write_text("KEY=1\n", encoding="utf-8")
        aufraeumen.append(env)
        s6 = AgentStub(EXT)
        asyncio.run(deliver(s6, None, f"[[JARVIS_DELIVER:{env.as_posix()}]]", set(), "u", jetzt))
        pruefe("Secret-Endung wird auch per Marker abgelehnt",
               chip_url(s6.gesendet) is None, str(s6.gesendet))

        abschnitt("5b) Zustandsdateien sind tabu – auch wenn sie im Text stehen")
        # Die Erweiterung der Endungsliste auf json/txt/... hat diese Pruefung
        # ueberhaupt erst noetig gemacht: vorher war settings.json ausser Reichweite,
        # weil .json nicht ausgeliefert wurde. Der Test hat das Loch gefunden.
        for name in ("settings.json", "license.json", "ad_cache.json", ".owners.json"):
            geheim = Path("/tmp") / name
            neu_angelegt = not geheim.exists()
            if neu_angelegt:
                geheim.write_text("{}", encoding="utf-8")
            s8 = AgentStub(EXT)
            asyncio.run(deliver(s8, None, f"Ergebnis in {geheim.as_posix()}", set(), "u", jetzt))
            pruefe(f"{name} wird nicht ausgeliefert", chip_url(s8.gesendet) is None,
                   str(s8.gesendet))
            if neu_angelegt:
                try:
                    geheim.unlink()
                except OSError:
                    pass

        abschnitt("6) Doppelte Auslieferung wird vermieden")
        p = Path("/tmp") / f"einmal_{uuid.uuid4().hex[:6]}.csv"
        p.write_text("a;b\n", encoding="utf-8")
        aufraeumen.append(p)
        s7 = AgentStub(EXT)
        gemeldet = set()
        t = f"{p.as_posix()} und noch einmal {p.as_posix()}"
        asyncio.run(deliver(s7, None, t, gemeldet, "u", jetzt))
        pruefe("derselbe Pfad ergibt genau EINEN Chip",
               len([m for m in s7.gesendet if "/api/documents/" in m]) == 1, str(s7.gesendet))

        abschnitt("7) Verfehlter Liefer-Marker wird GEMELDET (Vorfall 2026-08-24)")
        # Nachbau: die Shell schreibt ins gemeinsame /tmp (alter Broker), das
        # Backend haelt die Isolation fuer aktiv und uebersetzt -> die Datei ist
        # unter dem uebersetzten Pfad NICHT vorhanden. Vorher: stilles
        # `continue`, kein Log, kein Chip – und im Chat blieb der Satz stehen,
        # der auf den Link verwies.
        echte = Path("/tmp") / f"ergebnis_{uuid.uuid4().hex[:6]}.xlsx"
        echte.write_bytes(b"PK\x03\x04egal")
        aufraeumen.append(echte)
        arbeit = tmpdir / "jarvis-arbeit" / "abcdef01"
        arbeit.mkdir(parents=True, exist_ok=True)
        deliver_iso, clean_iso = baue(tmpdir, dok, LaufTmpStub(arbeit))

        s9 = AgentStub(EXT)
        marker = ("Die Liste liegt bereit. Falls kein Chip erscheint, nutze diesen Link:\n\n"
                  f"[[JARVIS_DELIVER:{echte.as_posix()}]]")
        asyncio.run(deliver_iso(s9, None, marker, set(), "u", jetzt, True))
        pruefe("kein Chip, wenn der uebersetzte Pfad ins Leere zeigt",
               not [m for m in s9.gesendet if "/api/documents/" in m], str(s9.gesendet))
        pruefe("der Benutzer wird darauf HINGEWIESEN",
               any("⚠️" in m and echte.name in m for m in s9.gesendet),
               "sonst steht 'nutze diesen Link:' im Chat und dahinter nichts – "
               f"gesendet: {s9.gesendet}")
        pruefe("und der Anzeigetext nennt den Marker nicht mehr",
               "JARVIS_DELIVER" not in clean_iso(s9, marker))

        # Gegenprobe 1: derselbe Text OHNE Meldeauftrag (Werkzeug-Ergebnis, die
        # Datei kann einen Schritt spaeter noch entstehen) -> keine Warnung.
        s10 = AgentStub(EXT)
        asyncio.run(deliver_iso(s10, None, marker, set(), "u", jetzt))
        pruefe("ein Werkzeug-Ergebnis warnt NICHT verfrueht",
               not any("⚠️" in m for m in s10.gesendet), str(s10.gesendet))

        # Gegenprobe 2: ohne Uebersetzung (Isolation aus bzw. gemeldet
        # unwirksam) findet derselbe Marker die Datei und liefert den Chip.
        s11 = AgentStub(EXT)
        asyncio.run(deliver(s11, None, marker, set(), "u", jetzt, True))
        pruefe("ohne Uebersetzung entsteht der Chip",
               len([m for m in s11.gesendet if "/api/documents/" in m]) == 1, str(s11.gesendet))
        pruefe("dann auch KEINE Warnung",
               not any("⚠️" in m for m in s11.gesendet), str(s11.gesendet))

        abschnitt("8) Wiederholter Liefer-Marker warnt NICHT (Vorfall 2026-09-04)")
        # Gemeldet von ECHT: die PPTX wurde erzeugt, der Download funktionierte -
        # und darunter stand "Konnte nicht zum Download bereitgestellt werden:
        # prozessautomatisierung.pptx ... bitte die Datei erneut erzeugen lassen".
        # Ursache: `_ingest` VERSCHIEBT die Quelle. Wurde die Datei schon aus
        # einem Werkzeug-Ergebnis ausgeliefert und wiederholt das Modell in der
        # Endantwort den Marker (der System-Prompt verlangt ihn), fand der
        # Marker-Zweig sie nicht mehr - ihm fehlte der `_schon`-Waechter, den
        # der Pfad-Zweig seit 2026-08-24 hat.
        #
        # Gemessen wird die EIGENSCHAFT (kommt eine Warnung neben dem Chip?),
        # nicht das Vorkommen von `_schon` im Quelltext - eine Textsuche bliebe
        # gruen, sobald jemand den Zweig spaeter ueberspringt.
        def zwei_durchgaenge(t1, t2):
            """Werkzeug-Ergebnis (melden=False) + Endantwort (melden=True)."""
            d = Path("/tmp") / f"prozessautomatisierung_{uuid.uuid4().hex[:6]}.pptx"
            d.write_bytes(b"PK\x03\x04egal")
            aufraeumen.append(d)
            s_ = AgentStub(EXT)
            gesehen = set()
            asyncio.run(deliver(s_, None, t1.format(p=d.as_posix()), gesehen, "u", jetzt, False))
            chip = chip_url(s_.gesendet)
            asyncio.run(deliver(s_, None, t2.format(p=d.as_posix()), gesehen, "u", jetzt, True))
            return chip, [m for m in s_.gesendet if "Konnte nicht zum Download" in m]

        for _name, _t1, _t2 in (
                ("Pfad -> Pfad", "Gespeichert: {p}", "Fertig, die Datei liegt unter {p}."),
                ("Pfad -> Marker", "Gespeichert: {p}", "Fertig.\n[[JARVIS_DELIVER:{p}]]"),
                ("Marker -> Marker", "[[JARVIS_DELIVER:{p}]]", "Fertig.\n[[JARVIS_DELIVER:{p}]]"),
                ("Marker -> Pfad", "[[JARVIS_DELIVER:{p}]]", "Fertig, die Datei liegt unter {p}.")):
            _chip, _warn = zwei_durchgaenge(_t1, _t2)
            pruefe(f"{_name}: der Chip entsteht", _chip is not None)
            pruefe(f"{_name}: KEINE Warnung neben dem fertigen Chip", not _warn, str(_warn))

        # Positivkontrolle - ohne sie waere "keine Warnung" trivial erfuellbar:
        # eine Datei, die es NIE gab, muss weiterhin gemeldet werden.
        s12 = AgentStub(EXT)
        nie = Path("/tmp") / f"gibtsnicht_{uuid.uuid4().hex[:6]}.pptx"
        asyncio.run(deliver(s12, None, f"[[JARVIS_DELIVER:{nie.as_posix()}]]",
                            set(), "u", jetzt, True))
        pruefe("eine nie erzeugte Datei wird weiterhin gemeldet",
               any("Konnte nicht zum Download" in m and nie.name in m for m in s12.gesendet),
               str(s12.gesendet))

        for f in aufraeumen:
            try:
                f.unlink()
            except OSError:
                pass

    print(f"\n{ok} ok, {fehler} Fehler ({ok + fehler} Pruefungen)")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
