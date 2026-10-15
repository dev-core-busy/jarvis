"""Erinnerungs-Ausnahme: freigegebene Messenger-Absender duerfen Sendeauftraege anlegen.

WARUM ES DAS GIBT (2026-07-29): Zeitgesteuerte Auftraege legt seit 2026-07-29 nur
noch ein Administrator an (`agent.py::_BLOCKED_TOOLS_FOR_LDAP`,
`main.py::_require_trigger_admin`). Grund: ein unprivilegiert angelegter Cron-Job
startet spaeter selbstaendig einen Agenten mit vollem Werkzeugkasten – ausserhalb
jeder Chat-Sitzung, wiederkehrend, ohne Freigabe. Ueber Prompt-Injection
(WhatsApp-Text → Zusammenfassung → Agent) war das der verbleibende Weg zu
dauerhafter Praesenz. Mit der Sperre fiel aber auch "Erinnere mich morgen um
06:15 per WhatsApp" weg, denn Messenger-Kanaele sind IMMER unprivilegiert
(`wa:+49…`, `tg:<chat>`) – auch dann, wenn das Telefon dem Administrator gehoert.

Diese Ausnahme holt genau diese Funktion zurueck, ohne die Luecke zu oeffnen.
Vier Bedingungen, die ALLE gelten muessen:

1. WHITELIST – nur ausdruecklich freigegebene Absender (Einstellungen →
   Sicherheit → Erinnerungen per Messenger). Vorgabe ist eine LEERE Liste: ohne
   bewusste Freigabe kann niemand etwas anlegen.
2. KEIN AGENT – ein Erinnerungs-Job hat `kind="reminder"` und wird vom Scheduler
   DIREKT versendet (`scheduler._execute`), ohne LLM und ohne Werkzeuge. Das ist
   der Kern der Sache: liefe der gespeicherte Text spaeter durch ein Modell, waere
   der Nachrichtentext wieder ein zeitversetzt ausgefuehrter Auftrag – also genau
   die Persistenz, die gerade geschlossen wurde.
3. NUR AN SICH SELBST – Empfaenger ist immer der anlegende Absender. Der Anrufer
   uebergibt keinen Empfaenger; er wird aus der Actor-Kennung abgeleitet. Sonst
   waere die Ausnahme ein Versandweg fuer fremde Nummern (Spam/Phishing mit dem
   Absender des Unternehmens).
4. EINMALIG + DECKEL – nur Einmal-Auftraege (`once=True`, loeschen sich nach dem
   Lauf) und hoechstens `MAX_OPEN` offene je Absender. Ein wiederkehrender Job ist
   dauerhafte Praesenz, und genau die ist Admins vorbehalten.

Die Auftraggeber-Bindung bleibt unveraendert: der Job gehoert `wa:+49…` und ist
`owner_privileged=False`. Selbst wenn der Sendezweig kuenftig einmal umgangen
wuerde, liefe er unprivilegiert.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request

SETTING_KEY = "reminder_senders"

# Hoechstzahl offener (noch nicht gefeuerter) Erinnerungen je Absender. Bremst
# eine per Injection gesteuerte Flut: ohne Deckel koennte eine einzige Nachricht
# tausende Jobs anlegen (Speicher, Datei, Zeitplan) – ein Denial-of-Service ganz
# ohne Rechteerhoehung.
MAX_OPEN = 20

# Laenge einer Erinnerung. Genug fuer einen Satz, zu wenig fuer eine ins Feld
# geschmuggelte Anweisungssammlung.
MAX_MESSAGE_LEN = 500

_WA_BRIDGE = "http://127.0.0.1:3001"

_PHONE_RE = re.compile(r"^\+\d{6,20}$")
_TG_RE = re.compile(r"^-?\d{1,20}$")


# ─── Kennungen ────────────────────────────────────────────────────────────────

def parse_actor(user: str) -> tuple[str, str] | None:
    """Zerlegt eine Actor-Kennung in (Kanal, Adresse).

    'wa:+4917…' → ('whatsapp', '+4917…'), 'tg:12345' → ('telegram', '12345').
    Alles andere → None. Ein Jarvis-Konto (Chat/API) landet also NIE in dieser
    Ausnahme – dort gilt die normale Admin-Regel.
    """
    u = (user or "").strip()
    if u.startswith("wa:"):
        num = _norm_phone(u[3:])
        return ("whatsapp", num) if num else None
    if u.startswith("tg:"):
        chat = u[3:].strip()
        return ("telegram", chat) if _TG_RE.match(chat) else None
    return None


def _norm_phone(raw: str) -> str:
    """Telefonnummer auf '+<Ziffern>' normieren ('' = unbrauchbar).

    WhatsApp-Kennungen kommen je Weg unterschiedlich an (mit Leerzeichen, '00'
    statt '+', als JID '4917…@s.whatsapp.net'). Ohne Normierung waere die
    Whitelist ein Zufallsspiel: dieselbe Nummer stuende drin und wuerde doch
    nicht erkannt.
    """
    s = (raw or "").strip()
    s = s.split("@", 1)[0]              # JID-Suffix abschneiden
    s = s.split(":", 1)[0]              # LID-Anteil (…:12) abschneiden
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if s.startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    out = "+" + digits
    return out if _PHONE_RE.match(out) else ""


def normalize_entry(raw: str) -> str:
    """Normiert einen Whitelist-Eintrag ('' = ungueltig, wird verworfen).

    Erlaubt sind Telefonnummern (mit oder ohne 'wa:'-Praefix) und
    'tg:<chat_id>'. Gespeichert wird immer in der Praefix-Form, damit ein
    Eintrag eindeutig einem Kanal gehoert – eine nackte Zahl waere sonst je nach
    Leser Telefonnummer ODER Telegram-Chat.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("tg:"):
        chat = s[3:].strip()
        return f"tg:{chat}" if _TG_RE.match(chat) else ""
    if low.startswith("wa:"):
        s = s[3:]
    num = _norm_phone(s)
    return f"wa:{num}" if num else ""


