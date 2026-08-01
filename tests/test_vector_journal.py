#!/usr/bin/env python3
"""Gedrosseltes Speichern gelernter Notizen mit Journal (B-7).

DAS PROBLEM: Jede gelernte Notiz schrieb den KOMPLETTEN FAISS-Index und die
vollstaendigen Metadaten neu – bei 16.000 Chunks rund 50 MB fuer ein paar
hundert Byte neuen Inhalt.

DER ZIELKONFLIKT: Blosses Entprellen spart die Schreiblast, oeffnet aber ein
Fenster – stirbt der Prozess dazwischen, sind die Notizen weg. Deshalb geht
jede Notiz SOFORT in ein winziges Journal und wird beim Start eingespielt.
Gespart wird die teure Serialisierung, NICHT die Dauerhaftigkeit.

DER KERN DIESES TESTS ist Abschnitt 3: der Absturz wird ECHT nachgestellt
(Objekt wegwerfen, aus den Dateien neu laden), nicht simuliert. Ein Test, der
nur prueft "Journal-Datei existiert", wuerde die eine Frage nicht beantworten,
auf die es ankommt – ob die Notiz nach einem Absturz wieder da ist.

Lauf:  python3 tests/test_vector_journal.py
"""
import json
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
    print("Journal fuer gelernte Notizen")
    print("=" * 70)

    try:
        from backend.tools import vector_store as VS
    except Exception as e:
        print(f"\nfaiss/sentence-transformers fehlen – uebersprungen ({e})")
        return True

    tmp = Path(tempfile.mkdtemp(prefix="jarvis_journal_"))
    try:
        vs = VS.VectorStore(tmp)
        journal = tmp / VS.VectorStore.JOURNAL_NAME
        idx = tmp / "faiss_index.bin"

        abschnitt("1. Notiz ist sofort suchbar, ohne den Index zu schreiben")
        geschrieben = vs.add_chunks_deferred(str(tmp / "notiz1.md"),
                                             ["Der Urlaubsantrag laeuft ueber das Personalportal."],
                                             1.0, max_eintraege=5, max_alter_s=9999)
        pruefe("noch nicht vollstaendig gespeichert", geschrieben is False)
        pruefe("Journal wurde geschrieben", journal.exists())
        pruefe("Chunk ist im Speicher-Index", vs.chunk_count() == 1, str(vs.chunk_count()))
        treffer = vs.search("Wie beantrage ich Urlaub?", 3)
        pruefe("und sofort auffindbar", len(treffer) >= 1, str(len(treffer)))
        # DAS ist der eingesparte Aufwand: das Journal ist winzig gegen den Index.
        j_gross = journal.stat().st_size
        pruefe("Journalzeile ist klein (< 2 KB)", j_gross < 2048, f"{j_gross} Byte")

        abschnitt("2. Nach genug Eintraegen wird gebuendelt gespeichert")
        for i in range(2, 5):
            r = vs.add_chunks_deferred(str(tmp / f"notiz{i}.md"), [f"Notiz {i} Inhalt."],
                                       float(i), max_eintraege=5, max_alter_s=9999)
            pruefe(f"Notiz {i}: noch kein Vollspeichern", r is False)
        r5 = vs.add_chunks_deferred(str(tmp / "notiz5.md"), ["Notiz 5 Inhalt."], 5.0,
                                    max_eintraege=5, max_alter_s=9999)
        pruefe("fuenfte Notiz loest das Speichern aus", r5 is True)
        pruefe("Journal danach geleert", not journal.exists())
        pruefe("Index liegt auf Platte", idx.exists())

        abschnitt("3. ABSTURZ – der eigentliche Nachweis")
        # Nach dem Flush oben ist alles gesichert. Jetzt zwei Notizen NUR ins
        # Journal, dann das Objekt wegwerfen und neu aus den Dateien laden –
        # so, wie es nach einem OOM-Kill oder Stromausfall aussieht.
        vs.add_chunks_deferred(str(tmp / "verloren1.md"),
                               ["Das Notfallkennwort lautet Blaufisch."], 10.0,
                               max_eintraege=99, max_alter_s=9999)
        vs.add_chunks_deferred(str(tmp / "verloren2.md"),
                               ["Der Serverraum ist im zweiten Stock."], 11.0,
                               max_eintraege=99, max_alter_s=9999)
        vorher = vs.chunk_count()
        pruefe("beide Notizen im Speicher", vorher == 7, str(vorher))
        pruefe("Journal haelt sie fest", journal.exists())

        del vs                                   # <- der "Absturz"
        neu = VS.VectorStore(tmp)                # aus den Dateien neu laden
        pruefe("nach dem Neustart fehlen sie zunaechst",
               neu.chunk_count() == 5, str(neu.chunk_count()))
        pruefe("das Journal liegt aber noch da", journal.exists())

        n = neu.replay_journal()
        pruefe("Wiedereinspielen meldet zwei Notizen", n == 2, str(n))
        pruefe("Chunks wieder vollstaendig", neu.chunk_count() == 7, str(neu.chunk_count()))
        tr = neu.search("Wie lautet das Notfallkennwort?", 3)
        pruefe("die verlorene Notiz ist wieder auffindbar",
               any("Blaufisch" in t[2] for t in tr), str([t[1] for t in tr]))
        pruefe("Journal nach dem Einspielen geleert", not journal.exists())

        abschnitt("4. Kein doppeltes Einspielen")
        # Das Journal kann Zeilen enthalten, die es noch in den letzten
        # Speichervorgang geschafft haben. Die duerfen nicht doppelt landen.
        neu.add_chunks_deferred(str(tmp / "doppelt.md"), ["Inhalt."], 20.0,
                                max_eintraege=99, max_alter_s=9999)
        neu.flush_pending()                       # jetzt im Index UND (nicht mehr) im Journal
        # Journal von Hand mit genau diesem Eintrag befuellen
        journal.write_text(json.dumps({"file_path": str(tmp / "doppelt.md"), "mtime": 20.0,
                                       "chunks": ["Inhalt."]}) + "\n", encoding="utf-8")
        vorher2 = neu.chunk_count()
        n2 = neu.replay_journal()
        pruefe("bereits vorhandener Eintrag wird uebersprungen", n2 == 0, str(n2))
        pruefe("Chunkzahl unveraendert", neu.chunk_count() == vorher2, str(neu.chunk_count()))

        abschnitt("5. Robustheit")
        journal.write_text("das ist kein json\n{kaputt\n", encoding="utf-8")
        try:
            n3 = neu.replay_journal()
            pruefe("kaputte Journalzeilen stuerzen nicht ab", n3 == 0, str(n3))
        except Exception as e:
            pruefe("kaputte Journalzeilen stuerzen nicht ab", False, repr(e))
        pruefe("kaputtes Journal wird entfernt", not journal.exists())
        pruefe("fehlendes Journal ist kein Fehler", neu.replay_journal() == 0)
        pruefe("flush ohne offene Eintraege tut nichts", neu.flush_pending() is False)
        pruefe("leere Chunkliste entfernt die Datei statt zu journalisieren",
               neu.add_chunks_deferred(str(tmp / "leer.md"), [], 1.0) is False
               and not journal.exists())

        abschnitt("6. Verdrahtung")
        lern = (Path(__file__).resolve().parent.parent / "backend/learning.py").read_text(encoding="utf-8")
        pruefe("learning.py nutzt den gedrosselten Pfad", "add_chunks_deferred" in lern)
        pruefe("und nicht mehr den vollen", "vs.add_chunks(str(filepath)" not in lern)
        hauptdatei = (Path(__file__).resolve().parent.parent / "backend/main.py").read_text(encoding="utf-8")
        pruefe("Start-Hook spielt das Journal ein", "replay_journal" in hauptdatei)
        pruefe("Shutdown-Hook sichert es", "flush_pending" in hauptdatei)
        # Reihenfolge: erst Index schreiben, dann Journal leeren. Andersherum
        # waere ein Absturz dazwischen genau der Verlust, den das Journal
        # verhindern soll.
        quelle = (Path(__file__).resolve().parent.parent / "backend/tools/vector_store.py").read_text(encoding="utf-8")
        block = quelle.split("def flush_pending")[1].split("def replay_journal")[0]
        pruefe("flush schreibt ZUERST den Index, dann das Journal",
               block.index("self._save()") < block.index("unlink"))
        pruefe("Journal wird mit fsync geschrieben", "os.fsync" in quelle)

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
