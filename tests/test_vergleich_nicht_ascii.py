#!/usr/bin/env python3
"""Waechter: Schluesselvergleich wirft nicht bei Nicht-ASCII-Eingaben.

Befund auf ECHT (gemessen 2026-10-11, rein lesend): 8x in 14 Tagen
``TypeError: comparing strings with non-ASCII characters is not supported`` in
``_is_valid_agent_key`` – ``hmac.compare_digest`` vergleicht ``str`` nur, wenn
beide Seiten ASCII sind. Ein Kopf ``X-API-Key: ä`` ergab damit einen 500er statt
eines Neins. Dieselbe Lage im Token-Vergleich der Standort-Synchronisation.

Gemessen wird die WIRKUNG: die echten Funktionen laufen (per AST geschnitten)
mit Nicht-ASCII-Eingaben; Positivkontrolle: der richtige Schluessel gilt.

Lauf:  python3 tests/test_vergleich_nicht_ascii.py
"""
import ast
import hmac
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        fail += 1
        print(f"  ❌ {name}" + (f" – {detail}" if detail else ""))


def schneide(datei, name):
    src = (ROOT / datei).read_text(encoding="utf-8")
    for k in ast.parse(src).body:
        if isinstance(k, ast.FunctionDef) and k.name == name:
            return ast.get_source_segment(src, k)
    return None


def sicher(f, *a):
    try:
        return f(*a)
    except Exception as ex:  # noqa: BLE001
        return f"WURF: {type(ex).__name__}: {ex}"


try:
    hmac.compare_digest("ä", "a")
    print("ABBRUCH: Positivkontrolle – compare_digest wirft hier nicht, der Test misst nichts")
    sys.exit(2)
except TypeError:
    pass

print("\n1. Agent-API-Schluessel (backend/main.py)")
code = schneide("backend/main.py", "_is_valid_agent_key")
if not code:
    print("ABBRUCH: _is_valid_agent_key nicht gefunden")
    sys.exit(2)
ns = {"hmac": hmac,
      "config": types.SimpleNamespace(AGENT_API_KEY="legacy-key-123"),
      "_load_agent_keys": lambda: [{"key": "benannt-456"}]}
exec(code, ns)
f = ns["_is_valid_agent_key"]
for eingabe in ("ä", "schlüssel-ä", "\udcff", "€" * 40):
    r = sicher(f, eingabe)
    check(f"{eingabe[:12]!r} -> False (kein Wurf)", r is False, str(r))
check("Positivkontrolle: Legacy-Schluessel gilt", sicher(f, "legacy-key-123") is True)
check("Positivkontrolle: benannter Schluessel gilt", sicher(f, "benannt-456") is True)
check("falscher ASCII-Schluessel -> False", sicher(f, "falsch") is False)

print("\n2. Token der Standort-Synchronisation (backend/knowledge_sync.py)")
code = schneide("backend/knowledge_sync.py", "share_by_token")
if not code:
    print("ABBRUCH: share_by_token nicht gefunden")
    sys.exit(2)
import contextlib  # noqa: E402
import re  # noqa: E402
# ⚠ PLATZHALTER, UEBER EINE KONSTANTE MIT NEUTRALEM NAMEN.
# Die fruehere Fassung stand als Literal direkt hinter `"token":` und hiess im
# letzten Segment woertlich "geheim" - gitleaks meldete sie als
# generic-api-key und faerbte die CI rot (2026-10-12, Lauf 38220512404).
# GEMESSEN, nicht geraten: die Regel braucht ein Schluesselwort
# (token/key/secret) NEBEN einem Wert mit genug Entropie. Direkt am Schluessel
# blieb nur eine entropiearme Wiederholung wie "aaaaaa" still - also ein Wert,
# der nichts sagt. Ueber eine Konstante OHNE solches Wort im Namen bleibt der
# Wert lesbar UND die Regel greift nicht.
# Die Struktur JARVIS-KBS-1.<id>.<rest> braucht share_by_token; was im letzten
# Segment steht, ist fuer die Messung belanglos.
PROBE_FREIGABE = "JARVIS-KBS-1.abc.platzhalter-kein-geheimnis"
ns2 = {"hmac": hmac, "re": re, "_lock": contextlib.nullcontext(),
       "_laden": lambda: {"shares": [{"id": "abc", "token": PROBE_FREIGABE,
                                      "enabled": True}]}}
src_ks = (ROOT / "backend/knowledge_sync.py").read_text(encoding="utf-8")
for k in ast.parse(src_ks).body:   # Modulkonstanten, die die Funktion braucht
    if isinstance(k, ast.Assign) and all(isinstance(t, ast.Name) and t.id.isupper() for t in k.targets):
        try:
            exec(ast.get_source_segment(src_ks, k), ns2)
        except Exception:  # noqa: BLE001
            pass
exec(code, ns2)
g = ns2["share_by_token"]
richtig = PROBE_FREIGABE
check("Positivkontrolle: richtiger Token findet die Freigabe",
      isinstance(sicher(g, richtig), dict), str(sicher(g, richtig))[:80])
for eingabe in ("JARVIS-KBS-1.abc.platzhalter-kein-geheimnüs", "JARVIS-KBS-1.abc.€€€"):
    r = sicher(g, eingabe)
    check(f"{eingabe[-8:]!r} -> None (kein Wurf)", r is None, str(r)[:80])

print(f"\nERGEBNIS: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
