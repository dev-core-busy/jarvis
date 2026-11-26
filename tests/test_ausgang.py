#!/usr/bin/env python3
"""Waechter: Ausgangsfilter fuer den ganzen Host (Haertung D1, deploy/security/ausgang.sh).

Zusagen:
  - Der Satz aus ``--zeigen`` LAEDT (nft im Wegwerf-Namensraum, unshare -rn) und
    wird an der JSON-Liste gemessen, nicht am Text.
  - Kette ``out`` am Hook output; MODUS=protokoll (auch wenn MODUS fehlt) ->
    policy accept, MODUS=sperre -> policy drop.
  - Reihenfolge: loopback, dann bestehende Verbindungen, dann die Freigaben,
    die Log-Regel ZULETZT (gedrosselt, mit uid, Praefix je Modus). Kein accept
    hinter der Log-Regel.
  - Jede Benutzer-Freigabe ist an genau die uid des Benutzers gebunden; eine
    "alle"-Freigabe an keine uid, aber an ein Ziel.
  - Ungueltige Konfigurationen (unbekannter Benutzer, kaputter Port/Ziel,
    "alle" mit "*", falscher MODUS, icmp mit Port, fehlende Datei) brechen mit
    Fehler ab und geben KEINEN Satz aus.

  [0] Positivkontrollen: nft im Namensraum nimmt einen guten Satz an, lehnt einen
      kaputten ab, und ``--zeigen`` liefert ueberhaupt einen Satz. Sonst Exit 2.

Fuer die Gegenprobe: JARVIS_AUSGANG_PRUEFLING zeigt auf eine Kopie.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKRIPT = Path(os.environ.get("JARVIS_AUSGANG_PRUEFLING") or REPO / "deploy" / "security" / "ausgang.sh")
TABELLE = "jarvis_ausgang"
OK = FAIL = 0


def check(name, bedingung, detail=""):
    global OK, FAIL
    if bedingung:
        OK += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {name}" + (f" – {detail}" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH: {grund}")
    sys.exit(2)


def zeigen(konf_text):
    """``ausgang.sh --zeigen`` mit einer Wegwerf-Konfiguration: (rc, stdout, stderr)."""
    with tempfile.TemporaryDirectory() as d:
        konf = Path(d) / "ausgang.conf"
        if konf_text is not None:
            konf.write_text(konf_text)
        env = dict(os.environ, JARVIS_AUSGANG_CONF=str(konf))
        p = subprocess.run(["bash", str(SKRIPT), "--zeigen"], capture_output=True, text=True,
                           timeout=30, env=env)
        return p.returncode, p.stdout, p.stderr


def laden_json(text):
    """Satz im Namensraum laden und als JSON listen: (rc, liste oder Meldung)."""
    with tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False) as f:
        f.write(text)
    try:
        p = subprocess.run(["unshare", "-rn", "sh", "-c",
                            'nft -f "$1" && nft -j list table inet "$2"', "sh", f.name, TABELLE],
                           capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            return p.returncode, (p.stderr or p.stdout).strip()[:300]
        return 0, json.loads(p.stdout)["nftables"]
    finally:
        os.unlink(f.name)


def kette_und_regeln(liste):
    kette = next((o["chain"] for o in liste if "chain" in o and o["chain"].get("name") == "out"), None)
    regeln = [o["rule"] for o in liste if "rule" in o and o["rule"].get("chain") == "out"]
    return kette, regeln


def hat(regel, schluessel):
    """Kommt ein Ausdruck mit diesem Schluessel in der Regel vor (accept, log, limit ...)?"""
    return any(schluessel in ausdruck for ausdruck in regel.get("expr", []))


def skuids(regel):
    """Alle uid-Bedingungen der Regel (meta skuid == N)."""
    werte = []
    for ausdruck in regel.get("expr", []):
        m = ausdruck.get("match")
        if m and m.get("left") == {"meta": {"key": "skuid"}}:
            werte.append((m.get("op"), m.get("right")))
    return werte


def hat_ziel(regel):
    for ausdruck in regel.get("expr", []):
        m = ausdruck.get("match")
        if m and m.get("left") == {"payload": {"protocol": "ip", "field": "daddr"}}:
            return True
    return False


def ist_lo(regel):
    return any(a.get("match", {}).get("left") == {"meta": {"key": "oifname"}}
               and a["match"].get("right") == "lo" for a in regel.get("expr", [])) and hat(regel, "accept")


def ist_bestehend(regel):
    for a in regel.get("expr", []):
        m = a.get("match")
        if m and m.get("left") == {"ct": {"key": "state"}}:
            r = m.get("right")
            r = set(r if isinstance(r, list) else [r])
            return r == {"established", "related"} and hat(regel, "accept")
    return False


# Lokale Benutzer, die es auf jedem Debian gibt – der Waechter darf nicht von
# Server-Konten abhaengen.
NOBODY = pwd.getpwnam("nobody").pw_uid
GUT = (
    "MODUS={modus}\n"
    "erlaube alle udp 53 192.0.2.53,192.0.2.54\n"
    "erlaube alle tcp 445 192.0.2.45\n"
    "erlaube root tcp 22,443 *\n"
    "erlaube nobody icmp - 192.0.2.0/24\n"
    "erlaube nobody tcp 8000-8100 198.51.100.7\n"
    "erlaube 4321 udp - 198.51.100.8\n"
)

print("[0] Positivkontrollen")
if not shutil.which("unshare") or not shutil.which("nft"):
    abbruch("unshare oder nft fehlt")
rc, _ = laden_json("table inet jarvis_ausgang {\n chain out {\n  type filter hook output priority 0; policy accept;\n }\n}\n")
if rc != 0:
    abbruch(f"nft im Namensraum nimmt einen guten Satz nicht an: {_}")
rc, _ = laden_json("table inet jarvis_ausgang {\n chain out {\n  kaputt\n }\n}\n")
if rc == 0:
    abbruch("nft im Namensraum nimmt einen kaputten Satz an – die Messung waere wertlos")
if not SKRIPT.is_file():
    abbruch(f"Pruefling fehlt: {SKRIPT}")
rc, satz, err = zeigen(GUT.format(modus="protokoll"))
if rc != 0 or "table inet" not in satz:
    abbruch(f"--zeigen liefert keinen Satz (rc={rc}): {err.strip()[:200]}")
print("  ✓ Messwerkzeug arbeitet")

print("[1] Protokollmodus: Satz laedt, Kette und Reihenfolge")
rc, liste = laden_json(satz)
check("Satz laedt im Namensraum", rc == 0, str(liste))
if rc == 0:
    kette, regeln = kette_und_regeln(liste)
    check("Kette out am Hook output", bool(kette) and kette.get("hook") == "output", str(kette))
    check("protokoll -> policy accept", bool(kette) and kette.get("policy") == "accept", str(kette))
    check("erste Regel: loopback accept", bool(regeln) and ist_lo(regeln[0]))
    check("zweite Regel: established,related accept", len(regeln) > 1 and ist_bestehend(regeln[1]))
    letzte = regeln[-1] if regeln else {}
    log = next((a["log"] for a in letzte.get("expr", []) if "log" in a), None)
    check("letzte Regel protokolliert", log is not None, str(letzte)[:200])
    check("Log-Regel gedrosselt", hat(letzte, "limit"))
    check("Log-Regel nennt die uid (flags skuid)",
          bool(log) and "skuid" in (log.get("flags") if isinstance(log.get("flags"), list) else [log.get("flags")]),
          str(log))
    check("Praefix im Protokollmodus nft-aus-frei", bool(log) and log.get("prefix") == "nft-aus-frei: ", str(log))
    check("Log-Regel verwirft/erlaubt selbst nichts", not hat(letzte, "accept") and not hat(letzte, "drop"))
    freigaben = regeln[2:-1]
    check("alle sechs Freigaben stehen zwischen Anfang und Log-Regel", len(freigaben) == 6, str(len(freigaben)))
    check("jede Freigabe endet mit accept", all(hat(r, "accept") for r in freigaben))
    erwartet = [None, None, 0, NOBODY, NOBODY, 4321]
    for r, uid in zip(freigaben, erwartet):
        name = r.get("comment", "?")
        if uid is None:
            check(f"'{name}': an keine uid gebunden, aber an ein Ziel", skuids(r) == [] and hat_ziel(r), str(r)[:200])
        else:
            check(f"'{name}': genau an uid {uid} gebunden", skuids(r) == [("==", uid)], str(skuids(r)))

print("[2] Sperrmodus und Vorgabe")
rc, satz, err = zeigen(GUT.format(modus="sperre"))
rc2, liste = laden_json(satz) if rc == 0 else (rc, err)
if rc2 == 0:
    kette, regeln = kette_und_regeln(liste)
    log = next((a["log"] for a in regeln[-1].get("expr", []) if "log" in a), None) if regeln else None
    check("sperre -> policy drop", kette.get("policy") == "drop", str(kette))
    check("Praefix im Sperrmodus nft-aus-drop", bool(log) and log.get("prefix") == "nft-aus-drop: ", str(log))
else:
    check("Sperrsatz laedt", False, str(liste))
rc, satz, err = zeigen(GUT.replace("MODUS={modus}\n", ""))
rc2, liste = laden_json(satz) if rc == 0 else (rc, err)
check("ohne MODUS gilt protokoll (policy accept)",
      rc2 == 0 and kette_und_regeln(liste)[0].get("policy") == "accept", str(liste)[:200])

print("[3] Ungueltige Konfiguration bricht ab, ohne Satz")
FAELLE = {
    "unbekannter Benutzer": "erlaube gibtsnicht_d1 tcp 443 *\n",
    "Port ausserhalb": "erlaube root tcp 70000 *\n",
    "Port kein Wert": "erlaube root tcp abc *\n",
    "Bereich verkehrt": "erlaube root tcp 9000-8000 *\n",
    "Ziel kaputt": "erlaube root tcp 443 192.0.2.300\n",
    "Ziel IPv6/Name": "erlaube root tcp 443 beispiel.de\n",
    "Maske zu gross": "erlaube root tcp 443 192.0.2.0/33\n",
    "alle mit *": "erlaube alle tcp 443 *\n",
    "falscher MODUS": "MODUS=offen\nerlaube root tcp 443 *\n",
    "icmp mit Port": "erlaube root icmp 8 192.0.2.1\n",
    "Protokoll unbekannt": "erlaube root sctp 443 *\n",
    "Feld zu viel": "erlaube root tcp 443 * extra\n",
    "Feld fehlt": "erlaube root tcp 443\n",
    "falsches Schluesselwort": "verbiete root tcp 443 *\n",
}
for name, text in FAELLE.items():
    rc, satz, err = zeigen("erlaube alle udp 53 192.0.2.53\n" + text)
    check(f"{name}: Fehler, kein Satz", rc != 0 and "table" not in satz, f"rc={rc} satz={satz[:80]!r}")
rc, satz, err = zeigen(None)
check("fehlende Datei: Fehler, kein Satz", rc != 0 and "table" not in satz, f"rc={rc}")

print("[4] Vorlage im Repo erzeugt einen Satz (Konten werden durch lokale ersetzt)")
vorlage = (REPO / "deploy" / "security" / "ausgang.conf.beispiel").read_text()
lokal = "\n".join(
    " ".join(["erlaube", "nobody"] + z.split()[2:]) if z.split()[:1] == ["erlaube"] and z.split()[1] not in ("alle", "root") else z
    for z in vorlage.splitlines())
rc, satz, err = zeigen(lokal)
rc2, liste = laden_json(satz) if rc == 0 else (rc, err)
check("Vorlage laedt", rc2 == 0, str(liste)[:200])
check("Vorlage steht auf protokoll", rc2 == 0 and kette_und_regeln(liste)[0].get("policy") == "accept")

print("[5] Zweimal laden ersetzt, statt anzuhaengen")
rc, satz, err = zeigen(GUT.format(modus="protokoll"))
with tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False) as f:
    f.write(satz)
try:
    p = subprocess.run(["unshare", "-rn", "sh", "-c",
                        'nft -f "$1" && nft -f "$1" && nft -j list table inet "$2"', "sh", f.name, TABELLE],
                       capture_output=True, text=True, timeout=30)
finally:
    os.unlink(f.name)
if p.returncode == 0:
    _, regeln = kette_und_regeln(json.loads(p.stdout)["nftables"])
    check("nach zwei Laeufen 9 Regeln (2 + 6 Freigaben + Log), nicht 18", len(regeln) == 9, str(len(regeln)))
else:
    check("zweiter Lauf laedt", False, (p.stderr or p.stdout)[:200])

print(f"\n{OK} ok, {FAIL} Befund(e)")
sys.exit(1 if FAIL else 0)
