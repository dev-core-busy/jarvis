"""Oeffentlich bekannte Standard-Kennwoerter – eine Anmeldung damit erzwingt den Wechsel.

Vorfall 2026-09-28: ``docs/install.sh`` legte den Linux-Benutzer ``jarvis`` mit
dem Kennwort ``jarvis`` an, ``.env.example`` gab ``JARVIS_PASSWORD=jarvis``
vor, und README/Landingpage nannten ``jarvis / jarvis``. Der Wechselzwang hing
bis dahin allein am Merker ``must_change_password`` in ``data/auth_state.json``
– wurde das Kennwort spaeter wieder auf den Standard gesetzt (Neuinstallation
ueber einen Bestand, ``chpasswd`` von Hand),
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
    "my-secure-password", "mein-sicheres-passwort",   # fruehere Doku-Beispiele
})


def ist_standardkennwort(kennwort: str, benutzer: str = "") -> bool:
    """True, wenn ``kennwort`` oeffentlich bekannt ist oder dem Benutzernamen entspricht."""
    k = (kennwort or "").strip().lower()
    if not k:
        return True
    if k in STANDARD_KENNWOERTER:
        return True
    return bool(benutzer) and k == benutzer.strip().lower()
