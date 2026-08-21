"""Excel-Add-in: Manifest-Erzeugung.

**Was das ist:** ein Office *Web*-Add-in (Office.js), das ein Chatfenster in
Excel oeffnet. Der Benutzer fragt etwas zur **gerade geoeffneten Arbeitsmappe**
("was faellt an Spalte D auf?", "trage in G2:G40 die Marge ein"); geantwortet
wird von einem Agentenlauf auf dem Server (``POST /api/excel/ask``).

WAS DIESES ADD-IN VOM OUTLOOK-ADD-IN UNTERSCHEIDET
--------------------------------------------------
Der wichtigste Unterschied ist nicht das Manifest, sondern **wo die Daten
liegen**: die Arbeitsmappe liegt im CLIENT, der Agent auf dem Server. Es gibt
deshalb keinen Werkzeugzugriff auf die Mappe – das Fenster liefert einen
Ueberblick mit der Frage mit und fuehrt Aenderungen nach ausdruecklicher
Bestaetigung selbst aus. Die Begruendung dazu steht in ``excel_ask.py``.

Zwei Folgen fuer das Manifest:

* ``ReadWriteDocument`` statt ``ReadItem``. Das Add-in SCHREIBT in die Mappe –
  aber erst, nachdem der Benutzer den Vorschlag in einer Diff-Ansicht gesehen
  und bestaetigt hat. Ein geringeres Recht gibt es fuer diesen Zweck nicht.
* **Kein SSO – und JEDER Benutzer meldet sich im Fenster an.** Das
  Outlook-Add-in meldet sich kennwortlos ueber das Exchange-Identity-Token an
  (``getUserIdentityTokenAsync``); das ist eine Mailbox-API und in Excel nicht
  vorhanden.

  WICHTIG, WEIL HIER ZUNAECHST DAS GEGENTEIL STAND: in Excel **am
  Arbeitsplatz** laeuft das Aufgabenfenster in einer eigenen WebView2-Instanz
  (auf dem Mac WKWebView) mit **eigenem localStorage**. Eine Anmeldung in
  Chrome oder Edge gilt dort NICHT – der Speicher ist an das Browserprofil
  gebunden, und das von Office ist ein anderes. Die Anmeldung im Fenster ist
  also Pflicht, nicht Rueckfall; sie bleibt bestehen, bis der Office-Cache
  geleert oder das Add-in entfernt wird.

  Nur in **Excel im Web** ist das Fenster ein iframe im echten Browser und
  traegt den Origin dieses Servers – dort greift die vorhandene
  Jarvis-Anmeldung ueber denselben localStorage, sofern der Browser Speicher
  fremder Herkunft nicht sperrt (strenge Cookie-Regeln, privates Fenster,
  Safari-ITP; dafuer gibt es in ``excel.js`` den Rueckfall im Arbeitsspeicher).

WAS MICROSOFT-SEITIG NICHT IN UNSERER HAND LIEGT (Stand 2026-08)
----------------------------------------------------------------
**Einen Exchange-Katalog wie fuer Outlook gibt es fuer Excel nicht** – Add-ins
fuer Arbeitsmappen verteilt ein Exchange nicht (``New-App`` gilt nur fuer
Postfach-Add-ins). Ohne Microsoft 365 bleibt der Weg ueber einen freigegebenen
Netzwerkordner, den jeder Arbeitsplatz in den Excel-Optionen als
vertrauenswuerdigen Katalog eintraegt (per Gruppenrichtlinie ausrollbar). Das
ist eine Eigenschaft der Plattform, keine dieses Add-ins.

Auch hier gilt: VSTO/COM scheidet aus (neues Office unterstuetzt es nicht mehr),
und das XML-Manifest ist die einzige Form, die ohne Microsoft 365 installierbar
ist.

WARUM DAS MANIFEST ERZEUGT UND NICHT ALS DATEI GEPFLEGT WIRD
-------------------------------------------------------------
Gleiche Begruendung wie beim Outlook-Add-in: jede URL darin muss auf **diesen**
Server zeigen, eine Repo-Datei muesste pro Server von Hand angepasst werden.
Der Administrator laedt ``/excel-addin/manifest.xml`` und hat eine fertige
Datei.
"""

