"""Outlook-Add-in: Manifest-Erzeugung und Auslieferung.

**Was das ist:** ein Office *Web*-Add-in (Office.js), das die Funktionen des
Bereichs ``/email`` in ein Aufgabenfenster in Outlook holt – eigenes Postfach
hinterlegen, Regeln pflegen, Protokoll lesen – und zusaetzlich das, wofuer es
ein Add-in ueberhaupt braucht: **die gerade markierte Nachricht mit einer Regel
verarbeiten** (``POST /api/email/rules/{id}/run_message``).

WARUM EIN WEB-ADD-IN UND KEIN VSTO/COM-PLUGIN
---------------------------------------------
Das neue Outlook fuer Windows unterstuetzt **keine** VSTO- und COM-Add-ins mehr;
migriert werden muss auf Web-Add-ins. Ein Web-Add-in laeuft ausserdem im
klassischen Outlook, in Outlook im Web und auf Mac – ein COM-Add-in nur im
klassischen Windows-Outlook. Es gibt also keine zweite ernsthafte Option.

WAS MICROSOFT-SEITIG NICHT IN UNSERER HAND LIEGT (Stand 2026-08)
----------------------------------------------------------------
Das **neue** Outlook fuer Windows unterstuetzt derzeit keine
**On-Premises-Exchange-Konten** (auch keine Hybrid-/Sovereign-Konten) – es kann
ein Postfach auf einem Exchange 2019 im Haus also gar nicht erst oeffnen, ganz
unabhaengig von Add-ins. Wo das Postfach on-prem liegt, sind die tragfaehigen
Wege deshalb **klassisches Outlook** (Microsoft 365 / Office 2021+) und
**Outlook im Web** des eigenen Exchange. Das ist keine Eigenschaft dieses
Add-ins, sondern des Clients; es ist in ``docs/outlook-addin.md`` benannt,
damit niemand den Fehler bei uns sucht.

MANIFEST-FORM: XML, NICHT DAS UNIFIED JSON MANIFEST
---------------------------------------------------
Das JSON-Manifest ("unified manifest for Microsoft 365") setzt eine
Bereitstellung ueber Microsoft 365 voraus. Ein Exchange im Haus kennt nur das
XML-Manifest ("add-in only manifest"), und genau darueber laeuft das Sideloading
per *Add-Ins verwalten* bzw. per Exchange-Verwaltungskonsole. Deshalb XML –
und deshalb ``Mailbox 1.3`` als Anforderung: hoehere Anforderungssaetze wuerden
das Add-in auf einem Exchange im Haus gar nicht erst installierbar machen.

WARUM DAS MANIFEST ERZEUGT UND NICHT ALS DATEI GEPFLEGT WIRD
-------------------------------------------------------------
Jede URL darin muss auf **diesen** Server zeigen. Eine Datei im Repo muesste auf
jedem Server von Hand angepasst werden – das ist genau das Drift-Muster, das in
diesem Projekt schon mehrfach teuer war (zuletzt die Landing-Page). Der
Administrator laedt ``/addin/manifest.xml`` und hat eine fertige Datei.

Die **Kennung** (``<Id>``) ist deshalb nicht fest verdrahtet, sondern aus der
Basis-URL abgeleitet (UUIDv5): auf demselben Server bleibt sie ueber alle
Aktualisierungen stabil (sonst gaelte das Add-in als ein neues und muesste neu
installiert werden), zwei Jarvis-Instanzen am selben Exchange kollidieren aber
nicht miteinander.
"""

from __future__ import annotations

import os
import uuid
from xml.sax.saxutils import escape as _escape


def x(wert) -> str:
    """XML-Maskierung fuer Text UND Attributwerte – die EINZIGE hier.

    ``xml.sax.saxutils.escape`` maskiert **kein** Anfuehrungszeichen. Ein
    Branding-Name wie ``Nex"us`` hat damit das ``DefaultValue="…"`` zerlegt und
    ein unlesbares Manifest erzeugt (beim Bauen aufgefallen). ``&quot;`` ist in
    Text und Attribut gleichermassen gueltig, deshalb genuegt eine Funktion –
    zwei Konventionen nebeneinander waren genau die Fehlerquelle.
    """
    return _escape(str(wert), {'"': "&quot;", "'": "&apos;"})

