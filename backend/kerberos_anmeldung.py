"""Windows-Anmeldung per Kerberos (HTTP-Negotiate/SPNEGO), nur die Ticketpruefung.

**Warum es das gibt:** Die AI-Maus fragte nach Benutzer und Kennwort, obwohl der
Benutzer an Windows mit DERSELBEN Domaenenanmeldung sitzt (Wunsch 2026-10-20).
Mit Kerberos holt sich Windows selbst ein Ticket fuer ``HTTP/<server-fqdn>``,
der Server prueft es mit seiner Keytab – ein Kennwort geht dabei nirgends hin.

WARUM ctypes UND KEIN PAKET
---------------------------
``pyspnego`` liegt zwar im venv, nimmt Kerberos unter Linux aber nur ueber das
Paket ``gssapi`` an – und dafuer gibt es keine fertigen Linux-Wheels (gemessen
2026-10-20: ``pip download gssapi --only-binary`` -> keine Version). Es muesste
auf jedem Server mit ``libkrb5-dev`` uebersetzt werden. Die Systembibliothek
``libgssapi_krb5.so.2`` ist dagegen auf DEV und ECHT vorhanden (MIT 1.21.3) und
bringt alles mit, was ein ANNEHMENDER Dienst braucht. Gebraucht werden nur fuenf
Funktionen; die stehen hier.

WAS GEPRUEFT WIRD
-----------------
1. **Nur Kerberos.** Ein rohes NTLM-Token (``NTLMSSP\\0``) wird abgewiesen, bevor
   es die Bibliothek sieht. Windows faellt bei fehlendem SPN still auf NTLM
   zurueck – das waere kein Ticket, sondern ein Challenge-Response gegen ein
   Kennwort, das der Server gar nicht pruefen kann.
2. **Einstufig abgeschlossen.** ``GSS_S_CONTINUE_NEEDED`` heisst: ein
   mehrstufiges Verfahren (NTLM in SPNEGO). Wird abgewiesen.
3. **Mechanismus = Kerberos** (OID 1.2.840.113554.1.2.2 bzw. die
   Microsoft-Variante 1.2.840.48018.1.2.2).
4. Ticket-Signatur, Laufzeit und Replay prueft die Bibliothek selbst (Keytab,
   Replay-Cache unter ``/var/tmp``).

WAS DIESES MODUL NICHT TUT
---------------------------
Es stellt **keine** Jarvis-Sitzung aus und kennt keine Freigaben. Es sagt nur:
"dieses Ticket gehoert zu ``name@REALM``". Realm-Abgleich, Freigabe, Sperre,
Lizenz und Sitzung entscheidet ``main.py`` – dieselbe Trennung wie bei
``addin_sso.py``.

EINGERICHTET IST ES, SOBALD DIE KEYTAB LIEGT
--------------------------------------------
Pfad: ``JARVIS_KERBEROS_KEYTAB`` oder ``data/kerberos/http.keytab``. Fehlt sie,
antwortet der Endpunkt sofort "nicht eingerichtet", und der Client nimmt die
Kennwortmaske – ohne dass Windows ueberhaupt ein Ticket anfordert.
"""

from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path

BASIS_DIR = Path(__file__).resolve().parent.parent
KEYTAB_VORGABE = BASIS_DIR / "data" / "kerberos" / "http.keytab"

GSS_S_COMPLETE = 0
GSS_S_CONTINUE_NEEDED = 1
GSS_C_GSS_CODE = 1
GSS_C_MECH_CODE = 2

# DER-Inhalt der Mechanismus-OIDs (ohne Tag/Laenge, so wie gss_OID_desc sie traegt)
_OID_KRB5 = bytes.fromhex("2a864886f712010202")       # 1.2.840.113554.1.2.2
_OID_KRB5_MS = bytes.fromhex("2a864882f712010202")    # 1.2.840.48018.1.2.2

_NTLM_KENNUNG = b"NTLMSSP\x00"


class KerberosFehler(Exception):
    """Ticket nicht annehmbar; der Text ist fuer Journal und Antwort gedacht."""


class _Puffer(ctypes.Structure):
    _fields_ = [("length", ctypes.c_size_t), ("value", ctypes.c_void_p)]


class _Oid(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("elements", ctypes.c_void_p)]


_lock = threading.Lock()
_lib = None
_registriert: str | None = None