from __future__ import annotations

import uuid

# Die Helfer sind bewusst GETEILT und nicht kopiert: Basis-URL-Aufloesung,
# XML-Maskierung, Erkennung lokaler Namen und der Markenname gelten fuer beide
# Add-ins gleichermassen. Eine zweite Fassung waere genau das Drift-Muster, das
# in diesem Projekt schon mehrfach teuer war.
from backend.addin import (  # noqa: F401  (Re-Export ist gewollt, s.u.)
    basis_url,
    ist_lokale_basis,
    x,
    anzeigename,
    ICON_GROESSEN,
)

# Eigener Zaehler, ausschliesslich fuer DIESES Manifest – nicht die
# Projektversion und **nicht** ``addin.ADDIN_VERSION``. Die beiden Add-ins
# werden getrennt installiert und muessen sich getrennt aktualisieren lassen;
# ein gemeinsamer Zaehler wuerde bei jeder Aenderung am einen auch das andere
# als veraltet ausweisen.
#
# ZU ERHOEHEN NUR BEI AENDERUNGEN AM MANIFEST SELBST (Knoepfe, Berechtigungen,
# Anforderungssatz, URLs). Die Fenster-Dateien liegen auf diesem Server, gehen
# mit ``no-store`` hinaus und erreichen jede Installation beim naechsten
# Oeffnen – dafuer ist die Zahl NICHT zu erhoehen.
EXCEL_ADDIN_VERSION = "1.0.0.0"

# Anforderungssatz. 1.7 deckt alles, was das Fenster braucht:
# ``getUsedRange``, ``formulas``/``formulasLocal``, ``valueTypes``,
# benannte Bereiche und ``worksheet.onSelectionChanged``.
#
# HOEHER WAERE EIN FEHLER, kein Fortschritt: der Anforderungssatz entscheidet,
# welche Excel-Staende das Add-in ueberhaupt installieren koennen. 1.7 kam mit
# Office 2019/M365 und ist auf allem verfuegbar, was heute im Einsatz ist.
#
# SENKEN HILFT ABER AUCH NICHT – Lehre vom 2026-08-21. Auf einem Office
# Professional Plus 2019 war der Anforderungssatz ERFUELLT: das Add-in liess
# sich installieren, der Menueband-Knopf erschien, das Fenster ging auf – und
# blieb weiss. Die Kaufversionen bis einschliesslich Office 2019 stellen
# Aufgabenfenstern den Trident-WebView (Internet Explorer) bereit, und der
# beherrscht nur ES5 und keine CSS-Variablen. Das ist eine Grenze des WEBVIEW,
# nicht des API-Satzes: wer hier die Zahl herunterdreht, aendert daran nichts
# und verliert nur Funktionen. WebView2 setzt Microsoft 365 bzw. Office LTSC
# 2021 voraus und laesst sich fuer Kaufversionen nicht erzwingen (kein
# Registry-Schalter; die Laufzeitumgebung von Hand zu installieren genuegt
# nicht). Die Absage an den Benutzer steht in `excel.js::start()`.
EXCEL_API_MIN = "1.7"

# EIGENER Namensraum – NICHT der aus addin.py. Die Kennung wird aus der
# Basis-URL abgeleitet; mit demselben Namensraum bekaemen Outlook- und
# Excel-Add-in auf demselben Server dieselbe Kennung, und Office haelt zwei
# Add-ins mit gleicher Id fuer dasselbe. Nicht aendern: eine Aenderung erzeugt
# ueberall eine neue Kennung, das alte Add-in bliebe daneben installiert.
_NS = uuid.UUID("9c1d4e7a-58b2-5f36-a0d1-7e93b6c2f481")


def addin_id(basis: str) -> str:
    """Stabile Kennung dieses Add-ins fuer diese Basis-URL."""
    return str(uuid.uuid5(_NS, (basis or "jarvis").lower() + "/excel-addin"))


