#!/usr/bin/env python3
"""Waechter: das Auto-Learning speichert kein wertloses Zeug.

⚠ AN ECHTEN DATEN GEMESSEN (DEV, 2026-09-06): von 71 Lernnotizen hatten **53**
als kompletten Inhalt das Wort "Standardantwort" - 75 % Muell, jede davon im
FAISS-Index und damit in JEDER kuenftigen Wissenssuche. Gemeldet vom Betreiber
("wieso ist sowas in einer gelernten Datei?").

Sie entstehen bei Auftraegen ohne Wissensgehalt ("Erzeuge ein Bild von einem
Hund"): das Modell liefert eine Floskel, und die wurde ungeprueft geschrieben.
Der bisherige Filter war eine WORTLISTE - unvollstaendig an dem Tag, an dem ein
Modell eine neue Floskel erfindet.

Gemessen wird die EIGENSCHAFT (Laenge UND Fakten-Struktur), und zwar an den
echten Texten aus dem Bestand.
"""
import ast
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OK = FAIL = 0


def check(name, bed):
    global OK, FAIL
    print(("  \033[32m✓\033[0m " if bed else "  \033[31m✗\033[0m ") + name)
    if bed:
        OK += 1
    else:
        FAIL += 1


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q = io.open(os.path.join(REPO, "backend/learning.py"), encoding="utf-8").read()

# ⚠ NUR die Funktion schneiden: `backend.learning` zu importieren zieht config,
# LLM-Provider und FAISS mit - der Test soll ueberall laufen und nichts anfassen.
baum = ast.parse(Q)
teile = [n for n in baum.body
         if (isinstance(n, ast.FunctionDef) and n.name == "_hat_substanz")
         or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "MIN_FAKTEN_ZEICHEN")]
if len(teile) != 2:
    print(f"ABBRUCH: _hat_substanz/MIN_FAKTEN_ZEICHEN nicht gefunden ({len(teile)}) - "
          "'konnte nicht laufen' ist nicht 'bestanden'.")
    sys.exit(2)
ns = {}
exec(compile(ast.Module(body=teile, type_ignores=[]), "<schnitt>", "exec"), ns)
hat_substanz = ns["_hat_substanz"]

print("\n\033[1m1. Die echten Muell-Texte aus dem Bestand\033[0m")
# Woertlich so im Bestand gefunden (53x)
for t in ("Standardantwort", "standardantwort", " Standardantwort \n"):
    check(f"{t.strip()!r} wird NICHT gespeichert", hat_substanz(t) is False)
for t in ("", "   ", "\n\n", "NICHTS", "keine Fakten"):
    check(f"{t.strip()!r} wird NICHT gespeichert", hat_substanz(t) is False)
check("None wirft nicht", hat_substanz(None) is False)

print("\n\033[1m2. Die echten WISSENS-Texte bleiben erhalten\033[0m")
# Woertlich die kuerzesten echten Notizen aus dem Bestand - sie sind der
# Massstab: was hier durchfaellt, ist Wissensverlust.
ECHT = [
    "- [Suchstrategie]: Bei Dateisystem-Abfragen muss Jarvis vorab pruefen, ob "
    "der Pfad existiert und lesbar ist, bevor eine Suche gestartet wird.",
    "- [mcp_everything_echo]: Das Tool gibt jede Eingabe woertlich zurueck und "
    "eignet sich damit als Funktionsprobe fuer die MCP-Anbindung des Servers.",
    "- [Umgebungsrestriktion]: Der aktuelle Nutzeraccount ist fuer Schreibzugriffe "
    "ausserhalb von /tmp gesperrt; Ergebnisdateien gehoeren deshalb nach /tmp.",
]
for t in ECHT:
    check(f"bleibt: {t[:46]!r}…", hat_substanz(t) is True)
check("mehrzeilig mit zwei Fakten bleibt",
      hat_substanz("- [A]: Ein hinreichend langer erster Fakt ueber das System.\n"
                   "- [B]: Und ein zweiter, ebenfalls ausreichend ausfuehrlich.") is True)

print("\n\033[1m3. Beide Kriterien sind noetig - einzeln waeren sie zu schwach\033[0m")
check("⚠ lang, aber OHNE Fakten-Struktur -> nicht gespeichert",
      hat_substanz("Ein langer Fliesstext ohne jede Struktur, der zwar deutlich "
                   "ueber achtzig Zeichen hat, aber keine Fakten-Zeile enthaelt.") is False)
check("⚠ MIT Struktur, aber zu kurz -> nicht gespeichert",
      hat_substanz("- [x]: kurz") is False)
check("die Schwelle liegt zwischen Muell (15 Z.) und echtem Wissen (170 Z.)",
      15 < ns["MIN_FAKTEN_ZEICHEN"] < 170)

print("\n\033[1m4. Die Pruefung ist VERDRAHTET (die Funktion allein nuetzt nichts)\033[0m")
fn = next((n for n in ast.walk(baum)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
           and "_save_and_index" in (ast.get_source_segment(Q, n) or "")
           and n.name != "_save_and_index"), None)
q = ast.get_source_segment(Q, fn) if fn else ""
check("die speichernde Funktion gefunden", bool(q))
check("⚠ sie ruft _hat_substanz", "_hat_substanz(" in q)
i_pruef = q.find("_hat_substanz(")
i_save = q.find("_save_and_index")
check("⚠ und zwar VOR dem Speichern", 0 <= i_pruef < i_save)
check("ein Fehlschlag wird protokolliert (sonst verschwindet es lautlos)",
      "nicht gespeichert" in q or "kein verwertbares Wissen" in q)

print("\n\033[1m5. Das Aufraeumskript fasst NUR conv_* an\033[0m")
# ⚠ AUF ECHT UM HAARESBREITE VERMIEDEN (2026-09-06): der Trockenlauf dort
# meldete 5 `feedback_*.md` als "ohne Wissensgehalt" - Dateien mit 3.000 bis
# 3.600 Zeichen echtem Inhalt. Sie schreibt main.py aus einer Benutzer-Bewertung
# und haben ein anderes Format ("## Urspruengliche Antwort", "## Was war
# schlecht"), fallen also durch die Fakten-Struktur-Pruefung. `_hat_substanz`
# ist NUR fuer das Auto-Learning gebaut (learning.py schreibt ausschliesslich
# conv_*.md). ZWEITES MAL an einem Tag, dass ein an DEV gemessenes Kriterium
# auf ECHT Schaden angerichtet haette (nach den Werkzeug-Buendeln).
AUF = io.open(os.path.join(REPO, "deploy/lernnotizen_aufraeumen.py"), encoding="utf-8").read()
check("das Aufraeumskript existiert", len(AUF) > 500)
check("⚠ es fasst NUR conv_*.md an",
      'startswith("conv_")' in AUF)
check("und meldet die uebersprungenen Gattungen (nicht stillschweigend)",
      "unberuehrt" in AUF or "fremd" in AUF)
check("⚠ es laedt das Kriterium aus learning.py (kein Nachbau)",
      "_hat_substanz_laden" in AUF and "learning.py" in AUF)
check("Trockenlauf ist die Vorgabe", '"--anwenden"' in AUF)
check("und es sichert VOR dem Loeschen", "tarfile" in AUF and "unlink" in AUF)
# Gegenprobe zur Zusage: learning.py darf keine feedback_-Dateien schreiben,
# sonst traefe der Schreibfilter sie doch.
check("⚠ learning.py schreibt kein feedback_* (der Filter trifft sie nie)",
      "feedback_" not in Q)

print(f"\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m")
sys.exit(1 if FAIL else 0)
