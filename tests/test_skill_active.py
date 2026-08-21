#!/usr/bin/env python3
"""Waechter fuer `main.py::_skill_active` – der Manifest-Standard muss zaehlen.

DER GEMELDETE FALL (2026-08-21): Auf ECHT fehlte die Portal-Kachel "Excel" und
`/excel` antwortete 404, obwohl der Skill lief und seine Werkzeuge bereitstellte.
Ursache war NICHT der Skill, sondern dieser eine Wachposten: er las
`config.get_skill_states()`, und das liefert ausschliesslich, was in der
settings.json steht. Ein Skill, den nie jemand umgeschaltet hat, hat dort keinen
Eintrag – `st.get("enabled")` war `None`, also "aus".

Der SkillManager entscheidet dagegen mit `state.get("enabled",
skill_info.get("enabled", True))`, mischt also den Manifest-Standard ein. Damit
gab es im System ZWEI Meinungen darueber, ob ein Skill aktiv ist. Dieser Test
haelt fest, dass es wieder eine ist.

Laeuft OHNE fastapi: die Funktionen werden per `ast` aus main.py geschnitten und
gegen eine Attrappe von `config` ausgefuehrt. `backend.config` wird ausdruecklich
NICHT importiert – der echte Import migriert Profile und schriebe die
Live-settings.json zurueck.
"""
import ast
import json
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MAIN = WURZEL / "backend" / "main.py"
MANAGER = WURZEL / "backend" / "skills" / "manager.py"

_ok = 0
_fail = 0


def pruefe(bedingung, text):
    global _ok, _fail
    if bedingung:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {text}")


def hole_funktionen(quelle: Path, namen) -> str:
    """Schneidet benannte Top-Level-Funktionen samt Zuweisungen per ast heraus.

    Bewusst ast statt Textsuche: ein Schnitt "von def bis zum naechsten def"
    nimmt im Zweifel fremden Code mit – genau daran ist am 2026-08-18 ein
    Waechter trivial wahr geworden.
    """
    baum = ast.parse(quelle.read_text(encoding="utf-8"))
    zeilen = quelle.read_text(encoding="utf-8").splitlines()
    teile = []
    for knoten in baum.body:
        treffer = (isinstance(knoten, ast.FunctionDef) and knoten.name in namen) or (
            isinstance(knoten, ast.AnnAssign)
            and isinstance(knoten.target, ast.Name)
            and knoten.target.id in namen
        )
        if treffer:
            teile.append("\n".join(zeilen[knoten.lineno - 1:knoten.end_lineno]))
    return "\n\n".join(teile)


class ConfigAttrappe:
    def __init__(self, zustaende):
        self._z = zustaende

    def get_skill_states(self):
        return self._z


def baue(zustaende, skills_wurzel: Path):
    """Fuehrt die geschnittenen Funktionen mit Attrappen aus und gibt sie zurueck."""
    quelle = hole_funktionen(
        MAIN, {"_skill_active", "_manifest_enabled", "_MANIFEST_ENABLED_CACHE"}
    )
    raum = {"config": ConfigAttrappe(zustaende), "Path": Path}
    exec(compile(quelle, "<skill_active>", "exec"), raum)  # noqa: S102
    # `_manifest_enabled` leitet den Pfad aus __file__ von main.py ab; im Test
    # zeigen wir auf ein Wegwerf-Verzeichnis, damit nie das echte skills/
    # gelesen wird (und der Test ohne Repo-Layout laeuft).
    #
    # FEHLT die Funktion (alter Stand), wird NICHT abgebrochen: ein Waechter
    # muss FEHLSCHLAGEN, nicht sterben – sonst sieht die Gegenprobe aus wie ein
    # bestandener Lauf. Im Projekt schon mehrfach passiert.
    raum.setdefault("_MANIFEST_ENABLED_CACHE", {})

    def ersatz(name, _raum=raum):
        cache = _raum["_MANIFEST_ENABLED_CACHE"]
        if name in cache:
            return cache[name]
        wert = False
        f = skills_wurzel / name / "skill.json"
        if f.exists():
            try:
                wert = bool(json.loads(f.read_text(encoding="utf-8")).get("enabled", True))
            except Exception:
                wert = False
        cache[name] = wert
        return wert

    raum["_manifest_enabled"] = ersatz
    return raum["_skill_active"], raum


def lege_skill(wurzel: Path, name: str, enabled):
    d = wurzel / name
    d.mkdir(parents=True, exist_ok=True)
    inhalt = {"name": name}
    if enabled is not None:
        inhalt["enabled"] = enabled
    (d / "skill.json").write_text(json.dumps(inhalt), encoding="utf-8")


