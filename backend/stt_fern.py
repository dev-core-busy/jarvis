"""Spracherkennung ueber einen entfernten STT-Dienst (JSON ueber WebSocket).

Alternative zum lokalen faster-whisper (``main._transcribe_audio``). Gemessen am
2026-10-22 mit verrauschtem Laptop-Mikrofon: lokal ``small`` 14,5 % Wortfehler,
der GPU-Dienst (large-v3) 9,0 % bei 1,6 s Antwortzeit – lokal brauchte ein
gleich gutes Modell auf vier Kernen rund 10 s je Satz.

Protokoll (DP-SwyxAgent STT WebSocket Protocol):
    -> {"type":"start", sessionId, language, sampleRate:16000, channels:1, format:"pcm_s16le"}
    <- {"type":"ready"}
    -> {"type":"audio", sessionId, sequence, pcmBase64, endOfUtterance}   (mehrfach)
    <- {"type":"final", text, fullText}          (nach endOfUtterance)
    -> {"type":"stop"}
    <- {"type":"stopped"}
    <- {"type":"error", message}                 (jederzeit)

Der Dienst transkribiert erst beim ``endOfUtterance`` – eine Aufnahme geht
deshalb als EINE Aeusserung hinueber, das letzte Stueck traegt die Markierung.
Ein leeres Stueck mit der Markierung verwirft der Dienst (``pcmBase64`` fehlt),
die Aeusserung wuerde nie transkribiert; das letzte Stueck ist darum nie leer.

Die Adresse steht NUR in den Einstellungen (settings.json), nie im Code.
"""
import asyncio
import base64
import json
import subprocess
import time
import urllib.parse
import urllib.request
import uuid

QUELLE_LOKAL = "lokal"
QUELLE_FERN = "fern"
QUELLEN = (QUELLE_LOKAL, QUELLE_FERN)

ABTASTRATE = 16000
BYTES_JE_SEKUNDE = ABTASTRATE * 2          # PCM s16le, mono
STUECK_BYTES = BYTES_JE_SEKUNDE // 4       # 250 ms je audio-Nachricht
VERBINDEN_S = 5
# Frist fuer das Ergebnis: Grundzeit plus die Laenge der Aufnahme – ein langer
# Audio-Anhang darf laenger rechnen als ein Satz aus dem Chat.
FRIST_GRUND_S = 20
STOP_FRIST_S = 5


def einstellung(cfg) -> tuple[str, str]:
    """(quelle, url) aus der Konfiguration; Unbekanntes gilt als lokal."""
    quelle = str(cfg.get_setting("stt_quelle", QUELLE_LOKAL) or QUELLE_LOKAL).strip()
    url = str(cfg.get_setting("stt_fern_url", "") or "").strip()
    if quelle not in QUELLEN:
        quelle = QUELLE_LOKAL
    return quelle, url


def url_pruefen(url: str) -> str:
    """Normierte WebSocket-Adresse oder ValueError mit lesbarem Grund."""
    url = (url or "").strip()
    if not url:
        raise ValueError("Adresse fehlt")
    if len(url) > 500 or any(c.isspace() for c in url):
        raise ValueError("Adresse ungueltig")
    teile = urllib.parse.urlsplit(url)
    if teile.scheme not in ("ws", "wss") or not teile.hostname:
        raise ValueError("Adresse muss mit ws:// oder wss:// beginnen")
    if teile.username or teile.password:
        raise ValueError("Zugangsdaten gehoeren nicht in die Adresse")
    return url


def health_url(url: str) -> str:
    """HTTP-Adresse von ``/health`` zur WebSocket-Adresse (Pfad ab /ws/ entfaellt)."""
    teile = urllib.parse.urlsplit(url)
    schema = "https" if teile.scheme == "wss" else "http"
    pfad = teile.path
    if "/ws/" in pfad:
        pfad = pfad[:pfad.index("/ws/")]
    return urllib.parse.urlunsplit((schema, teile.netloc, pfad.rstrip("/") + "/health", "", ""))