# Eigener Zaehler, ausschliesslich fuer das Add-in-Manifest – NICHT die
# Projektversion. Outlook laedt ein geaendertes Manifest nur dann neu, wenn
# diese Zahl steigt; wer am Manifest oder an den Aufgabenfenster-Dateien etwas
# aendert, das ein installiertes Add-in erreichen soll, muss sie erhoehen.
ADDIN_VERSION = "1.1.0.0"

# Anforderungssatz. 1.3 ist die hoechste Stufe, die auf einem Exchange im Haus
# durchweg verfuegbar ist; alles darueber (z.B. 1.14 fuer ein Aufgabenfenster
# ohne markierte Nachricht) wuerde die Installation dort verhindern.
MAILBOX_MIN = "1.3"

# Fester Namensraum fuer die abgeleitete Kennung. Nicht aendern – eine
# Aenderung erzeugt auf jedem Server eine neue Add-in-Kennung, und Outlook haelt
# das Ergebnis fuer ein anderes Add-in (das alte bliebe daneben installiert).
_NS = uuid.UUID("6b3f1f8e-2c74-5a9d-9f21-4d7c8e2a1b60")


def basis_url(request=None) -> str:
    """Basis-URL dieses Servers, ohne abschliessenden Schraegstrich.

    Reihenfolge: ausdrueckliche Einstellung → Anfrage → leer. Die Einstellung
    (``JARVIS_ADDIN_BASE``) gibt es, weil der Host-Kopf hinter einem
    Rueckwaertsproxy nicht der Name sein muss, unter dem die Arbeitsplaetze den
    Server erreichen – und im Manifest steht die URL, die der CLIENT aufruft.

    **Immer https**: Office laedt Add-in-Quellen ausschliesslich ueber HTTPS.
    Ein Manifest mit ``http://`` wird stillschweigend nicht geladen, deshalb
    wird das Schema hier hart gesetzt statt uebernommen.
    """
    fest = (os.environ.get("JARVIS_ADDIN_BASE") or "").strip()
    if not fest:
        try:
            from backend.config import config  # noqa: PLC0415
            fest = str(config.get_setting("addin_base_url", "") or "").strip()
        except Exception:  # noqa: BLE001
            fest = ""
    if fest:
        roh = fest
    elif request is not None:
        roh = str(getattr(request, "base_url", "") or "")
    else:
        roh = ""
    roh = roh.strip().rstrip("/")
    if not roh:
        return ""
    if roh.startswith("http://"):
        roh = "https://" + roh[len("http://"):]
    elif not roh.startswith("https://"):
        roh = "https://" + roh
    return roh


# Hostnamen, unter denen NUR der Server selbst erreichbar ist. Ein Manifest mit
# einer solchen Adresse ist auf jedem Arbeitsplatz unbrauchbar – und der Fehler
# ist uebel zu deuten: Outlook installiert das Add-in klaglos, das
# Aufgabenfenster bleibt dann leer (der Arbeitsplatz hat unter "localhost"
# keinen Jarvis). Deshalb wird die Auslieferung verweigert statt gewarnt.
_LOKALE_NAMEN = ("localhost", "127.0.0.1", "[::1]", "::1", "0.0.0.0")


def ist_lokale_basis(basis: str) -> bool:
    """True, wenn die Basis-URL nur auf dem Server selbst gilt."""
    wert = (basis or "").strip().lower()
    for schema in ("https://", "http://"):
        if wert.startswith(schema):
            wert = wert[len(schema):]
            break
    host = wert.split("/")[0].split("?")[0]
    # Port abtrennen – aber nicht innerhalb einer IPv6-Klammer.
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.split(":")[0]
    return host in _LOKALE_NAMEN


def addin_id(basis: str) -> str:
    """Stabile Add-in-Kennung fuer diese Basis-URL (siehe Modulkopf)."""
    return str(uuid.uuid5(_NS, (basis or "jarvis").lower() + "/addin"))


