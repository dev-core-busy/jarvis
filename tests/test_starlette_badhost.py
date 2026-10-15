#!/usr/bin/env python3
"""Waechter: Starlette darf nicht unter 1.0.1 fallen (CVE-2026-48710, "BadHost").

DER ANLASS (2026-10-01): DEV und ECHT liefen beide auf Starlette 0.41.3. Starlette
baut ``request.url`` aus dem Host-Header, ohne ihn zu pruefen. Ein Host mit
Autoritaet-zu-Pfad-Trennzeichen – etwa ``opfer.example/static`` – verschiebt damit
den von der Anwendung gesehenen ``request.url.path``, waehrend das Routing nach
dem unveraenderten ``scope["path"]`` entscheidet.

Warum das hier teuer war: ``_api_local_only_mw`` in ``backend/main.py`` steigt
frueh aus, wenn der Pfad mit ``/static/`` beginnt. Mit Host ``<host>/static`` wurde
aus ``/api/admin/...`` ein ``/static/api/admin/...`` – die 403-Sperre fuer
"nur lokal" markierte Endpunkte UND die Fremdzugriffs-Zaehlung fielen beide weg,
der echte Endpunkt lief trotzdem. Gemessen, nicht vermutet:
``tests/live_starlette_badhost.py``.

Die Lage war in CISAs KEV-Katalog, Frist 2026-09-16 – also bereits ueberschritten,
als es auffiel.

Dieser Test liest NUR Text: er laeuft lokal wie auf jedem Server, auch ohne
installiertes Starlette. Die Wirkung misst ``live_starlette_badhost.py``, denn
eine Deklaration ist noch keine Installation.

ZUSATZ-FALLE, die Zeit gekostet hat: FastAPI ab 0.142.0 verlangt hart
``opentelemetry-api>=1.44.0``. Der OTel-Stack hier ist auf 1.40.0/0.61b0
festgenagelt (``opentelemetry-sdk==1.40.0`` verlangt ``opentelemetry-api==1.40.0``),
ein Hochziehen von FastAPI reisst ihn also mit. Deshalb traegt FastAPI eine
Obergrenze ``<0.142.0`` – die ist Absicht und keine Vorsicht. Wer sie entfernt,
muss den OTel-Stack geschlossen mitziehen.

Lauf:  python3 tests/test_starlette_badhost.py
Exit 0 = Deklaration traegt die Untergrenze, Exit 1 = Verstoss, Exit 2 = konnte nicht laufen
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Pfad als Argument, damit gegen_starlette_badhost.py dem Waechter gebaute
# Verstoesse vorlegen kann. Ohne Argument: die echte Datei.
REQ = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "requirements.txt"

# Behoben in 1.0.1; verwundbar ist >= 0.8.3, < 1.0.1
MINDEST = (1, 0, 1)

ok = 0
fehler = 0


def pruefe(was, bedingung, detail=""):
    global ok, fehler
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {was}")
    else:
        fehler += 1
        print(f"  \033[31m✗\033[0m {was}" + (f"\n      {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n\033[1m{t}\033[0m")


def version_tupel(text):
    """'1.0.1' -> (1, 0, 1). Nicht-Zahlen (rc, b0, *) brechen sauber ab -> None."""
    teile = []
    for stueck in text.strip().split("."):
        m = re.match(r"^(\d+)", stueck)
        if not m:
            return None
        teile.append(int(m.group(1)))
    return tuple(teile) if teile else None


def zeilen_ohne_kommentar(pfad):
    """Anforderungszeilen als (nummer, text) – Kommentare und Leerzeilen heraus."""
    raus = []
    for nr, roh in enumerate(pfad.read_text(encoding="utf-8").splitlines(), 1):
        text = roh.split("#", 1)[0].strip()
        if text:
            raus.append((nr, text))
    return raus


def anforderung(zeilen, paketname):
    """Die Zeile, die genau dieses Paket deklariert – nicht ein Paket, das es
    als Teilstring enthaelt. 'sse-starlette' ist NICHT 'starlette'."""
    treffer = []
    for nr, text in zeilen:
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", text)
        if m and m.group(1).lower() == paketname.lower():
            treffer.append((nr, text))
    return treffer


def untergrenze(spez, paketname):
    """Kleinste Version, die die Spezifikation noch zulaesst. None = keine Grenze."""
    rest = spez[len(paketname):]
    kandidaten = []
    for op, ver in re.findall(r"(>=|==|~=|>)\s*([0-9][0-9A-Za-z.*]*)", rest):
        t = version_tupel(ver)
        if t is None:
            continue
        kandidaten.append(t if op != ">" else t + (0,))
    return min(kandidaten) if kandidaten else None


# ── Positivkontrolle: existiert die Zusage ueberhaupt? ───────────────────────
# Ohne sie waere jede Aussage unten trivial wahr – ein fehlendes requirements.txt
# oder ein fehlender starlette-Eintrag ist "konnte nicht laufen", nicht "bestanden".
if not REQ.exists():
    print(f"Exit 2: {REQ} fehlt – nichts zu pruefen")
    sys.exit(2)

zeilen = zeilen_ohne_kommentar(REQ)
if not zeilen:
    print(f"Exit 2: {REQ} enthaelt keine Anforderungszeile")
    sys.exit(2)

star = anforderung(zeilen, "starlette")
if not star:
    print("Exit 2: requirements.txt deklariert 'starlette' ueberhaupt nicht – "
          "der Waechter kann keine Untergrenze pruefen, die es nicht gibt. "
          "(Starlette kommt sonst nur transitiv ueber fastapi und ist dann "
          "gar nicht steuerbar.)")
    sys.exit(2)

print(f"Starlette-Deklaration in requirements.txt: Zeile {star[0][0]}: {star[0][1]!r}")

abschnitt("Starlette-Untergrenze gegen CVE-2026-48710")

pruefe("starlette genau einmal deklariert",
       len(star) == 1,
       f"{len(star)} Zeilen: {[f'Z{n}: {t}' for n, t in star]} – "
       f"mehrere Eintraege, pip nimmt den letzten; die Absicht ist dann unlesbar")

for nr, spez in star:
    grenze = untergrenze(spez, "starlette")
    pruefe(f"Z{nr} traegt eine Untergrenze",
           grenze is not None,
           f"{spez!r} laesst jede Version zu – auch die verwundbare 0.41.3. "
           f"Noetig ist mindestens 'starlette>={'.'.join(map(str, MINDEST))}'")
    if grenze is not None:
        pruefe(f"Z{nr} Untergrenze >= {'.'.join(map(str, MINDEST))}",
               grenze >= MINDEST,
               f"{spez!r} laesst {'.'.join(map(str, grenze))} zu. Verwundbar ist "
               f">= 0.8.3, < 1.0.1 (BadHost: Host-Header vergiftet url.path)")

abschnitt("FastAPI-Obergrenze (haelt den OTel-Stack zusammen)")

fapi = anforderung(zeilen, "fastapi")
pruefe("fastapi ist deklariert", bool(fapi),
       "ohne Deklaration ist die Starlette-Fassung nicht steuerbar")

for nr, spez in fapi:
    # FastAPI darf Starlette nicht unter die Untergrenze zwingen. 0.115.6 pinnte
    # starlette<0.42.0 – damit war 1.0.1 schlicht nicht installierbar.
    grenze = untergrenze(spez, "fastapi")
    pruefe(f"Z{nr} fastapi-Untergrenze >= 0.133.0 (erste mit Starlette-1.x-Support)",
           grenze is not None and grenze >= (0, 133, 0),
           f"{spez!r}: FastAPI < 0.133.0 pinnt starlette < 1.0 und macht die "
           f"Untergrenze oben unerfuellbar")
    pruefe(f"Z{nr} fastapi traegt Obergrenze < 0.142.0 (OTel-Stack)",
           bool(re.search(r"<\s*0\.142(\.0)?\b", spez)),
           f"{spez!r}: ab 0.142.0 verlangt FastAPI hart opentelemetry-api>=1.44.0 "
           f"und bricht opentelemetry-sdk==1.40.0 / semantic-conventions==0.61b0. "
           f"Wer die Grenze loest, zieht den OTel-Stack geschlossen mit")

print(f"\n{'─' * 60}")
print(f"OK: {ok}   Fehler: {fehler}")
sys.exit(1 if fehler else 0)
