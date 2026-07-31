#!/usr/bin/env python3
"""Fehlgeschlagene Dateien bei der Indizierung: Namen und Grund statt „siehe Journal".

DER GEMELDETE FALL: Die Oberflaeche zeigte „4 Datei(en) fehlgeschlagen – siehe
Journal". Der Verweis war doppelt unbrauchbar:

  1. An das Journal kommt man ueber die Weboberflaeche gar nicht heran.
  2. Die Namen standen dort NICHT EINMAL DRIN. Nachgemessen auf ECHT: das
     gesamte Journal enthaelt null Zeilen der `jarvis.*`-Logger. Ursache war
     eine fehlende Logging-Konfiguration – ohne sie nutzt Python den
     "handler of last resort", der erst ab WARNING schreibt, und der
     haeufigste Zweig der Indizierung protokollierte mit `_log.info`.

Ein Verweis auf eine Quelle, die der Leser nicht erreicht UND die die
Information nicht enthaelt, ist schlimmer als gar keiner.

Lauf:  python3 tests/test_index_failures.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ergebnis = []


def pruefe(name, bedingung, detail=""):
    ergebnis.append((name, bool(bedingung)))
    print(("  ✅ " if bedingung else "  ❌ ") + name + ("" if bedingung or not detail else f" – {detail}"))


def abschnitt(t):
    print("\n" + t)


def main():
    print("=" * 70)
    print("Indizierung: welche Dateien sind gescheitert und warum")
    print("=" * 70)

    from backend.tools import knowledge as K

    tmp = Path(tempfile.mkdtemp(prefix="jarvis_fail_"))
    try:
        abschnitt("1. Grund-Ermittlung – handlungsleitend, nicht kryptisch")
        leer = tmp / "leer.txt"
        leer.write_bytes(b"")
        pruefe("leere Datei wird als solche benannt",
               "leer" in K._unlesbar_grund(leer, 10_000_000).lower(),
               K._unlesbar_grund(leer, 10_000_000))

        gross = tmp / "gross.txt"
        gross.write_bytes(b"x" * 5000)
        g = K._unlesbar_grund(gross, 1000)
        pruefe("zu grosse Datei nennt beide Groessen", "zu gross" in g and "MB" in g, g)
        pruefe("und sagt, WO man das Limit aendert",
               "Einstellungen" in g, g)

        fremd = tmp / "datei.xyz"
        fremd.write_bytes(b"abc")
        pruefe("unbekanntes Format wird benannt",
               ".xyz" in K._unlesbar_grund(fremd, 10_000_000),
               K._unlesbar_grund(fremd, 10_000_000))

        ohne = tmp / "dateiohneendung"
        ohne.write_bytes(b"abc")
        pruefe("fehlende Endung wird benannt",
               "endung" in K._unlesbar_grund(ohne, 10_000_000).lower(),
               K._unlesbar_grund(ohne, 10_000_000))

        pdf = tmp / "kaputt.pdf"
        pdf.write_bytes(b"nicht wirklich ein PDF")
        gp = K._unlesbar_grund(pdf, 10_000_000)
        pruefe("kaputtes PDF nennt die moeglichen Ursachen",
               "PDF" in gp and ("beschaedigt" in gp or "passwort" in gp.lower()), gp)
        pruefe("und nennt OCR als Abhilfe bei Scans", "tesseract" in gp, gp)

        weg = tmp / "gibtsnicht.txt"
        pruefe("verschwundene Datei stuerzt nicht ab",
               isinstance(K._unlesbar_grund(weg, 10_000_000), str))

        abschnitt("2. Erfassung im Fortschritt")
        K._set_progress(failed=0, failed_list=[])
        K._note_failed(str(tmp / "a.pdf"), "PDF nicht lesbar")
        K._note_failed(str(tmp / "b.docx"), "zu gross")
        p = K.get_index_progress()
        pruefe("beide Eintraege erfasst", len(p.get("failed_list", [])) == 2,
               str(p.get("failed_list")))
        pruefe("Eintrag hat Datei UND Grund",
               all(set(x) >= {"file", "reason"} for x in p["failed_list"]),
               str(p["failed_list"]))
        pruefe("Grund ist nicht leer", all(x["reason"] for x in p["failed_list"]))

        abschnitt("3. Deckel – ein totes Netzlaufwerk darf die Antwort nicht sprengen")
        K._set_progress(failed=0, failed_list=[])
        for i in range(K.MAX_FAILED_LIST + 25):
            K._note_failed(str(tmp / f"f{i}.txt"), "Grund")
        n = len(K.get_index_progress()["failed_list"])
        pruefe(f"hoechstens {K.MAX_FAILED_LIST} Eintraege", n == K.MAX_FAILED_LIST, str(n))

        abschnitt("4. Ein neuer Lauf zeigt nicht die Fehler des alten")
        # Ohne das Leeren steht beim naechsten Lauf noch der Altbestand da und
        # der Admin sucht Dateien, die laengst in Ordnung sind.
        import inspect
        quelle = inspect.getsource(K._do_force_reindex)
        pruefe("Lauf-Start setzt failed_list zurueck", "failed_list=[]" in quelle)
        pruefe("Liste wandert ins Ergebnis", 'result["failed_list"]' in quelle)
        pruefe("Liste wird persistiert", '"failed_list": failed_list' in quelle)

        abschnitt("5. Die Oberflaeche zeigt es dort, wo die Meldung steht")
        js = (Path(__file__).resolve().parent.parent / "frontend/js/knowledge.js").read_text(encoding="utf-8")
        pruefe("Frontend liest failed_list", "failed_list" in js)
        pruefe("und rendert einen Aufklapper", "kb-failed" in js and "<details" in js)
        pruefe("Dateinamen werden escaped (kommen aus dem Dateisystem)",
               "_esc(f.file" in js)
        i18n = (Path(__file__).resolve().parent.parent / "frontend/js/i18n.js").read_text(encoding="utf-8")
        pruefe("Meldung verweist NICHT mehr blind aufs Journal",
               "fehlgeschlagen – siehe Journal" not in i18n)
        for k in ("knowledge.index_failed_show", "knowledge.index_failed_more"):
            pruefe(f"i18n-Schluessel {k} in DE und EN",
                   i18n.count(f"'{k}'") == 2, str(i18n.count(f"'{k}'")))

        abschnitt("6. Logging schreibt jetzt ueberhaupt etwas")
        # Die zweite Ursache: ohne Konfiguration verwirft Python alles unter
        # WARNING. Ein `_log.info` war damit im gesamten Backend wirkungslos.
        hauptdatei = (Path(__file__).resolve().parent.parent / "backend/main.py").read_text(encoding="utf-8")
        pruefe("basicConfig vorhanden", "logging.basicConfig(" in hauptdatei)
        pruefe("mit force=True (uvicorn setzt sonst eigene Handler)",
               "force=True" in hauptdatei)
        pruefe("Level ueber Umgebungsvariable steuerbar",
               "JARVIS_LOG_LEVEL" in hauptdatei)
        pruefe("Fremdbibliotheken gedaempft (httpx protokolliert sonst jede LLM-Anfrage)",
               '"httpx"' in hauptdatei and "setLevel(logging.WARNING)" in hauptdatei)
        # Der Indizierungs-Zweig darf nicht mehr auf INFO stehen: genau dort
        # gingen die vier Meldungen verloren.
        kq = inspect.getsource(K._rebuild_vector_index)
        pruefe("Nicht-lesbar-Meldung protokolliert als WARNING, nicht INFO",
               'Nicht lesbar' in kq and '_log.info("Nicht lesbar' not in kq)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = sum(1 for _, g in ergebnis if g)
    print("\n" + "=" * 70)
    print(f"ERGEBNIS: {ok}/{len(ergebnis)} Pruefungen bestanden")
    print("=" * 70)
    for name, g in ergebnis:
        if not g:
            print("  FEHLGESCHLAGEN: " + name)
    return ok == len(ergebnis)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