def anzeigename() -> str:
    """Name des Add-ins – folgt dem Branding.

    Gleiche Quelle und gleiche Begruendung wie
    ``mail_accounts.kategorie_name()``: der Name steht im Menueband jedes
    Arbeitsplatzes. Ein White-Label-System darf dort nicht "Jarvis" schreiben.
    """
    try:
        from backend.mail_accounts import kategorie_name  # noqa: PLC0415
        name = (kategorie_name() or "").strip()
    except Exception:  # noqa: BLE001
        name = ""
    return (name or "Jarvis")[:40]


def dateiname() -> str:
    """Dateiname des Manifests fuer den Download – folgt dem Branding.

    Der Administrator legt die Datei ab und waehlt sie beim Sideloading wieder
    aus; auf einem White-Label-System hat sie deshalb den Namen des Hauses zu
    tragen und nicht "jarvis" (gemeldet 2026-08-17).

    Entschaerft auf ``[A-Za-z0-9_-]`` und klein: der Wert kommt aus dem
    Branding-Formular, geht in einen ``Content-Disposition``-Kopf und darf dort
    weder ein Anfuehrungszeichen noch einen Zeilenumbruch einschleusen. Bleibt
    nach dem Entschaerfen nichts uebrig (z.B. ein rein kyrillischer Name), gilt
    ``jarvis`` – ein Dateiname ohne Stamm waere schlechter als ein generischer.
    """
    roh = anzeigename().lower()
    sauber = "".join(c if (c.isascii() and (c.isalnum() or c in "-_")) else "-"
                     for c in roh)
    sauber = "-".join(t for t in sauber.split("-") if t)[:40]
    return "%s-outlook-addin.xml" % (sauber or "jarvis")


# Groessen, die das Manifest anfordert. 16/32/80 stehen im Menueband, 64/128
# in der Add-in-Verwaltung.
ICON_GROESSEN = (16, 32, 64, 80, 128)


