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

# Proben-Dateien im echten /tmp – modulweit, damit `aufraeumen_jetzt()`
# sie auch nach einer Ausnahme erreicht (siehe dort).
AUFRAEUMEN = []


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


def modul_konstanten() -> dict:
    """Namensraum mit ALLEN modulweiten Konstanten aus agent.py – als REGEL.

    ⚠ EINE GEPFLEGTE LISTE WAR HIER EIN FEHLER. Der Harness nannte nur
    ``_GENERATED_URL_RE``; als ``_clean_doc_refs`` eine zweite Konstante
    (``_NETZQUELLE_RE``) hinzubekam, brach der Lauf mit einem nackten
    NameError ab – kein FAIL, keine Bilanzzeile, also von "nicht gelaufen"
    nicht zu unterscheiden. Dieselbe Falle wie bei den Funktionslisten der
    Popup-Harnesse.

    Ausgefuehrt wird in QUELLTEXT-Reihenfolge (Konstanten bauen aufeinander
    auf); was ohne fremde Importe nicht auswertbar ist, wird uebersprungen.
    Das darf nicht still bleiben: ``pruefe_vorhanden()`` verlangt danach
    ausdruecklich jeden Namen, den die geschnittene Funktion wirklich benutzt.
    """
    import ast as _ast
    aus = {"re": re}
    for k in _ast.parse(QUELLE).body:
        if not isinstance(k, _ast.Assign) or len(k.targets) != 1:
            continue
        ziel = getattr(k.targets[0], "id", "")
        if not ziel.startswith("_") or not ziel.isupper() and ziel.upper() != ziel:
            continue
        try:
            exec(_ast.get_source_segment(QUELLE, k), aus)
        except Exception:      # braucht einen fremden Import – nicht noetig
            pass
    return aus


def pruefe_vorhanden(umg: dict, quelle_der_funktion: str) -> None:
    """Jede ``_..._X``-Konstante, die die geschnittene Funktion nennt, MUSS da
    sein – sonst stirbt der Lauf spaeter mitten in einer Pruefung."""
    # Namen, die die Funktion SELBST setzt (``_EXT_RE = self._liefer_ext_re()``),
    # sind lokal und gehoeren nicht in den Namensraum.
    lokal = set(re.findall(r"^\s*(_[A-Z][A-Z0-9_]*)\s*(?::[^=\n]+)?=",
                           quelle_der_funktion, re.M))
    fehlt = sorted({n for n in re.findall(r"\b_[A-Z][A-Z0-9_]*\b", quelle_der_funktion)
                    if n not in umg and n not in lokal})
    if fehlt:
        raise AssertionError("Konstanten fehlen im Testnamensraum: " + ", ".join(fehlt))


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
        self.dauerhaft = []     # Texte, die mit persist=True gesendet wurden

    def _liefer_ext_re(self):
        return "|".join(re.escape(e) for e in self._ext)

    # ⚠ DIE SIGNATUR IST DIE DES ORIGINALS, nicht die bequemere.
    # Als `persist` dazukam, brach dieser Lauf mitten in Abschnitt 7 mit einem
    # nackten TypeError ab – ohne Bilanzzeile, also von "nicht gelaufen" nicht
    # zu unterscheiden. Register: eine Attrappe mit weniger als dem Original
    # stirbt beim naechsten Argument.
    async def _send_status(self, ws, msg, highlight=False, intermediate=False,
                           persist=False):
        self.gesendet.append(msg)
        if persist:
            self.dauerhaft.append(msg)