def keytab_pfad() -> Path:
    """Ort der Keytab (Umgebung vor Vorgabe)."""
    roh = (os.environ.get("JARVIS_KERBEROS_KEYTAB") or "").strip()
    return Path(roh) if roh else KEYTAB_VORGABE


def _bibliothek():
    """Laedt libgssapi_krb5 einmal und setzt die Signaturen. Wirft KerberosFehler."""
    global _lib
    if _lib is not None:
        return _lib
    try:
        lib = ctypes.CDLL("libgssapi_krb5.so.2")
    except OSError as e:
        raise KerberosFehler(f"libgssapi_krb5 nicht ladbar ({e})") from e
    try:
        _signaturen(lib)
    except AttributeError as e:
        # Fehlendes Symbol: eine andere GSSAPI-Fassung. Klartext statt Absturz.
        raise KerberosFehler(f"libgssapi_krb5 ohne benoetigte Funktion ({e})") from e
    _lib = lib
    return lib


def _signaturen(lib) -> None:
    """Argument- und Rueckgabetypen der benutzten Funktionen setzen."""
    u32p = ctypes.POINTER(ctypes.c_uint32)
    vpp = ctypes.POINTER(ctypes.c_void_p)
    pp = ctypes.POINTER(_Puffer)
    lib.gss_accept_sec_context.argtypes = [
        u32p, vpp, ctypes.c_void_p, pp, ctypes.c_void_p, vpp,
        ctypes.POINTER(ctypes.POINTER(_Oid)), pp, u32p, u32p, ctypes.c_void_p]
    lib.gss_accept_sec_context.restype = ctypes.c_uint32
    lib.gss_display_name.argtypes = [u32p, ctypes.c_void_p, pp, ctypes.c_void_p]
    lib.gss_display_name.restype = ctypes.c_uint32
    lib.gss_display_status.argtypes = [u32p, ctypes.c_uint32, ctypes.c_int,
                                       ctypes.c_void_p, u32p, pp]
    lib.gss_display_status.restype = ctypes.c_uint32
    lib.gss_release_buffer.argtypes = [u32p, pp]
    lib.gss_release_buffer.restype = ctypes.c_uint32
    lib.gss_release_name.argtypes = [u32p, vpp]
    lib.gss_release_name.restype = ctypes.c_uint32
    lib.gss_delete_sec_context.argtypes = [u32p, vpp, ctypes.c_void_p]
    lib.gss_delete_sec_context.restype = ctypes.c_uint32
    # MIT-Name; ``gsskrb5_register_acceptor_identity`` ist die Heimdal-Fassung
    # und fehlt in Debians libgssapi_krb5 (gemessen 2026-10-20).
    lib.krb5_gss_register_acceptor_identity.argtypes = [ctypes.c_char_p]
    lib.krb5_gss_register_acceptor_identity.restype = ctypes.c_uint32


def eingerichtet() -> tuple[bool, str]:
    """(bereit, Grund). Bereit = Keytab lesbar UND Bibliothek ladbar."""
    pfad = keytab_pfad()
    if not pfad.is_file():
        return False, f"keine Keytab unter {pfad}"
    if not os.access(pfad, os.R_OK):
        return False, f"Keytab {pfad} fuer den Dienst nicht lesbar"
    try:
        _bibliothek()
    except KerberosFehler as e:
        return False, str(e)
    return True, ""


def _statustext(lib, major: int, minor: int) -> str:
    """Klartext zu (major, minor) – der minor-Teil nennt die eigentliche Ursache
    (z. B. "Key version number for principal in key table is incorrect")."""
    teile = []
    for wert, art in ((major, GSS_C_GSS_CODE), (minor, GSS_C_MECH_CODE)):
        if not wert:
            continue
        ctx = ctypes.c_uint32(0)
        for _ in range(8):
            mn = ctypes.c_uint32(0)
            buf = _Puffer()
            if lib.gss_display_status(ctypes.byref(mn), wert, art, None,
                                      ctypes.byref(ctx), ctypes.byref(buf)) != GSS_S_COMPLETE:
                break
            try:
                if buf.length:
                    teile.append(ctypes.string_at(buf.value, buf.length).decode("utf-8", "replace"))
            finally:
                lib.gss_release_buffer(ctypes.byref(mn), ctypes.byref(buf))
            if not ctx.value:
                break
    return "; ".join(t for t in teile if t) or f"GSS-Fehler {major:#x}/{minor}"


