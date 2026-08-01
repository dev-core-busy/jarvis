#!/usr/bin/env python3
"""Abschnittsweise Extraktion: lange Dokumente vollstaendig statt nur der Anfang.

DAS PROBLEM: Der Extraktor sah nur die ersten 8000 Zeichen. Bei einem laengeren
Handbuch fiel alles danach STILL weg – das Ergebnis sah vollstaendig aus,
niemand erfuhr, dass zwei Drittel nie betrachtet wurden. Der unsichtbare Fehler
ist der schlimmere.

Es gab DREI Stellen mit `[:8000]`, jede mit eigener LLM-Logik:
  extract_structured_from_text  (Confluence, Wiederverwendung)
  extract_from_url              (HTML-Seiten)  – fast identische Kopie
  extract_from_file             (Uploads)      – nochmal
Alle drei laufen jetzt ueber EINE Funktion; nur der Bild-Pfad bleibt einstufig
(dort haengt das Bild am Aufruf, und ein Bild ist eine Seite).

Geprueft wird mit einem STUB-Modell: die Zerlegung, die Verteilung der
Fragenanzahl und die Zusammenfuehrung sind Logik, kein Modellverhalten.

Lauf:  python3 tests/test_extract_windows.py
"""
import asyncio
import sys
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
    print("Abschnittsweise Extraktion langer Dokumente")
    print("=" * 70)

    import backend.web_extractor as W

    abschnitt("1. Zerlegung in Fenster")
    kurz = "Ein kurzer Text." * 10
    pruefe("kurzer Text bleibt EIN Fenster", len(W._fenster(kurz)) == 1, str(len(W._fenster(kurz))))
    pruefe("leerer Text ergibt gar kein Fenster", W._fenster("") == [])
    pruefe("nur Leerzeichen ergibt kein Fenster", W._fenster("   \n  ") == [])

    # 40.000 Zeichen mit klaren Absaetzen
    lang = "\n\n".join(f"Abschnitt {i}. " + ("Satz zum Thema. " * 30) for i in range(90))
    f = W._fenster(lang)
    pruefe("langer Text wird zerlegt", len(f) > 1, f"{len(lang)} Zeichen -> {len(f)} Fenster")
    pruefe("kein Fenster ueberschreitet die Groesse",
           all(len(x) <= W.FENSTER_ZEICHEN for x in f), str([len(x) for x in f]))
    pruefe("Fenster ueberlappen sich",
           len(f) > 1 and sum(len(x) for x in f) > len(lang), "sonst gehen Grenzfaelle verloren")
    # Der Anfang des Dokuments muss im ersten Fenster stehen (Titelquelle).
    pruefe("erstes Fenster beginnt am Dokumentanfang", f[0].startswith("Abschnitt 0."))

    abschnitt("2. Deckel und ehrliche Meldung")
    riesig = "\n\n".join(f"Kapitel {i}. " + ("Inhalt. " * 200) for i in range(200))
    fr = W._fenster(riesig)
    pruefe(f"hoechstens MAX_FENSTER ({W.MAX_FENSTER})", len(fr) == W.MAX_FENSTER, str(len(fr)))

    abschnitt("3. Zusammenfuehrung ueber die Fenster")
    aufrufe = {"n": 0, "qa_counts": []}

    async def stub(content, fallback_title, qa_count, prof):
        aufrufe["n"] += 1
        aufrufe["qa_counts"].append(qa_count)
        i = aufrufe["n"]
        return {
            "title": f"Titel aus Fenster {i}",
            "summary": f"Zusammenfassung {i}.",
            # Fakt 1 kommt in JEDEM Fenster vor -> muss entdoppelt werden
            "facts": ["Gemeinsamer Fakt.", f"Eigener Fakt {i}."],
            "qa_pairs": [{"q": "Gemeinsame Frage?", "a": "A."},
                         {"q": f"Frage {i}?", "a": f"Antwort {i}."}],
        }

    echt = W._extract_ein_fenster
    W._extract_ein_fenster = stub
    try:
        r = asyncio.run(W.extract_structured_from_text(lang, fallback_title="Datei.pdf", qa_count=None))
    finally:
        W._extract_ein_fenster = echt

    pruefe("jedes Fenster wurde abgefragt", aufrufe["n"] == len(f), f"{aufrufe['n']} von {len(f)}")
    pruefe("Titel kommt aus dem ERSTEN Fenster", r["title"] == "Titel aus Fenster 1", r["title"])
    pruefe("alle Zusammenfassungen enthalten",
           r["summary"].count("Zusammenfassung") == len(f), r["summary"][:80])
    pruefe("gemeinsamer Fakt nur EINMAL",
           r["facts"].count("Gemeinsamer Fakt.") == 1, str(r["facts"][:4]))
    pruefe("eigene Fakten aller Fenster vorhanden",
           sum(1 for x in r["facts"] if x.startswith("Eigener Fakt")) == len(f), str(len(r["facts"])))
    pruefe("gemeinsame Frage nur EINMAL",
           sum(1 for p in r["qa_pairs"] if p["q"] == "Gemeinsame Frage?") == 1,
           str([p["q"] for p in r["qa_pairs"]][:4]))

    abschnitt("4. Abdeckung wird ausgewiesen")
    cov = r.get("coverage") or {}
    pruefe("coverage vorhanden", bool(cov), str(cov))
    pruefe("Gesamtlaenge stimmt", cov.get("chars_total") == len(lang), str(cov.get("chars_total")))
    pruefe("Fensterzahl stimmt", cov.get("windows") == len(f), str(cov.get("windows")))
    pruefe("gesehene Zeichen nicht groesser als das Dokument",
           cov.get("chars_seen", 0) <= cov.get("chars_total", 0))
    pruefe("nicht als abgeschnitten gemeldet", cov.get("truncated") is False, str(cov))

    # Und bei einem Dokument ueber dem Deckel MUSS es als abgeschnitten gelten –
    # das ist der Kern: der Verlust wird ausgewiesen statt verschwiegen.
    aufrufe["n"] = 0
    W._extract_ein_fenster = stub
    try:
        rr = asyncio.run(W.extract_structured_from_text(riesig, qa_count=None))
    finally:
        W._extract_ein_fenster = echt
    pruefe("zu langes Dokument wird als abgeschnitten gemeldet",
           (rr.get("coverage") or {}).get("truncated") is True, str(rr.get("coverage")))

    abschnitt("5. Fragenanzahl wird VERTEILT, nicht vervielfacht")
    # Ohne Verteilung liefert jedes Fenster die volle Anzahl: bei 6 Fenstern und
    # "10 Fragen" waeren es 60.
    aufrufe["n"] = 0
    aufrufe["qa_counts"] = []
    W._extract_ein_fenster = stub
    try:
        r10 = asyncio.run(W.extract_structured_from_text(lang, qa_count=10))
    finally:
        W._extract_ein_fenster = echt
    pruefe("je Fenster wurde weniger als die Gesamtzahl angefordert",
           all(c is not None and c < 10 for c in aufrufe["qa_counts"]), str(aufrufe["qa_counts"]))
    pruefe("Ergebnis ueberschreitet die Wunschzahl nicht",
           len(r10["qa_pairs"]) <= 10, str(len(r10["qa_pairs"])))

    aufrufe["n"] = 0
    W._extract_ein_fenster = stub
    try:
        r0 = asyncio.run(W.extract_structured_from_text(lang, qa_count=0))
    finally:
        W._extract_ein_fenster = echt
    pruefe("qa_count=0 liefert KEINE Fragen", r0["qa_pairs"] == [], str(r0["qa_pairs"][:2]))

    abschnitt("6. Ein gescheitertes Fenster kostet nicht das Dokument")
    zaehler = {"n": 0}

    async def stub_mit_fehler(content, fallback_title, qa_count, prof):
        zaehler["n"] += 1
        if zaehler["n"] == 2:
            raise ValueError("LLM lieferte kein gueltiges JSON")
        return {"title": "T", "summary": f"S{zaehler['n']}",
                "facts": [f"F{zaehler['n']}"], "qa_pairs": []}

    W._extract_ein_fenster = stub_mit_fehler
    try:
        rf = asyncio.run(W.extract_structured_from_text(lang, qa_count=None))
    finally:
        W._extract_ein_fenster = echt
    pruefe("Ergebnis trotz Ausfall vorhanden", bool(rf["facts"]), str(rf["facts"][:3]))
    pruefe("nur das kaputte Fenster fehlt",
           len(rf["facts"]) == len(f) - 1, f"{len(rf['facts'])} statt {len(f) - 1}")

    # Bei EINEM Fenster gibt es nichts zu retten -> die Ausnahme muss durch,
    # sonst entstuende ein leerer Entwurf ohne erkennbaren Grund.
    async def stub_immer_fehler(content, fallback_title, qa_count, prof):
        raise ValueError("kaputt")

    W._extract_ein_fenster = stub_immer_fehler
    try:
        asyncio.run(W.extract_structured_from_text(kurz, qa_count=None))
        pruefe("einzelnes Fenster: Ausnahme kommt durch", False, "keine Ausnahme")
    except ValueError:
        pruefe("einzelnes Fenster: Ausnahme kommt durch", True)
    finally:
        W._extract_ein_fenster = echt

    abschnitt("7. Keine abschneidende Kopie mehr im Code")
    quelle = (Path(__file__).resolve().parent.parent / "backend/web_extractor.py").read_text(encoding="utf-8")
    # Nur noch der Bild-Pfad darf deckeln (ein Bild ist eine Seite).
    treffer = [z.strip() for z in quelle.splitlines()
               if "[:8000]" in z and not z.strip().startswith("#")]
    pruefe("hoechstens eine deckelnde Stelle (Bild-Pfad)", len(treffer) <= 1, str(treffer))
    pruefe("URL-Pipeline nutzt die gemeinsame Funktion",
           quelle.count("await extract_structured_from_text(") >= 3,
           str(quelle.count("await extract_structured_from_text(")))
    js = (Path(__file__).resolve().parent.parent / "frontend/js/wissen.js").read_text(encoding="utf-8")
    pruefe("Oberflaeche zeigt die Abdeckung", "coverage_partial" in js and "covHtml" in js)
    i18n = (Path(__file__).resolve().parent.parent / "frontend/js/i18n.js").read_text(encoding="utf-8")
    for k in ("wissen.coverage_partial", "wissen.coverage_full"):
        pruefe(f"i18n {k} in DE und EN", i18n.count(f"'{k}'") == 2, str(i18n.count(f"'{k}'")))

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
