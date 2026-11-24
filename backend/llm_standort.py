"""Standort eines LLM-Profils: INTERN (eigenes Netz) oder EXTERN (Cloud).

Schalter "sensible Daten" (``backend/sensibel.py``, Festlegung 2026-11-24):
ein sensibler Lauf darf NUR interne Modelle benutzen. Drei Teile:

1. **Einstufung** (``einstufen``): jedes Profil traegt ``standort`` =
   ``auto`` (Vorgabe) | ``intern`` | ``extern``. Bei ``auto`` entscheidet die
   Erkennung (``auto_einstufen``) ueber Anbieter und Adresse:

   * Google, Anthropic (API und Sitzung): fester Cloud-Endpunkt -> extern.
     Ein ``intern`` von Hand ist dort NICHT erlaubt – der Anbieter ruft immer
     dessen oeffentliche Schnittstelle, die Adresse im Profil wirkt nicht.
   * Adresse ist ``localhost``/Loopback/private IP (RFC 1918, ULA, link-local)
     oder liegt in einem der eingestellten INTERNEN NETZE
     (``config.INTERNE_NETZE``) -> intern; sonst oeffentliche IP -> extern.
     Die Liste gibt es, weil Firmennetze nicht immer private Bereiche benutzen
     (gemessen 2026-11-24: DEV und der Haus-LLM-Server liegen in einem
     oeffentlich registrierten Bereich, die Erkennung hielte ihn fuer Cloud).
   * Bekannter Cloud-Anbieter (Liste ``_CLOUD_DOMAINS``) -> extern.
   * Einteiliger Name oder interne Endung (``.local``, ``.lan``, ``.intern`` …)
     -> intern.
   * Sonst DNS: alle Adressen privat -> intern, eine oeffentliche -> extern,
     keine Aufloesung -> ``unbekannt``.

   ``unbekannt`` gilt NIE als intern (fail-closed). Die Handeinstellung
   ueberstimmt die Erkennung in beide Richtungen: ``extern`` fuer einen
   lokalen Proxy, der in die Cloud weiterleitet (die Erkennung sieht nur
   ``localhost``), ``intern`` fuer ein Haus-Modell hinter einer oeffentlichen
   Adresse.

2. **Wechsel** (``sensibles_profil``): der Agent ersetzt in einem sensiblen
   Lauf ein externes Profil durch ein internes – zuerst das eingestellte
   "Profil fuer sensible Daten" (``config.SENSIBEL_PROFILE_ID``), sonst das
   erste interne, das der Benutzer benutzen darf.

3. **Riegel** (``riegel``): sitzt in ``llm.LLMProvider`` an JEDEM
   ``generate_response``/``generate_image``. Ein sensibler Lauf, der trotzdem
   ein externes Ziel erreicht (Werkzeug mit eigenem Profil, verwaiste
   Einstellung, neuer Aufrufer), scheitert dort mit ``ExternGesperrt`` statt
   Inhalte hinauszuschicken. Der Wechsel ist die Bequemlichkeit, der Riegel
   die Zusage.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
import time
from urllib.parse import urlparse

FELD = "standort"
STANDORTE = ("auto", "intern", "extern")
# Anbieter mit FESTEM Cloud-Endpunkt (die Adresse im Profil wird nicht benutzt)
_IMMER_EXTERN = {"google", "anthropic", "anthropic_session"}
# Bekannte Cloud-Anbieter: Endung des Hostnamens -> extern, ohne DNS-Frage.
_CLOUD_DOMAINS = (
    "openai.com", "anthropic.com", "claude.ai", "googleapis.com", "openrouter.ai",
    "mistral.ai", "groq.com", "together.xyz", "together.ai", "deepseek.com",
    "x.ai", "perplexity.ai", "cohere.com", "cohere.ai", "fireworks.ai",
    "huggingface.co", "hf.space", "azure.com", "windows.net", "amazonaws.com",
    "cloudflare.com", "nvidia.com", "deepinfra.com", "replicate.com",
    "cerebras.ai", "sambanova.ai", "novita.ai", "moonshot.cn", "aliyuncs.com",
)
# Endungen, die es im oeffentlichen DNS nicht gibt bzw. die per Konvention
# im eigenen Netz liegen.
_INTERNE_ENDUNGEN = (".local", ".lan", ".intern", ".internal", ".home.arpa",
                     ".localdomain", ".corp", ".localhost", ".private")
_DNS_DECKEL_S = 2.0
_DNS_GUELTIG_S = 600.0
_dns_cache: dict[str, tuple[float, list | None]] = {}
_dns_sperre = threading.Lock()


class ExternGesperrt(RuntimeError):
    """Ein sensibler Lauf wollte ein externes Modell aufrufen."""


def _norm(wert) -> str:
    return str(wert or "").strip().lower()


def handwert(profil: dict | None) -> str:
    """Die Handeinstellung des Profils (``auto`` bei fehlendem/ungueltigem Wert)."""
    w = _norm((profil or {}).get(FELD))
    return w if w in STANDORTE else "auto"


def handwert_pruefen(provider: str, wert) -> tuple[str, str]:
    """Zum Speichern: ``(wert, fehler)``. ``intern`` fuer einen Anbieter mit
    festem Cloud-Endpunkt ist ein Fehler, kein stiller Rueckfall – sonst
    stuende ein Profil als intern da, das Inhalte in die Cloud schickt."""
    w = _norm(wert) or "auto"
    if w not in STANDORTE:
        return "auto", "Unbekannter Standort (auto, intern oder extern)."
    if w == "intern" and _norm(provider) in _IMMER_EXTERN:
        return "auto", ("Dieser Anbieter ruft immer seine öffentliche Schnittstelle auf "
                        "und kann nicht als intern gelten.")
    return w, ""


def _host(api_url: str) -> str:
    u = str(api_url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    try:
        return (urlparse(u).hostname or "").strip().lower().rstrip(".")
    except ValueError:
        return ""


def netze_lesen(text) -> tuple[list, list]:
    """``(netze, ungueltige)`` aus Freitext (Komma, Leerzeichen, Zeilen)."""
    netze, falsch = [], []
    for teil in str(text or "").replace(",", " ").split():
        try:
            netze.append(ipaddress.ip_network(teil, strict=False))
        except ValueError:
            falsch.append(teil)
    return netze, falsch


def _eigene_netze() -> list:
    try:
        from backend.config import config
        return netze_lesen(getattr(config, "INTERNE_NETZE", "") or "")[0]
    except Exception:  # noqa: BLE001
        return []


def _im_eigenen_netz(ip) -> str:
    for n in _eigene_netze():
        if ip.version == n.version and ip in n:
            return str(n)
    return ""


def _ip_intern(ip: ipaddress._BaseAddress) -> bool:
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if ip.is_loopback or ip.is_link_local or _im_eigenen_netz(ip):
        return True
    # 100.64.0.0/10 (CGNAT) gilt NICHT als intern: geteilter Adressraum eines
    # Providers, nicht das eigene Netz.
    return bool(ip.is_private) and not ip.is_global


def _dns_aufloesen(host: str) -> list[str] | None:
    """Adressen von ``host`` mit hartem Deckel – ``None`` = nicht aufloesbar.

    Daemon-Thread mit ``join(timeout)``: ``getaddrinfo`` laesst sich nicht
    abbrechen, und der Aufruf darf den Event-Loop nicht beliebig lange halten
    (Register: ``asyncio.wait_for(to_thread)`` bricht nichts ab)."""
    erg: dict = {}

    def _lauf():
        try:
            erg["a"] = sorted({i[4][0] for i in socket.getaddrinfo(host, None)})
        except OSError:
            erg["a"] = None

    t = threading.Thread(target=_lauf, daemon=True)
    t.start()
    t.join(_DNS_DECKEL_S)
    return erg.get("a") if not t.is_alive() else None


def _per_dns(host: str) -> tuple[str, str]:
    # Gemerkt werden die ADRESSEN, nicht das Urteil: aendert der Administrator
    # die internen Netze, gilt das sofort und nicht erst nach Ablauf.
    jetzt = time.monotonic()
    with _dns_sperre:
        c = _dns_cache.get(host)
    if c and jetzt - c[0] < _DNS_GUELTIG_S:
        adressen = c[1]
    else:
        adressen = _dns_aufloesen(host)
        with _dns_sperre:
            _dns_cache[host] = (jetzt, adressen)
    if not adressen:
        st, grund = "unbekannt", f"{host} lässt sich nicht auflösen"
    else:
        try:
            alle_intern = all(_ip_intern(ipaddress.ip_address(a.split("%")[0]))
                              for a in adressen)
        except ValueError:
            alle_intern = False
        st = "intern" if alle_intern else "extern"
        grund = (f"{host} löst auf interne Adresse(n) auf" if alle_intern
                 else f"{host} löst auf öffentliche Adresse(n) auf")
    return st, grund


def auto_einstufen(provider: str, api_url: str) -> tuple[str, str]:
    """Erkennung ohne Handeinstellung: ``(intern|extern|unbekannt, grund)``."""
    prov = _norm(provider)
    if prov in _IMMER_EXTERN:
        return "extern", "fester Cloud-Endpunkt des Anbieters"
    host = _host(api_url)
    if not host:
        if prov == "openai_compatible":
            # Vorgabe von get_provider: http://localhost:11434 (Ollama)
            return "intern", "keine Adresse – lokaler Standard (localhost)"
        if prov == "openrouter":
            return "extern", "Cloud-Dienst OpenRouter"
        return "unbekannt", "keine Adresse"
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        netz = _im_eigenen_netz(getattr(ip, "ipv4_mapped", None) or ip)
        if netz:
            return "intern", f"im internen Netz {netz}"
        return (("intern", "private bzw. lokale IP-Adresse") if _ip_intern(ip)
                else ("extern", "öffentliche IP-Adresse"))
    if host == "localhost" or host.endswith(".localhost"):
        return "intern", "localhost"
    for d in _CLOUD_DOMAINS:
        if host == d or host.endswith("." + d):
            return "extern", f"bekannter Cloud-Anbieter ({d})"
    if "." not in host:
        return "intern", "Rechnername ohne Domäne (eigenes Netz)"
    for e in _INTERNE_ENDUNGEN:
        if host.endswith(e):
            return "intern", f"interne Domänen-Endung ({e})"
    return _per_dns(host)


def einstufen(profil: dict | None) -> dict:
    """``{standort, quelle, grund, auto}`` – ``standort`` ist der WIRKSAME Wert.

    ``quelle`` = ``hand`` (Einstellung) oder ``auto`` (Erkennung); ``auto``
    traegt immer das Ergebnis der Erkennung mit, damit die Oberflaeche einen
    Widerspruch zwischen Hand und Erkennung zeigen kann."""
    p = profil or {}
    auto, grund = auto_einstufen(p.get("provider") or "", p.get("api_url") or "")
    hand = handwert(p)
    if hand != "auto":
        # Hand-"intern" fuer einen Cloud-Anbieter wird beim Speichern abgewiesen;
        # steht er trotzdem in der Datei (von Hand geschrieben), gilt er nicht.
        if hand == "intern" and _norm(p.get("provider")) in _IMMER_EXTERN:
            return {"standort": "extern", "quelle": "auto", "grund": grund, "auto": auto}
        return {"standort": hand, "quelle": "hand",
                "grund": "vom Administrator festgelegt", "auto": auto}
    return {"standort": auto, "quelle": "auto", "grund": grund, "auto": auto}


def ist_intern(profil: dict | None) -> bool:
    return bool(profil) and einstufen(profil)["standort"] == "intern"


def _ziel_gleich(p: dict, provider: str, api_url: str) -> bool:
    if _norm(p.get("provider")) != _norm(provider):
        # OpenRouter erbt die Klasse von openai_compatible, traegt aber eine
        # eigene Kennung; die Session-Variante heisst im Profil "anthropic".
        if not (_norm(provider) == "anthropic_session" and _norm(p.get("provider")) == "anthropic"):
            return False
    if _norm(provider) in _IMMER_EXTERN:
        return True
    a = str(p.get("api_url") or "").strip().rstrip("/").lower()
    b = str(api_url or "").strip().rstrip("/").lower()
    return a == b or (a and b.startswith(a))


def ziel_intern(provider: str, api_url: str, profile: list | None = None) -> tuple[bool, str]:
    """Ist das ZIEL eines Aufrufs intern? Fuer den Riegel.

    Massgeblich sind die Profile mit demselben Ziel: steht eines davon von Hand
    auf ``extern``, gilt das Ziel als extern (der strengere Wert gewinnt);
    sonst ein Hand-``intern``; sonst die Erkennung."""
    if profile is None:
        try:
            from backend.config import config
            profile = list(config.profiles or [])
        except Exception:  # noqa: BLE001
            profile = []
    passend = [p for p in profile if isinstance(p, dict) and _ziel_gleich(p, provider, api_url)]
    hand = {handwert(p) for p in passend}
    if "extern" in hand:
        return False, "vom Administrator als extern festgelegt"
    if "intern" in hand and _norm(provider) not in _IMMER_EXTERN:
        return True, "vom Administrator als intern festgelegt"
    st, grund = auto_einstufen(provider, api_url)
    return st == "intern", grund


def _darf(benutzer: str, profil: dict) -> bool:
    """Profilrecht wie im Umschalter (``main._may_use_profile``) – ohne main
    geladen (Tests, Werkzeuge): nur uneingeschraenkte Profile oder solche, die
    den Benutzer namentlich nennen."""
    import sys
    m = sys.modules.get("backend.main")
    f = getattr(m, "_may_use_profile", None) if m else None
    if callable(f):
        try:
            return bool(f(benutzer, profil))
        except Exception:  # noqa: BLE001
            return False
    au = str(profil.get("allowed_users") or "").strip()
    ag = str(profil.get("allowed_group") or "").strip()
    if not au and not ag:
        return True
    norm = lambda u: u.strip().split("\\")[-1].split("@")[0].lower()  # noqa: E731
    return bool(benutzer) and norm(benutzer) in {norm(u) for u in au.split(",") if u.strip()}


def sensibles_profil(benutzer: str, bevorzugt: dict | None = None) -> dict | None:
    """Das Profil, mit dem ein sensibler Lauf arbeitet – ``None`` = keines.

    1. ``bevorzugt`` (Rolle/Benutzerwahl/global), wenn es intern ist;
    2. das eingestellte Profil fuer sensible Daten – OHNE Profilrecht: der
       Administrator hat es ausdruecklich dafuer bestimmt;
    3. das erste interne Profil, das der Benutzer benutzen darf."""
    if ist_intern(bevorzugt):
        return bevorzugt
    try:
        from backend.config import config
        profile = list(config.profiles or [])
        pid = str(getattr(config, "SENSIBEL_PROFILE_ID", "") or "").strip()
    except Exception:  # noqa: BLE001
        return None
    if pid:
        p = next((x for x in profile if x.get("id") == pid), None)
        if p is not None and ist_intern(p):
            return p
        if p is not None:
            print(f"[SENSIBEL] eingestelltes Profil {pid} ist nicht intern – wird übergangen",
                  flush=True)
    for p in profile:
        if ist_intern(p) and _darf(benutzer, p):
            return p
    return None


KEIN_INTERNES = ("Für sensible Daten ist kein internes KI-Modell verfügbar. "
                 "Der Administrator muss ein internes LLM-Profil einrichten "
                 "(Einstellungen → LLM-Profile, Standort „intern“).")


def riegel(provider_kennung: str, api_url: str) -> None:
    """Wirft ``ExternGesperrt``, wenn ein SENSIBLER Lauf ein nicht internes
    Ziel ruft. Ausserhalb eines sensiblen Laufs: nichts."""
    try:
        from backend import sensibel
        if not sensibel.aktiv():
            return
    except Exception:  # noqa: BLE001
        return
    intern, grund = ziel_intern(provider_kennung, api_url)
    if intern:
        return
    host = _host(api_url) or provider_kennung
    print(f"[SENSIBEL] externer LLM-Aufruf gesperrt: {provider_kennung} {host} ({grund})",
          flush=True)
    text = (f"Sensible Daten: das KI-Modell ({host}) ist extern ({grund}) – der Aufruf "
            f"wurde gesperrt, damit keine Inhalte das eigene Netz verlassen.")
    try:
        from backend.config import config
        if not any(ist_intern(p) for p in (config.profiles or [])):
            text += " " + KEIN_INTERNES
    except Exception:  # noqa: BLE001
        pass
    raise ExternGesperrt(text)