def pruefe(token: bytes) -> tuple[str, bytes]:
    """Nimmt ein Negotiate-Token an. Rueckgabe ``(principal, antwort_token)``.

    ``principal`` ist z. B. ``name@FIRMA.LOCAL``; ``antwort_token`` (evtl. leer)
    gehoert fuer die gegenseitige Authentisierung zurueck in
    ``WWW-Authenticate: Negotiate <b64>``. Wirft :class:`KerberosFehler`."""
    global _registriert
    if not token:
        raise KerberosFehler("leeres Token")
    if token.startswith(_NTLM_KENNUNG):
        raise KerberosFehler("NTLM statt Kerberos (fehlt der SPN, oder spricht der "
                             "Client den Server nicht ueber den FQDN an?)")
    bereit, grund = eingerichtet()
    if not bereit:
        raise KerberosFehler(grund)
    lib = _bibliothek()
    pfad = str(keytab_pfad())
    with _lock:
        # Prozessweit: nur neu setzen, wenn sich der Pfad geaendert hat.
        if _registriert != pfad:
            if lib.krb5_gss_register_acceptor_identity(pfad.encode()) != GSS_S_COMPLETE:
                raise KerberosFehler(f"Keytab {pfad} nicht verwendbar")
            _registriert = pfad

    minor = ctypes.c_uint32(0)
    ctx = ctypes.c_void_p(None)
    name = ctypes.c_void_p(None)
    mech = ctypes.POINTER(_Oid)()
    rein = _Puffer(len(token), ctypes.cast(ctypes.create_string_buffer(token, len(token)),
                                            ctypes.c_void_p))
    raus = _Puffer()
    flags = ctypes.c_uint32(0)
    zeit = ctypes.c_uint32(0)
    try:
        major = lib.gss_accept_sec_context(
            ctypes.byref(minor), ctypes.byref(ctx), None, ctypes.byref(rein), None,
            ctypes.byref(name), ctypes.byref(mech), ctypes.byref(raus),
            ctypes.byref(flags), ctypes.byref(zeit), None)
        if major == GSS_S_CONTINUE_NEEDED:
            raise KerberosFehler("mehrstufiges Verfahren (NTLM in SPNEGO) – nur "
                                 "Kerberos wird angenommen")
        if major != GSS_S_COMPLETE:
            raise KerberosFehler(_statustext(lib, major, minor.value))
        oid = b""
        if mech and mech.contents.length and mech.contents.elements:
            oid = ctypes.string_at(mech.contents.elements, mech.contents.length)
        if oid not in (_OID_KRB5, _OID_KRB5_MS):
            raise KerberosFehler(f"Mechanismus {oid.hex() or '?'} ist nicht Kerberos")
        anzeige = _Puffer()
        mn = ctypes.c_uint32(0)
        if lib.gss_display_name(ctypes.byref(mn), name, ctypes.byref(anzeige),
                                None) != GSS_S_COMPLETE:
            raise KerberosFehler("Benutzername des Tickets nicht lesbar")
        try:
            principal = ctypes.string_at(anzeige.value, anzeige.length).decode("utf-8")
        finally:
            lib.gss_release_buffer(ctypes.byref(mn), ctypes.byref(anzeige))
        antwort = ctypes.string_at(raus.value, raus.length) if raus.length else b""
        return principal, antwort
    finally:
        mn = ctypes.c_uint32(0)
        if raus.length:
            lib.gss_release_buffer(ctypes.byref(mn), ctypes.byref(raus))
        if name.value:
            lib.gss_release_name(ctypes.byref(mn), ctypes.byref(name))
        if ctx.value:
            lib.gss_delete_sec_context(ctypes.byref(mn), ctypes.byref(ctx), None)


def konto_aus_principal(principal: str, realm_erwartet: str) -> str:
    """``name@REALM`` -> blosser Kontoname (klein). Wirft KerberosFehler bei
    fremdem Realm (Vertrauensstellung) oder Dienst-Principal (``a/b@R``)."""
    name, _, realm = (principal or "").rpartition("@")
    if not name or not realm:
        raise KerberosFehler(f"Principal ohne Realm: {principal!r}")
    if realm.upper() != (realm_erwartet or "").strip().upper():
        raise KerberosFehler(f"fremder Realm {realm} (erwartet "
                             f"{(realm_erwartet or '?').upper()})")
    if "/" in name or "\\" in name:
        raise KerberosFehler(f"kein Benutzer-Principal: {principal!r}")
    return name.strip().lower()
