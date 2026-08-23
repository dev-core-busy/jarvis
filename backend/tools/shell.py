"""Shell Tool – fuehrt Kommandozeilen-Befehle aus, mit optionalem Live-Streaming.

Rechte-Modell (Trennung UI-/Ausfuehrungsebene):
- Das Backend laeuft unprivilegiert (jarvis.service, User=jarvis). Normale
  Befehle laufen als Dienst-Benutzer.
- Befehle nicht-privilegierter (Domain-)Benutzer laufen als Sandbox-OS-User –
  die runuser-Umschaltung braucht root und laeuft daher ueber den Root-Broker.
- Root-Befehle privilegierter Benutzer (systemctl, apt, mount, ...) laufen
  ueber die Broker-Operation shell_root: jeder neue Befehl erscheint als
  auditierbarer Pending-Eintrag, den ein Admin erlauben/ablehnen muss
  (Einstellungen → Sicherheit → Root-Freigaben).
"""

import asyncio
import os
import re

from backend.tools.base import BaseTool
from backend.config import config

# Programme, die root brauchen (erstes Wort eines Befehls-Segments).
_ROOT_PROGRAMS = {
    "systemctl", "service", "apt", "apt-get", "dpkg", "snap",
    "useradd", "userdel", "usermod", "groupadd", "adduser", "deluser",
    "passwd", "chpasswd", "nft", "iptables", "ip6tables", "ufw",
    "mount", "umount", "swapon", "swapoff",
    "reboot", "shutdown", "poweroff", "halt", "fdisk", "parted",
    "certbot", "timedatectl", "hostnamectl", "localectl",
    "update-alternatives", "modprobe", "rmmod", "insmod", "visudo",
}
# systemctl-Subkommandos, die auch unprivilegiert funktionieren (nur lesen)
_SYSTEMCTL_READONLY = {
    "status", "is-active", "is-enabled", "is-failed", "show", "cat",
    "list-units", "list-timers", "list-unit-files", "list-sockets",
}


def _needs_root(command: str) -> bool:
    """Heuristik: braucht der Befehl root? (fuer Routing ueber den Root-Broker)
    Prueft jedes Shell-Segment (getrennt durch && || ; |) auf sudo bzw.
    bekannte root-pflichtige Programme."""
    for seg in re.split(r'&&|\|\||;|\|', command or ""):
        words = seg.strip().split()
        if not words:
            continue
        prog = words[0]
        if prog == "sudo":
            return True
        base = prog.rsplit("/", 1)[-1]
        if base.startswith("mkfs"):
            return True
        if base in _ROOT_PROGRAMS:
            if base == "systemctl" and len(words) > 1 and words[1] in _SYSTEMCTL_READONLY:
                continue
            return True
    return False