class LaufTmpStub:
    """Ersatz fuer backend.lauf_tmp – die Uebersetzung ist HIER umschaltbar.

    Ohne sie war dieser Test seit dem /tmp-Umbau (2026-08-23) rot: `_hostpfad`
    ruft `_lauf_tmp.aufloesen`, und in der Attrappen-Umgebung gab es das Modul
    nicht (NameError mitten im Lauf). Mit `arbeit` laesst sich der Vorfall vom
    2026-08-24 nachstellen – Backend uebersetzt, die Datei liegt aber im echten
    /tmp.
    """

    def __init__(self, arbeit=None, anhaenge=None):
        self.arbeit = Path(arbeit) if arbeit else None
        self.anhaenge = Path(anhaenge) if anhaenge else None

    def such_wurzeln(self):
        return [self.arbeit] if self.arbeit else []

    def anhang_verzeichnis(self, benutzer, anlegen=False):
        """Signatur wie im Original (``backend/lauf_tmp.py``), inkl. `anlegen`.

        ``None`` ist die ECHTE Antwort ohne Isolation – dann liegt die
        Arbeitskopie direkt in /tmp, und die Namensschranke muss trotzdem
        greifen."""
        return self.anhaenge

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
        **modul_konstanten(),
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
        aufraeumen = AUFRAEUMEN

        abschnitt("2) DER GEMELDETE FALL, wortgleich")
        quelle_datei = Path("/tmp") / f"KIM_Adressen_2026_{uuid.uuid4().hex[:6]}.csv"
        quelle_datei.write_text("plz;ort\n66111;Saarbruecken\n", encoding="utf-8")
        aufraeumen.append(quelle_datei)
        antwort = f"Das Ergebnis liegt als CSV-Datei vor unter: {quelle_datei.as_posix()}"
        asyncio.run(deliver(stub, None, antwort, set(), "firma\\l.platz", jetzt))
        url = chip_url(stub.gesendet)
        pruefe("ein Download-Chip wurde gesendet", url is not None, str(stub.gesendet))
        pruefe("die Datei liegt jetzt in data/documents",
               url is not None and (docs / url).is_file())
        pruefe("Inhalt unveraendert",
               url is not None and (docs / url).read_text(encoding="utf-8").startswith("plz;ort"))
        pruefe("Eigentuemer vermerkt",
               dok.eintraege and dok.eintraege[-1][1] == "firma\\l.platz", str(dok.eintraege))
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

        abschnitt("9) Datei ist beim Benutzer -> keine Warnung (Vorfall 2026-09-04)")
        # Der Fix vom selben Tag (`_schon`) griff nur bei GLEICHEM Pfad. Gemeldet
        # blieb: `office_create_powerpoint` legt die Datei mit Capability-Namen in
        # data/documents (Chip via Zweig a), und das Modell nennt in derselben
        # Antwort zusaetzlich einen Pfad, den es nie gab. Ein Pfad-Schluessel kann
        # das nicht erkennen - verglichen wird deshalb der NAME.
        def mit_office(zweiter_text, dateiname="Prozessautomatisierung.pptx"):
            """(Chip?, Warnungen) – Werkzeug-Ergebnis, dann Endantwort."""
            cap = f"{uuid.uuid4().hex}__{dateiname}"
            docs.mkdir(parents=True, exist_ok=True)
            (docs / cap).write_bytes(b"PK\x03\x04egal")
            s_ = AgentStub(EXT)
            gesehen = set()
            werkzeug = f"✅ '{dateiname}' wurde erstellt.\n\n[📥 x](/api/documents/{cap})"
            asyncio.run(deliver(s_, None, werkzeug, gesehen, "u", jetzt, False))
            asyncio.run(deliver(s_, None, zweiter_text, gesehen, "u", jetzt, True))
            return (chip_url(s_.gesendet),
                    [m for m in s_.gesendet if "Konnte nicht zum Download" in m])

        for _name, _text in (
                ("Phantom-Pfad in der Antwort",
                 "Fertig. Die Datei liegt unter /tmp/prozessautomatisierung.pptx."),
                ("Phantom-Marker in der Antwort",
                 "Fertig.\n[[JARVIS_DELIVER:/tmp/prozessautomatisierung.pptx]]"),
                ("Rohname in data/documents genannt",
                 "Fertig, gespeichert als data/documents/Prozessautomatisierung.pptx."),
                # Auf DEV live gemessene Variante: der Marker traegt den ABSOLUTEN
                # Pfad nach data/documents – auch dort gibt es die Datei nur unter
                # ihrem Capability-Namen.
                ("Marker auf den absoluten data/documents-Pfad",
                 "Fertig.\n[[JARVIS_DELIVER:%s/Prozessautomatisierung.pptx]]" % docs.as_posix())):
            _chip, _warn = mit_office(_text)
            pruefe(f"{_name}: der Chip entsteht", _chip is not None)
            pruefe(f"{_name}: KEINE Warnung – die Datei ist beim Benutzer",
                   not _warn, str(_warn))

        # Positivkontrolle 1: nichts geliefert -> die Warnung MUSS kommen.
        s13 = AgentStub(EXT)
        nie2 = Path("/tmp") / f"fehlt_{uuid.uuid4().hex[:6]}.pptx"
        asyncio.run(deliver(s13, None, f"Ergebnis: {nie2.as_posix()}", set(), "u", jetzt, True))
        pruefe("ohne jede Auslieferung wird weiterhin gewarnt",
               any("Konnte nicht zum Download" in m for m in s13.gesendet), str(s13.gesendet))

        # Positivkontrolle 2 – die GRENZE der Regel: ein ANDERER Name wird
        # weiterhin gemeldet, auch wenn nebenher etwas geliefert wurde. Ohne
        # diese Haelfte waere die Schranke "es kam ja irgendein Chip" und wuerde
        # eine echte verfehlte zweite Datei verschlucken.
        _chip2, _warn2 = mit_office(f"Fertig. Zweite Datei: /tmp/anhang_{uuid.uuid4().hex[:6]}.csv")
        pruefe("ein ANDERER Name wird weiterhin gemeldet", bool(_warn2), str(_chip2))

        # Die Verdrahtung in run_task: ein ZWISCHENTEXT (neben Werkzeug-Aufrufen)
        # ist nicht der letzte Text des Laufs und darf nichts melden – sonst warnt
        # der Lauf, BEVOR das Werkzeug die angekuendigte Datei erzeugt.
        _ruf = re.search(r"await self\._deliver_docs\(ws, text, _delivered_docs.*?\)",
                         QUELLE, re.S)
        pruefe("run_task meldet nur am letzten Text",
               bool(_ruf) and "melden=True" not in _ruf.group(0)
               and "is_intermediate" in _ruf.group(0),
               _ruf.group(0) if _ruf else "Aufruf nicht gefunden")
        pruefe("ein angekuendigter Pfad ohne Meldeauftrag warnt nicht",
               not any("Konnte nicht zum Download" in m for m in (lambda s_: (
                   asyncio.run(deliver(s_, None,
                                       "Ich speichere sie unter /tmp/kuendigt_an.pptx.",
                                       set(), "u", jetzt, False)), s_.gesendet)[1])(AgentStub(EXT))))

        abschnitt("10) Der Prompt fordert den Marker nur fuer eigene /tmp-Dateien")
        # Die Namensregel oben faengt den Fehlalarm ab – sie beseitigt aber nicht
        # den Grund. Auf ECHT gemessen (Journal, 4 Tage): 9 von 11 Meldungen
        # entstanden, weil das Modell nach einem office_*-Werkzeug ZUSAETZLICH
        # einen Marker auf einen /tmp-Pfad setzte, den es nie gab. Der Prompt
        # verlangte den Marker fuer "JEDER ANDERE Dateityp" – logisch richtig,
        # aber ohne den konkreten Gegenfall, und genau den ueberliest das Modell
        # (dieselbe Lehre wie beim erfundenen Fehlschlag, 2026-08-30).
        #
        # ⚠ GEMESSEN, UND ES HILFT NICHT: auf DEV mit echtem Modell 1 von 4
        # Laeufen VOR der Prompt-Zeile, 2 von 8 danach – unveraendert rund ein
        # Viertel. Die Zeile bleibt als knapper Halbsatz stehen, weil sie sachlich
        # richtig ist; TRAGEND ist die Namensregel oben. Wer hier eine laengere
        # Belehrung einbaut, zahlt Prompt-Laenge fuer einen Effekt, der nicht
        # nachweisbar ist.
        _marker_zeile = next((z for z in QUELLE.split("\n")
                              if "[[JARVIS_DELIVER:/tmp/<dateiname.ext>]]" in z), "")
        pruefe("die Marker-Regel nennt die office_*-Ausnahme",
               "office_" in _marker_zeile and "selbst geschrieben" in _marker_zeile,
               _marker_zeile[-200:] or "Prompt-Zeile nicht gefunden")
        _auto_zeile = next((z for z in QUELLE.split("\n")
                            if "DU musst dich darum nicht kuemmern" in z), "")
        pruefe("und die Auslieferungs-Regel sagt es fuer Office/Bilder ausdruecklich",
               "KEINEN Liefer-Marker" in _auto_zeile,
               _auto_zeile[-200:] or "Prompt-Zeile nicht gefunden")

        # 2026-10-06: der Prompt muss den NAMEN zur Pflicht machen, nicht nur
        # den Marker. Das Modell hatte `Auftragsnummer_C128.jpg` behauptet, ohne
        # je ein `ls` gesehen zu haben – pdftoppm meldet Erfolg mit LEERER
        # Ausgabe, und "(Keine Ausgabe)" sah fuer das Modell wie Bestaetigung
        # aus. Geprueft wird die EIGENSCHAFT (nennt die Regel das Nachsehen und
        # den Grund?), nicht der Wortlaut.
        _seh_zeile = next((z for z in QUELLE.split("\n")
                           if "NENNE einen Dateinamen erst" in z), "")
        pruefe("der Prompt verlangt, den Dateinamen vorher zu SEHEN",
               bool(_seh_zeile), "Prompt-Zeile nicht gefunden")
        pruefe("er nennt den konkreten Fall (Seitennummer) und das Nachsehen",
               "pdftoppm" in _seh_zeile and "ls -l" in _seh_zeile,
               _seh_zeile[-220:] or "Prompt-Zeile nicht gefunden")
        # `-singlefile` ist eine ZUSAGE an das Modell – lokal nachgemessen:
        # mit dem Schalter entsteht `ziel.jpg`, ohne ihn `ziel-1.jpg`. Ein
        # Prompt ist Code; eine erfundene Option waere eine Sackgasse.
        pruefe("und den Ausweg, der ohne Seitenzusatz schreibt",
               "-singlefile" in _seh_zeile, _seh_zeile[-220:])

        abschnitt("11) Seitennummer im Namen (Vorfall 2026-10-06, ECHT)")
        # DER GEMELDETE FALL, wortgleich: ein Benutzer liess ein PDF in ein
        # 300-dpi-JPEG wandeln. Der Agent rief korrekt
        #   pdftoppm -jpeg -r 300 <quelle> /tmp/Auftragsnummer_C128
        # auf. pdftoppm haengt die SEITENNUMMER an (lokal nachgemessen:
        # `Auftragsnummer_C128-1.jpg`, rc 0, stdout LEER) und das Modell nannte
        # in der Antwort `Auftragsnummer_C128.jpg`. Zweig (c) suchte genau
        # diesen Namen, fand nichts und brach mit einem nackten `continue` ab:
        # kein Chip, keine Vorschau, keine Journal-Zeile, keine Warnung.
        arb2 = tmpdir / "jarvis-arbeit" / "83cccf13"
        arb2.mkdir(parents=True, exist_ok=True)
        anh2 = tmpdir / "jarvis-anhaenge" / "83cccf13"
        anh2.mkdir(parents=True, exist_ok=True)
        deliver2, _clean2 = baue(tmpdir, dok, LaufTmpStub(arb2, anh2))

        (arb2 / "Auftragsnummer_C128-1.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 64)
        s14 = AgentStub(EXT)
        echte_antwort = ("Die Konvertierung war erfolgreich. Das PDF wurde als JPEG "
                         "im Hausdesign (300 dpi) erstellt und steht dir zur Verfügung.\n\n"
                         "✅ **Auftragsnummer_C128.jpg** liegt im Dateisystem und wird "
                         "automatisch als Vorschau im Chat angezeigt.")
        asyncio.run(deliver2(s14, None, echte_antwort, set(), "u", jetzt, True))
        _u14 = chip_url(s14.gesendet)
        pruefe("die Datei mit Seitennummer wird ausgeliefert",
               _u14 is not None and "Auftragsnummer_C128-1" in _u14, str(s14.gesendet))
        pruefe("als Bild inline (Vorschau)",
               any(m.startswith("![") for m in s14.gesendet), str(s14.gesendet))
        # ZWEITER gemeldeter Fall (ECHT 2026-10-12): Auslieferung und Vorschau
        # klappten, der Benutzer hatte aber "zum download anbieten" verlangt –
        # es gab nur das eingebettete Bild. Zur Vorschau gehoert der Chip mit
        # DERSELBEN Adresse (keine zweite Kopie der Datei).
        _bild14 = [m for m in s14.gesendet if m.startswith("![")]
        _chip14 = re.findall(r"\[📥 ([^\]]+) herunterladen\]\((/api/documents/[^)]+)\)",
                             "\n".join(_bild14))
        pruefe("zur Bild-Vorschau gehoert ein Download-Chip",
               len(_chip14) == 1, str(s14.gesendet))
        pruefe("Chip und Vorschau zeigen auf DIESELBE Datei",
               # chip_url liefert den Capability-NAMEN ohne Pfadpraefix
               bool(_chip14) and _u14 is not None
               and _chip14[0][1] == "/api/documents/" + _u14,
               f"chip={_chip14} bild={_u14}")
        pruefe("der Chip traegt den Dateinamen samt Endung",
               bool(_chip14) and _chip14[0][0].endswith(".jpg"), str(_chip14))
        pruefe("und KEINE Warnung, weil der Benutzer die Datei bekommt",
               not any("Konnte nicht zum Download" in m for m in s14.gesendet),
               str(s14.gesendet))

        # Gegenprobe 1: ein nicht-numerischer Zusatz ist KEIN Geschwister.
        # Ohne diese Schranke waere `bericht.pdf` -> `bericht_final.pdf` ein
        # Treffer, und das Modell liefert eine andere Datei aus als gemeint.
        (arb2 / "bericht_final.pdf").write_bytes(b"%PDF-1.4 x")
        s15 = AgentStub(EXT)
        asyncio.run(deliver2(s15, None, "Ergebnis: bericht.pdf", set(), "u", jetzt, True))
        pruefe("bericht_final.pdf gilt NICHT als Seite von bericht.pdf",
               not [m for m in s15.gesendet if "/api/documents/" in m], str(s15.gesendet))

        # Gegenprobe 1b: ein PROJEKTVERZEICHNIS-Name wird nie ueber den blossen
        # Namen ausgeliefert. Der Suchraum (`_search_dirs`) enthaelt `proj`
        # nicht – die Ortsschranke in `_liefere_namenstreffer` ist der GUERTEL
        # darunter und wird erst messbar, wenn der Suchraum sich ausweitet
        # (genau dafuer gibt es die Gegenprobe "Suchraum + Guertel weg").
        _zust = f"zustand_{uuid.uuid4().hex[:6]}.json"
        (tmpdir / _zust).write_text("{}", encoding="utf-8")
        s15b = AgentStub(EXT)
        asyncio.run(deliver2(s15b, None, f"Ergebnis: {_zust}", set(), "u", jetzt, True))
        pruefe("ein Name aus dem Projektverzeichnis wird nicht ausgeliefert",
               not [m for m in s15b.gesendet if "/api/documents/" in m],
               str(s15b.gesendet))

        # Gegenprobe 2: ein Geschwister aus einem FRUEHEREN Lauf bleibt liegen.
        # Das Arbeitsverzeichnis haengt am BENUTZER und ueberlebt Stunden – dort
        # liegen auch die Zwischenprodukte von vorhin.
        _alt_g = arb2 / "vormittag-1.csv"
        _alt_g.write_text("a;b\n", encoding="utf-8")
        os.utime(_alt_g, (time.time() - 9000, time.time() - 9000))
        s16 = AgentStub(EXT)
        asyncio.run(deliver2(s16, None, "Ergebnis: vormittag.csv", set(), "u", jetzt, True))
        pruefe("ein Geschwister aus einem frueheren Lauf wird nicht ausgeliefert",
               not [m for m in s16.gesendet if "/api/documents/" in m], str(s16.gesendet))

        # Gegenprobe 3 – DER ENGERE SUCHRAUM: Geschwister werden NUR in den
        # Arbeitswurzeln gesucht, nicht im gemeinsamen /tmp. Der Zweig raet ueber
        # einen Namen; das Register fuehrt genau dafuer den Verzicht auf einen
        # "dann im echten /tmp suchen"-Rueckfall (Dateinamen sind ratbar).
        _gemeinsam = Path("/tmp") / f"gemeinsam_{uuid.uuid4().hex[:6]}"
        _gem_datei = Path(str(_gemeinsam) + "-1.png")
        _gem_datei.write_bytes(b"\x89PNG" + b"x" * 32)
        aufraeumen.append(_gem_datei)
        s17 = AgentStub(EXT)
        asyncio.run(deliver2(s17, None, f"Ergebnis: {_gemeinsam.name}.png", set(), "u", jetzt, True))
        pruefe("im gemeinsamen /tmp wird NICHT nach Geschwistern geraten",
               not [m for m in s17.gesendet if "/api/documents/" in m], str(s17.gesendet))
        # Positivkontrolle dazu: DERSELBE Name im Arbeitsverzeichnis wird
        # geliefert. Ohne sie wuerde die Pruefung oben auch gruen bleiben, wenn
        # der ganze Geschwister-Zweig kaputt waere.
        (arb2 / (_gemeinsam.name + "-1.png")).write_bytes(b"\x89PNG" + b"x" * 32)
        s18 = AgentStub(EXT)
        asyncio.run(deliver2(s18, None, f"Ergebnis: {_gemeinsam.name}.png", set(), "u", jetzt, True))
        pruefe("im Arbeitsverzeichnis dagegen schon (Positivkontrolle)",
               [m for m in s18.gesendet if "/api/documents/" in m], str(s18.gesendet))

        # Mehrere Seiten: alle, aber gedeckelt – und der Deckel wird GENANNT.
        _deckel = int(re.search(r"_SEITEN_DECKEL\s*=\s*(\d+)", QUELLE).group(1))
        _stamm = f"mehrseitig_{uuid.uuid4().hex[:6]}"
        for i in range(1, _deckel + 3):
            (arb2 / f"{_stamm}-{i}.jpg").write_bytes(b"\xff\xd8\xff" + bytes([i]))
        s19 = AgentStub(EXT)
        asyncio.run(deliver2(s19, None, f"Ergebnis: {_stamm}.jpg", set(), "u", jetzt, True))
        _chips19 = [m for m in s19.gesendet if "/api/documents/" in m]
        pruefe(f"mehrere Seiten: genau {_deckel} Chips (Deckel greift)",
               len(_chips19) == _deckel, f"{len(_chips19)} Chips")
        # KEIN Index-Zugriff ohne Laengenpruefung: `_chips19[0]` WIRFT, wenn
        # nichts geliefert wurde – der Lauf endete dann ohne Bilanzzeile und war
        # von "nicht gelaufen" nicht zu unterscheiden. Genau so haben zwei
        # Gegenproben zuerst ausgesehen (Register: nie `[1]` in einer Pruefung).
        pruefe("die erste Seite ist dabei und die Reihenfolge ist numerisch",
               len(_chips19) >= 2 and f"{_stamm}-1." in _chips19[0]
               and f"{_stamm}-2." in _chips19[1],
               str(_chips19[:3]))
        pruefe("was der Deckel abschneidet, wird dem Benutzer GENANNT",
               any(str(_deckel + 2) in m and "Seiten" in m for m in s19.dauerhaft),
               str(s19.dauerhaft))

        abschnitt("12) Blosser Name, nichts geliefert -> MELDUNG statt Stille")
        # Lauf 2 des gemeldeten Vorfalls: 0 Schritte, das Modell behauptete nur
        # "ist nun ueber den untenstehenden Download-Chip verfuegbar". Zweig (b)
        # hat dort gewarnt, weil ein PFAD im Text stand. Nennt das Modell nur den
        # NAMEN (Lauf 1), gab es bis 2026-10-06 keine einzige Spur.
        _fehlt = f"niemals_{uuid.uuid4().hex[:6]}.xlsx"
        s20 = AgentStub(EXT)
        asyncio.run(deliver2(s20, None, f"Fertig. ✅ **{_fehlt}** steht bereit.",
                             set(), "u", jetzt, True))
        pruefe("ein blosser Name ohne Datei wird gemeldet",
               any("Konnte nicht zum Download" in m and _fehlt in m for m in s20.gesendet),
               str(s20.gesendet))
        pruefe("und die Meldung ist DAUERHAFT (persist)",
               any("Konnte nicht zum Download" in m for m in s20.dauerhaft),
               "ohne persist raeumt das Frontend sie am Laufende weg")

        # Gegenprobe 1: ein Werkzeug-Ergebnis darf nichts behaupten – die Datei
        # kann einen Schritt spaeter noch entstehen.
        s21 = AgentStub(EXT)
        asyncio.run(deliver2(s21, None, f"Ich schreibe sie als {_fehlt}.",
                             set(), "u", jetzt, False))
        pruefe("ein Werkzeug-Ergebnis meldet nicht verfrueht",
               not any("Konnte nicht zum Download" in m for m in s21.gesendet),
               str(s21.gesendet))

        # Gegenprobe 2 – DIE WICHTIGSTE: der Name einer EINGABE darf nicht
        # gemeldet werden. Wer ein PDF hochlaedt und "worum geht es?" fragt,
        # bekommt eine Antwort, die die Datei beim Namen nennt, und es wird
        # voellig richtig nichts ausgeliefert. Ohne diese Schranke waere die
        # Meldung ein Dauerlaeufer im Normalbetrieb.
        _eingabe = f"untersuchung_{uuid.uuid4().hex[:6]}.pdf"
        (anh2 / f"anhang_{uuid.uuid4().hex[:12]}_{_eingabe}").write_bytes(b"%PDF-1.4 x")
        s22 = AgentStub(EXT)
        asyncio.run(deliver2(s22, None, f"Das Dokument {_eingabe} beschreibt einen Auftrag.",
                             set(), "u", jetzt, True))
        pruefe("der Name eines ANHANGS wird nicht gemeldet",
               not any("Konnte nicht zum Download" in m for m in s22.gesendet),
               str(s22.gesendet))

        # Gegenprobe 3: wurde etwas ausgeliefert, konkurriert keine Warnung mit
        # dem Ergebnis. Das ist die BENANNTE Luecke des Zweigs – ein zweiter,
        # nur mit Namen behaupteter Treffer bleibt still; den Fall deckt (b) ab,
        # sobald das Modell einen Pfad nennt. Eine Warnung neben einem fertigen
        # Chip war 2026-09-04 selbst der gemeldete Fehler.
        (arb2 / "geliefert.csv").write_text("a;b\n", encoding="utf-8")
        s23 = AgentStub(EXT)
        asyncio.run(deliver2(s23, None, f"Fertig: geliefert.csv und {_fehlt}.",
                             set(), "u", jetzt, True))
        pruefe("neben einem fertigen Chip wird nicht gewarnt",
               [m for m in s23.gesendet if "/api/documents/" in m]
               and not any("Konnte nicht zum Download" in m for m in s23.gesendet),
               str(s23.gesendet))

        abschnitt("13) Die drei verschluckten Meldungen tragen persist")
        # Geprueft wird die EIGENSCHAFT am Syntaxbaum: jeder _send_status-Aufruf,
        # dessen Text mit einem Status-Emoji BEGINNT und der highlight=True
        # setzt, muss auch persist=True setzen – sonst raeumt das Frontend ihn
        # am Laufende weg (Praefix-Regel in chat.js). Eine Textsuche nach
        # "persist" waere hier zahnlos: sie bliebe gruen, sobald irgendwo im
        # Modul das Wort steht.
        import ast as _ast

        _PRAEFIXE = tuple(re.findall(r"'([^']+)'",
                                     re.search(r"const STATUS_PREFIXES = \[([^\]]+)\]",
                                               (ROOT / "frontend" / "js" / "chat.js")
                                               .read_text(encoding="utf-8")).group(1)))
        pruefe("die Praefixliste wurde aus chat.js GELESEN, nicht abgetippt",
               len(_PRAEFIXE) >= 10 and "⚠️" in _PRAEFIXE, str(_PRAEFIXE))

        # ⚠ GEMESSEN UND KORRIGIERT: die erste Fassung dieser Regel verlangte
        # persist fuer JEDEN Emoji-Text mit highlight – und meldete damit
        # `⏳ Warte auf LLM-Antwort…` (agent.py), das transient bleiben MUSS.
        # Der Waechter hatte recht zu beissen, die Regel war falsch gefasst.
        # Die Eigenschaft ist nicht "Emoji", sondern FEHLER: ein Fehler darf
        # nicht von selbst verschwinden, ein Fortschritt schon (Register).
        # Dass es eine genannte Zwei-Element-Menge ist, ist die Schwaeche der
        # Regel – es gibt keine maschinenlesbare Quelle fuer "dieses Emoji
        # bedeutet Fehler". Beide Zeichen werden deshalb gegen chat.js
        # geprueft: wer sie dort umbenennt, bekommt hier ein FAIL statt eines
        # still blinden Waechters.
        _FEHLER_PRAEFIXE = ("⚠️", "❌")
        for _fp in _FEHLER_PRAEFIXE:
            pruefe(f"{_fp} ist in chat.js ueberhaupt ein Status-Praefix",
                   _fp in _PRAEFIXE,
                   "sonst prueft die Regel unten eine Darstellung, die es "
                   "nicht gibt")

        _ohne_persist = []
        _mit_persist = []
        for _k in _ast.walk(_ast.parse(QUELLE)):
            if not isinstance(_k, _ast.Call):
                continue
            if getattr(_k.func, "attr", "") != "_send_status":
                continue
            _kw = {k.arg: k.value for k in _k.keywords}
            if not isinstance(_kw.get("highlight"), _ast.Constant) \
                    or _kw["highlight"].value is not True:
                continue
            # Nur Aufrufe mit WOERTLICHEM Text beurteilen – bei einer Variablen
            # (`err_msg`, `_display`) ist das erste Zeichen zur Laufzeit unbekannt.
            _arg = _k.args[1] if len(_k.args) > 1 else None
            _txt = ""
            if isinstance(_arg, _ast.Constant) and isinstance(_arg.value, str):
                _txt = _arg.value
            elif isinstance(_arg, _ast.JoinedStr):
                _teile = [v.value for v in _arg.values
                          if isinstance(v, _ast.Constant) and isinstance(v.value, str)]
                _txt = _teile[0] if _teile else ""
            if not _txt.startswith(_FEHLER_PRAEFIXE):
                continue
            _hat = isinstance(_kw.get("persist"), _ast.Constant) \
                and _kw["persist"].value is True
            (_mit_persist if _hat else _ohne_persist).append(
                (_k.lineno, _txt[:48]))

        # Positivkontrolle VOR dem Urteil: findet die Messung ueberhaupt
        # Aufrufe? Ohne sie waere "keine Lueckenfaelle" trivial wahr, sobald der
        # AST-Spaziergang nichts mehr trifft (Exit 2, nicht Exit 1 – "konnte
        # nicht laufen" ist kein Befund).
        if len(_mit_persist) + len(_ohne_persist) < 3:
            print(f"\n\033[31mABBRUCH\033[0m: nur "
                  f"{len(_mit_persist) + len(_ohne_persist)} beurteilbare "
                  f"_send_status-Aufrufe gefunden – die Messung greift nicht.")
            return 2
        pruefe(f"die Messung findet {len(_mit_persist) + len(_ohne_persist)} "
               "Fehlermeldungen mit highlight", True)
        pruefe("jede davon traegt persist=True",
               not _ohne_persist,
               "ohne persist raeumt chat.js sie am Laufende weg: "
               + "; ".join(f"Zeile {z}: {t!r}" for z, t in _ohne_persist))
        # Die Gegenseite der Regel, damit sie nicht zu "alles persistieren"
        # verkommt: ein FORTSCHRITT darf transient bleiben und tut es.
        _fortschritt = [z for z in re.findall(r"_send_status\(\s*ws,\s*f?\"(⏳[^\"]*)\"",
                                              QUELLE)]
        pruefe("ein Fortschritts-Hinweis bleibt dagegen transient",
               bool(_fortschritt) and "persist" not in QUELLE[
                   QUELLE.index(_fortschritt[0]):QUELLE.index(_fortschritt[0]) + 200],
               str(_fortschritt))

        # Die Verbindung der beiden Haelften: landet das Feld ueberhaupt in der
        # Nachricht? Das AST-Urteil oben prueft die AUFRUFER, der JS-Waechter
        # baut seine Nachrichten selbst – ohne diese Pruefung konnte
        # `msg["persist"] = True` aus `_send_status` entfernt werden, ohne dass
        # eine Messung etwas sah (von einer Gegenprobe gefunden).
        class WsStub:
            def __init__(self):
                self.gesendet = []

            async def send_json(self, d):
                self.gesendet.append(d)

        class _Zustand:
            value = "BUSY"

        class StatusAgent:
            state = _Zustand()
            agent_id = "_main"
            label = "Hauptagent"
            is_sub_agent = False

        _su = {"WebSocket": object}
        exec(hole("_send_status"), _su)
        _ws = WsStub()
        asyncio.run(_su["_send_status"](StatusAgent(), _ws, "⚠️ x",
                                        highlight=True, persist=True))
        asyncio.run(_su["_send_status"](StatusAgent(), _ws, "⏳ y", highlight=True))
        pruefe("_send_status legt persist WIRKLICH in die Nachricht",
               len(_ws.gesendet) == 2 and _ws.gesendet[0].get("persist") is True,
               str(_ws.gesendet))
        pruefe("und laesst es weg, wenn es nicht verlangt war",
               len(_ws.gesendet) == 2 and "persist" not in _ws.gesendet[1],
               str(_ws.gesendet))

        # Und die Gegenseite: chat.js MUSS persist vor der Praefix-Regel
        # auswerten. Gemessen an der Reihenfolge im Quelltext – eine Pruefung
        # auf das Vorkommen von "persist" waere blind dagegen, dass der Block
        # hinter `isStatus` steht und damit nie greift.
        _cjs = (ROOT / "frontend" / "js" / "chat.js").read_text(encoding="utf-8")
        _i_persist = _cjs.find("msg.persist")
        _i_praefix = _cjs.find("msg.highlight && !isStatus")
        pruefe("chat.js entscheidet persist VOR der Praefix-Regel",
               0 < _i_persist < _i_praefix,
               f"persist@{_i_persist} praefix@{_i_praefix}")

    print(f"\n{ok} ok, {fehler} Fehler ({ok + fehler} Pruefungen)")
    return 1 if fehler else 0


def aufraeumen_jetzt():
    """Die Proben-Dateien im echten /tmp entfernen – AUCH nach einer Ausnahme.

    ⚠ Die Schleife stand bis 2026-10-06 am Ende von ``main()``, also HINTER
    allen Pruefungen: jeder unerwartete Abbruch liess die Dateien liegen. Beim
    Bau der Gegenproben waren nach 26 sabotierten Laeufen 43 Leichen in /tmp
    (``alt_*.csv``, ``cfg_*.env`` …). Register: ein Test, der in den echten
    Bestand schreibt, raeumt am ENDE auf, nicht hinter den Pruefungen.
    Ein ``kill -9`` fuehrt das trotzdem nicht aus – die Namen tragen deshalb
    eine Zufallskennung und koennen sich nie gegenseitig treffen.
    """
    for f in AUFRAEUMEN:
        try:
            f.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        aufraeumen_jetzt()
