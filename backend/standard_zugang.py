"""Oeffentlich bekannte Standard-Kennwoerter – eine Anmeldung damit erzwingt den Wechsel.

Vorfall 2026-09-28: ``docs/install.sh`` legte den Linux-Benutzer ``jarvis`` mit
dem Kennwort ``jarvis`` an, Docker/``.env.example`` gaben ``JARVIS_PASSWORD=jarvis``
vor, und README/Landingpage nannten ``jarvis / jarvis``. Der Wechselzwang hing
bis dahin allein am Merker ``must_change_password`` in ``data/auth_state.json``
– wurde das Kennwort spaeter wieder auf den Standard gesetzt (Neuinstallation
ueber einen Bestand, ``chpasswd`` von Hand, Docker ohne gespeicherten Hash),
galt der alte Merker weiter und niemand musste wechseln.

Jetzt entscheidet das KENNWORT selbst: wer sich damit anmeldet, muss wechseln.
Bewusst ohne Import von ``backend.config``/``backend.main`` (testbar ohne
Live-Zustand).
"""

# Alles, was je als Vorgabe in Repo, Doku oder Installationsweg stand –
# plus die naheliegenden Nachbarn, die ``_validate_password_strength`` ohnehin
# als "zu einfach" ablehnt. Vergleich ohne Gross-/Kleinschreibung.
STANDARD_KENNWOERTER = frozenset({
    "jarvis",
    "password", "passwort",
    "12345678", "123456789",
    "my-secure-password", "mein-sicheres-passwort",   # Doku-Beispiele (docker.html)
})


def ist_standardkennwort(kennwort: str, benutzer: str = "") -> bool:
    """True, wenn ``kennwort`` oeffentlich bekannt ist oder dem Benutzernamen entspricht."""
    k = (kennwort or "").strip().lower()
    if not k:
        return True
    if k in STANDARD_KENNWOERTER:
        return True
    return bool(benutzer) and k == benutzer.strip().lower()


def docker_erstkennwort(env_wert: str, datei) -> str:
    """Web-Kennwort im Docker-Modus, solange noch kein eigenes gesetzt ist.

    ``JARVIS_PASSWORD`` aus der Umgebung gilt nur, wenn es KEIN Standard-
    kennwort ist. Sonst (Vorgabe fehlt oder lautet "jarvis"): Zufallskennwort,
    einmal erzeugt, in ``datei`` (0600) abgelegt und ins Log geschrieben
    (``docker logs jarvis``). Beim ersten Login erzwingt Jarvis den Wechsel.
    Ohne das konnte sich, wer den Container ZUERST erreichte, mit
    jarvis/jarvis anmelden und selbst ein Kennwort vergeben.
    """
    import os
    import secrets
    from pathlib import Path
    datei = Path(datei)
    if not ist_standardkennwort(env_wert):
        return env_wert.strip()
    wert = datei.read_text().strip() if datei.exists() else ""
    if ist_standardkennwort(wert):
        wert = secrets.token_urlsafe(12)
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_text(wert)
        os.chmod(str(datei), 0o600)
        # Nur beim ERZEUGEN ins Log – spaeter ist es womoeglich laengst geaendert
        print(f"[AUTH] Erstkennwort fuer 'jarvis': {wert}  (auch in {datei}; "
              "beim ersten Login muss es geaendert werden)", flush=True)
    return wert


# ── Gespeichertes Docker-Kennwort (data/auth_state.json) ─────────────────────
# Bis 2026-10-29 ungesalzenes SHA-256: wer die Datei las (Sicherung, kopiertes
# Volume), rechnete ein uebliches Kennwort per Woerterbuch in Sekunden zurueck,
# und gleiche Kennwoerter hatten gleiche Hashes. Jetzt scrypt mit Salz aus der
# Standardbibliothek (keine neue Abhaengigkeit im Image).
# Kosten: N=2^15, r=8 → 32 MB je Pruefung (Richtwert OWASP fuer scrypt).
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1
# Obergrenzen fuer GELESENE Parameter: ein manipulierter Eintrag soll den
# Dienst nicht ueber Speicher oder Rechenzeit lahmlegen koennen.
_SCRYPT_N_MAX = 2 ** 16
_SCRYPT_R_MAX = 8
_SCRYPT_P_MAX = 2


def _scrypt(kennwort: str, salz: bytes, n: int, r: int, p: int, laenge: int) -> bytes:
    import hashlib
    # maxmem mit Reserve: OpenSSL braucht etwas mehr als 128*n*r
    return hashlib.scrypt(kennwort.encode("utf-8"), salt=salz, n=n, r=r, p=p,
                          maxmem=256 * n * r + (1 << 20), dklen=laenge)


def kennwort_hash(kennwort: str) -> str:
    """Speicherform: ``scrypt$N$r$p$<salz b64>$<hash b64>``, je Aufruf neues Salz."""
    import base64
    import secrets
    salz = secrets.token_bytes(16)
    wert = _scrypt(kennwort, salz, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, 32)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salz)}${b64(wert)}"


def kennwort_pruefen(kennwort: str, gespeichert) -> tuple:
    """Prueft ``kennwort`` gegen die Speicherform. Rueckgabe ``(passt, veraltet)``.

    ``veraltet`` ist nur bei einem PASSENDEN Altwert (64 Hex-Zeichen, SHA-256)
    wahr – der Aufrufer schreibt ihn dann mit ``kennwort_hash`` neu. Alles
    andere (unbekanntes Format, kaputte oder ueberzogene Parameter) ist
    fail-closed: ``(False, False)``.
    """
    import base64
    import binascii
    import hashlib
    import hmac
    import re
    if not isinstance(kennwort, str) or not isinstance(gespeichert, str):
        return False, False
    if gespeichert.startswith("scrypt$"):
        teile = gespeichert.split("$")
        if len(teile) != 6:
            return False, False
        try:
            n, r, p = int(teile[1]), int(teile[2]), int(teile[3])
            salz = base64.b64decode(teile[4], validate=True)
            soll = base64.b64decode(teile[5], validate=True)
        except (ValueError, binascii.Error):
            return False, False
        if not (2 <= n <= _SCRYPT_N_MAX and n & (n - 1) == 0
                and 1 <= r <= _SCRYPT_R_MAX and 1 <= p <= _SCRYPT_P_MAX
                and len(salz) >= 16 and 16 <= len(soll) <= 64):
            return False, False
        try:
            ist = _scrypt(kennwort, salz, n, r, p, len(soll))
        except (ValueError, MemoryError):
            return False, False
        return hmac.compare_digest(ist, soll), False
    if re.fullmatch(r"[0-9a-f]{64}", gespeichert):
        passt = hmac.compare_digest(hashlib.sha256(kennwort.encode()).hexdigest(), gespeichert)
        return passt, passt
    return False, False
