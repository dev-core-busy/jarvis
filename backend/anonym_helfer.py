"""Hilfsprozess fuer ``backend/anonymisieren.py``: Namen (Presidio) und Gesichter (YuNet).

WARUM EIN EIGENER PROZESS (Entscheidung des Betreibers, 2026-10-27)
==================================================================
Presidio mit dem spaCy-Modell ``de_core_news_md`` belegt gemessen rund 760 MB
(DEV, RSS nach dem ersten Lauf). Python gibt diesen Speicher nicht verlaesslich
an das System zurueck – im Dienstprozess waere er bis zum naechsten Neustart weg,
auch wenn niemand je wieder anonymisiert. Dieser Prozess wird beim ersten
Gebrauch gestartet und vom Dienst nach einer Leerlauffrist beendet; dann ist der
Speicher wirklich frei.

⚠ KEIN IMPORT AUS ``backend``. Der Prozess wird mit ``python -I <datei>``
gestartet (isoliert: kein PYTHONPATH, kein Arbeitsverzeichnis im Suchpfad) und
soll ohne den Backend-Stack laufen. ``backend.config`` zu importieren hiesse
ausserdem, die Live-``settings.json`` aus einem zweiten Prozess anzufassen.

PROTOKOLL – eine JSON-Zeile je Anfrage auf stdin, eine je Antwort auf stdout:
  Start:  {"bereit": true, "personen": bool, "gesichter": bool, "fehler": {...}}
  {"op": "personen", "text": "..."}  -> {"ok": true, "treffer": [{"start","end","typ","score"}]}
  {"op": "gesichter", "pfad": "..."} -> {"ok": true, "boxen": [[x, y, w, h, score], ...]}
Fehlt eine Faehigkeit (Paket nicht installiert), meldet der Start das, statt zu
sterben: das Anonymisieren laeuft dann ohne diesen Teil und SAGT das.

Bilder kommen als PFAD, nicht als base64 auf der Leitung: der Dienst legt sie in
ein privates Wegwerfverzeichnis (0700) und raeumt es nach dem Lauf selbst ab.
"""

import json
import sys

# Welche Arten Presidio melden soll. ORGANIZATION und URL liefert es ebenfalls
# (gemessen am 2026-10-27) – sie sind keine personenbezogenen Daten im Sinne
# dieser Aktion: ein Firmenname im Screenshot ist meist genau der Inhalt, um den
# es geht, und eine geschwaerzte Adresszeile macht das Bild unbrauchbar.
ARTEN = ["PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "IBAN_CODE"]
# Unter diesem Wert gilt ein Treffer als Rauschen. Telefonnummern kommen mit 0,4
# (gemessen), deshalb liegt die Grenze darunter.
MIN_SCORE = 0.35
# Gesichter: Mindestwert des Detektors. Ein faelschlich verpixelter Fleck kostet
# wenig, ein uebersehenes Gesicht ist der Schaden – deshalb niedriger als die
# 0,6 der OpenCV-Beispiele.
GESICHT_SCORE = 0.5

_analyzer = None
_gesicht_modell = ""

# ⚠ stdout IST DER PROTOKOLLKANAL – und nur fuer die Antworten. Eine Bibliothek,
# die beim Laden etwas druckt (Fortschritt, Hinweise), wuerde sonst eine Zeile
# einschieben, die der Dienst als Antwort liest. Alles andere geht auf stderr
# und landet damit im Journal des Dienstes.
_KANAL = sys.stdout
sys.stdout = sys.stderr


def _antwort(obj: dict) -> None:
    _KANAL.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _KANAL.flush()


def _presidio_laden() -> str:
    """Presidio mit dem deutschen spaCy-Modell. Rueckgabe: Fehlertext oder ``""``."""
    global _analyzer
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        prov = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "de", "model_name": "de_core_news_md"}]})
        _analyzer = AnalyzerEngine(nlp_engine=prov.create_engine(),
                                   supported_languages=["de"])
        return ""
    except Exception as e:  # noqa: BLE001
        _analyzer = None
        return "%s: %s" % (type(e).__name__, str(e)[:200])


