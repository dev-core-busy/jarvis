#!/usr/bin/env python3
"""Waechter: Zeitplan und Verlauf der automatischen Sicherheitsupdates
(backend/apt_upgrades.py: verlauf_parsen, eingespielt, zeitplan).

Hintergrund (2026-10-29): Die Auftragsliste zeigt jetzt einen Eintrag fuer
Debians unattended-upgrades (cron.js _renderSystem). Die Daten dafuer:
  * ``/var/log/apt/history.log`` – feste englische Schluessel; NUR Bloecke mit
    ``Commandline: /usr/bin/unattended-upgrade`` zaehlen (von Hand
    eingespielte Pakete stehen in derselben Datei).
  * ``systemctl list-timers --output=json`` – Mikrosekunden, 0 = unbekannt.
Das Material unten ist dem echten Format von DEV nachgebaut (Doppel-Leerraum
im Datum, Epoch-Versionen ``1:153…``, zwei Bloecke eines Laufs).

Lauf:  python3 tests/test_apt_verlauf.py [pfad/zu/apt_upgrades.py]
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
"""
import gzip
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path

HIER = Path(__file__).resolve().parent
MODUL = Path(sys.argv[1]) if len(sys.argv) > 1 else HIER.parent / "backend" / "apt_upgrades.py"

ergebnisse = []


def pruefe(name, bed, detail=""):
    ergebnisse.append(bool(bed))
    print(("  OK    " if bed else "  FAIL  ") + name + ("" if bed or not detail else " – " + str(detail)))