def manifest(basis: str) -> str:
    """Vollstaendiges XML-Manifest fuer diese Basis-URL.

    **Die Reihenfolge der Elemente ist Schema-Vorgabe, keine Kosmetik** – ein
    vertauschtes Element laesst Exchange das Manifest mit einer generischen
    Meldung ablehnen ("Das Manifest ist ungueltig"), die nicht sagt, welche.

    Alles, was aus der Konfiguration kommt (Anzeigename), wird escaped: der
    Wert stammt aus dem Branding-Formular und ist damit Fremdeingabe.
    """
    basis = (basis or "").rstrip("/")
    marke = anzeigename()
    titel = "%s E-Mail" % marke
    beschreibung = (
        "Regeln fuer eingehende E-Mails anlegen und pflegen, das eigene "
        "Postfach hinterlegen, das Protokoll einsehen und die gerade "
        "geoeffnete Nachricht mit einer Regel verarbeiten."
    )
    tp = "%s/addin/taskpane.html" % basis
    # XML VERBIETET "--" INNERHALB EINES KOMMENTARS – und ``x()`` kann das nicht
    # maskieren, weil es dafuer keine Entity gibt. Eine Umlaut-Domaene ist im
    # Punycode genau so geschrieben (``xn--mller-kva``), ebenso jeder Host mit
    # doppeltem Bindestrich: das Manifest waere unlesbar, und Exchange meldete
    # nur das generische "Das Manifest ist ungueltig". Fuer den Kommentar wird
    # die Adresse deshalb entschaerft; in den ATTRIBUTEN steht sie unveraendert.
    basis_komm = x(basis).replace("--", "&#45;&#45;")

    return """<?xml version="1.0" encoding="UTF-8"?>
<!--
  %(titel)s – Outlook-Add-in
  Erzeugt von %(basis_komm)s/addin/manifest.xml
  Diese Datei nicht von Hand bearbeiten: sie wird bei jedem Abruf neu aus der
  Serverkonfiguration erzeugt. Aenderungen gehen beim naechsten Abruf verloren.
-->
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xmlns:bt="http://schemas.microsoft.com/office/officeappbasictypes/1.0"
           xmlns:ov="http://schemas.microsoft.com/office/mailappversionoverrides"
           xsi:type="MailApp">
  <Id>%(id)s</Id>
  <Version>%(version)s</Version>
  <ProviderName>%(marke)s</ProviderName>
  <DefaultLocale>de-DE</DefaultLocale>
  <DisplayName DefaultValue="%(titel)s"/>
  <Description DefaultValue="%(desc)s"/>
  <IconUrl DefaultValue="%(basis)s/addin/icon-64.png"/>
  <HighResolutionIconUrl DefaultValue="%(basis)s/addin/icon-128.png"/>
  <SupportUrl DefaultValue="%(basis)s/email"/>
  <AppDomains>
    <AppDomain>%(basis)s</AppDomain>
  </AppDomains>
  <Hosts>
    <Host Name="Mailbox"/>
  </Hosts>
  <Requirements>
    <Sets>
      <Set Name="Mailbox" MinVersion="%(mailbox)s"/>
    </Sets>
  </Requirements>
  <FormSettings>
    <Form xsi:type="ItemRead">
      <DesktopSettings>
        <SourceLocation DefaultValue="%(tp)s"/>
        <RequestedHeight>420</RequestedHeight>
      </DesktopSettings>
    </Form>
  </FormSettings>
  <!--
    ReadItem genuegt und ist Absicht: das Add-in liest die Kennung und den
    Betreff der markierten Nachricht. JEDE Aenderung am Postfach macht der
    Server mit den Zugangsdaten des Benutzers (Regel-Lauf) – nicht der Browser.
    Ein hoeheres Recht hier waere ein Recht, das niemand braucht.
  -->
  <Permissions>ReadItem</Permissions>
  <Rule xsi:type="RuleCollection" Mode="Or">
    <Rule xsi:type="ItemIs" ItemType="Message" FormType="Read"/>
  </Rule>
  <DisableEntityHighlighting>false</DisableEntityHighlighting>

  <VersionOverrides xmlns="http://schemas.microsoft.com/office/mailappversionoverrides"
                    xsi:type="VersionOverridesV1_0">
    <Requirements>
      <bt:Sets DefaultMinVersion="%(mailbox)s">
        <bt:Set Name="Mailbox"/>
      </bt:Sets>
    </Requirements>
    <Hosts>
      <Host xsi:type="MailHost">
        <DesktopFormFactor>
          <ExtensionPoint xsi:type="MessageReadCommandSurface">
            <OfficeTab id="TabDefault">
              <Group id="jarvisMailGroup">
                <Label resid="grpLabel"/>
                <Control xsi:type="Button" id="jarvisMailTaskpane">
                  <Label resid="btnLabel"/>
                  <Supertip>
                    <Title resid="btnLabel"/>
                    <Description resid="btnTip"/>
                  </Supertip>
                  <Icon>
                    <bt:Image size="16" resid="ico16"/>
                    <bt:Image size="32" resid="ico32"/>
                    <bt:Image size="80" resid="ico80"/>
                  </Icon>
                  <Action xsi:type="ShowTaskpane">
                    <SourceLocation resid="tpUrl"/>
                  </Action>
                </Control>
              </Group>
            </OfficeTab>
          </ExtensionPoint>
        </DesktopFormFactor>
      </Host>
    </Hosts>
    <Resources>
      <bt:Images>
        <bt:Image id="ico16" DefaultValue="%(basis)s/addin/icon-16.png"/>
        <bt:Image id="ico32" DefaultValue="%(basis)s/addin/icon-32.png"/>
        <bt:Image id="ico80" DefaultValue="%(basis)s/addin/icon-80.png"/>
      </bt:Images>
      <bt:Urls>
        <bt:Url id="tpUrl" DefaultValue="%(tp)s"/>
      </bt:Urls>
      <bt:ShortStrings>
        <bt:String id="grpLabel" DefaultValue="%(marke)s"/>
        <bt:String id="btnLabel" DefaultValue="%(titel)s"/>
      </bt:ShortStrings>
      <bt:LongStrings>
        <bt:String id="btnTip" DefaultValue="%(desc)s"/>
      </bt:LongStrings>
    </Resources>
  </VersionOverrides>
</OfficeApp>
""" % {
        "id": addin_id(basis),
        "version": ADDIN_VERSION,
        "mailbox": MAILBOX_MIN,
        "basis": x(basis),
        "basis_komm": basis_komm,
        "marke": x(marke),
        "titel": x(titel),
        "desc": x(beschreibung),
        "tp": x(tp),
    }
