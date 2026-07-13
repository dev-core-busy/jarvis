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
    def _code_to_command(code: str) -> str:
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

        # Python-Code in Temp-Datei schreiben (vermeidet ALLE Quoting-Probleme)
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', prefix='jarvis_',
                                           dir='/tmp', delete=False)
        tmp.write(stripped)
        tmp.close()
        return f"python3 {tmp.name} ; rm -f {tmp.name}"

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
        # Fallback: LLM schickt manchmal "cmd" oder "code" statt "command"
        if not command and kwargs.get("cmd"):
            command = kwargs["cmd"]
        if not command and code:
            command = self._code_to_command(code.strip())
        elif command and code:
            if command.strip().endswith("-c"):
                # command="python3 -c" + code separat -> Temp-Datei
                command = self._code_to_command(code.strip())
            # Sonst: command hat Vorrang, code ignorieren

        if not command:
            return "Fehler: Kein Befehl angegeben (Parameter 'command' ist Pflicht)"

        timeout = timeout or config.COMMAND_TIMEOUT
        cwd = working_directory or None

        # Root-Bedarf VOR dem Env-Prefix erkennen (Original-Befehl des Agenten)
        _wants_root = _needs_root(command)

        # Grafik-Umgebung fuer matplotlib/seaborn: headless (Agg, kein DISPLAY) +
        # schreibbarer Cache PRO OS-User unter /tmp. Der Sandbox-User hat kein
        # schreibbares HOME; der $(id -u)-Suffix vermeidet Rechte-Kollisionen
        # zwischen privilegierten Usern und dem Sandbox-User. Als Prefix im
        # Kommando (nicht via Parent-Env), weil runuser die Env nicht durchreicht.
        command = "export MPLBACKEND=Agg MPLCONFIGDIR=/tmp/.mpl-$(id -u); " + command

        _broker_user = (kwargs.get("_broker_user") or "").strip()

        # OS-Sandbox: Befehl als unprivilegierter OS-User ausfuehren (harte Grenze).
        # Wird vom Agent-Dispatch nur fuer nicht-privilegierte Benutzer gesetzt.
        _sandbox_user = (kwargs.get("_sandbox_user") or "").strip()
        if _sandbox_user:
            if os.geteuid() == 0:
                # Alt-Betrieb (Backend als root): runuser direkt
                from backend import sandbox as _sbx
                command = _sbx.wrap_sandboxed(command, _sandbox_user)
                cwd = "/tmp"   # Arbeitsverzeichnis auf den Sandbox-Bereich zwingen
            else:
                # Getrennter Betrieb: runuser braucht root → Root-Broker
                return await self._exec_via_broker(
                    "sandbox_exec",
                    {"user": _sandbox_user, "command": command, "timeout": timeout},
                    _broker_user, timeout, _status_callback)

        # Root-Befehle privilegierter Benutzer: ueber den Root-Broker (shell_root).
        # Unbekannte Befehle erzeugen dort einen Pending-Eintrag fuer den Admin.
        elif _wants_root and os.geteuid() != 0 and kwargs.get("_root_broker"):
            return await self._exec_via_broker(
                "shell_root",
                {"command": command, "cwd": cwd, "timeout": timeout},
                _broker_user, timeout, _status_callback)

        # Python-Buffering deaktivieren fuer Live-Streaming
        import os
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                env=env,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
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
                            proc.kill()
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
                    proc.kill()
                    return f"⏰ Timeout nach {timeout}s. Befehl abgebrochen."

                result = ""
                if stdout_lines:
                    result += f"STDOUT:\n" + "\n".join(stdout_lines)
                if stderr_data:
                    result += f"\nSTDERR:\n{stderr_data.decode('utf-8', errors='replace')}"
                if proc.returncode and proc.returncode != 0:
                    result += f"\nExit-Code: {proc.returncode}"

                return result.strip() or "(Keine Ausgabe)"

            else:
                # Klassischer Modus: alles auf einmal
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    return f"⏰ Timeout nach {timeout}s. Befehl abgebrochen."

                result = ""
                if stdout:
                    result += f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}"
                if stderr:
                    result += f"\nSTDERR:\n{stderr.decode('utf-8', errors='replace')}"
                if proc.returncode != 0:
                    result += f"\nExit-Code: {proc.returncode}"

                return result.strip() or "(Keine Ausgabe)"

        except Exception as e:
            return f"Fehler: {str(e)}"

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
        return result.strip() or "(Keine Ausgabe)"