def laden():
    spec = importlib.util.spec_from_file_location("apt_upgrades_probe", MODUL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HISTORY = """
Start-Date: 2026-10-25  06:59:50
Commandline: /usr/bin/unattended-upgrade
Upgrade: libbrotli1:amd64 (1.1.0-2+b7, 1.1.0-2+deb13u1)
End-Date: 2026-10-25  06:59:51

Start-Date: 2026-10-26  07:24:09
Commandline: apt-get install -y --only-upgrade nodejs
Upgrade: nodejs:amd64 (24.22.0-1nodesource1, 24.22.1-1nodesource1)
End-Date: 2026-10-26  07:24:12

Start-Date: 2026-10-28  06:17:48
Commandline: /usr/bin/unattended-upgrade
Upgrade: thunderbird:amd64 (1:153.5.1esr-1~deb13u1, 1:153.5.1esr-1~deb13u2)
End-Date: 2026-10-28  06:17:53

Start-Date: 2026-10-28  06:17:54
Commandline: /usr/bin/unattended-upgrade
Install: libneu1:amd64 (2.0-1, automatic)
Upgrade: openjdk-21-jre-headless:amd64 (21.0.12.1+1-1~deb13u1, 21.0.13+9-1~deb13u2), libx:amd64 (1.0, 1.1)
Error: Sub-process /usr/bin/dpkg returned an error code (1)
End-Date: 2026-10-28  06:17:57
"""

ALT = """
Start-Date: 2026-09-30  06:05:10
Commandline: /usr/bin/unattended-upgrade
Upgrade: libalt:amd64 (0.9, 1.0)
End-Date: 2026-09-30  06:05:12
"""


def ts(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


def main() -> int:
    try:
        m = laden()
        for n in ("verlauf_parsen", "eingespielt", "zeitplan"):
            if not callable(getattr(m, n, None)):
                raise AttributeError(n)
    except Exception as e:  # noqa: BLE001
        print(f"ABBRUCH: Modul nicht ladbar ({type(e).__name__}: {e})")
        return 2

    v = m.verlauf_parsen(HISTORY)
    # Positivkontrolle: das Material wird ueberhaupt erkannt – sonst waeren
    # alle Pruefungen unten ueber eine leere Liste trivial.
    if not v:
        print("ABBRUCH: Positivkontrolle – kein einziger Block aus dem Material erkannt")
        return 2

    print("1. verlauf_parsen")
    pruefe("genau die drei unattended-Bloecke (der Handlauf von nodejs zaehlt nicht)",
           len(v) == 3, [x.get("pakete") for x in v])
    namen = [p["name"] for x in v for p in x["pakete"]]
    pruefe("nodejs (von Hand eingespielt) fehlt", "nodejs" not in namen, namen)
    pruefe("Architektur abgeschnitten (libbrotli1, nicht libbrotli1:amd64)", "libbrotli1" in namen, namen)
    tb = next((p for x in v for p in x["pakete"] if p["name"] == "thunderbird"), {})
    pruefe("Epoch-Version bleibt ganz (1:153.5.1esr-1~deb13u1 -> …u2)",
           tb.get("von") == "1:153.5.1esr-1~deb13u1" and tb.get("nach") == "1:153.5.1esr-1~deb13u2", tb)
    vier = v[2] if len(v) > 2 else {"pakete": [], "fehler": ""}
    neu = next((p for p in vier["pakete"] if p["name"] == "libneu1"), {})
    pruefe("Install: neue Fassung ist die ERSTE Angabe, 'automatic' keine Version",
           neu.get("nach") == "2.0-1" and neu.get("von") == "" and neu.get("neu") is True, neu)
    pruefe("mehrere Pakete in einer Upgrade-Zeile", {"openjdk-21-jre-headless", "libx"}
           <= {p["name"] for p in vier["pakete"]}, vier["pakete"])
    pruefe("Error-Zeile wird getragen", "error code" in vier.get("fehler", ""), vier.get("fehler"))
    pruefe("Startzeit mit Doppel-Leerraum gelesen",
           v[0].get("start") == ts("2026-10-25 06:59:50"), v[0].get("start"))
    pruefe("leerer/kaputter Text wirft nicht", m.verlauf_parsen("") == []
           and m.verlauf_parsen("Start-Date: kaputt\nCommandline: /usr/bin/unattended-upgrade") is not None)

    print("2. eingespielt (Dateien im Wegwerf-Verzeichnis)")
    with tempfile.TemporaryDirectory() as tmp:
        akt, rot = Path(tmp) / "history.log", Path(tmp) / "history.log.1.gz"
        m.HISTORY = (str(akt), str(rot))
        pruefe("keine Datei lesbar -> None (NICHT die leere Liste)", m.eingespielt() is None,
               m.eingespielt())
        akt.write_text("Start-Date: 2026-10-01  10:00:00\nCommandline: apt-get install x\n"
                       "End-Date: 2026-10-01  10:00:01\n")
        pruefe("lesbar, aber nichts automatisch eingespielt -> []", m.eingespielt() == [],
               m.eingespielt())
        akt.write_text(HISTORY)
        with gzip.open(rot, "wt") as f:
            f.write(ALT)
        e = m.eingespielt()
        pruefe("rotierte .gz-Datei wird mitgelesen", any(p["name"] == "libalt"
               for x in (e or []) for p in x["pakete"]), e)
        starts = [x["start"] for x in (e or [])]
        pruefe("neueste zuerst", starts == sorted(starts, reverse=True) and len(starts) == 4, starts)
        pruefe("max_n begrenzt", len(m.eingespielt(2) or []) == 2)
        akt.unlink()
        pruefe("nur die rotierte Datei da (Monatswechsel) -> trotzdem Verlauf",
               [p["name"] for x in (m.eingespielt() or []) for p in x["pakete"]] == ["libalt"])

    print("3. zeitplan (systemctl als Attrappe mit der echten Ausgabeform)")

    class R:
        def __init__(self, out, rc=0):
            self.stdout, self.stderr, self.returncode = out, "", rc

    def attrappe(timer_out, show_out):
        def _run(cmd, timeout=30, env=None):
            if "list-timers" in cmd:
                return R(timer_out)
            if "show" in cmd:
                return R(show_out)
            return R("", 1)
        return _run

    echt = json.dumps([{"next": 1793338814692996, "left": 1793338814692996, "last": 1793250579983821,
                        "passed": 301482817729, "unit": "apt-daily-upgrade.timer",
                        "activates": "apt-daily-upgrade.service"}])
    m._run = attrappe(echt, "Result=success\nExecMainStatus=0\n")
    z = m.zeitplan()
    pruefe("Mikrosekunden -> Sekunden", abs((z.get("naechster") or 0) - 1793338814.692996) < 1e-3
           and abs((z.get("letzter") or 0) - 1793250579.983821) < 1e-3, z)
    pruefe("Ergebnis und Exit gelesen", z.get("ergebnis") == "success" and z.get("exit") == 0, z)
    m._run = attrappe(json.dumps([{"next": 0, "last": 0, "unit": "apt-daily-upgrade.timer"}]), "")
    z = m.zeitplan()
    pruefe("0 = unbekannt -> None, nicht 1970", z.get("naechster") is None and z.get("letzter") is None, z)
    m._run = attrappe(json.dumps([{"next": 5_000_000, "last": 4_000_000, "unit": "apt-daily.timer"}]), "")
    pruefe("fremder Timer wird nicht genommen", m.zeitplan().get("letzter") is None)
    m._run = attrappe("kein json", "Result=\nExecMainStatus=\n")
    z = m.zeitplan()
    pruefe("kaputte Ausgabe wirft nicht und meldet unbekannt",
           z.get("letzter") is None and z.get("exit") is None, z)

    ok = sum(ergebnisse)
    print(f"\nErgebnis: {ok}/{len(ergebnisse)}")
    return 0 if ok == len(ergebnisse) else 1


if __name__ == "__main__":
    sys.exit(main())
