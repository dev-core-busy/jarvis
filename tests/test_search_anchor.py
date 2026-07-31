#!/usr/bin/env python3
"""Lexikalischer Anker: Kennzeichnung schwacher Treffer statt stiller Auffuellung.

DER BEFUND, DER DAS AUSGELOEST HAT (gemessen am Echt-Index, 9207 Chunks):
Die hybride Suche hatte KEINEN absoluten Qualitaetsboden – `MIN_SCORE` wird dort
gar nicht angewandt, der Score ist ein auf 1.0 normierter RRF-Rang, der Top-Treffer
also IMMER 1.00. `MIN_KEEP = 3` erzwang drei Treffer, egal wie sinnlos die Anfrage.

Ein Cosine-Boden waere das naheliegende Gegenmittel und ist NACHWEISLICH FALSCH:

    Gruppe                             bester Cosine
    echte Fachfragen                   0.8434 - 0.8984
    sinnvolle Fragen, falsches Thema   0.7931 - 0.8258
    ZEICHENSALAT                       0.8210 - 0.8644   <-- schlaegt echte Fragen

`qqq www eee rrr ttt` erreicht 0.8644 und liegt damit ueber drei echten Fachfragen.
e5 legt bedeutungslose Zeichenfolgen in eine generische Region, die zu allem
maessig aehnlich ist.

Was TRENNT, ist die blosse EXISTENZ eines BM25-Treffers:
    echte Fragen 0/12 ohne, falsches Thema 0/8 ohne, englisch 0/5 ohne,
    kurze Anfragen 0/4 ohne  -- Zeichensalat 5/6 OHNE.

Das Signal hat aber einen gemessenen FEHLALARM: "patiententen anlgen" (zwei
Tippfehler) hat ebenfalls keinen Anker. Deshalb wird NICHT unterdrueckt, sondern
gekennzeichnet – und nicht auf drei Treffer aufgefuellt.

Lauf:  python3 tests/test_search_anchor.py
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


DOKUMENTE = {
    "handbuch.md": (
        "Patientenverwaltung. Um einen neuen Patienten anzulegen, oeffnen Sie die "
        "Stammdaten und waehlen Neu. Tragen Sie Name, Geburtsdatum und Versicherung ein. "
        "Die Patientenakte wird automatisch angelegt und erhaelt eine Nummer."
    ),
    "abrechnung.md": (
        "Abrechnung und Quartalsabschluss. Der Quartalsabschluss erfolgt ueber das Menue "
        "Abrechnung. Pruefen Sie zuvor die Scheine auf Vollstaendigkeit. Die Abrechnung "
        "wird anschliessend an die Kassenaerztliche Vereinigung uebermittelt."
    ),
    "drucker.md": (
        "Drucker einrichten. Waehlen Sie unter Einstellungen den Punkt Drucker. "
        "Dort koennen Sie Formulare zuordnen und den Standarddrucker festlegen. "
        "Bei Problemen pruefen Sie die Warteschlange."
    ),
}


def main():
    print("=" * 70)
    print("Lexikalischer Anker in der Hybridsuche")
    print("=" * 70)

    try:
        from backend.tools import vector_store as VS
    except Exception as e:
        print(f"\nfaiss/sentence-transformers nicht verfuegbar – uebersprungen ({e})")
        return True

    tmp = Path(tempfile.mkdtemp(prefix="jarvis_anker_"))
    try:
        vs = VS.VectorStore(tmp)
        for name, text in DOKUMENTE.items():
            vs.add_chunks(str(tmp / name), [text], 0.0, save=False)
        pruefe("Index aufgebaut", vs.chunk_count() == len(DOKUMENTE), str(vs.chunk_count()))

        abschnitt("1. Anker-Erkennung")
        pruefe("echte Fachfrage hat einen Anker",
               vs.has_lexical_anchor("Wie lege ich einen neuen Patienten an?") is True)
        pruefe("Abrechnungsfrage hat einen Anker",
               vs.has_lexical_anchor("Quartalsabschluss Abrechnung") is True)
        pruefe("Zeichensalat hat KEINEN Anker",
               vs.has_lexical_anchor("xyzzy plugh frobnicate") is False)
        pruefe("zweiter Zeichensalat hat KEINEN Anker",
               vs.has_lexical_anchor("asdkjhasd qwiuehqwe") is False)
        # Ein einzelnes Wort aus dem Bestand genuegt – so soll es sein.
        pruefe("ein einziges bekanntes Wort genuegt",
               vs.has_lexical_anchor("Drucker") is True)

        abschnitt("2. MIN_KEEP wird ohne Anker NICHT erzwungen")
        # Der Kern des Befunds: vorher kamen hier drei Treffer heraus, egal was
        # gefragt wurde. Das Modell baute darauf eine Antwort.
        muell = vs.search_hybrid("xyzzy plugh frobnicate", 10)
        pruefe("Zeichensalat liefert hoechstens einen Treffer",
               len(muell) <= VS.MIN_KEEP_OHNE_ANKER, f"{len(muell)} Treffer")
        echt = vs.search_hybrid("Wie lege ich einen neuen Patienten an?", 10)
        pruefe("echte Frage liefert weiterhin Treffer", len(echt) >= 1, f"{len(echt)} Treffer")
        pruefe("und zwar den richtigen",
               echt and "handbuch" in echt[0][1], echt[0][1] if echt else "-")

        abschnitt("3. Der Fehlalarm ist bewusst in Kauf genommen")
        # "patiententen anlgen" – zwei Tippfehler, kein Wort im Index. Die Anfrage
        # ist legitim. Sie DARF keine leere Antwort bekommen.
        vertippt = vs.search_hybrid("patiententen anlgen", 10)
        pruefe("stark vertippte Anfrage liefert trotzdem etwas",
               len(vertippt) >= 1, f"{len(vertippt)} Treffer")
        pruefe("Suche unterdrueckt NIE vollstaendig",
               len(muell) >= 1, "auch Muell bekommt einen Treffer, nur gekennzeichnet")

        abschnitt("4. Ohne lexikalischen Index keine Aussage")
        # Fehlt der Index, ist eine leere BM25-Liste eine Aussage ueber den INDEX,
        # nicht ueber die Anfrage. Dann darf weder gewarnt noch gekuerzt werden.
        # FALLSTRICK: _lex_postings einfach auf None zu setzen bringt nichts –
        # has_lexical_anchor ruft _ensure_lexical_index() und baut ihn sofort neu.
        # Simuliert wird deshalb der Fall, der im Betrieb wirklich auftritt: der
        # Aufbau des lexikalischen Index scheitert.
        echt_ensure = vs._ensure_lexical_index

        def kaputt():
            raise RuntimeError("BM25-Index nicht verfuegbar")

        vs._ensure_lexical_index = kaputt
        try:
            pruefe("scheiternder BM25-Index -> 'unbekannt', nicht False",
                   vs.has_lexical_anchor("xyzzy plugh") is None)
        finally:
            vs._ensure_lexical_index = echt_ensure
        pruefe("danach wieder normal", vs.has_lexical_anchor("Drucker") is True)

        abschnitt("5. Kennzeichnung im Werkzeug-Ergebnis")
        from backend.tools import knowledge as K
        liste = K._TrefferListe([(1.0, "a.md", "text")])
        pruefe("Trefferliste traegt das Merkmal", hasattr(liste, "kein_anker"))
        pruefe("Vorgabe ist False (fail-safe: keine Warnung ohne Befund)",
               liste.kein_anker is False)
        pruefe("verhaelt sich wie eine Liste", len(liste) == 1 and liste[0][1] == "a.md")
        # Der Hinweistext muss dem Modell einen AUFTRAG geben, nicht nur eine
        # Beobachtung mitteilen – sonst liefert es trotzdem eine erfundene Antwort.
        import inspect
        quelle = inspect.getsource(K.KnowledgeTool.execute)
        pruefe("Hinweis steht im Ausgabepfad", "kein_anker" in quelle)
        for satz in ("Antworte NUR", "Erfinde nichts", "einschlägig", "HINWEIS ZUR QUALITÄT"):
            pruefe(f"Hinweis enthaelt '{satz}'", satz in quelle)

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
