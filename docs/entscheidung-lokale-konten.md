# Lokale Admin-Konten in Jarvis – Prüfung und Entscheidung

Stand: 2026-11-13 · Status: **geprüft, voraussichtlich NICHT umgesetzt** (kein Code geändert).

## Anlass

Gewünscht war: Reguläre AD-Benutzer arbeiten ohne Admin-Rechte. Einstellungen sind nur über
eigene **lokale Jarvis-Konten** möglich (Muster `admin-<vorname.nachname>`). Beim Anlegen
soll geprüft werden, dass es den Anmeldenamen im AD nicht gibt.

## Entscheidung

Wird voraussichtlich **nicht** umgesetzt. Zwei Gründe:

1. **Vorgabe Offboarding:** Benutzer müssen beim Verlassen des Unternehmens automatisch
   gesperrt werden. Lokale Konten hängen nicht am AD, die Deaktivierung dort erreicht sie nicht.
2. **Verbot lokal gespeicherter Konten:** Ein eigener Kontenbestand mit Kennwort-Hashes
   auf dem Jarvis-Server widerspricht der Vorgabe.

Empfohlen ist stattdessen die Alternative unten.

## Ausgangslage im Code (2026-11-13)

- „Lokal“ gibt es nur für **ein** Konto: `jarvis` (`ALLOWED_USERS = {"jarvis"}` in
  `backend/main.py`). Geprüft wird es über PAM, also als Linux-Konto. Nur im Docker-Betrieb
  läuft die Prüfung über einen scrypt-Hash in `auth_state.json`. Jeder andere Name geht an das AD.
- Konten anlegen lässt sich nicht. `ALLOWED_USERS` ist eine Konstante und wird an rund
  20 Stellen geprüft, und zwar gegen den **eingetippten** Namen.
- Lokale Konten sind pauschal Admin. Sie werden **nie automatisch gesperrt** (`_sec_exempt`),
  sind von der Obergrenze gleichzeitiger Aufträge ausgenommen, und ihr Agent läuft
  privilegiert ohne Sandbox.
- Der Root-Broker setzt Linux-Kennwörter absichtlich nur für `jarvis` (Befund K2).

## Messung im AD von DEV (lesend, 2026-11-13)

| Abfrage | Ergebnis |
|---|---|
| bekanntes Benutzerkonto (Positivkontrolle) | gefunden ✓ |
| `admin-<vorname.nachname>` (der geplante Name) | nicht vorhanden |
| `jarvis`, `root`, `api`, `system` | nicht vorhanden |
| Konten mit Präfix `admin-` | **2 vorhanden** |

Das Präfix `admin-` ist im AD also schon in Gebrauch. Eine spätere Namensgleichheit ist
wahrscheinlich. ECHT wurde nicht gemessen (per SSH nicht erreichbar).

## Kernproblem bei einer Umsetzung: Namensgleichheit mit dem AD

Ob Jarvis lokal oder über das AD prüft, entscheidet heute der **rohe** Eingabetext. Die
Identität dahinter, also Ablagen, Chatverlauf, Gedächtnis und der Eintrag in
`auth_state.json` samt **2FA-Geheimnis**, hängt am **normierten** Namen (Domäne weg,
Kleinschreibung). `DOMÄNE\admin-x` geht deshalb an das AD und landet trotzdem in der
Identität des lokalen `admin-x`. Ein gleichnamiges AD-Konto übernimmt damit das lokale Konto.

- **Die AD-Prüfung allein beim Anlegen genügt nicht.** Ein AD-Konto kann später entstehen.
- **Lösung:** Den Namen zuerst normieren, dann lokal prüfen. Ist der Name lokal, gilt nur
  das lokale Kennwort, und das AD wird nie gefragt. Das muss auf **jedem** Anmeldeweg gelten.
  Die Windows-Anmeldung (Kerberos) macht das bereits normiert, prüft aber gegen die Konstante.
- **Folgen, die mitzuziehen wären:**
  - Die gleichnamige AD-Person ist ausgesperrt und sieht nur „Kennwort falsch“. Es bräuchte
    einen Hinweis im Journal bzw. für Admins.
  - Ihre Fehlversuche zählen gegen das lokale Admin-Konto. Die Sperre müsste deshalb begrenzt
    sein, sonst ist die Notfall-Administration blockierbar.
- Die AD-Prüfung beim Anlegen wäre dann nur noch eine zusätzliche Absicherung: Sie verhindert,
  dass man von vornherein ein Konto anlegt, das einen AD-Benutzer aussperrt.

