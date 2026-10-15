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
