"""Skill Manager – verwaltet alle Skills (Built-in + externe)."""

import glob
import importlib.metadata as _im
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from backend.skills.loader import SkillLoader
from backend.config import config

# Repo-Wurzel (…/backend/skills/manager.py → drei Ebenen hoch)
REPO_ROOT = Path(__file__).parent.parent.parent


def _canon(name: str) -> str:
    """Kanonischer pip-Paketname (PEP 503): klein, -/_/. vereinheitlicht."""
    return re.sub(r"[-_.]+", "-", (name or "").strip()).lower()


def _spec_name(spec: str) -> str:
    """Extrahiert den Paketnamen aus einer Requirement-Zeile ('foo>=1.2' → 'foo')."""
    return _canon(re.split(r"[<>=!~\[;(\s]", spec.strip(), maxsplit=1)[0])


class SkillManager:
    """Zentrale Verwaltung aller Jarvis Skills."""

    def __init__(self):
        self.loader = SkillLoader()
        # Install-Status pro Skill: {running, ok, log[]}
        self._install_status: dict[str, dict] = {}
        # Optionaler Callback nach erfolgreicher Hintergrund-Installation
        # (main.py haengt hier das Agent-Tool-Reload ein)
        self.post_install_hook = None
        self._load_enabled_skills()

    def _load_enabled_skills(self):
        """Lädt alle aktivierten Skills."""
        self.loader.loaded_skills.clear()
        skill_states = config.get_skill_states()

        for skill_info in self.loader.discover_skills():
            if "error" in skill_info:
                continue

            skill_name = Path(skill_info["path"]).name
            state = skill_states.get(skill_name, {})
            # Enabled aus Config oder aus Manifest-Default
            enabled = state.get("enabled", skill_info.get("enabled", True))

            if enabled:
                try:
                    self.loader.load_skill(skill_name)
                except Exception as e:
                    print(f"Skill '{skill_name}' konnte nicht geladen werden: {e}")

    def list_skills(self) -> list[dict]:
        """Gibt alle Skills mit Manifest und Status zurück."""
        skills = []
        skill_states = config.get_skill_states()

        for skill_info in self.loader.discover_skills():
            if "error" in skill_info:
                skills.append(skill_info)
                continue

            skill_name = Path(skill_info["path"]).name
            state = skill_states.get(skill_name, {})

            skill_info["enabled"] = state.get("enabled", skill_info.get("enabled", True))
            # "installed" steuert die UI-Einordnung (Installierte vs. Moegliche).
            # Getrennt von "enabled": ein installierter Skill kann ausgeschaltet
            # sein und bleibt trotzdem unter "Installierte". Fallback (kein Flag
            # gesetzt) = enabled-Zustand → abwaertskompatibel.
            skill_info["installed"] = state.get("installed", skill_info["enabled"])
            skill_info["config"] = state.get("config", {})
            skill_info["loaded"] = skill_name in self.loader.loaded_skills

            skills.append(skill_info)

        return skills

    def enable_skill(self, name: str) -> dict:
        """Aktiviert einen Skill (und markiert ihn als installiert).

        Fehlen deklarierte Abhaengigkeiten (pip/apt/install_commands), laeuft
        die Installation im Hintergrund-Thread; Fortschritt via
        get_install_status(). Rueckgabe: {success, installing}.
        """
        config.save_skill_state(name, {"enabled": True, "installed": True})
        info = self._skill_info(name) or {}

        missing_pip = self._missing_dependencies(info)
        pending_cmds = self._pending_install_commands(info)
        missing_apt = self._missing_system_packages(info)

        if missing_pip or pending_cmds or missing_apt:
            self._start_install(name, info, missing_pip, missing_apt, pending_cmds)
            return {"success": True, "installing": True}

        ok = True
        try:
            self.loader.load_skill(name)
        except Exception as e:
            print(f"Skill '{name}' konnte nicht aktiviert werden: {e}")
            ok = False
        # An den Skill gekoppelten systemd-Dienst (z.B. whatsapp-bridge) mitstarten
        self._control_skill_service(name, start=True)
        return {"success": ok, "installing": False}

    # ─── Installations-Lifecycle ──────────────────────────────────────

    def _skill_info(self, name: str) -> dict | None:
        """Manifest-Info eines Skills aus discover_skills()."""
        for s in self.loader.discover_skills():
            if "error" not in s and Path(s["path"]).name == name:
                return s
        return None

    @staticmethod
    def _installed_packages() -> set[str]:
        """Kanonische Namen aller im venv installierten pip-Pakete."""
        pkgs = set()
        for dist in _im.distributions():
            try:
                pkgs.add(_canon(dist.metadata["Name"]))
            except Exception:  # noqa: BLE001
                continue
        return pkgs

    def _missing_dependencies(self, info: dict) -> list[str]:
        """Noch nicht installierte pip-Abhaengigkeiten (volle Specs)."""
        installed = self._installed_packages()
        return [d for d in info.get("dependencies", []) if _spec_name(d) not in installed]

    @staticmethod
    def _missing_system_packages(info: dict) -> list[str]:
        """Noch nicht installierte apt-Pakete (Pruefung via dpkg -s)."""
        missing = []
        for pkg in info.get("system_packages", []):
            try:
                r = subprocess.run(["dpkg", "-s", pkg], capture_output=True, timeout=10)
                if r.returncode != 0:
                    missing.append(pkg)
            except Exception:  # noqa: BLE001
                missing.append(pkg)
        return missing

    @staticmethod
    def _pending_install_commands(info: dict) -> list[dict]:
        """install_commands, deren 'creates'-Pfad noch fehlt (leer = immer faellig)."""
        pending = []
        for cmd in info.get("install_commands", []):
            creates = cmd.get("creates")
            if creates and (REPO_ROOT / creates).exists():
                continue
            pending.append(cmd)
        return pending

    def _start_install(self, name, info, missing_pip, missing_apt, pending_cmds):
        """Startet die Hintergrund-Installation (idempotent pro Skill)."""
        st = self._install_status.get(name)
        if st and st.get("running"):
            return
        status = {"running": True, "ok": None, "log": []}
        self._install_status[name] = status
        t = threading.Thread(
            target=self._install_worker,
            args=(name, info, missing_pip, missing_apt, pending_cmds, status),
            daemon=True, name=f"skill-install-{name}",
        )
        t.start()

    def _install_worker(self, name, info, missing_pip, missing_apt, pending_cmds, status):
        """Installiert apt-Pakete (Broker), pip-Pakete und Zusatzbefehle, laedt
        den Skill danach und startet den gekoppelten Dienst."""
        log = status["log"]
        ok = True
        try:
            if missing_apt:
                log.append(f"Installiere Systempakete: {', '.join(missing_apt)} …")
                ok = self._apt_install(missing_apt, log) and ok

            if missing_pip:
                log.append(f"Installiere Python-Pakete: {', '.join(missing_pip)} …")
                try:
                    proc = subprocess.Popen(
                        [sys.executable, "-m", "pip", "install", *missing_pip],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    )
                    for line in proc.stdout:
                        line = line.rstrip()
                        if line:
                            log.append(line)
                    proc.wait(timeout=1800)
                    if proc.returncode != 0:
                        log.append(f"pip install fehlgeschlagen (rc={proc.returncode})")
                        ok = False
                except Exception as e:  # noqa: BLE001
                    log.append(f"pip install Fehler: {e}")
                    ok = False

            for cmd in pending_cmds:
                argv = cmd.get("cmd") or []
                cwd = REPO_ROOT / cmd.get("cwd", ".")
                log.append(f"Fuehre aus: {' '.join(argv)} (in {cmd.get('cwd', '.')}) …")
                try:
                    r = subprocess.run(argv, cwd=str(cwd), capture_output=True,
                                       text=True, timeout=900)
                    if r.returncode != 0:
                        log.append(f"Befehl fehlgeschlagen (rc={r.returncode}): "
                                   f"{(r.stderr or '').strip()[:300]}")
                        ok = False
                except Exception as e:  # noqa: BLE001
                    log.append(f"Befehl-Fehler: {e}")
                    ok = False

            # Skill laden (auch bei Teil-Fehlern versuchen – Import entscheidet)
            try:
                self.loader.load_skill(name)
                log.append(f"Skill '{name}' geladen.")
            except Exception as e:  # noqa: BLE001
                log.append(f"Skill laden fehlgeschlagen: {e}")
                ok = False

            self._control_skill_service(name, start=True)

            if ok and callable(self.post_install_hook):
                try:
                    self.post_install_hook()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            status["ok"] = ok
            status["running"] = False
            log.append("Installation abgeschlossen." if ok
                       else "Installation mit Fehlern beendet.")

    def _apt_install(self, packages: list[str], log: list) -> bool:
        """apt-Installation ueber den Root-Broker (best-effort)."""
        try:
            from backend import broker_client
        except Exception as e:  # noqa: BLE001
            log.append(f"Broker-Client nicht verfuegbar: {e}")
            return False
        cmd = "DEBIAN_FRONTEND=noninteractive apt-get install -y " + " ".join(packages)
        res = broker_client.call_sync("shell_root", {"command": cmd},
                                      timeout=900, stream_cb=lambda l: log.append(l))
        if res.get("ok"):
            return True
        if res.get("decision") == "pending":
            log.append("Systempakete warten auf Root-Freigabe "
                       "(Einstellungen → Sicherheit → Root-Freigaben).")
        else:
            log.append(f"Systempaket-Installation fehlgeschlagen: "
                       f"{res.get('error') or res.get('stderr') or res}")
        return False

    def get_install_status(self, name: str) -> dict:
        """Installations-Fortschritt eines Skills ({running, ok, log})."""
        st = self._install_status.get(name)
        if not st:
            return {"running": False, "ok": None, "log": []}
        return {"running": st["running"], "ok": st["ok"], "log": list(st["log"][-100:])}

    def disable_skill(self, name: str) -> bool:
        """Deaktiviert einen Skill, laesst ihn aber installiert (bleibt unter
        'Installierte Skills', nur ausgeschaltet)."""
        config.save_skill_state(name, {"enabled": False, "installed": True})
        self.loader.unload_skill(name)
        # Gekoppelten systemd-Dienst ebenfalls stoppen+deaktivieren
        self._control_skill_service(name, start=False)
        return True

    def remove_skill(self, name: str) -> bool:
        """Entfernt einen Skill aus 'Installierte' (→ zurueck zu 'Moegliche'),
        OHNE die Dateien zu loeschen. Nicht-destruktive Alternative zum 'x':
        deaktiviert + markiert als nicht installiert."""
        config.save_skill_state(name, {"enabled": False, "installed": False})
        self.loader.unload_skill(name)
        self._control_skill_service(name, start=False)
        return True

    def purge_skill(self, name: str, remove_data: bool = False) -> dict:
        """Deinstalliert einen Skill vollstaendig: Dienst stoppen, pip-Pakete
        entfernen (nur wenn kein anderer Skill/Kern sie braucht), optional
        Daten und Caches loeschen. Der Skill-Code (git-getrackt) bleibt liegen.

        Rueckgabe-Report: removed_packages, kept_packages{pkg: grund},
        removed_paths, errors.
        """
        report = {"removed_packages": [], "kept_packages": {},
                  "removed_paths": [], "errors": []}
        info = self._skill_info(name)
        if not info:
            report["errors"].append(f"Skill '{name}' nicht gefunden")
            return report

        # Deaktivieren + aus 'Installierte' nehmen + Dienst stoppen
        config.save_skill_state(name, {"enabled": False, "installed": False})
        self.loader.unload_skill(name)
        self._control_skill_service(name, start=False)

        # Kandidaten: purge_packages (falls gesetzt), sonst dependencies
        specs = info.get("purge_packages") or info.get("dependencies", [])
        candidates = {_spec_name(s) for s in specs}
        installed = self._installed_packages()

        # Schutz 1: Kern-Abhaengigkeiten aus requirements.txt
        protected: dict[str, str] = {}
        req_file = REPO_ROOT / "requirements.txt"
        if req_file.exists():
            for line in req_file.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if line:
                    protected.setdefault(_spec_name(line), "Kern (requirements.txt)")

        # Schutz 2: andere installierte Skills (dependencies + optional_dependencies)
        skill_states = config.get_skill_states()
        for s in self.loader.discover_skills():
            if "error" in s or Path(s["path"]).name == name:
                continue
            other = Path(s["path"]).name
            state = skill_states.get(other, {})
            if not state.get("installed", state.get("enabled", s.get("enabled", True))):
                continue
            for d in s.get("dependencies", []) + s.get("optional_dependencies", []):
                protected.setdefault(_spec_name(d), f"Skill '{other}'")

        # Schutz 3: Reverse-Abhaengigkeiten aller installierten Pakete
        # (Extras werden ignoriert – nur harte Requirements zaehlen)
        rev: dict[str, set[str]] = {}
        for dist in _im.distributions():
            try:
                dn = _canon(dist.metadata["Name"])
            except Exception:  # noqa: BLE001
                continue
            for req in dist.requires or []:
                if ";" in req and "extra" in req.split(";", 1)[1]:
                    continue
                rev.setdefault(_spec_name(req), set()).add(dn)

        removal = {c for c in candidates if c in installed and c not in protected}
        for c in sorted(candidates - removal):
            if c not in installed:
                report["kept_packages"][c] = "nicht installiert"
            elif c in protected:
                report["kept_packages"][c] = f"benoetigt von {protected[c]}"

        # Fixpunkt: Paket nur entfernen, wenn alle Abhaengigen mit entfernt werden
        changed = True
        while changed:
            changed = False
            for c in list(removal):
                dependents = rev.get(c, set()) - removal
                if dependents:
                    removal.discard(c)
                    report["kept_packages"][c] = ("benoetigt von "
                                                  + ", ".join(sorted(dependents)))
                    changed = True

        if removal:
            try:
                r = subprocess.run(
                    [sys.executable, "-m", "pip", "uninstall", "-y", *sorted(removal)],
                    capture_output=True, text=True, timeout=600)
                if r.returncode == 0:
                    report["removed_packages"] = sorted(removal)
                else:
                    report["errors"].append(f"pip uninstall fehlgeschlagen: "
                                            f"{(r.stderr or '').strip()[:300]}")
            except Exception as e:  # noqa: BLE001
                report["errors"].append(f"pip uninstall Fehler: {e}")

        # Daten + Caches nur auf ausdruecklichen Wunsch
        if remove_data:
            targets = [REPO_ROOT / d for d in info.get("data_dirs", [])]
            for pattern in info.get("caches", []):
                targets += [Path(p) for p in
                            glob.glob(str(Path(pattern).expanduser()))]
            for target in targets:
                if not target.exists():
                    continue
                if not self._safe_to_delete(target):
                    report["errors"].append(f"Pfad ausserhalb erlaubter Bereiche: {target}")
                    continue
                try:
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                    report["removed_paths"].append(str(target))
                except Exception as e:  # noqa: BLE001
                    report["errors"].append(f"Loeschen fehlgeschlagen ({target}): {e}")

        return report

    @staticmethod
    def _safe_to_delete(path: Path) -> bool:
        """Nur Pfade im Repo oder im ~/.cache des Dienst-Users duerfen weg."""
        try:
            p = path.resolve()
        except Exception:  # noqa: BLE001
            return False
        allowed = [REPO_ROOT.resolve(), (Path.home() / ".cache").resolve()]
        return any(str(p).startswith(str(a) + os.sep) for a in allowed)

    def _skill_service(self, name: str) -> str | None:
        """Liest das Feld 'systemd_service' aus dem Skill-Manifest, falls vorhanden."""
        for s in self.loader.discover_skills():
            if "error" in s:
                continue
            if Path(s["path"]).name == name:
                svc = s.get("systemd_service")
                return svc.strip() if isinstance(svc, str) and svc.strip() else None
        return None

    def _control_skill_service(self, name: str, start: bool):
        """Koppelt einen optionalen systemd-Dienst an den Skill-Zustand.

        Skill aktiviert -> Dienst 'enable --now', deaktiviert -> 'disable --now'.
        Best-effort: schlaegt fehl lautlos (kein systemctl, kein Root, keine Unit),
        damit das Aktivieren/Deaktivieren des Skills nie daran scheitert.
        """
        svc = self._skill_service(name)
        if not svc:
            return
        unit = svc if svc.endswith(".service") else svc + ".service"
        verb = "gestartet+aktiviert" if start else "gestoppt+deaktiviert"

        # Bevorzugt ueber den Root-Broker (unprivilegiertes Backend)
        try:
            from backend import broker_client
            res = broker_client.call_sync(
                "systemctl",
                {"action": "enable" if start else "disable", "unit": unit, "now": True},
                timeout=60)
            if res.get("ok"):
                print(f"Skill '{name}': Dienst {unit} {verb} (Broker).")
                return
            if res.get("decision") != "unreachable":
                print(f"Skill '{name}': Broker-Dienststeuerung ({unit}) fehlgeschlagen: "
                      f"{res.get('error') or res.get('stderr') or res}")
        except Exception as e:  # noqa: BLE001
            print(f"Skill '{name}': Broker nicht nutzbar ({e}) – Fallback systemctl.")

        # Fallback: direktes systemctl (Alt-Betrieb, Backend als root)
        if not shutil.which("systemctl"):
            return
        action = ["enable", "--now"] if start else ["disable", "--now"]
        try:
            r = subprocess.run(["systemctl", *action, unit],
                               capture_output=True, text=True, timeout=20)
            if r.returncode == 0:
                print(f"Skill '{name}': Dienst {unit} {verb}.")
            else:
                print(f"Skill '{name}': Dienst {unit} konnte nicht {verb} werden "
                      f"(rc={r.returncode}): {(r.stderr or '').strip()[:200]}")
        except Exception as e:
            print(f"Skill '{name}': Dienststeuerung ({unit}) fehlgeschlagen: {e}")

    def get_skill_config(self, name: str) -> dict:
        """Gibt die Konfiguration eines Skills zurück."""
        states = config.get_skill_states()
        return states.get(name, {}).get("config", {})

    def update_skill_config(self, name: str, data: dict) -> bool:
        """Aktualisiert die Konfiguration eines Skills."""
        states = config.get_skill_states()
        state = states.get(name, {})
        current_config = state.get("config", {})
        current_config.update(data)
        state["config"] = current_config
        if "enabled" not in state:
            state["enabled"] = True
        config.save_skill_state(name, state)
        return True

    def get_enabled_tools(self) -> list:
        """Gibt alle Tools von aktivierten Skills zurück."""
        tools = []
        for skill_name, skill_data in self.loader.loaded_skills.items():
            tools.extend(skill_data["tools"])
        return tools

    def is_readonly(self, skill_name: str) -> bool:
        """Gibt True zurück wenn der Skill als readonly markiert ist."""
        manifest = self.loader.loaded_skills.get(skill_name, {}).get("manifest", {})
        return bool(manifest.get("readonly", False))

    def get_tool_skill(self, tool_name: str) -> str | None:
        """Gibt den Skill-Namen zurück, der ein bestimmtes Tool bereitstellt."""
        for skill_name, skill_data in self.loader.loaded_skills.items():
            for tool in skill_data.get("tools", []):
                if getattr(tool, "name", None) == tool_name:
                    return skill_name
        return None

    def is_tool_readonly(self, tool_name: str) -> bool:
        """Gibt True zurück wenn das Tool von einem readonly-Skill stammt."""
        skill_name = self.get_tool_skill(tool_name)
        if skill_name:
            return self.is_readonly(skill_name)
        return False

    def install_dependencies(self, name: str) -> str:
        """Installiert die Abhängigkeiten eines Skills."""
        skills = self.loader.discover_skills()
        skill_info = None
        for s in skills:
            if Path(s.get("path", "")).name == name:
                skill_info = s
                break

        if not skill_info:
            return f"Skill '{name}' nicht gefunden"

        deps = skill_info.get("dependencies", [])
        if not deps:
            return "Keine Abhängigkeiten definiert"

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install"] + deps,
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                joined = ', '.join(deps)
                return f"Abhängigkeiten installiert: {joined}"
            return f"Fehler: {result.stderr}"
        except Exception as e:
            return f"Fehler bei Installation: {e}"

    def uninstall_skill(self, name: str) -> bool:
        """Entfernt einen Skill (nur nicht-system Skills)."""
        skills = self.loader.discover_skills()
        for s in skills:
            if Path(s.get("path", "")).name == name:
                if s.get("system", False):
                    return False
                self.loader.unload_skill(name)
                shutil.rmtree(s["path"])
                config.remove_skill_state(name)
                return True
        return False

    def reload_all(self):
        """Lädt alle Skills neu."""
        self._load_enabled_skills()
