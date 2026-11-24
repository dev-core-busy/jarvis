#!/usr/bin/env python3
"""Gegenproben: sensible Laeufe nur auf internen LLMs (backend/llm_standort.py).

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob
``tests/test_llm_standort.py`` beisst. Eine Probe, die nicht beisst, ist ein
Testmangel – kein Beweis.

Sabotiert wird eine KOPIE (Wegwerf-Baum je Probe, Vorbild
``gegen_sensibel.py``), nie der Arbeitsbaum: der Betreiber arbeitet parallel
an ``main.py``, ``agent.py`` und ``llm.py``.

Gezaehlt wird nur ein ECHTER Biss: Exit 1 MIT Bilanzzeile und mindestens einem
FAIL. Exit 2 oder ein Absturz ohne Bilanz zaehlt als NICHT gebissen.

    venv/bin/python tests/gegen_llm_standort.py
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PY = "tests/test_llm_standort.py"
FRONT = ["frontend/js/prompt_check.js", "frontend/js/tracks.js"]


def baum() -> Path:
    wurzel = Path(tempfile.mkdtemp(prefix="gegen_llm_standort_"))
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "backend", wurzel / "backend", ignore=ign)
    for rel in FRONT + [PY]:
        ziel = wurzel / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, ziel)
    (wurzel / "data").mkdir()
    return wurzel


def lauf(wurzel: Path) -> tuple[int, int, bool]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run([sys.executable, PY], cwd=wurzel, capture_output=True,
                           text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return (124, -1, False)
    treffer = re.findall(r"Ergebnis: (\d+) OK, (\d+) FAIL", p.stdout + p.stderr)
    if not treffer:
        return (p.returncode, -1, False)
    return (p.returncode, int(treffer[-1][1]), True)


def patch(wurzel: Path, rel: str, alt: str, neu: str) -> None:
    p = wurzel / rel
    s = p.read_text(encoding="utf-8")
    n = s.count(alt)
    if n != 1:
        raise SystemExit("ABBRUCH: Sabotage-Anker in %s trifft %d-mal statt einmal:\n%s"
                         % (rel, n, alt[:160]))
    p.write_text(s.replace(alt, neu), encoding="utf-8")


PROBEN = []


def probe(name, *aenderungen):
    PROBEN.append((name, aenderungen))


S, L, AG, MA, CO = ("backend/llm_standort.py", "backend/llm.py", "backend/agent.py",
                    "backend/main.py", "backend/config.py")
PC = "frontend/js/prompt_check.js"

# ── Riegel ──
probe("Riegel-Huelle wird nicht angelegt",
      (L, "                setattr(cls, _name, _riegel_umhuellen(_f))", "                pass"))
probe("Riegel laesst alles durch",
      (S, "    intern, grund = ziel_intern(provider_kennung, api_url)\n    if intern:\n        return",
          "    intern, grund = ziel_intern(provider_kennung, api_url)\n    if True:\n        return"))
probe("Provider meldet seine Adresse nicht",
      (L, "        return (str(self.anbieter_kennung), self.base_url)",
          "        return (str(self.anbieter_kennung), \"\")"))
probe("Hand-extern eines Profils zaehlt fuer das Ziel nicht",
      (S, '    if "extern" in hand:\n', '    if False:\n'))
# ── Erkennung ──
probe("oeffentliche IP gilt als intern",
      (S, "    return bool(ip.is_private) and not ip.is_global", "    return True"))
probe("CGNAT gilt als intern",
      (S, "    return bool(ip.is_private) and not ip.is_global",
          "    return bool(ip.is_private) or not ip.is_global"))
probe("Cloud-Liste wird nicht befragt",
      (S, "    for d in _CLOUD_DOMAINS:\n", "    for d in ():\n"))
probe("Google/Anthropic nicht mehr fest extern",
      (S, '    if prov in _IMMER_EXTERN:\n        return "extern", "fester Cloud-Endpunkt des Anbieters"\n', ""))
probe("unbekannt gilt als intern",
      (S, '    return bool(profil) and einstufen(profil)["standort"] == "intern"',
          '    return bool(profil) and einstufen(profil)["standort"] != "extern"'))
# Je EIN Weg je Probe (Register: eine Probe, die auf mehreren Wegen trifft,
# misst keinen davon): IP-Literal und DNS-Name laufen getrennt.
# Das IP-Literal faellt danach ueber _ip_intern trotzdem auf intern – die
# Probe misst, dass der GRUND das Netz nennt (sonst weiss niemand, warum).
probe("interne Netze: Grund nennt das Netz nicht",
      (S, "        netz = _im_eigenen_netz(getattr(ip, \"ipv4_mapped\", None) or ip)\n",
          "        netz = \"\"\n"))
probe("interne Netze: DNS-Adressen werden nicht geprueft",
      (S, "    if ip.is_loopback or ip.is_link_local or _im_eigenen_netz(ip):",
          "    if ip.is_loopback or ip.is_link_local:"))
probe("interne Netze: Speichern nimmt auch Teilmengen",
      (CO, "            if not _falsch:\n                self.INTERNE_NETZE", "            if True:\n                self.INTERNE_NETZE"))
probe("DNS-Ergebnis wird nicht gemerkt",
      (S, "    if c and jetzt - c[0] < _DNS_GUELTIG_S:", "    if False:"))
probe("Hand-intern fuer Google wird beim Speichern angenommen",
      (S, '    if w == "intern" and _norm(provider) in _IMMER_EXTERN:', '    if False:'))
# ── Ersatzprofil ──
probe("Ersatz ignoriert das Profilrecht",
      (S, "        if ist_intern(p) and _darf(benutzer, p):", "        if ist_intern(p):"))
probe("eingestelltes Profil gilt auch extern",
      (S, "        if p is not None and ist_intern(p):\n            return p",
          "        if p is not None:\n            return p"))
probe("provider_fuer_lauf wechselt nicht",
      (L, "    p = _sensibel_profil_waehlen(p if isinstance(p, dict) and p else None)\n", ""))
probe("provider_fuer_bild nimmt das externe Bildprofil",
      (L, "            if not llm_standort.ist_intern(_bp):", "            if False:"))
# ── Agent ──
probe("Rolle umgeht den Wechsel",
      (AG, "                    self._active_profile = p\n                    self._sensibel_profil_anwenden()\n",
           "                    self._active_profile = p\n"))
probe("Agent ersetzt das externe Profil nicht",
      (AG, "        if ersatz:\n            self._active_profile = ersatz", "        if False:\n            self._active_profile = ersatz"))
probe("Statuszeile wird nicht gesendet",
      (AG, "        _sens_zeile = self._sensibel_statuszeile()\n", "        _sens_zeile = ''\n"))
probe("Sperrtext wird von den Anbieter-Mustern umgedeutet",
      (AG, '    if type(exc).__name__ == "ExternGesperrt":\n        return "🔒 " + str(exc)\n', ""))
# ── Verdrahtung ──
probe("Prompt-Pruefung ohne sensiblen Rahmen",
      (MA, '        async with _sensibel.anfrage(body.get("sensibel") is True):\n            erg = await',
           '        if True:\n            erg = await'))
probe("Einstellung nimmt auch externe Profile",
      (CO, "                if llm_standort.ist_intern(_p):\n                    self.SENSIBEL_PROFILE_ID = _neu",
           "                if True:\n                    self.SENSIBEL_PROFILE_ID = _neu"))
probe("prompt_check.js schickt den Schalter nicht",
      (PC, "                    sensibel: !!(sensEl && sensEl.checked),\n", "                    sensibel: false,\n"))

# ── Ablauf ──────────────────────────────────────────────────────────────────
for name, aend in PROBEN:
    for rel, _a, _n in aend:
        if not (rel.startswith("backend/") or rel in FRONT):
            print("ABBRUCH: Probe '%s' sabotiert %s, das nicht kopiert wird" % (name, rel))
            sys.exit(2)

basis = baum()
try:
    code, fails, bilanz = lauf(basis)
    if code != 0 or fails != 0 or not bilanz:
        print("ABBRUCH: Basis ist nicht gruen (exit=%s FAIL=%s Bilanz=%s) – mit dem venv starten?"
              % (code, fails, bilanz))
        sys.exit(2)
finally:
    shutil.rmtree(basis, ignore_errors=True)
print("Basis gruen (Wegwerf-Baum)\n")

stumm, abgestuerzt = [], []
for name, aend in PROBEN:
    w = baum()
    try:
        for rel, alt, neu in aend:
            patch(w, rel, alt, neu)
        code, fails, bilanz = lauf(w)
    finally:
        shutil.rmtree(w, ignore_errors=True)
    if code == 1 and bilanz and fails > 0:
        print("  BEISST  %-58s %d FAIL" % (name, fails))
    elif not bilanz or code not in (0, 1):
        abgestuerzt.append(name)
        print("  ABSTURZ %-58s exit=%s (kein Biss)" % (name, code))
    else:
        stumm.append(name)
        print("  STUMM   %-58s" % name)

print("\n%d Proben: %d beissen, %d stumm, %d abgestuerzt"
      % (len(PROBEN), len(PROBEN) - len(stumm) - len(abgestuerzt), len(stumm), len(abgestuerzt)))
sys.exit(1 if (stumm or abgestuerzt) else 0)