def gesundheit(url: str, frist_s: float = 3.0) -> dict:
    """Erreichbarkeit des Dienstes: {"ok", "detail", "modell", "geraet"}.

    Ohne System-Proxy: der Dienst ist ein interner Host, den ein Firmen-Proxy
    nicht kennt (im Windows-Client so beobachtet – mit Proxy galt er als
    unerreichbar, waehrend der WebSocket ging)."""
    oeffner = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with oeffner.open(health_url(url), timeout=frist_s) as antwort:
            daten = json.loads(antwort.read(65536).decode("utf-8", "replace") or "{}")
    except Exception as e:  # noqa: BLE001 – jeder Grund ist "nicht erreichbar"
        return {"ok": False, "detail": str(e)[:200], "modell": "", "geraet": ""}
    modell = str(daten.get("modelPath") or "").rstrip("/").rsplit("/", 1)[-1]
    return {"ok": daten.get("status") == "ok", "detail": str(daten.get("status") or ""),
            "modell": modell, "geraet": str(daten.get("device") or "")}


def pcm_aus_datei(pfad: str) -> bytes:
    """Beliebige Audio-/Videodatei -> PCM s16le, 16 kHz, mono (ffmpeg)."""
    erg = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", pfad,
         "-vn", "-f", "s16le", "-ac", "1", "-ar", str(ABTASTRATE), "-"],
        capture_output=True, timeout=300)
    if erg.returncode != 0:
        raise RuntimeError("ffmpeg: " + erg.stderr.decode("utf-8", "replace").strip()[:200])
    return erg.stdout


async def _erkennen(pcm: bytes, url: str, sprache: str) -> str:
    import websockets
    sitzung = "jarvis-" + uuid.uuid4().hex[:12]
    frist = FRIST_GRUND_S + len(pcm) / BYTES_JE_SEKUNDE
    texte: list[str] = []

    async def lies(bis: float) -> dict:
        roh = await asyncio.wait_for(ws.recv(), max(0.1, bis - time.monotonic()))
        m = json.loads(roh)
        if not isinstance(m, dict):
            raise RuntimeError("unerwartete Antwort")
        if m.get("type") == "error":
            raise RuntimeError("Dienst meldet: " + str(m.get("message") or "Fehler")[:200])
        return m

    async with websockets.connect(url, open_timeout=VERBINDEN_S, max_size=2 ** 22,
                                  ping_interval=None) as ws:
        ende = time.monotonic() + frist
        await ws.send(json.dumps({"type": "start", "sessionId": sitzung, "language": sprache,
                                  "sampleRate": ABTASTRATE, "channels": 1, "format": "pcm_s16le"}))
        while (await lies(ende)).get("type") != "ready":
            pass
        stuecke = [pcm[i:i + STUECK_BYTES] for i in range(0, len(pcm), STUECK_BYTES)] or [b""]
        if not stuecke[-1]:
            # Nie ein leeres Schlussstueck: 20 ms Stille als Traeger der Markierung.
            stuecke[-1] = bytes(BYTES_JE_SEKUNDE // 50)
        for nr, stueck in enumerate(stuecke, 1):
            await ws.send(json.dumps({"type": "audio", "sessionId": sitzung, "sequence": nr,
                                      "pcmBase64": base64.b64encode(stueck).decode("ascii"),
                                      "endOfUtterance": nr == len(stuecke)}))
        while True:
            m = await lies(ende)
            if m.get("type") == "final":
                texte.append(str(m.get("text") or "").strip())
                break
        # Abmelden; ein spaetes final vor "stopped" gehoert noch dazu. Bleibt
        # die Bestaetigung aus, ist das Ergebnis trotzdem vollstaendig.
        await ws.send(json.dumps({"type": "stop", "sessionId": sitzung}))
        stop_ende = time.monotonic() + STOP_FRIST_S
        try:
            while True:
                m = await lies(stop_ende)
                if m.get("type") == "final":
                    texte.append(str(m.get("text") or "").strip())
                elif m.get("type") == "stopped":
                    break
        except (asyncio.TimeoutError, RuntimeError):
            pass
    return " ".join(t for t in texte if t).strip()


def transkribieren(pfad: str, url: str, sprache: str | None = None) -> str:
    """Datei ueber den Fern-Dienst erkennen. Synchron – laeuft in einem Thread
    (``_transcribe_audio`` wird ausschliesslich ueber to_thread/Executor gerufen).
    Wirft bei jedem Fehlschlag; ein leerer Text heisst "keine Sprache"."""
    url = url_pruefen(url)
    pcm = pcm_aus_datei(pfad)
    if not pcm:
        return ""
    return asyncio.run(_erkennen(pcm, url, sprache or "de"))
