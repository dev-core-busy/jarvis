"""Durchsetzung der Lizenzgrenzen.

Getrennt von `license.py`, weil das eine die *Feststellung* ist (welche Stufe
gilt) und das andere die *Folge* (was darf noch benutzt werden). Die Trennung
haelt `license.py` frei von Importen auf Skill-Manager, Wissensdatenbank und
Benutzerbuchhaltung – und macht die Feststellung testbar, ohne dass ein Test
versehentlich Skills abschaltet.

Zwei Sorten Grenzen, die sich im Verhalten unterscheiden:

* **Torwaechter** (`darf_*`): fragen vor einer Handlung. Sie lehnen ab und
  erklaeren, was fehlt – es passiert nichts Ueberraschendes.
* **Nachfuehrung** (`anwenden`): laeuft nach jedem Lizenz-Prueflauf und bringt
  einen bestehenden Zustand auf die erlaubte Groesse. Nur hier wird von sich
  aus etwas abgeschaltet, und ausdruecklich erst, wenn die Einfuehrungs-Karenz
  abgelaufen ist (siehe license.EINFUEHRUNG_KARENZ_TAGE).

Was die Nachfuehrung NICHT anfasst: Profile (ein geloeschtes Profil waere
Datenverlust – dort greift nur der Torwaechter beim Anlegen und die Auswahl des
aktiven Profils), Wissensdateien und Benutzerkonten. Angefasst werden nur
Skills (abschalten) und der Auto-Update-Auftrag (entfernen) – beides ist
umkehrbar und beides sind Handlungen des Systems, keine Kundendaten.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from backend import license as lic

# Zeitfenster fuer "aktive Benutzer": wer sich in dieser Zeit angemeldet hat,
# zaehlt gegen die Grenze. Ein Konto, das ein halbes Jahr ruht, tut das nicht.
BENUTZER_FENSTER_SEK = lic.BENUTZER_FENSTER_TAGE * 86400

# Konten, die NIE gegen die Benutzergrenze zaehlen und nie abgewiesen werden.
# `jarvis` ist der lokale Rueckweg in die Oberflaeche (dieselbe Begruendung wie
# bei der AD-Freigabe: eine Grenze, die den Betreiber aus seinen eigenen
# Einstellungen aussperrt, ist schlimmer als die Luecke, die sie schliesst –
# er koennte den Lizenzschluessel sonst gar nicht mehr eintragen).
# `api` ist der Agent-API-Benutzer, kein Mensch.
FREIE_KONTEN = {"jarvis", "api", "root", "system"}


def _norm(username: str) -> str:
    name = (username or "").strip().lower()
    if "@" in name:
        name = name.split("@", 1)[0]
    if "\\" in name:
        name = name.rsplit("\\", 1)[1]
    return name


# ─── Zaehlungen ────────────────────────────────────────────────────────────

def anzahl_profile() -> int:
    try:
        from backend.config import config
        return len(config.profiles or [])
    except Exception:
        return 0


def aktive_skills() -> list[str]:
    """Namen der aktiven Skills, in der Reihenfolge, in der sie abgeschaltet
    wuerden (zuletzt aktivierte zuerst).

    Sortiert nach `enabled_at` absteigend; Bestand ohne Zeitstempel gilt als
    aelter und steht damit hinten – innerhalb dieser Gruppe in umgekehrter
    Listenreihenfolge, so wie abgesprochen.

    **Gezaehlt wird dasselbe wie in der Skill-Liste der Oberflaeche**, also
    `state.enabled` ODER – wenn es gar keinen Eintrag gibt – der Vorgabewert
    aus dem Manifest. Auf DEV waren das 19 statt 13 Skills: sechs liefen ohne
    Eintrag in settings.json ueber ihren Manifest-Standard. Eine Zaehlung nur
    ueber die gespeicherten Zustaende haette sie weder gezaehlt noch je
    abgeschaltet – die Grenze waere auf einem frisch installierten System
    praktisch wirkungslos gewesen (dort hat NIEMAND einen Eintrag).
    """
    try:
        from backend.config import config
        zustaende = config.get_skill_states() or {}
    except Exception:
        zustaende = {}

    namen: list[str] = []
    sm = _skill_manager()
    if sm is not None and hasattr(sm, "list_skills"):
        try:
            for s in sm.list_skills():
                if "error" in s or not s.get("enabled"):
                    continue
                # Der VERZEICHNISname ist der Schluessel in den Skill-Zustaenden
                # und das, was disable_skill erwartet – der Anzeigename aus dem
                # Manifest kann davon abweichen.
                name = Path(s.get("path", "")).name
                if name:
                    namen.append(name)
        except Exception:  # noqa: BLE001
            namen = []
    if not namen:
        # Rueckfall: nur die gespeicherten Zustaende. Untertreibt moeglicherweise
        # (siehe oben), ist aber besser als gar keine Grenze.
        namen = [n for n, st in zustaende.items() if (st or {}).get("enabled")]

    aktiv = []
    for index, name in enumerate(namen):
        st = zustaende.get(name) or {}
        aktiv.append((float(st.get("enabled_at") or 0), index, name))
    aktiv.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [name for _, _, name in aktiv]


def anzahl_skills() -> int:
    return len(aktive_skills())


def anzahl_benutzer() -> int:
    """Verschiedene Personen mit Anmeldung in den letzten 30 Tagen."""
    return len(_benutzer_menge())


def _benutzer_menge() -> set[str]:
    try:
        from backend import user_sessions
        grenze_ts = time.time() - BENUTZER_FENSTER_SEK
        menge = set()
        for u in user_sessions.list_users():
            name = _norm(u.get("username", ""))
            if not name or name in FREIE_KONTEN:
                continue
            # last_seen deckt auch Sitzungen ab, die ohne frischen Login
            # weiterlaufen; last_login allein wuerde Daueranmeldungen uebersehen.
            if max(float(u.get("last_seen") or 0), float(u.get("last_login") or 0)) >= grenze_ts:
                menge.add(name)
        return menge
    except Exception:
        return set()


def _skill_manager():
    """SkillManager beschaffen, OHNE `backend.main` zu importieren.

    Der Weg ueber main.py waere ein Zirkelimport (main importiert dieses Modul)
    und wuerde fastapi in jeden Testlauf ziehen. Im laufenden Dienst ist
    `backend.main` aber ohnehin geladen – dann wird dessen Instanz benutzt,
    denn nur sie kennt den Agenten und laedt dessen Werkzeuge nach.
    """
    modul = sys.modules.get("backend.main")
    if modul is not None and hasattr(modul, "_get_skill_manager"):
        try:
            return modul._get_skill_manager()
        except Exception:  # noqa: BLE001
            pass
    try:
        from backend.skills.manager import SkillManager
        return SkillManager()
    except Exception:  # noqa: BLE001
        return None


def _skill_abschalten(name: str) -> None:
    """Einen Skill deaktivieren – moeglichst ueber den Manager.

    Der Manager macht mehr als ein Flag zu setzen: er entlaedt die Werkzeuge
    und stoppt einen gekoppelten systemd-Dienst (z.B. die WhatsApp-Bridge).
    Ohne ihn liefe der Dienst weiter, obwohl der Skill als aus gilt. Der
    Rueckfall auf die reine Zustandsaenderung ist die Notloesung, damit die
    Grenze auch dann greift.
    """
    sm = _skill_manager()
    if sm is not None and hasattr(sm, "disable_skill"):
        sm.disable_skill(name)
        return
    from backend.config import config
    config.save_skill_state(name, {"enabled": False, "installed": True})


def anzahl_rag() -> int:
    """Dateien in der Wissensdatenbank (nicht Chunks).

    Von anderen Standorten GESPIEGELTE Dateien zaehlen NICHT mit: sie sind dort
    schon lizenziert, und diese Installation haelt nur eine Kopie. Wuerden sie
    mitzaehlen, wuerde ein Pull von 300 fremden Dateien die Grenze reissen und
    danach jeden eigenen Upload sperren – die Kopie waere damit eine Strafe.

    Grundlage ist der Stand des letzten Sync-Laufs (`gespiegelte_dateien`), kein
    zweiter Verzeichnis-Durchlauf: diese Funktion haengt an jeder Upload-Pruefung.
    """
    try:
        from backend.tools.knowledge import get_disk_file_count
        n = int(get_disk_file_count() or 0)
    except Exception:
        return 0
    try:
        from backend import knowledge_sync
        n -= knowledge_sync.gespiegelte_dateien()
    except Exception:  # noqa: BLE001
        pass
    return max(0, n)


# ─── Torwaechter ───────────────────────────────────────────────────────────

def _grenze(name: str):
    z = lic.zustand()
    if not z.get("durchsetzung_aktiv"):
        return None
    return z["grenzen"].get(name)


def _text(was: str, grenze_wert: int, ist: int) -> str:
    z = lic.zustand()
    return (f"Lizenzgrenze erreicht: {was} {ist}/{grenze_wert} "
            f"(Lizenz {z.get('art', 'FREE')}). "
            "Eine höhere Lizenz hebt die Grenze auf – Einstellungen → "
            "KI & System → System-Einstellungen.")


def darf_profil_anlegen() -> tuple[bool, str]:
    g = _grenze("profile")
    if g is None:
        return True, ""
    ist = anzahl_profile()
    if ist >= g:
        return False, _text("LLM-Profile", g, ist)
    return True, ""


def darf_skill_aktivieren(name: str = "") -> tuple[bool, str]:
    g = _grenze("skills")
    if g is None:
        return True, ""
    aktiv = aktive_skills()
    if name and name in aktiv:
        return True, ""     # schon an – erneutes Einschalten aendert nichts
    if len(aktiv) >= g:
        return False, _text("aktive Skills", g, len(aktiv))
    return True, ""


def darf_benutzer_anmelden(username: str) -> tuple[bool, str]:
    """Grenze fuer die Zahl verschiedener Personen.

    Bereits gezaehlte Benutzer kommen immer durch – die Grenze soll den Kreis
    begrenzen, nicht denjenigen aussperren, der gerade arbeitet. Abgewiesen
    wird nur ein NEUES Konto, wenn der Kreis schon voll ist.
    """
    g = _grenze("benutzer")
    if g is None:
        return True, ""
    name = _norm(username)
    if not name or name in FREIE_KONTEN:
        return True, ""
    menge = _benutzer_menge()
    if name in menge:
        return True, ""
    if len(menge) >= g:
        return False, (f"Die Lizenz erlaubt {g} verschiedene Benutzer in "
                       f"{lic.BENUTZER_FENSTER_TAGE} Tagen, aktuell sind es "
                       f"{len(menge)}. Bitte den Administrator ansprechen.")
    return True, ""


def darf_wissen_hinzufuegen(anzahl: int = 1) -> tuple[bool, str]:
    """Grenze fuer die Wissensdatenbank.

    Der Bestand bleibt immer lesbar und durchsuchbar – gesperrt ist nur das
    Hinzufuegen. Eine Lizenzgrenze darf vorhandenes Wissen nicht unerreichbar
    machen.
    """
    g = _grenze("rag")
    if g is None:
        return True, ""
    ist = anzahl_rag()
    if ist + max(1, int(anzahl or 1)) > g:
        return False, (f"Lizenzgrenze erreicht: Wissensdatenbank {ist}/{g} Dateien "
                       f"(Lizenz {lic.zustand().get('art', 'FREE')}). "
                       "Vorhandene Dateien bleiben nutzbar.")
    return True, ""


# ─── Nachfuehrung ──────────────────────────────────────────────────────────

def anwenden(zustand: dict | None = None) -> dict:
    """Bestehenden Zustand auf die erlaubte Groesse bringen.

    Laeuft nach jedem Lizenz-Prueflauf. Rueckgabe = Bericht fuer Oberflaeche
    und Audit-Log. Fasst NUR Skills an (siehe Modulkopf).
    """
    z = zustand or lic.zustand()
    bericht = {"skills_deaktiviert": [], "hinweise": []}
    if not z.get("durchsetzung_aktiv"):
        return bericht

    g = z["grenzen"].get("skills")
    if g is not None:
        aktiv = aktive_skills()
        ueber = len(aktiv) - g
        if ueber > 0:
            from backend import audit_log
            for name in aktiv[:ueber]:
                try:
                    _skill_abschalten(name)
                    bericht["skills_deaktiviert"].append(name)
                except Exception as e:  # noqa: BLE001
                    bericht["hinweise"].append(f"{name}: {e}")
            if bericht["skills_deaktiviert"]:
                print(f"[Lizenz] {len(bericht['skills_deaktiviert'])} Skill(s) wegen "
                      f"Lizenzgrenze deaktiviert: "
                      f"{', '.join(bericht['skills_deaktiviert'])}", flush=True)
                try:
                    audit_log.log_tool("system", "lizenz_skills_deaktiviert",
                                       {"skills": bericht["skills_deaktiviert"],
                                        "grenze": g, "art": z.get("art")}, 0, 0)
                except Exception:
                    pass

    # Zeitgesteuertes Update abraeumen, wenn die Lizenz es nicht mehr traegt.
    # Der Cron-Job laeuft ueber den Scheduler und damit AM Endpunkt vorbei –
    # ohne diesen Schritt liefe ein einmal eingerichtetes Auto-Update nach
    # einer Herabstufung einfach weiter, und die Sperre am Endpunkt waere
    # eine Fassade.
    if not z["grenzen"].get("auto_update"):
        try:
            from backend.config import config
            from backend.scheduler import cron_manager
            if config.get_setting("auto_update_schedule", "never") != "never":
                config.save_setting("auto_update_schedule", "never")
                bericht["hinweise"].append(
                    "Automatisches Update abgeschaltet (Lizenz erlaubt es nicht).")
            if cron_manager.delete_job("system_auto_update"):
                bericht["auto_update_entfernt"] = True
                print("[Lizenz] Zeitgesteuertes Update entfernt "
                      f"(Lizenz {z.get('art')}).", flush=True)
        except Exception as e:  # noqa: BLE001
            bericht["hinweise"].append(f"Auto-Update: {e}")

    # Profile werden NICHT geloescht. Ist die Grenze ueberschritten, sagt das
    # nur der Bericht – nutzbar ist dann das aktive Profil (siehe
    # profil_nutzbar), die uebrigen bleiben unangetastet auf Platte.
    gp = z["grenzen"].get("profile")
    if gp is not None and anzahl_profile() > gp:
        bericht["hinweise"].append(
            f"{anzahl_profile()} LLM-Profile vorhanden, die Lizenz erlaubt {gp} – "
            "nutzbar ist das aktive Profil.")
    return bericht


def profil_nutzbar(profil_id: str) -> bool:
    """Darf dieses Profil benutzt werden?

    Bei einer Profil-Grenze von 1 ist das ausschliesslich das aktive Profil.
    Nichts wird geloescht oder ausgeblendet – ein spaeteres Upgrade macht die
    uebrigen Profile ohne Zutun wieder nutzbar.
    """
    g = _grenze("profile")
    if g is None:
        return True
    try:
        from backend.config import config
        erlaubt = [p["id"] for p in (config.profiles or [])][:0]
        aktiv = config.active_profile_id
        if aktiv:
            erlaubt = [aktiv]
        # Falls kein aktives Profil gesetzt ist: die ersten g der Liste.
        if not erlaubt:
            erlaubt = [p["id"] for p in (config.profiles or [])[:g]]
        return profil_id in erlaubt
    except Exception:
        return True


def uebersicht() -> dict:
    """Zahlen fuer die Oberflaeche: Verbrauch je Grenze."""
    z = lic.zustand()
    g = z["grenzen"]
    return {
        "profile": {"ist": anzahl_profile(), "max": g.get("profile")},
        "skills": {"ist": anzahl_skills(), "max": g.get("skills")},
        "benutzer": {"ist": anzahl_benutzer(), "max": g.get("benutzer"),
                     "fenster_tage": lic.BENUTZER_FENSTER_TAGE},
        "rag": {"ist": anzahl_rag(), "max": g.get("rag")},
        "updates": g.get("updates"),
        "auto_update": g.get("auto_update"),
    }
