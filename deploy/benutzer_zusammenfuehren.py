#!/usr/bin/env python3
"""Doppelte Benutzer-Ablagen zusammenfuehren – Handbetrieb.

Der Regelweg ist der Backend-Start (`startup_benutzer_ablagen`); dieses Skript
ist fuer den Fall, dass man den Befund SEHEN will, bevor etwas passiert – und
fuer Server, auf denen die Automatik abgeschaltet ist
(`JARVIS_BENUTZER_MIGRATION=0`).

    python3 deploy/benutzer_zusammenfuehren.py            # Trockenlauf (Vorgabe)
    python3 deploy/benutzer_zusammenfuehren.py --anwenden  # schreibt, mit Sicherung

⚠ ALS DIENSTBENUTZER AUFRUFEN (`runuser -u jarvis -- …` bzw. `sudo -u jarvis`).
Als root angelegte Dateien in `data/` legen den naechsten Zugriff des Backends
lahm – oft erst Wochen spaeter (Register).

⚠ UND DEN DIENST DANACH NEU STARTEN. `tools/memory.py` haelt je Benutzer einen
Cache im RAM: ohne Neustart arbeitet der Agent mit dem alten Stand weiter, und
das naechste `memory_manage save` schreibt die Zusammenfuehrung wieder zu
(am 2026-09-04 bezahlt).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import benutzer_migration as bm  # noqa: E402


def main() -> int:
    anwenden = "--anwenden" in sys.argv[1:]
    unbekannt = [a for a in sys.argv[1:] if a not in ("--anwenden",)]
    if unbekannt:
        print(f"Unbekannte Argumente: {unbekannt}")
        print(__doc__)
        return 2

    print(f"Datenverzeichnis: {bm.DATA}")
    befund = bm.finde()
    print(f"Bekannte Benutzer ({len(befund.benutzer)}): {', '.join(befund.benutzer) or '–'}")
    print(f"Domaenen-Praefixe: {', '.join(befund.praefixe) or '–'}")
    print()

    if befund.unzuordenbar:
        print("⚠ NICHT ZUORDENBAR – bleibt unangetastet:")
        for ablage, e in befund.unzuordenbar:
            print(f"   {ablage}: '{e}'")
        print("   (Der Benutzer steht in keiner Namensquelle. Ein geratener")
        print("    Zusammenschluss vermischt die Daten zweier Menschen.)")
        print()

    if befund.schluessel:
        print(f"{len(befund.schluessel)} doppelte(r) Benutzer-Schluessel:")
        for m in befund.schluessel:
            print(f"   {m}")
        print()

    if not befund.vorgaenge and not befund.schluessel:
        print("Nichts zusammenzufuehren.")
        return 0

    if not befund.vorgaenge:
        if not anwenden:
            print("TROCKENLAUF – es wurde nichts geaendert. Mit --anwenden ausfuehren.")
            return 0
        bm.schluessel_aufraeumen(trocken=False)
        print("✓ Schluessel bereinigt.")
        print("⚠ Jetzt den Dienst neu starten (RAM-Cache je Benutzer).")
        return 0

    print(f"{len(befund.vorgaenge)} Vorgang/Vorgaenge:")
    for v in befund.vorgaenge:
        print(f"   [{v.art:16}] {v.ablage:22} '{v.quelle.name}' -> '{v.ziel.name}'"
              f"   (Benutzer: {v.benutzer})")
    print()

    if not anwenden:
        print("TROCKENLAUF – es wurde nichts geaendert. Mit --anwenden ausfuehren.")
        return 0

    erg = bm.anwenden(befund, trocken=False)
    if erg.get("sicherung"):
        print(f"Sicherung: {erg['sicherung']}")
    for v in erg["vorgaenge"]:
        print(f"   ✓ {v['art']}: {v['ablage']} '{v['quelle']}' -> '{v['ziel']}'")
        for h in v.get("hinweise", []):
            print(f"       {h}")
    for f in erg["fehler"]:
        print(f"   ⚠ FEHLER {f}")
    print()
    nach = bm.finde()
    print(f"Kontrolllauf: {len(nach.vorgaenge)} Vorgang/Vorgaenge offen"
          + ("  ✓ nichts mehr zu tun" if not nach.vorgaenge else "  ⚠ nicht vollstaendig"))
    print("⚠ Jetzt den Dienst neu starten (RAM-Cache je Benutzer).")
    return 1 if erg["fehler"] or nach.vorgaenge else 0


if __name__ == "__main__":
    sys.exit(main())
