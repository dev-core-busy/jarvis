#!/usr/bin/env python3
"""Probe: vergiftet der Host-Header hier noch request.url.path? (CVE-2026-48710)

Der Waechter ``test_starlette_badhost.py`` prueft die DEKLARATION. Eine
Deklaration ist aber keine Installation – auf dem Server zaehlt, was im venv
liegt. Diese Probe misst deshalb die WIRKUNG am Syntax-nahen Primitiv: sie baut
einen ASGI-Scope mit bosartigem Host und vergleicht den von der Anwendung
gesehenen ``request.url.path`` mit dem ASGI-Pfad ``scope["path"]``, nach dem das
Routing entscheidet. Weichen sie ab, ist die Luecke offen.

Das ist kein Vorkommens-Test: gemessen wird das Verhalten der installierten
Bibliothek, nicht ein Versionsstring. Eine Version, die luegt, faellt hier auf.

Der Angriff in diesem Projekt, konkret: ``_api_local_only_mw`` in
``backend/main.py`` steigt frueh aus, wenn der Pfad mit ``/static/`` beginnt.
Host ``<host>/static`` macht aus ``/api/admin/...`` ein ``/static/api/admin/...``
– 403-Sperre und Fremdzugriffs-Zaehlung fallen weg, der Endpunkt laeuft.

Lauf (dort, wo das venv liegt):
    /opt/jarvis/venv/bin/python tests/live_starlette_badhost.py

Exit 0 = dicht, Exit 1 = verwundbar, Exit 2 = konnte nicht laufen
"""
import sys

ZIEL_PFAD = "/api/admin/geheim"

# Hosts mit eingeschmuggeltem Autoritaet-zu-Pfad-Trennzeichen. Der erste Fall ist
# der, der hier wirklich etwas aushebelt (siehe /static/-Frueh-Ausstieg oben).
BOESE_HOSTS = [
    b"opfer.example/static",
    b"opfer.example/static/",
    b"opfer.example#",
    b"opfer.example?x=1",
    b"opfer.example/..",
    b"opfer.example\\static",
]

try:
    import starlette
    from starlette.requests import Request
except Exception as e:  # noqa: BLE001
    print(f"Exit 2: Starlette nicht importierbar ({e}). Diese Probe braucht das "
          f"venv des Dienstes, z.B. /opt/jarvis/venv/bin/python")
    sys.exit(2)

print(f"Starlette {starlette.__version__}  (Python {sys.version.split()[0]})")


def scope(host: bytes) -> dict:
    """Vollstaendiger HTTP-Scope – die Attrappe bildet die echte Form nach,
    sonst misst die Probe eine Ausnahme statt eines Verhaltens."""
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": ZIEL_PFAD,
        "raw_path": ZIEL_PFAD.encode(),
        "query_string": b"",
        "root_path": "",
        "server": ("127.0.0.1", 443),
        "client": ("192.0.2.9", 54321),
        "headers": [(b"host", host)],
    }


def gesehener_pfad(host: bytes):
    """(pfad, None) oder (None, fehlertext) – wirft nicht, damit ein Fehlschlag
    ein FAIL bleibt und kein Abbruch."""
    try:
        return Request(scope(host)).url.path, None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


# ── Positivkontrolle VOR den inhaltlichen Pruefungen ────────────────────────
# Liefert ein harmloser Host nicht den erwarteten Pfad, dann misst die Sonde
# nicht das, was sie zu messen behauptet – und jedes "dicht" unten waere
# trivial wahr. Das ist Exit 2, nicht Exit 0.
kontrolle, fehler = gesehener_pfad(b"opfer.example")
if fehler:
    print(f"Exit 2: Positivkontrolle wirft {fehler}")
    sys.exit(2)
if kontrolle != ZIEL_PFAD:
    print(f"Exit 2: Positivkontrolle liefert {kontrolle!r}, erwartet {ZIEL_PFAD!r} "
          f"– die Sonde taugt nicht, Befund waere nicht deutbar")
    sys.exit(2)
print(f"  \033[32m✓\033[0m Positivkontrolle: harmloser Host -> url.path {kontrolle!r}")

# ── Messung ─────────────────────────────────────────────────────────────────
print()
vergiftet = []
for host in BOESE_HOSTS:
    pfad, fehler = gesehener_pfad(host)
    if fehler:
        # Eine Ausnahme laesst nichts durch, ist aber auch kein stiller Erfolg
        print(f"  \033[33m?\033[0m Host {host!r:28} -> Ausnahme {fehler}")
        continue
    if pfad != ZIEL_PFAD:
        vergiftet.append((host, pfad))
        print(f"  \033[31m✗\033[0m Host {host!r:28} -> url.path {pfad!r}  VERGIFTET")
    else:
        print(f"  \033[32m✓\033[0m Host {host!r:28} -> url.path {pfad!r}")

print(f"\n{'─' * 60}")
if vergiftet:
    print(f"FAIL: {len(vergiftet)} von {len(BOESE_HOSTS)} Hosts verschieben url.path "
          f"gegen scope['path'].")
    print(f"      Starlette {starlette.__version__} ist verwundbar (CVE-2026-48710). "
          f"Noetig ist >= 1.0.1.")
    for host, pfad in vergiftet:
        print(f"      {host.decode()!r:34} -> {pfad!r}")
    sys.exit(1)

print(f"OK: alle {len(BOESE_HOSTS)} bosartigen Hosts lassen url.path unveraendert "
      f"(Starlette {starlette.__version__}).")
sys.exit(0)