def _gesichter_laden(modell: str) -> str:
    """YuNet ueber OpenCV pruefen. Rueckgabe: Fehlertext oder ``""``."""
    global _gesicht_modell
    try:
        import os
        import cv2
        if not modell or not os.path.isfile(modell):
            return "Modelldatei fehlt: %s" % (modell or "-")
        # EIN Kern: der Dienst laeuft daneben weiter, und die Bilder sind klein.
        cv2.setNumThreads(1)
        cv2.FaceDetectorYN.create(modell, "", (320, 320), GESICHT_SCORE)
        _gesicht_modell = modell
        return ""
    except Exception as e:  # noqa: BLE001
        _gesicht_modell = ""
        return "%s: %s" % (type(e).__name__, str(e)[:200])


def personen(text: str) -> list:
    if _analyzer is None:
        raise RuntimeError("Namenserkennung nicht verfuegbar")
    if not text.strip():
        return []
    raus = []
    for r in _analyzer.analyze(text=text, language="de", entities=ARTEN):
        if r.score < MIN_SCORE:
            continue
        raus.append({"start": int(r.start), "end": int(r.end),
                     "typ": str(r.entity_type), "score": round(float(r.score), 3)})
    return raus


def _faktor(breite: int, hoehe: int) -> int:
    """Hochskalieren fuer kleine Gesichter – gemessen, nicht geschaetzt.

    YuNet findet ein Gesicht direkt erst ab rund 30 px. Am 2026-10-27 auf DEV:
    ein Profilbild von 40 px (Gesicht ~12 px) wird erst mit Faktor 3 gefunden,
    48/64 px schon mit Faktor 2, 32 px auch mit 3 nicht. Ein Bildschirmausschnitt
    mit Kontaktliste ist genau dieser Fall. Grosse Ausschnitte werden nicht
    vergroessert – dort sind die Gesichter gross, und die Rechenzeit waechst mit
    der Flaeche.
    """
    seite = max(breite, hoehe)
    if seite <= 1000:
        return 3
    if seite <= 2000:
        return 2
    return 1


def gesichter(pfad: str) -> list:
    if not _gesicht_modell:
        raise RuntimeError("Gesichtserkennung nicht verfuegbar")
    import cv2
    bild = cv2.imread(pfad, cv2.IMREAD_COLOR)
    if bild is None:
        raise RuntimeError("Bild nicht lesbar")
    h, w = bild.shape[:2]
    fak = _faktor(w, h)
    if fak > 1:
        bild = cv2.resize(bild, (w * fak, h * fak), interpolation=cv2.INTER_CUBIC)
    hh, ww = bild.shape[:2]
    det = cv2.FaceDetectorYN.create(_gesicht_modell, "", (ww, hh), GESICHT_SCORE)
    _, funde = det.detect(bild)
    raus = []
    for f in (funde if funde is not None else []):
        raus.append([float(f[0]) / fak, float(f[1]) / fak,
                     float(f[2]) / fak, float(f[3]) / fak, round(float(f[14]), 3)])
    return raus


def main() -> int:
    modell = sys.argv[1] if len(sys.argv) > 1 else ""
    fehler = {}
    f = _presidio_laden()
    if f:
        fehler["personen"] = f
    f = _gesichter_laden(modell)
    if f:
        fehler["gesichter"] = f
    _antwort({"bereit": True, "personen": _analyzer is not None,
              "gesichter": bool(_gesicht_modell), "fehler": fehler})
    for zeile in sys.stdin:
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            auftrag = json.loads(zeile)
            op = auftrag.get("op")
            if op == "personen":
                _antwort({"ok": True, "treffer": personen(str(auftrag.get("text") or ""))})
            elif op == "gesichter":
                _antwort({"ok": True, "boxen": gesichter(str(auftrag.get("pfad") or ""))})
            else:
                _antwort({"ok": False, "fehler": "unbekannte Operation"})
        except Exception as e:  # noqa: BLE001
            _antwort({"ok": False, "fehler": "%s: %s" % (type(e).__name__, str(e)[:200])})
    return 0


if __name__ == "__main__":
    sys.exit(main())