## Gegenargumente zu lokalen Konten

1. **Offboarding (das schwerste Argument):** Das AD-Konto wird beim Austritt deaktiviert,
   das lokale Jarvis-Konto bleibt aktiv, bis jemand es von Hand sperrt. Ausgerechnet die
   Konten mit den meisten Rechten fallen aus dem zentralen Austrittsprozess
   (Personalabteilung → AD).
2. **Eigener Kennwortbestand ohne AD-Regeln:** Länge, Ablauf, Historie, Sperre und
   Self-Service-Reset des AD gelten nicht. Die Hashes liegen auf dem Jarvis-Server, der damit
   ein zusätzliches Angriffsziel wird.
3. **Keine zentrale Überwachung:** Anmeldungen und Fehlversuche erscheinen nicht im Protokoll
   der Domänencontroller und in keinem zentralen Monitoring (SIEM). Einen Angriff mit geratenen
   Kennwörtern auf ein Admin-Konto sieht nur Jarvis.
4. **Unsichtbar bei Berechtigungsprüfungen:** Lokale Admins stehen in keiner AD-Gruppe. Bei
   Rezertifizierungen und Audits tauchen sie nicht auf.
5. **Namensgleichheit mit dem AD:** Es droht die Übernahme von Daten und zweitem Faktor (siehe
   oben). Das ist nur beherrschbar, wenn jeder heutige und künftige Anmeldeweg korrekt
   normiert prüft.
6. **Mehr Konten mit Sonderrechten:** Keine automatische Sperre, privilegierte Agentenläufe
   ohne Sandbox. Jedes weitere lokale Konto vergrößert genau die Angriffsfläche, die am
   schwersten wiegt.
7. **Aussperren durch Fehlversuche:** Eine gleichnamige AD-Person oder ein Angreifer kann das
   lokale Admin-Konto über Fehlversuche sperren.
8. **Keine zentrale Mehrfaktor-Anmeldung:** Eine zentral über das AD gesteuerte
   Mehrfaktor-Anmeldung und zentrale Zugriffsregeln greifen nicht. Es bleibt nur der
   Zwei-Faktor-Code in Jarvis, den jeder selbst einrichtet und pflegt.

## Empfohlene Alternative (ohne Code-Änderung)

Ein eigenes **AD-Konto nur für die Jarvis-Verwaltung**, ohne Domänenrechte, in einer AD-Gruppe,
die als `ad_admins_group` eingetragen ist. Das normale AD-Konto bleibt ohne Admin-Rechte.

- Offboarding, Kennwortregeln, Überwachung und Berechtigungsprüfung bleiben zentral im AD.
- Das Admin-Konto muss **zusätzlich** zur Admin-Gruppe in `ad_allowed_users` bzw. in
  `ad_allowed_group` stehen. Sonst weist die Vorab-Freigabe es ab, bevor das Kennwort zum DC
  geht, und die Meldung sieht aus wie ein falsches Kennwort.
- **Kein Domänen-Admin-Konto (Tier 0) verwenden:** Jarvis prüft per LDAP-Simple-Bind, das
  Kennwort läuft also durch den Jarvis-Dienst.
- AD-Anmeldenamen haben höchstens 20 Zeichen. Bei längeren Namen kürzt das AD, und die
  Anmeldung mit dem langen Namen scheitert am Who-am-I-Abgleich. Ein kurzes Präfix wählen.
- `admin_2fa_pflicht` eingeschaltet lassen (auf DEV am 2026-11-13 **aus**).
- Für Admin-Arbeit über die Anmeldemaske anmelden. Die Windows-Anmeldung meldet das normale
  Konto an.
- Der lokale `jarvis` bleibt als Notfallzugang.

## Offener Härtungspunkt (unabhängig von der Entscheidung)

Die Lücke „roher statt normierter Name“ betrifft schon heute das Konto `jarvis`: Die Eingabe
`DOMÄNE\jarvis` geht an das AD. Ausnutzbar ist das nur, wenn im AD ein Konto `jarvis` entsteht
und für Jarvis freigegeben wird. Laut Messung gibt es keines. Auf DEV steht `jarvis` aber in
`ad_admins`, ein solches Konto bekäme also Admin-Rechte.

Abhilfe:
- Lokale Namen normiert erkennen und den AD-Weg für sie sperren.
- `jarvis` aus `ad_admins` entfernen. Der Eintrag ist für das lokale Konto ohnehin wirkungslos.
