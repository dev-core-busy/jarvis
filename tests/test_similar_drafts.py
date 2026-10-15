#!/usr/bin/env python3
"""Dubletten-/Widerspruchs-Hinweis beim Freigeben eines Entwurfs.

DAS PROBLEM: Beim Freigeben in /wissen prueft nichts, ob dieselbe Aussage schon
im Bestand steht. Ueber die Zeit sammeln sich mehrere Fassungen; die Suche
liefert dann beide, und das Modell entscheidet unbegruendet, welcher es glaubt.

WARUM NUR EIN HINWEIS UND KEINE AUTOMATIK: Ob zwei aehnliche Aussagen eine
Dublette, eine Praezisierung oder ein echter Widerspruch sind, entscheidet der
Inhalt – nicht die Distanz. Der Mensch prueft ohnehin schon; er braucht die
Information, nicht eine Entscheidung.

DER RELATIVE SCHNITT IST DER KERN. Am Echt-Index gemessen: ein woertlich
uebernommener Chunk fand sich mit 0.931 – daneben drei thematisch fremde mit
0.868-0.871, alle ueber der absoluten Schwelle. e5 komprimiert Cosine auf
~0.83-0.93, deshalb trennt nur der ABSTAND zum Spitzenwert. Ohne den Schnitt
besteht die Warnung zu drei Vierteln aus Beifang – und wird weggeklickt.

Lauf:  python3 tests/test_similar_drafts.py
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


BESTAND = {
    "urlaub.md": (
        "Urlaubsantrag stellen. Der Urlaubsantrag wird im Personalportal unter "
        "Abwesenheiten erfasst. Die Genehmigung erfolgt durch die direkte "
        "Fuehrungskraft. Resturlaub verfaellt am 31. Maerz des Folgejahres."
    ),
    "drucker.md": (
        "Drucker einrichten. Waehlen Sie unter Einstellungen den Punkt Drucker "
        "und ordnen Sie die Formulare zu. Der Standarddrucker gilt fuer alle "
        "Ausdrucke, solange nichts anderes gewaehlt wird."
    ),
    "abrechnung.md": (
        "Quartalsabschluss. Die Abrechnung wird ueber das Menue Abrechnung "
        "erstellt und an die Kassenaerztliche Vereinigung uebermittelt. Pruefen "
        "Sie zuvor die Scheine auf Vollstaendigkeit."
    ),
}


def main():
    print("=" * 70)
    print("Aehnliches Wissen beim Freigeben eines Entwurfs")
    print("=" * 70)

    try:
        from backend.tools import vector_store as VS
        from backend.tools import knowledge as K
    except Exception as e:
        print(f"\nfaiss/sentence-transformers fehlen – uebersprungen ({e})")
        return True

    tmp = Path(tempfile.mkdtemp(prefix="jarvis_sim_"))
    echt_store = K._vector_store
    try:
        vs = VS.VectorStore(tmp)
        for name, text in BESTAND.items():
            vs.add_chunks(str(tmp / name), [text], 0.0, save=False)
        K._vector_store = vs          # Singleton fuer den Test umbiegen
        pruefe("Bestand aufgebaut", vs.chunk_count() == len(BESTAND), str(vs.chunk_count()))

        abschnitt("1. Echte Dublette wird gefunden")
        dublette = {
            "title": "Urlaub beantragen",
            "summary": ("Der Urlaubsantrag wird im Personalportal unter Abwesenheiten "
                        "erfasst. Die Genehmigung erfolgt durch die Fuehrungskraft."),
            "facts": [], "qa_pairs": [],
        }
        r = K.find_similar_existing(dublette)
        pruefe("mindestens ein Treffer", len(r["items"]) >= 1, str(r))
        pruefe("und zwar das richtige Dokument",
               r["items"] and "urlaub" in r["items"][0]["file"], str(r["items"][:1]))
        pruefe("Treffer nennt die Fundstelle im Entwurf",
               r["items"] and r["items"][0]["matched"] in ("Titel", "Zusammenfassung", "Fakt", "Frage"),
               str(r["items"][:1]))
        pruefe("Treffer bringt einen Textausschnitt mit",
               r["items"] and len(r["items"][0]["text"]) > 20)

        abschnitt("2. Neues Thema schlaegt NICHT an")
        neu = {
            "title": "Spareribs grillen",
            "summary": ("Spareribs drei Stunden bei 120 Grad im Smoker garen, danach "
                        "mit Barbecue-Sauce bestreichen und karamellisieren lassen."),
            "facts": ["Kerntemperatur 92 Grad"],
            "qa_pairs": [{"question": "Wie lange garen Spareribs?", "answer": "Etwa drei Stunden."}],
        }
        r2 = K.find_similar_existing(neu)
        pruefe("keine Treffer bei fremdem Thema", len(r2["items"]) == 0, str(r2["items"][:2]))
        pruefe("es wurde trotzdem gesucht", r2["checked"] >= 3, str(r2["checked"]))

        abschnitt("3. Der relative Schnitt haelt die Liste sauber")
        # OHNE Schnitt kommen bei e5 auch unbeteiligte Chunks knapp ueber die
        # absolute Schwelle. Gegenprobe: Schnitt ausschalten und vergleichen.
        alt = K.AEHNLICH_REL
        K.AEHNLICH_REL = 0.0
        try:
            ohne = K.find_similar_existing(dublette)
        finally:
            K.AEHNLICH_REL = alt
        mit = K.find_similar_existing(dublette)
        pruefe("Schnitt entfernt schwaechere Treffer",
               len(mit["items"]) <= len(ohne["items"]),
               f"mit={len(mit['items'])} ohne={len(ohne['items'])}")
        pruefe("der beste Treffer bleibt erhalten",
               mit["items"] and ohne["items"]
               and mit["items"][0]["file"] == ohne["items"][0]["file"])
        pruefe("alle verbliebenen liegen nah am Besten",
               all(x["score"] >= mit["items"][0]["score"] * K.AEHNLICH_REL for x in mit["items"]),
               str([x["score"] for x in mit["items"]]))

        abschnitt("4. Gelernte Notizen sind ausgeschlossen")
        # Sie tragen die Benutzerfrage als Ueberschrift und waeren fuer eine
        # Q&A-Abfrage immer der Top-Treffer – unabhaengig vom Inhalt.
        # Der Pfad MUSS /knowledge/learned/ enthalten – daran erkennt
        # _is_learned_note() sie. Ein beliebiges "learned"-Verzeichnis reicht
        # nicht (erste Testfassung lief genau hier vorbei).
        lern = tmp / "knowledge" / "learned"
        lern.mkdir(parents=True)
        vs.add_chunks(str(lern / "conv_x.md"),
                      ["Urlaubsantrag stellen. Der Urlaubsantrag wird im Personalportal "
                       "unter Abwesenheiten erfasst und von der Fuehrungskraft genehmigt."],
                      0.0, save=False)
        r3 = K.find_similar_existing(dublette)
        pruefe("gelernte Notiz taucht nicht auf",
               not any("learned" in x["file"] for x in r3["items"]),
               str([x["file"] for x in r3["items"]]))

        abschnitt("5. Robustheit")
        pruefe("leerer Entwurf wirft nicht",
               K.find_similar_existing({})["items"] == [])
        pruefe("Entwurf nur mit Titel funktioniert",
               isinstance(K.find_similar_existing({"title": "Drucker"})["items"], list))
        pruefe("Deckel greift", K.AEHNLICH_GESAMT <= 10)
        # FALLSTRICK: _vector_store = None genuegt NICHT – _get_vector_store()
        # erzeugt den Store dann einfach neu. Der Zugriff selbst muss ausfallen.
        echt_get = K._get_vector_store
        K._get_vector_store = lambda: None
        try:
            K.find_similar_existing(dublette)
            pruefe("ohne Vektor-Index klare Ausnahme", False, "keine Ausnahme")
        except RuntimeError:
            pruefe("ohne Vektor-Index klare Ausnahme", True)
        except Exception as e:
            pruefe("ohne Vektor-Index klare Ausnahme", False, repr(e))
        finally:
            K._get_vector_store = echt_get

        abschnitt("6. Verdrahtung")
        import inspect
        hauptdatei = (Path(__file__).resolve().parent.parent / "backend/main.py").read_text(encoding="utf-8")
        pruefe("Endpunkt vorhanden", "/api/wissen/pending/{doc_id}/similar" in hauptdatei)
        pruefe("Endpunkt prueft den Eigentuemer",
               "wissen_pending_similar" in hauptdatei
               and hauptdatei.split("wissen_pending_similar")[1].split("approve")[0].count("created_by") == 1)
        pruefe("Ausfall blockiert die Freigabe nicht (ok:False statt Fehlercode)",
               '"ok": False, "error": str(e)[:200], "items": []' in hauptdatei)
        js = (Path(__file__).resolve().parent.parent / "frontend/js/wissen.js").read_text(encoding="utf-8")
        pruefe("Frontend laedt nach", "loadSimilar" in js and "/similar" in js)
        pruefe("Anzeige steht ueber den Knoepfen",
               js.index("wi-rev-similar") < js.index("wi-rev-approve"))
        pruefe("verspaetete Antwort eines anderen Entwurfs wird verworfen",
               "_revId !== id" in js)
        i18n = (Path(__file__).resolve().parent.parent / "frontend/js/i18n.js").read_text(encoding="utf-8")
        for k in ("wissen.similar_checking", "wissen.similar_found", "wissen.similar_hint"):
            pruefe(f"i18n {k} in DE und EN", i18n.count(f"'{k}'") == 2, str(i18n.count(f"'{k}'")))

    finally:
        K._vector_store = echt_store
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
