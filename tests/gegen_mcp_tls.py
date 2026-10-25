#!/usr/bin/env python3
"""Gegenprobe zu tests/test_mcp_tls.py: beisst der Waechter?

Jede Probe dreht EINEN Teil der Zusage zurueck und erwartet mindestens einen
FAIL. Vorher gruener Basislauf, danach Byte-Gleichheit per md5, ohne Bytecode.

Die beiden wichtigsten Proben sind die ersten: sie schalten die Pruefung ab
(``CERT_NONE`` bzw. ``check_hostname = False``) – also genau das, was es in
diesem Weg NICHT geben darf. Beissen sie nicht, ist der Waechter fuer die
Kernzusage blind.

⚠ EINE SABOTAGE MUSS DIE ZUSAGE ENTFERNEN, NICHT DEN CODE KAPUTT MACHEN. Ein
NameError oder SyntaxError laesst den Waechter mit Exit 2 abbrechen, und ein
Abbruch ist von einem bestandenen Lauf nicht zu unterscheiden (Register; beim
Bau von gegen_mcp_lifespan zweimal bezahlt).

Exit 0 = alle beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.

    venv/bin/python tests/gegen_mcp_tls.py
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_mcp_tls.py"
TLS = "backend/mcp_tls.py"
WI = "tests/test_mcp_tls.py"
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() \
    else sys.executable

PROBEN = [
    # ── PRODUKT: die Kernzusage – die Pruefung bleibt AN ───────────────────
    ("PRODUKT Pruefung aus (CERT_NONE im Verbindungsweg)", TLS,
     "    ctx = ssl.create_default_context()\n"
     "    ctx.check_hostname = True\n"
     "    ctx.verify_mode = ssl.CERT_REQUIRED\n",
     "    ctx = ssl.create_default_context()\n"
     "    ctx.check_hostname = False\n"
     "    ctx.verify_mode = ssl.CERT_NONE\n"),
    ("PRODUKT Hostname wird nicht mehr geprueft", TLS,
     "    ctx.check_hostname = True\n", "    ctx.check_hostname = False\n"),
    # ── PRODUKT: ein eigenes Zert ERSETZT die System-CAs ───────────────────
    # `create_default_context` laedt sie; ein nackter SSLContext nicht. Damit
    # braeche derselbe Server, sobald er ein regulaeres Zertifikat bekommt.
    ("PRODUKT System-CAs fallen weg (eigenes Zert ERSETZT statt ergaenzt)", TLS,
     "    ctx = ssl.create_default_context()\n",
     "    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)\n"),
    # ── PRODUKT: die Pfad-Schranke ─────────────────────────────────────────
    ("PRODUKT Schluessel-Formate werden gelesen (.key/.p12)", TLS,
     "    schluessel = {\".key\", \".p12\", \".pfx\", \".jks\", \".keystore\", \".keytab\"}\n",
     "    schluessel = set()\n"),
    ("PRODUKT Dienst-Geheimnisse werden gelesen", TLS,
     "    if name in sandbox._SECRET_NAMES or name.startswith(\".env\"):\n",
     "    if False:\n"),
    ("PRODUKT gesperrte Orte werden gelesen (/root, /etc/jarvis)", TLS,
     "    if s == \"/root\" or s.startswith(sandbox._SYSTEM_DENY_PREFIX):\n",
     "    if False:\n"),
    ("PRODUKT relative Pfade werden angenommen", TLS,
     "    if not p.is_absolute():\n", "    if False:\n"),
    ("PRODUKT die Schutzpruefung wird fail-OPEN", TLS,
     "    except Exception:  # noqa: BLE001\n"
     "        # Fail-closed: laesst sich die Schranke nicht befragen, wird nicht\n",
     "    except Exception:  # noqa: BLE001\n"
     "        geschuetzt, grund = False, \"\"\n"
     "    if False:\n"
     "        # Fail-closed: laesst sich die Schranke nicht befragen, wird nicht\n"),
    # ── PRODUKT: Ansehen ist kein Vertrauen ────────────────────────────────
    ("PRODUKT kein Fingerabdruck mehr (nichts zu vergleichen)", TLS,
     "    aus[\"fingerprint_sha256\"] = \":\".join(\n",
     "    aus[\"fingerabdruck_weg\"] = \":\".join(\n"),
    ("PRODUKT Fingerabdruck ueber SHA1 statt SHA256", TLS,
     "        \"%02X\" % b for b in cert.fingerprint(hashes.SHA256()))\n",
     "        \"%02X\" % b for b in cert.fingerprint(hashes.SHA1()))\n"),
    ("PRODUKT keine Befunde mehr (blosses ok/nicht-ok)", TLS,
     "    aus[\"befunde\"] = befunde\n", "    aus[\"befunde\"] = []\n"),
    ("PRODUKT selbstsigniert faellt nicht auf", TLS,
     "    if aus[\"selbstsigniert\"]:\n"
     "        befunde.append(\"selbstsigniert (kein Aussteller, dem das System traut)\")\n",
     "    if False:\n"
     "        befunde.append(\"selbstsigniert (kein Aussteller, dem das System traut)\")\n"),
    # ⚠ NICHT `= True` -> `= False` sabotieren: das Testzertifikat ist
    # selbstsigniert, `vertraut_system` ist dort SO ODER SO False – die Probe
    # aenderte den gemessenen Fall nicht und blieb stumm. Eine Sabotage muss
    # den Fall treffen, den der Waechter herstellt (Register). Entfernt wird
    # deshalb der SCHLUESSEL: dann fehlt die Aussage ganz, und der Durchstich
    # sieht `None` statt `False`.
    ("PRODUKT der regulaere Gegentest faellt weg (vertraut_system)", TLS,
     "        aus[\"vertraut_system\"] = False\n",
     "        aus[\"gegentest_weg\"] = False\n"),
    ("PRODUKT http gilt als pruefbar", TLS,
     "    if teile.scheme != \"https\":\n", "    if False:\n"),
    ("PRODUKT Wildcard deckt auch den nackten Namen", TLS,
     "            if h.endswith(\".\" + rest) and h.count(\".\") == m.count(\".\"):\n",
     "            if h.endswith(rest):\n"),
    ("PRODUKT die Beschreibung gibt das Zertifikat heraus", TLS,
     "    return \"eigenes CA-Zertifikat (PEM-Block)\" if ist_pem(roh) \\\n",
     "    return roh if ist_pem(roh) \\\n"),
    # ── PRODUKT: Pinning (2026-10-25) – die Sicherheit haengt an DREI Grenzen ──
    # ⚠ Die wichtigste Probe: Pinning MIT System-CAs. Dann vertraute
    # `check_hostname=False` jedem CA-signierten Zertifikat fuer JEDEN Host.
    ("PRODUKT Pinning laedt die System-CAs (offenes Tor)", TLS,
     "        pin = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)\n",
     "        pin = ssl.create_default_context()\n"),
    # Die Grenze liegt seit dem theben-Befund nicht mehr an CA:TRUE, sondern
    # an "fuer einen Server ausgestellt". Eine echte Root-CA (CA:TRUE, OHNE
    # Server-Namen) darf nie gepinnt werden – sonst gilt jeder ihrer Server
    # fuer jede Adresse.
    ("PRODUKT eine echte Root-CA wird gepinnt (jeder ihrer Server ueberall)", TLS,
     "        if not hat_servernamen:\n            return False\n",
     "        if False:\n            return False\n"),
    # Und die Gegenrichtung, der gemeldete Fall: CA:TRUE schliesst wieder aus,
    # ein Zertifikat aus `openssl req -x509` wird nie gepinnt.
    ("PRODUKT CA:TRUE schliesst aus (theben wird nie gepinnt)", TLS,
     "    if ist_ca:\n        try:\n",
     "    if ist_ca:\n        return False\n        try:\n"),
    ("PRODUKT eine Kette wird gepinnt", TLS,
     "    if str(pem).count(\"BEGIN CERTIFICATE\") != 1:\n        return False\n",
     "    if False:\n        return False\n"),
    ("PRODUKT Pinning ohne CERT_REQUIRED (jedes Zert kommt durch)", TLS,
     "        pin.verify_mode = ssl.CERT_REQUIRED\n",
     "        pin.verify_mode = ssl.CERT_NONE\n"),
    ("PRODUKT Pinning greift nicht (der gemeldete Fall: IP lehnt ab)", TLS,
     "    if ist_pem(roh) and _ist_server_zert_zum_pinnen(roh):\n",
     "    if False:\n"),
    # ── SONDE: schlagen die Positivkontrollen an? ──────────────────────────
    # ⚠ HIER IST EXIT 2 DAS RICHTIGE ERGEBNIS, kein Mangel. Ohne gueltiges
    # Testmaterial kann der Waechter nichts messen – und "konnte nicht laufen"
    # von "bestanden" zu trennen ist der ganze Zweck der Exit-2-Stufe. Eine
    # Probe, die das als Biss zaehlt, wuerde einen kaputten Pruefstand fuer
    # eine Messung halten (Register). Deshalb traegt die Probe ihre erwartete
    # Art mit.
    ("SONDE das Testzertifikat wird nicht mehr erzeugt", WI,
     "    pem = cert.public_bytes(serialization.Encoding.PEM).decode()\n",
     "    pem = \"kein Zertifikat\"\n", "abbruch"),
    # Und eine Sonde, die FAIL ergeben MUSS: ein gueltiges, aber ANDERES
    # Zertifikat – dann sind die Vergleiche falsch, der Lauf aber messbar.
    ("SONDE der Vergleich bekommt ein fremdes Zertifikat", WI,
     "check(\"dasselbe Zertifikat gilt als hinterlegt\",\n"
     "      T.passt_zum_gespeicherten(PEM, PEM) is True)\n",
     "check(\"dasselbe Zertifikat gilt als hinterlegt\",\n"
     "      T.passt_zum_gespeicherten(PEM, _zert(cn=\"fremd.invalid\")) is True)\n",
     "fail"),
]

DATEIEN = [TLS, WI]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, object]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run([PY, str(WAECHTER)], capture_output=True, text=True,
                           timeout=300, cwd=str(ROOT), env=env)
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), 0


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an: %s"
              % sorted({p[1] for p in PROBEN} - set(DATEIEN)))
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    beissen = 0
    try:
        for probe in PROBEN:
            name, datei, alt, neu = probe[:4]
            erwartet = probe[4] if len(probe) > 4 else "fail"
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %-58s Anker %dx" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0 and erwartet == "fail":
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, fails))
            elif fails < 0 and erwartet == "abbruch":
                # Erwartet: der Waechter MUSS hier abbrechen (Exit 2), weil
                # sein Material kaputt ist. Das ist der Biss dieser Probe.
                beissen += 1
                print("  BISS %-58s Exit 2 (erwartet)" % name)
            elif fails < 0:
                print("  ABBR %-58s konnte nicht laufen (rc=%s) – erwartet "
                      "war ein FAIL" % (name, rc))
            elif fails > 0:
                print("  ??!  %-58s %d FAIL – erwartet war Exit 2"
                      % (name, fails))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