# ---------------------------------------------------------------------------
# Fehlende Python-Module: Klartext statt blindem Weitersuchen
#
# Shell-Befehle des Agenten laufen mit /usr/bin/python3 (bei Domain-Benutzern
# zusaetzlich als Sandbox-OS-User), NICHT im venv des Backends. Was dort fehlt,
# meldet Python nur als "ModuleNotFoundError: No module named 'x'" - und das
# Modell schliesst daraus regelmaessig, die FAEHIGKEIT fehle. Auf ECHT ist so
# am 2026-08-18 eine Excel-Anfrage in einer CSV-Notloesung geendet, nachdem
# vier Schritte mit dem Suchen nach openpyxl verbrannt waren.
#
# Die Zuordnung nennt deshalb den ERSATZWEG, nicht die Abwesenheit. Sie behauptet
# bewusst NICHT, welche Module vorhanden sind: das liesse sich hier nur im
# Backend-Prozess pruefen, und der laeuft im venv - also in einer anderen
# Python-Welt als der Befehl. Eine solche Auskunft waere im Zweifel falsch.
_MODUL_ERSATZ = {
    "openpyxl":   "Fuer Excel-Dateien das Werkzeug office_create_excel benutzen (erzeugt .xlsx und liefert den Download).",
    "xlsxwriter": "Fuer Excel-Dateien das Werkzeug office_create_excel benutzen.",
    "xlwt":       "Fuer Excel-Dateien das Werkzeug office_create_excel benutzen.",
    "docx":       "Fuer Word-Dokumente das Werkzeug office_create_word benutzen.",
    "pptx":       "Fuer Praesentationen das Werkzeug office_create_powerpoint benutzen (nutzt die Hausvorlage).",
    "pandas":     "Tabellen mit dem eingebauten Modul csv verarbeiten; die Ausgabe ueber office_create_excel erzeugen.",
    "numpy":      "Einfache Rechnungen mit den eingebauten Modulen statistics/math loesen.",
    "matplotlib": "Fuer Diagramme das Werkzeug create_chart benutzen.",
    "seaborn":    "Fuer Diagramme das Werkzeug create_chart benutzen.",
    "plotly":     "Fuer Diagramme das Werkzeug create_chart benutzen.",
    "pdfplumber": "PDF-Text steht bei Anhaengen bereits im Verlauf; sonst 'pdftotext -layout <datei> -' benutzen.",
    "pypdf":      "PDF-Text steht bei Anhaengen bereits im Verlauf; sonst 'pdftotext -layout <datei> -' benutzen.",
    "PyPDF2":     "PyPDF2 ist ueberholt. PDF-Text steht bei Anhaengen bereits im Verlauf; sonst 'pdftotext -layout <datei> -' benutzen.",
    "fitz":       "PDF-Text steht bei Anhaengen bereits im Verlauf; sonst 'pdftotext -layout <datei> -' benutzen.",
    "PIL":        "Bilder mit den vorhandenen Kommandozeilen-Werkzeugen bearbeiten.",
    "jira":       "Jira ist ueber die jira_*-Werkzeuge angebunden - kein eigener Python-Client noetig.",
    "atlassian":  "Jira und Confluence sind ueber die jira_*- und confluence_*-Werkzeuge angebunden.",
    "requests":   "Netzzugriffe laufen nicht ueber die Shell; die eingebaute urllib genuegt, sofern Internet freigeschaltet ist.",
    "httpx":      "Netzzugriffe laufen nicht ueber die Shell; die eingebaute urllib genuegt, sofern Internet freigeschaltet ist.",
}

_MODUL_FEHLT_RE = re.compile(r"No module named ['\"]([A-Za-z0-9_.]+)['\"]")

# Nur der Wurzel-Name zaehlt: "No module named 'docx.oxml'" heisst, dass
# python-docx fehlt, nicht ein Untermodul.
def _modul_hinweis(result: str) -> str:
    """Haengt an eine Ausgabe mit ModuleNotFoundError einen Klartext-Hinweis.

    Ohne diesen Hinweis probiert das Modell weitere Importe, sucht nach
    Alternativ-Installationen und weicht am Ende auf ein schlechteres Ergebnis
    aus, statt das vorhandene Werkzeug zu nehmen.
    """
    try:
        if "No module named" not in result:
            return result
        namen, gesehen = [], set()
        for treffer in _MODUL_FEHLT_RE.findall(result):
            wurzel = treffer.split(".")[0]
            if wurzel and wurzel not in gesehen:
                gesehen.add(wurzel)
                namen.append(wurzel)
        if not namen:
            return result

        zeilen = ["", "HINWEIS_AN_NUTZER: Ein Python-Modul fehlt in der Umgebung, "
                      "in der dieser Befehl laeuft."]
        for name in namen:
            rat = _MODUL_ERSATZ.get(name)
            zeilen.append(f"- {name} ist nicht verfuegbar."
                          + (f" {rat}" if rat else ""))
        zeilen.append(
            "Ein Nachinstallieren ist dir NICHT moeglich (kein pip, kein Internet). "
            "Nimm den genannten Weg oder die Standardbibliothek und liefere ein "
            "Ergebnis - such nicht nach weiteren Modulen. Ist ein Modul wirklich "
            "unverzichtbar, nenne es dem Benutzer: ein Administrator kann es mit "
            "deploy/sandbox_python.sh nachinstallieren."
        )
        return result + "\n".join(zeilen)
    except Exception:
        return result