# ─── Whitelist ────────────────────────────────────────────────────────────────

def allowed_senders() -> list[str]:
    """Freigegebene Absender aus settings.json (normiert, ohne Duplikate)."""
    from backend.config import config
    raw = config.get_setting(SETTING_KEY, []) or []
    if isinstance(raw, str):                      # handgeschriebene settings.json
        raw = [p for p in re.split(r"[,\n;]", raw)]
    out: list[str] = []
    for item in raw:
        norm = normalize_entry(str(item))
        if norm and norm not in out:
            out.append(norm)
    return out


def set_allowed_senders(entries) -> list[str]:
    """Whitelist speichern; gibt die uebernommene (normierte) Liste zurueck.

    Ungueltige Eintraege werden VERWORFEN, nicht geraten – eine falsch
    verstandene Nummer waere eine Freigabe fuer den Falschen.
    """
    from backend.config import config
    if isinstance(entries, str):
        entries = re.split(r"[,\n;]", entries)
    clean: list[str] = []
    dropped: list[str] = []
    for item in entries or []:
        norm = normalize_entry(str(item))
        if not norm:
            if str(item).strip():
                dropped.append(str(item).strip()[:40])
        elif norm not in clean:
            clean.append(norm)
    config.save_setting(SETTING_KEY, clean)
    if dropped:
        print(f"[Reminder] Whitelist: {len(dropped)} ungueltige Eintraege verworfen: "
              f"{', '.join(dropped[:5])}", flush=True)
    return clean


def is_allowed(actor_user: str) -> bool:
    """True, wenn dieser Messenger-Absender Erinnerungen anlegen darf."""
    parsed = parse_actor(actor_user)
    if not parsed:
        return False
    channel, addr = parsed
    key = f"{'wa' if channel == 'whatsapp' else 'tg'}:{addr}"
    return key in allowed_senders()


# ─── Deckel ───────────────────────────────────────────────────────────────────

def open_count(owner: str) -> int:
    """Anzahl der noch offenen Erinnerungen dieses Absenders."""
    from backend.scheduler import cron_manager
    return sum(1 for j in cron_manager.list_jobs()
               if j.get("kind") == "reminder" and (j.get("owner") or "") == owner)


# ─── Versand (ohne Agent!) ────────────────────────────────────────────────────

async def deliver(payload: dict) -> str:
    """Sendet eine Erinnerung direkt ueber den Messenger. Rueckgabe = Klartext.

    Bewusst KEIN Agent, kein LLM, kein Werkzeug – nur Text an eine feste Adresse
    (siehe Modul-Docstring, Punkt 2).
    """
    channel = (payload or {}).get("channel", "")
    to = str((payload or {}).get("to", "")).strip()
    message = str((payload or {}).get("message", "")).strip()
    if not to or not message:
        return "Fehler: Erinnerung ohne Empfaenger oder Text"
    if channel == "whatsapp":
        return await asyncio.to_thread(_send_whatsapp, to, message)
    if channel == "telegram":
        return await _send_telegram(to, message)
    return f"Fehler: unbekannter Kanal '{channel}'"


def _send_whatsapp(to: str, message: str) -> str:
    """Blockierender Bridge-Aufruf – NUR aus asyncio.to_thread heraus benutzen.

    Ein synchroner HTTP-Aufruf im Event-Loop friert den ganzen Dienst ein
    (siehe CLAUDE.md, WhatsApp-Integration).
    """
    try:
        data = json.dumps({"to": to, "message": message}).encode("utf-8")
        req = urllib.request.Request(
            f"{_WA_BRIDGE}/send", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("success"):
            return f"Erinnerung an {to} gesendet."
        return f"Fehler beim Senden: {result}"
    except urllib.error.URLError as e:
        return f"WhatsApp-Bridge nicht erreichbar: {e.reason}"
    except Exception as e:  # noqa: BLE001
        return f"Fehler beim Senden: {e}"


async def _send_telegram(chat_id: str, message: str) -> str:
    try:
        from skills.telegram import main as tg
        mgr = getattr(tg, "_manager", None)
        if not mgr:
            return "Fehler: Telegram-Bot nicht aktiv."
        ok = await mgr.send_message(int(chat_id), message)
        return (f"Erinnerung an Telegram-Chat {chat_id} gesendet." if ok
                else "Fehler: Telegram-Versand fehlgeschlagen.")
    except Exception as e:  # noqa: BLE001
        return f"Fehler beim Senden: {e}"
