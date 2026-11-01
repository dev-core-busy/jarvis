#!/usr/bin/env python3
"""Waechter: Werkzeug-Argumente gehen ohne Geheimnisse in den Verlauf.

Code-Review 2026-11-01: ``conv_log.args_fuer_verlauf`` schrieb die Argumente
nur gekuerzt in den Verlauf – ein ``curl -u admin:Geheim`` oder ein
Kennwort-Feld stand im Klartext auf der Platte und ging ueber die
Fehleranalyse als Dossier an ein LLM.

Was festgehalten wird:

0. Positivkontrolle: die Funktion laeuft und laesst ein harmloses Argument
   unveraendert (sonst waere "Geheimnis fehlt" trivial wahr – etwa wenn sie
   gar nichts mehr zurueckgibt).
1. MUSS-GESCHWAERZT: jede Schreibweise einzeln, je mit einem eigenen
   Geheimnis; geprueft wird, dass der WERT fehlt und der NAME bleibt.
2. MUSS-FREI: Diagnosefelder, die wie Geheimnisse klingen, aber keine sind
   (``max_tokens``, ``--token-file``, ``PASSWORD_FILE``, Pfade, Befehle).
3. Verschachtelt (Objekt/Liste) und VOR dem Kuerzen geschwaerzt.
4. Regel am Syntaxbaum: jeder Werkzeug-Eintrag mit ``"args"`` im Verlauf
   von ``agent.py`` geht durch ``args_fuer_verlauf``.

    python3 tests/test_conv_log_geheimnisse.py
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist bereits geladen.", file=sys.stderr)
    raise SystemExit(2)

_ok = 0
_fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


from backend import conv_log  # noqa: E402

if "backend.config" in sys.modules:
    print("ABBRUCH: conv_log hat backend.config nachgeladen.", file=sys.stderr)
    raise SystemExit(2)

A = conv_log.args_fuer_verlauf

# ─── 0. Positivkontrolle ─────────────────────────────────────────────────────
print("\n0. Positivkontrolle")
try:
    harmlos = A({"path": "/tmp/bericht.xlsx", "command": "ls -l /tmp", "n": 3})
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: args_fuer_verlauf wirft: {e!r}", file=sys.stderr)
    raise SystemExit(2)
if harmlos != {"path": "/tmp/bericht.xlsx", "command": "ls -l /tmp", "n": 3}:
    print(f"ABBRUCH: harmlose Argumente veraendert: {harmlos!r}", file=sys.stderr)
    raise SystemExit(2)
check(True, "harmlose Argumente kommen unveraendert an")


def _text(d):
    return json.dumps(d, ensure_ascii=False)


# ─── 1. MUSS-GESCHWAERZT ─────────────────────────────────────────────────────
print("\n1. Geheimnisse verschwinden, Namen bleiben")
FAELLE = [
    # (Beschreibung, Argumente, Geheimnis, Rest, der stehen bleiben muss)
    ("curl -u benutzer:kennwort", {"command": "curl -u admin:Sonde1Kw https://x/api"},
     "Sonde1Kw", "-u admin:"),
    ("curl --user=benutzer:kennwort", {"command": "curl --user=admin:Sonde2Kw https://x"},
     "Sonde2Kw", "--user=admin:"),
    ("Authorization: Bearer", {"command": 'curl -H "Authorization: Bearer Sonde3Tok" x'},
     "Sonde3Tok", "Authorization: Bearer"),
    ("Authorization: Basic", {"command": "curl -H 'Authorization: Basic U29uZGU0' x"},
     "U29uZGU0", "Authorization: Basic"),
    ("Kopfsatz X-API-Key", {"command": 'curl -H "X-API-Key: Sonde5Key" x'},
     "Sonde5Key", "X-API-Key:"),
    ("Schalter --password=", {"command": "mysql --password=Sonde6Pw db"},
     "Sonde6Pw", "--password="),
    ("Schalter --api-key mit Leerzeichen", {"command": "tool --api-key Sonde7Key run"},
     "Sonde7Key", "--api-key"),
    ("Umgebungs-Zuweisung", {"command": "GITHUB_TOKEN=Sonde8Tok gh repo list"},
     "Sonde8Tok", "GITHUB_TOKEN="),
    ("Python-Zuweisung", {"code": 'passwort = "Sonde9Pw"\nprint(1)'},
     "Sonde9Pw", "passwort ="),
    ("JSON-Schluessel im Text", {"body": '{"password": "Sonde10Pw", "name": "n"}'},
     # Der Wert ist selbst ein String im JSON-Text -> Anfuehrungszeichen escaped.
     "Sonde10Pw", r'\"password\": \"***\"'),
    ("sshpass -p", {"command": "sshpass -p Sonde11Pw ssh host"},
     "Sonde11Pw", "sshpass -p"),
    ("Kennwort in Adresse", {"url": "https://admin:Sonde12Pw@host/x"},
     "Sonde12Pw", "https://admin:"),
    ("Token im Query-String", {"url": "https://host/x?token=Sonde13Tok&a=1"},
     "Sonde13Tok", "token="),
    ("geheimer Feldname", {"password": "Sonde14Pw"}, "Sonde14Pw", '"password"'),
    ("geheimer Feldname mit Endung", {"smtp_password": "Sonde15Pw"},
     "Sonde15Pw", '"smtp_password"'),
]
for besch, args, geheim, rest in FAELLE:
    t = _text(A(args))
    check(geheim not in t and rest in t, f"{besch}: Wert weg, Name bleibt ({t[:70]})")

# ─── 2. MUSS-FREI ────────────────────────────────────────────────────────────
print("\n2. Diagnosefelder bleiben lesbar")
FREI = {
    "max_tokens": 4096,
    "command": "tool --max-tokens 50 --token-file /etc/x.tok --password-file /etc/p",
    "env": "PASSWORD_FILE=/etc/p TOKEN_PATH=/x",
    "path": "/tmp/token_bericht.xlsx",
    "token_json_path": "$.data.token",
    "query": "Wie setze ich mein Kennwort zurueck?",
}
aus = A(FREI)
for k, v in FREI.items():
    check(aus.get(k) == v, f"unveraendert: {k} = {v!r}")

# ─── 3. Verschachtelt und vor dem Kuerzen ────────────────────────────────────
print("\n3. Verschachtelte Werte, Reihenfolge Schwaerzen -> Kuerzen")
t = _text(A({"params": {"user": "u", "api_key": "Sonde16Key",
                        "liste": ["--password Sonde17Pw", {"secret": "Sonde18Sec"}]}}))
check("Sonde16Key" not in t and "Sonde17Pw" not in t and "Sonde18Sec" not in t,
      "Geheimnisse in Objekt und Liste geschwaerzt")
check('"user": "u"' in t, "harmloses Nachbarfeld im Objekt bleibt")
lang = "curl -u admin:Sonde19Pw https://x " + "a" * (conv_log._MAX_ARG_CHARS * 2)
t = _text(A({"command": lang}))
check("Sonde19Pw" not in t and "gekuerzt" in t, "langer Text: geschwaerzt UND gekuerzt")

# ─── 4. Regel: der Verlauf in agent.py geht durch args_fuer_verlauf ──────────
print("\n4. agent.py: jeder Verlaufs-Eintrag mit \"args\" geht durch args_fuer_verlauf")
baum = ast.parse((ROOT / "backend" / "agent.py").read_text(encoding="utf-8"))
eintraege = []
for n in ast.walk(baum):
    if isinstance(n, ast.Dict):
        schl = [k.value for k in n.keys if isinstance(k, ast.Constant)]
        if "args" in schl and "tool" in schl and "role" in schl:
            eintraege.append(n.values[schl.index("args")])
if not eintraege:
    print("ABBRUCH: keine Verlaufs-Eintraege mit args in agent.py gefunden.", file=sys.stderr)
    raise SystemExit(2)
for wert in eintraege:
    ok = (isinstance(wert, ast.Call) and isinstance(wert.func, ast.Attribute)
          and wert.func.attr == "args_fuer_verlauf")
    check(ok, f"Zeile {wert.lineno}: args = {ast.unparse(wert)[:60]}")

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