class ShellTool(BaseTool):
    """Fuehrt Shell-Befehle auf dem Linux-System aus."""

    # Streaming-Unterstuetzung: Agent kann Live-Output senden
    supports_streaming = True

    @property
    def name(self) -> str:
        return "shell_execute"

    @property
    def description(self) -> str:
        return (
            "Fuehrt einen Shell-Befehl (bash) auf dem Linux-System aus. "
            "Gibt stdout und stderr zurueck. Bei lang laufenden Befehlen "
            "wird die Ausgabe zeilenweise live gestreamt. "
            "Nutze dies fuer: Dateien auflisten, Pakete installieren, "
            "Systeminformationen abfragen, Programme starten, Code ausfuehren, etc."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "Der auszufuehrende Shell-Befehl",
                },
                "working_directory": {
                    "type": "STRING",
                    "description": "Arbeitsverzeichnis (optional, Standard: Home-Verzeichnis)",
                },
                "timeout": {
                    "type": "INTEGER",
                    "description": f"Timeout in Sekunden (optional, Standard: {config.COMMAND_TIMEOUT})",
                },
            },
            "required": ["command"],
        }

    @staticmethod
    def _code_to_command(code: str, tempdateien: list = None) -> str:
        """Wandelt Code in einen ausfuehrbaren Shell-Befehl um.
        Schreibt Python-Code in eine Temp-Datei um Quoting-Probleme zu vermeiden."""
        import tempfile, os

        # Python-Code aus 'python3 -c "..."' extrahieren
        stripped = code
        for prefix in ('python3 -c ', 'python -c '):
            if code.startswith(prefix):
                stripped = code[len(prefix):]
                # Aeussere Anfuehrungszeichen entfernen (""", ''', ", ')
                for q in ('"""', "'''", '"', "'"):
                    if stripped.startswith(q) and stripped.endswith(q):
                        stripped = stripped[len(q):-len(q)]
                        break
                break

        # Pruefen ob es ein Shell-Befehl ist (kein Python-Code)
        shell_indicators = ("ls ", "cat ", "cd ", "mkdir ", "rm ", "cp ", "mv ",
                            "chmod ", "grep ", "curl ", "wget ", "apt ", "pip ",
                            "git ", "npm ", "node ", "bash ", "sh ", "./", "/")
        if any(code.startswith(s) for s in shell_indicators):
            return code

        # Python-Code in Temp-Datei schreiben (vermeidet ALLE Quoting-Probleme).
        #
        # Die Datei entsteht DIREKT im Lauf-Verzeichnis (ohne Isolation: im
        # echten /tmp). Der Lauf sieht sie dort als `/tmp/<name>` – es braucht
        # also keine eigene Bindung, und im Befehl steht der Modell-Pfad.
        #
        # ALTFEHLER, hier mitbehoben: `NamedTemporaryFile` legt mit 0600 an. Der
        # Befehl eines Domain-Benutzers laeuft aber als `jarvis_sandbox` –
        # `python3 /tmp/jarvis_x.py` scheiterte damit seit immer mit `Errno 13`,
        # der Parameter `code` war fuer Netzwerk-Benutzer also unbenutzbar.
        # Aufgeraeumt wird vom Aufrufer und NICHT per `rm -f` im Befehl: als
        # Sandbox-Benutzer scheiterte dieses rm ohnehin still (fremder
        # Eigentuemer im sticky /tmp).
        from backend import lauf_tmp as _lt
        _verz = _lt.temp_verzeichnis()
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', prefix='jarvis_',
                                           dir=str(_verz), delete=False)
        tmp.write(stripped)
        tmp.close()
        _lt.temp_datei_freigeben(tmp.name)
        if tempdateien is not None:
            tempdateien.append(tmp.name)
        # Im Lauf heisst dieselbe Datei /tmp/<name> – der Befehl muss den
        # MODELL-Pfad nennen, nicht den Host-Pfad.
        _im_lauf = "/tmp/" + os.path.basename(tmp.name)
        return f"python3 {_im_lauf}"

    async def execute(
        self,
        command: str = "",
        working_directory: str = None,
        timeout: int = None,
        _status_callback=None,
        code: str = "",
        **kwargs,
    ) -> str:
        """Fuehrt Shell-Befehl aus. Bei _status_callback wird stdout live gestreamt."""
        # Temp-Skripte dieses Aufrufs: werden am Ende geloescht und bei aktiver
        # Lauf-Isolation in den Namespace gebunden.
        _tempdateien: list = []
        # Fallback: LLM schickt manchmal "cmd" oder "code" statt "command"
        if not command and kwargs.get("cmd"):
            command = kwargs["cmd"]
        if not command and code:
            command = self._code_to_command(code.strip(), _tempdateien)
        elif command and code:
            if command.strip().endswith("-c"):
                # command="python3 -c" + code separat -> Temp-Datei
                command = self._code_to_command(code.strip(), _tempdateien)
            # Sonst: command hat Vorrang, code ignorieren

        if not command:
            return "Fehler: Kein Befehl angegeben (Parameter 'command' ist Pflicht)"

        timeout = timeout or config.COMMAND_TIMEOUT
        cwd = working_directory or None

        # Root-Bedarf VOR dem Env-Prefix erkennen (Original-Befehl des Agenten)
        _wants_root = _needs_root(command)

        # Privates /tmp (backend/lauf_tmp.py). Im Lauf IST /tmp das
        # Arbeitsverzeichnis DIESES BENUTZERS – der Modell-Pfad
        # /tmp/ergebnis.xlsx bleibt damit gueltig, die Datei liegt auf dem Host
        # darin und ist fuer die Auslieferung erreichbar.
        from backend import lauf_tmp as _lauf_tmp
        _lauf = _lauf_tmp.aktueller_lauf()

        # Grafik-Umgebung fuer matplotlib/seaborn: headless (Agg, kein DISPLAY) +
        # schreibbarer Cache unter /tmp. Der Sandbox-User hat kein schreibbares
        # HOME. Ohne Isolation trennt der $(id -u)-Suffix privilegierte User vom
        # Sandbox-User; MIT Isolation liegt der Cache IM Arbeitsverzeichnis, das
        # je Benutzer existiert und den Lauf ueberlebt – der Schriftarten-Index
        # wird also einmal gebaut und nicht bei jedem Shell-Befehl. Als Prefix im
        # Kommando (nicht via Parent-Env), weil runuser die Env nicht durchreicht.
        _mplcfg = _lauf_tmp.MPL_ZIEL if _lauf else "/tmp/.mpl-$(id -u)"
        command = ("export MPLBACKEND=Agg TMPDIR=/tmp MPLCONFIGDIR=%s; " % _mplcfg) + command

        _broker_user = (kwargs.get("_broker_user") or "").strip()
        # Rein informativer Ausloeser-Kontext (Agent-Task-Auszug) fuers Audit-Log.
        _broker_context = (kwargs.get("_broker_context") or "").strip()[:200]

        # OS-Sandbox: Befehl als unprivilegierter OS-User ausfuehren (harte Grenze).
        # Wird vom Agent-Dispatch nur fuer nicht-privilegierte Benutzer gesetzt.
        _sandbox_user = (kwargs.get("_sandbox_user") or "").strip()
        if _sandbox_user:
            # Was in den Lauf hineingebunden werden muss: das Anhang-Verzeichnis
            # dieses Benutzers. Es liegt bewusst NICHT im Lauf-Verzeichnis – eine
            # Arbeitskopie ueberlebt den Lauf, weil die Folgefrage ("und jetzt
            # Spalte C") sie noch braucht. Die Temp-Skripte brauchen keine
            # Bindung: sie werden direkt im Lauf-Verzeichnis angelegt.
            _ro_binds = []
            _rw_binds = []
            if _lauf:
                _ro_binds += _lauf_tmp.anhang_binds(_lauf.benutzer)
                # Vom AUFRUFER angemeldete Arbeitsverzeichnisse (z.B. der
                # Wegwerf-Klon des Claude-Subagenten). Sie ueberleben den Lauf
                # und koennen deshalb nicht im Lauf-Verzeichnis liegen.
                _rw_binds += list(_lauf_tmp.zusatz_binds())
            if os.geteuid() == 0:
                # Alt-Betrieb (Backend als root): runuser direkt
                from backend import sandbox as _sbx
                _ldir = (_lauf_tmp.arbeit_bereitstellen(_lauf.kennung, _sandbox_user)
                         if _lauf else None)
                command = _sbx.wrap_sandboxed(
                    command, _sandbox_user, _ldir,
                    _lauf_tmp.binds_pruefen(_ro_binds),
                    rw_binds=_lauf_tmp.rw_binds_pruefen(_rw_binds))
                # Arbeitsverzeichnis auf den Sandbox-Bereich zwingen. Bei aktiver
                # Isolation setzt bwrap zusaetzlich --chdir /tmp; der Host-cwd
                # muss trotzdem existieren, sonst startet die Shell nicht.
                cwd = str(_ldir) if _ldir else "/tmp"
            else:
                # Getrennter Betrieb: runuser braucht root → Root-Broker. Der legt
                # das Arbeitsverzeichnis an und uebertraegt es dem Sandbox-Benutzer
                # (chown braucht root) – deshalb geht nur die KENNUNG hinueber.
                try:
                    return await self._exec_via_broker(
                        "sandbox_exec",
                        {"user": _sandbox_user, "command": command, "timeout": timeout,
                         "arbeit": _lauf.kennung if _lauf else "",
                         "ro_binds": _ro_binds, "rw_binds": _rw_binds,
                         "_context": _broker_context},
                        _broker_user, timeout, _status_callback)
                finally:
                    self._temp_weg(_tempdateien)

        # Root-Befehle privilegierter Benutzer: ueber den Root-Broker (shell_root).
        # Unbekannte Befehle erzeugen dort einen Pending-Eintrag fuer den Admin.
        elif _wants_root and os.geteuid() != 0 and kwargs.get("_root_broker"):
            try:
                return await self._exec_via_broker(
                    "shell_root",
                    {"command": command, "cwd": cwd, "timeout": timeout,
                     "_context": _broker_context},
                    _broker_user, timeout, _status_callback)
            finally:
                self._temp_weg(_tempdateien)

        # Python-Buffering deaktivieren fuer Live-Streaming
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                env=env,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                # EIGENE Prozessgruppe: ein Timeout muss den ganzen Baum treffen.
                # `proc.kill()` beendet nur die aeussere Shell – bei
                # `runuser -> setpriv -> bwrap -> bash -> python` lief der Rest
                # als Waise weiter (aelter als die Isolation, faellt damit aber
                # mehr auf: die Waise schreibt in ein abgeraeumtes Verzeichnis).
                start_new_session=True,
            )

            # Live-Streaming: stdout zeilenweise lesen und senden
            print(f"[SHELL] callback={_status_callback is not None} stdout={proc.stdout is not None}", flush=True)
            if _status_callback and proc.stdout:
                stdout_lines = []
                stderr_data = b""

                async def _read_stderr():
                    nonlocal stderr_data
                    if proc.stderr:
                        stderr_data = await proc.stderr.read()

                stderr_task = asyncio.create_task(_read_stderr())

                try:
                    while True:
                        try:
                            line = await asyncio.wait_for(
                                proc.stdout.readline(), timeout=timeout
                            )
                        except asyncio.TimeoutError:
                            self._gruppe_beenden(proc)
                            return f"⏰ Timeout nach {timeout}s. Befehl abgebrochen."

                        if not line:
                            break

                        decoded = line.decode("utf-8", errors="replace").rstrip()
                        stdout_lines.append(decoded)
                        # Live an Frontend senden
                        try:
                            await _status_callback(f"💻 {decoded}")
                        except Exception as cb_err:
                            print(f"[SHELL] callback error: {cb_err}", flush=True)

                    await asyncio.wait_for(proc.wait(), timeout=5)
                    await stderr_task

                except asyncio.TimeoutError:
                    self._gruppe_beenden(proc)
                    return f"⏰ Timeout nach {timeout}s. Befehl abgebrochen."

                result = ""
                if stdout_lines:
                    result += f"STDOUT:\n" + "\n".join(stdout_lines)
                if stderr_data:
                    result += f"\nSTDERR:\n{stderr_data.decode('utf-8', errors='replace')}"
                if proc.returncode and proc.returncode != 0:
                    result += f"\nExit-Code: {proc.returncode}"

                return _modul_hinweis(result.strip()) or "(Keine Ausgabe)"

            else:
                # Klassischer Modus: alles auf einmal
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    self._gruppe_beenden(proc)
                    return f"⏰ Timeout nach {timeout}s. Befehl abgebrochen."

                result = ""
                if stdout:
                    result += f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}"
                if stderr:
                    result += f"\nSTDERR:\n{stderr.decode('utf-8', errors='replace')}"
                if proc.returncode != 0:
                    result += f"\nExit-Code: {proc.returncode}"

                return _modul_hinweis(result.strip()) or "(Keine Ausgabe)"

        except Exception as e:
            return f"Fehler: {str(e)}"
        finally:
            self._temp_weg(_tempdateien)

    @staticmethod
    def _gruppe_beenden(proc) -> None:
        """Prozessgruppe des Befehls beenden (Timeout).

        Mit ``start_new_session=True`` ist die pid des Kindes die Gruppen-Id;
        ``killpg`` erwischt damit auch runuser/bwrap/python darunter. Rueckfall
        auf ``proc.kill()``, falls die Gruppe schon weg ist.
        """
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _temp_weg(pfade) -> None:
        """Temp-Skripte dieses Aufrufs entfernen.

        Sie gehoeren dem Dienstbenutzer, das Loeschen klappt also auch dann, wenn
        der Befehl selbst als Sandbox-Benutzer lief – genau das konnte das
        frueher im Befehl mitgeschickte `rm -f` NICHT (fremder Eigentuemer im
        sticky /tmp), weshalb diese Dateien bis zum Reboot liegen blieben.
        """
        for pf in (pfade or []):
            try:
                os.unlink(pf)
            except OSError:
                pass

    async def _exec_via_broker(self, op: str, args: dict, username: str,
                               timeout: int, _status_callback) -> str:
        """Befehl ueber den Root-Broker ausfuehren (sandbox_exec/shell_root).

        Live-Zeilen werden – wie beim lokalen Streaming – mit 💻-Prefix an das
        Frontend gereicht. Pending/Denied werden dem Agenten verstaendlich
        gemeldet, damit er den Benutzer informiert statt Umgehungen zu suchen."""
        from backend import broker_client

        if _status_callback:
            async def _cb(line: str):
                await _status_callback(f"💻 {line}")
        else:
            _cb = None

        res = await broker_client.call(op, args, user=username or "system",
                                       timeout=timeout + 30, stream_cb=_cb)

        decision = res.get("decision", "")
        if decision == "pending":
            shown = args.get("command", "")
            return (
                "🔐 Root-Rechte erforderlich – Befehl wurde NICHT ausgeführt.\n"
                f"Befehl: {shown}\n"
                "Er wurde als Freigabe-Anfrage eingetragen (Einstellungen → Sicherheit → "
                "Root-Freigaben). Ein lokaler Administrator muss ihn dort erlauben; danach "
                "kann er erneut ausgeführt werden. Informiere den Benutzer darüber und "
                "versuche KEINE Umgehung."
            )
        if decision == "denied":
            return ("🚫 Vom Administrator abgelehnt: Dieser Root-Befehl ist gesperrt "
                    "(Einstellungen → Sicherheit → Root-Freigaben). Führe ihn nicht auf "
                    "anderem Weg aus.")
        if decision in ("unreachable", "error") or (not res.get("ok") and res.get("error")
                                                    and "rc" not in res):
            return f"Fehler: {res.get('error', 'Root-Broker nicht erreichbar')}"

        result = ""
        if res.get("stdout"):
            result += "STDOUT:\n" + str(res["stdout"])
        if res.get("stderr"):
            result += "\nSTDERR:\n" + str(res["stderr"])
        rc = res.get("rc")
        if rc:
            result += f"\nExit-Code: {rc}"
        return _modul_hinweis(result.strip()) or "(Keine Ausgabe)"
