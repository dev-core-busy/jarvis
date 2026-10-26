"""SECRET_KEY aufloesen – ohne je einen oeffentlich bekannten Wert zu verwenden.

Mit dem SECRET_KEY werden die Sitzungstokens (``main.generate_token``) und die
Abruf-Schluessel (``download_key``) per HMAC signiert. Wer ihn kennt, stellt
sich fuer JEDEN Benutzernamen ein gueltiges Token aus – ohne Kennwort.

Vorfall 2026-09-28: ``.env.example`` (oeffentlich auf GitHub) trug einen
Beispielwert, ``docs/install.sh`` kopierte die Vorlage unveraendert nach
``.env`` – eine Installation lief damit auf dem Schluessel aus dem Repo.
Deshalb gilt ein Platzhalter hier wie ein FEHLENDER Wert: es wird ein
Zufallsschluessel erzeugt und in ``data/.secret_key`` abgelegt.

Bewusst ohne Import von ``backend.config`` – damit ein Test diese Logik
pruefen kann, ohne die Live-``settings.json`` anzufassen.
"""
import os
import secrets
from pathlib import Path

# Werte, die je in Vorlage oder Doku standen. Alles mit "change-me" am Anfang
# gilt ebenfalls als Platzhalter (Abwandlungen in Anleitungen).
BEKANNTE_PLATZHALTER = frozenset({
    "change-me-to-a-secure-random-string-min-32-chars",   # .env.example bis 2026-09
    "change-me-to-a-random-string",                       # README
})


def ist_platzhalter(wert: str) -> bool:
    """True fuer leer, bekannte Beispielwerte und alles, was mit 'change-me' beginnt."""
    w = (wert or "").strip()
    if not w:
        return True
    return w in BEKANNTE_PLATZHALTER or w.lower().startswith("change-me")


def aufloesen(env_wert: str, datei: Path) -> str:
    """Liefert den zu verwendenden SECRET_KEY.

    Reihenfolge: gesetzter Wert aus der Umgebung, sofern KEIN Platzhalter ->
    sonst ``datei`` (frueher erzeugt) -> sonst neu erzeugen und in ``datei``
    ablegen (0600). Ein Platzhalter in ``datei`` wird ebenfalls verworfen.
    """
    if not ist_platzhalter(env_wert):
        return env_wert.strip()
    if env_wert and env_wert.strip():
        print("[SECURITY] SECRET_KEY in .env ist ein oeffentlich bekannter "
              "Beispielwert und wird IGNORIERT – es gilt der Schluessel aus "
              f"{datei}. Bitte die Zeile SECRET_KEY in .env leeren.", flush=True)
    wert = ""
    if datei.exists():
        wert = datei.read_text().strip()
    haupt = _hauptfernet()
    if wert.startswith(_PRAEFIX):
        # BSI M5: mit dem Hauptschluessel verpackt. ⚠ NIE neu erzeugen, wenn er
        # hier fehlt – ein neuer Schluessel machte jede Sitzung ungueltig, und
        # im Dienst (mit Hauptschluessel) gaelte danach wieder der alte.
        #
        # ⚠ Und NIE das Chiffrat selbst als Schluessel nehmen (Code-Review
        # 2026-10-07): es liegt lesbar fuer den Dienstbenutzer in data/ – jedes
        # Werkzeug, das als jarvis laeuft, haette damit Tokens fuer einen ohne
        # Hauptschluessel gestarteten Dienst faelschen koennen, auch Admin-
        # Tokens. Stattdessen ein FLUECHTIGER Zufallsschluessel nur fuer diesen
        # Prozess: seine Tokens gelten nirgends sonst und nicht ueber einen
        # Neustart (fail-closed), die Datei bleibt unberuehrt.
        if haupt is None:
            print(f"[SECURITY] {datei.name} ist verpackt, der Hauptschluessel fehlt in "
                  "diesem Prozess – es gilt ein fluechtiger Schluessel: Tokens dieses "
                  "Prozesses gelten nirgends sonst und nicht ueber einen Neustart "
                  "(Prozess ueber systemd mit LoadCredential starten).", flush=True)
            return secrets.token_hex(32)
        try:
            return haupt.decrypt(wert[len(_PRAEFIX):].encode("ascii")).decode("utf-8")
        except Exception:  # noqa: BLE001
            print(f"[SECURITY] {datei.name} passt nicht zum Hauptschluessel – "
                  "/etc/jarvis/geheimnis.key ersetzt? Es gilt ein fluechtiger "
                  "Schluessel; Sitzungen sind ungueltig, bis die passende Datei "
                  "zurueck ist.", flush=True)
            return secrets.token_hex(32)
    if ist_platzhalter(wert):
        wert = secrets.token_hex(32)
        datei.parent.mkdir(parents=True, exist_ok=True)
        _schreiben(datei, wert, haupt)
        print(f"[SECURITY] SECRET_KEY auto-generiert und in {datei} gespeichert", flush=True)
        return wert
    if haupt is not None:
        # Altbestand im Klartext: verpacken (misslingt es, bleibt er lesbar).
        try:
            _schreiben(datei, wert, haupt)
            print(f"[SECURITY] {datei.name} mit dem Hauptschluessel verpackt", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[SECURITY] {datei.name} nicht verpackt: {e}", flush=True)
    return wert


_PRAEFIX = "JGK1:"


def nur_lesen(env_wert: str, datei: Path) -> str | None:
    """Den ECHTEN Schluessel lesen – oder None, wenn dieser Prozess ihn nicht hat.

    Anders als ``aufloesen`` wird hier nie erzeugt, nie geschrieben und nie ein
    fluechtiger Ersatz geliefert. Gedacht fuer Nebenprozesse (Wartungsbefehle,
    ``python -m backend.sicherheits_log pruefen``), die mit dem Schluessel
    etwas NACHPRUEFEN oder FORTSCHREIBEN wollen: ein fluechtiger Schluessel
    saehe dort wie ein gueltiger aus und erzeugte falsche Pruefmerkmale.
    """
    if not ist_platzhalter(env_wert):
        return env_wert.strip()
    try:
        wert = datei.read_text().strip()
    except OSError:
        return None
    if wert.startswith(_PRAEFIX):
        haupt = _hauptfernet()
        if haupt is None:
            return None
        try:
            return haupt.decrypt(wert[len(_PRAEFIX):].encode("ascii")).decode("utf-8")
        except Exception:  # noqa: BLE001
            return None
    return None if ist_platzhalter(wert) else wert


def _hauptfernet():
    """Hauptschluessel (BSI M5) – None ohne ihn (Entwicklungsrechner, Docker
    ohne Datei, Prozess ausserhalb des Dienstes)."""
    try:
        from backend import geheimnis_tresor as _t
        return _t.hauptfernet()
    except Exception:  # noqa: BLE001
        return None


def _schreiben(datei: Path, wert: str, haupt) -> None:
    """0600, atomar, Eigentuemer erhalten; verpackt, wenn ein Hauptschluessel da ist."""
    from backend import geheimnis_tresor as _t
    inhalt = (_PRAEFIX + haupt.encrypt(wert.encode("utf-8")).decode("ascii")) if haupt else wert
    _t._schreibe_atomar(datei, inhalt.encode("utf-8"), 0o600)