def dateiname() -> str:
    """Dateiname des Manifests fuer den Download – folgt dem Branding.

    Gleiche Entschaerfung wie ``addin.dateiname()`` (der Wert geht in einen
    ``Content-Disposition``-Kopf und darf dort weder Anfuehrungszeichen noch
    Zeilenumbrueche einschleusen), nur mit anderem Stamm – sonst laegen beide
    Manifeste unter demselben Namen im Download-Ordner und der Administrator
    installiert das falsche.
    """
    roh = anzeigename().lower()
    sauber = "".join(c if (c.isascii() and (c.isalnum() or c in "-_")) else "-"
                     for c in roh)
    sauber = "-".join(t for t in sauber.split("-") if t)[:40]
    return "%s-excel-addin.xml" % (sauber or "jarvis")


def manifest(basis: str) -> str:
    """Vollstaendiges XML-Manifest fuer diese Basis-URL.

    **Die Reihenfolge der Elemente ist Schema-Vorgabe, keine Kosmetik** – ein
    vertauschtes Element laesst Office das Manifest mit einer generischen
    Meldung ablehnen ("Das Manifest ist ungueltig"), die nicht sagt, welches.

    Drei Unterschiede zum Postfach-Manifest, die man kennen muss:

    * ``xsi:type="TaskPaneApp"`` und ``DefaultSettings`` statt ``FormSettings``
      – ein Arbeitsmappen-Add-in hat kein Lese-Formular.
    * Die ``VersionOverrides`` liegen in einem ANDEREN Namensraum
      (``taskpaneappversionoverrides``); der Mail-Namensraum wuerde hier
      wortlos nicht greifen.
    * Die ``Group`` braucht ein eigenes ``Icon`` und die Aktion eine
      ``TaskpaneId``. Beides ist bei ``MailApp`` nicht noetig und hier Pflicht.
    """
    basis = (basis or "").rstrip("/")
    marke = anzeigename()
    titel = "%s Tabellen-Assistent" % marke
    kurz = "%s Assistent" % marke          # Menueband, muss kurz sein
    beschreibung = (
        "Fragen zur geöffneten Arbeitsmappe stellen, Tabellen auswerten und "
        "Änderungen vorschlagen lassen. Jede Änderung wird vor dem Schreiben "
        "angezeigt und muss bestätigt werden."
    )
    # Die Manifest-Version geht als Abfrageparameter mit – Office.js hat keine
    # Schnittstelle, mit der ein Fenster die Version seines EIGENEN Manifests
    # lesen koennte. Das Fenster vergleicht den Wert mit
    # ``GET /api/excel-addin/version`` und weist ein veraltetes Manifest aus.
    # KAEME JE EIN ZWEITER PARAMETER DAZU, muss das ``&`` als ``&amp;`` in das
    # XML – sonst ist die Datei unlesbar.
    tp = "%s/excel-addin/taskpane.html?mv=%s" % (basis, EXCEL_ADDIN_VERSION)
    # XML verbietet "--" INNERHALB eines Kommentars, und es gibt dafuer keine
    # Entity. Eine Umlaut-Domaene ist im Punycode genau so geschrieben
    # (``xn--mller-kva``): das Manifest waere unlesbar, und Office meldete nur
    # das generische "Das Manifest ist ungueltig". In den ATTRIBUTEN steht die
    # Adresse unveraendert.
    basis_komm = x(basis).replace("--", "&#45;&#45;")

    return """<?xml version="1.0" encoding="UTF-8"?>
<!--
  %(titel)s – Excel-Add-in
  Erzeugt von %(basis_komm)s/excel-addin/manifest.xml
  Diese Datei nicht von Hand bearbeiten: sie wird bei jedem Abruf neu aus der
  Serverkonfiguration erzeugt. Aenderungen gehen beim naechsten Abruf verloren.
-->
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xmlns:bt="http://schemas.microsoft.com/office/officeappbasictypes/1.0"
           xmlns:ov="http://schemas.microsoft.com/office/taskpaneappversionoverrides"
           xsi:type="TaskPaneApp">
  <Id>%(id)s</Id>
  <Version>%(version)s</Version>
  <ProviderName>%(marke)s</ProviderName>
  <DefaultLocale>de-DE</DefaultLocale>
  <DisplayName DefaultValue="%(titel)s"/>
  <Description DefaultValue="%(desc)s"/>
  <IconUrl DefaultValue="%(basis)s/excel-addin/icon-64.png"/>
  <HighResolutionIconUrl DefaultValue="%(basis)s/excel-addin/icon-128.png"/>
  <SupportUrl DefaultValue="%(basis)s/portal"/>
  <AppDomains>
    <AppDomain>%(basis)s</AppDomain>
  </AppDomains>
  <Hosts>
    <Host Name="Workbook"/>
  </Hosts>
  <Requirements>
    <Sets DefaultMinVersion="1.1">
      <Set Name="ExcelApi" MinVersion="%(excelapi)s"/>
    </Sets>
  </Requirements>
  <DefaultSettings>
    <SourceLocation DefaultValue="%(tp)s"/>
  </DefaultSettings>
  <!--
    ReadWriteDocument ist noetig, WEIL das Add-in Zellen schreibt – aber erst
    nach ausdruecklicher Bestaetigung einer Diff-Ansicht. Der Server fuehrt
    KEINE Zellaenderung aus; er schlaegt vor, das Fenster schreibt.
  -->
  <Permissions>ReadWriteDocument</Permissions>

  <VersionOverrides xmlns="http://schemas.microsoft.com/office/taskpaneappversionoverrides"
                    xsi:type="VersionOverridesV1_0">
    <Hosts>
      <Host xsi:type="Workbook">
        <DesktopFormFactor>
          <GetStarted>
            <Title resid="gsTitle"/>
            <Description resid="gsDesc"/>
            <LearnMoreUrl resid="gsUrl"/>
          </GetStarted>
          <ExtensionPoint xsi:type="PrimaryCommandSurface">
            <OfficeTab id="TabHome">
              <Group id="jarvisXlGroup">
                <Label resid="grpLabel"/>
                <Icon>
                  <bt:Image size="16" resid="ico16"/>
                  <bt:Image size="32" resid="ico32"/>
                  <bt:Image size="80" resid="ico80"/>
                </Icon>
                <Control xsi:type="Button" id="jarvisXlTaskpane">
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
                    <TaskpaneId>jarvisXlPane</TaskpaneId>
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
        <bt:Image id="ico16" DefaultValue="%(basis)s/excel-addin/icon-16.png"/>
        <bt:Image id="ico32" DefaultValue="%(basis)s/excel-addin/icon-32.png"/>
        <bt:Image id="ico80" DefaultValue="%(basis)s/excel-addin/icon-80.png"/>
      </bt:Images>
      <bt:Urls>
        <bt:Url id="tpUrl" DefaultValue="%(tp)s"/>
        <bt:Url id="gsUrl" DefaultValue="%(basis)s/portal"/>
      </bt:Urls>
      <bt:ShortStrings>
        <bt:String id="grpLabel" DefaultValue="%(marke)s"/>
        <bt:String id="btnLabel" DefaultValue="%(kurz)s"/>
        <bt:String id="gsTitle" DefaultValue="%(titel)s"/>
      </bt:ShortStrings>
      <bt:LongStrings>
        <bt:String id="btnTip" DefaultValue="%(desc)s"/>
        <bt:String id="gsDesc" DefaultValue="%(desc)s"/>
      </bt:LongStrings>
    </Resources>
  </VersionOverrides>
</OfficeApp>
""" % {
        "id": addin_id(basis),
        "version": EXCEL_ADDIN_VERSION,
        "excelapi": EXCEL_API_MIN,
        "basis": x(basis),
        "basis_komm": basis_komm,
        "marke": x(marke),
        "titel": x(titel),
        "kurz": x(kurz),
        "desc": x(beschreibung),
        "tp": x(tp),
    }