def main():
    print("=" * 70)
    print("_skill_active – Manifest-Standard zaehlt")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmp:
        s = Path(tmp)
        lege_skill(s, "excel-addin", True)     # Manifest sagt AN
        lege_skill(s, "email", False)          # Manifest sagt AUS
        lege_skill(s, "ohne-flag", None)       # kein enabled → Vorgabe True

        # ── 1. Der gemeldete Fall: kein Eintrag in settings.json ──────────
        print("\n1. Kein Eintrag in settings.json (der gemeldete Fall)")
        aktiv, _ = baue({}, s)
        pruefe(aktiv("excel-addin") is True,
               "excel-addin ohne Eintrag muss AKTIV sein (Manifest enabled:true)")
        pruefe(aktiv("email") is False,
               "email ohne Eintrag muss AUS sein (Manifest enabled:false)")
        pruefe(aktiv("ohne-flag") is True,
               "Skill ohne enabled-Feld: Vorgabe True (wie im SkillManager)")

        # ── 2. Ein ausdruecklicher Eintrag gewinnt IMMER ──────────────────
        print("2. Ausdruecklicher Eintrag ueberstimmt das Manifest")
        aktiv, _ = baue({"excel-addin": {"enabled": False}}, s)
        pruefe(aktiv("excel-addin") is False,
               "ausdrueckliches enabled:false muss das Manifest ueberstimmen")
        aktiv, _ = baue({"email": {"enabled": True}}, s)
        pruefe(aktiv("email") is True,
               "ausdrueckliches enabled:true muss das Manifest ueberstimmen")

        # `enabled: false` darf NICHT als "kein Eintrag" gelten – das ist der
        # Unterschied zwischen `"enabled" in st` und `st.get("enabled")`.
        aktiv, _ = baue({"excel-addin": {"enabled": False, "installed": True}}, s)
        pruefe(aktiv("excel-addin") is False,
               "enabled:false neben anderen Feldern bleibt AUS")

        # ── 3. Nicht installiert = nicht aktiv ────────────────────────────
        print("3. Fehlendes Verzeichnis = nicht installiert")
        aktiv, _ = baue({}, s)
        pruefe(aktiv("gibt-es-nicht") is False,
               "unbekannter Skill ohne Verzeichnis muss False liefern")
        # Ein Zustandseintrag ohne Verzeichnis (Altbestand nach Purge) zaehlt
        # weiterhin, wenn er ausdruecklich AN sagt – so verhaelt sich auch der
        # SkillManager; das Verzeichnis fehlt dann schlicht beim Laden.
        aktiv, _ = baue({"gibt-es-nicht": {"enabled": True}}, s)
        pruefe(aktiv("gibt-es-nicht") is True,
               "ausdruecklicher Eintrag wirkt auch ohne Manifest")

        # ── 4. Fehler duerfen nicht durchschlagen ─────────────────────────
        print("4. Fehlertoleranz")
        (s / "kaputt").mkdir()
        (s / "kaputt" / "skill.json").write_text("{kein json", encoding="utf-8")
        aktiv, _ = baue({}, s)
        pruefe(aktiv("kaputt") is False,
               "unlesbares Manifest → False, keine Ausnahme")

        class Explodiert:
            def get_skill_states(self):
                raise RuntimeError("kaputt")

        quelle = hole_funktionen(
            MAIN, {"_skill_active", "_manifest_enabled", "_MANIFEST_ENABLED_CACHE"}
        )
        raum = {"config": Explodiert(), "Path": Path}
        exec(compile(quelle, "<x>", "exec"), raum)  # noqa: S102
        pruefe(raum["_skill_active"]("egal") is False,
               "Ausnahme in get_skill_states → False statt Absturz")

        # ── 5. Der Cache darf nicht zwischen Skills verrutschen ───────────
        print("5. Cache je Skill")
        aktiv, raum = baue({}, s)
        aktiv("excel-addin"), aktiv("email")
        pruefe(aktiv("excel-addin") is True and aktiv("email") is False,
               "zweiter Aufruf liefert je Skill denselben Wert (Cache korrekt)")

    # ── 6. Drift-Schranke gegen den SkillManager ──────────────────────────
    print("6. Beide Stellen sind sich einig")
    mgr = MANAGER.read_text(encoding="utf-8")
    pruefe('state.get("enabled", skill_info.get("enabled", True))' in mgr,
           "SkillManager mischt den Manifest-Standard ein (Grundlage dieses Tests)")
    quelle_akt = hole_funktionen(MAIN, {"_skill_active"})
    pruefe("_manifest_enabled" in quelle_akt,
           "_skill_active zieht den Manifest-Standard heran")
    pruefe('"enabled" in st' in quelle_akt,
           "_skill_active unterscheidet 'Eintrag fehlt' von 'Eintrag ist false'")
    pruefe("st.get(\"enabled\"))" not in quelle_akt.replace('bool(st["enabled"])', ""),
           "kein blosses st.get('enabled') mehr – das war der Fehler")

    # ── 7. Der Ausloeser: excel-addin ist der einzige mit enabled:true ────
    print("7. Warum es erst jetzt auffiel")
    xl = json.loads((WURZEL / "skills" / "excel-addin" / "skill.json")
                    .read_text(encoding="utf-8"))
    pruefe(xl.get("enabled") is True,
           "excel-addin steht im Manifest auf enabled:true")
    gated = ["sap", "email", "short-tracks", "userchat", "avatar"]
    andere = []
    for n in gated:
        f = WURZEL / "skills" / n / "skill.json"
        if f.exists():
            andere.append(json.loads(f.read_text(encoding="utf-8")).get("enabled"))
    pruefe(all(v is False for v in andere) and andere,
           "alle uebrigen ueber _skill_active abgesicherten Skills stehen auf false")

    print("\n" + "=" * 70)
    print(f"Ergebnis: {_ok} bestanden, {_fail} fehlgeschlagen")
    print("=" * 70)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
