# Anmeldung über den IdP (OpenID Connect) – Umsetzungsplan

Stand: 2026-11-18 · Status: **Phasen 0–4 umgesetzt. Auf DEV mit echtem IdP-Client
angemeldet (2026-11-18). ECHT: IdP-Anmeldung aus, eigener IdP-Client steht aus.**

### Nachtrag 2026-11-18 (Erfahrungen DEV, Festlegungen des Betreibers)

- IdP schrieb den Rechnernamen im id_token gross, im Discovery-Dokument klein → Vergleich des
  Ausstellers ohne Gross-/Kleinschreibung NUR fuer den Rechnernamen (`issuer_gleich`).
- `sub` ist beim IdP eine interne Nummer; der Anmeldename steht in `preferred_username`.
  Die Anmeldung protokolliert seitdem die NAMEN der Claims (keine Werte).
- **E1 neu entschieden:** Die IdP-Anmeldung zaehlt in der Vorgabe als zweiter Faktor, auch
  fuer Administratoren. Abschalten nur ausdruecklich.
- **E2 entschieden:** Schalter „AD-Anmeldung zusaetzlich“ (`oidc_ad_modus`), sichtbar nur bei
  eingeschaltetem IdP. Vorgabe seit 2026-11-19 **an** (`zusaetzlich`): die Kennwortmaske steht
  immer neben dem Knopf (bis dahin war die Vorgabe `fallback`). Aus (`fallback`): sie erscheint
  erst, wenn die IdP-Anmeldung scheitert (Fehlerkennung, Einloesen abgelehnt, IdP/Status nicht
  erreichbar). Ein gespeicherter Wert bleibt bestehen. Nur Anzeige – `/api/login` bleibt
  erreichbar; fail-open bei jedem Zweifel. Notfallkonto `jarvis`: beim IdP „Deny“ waehlen
  → Ausweichweg.

### Umsetzung und Abweichungen vom Plan (2026-11-17)

- Code: `backend/oidc_anmeldung.py`, Block „Anmeldung über den IdP“ in `backend/main.py`,
  `frontend/js/idp_anmeldung.js`, `frontend/js/settings_idp.js`.
  Wächter: `tests/test_oidc_anmeldung.py` (135) + `tests/gegen_oidc_anmeldung.py` (20/20 beißen),
  `tests/test_idp_anmeldung_ui.js` (22, drei Sabotagen beißen).
- **Die TOTP-Prüfung wurde NICHT aus `_login_ablauf` herausgezogen.** An ihr hängen Textanker
  der BSI-M3-Gegenproben, und der Umbau wäre der riskanteste Eingriff gewesen. Der IdP-Weg ruft
  dieselben Bausteine (`_totp_broker_pruefen`, `_totp_schutz.pruefen`, `_totp_fehlertext`).
  Alle bestehenden Anmeldefunktionen sind im Syntaxbaum identisch zu HEAD.
- **Admin ohne eingerichtete 2FA bei Pflicht:** keine Einrichtung über den IdP-Weg, sondern eine
  Sitzung OHNE Admin-Rechte mit Hinweis (wie beim Outlook-SSO). Eingerichtet wird über die
  Kennwortanmeldung.
- **E1 liegt im Bereich „Pflicht für Administratoren“** (Einstellungen → Sicherheit), Schalter
  plus Feld „Nachweis im Token“. Die Verbindungsdaten liegen im Bereich Berechtigungen →
  „Anmeldung über den IdP“.


## Ausgangslage

- Der **IdP** holt die Benutzer per LDAPS aus dem AD
  und legt keine eigenen Konten an. Freigegeben sind SAML und OIDC, gewählt ist **OIDC**.
- Jarvis meldet heute an über: Kennwortmaske (LDAP-Simple-Bind, das Kennwort läuft durch
  den Dienst), Windows-Anmeldung (Kerberos, `kerberos_anmeldung.py`) und Outlook-Add-in
  (Exchange-Token, `addin_sso.py`).
- **Es gibt keinen Gruppen-Claim.** Die Freigabe prüft Jarvis weiter über das AD mit dem
  Dienstkonto, also genau so wie bei der Windows-Anmeldung (`_ad_windows_freigabe`).
  Vorteile: keine Pflege im IdP je Gruppe, aktueller Stand statt Stand der Anmeldung, eine
  Rechtelogik für alle Anmeldewege.
- Jira- und Confluence-PATs bleiben unverändert. Sie hängen an der Jarvis-Identität, deshalb
  muss der Name aus dem IdP **exakt** dieselbe Identität ergeben wie die Kennwortanmeldung.

## Bestandsschutz: die heutige Anmeldung bleibt

OIDC kommt **zusätzlich** dazu, es ersetzt nichts. Der Schalter „OIDC aktiv“ steht in der
Vorgabe auf **aus**. Solange er aus ist, sieht und verhält sich Jarvis wie heute: kein
neuer Knopf, und die neuen Endpunkte antworten „nicht eingerichtet“.

| Anmeldeweg | nach dem Umbau |
|---|---|
| Kennwortmaske (AD per LDAP) | unverändert |
| Notfallzugang `jarvis` | unverändert, nur per Kennwort, nie über den IdP |
| Windows-Anmeldung (Kerberos, AI-Maus) | unverändert |
| Outlook-Add-in (Exchange-Token) | unverändert |
| Apps, Programmschlüssel (Bearer) | unverändert |
| **neu:** „Mit Firmenkonto anmelden“ | nur wenn OIDC aktiv |

Der **einzige Eingriff in bestehenden Code** ist das Herausziehen der TOTP- und
Admin-2FA-Prüfung aus `_login_ablauf` in eine gemeinsame Hilfsfunktion (Phase 2). Dafür
entsteht **vorher** ein Wächter (`test_login_totp_gemeinsam.py`), der das heutige Verhalten
der Kennwortanmeldung festhält und grün sein muss. Nach dem Umbau muss er unverändert grün
sein. Fällt die IdP-Anmeldung aus (IdP nicht erreichbar, Fehlkonfiguration), betrifft das
nur den neuen Knopf.

## Grundsatz

Das neue Modul sagt nur: „Dieses Token gehört zu Konto X.“ Freigabe, Kontosperre, Lizenz,
2FA, Admin-Rechte und Sitzung entscheidet `main.py` mit den vorhandenen Prüfungen. Es gibt
keine zweite, halb nachgebaute Rechtelogik (dieselbe Trennung wie bei Kerberos und Add-in).

## Ablauf (Authorization Code + PKCE)

```
Browser                  Jarvis                               IdP
  │ Klick "Mit Firmen-     │                                    │
  │ konto anmelden"        │                                    │
  ├─GET /api/login/oidc/start─>│ state, nonce, PKCE anlegen     │
  │<─302 + Cookie (Lax)────────┤                                │
  ├────────────────────────────┼──────── Anmeldung + MFA ──────>│
  │<───────────────────────────┼──────── 302 ?code&state ───────┤
  ├─GET /api/login/oidc/callback>│ state prüfen, code tauschen ─>│
  │                            │<───────── id_token ────────────┤
  │                            │ Token prüfen → Konto → Freigabe│
  │<─303 /chat.html + Einlöse-Cookie (Lax, 2 min, einmalig)     │
  ├─POST /api/login/oidc/einloesen (fetch, X-Jarvis-Sitzung)──> │
  │<─Sitzungs-Cookie + CSRF-Token (oder requires_totp)          │
```

**Warum der Umweg über „Einlösen“:** Das Sitzungs-Cookie ist `SameSite=Strict`
(`sitzung_cookie.py`). Eine Weiterleitungskette, die beim IdP beginnt, gilt dem Browser als
seitenfremd. Und das Frontend erwartet das CSRF-Token aus der JSON-Antwort der Anmeldung.
Der Callback stellt deshalb **keine** Sitzung aus, sondern nur einen kurzlebigen, einmaligen
Einlöse-Schein. Die eigentliche Sitzung entsteht in einem gewöhnlichen `fetch` von der
eigenen Seite. Das läuft über denselben Weg (`_sitzung_antwort`) wie heute, und
TOTP-Abfrage, Admin-2FA-Pflicht und Fehlertexte lassen sich wiederverwenden. Der Schein
steht **nie in der URL** (Protokolle, Referer), sondern in einem HttpOnly-Cookie.

**Der Login-Knopf ist ein Link, kein Formular.** Die CSP setzt `form-action 'self'`, und
Chrome wendet das auch auf die Weiterleitung nach einem Formularversand an. Ein Formular
zum IdP würde still blockiert.

## Phase 0 – Einrichten und messen (IdP-Admin + DEV, kein Code)

1. Im IdP Jarvis-DEV als vertraulichen OIDC-Client anlegen:
   - Redirect-URI `https://<dev-host>/api/login/oidc/callback`
   - Scopes `openid profile`, kein Gruppen-Claim
   - Client-ID und Client-Secret (gehören nach Jarvis, **nicht** ins Repo)
2. Messen und hier eintragen, bevor Code entsteht:

| Frage | Warum |
|---|---|
| Discovery-URL (`/.well-known/openid-configuration`) erreichbar vom Dienst aus? | Ausgangsweg, Firewall |
| Zertifikatskette des IdP: interne CA? Vertraut der Server ihr schon? | TLS-Prüfung, kein `verify=False` |
| Signaturalgorithmus des `id_token` (RS256/ES256?) | feste Positivliste |
| Unterstützt der IdP PKCE (S256)? | sonst nur mit Client-Secret |
| **In welchem Claim und welchem Format steht der Anmeldename?** (`preferred_username`, `sub`, `upn`; `name`, `name@domäne`, `DOMÄNE\name`?) | Identität, siehe Risiko 1 |
| Liefert der IdP `amr`/`acr`, und steht darin, ob ein zweiter Faktor geprüft wurde? | Entscheidung E1 |
| `end_session_endpoint` vorhanden? | Entscheidung E3 |

Gemessen wird mit einem echten Test-Benutzer im Browser und einem Hilfsskript, das das
`id_token` nur **dekodiert anzeigt**. Ins Repo kommt weder das Token noch ein Echtwert.

## Phase 1 – Backend-Modul `backend/oidc_anmeldung.py`

Reine Prüflogik ohne Sitzung, ohne Rechte, ohne Import von `backend.config` (testbar mit
Stub):

- **Discovery** laden und zwischenspeichern (TTL). Nur `https`. Der `issuer` im Dokument
  muss **exakt** dem konfigurierten entsprechen.
- **JWKS** zwischenspeichern. Bei unbekanntem `kid` einmal neu laden, mit Mindestabstand,
  damit kein Angreifer das Neuladen in Dauerschleife auslösen kann.
- **Code-Tausch** mit `client_secret_basic` und PKCE-Verifier, fester Timeout, **keine**
  Weiterleitungen folgen, TLS über `tls_richtlinie`.
- **`id_token` prüfen:**
  - `alg` aus fester Liste (RS256, ggf. ES256). `none` und `HS*` werden immer abgewiesen.
  - Signatur gegen den JWKS-Schlüssel mit passendem `kid`
  - `iss` gleich dem konfigurierten Issuer
  - `aud` enthält die Client-ID. Bei mehreren Audiences muss `azp` gleich der Client-ID sein.
  - `exp`/`nbf`/`iat` mit 60 s Toleranz
  - `nonce` gleich der hinterlegten
- **Konto ableiten:** Namensclaim laut Einstellung, Domänenanteil prüfen (wie
  `konto_aus_principal`), dann `_norm_login`. Ein Name, der nach der Normierung ein lokales
  Konto ist (`ALLOWED_USERS`, also `jarvis`), wird **abgewiesen**.
- Kryptografie über `cryptography` (vorhanden). Ein neues Paket nur, wenn die Messung in
  Phase 0 es erzwingt.

## Phase 2 – Endpunkte in `main.py`

**`GET /api/login/oidc/start`**
- OIDC eingerichtet? Sonst 503 mit „nicht eingerichtet“. Dann `_check_rate_limit`.
- `state`, `nonce` und PKCE-Verifier erzeugen und serverseitig unter `state` ablegen:
  10 Minuten gültig, einmalig, mit Obergrenze der Einträge.
- An den Browser binden: Cookie `__Host-jarvis_oidc` (HttpOnly, Secure, SameSite=**Lax**,
  Path=/) mit einem Hash, der zum Eintrag passen muss. Damit kann niemand einen fremden
  Callback in den Browser des Opfers schieben (Login-CSRF).
- 302 zum `authorization_endpoint`.

**`GET /api/login/oidc/callback`**
- Fehlerparameter des IdP (`error=`) verständlich anzeigen, ohne Rohdaten.
- `state` gegen Cookie und Ablage prüfen und **sofort verbrauchen**.
- Code tauschen, Token prüfen (Phase 1) und Konto ableiten.
- Danach dieselbe Kette wie bei `_login_windows_ablauf`: kein lokales Konto →
  `_konto_sperre_antwort` → `_ad_windows_freigabe` über das Dienstkonto. „fehler“ ergibt
  503 „nicht prüfbar“, nie „nein“. Dann die Lizenzgrenze.
- **Ein ungültiges Token zählt nicht als Fehlversuch des Kontos** (wie bei Kerberos). Es ist
  ein Einrichtungs-, kein Rateindiz. Die IP-Begrenzung gilt trotzdem.
- Erfolg: Einlöse-Schein erzeugen (Zufallswert, 2 Minuten, einmalig, höchstens 3
  TOTP-Versuche), Cookie `__Host-jarvis_oidc_schein` (Lax), dann 303 auf die Startseite.
- Jeder Ausgang wird über `_anmeldung_protokollieren(…, "oidc")` protokolliert.

**`POST /api/login/oidc/einloesen`**
- Schein aus dem Cookie lesen und löschen. Bei abgewiesenem TOTP bleibt er bis zur
  Versuchsgrenze erhalten.
- **2FA:** Den TOTP- und `admin_2fa_pflicht`-Teil aus `_login_ablauf` in eine gemeinsame
  Hilfsfunktion ziehen und von beiden Wegen aufrufen. Das ist der riskanteste Eingriff am
  bestehenden Code: Er braucht einen Wächter vorher, der grün ist, und eine Gegenprobe
  danach. Verhalten nach E1.
- `generate_token`, `_anmelde_schutz.erfolg`, `record_login`, `_sitzung_antwort`.

**Prüfen, nicht annehmen:** Greift der vorhandene Sitzungswiderruf bei Gruppenentzug und bei
einem im AD deaktivierten Konto auch für Sitzungen, die nicht per Kennwort entstanden sind?
Er stützt sich auf einen Anmelde-Zwischenspeicher. Messen, wie bei Kerberos-Sitzungen.

## Phase 3 – Einstellungen und Oberfläche

- **Admin-Einstellungen** im Bereich der AD-Anmeldung:
  - OIDC aktiv, Issuer-URL, Client-ID
  - Client-Secret: nur schreibbar, nie zurückgegeben, auch nicht maskiert
  - Namensclaim (Auswahl aus fester Liste)
  - **„MFA des IdP als zweiten Faktor anerkennen“** (E1, Vorgabe aus) mit Feld
    „Nachweis im Token“ (siehe E1)
  - Knopf „Verbindung testen“ (Discovery und JWKS erreichbar, Algorithmus passt)
- **Client-Secret** in `settings.json` über `geheimnis_tresor` als `JGS1:` speichern.
  Prüfen, dass der gewählte Feldname als geheim erkannt wird, mit eigenem Wächter.
- **Anmeldeseite:** Knopf „Mit Firmenkonto anmelden“, nur sichtbar, wenn ein öffentlicher
  Status-Endpunkt „aktiv“ meldet. `data-i18n` mit DE/EN, `{marke}` statt Produktname. Nach
  der Rückkehr (Schein-Cookie vorhanden) ruft das Frontend `einloesen` auf und zeigt bei
  `requires_totp` die vorhandene Code-Abfrage.
- Die Kennwortmaske bleibt. Der lokale Notfallzugang `jarvis` bleibt immer per Kennwort.
- Cache-Buster in **allen** HTML-Dateien hochzählen.

## Phase 4 – Tests (je Wächter eine Gegenprobe, die beißt)

| Datei | Prüft |
|---|---|
| `test_oidc_token.py` / `gegen_oidc_token.py` | fremder `iss`, falsches `aud`, fehlendes `azp` bei Mehrfach-`aud`, abgelaufen, `nbf` in der Zukunft, `alg: none`, `HS256` mit dem öffentlichen Schlüssel als Geheimnis, unbekanntes `kid`, falsche `nonce`, manipulierte Nutzlast. Positivkontrolle mit selbst erzeugtem Schlüsselpaar zuerst, sonst Exit 2. |
| `test_oidc_konto.py` | Namensformate aus Phase 0, fremde Domäne, `jarvis`/`JARVIS`/`DOMÄNE\jarvis` werden abgewiesen, gleiche Identität wie bei der Kennwortanmeldung |
| `test_oidc_ablauf.py` | `state` einmalig, ohne Cookie wertlos, Schein einmalig und befristet, TOTP-Pflicht greift, Freigabe „fehler“ ergibt nie eine Sitzung, Lizenzgrenze |
| `test_oidc_geheimnis.py` | Client-Secret wird verschlüsselt geschrieben und von keinem Endpunkt herausgegeben |
| `test_login_totp_gemeinsam.py` | Verhalten der Kennwortanmeldung vor und nach dem Herausziehen der 2FA-Hilfsfunktion identisch |
| `live_oidc_dev.py` | Probe gegen DEV mit Test-Benutzer: Discovery, Weiterleitung, Callback-Fehlerpfade |

Den Browserablauf (SameSite, Weiterleitungskette, CSP) sieht kein jsdom. Er wird **in einem
echten Browser** gemessen: Chrome, Edge, Firefox.

## Phase 5 – Ausrollen

1. DEV per `scp`, Dienst neu starten, Live-Probe, Test-Benutzer mit und ohne TOTP, Admin.
2. ECHT **nur auf benannte Anweisung**. Im IdP ist dafür ein **zweiter** Client mit der
   ECHT-Redirect-URI nötig, nicht derselbe wie DEV.

## Risiken

1. **Identitätsspaltung:** Liefert der IdP den Namen in anderem Format, entsteht eine leere
   neue Identität ohne Chatverlauf, Gedächtnis, 2FA-Eintrag und PATs. Gegenmittel: die
   Messung in Phase 0, ein Wächter auf gleiche Normierung, und ein Konto, das im AD nicht
   auffindbar ist, wird abgewiesen statt neu angelegt. Achtung: `_ad_windows_freigabe`
   antwortet bei einem Treffer in `ad_allowed_users` mit „ja“, **ohne** das AD zu fragen.
2. **Übernahme lokaler Konten:** Ein IdP-Name, der zu `jarvis` normiert wird, darf nie
   durchgehen (siehe `docs/entscheidung-lokale-konten.md`).
3. **Login-CSRF und Code-Einschleusen:** abgedeckt durch `state` am Browser-Cookie, PKCE
   und `nonce`.
4. **IdP nicht erreichbar:** Es fällt nur dieser Weg aus. Kennwortmaske und Notfallzugang
   bleiben.
5. **Doppelte MFA oder 2FA-Umgehung:** wird durch E1 entschieden, nicht stillschweigend.

## Offene Entscheidungen (Vorgabe in Klammern)

- **E1 – Zählt die MFA des IdP als zweiter Faktor?** **Entschieden 2026-11-17:
  einstellbar**, Schalter „MFA des IdP als zweiten Faktor anerkennen“, Vorgabe **aus**.
  **Geaendert 2026-11-18: Vorgabe AN** (siehe Nachtrag oben).
  - **Aus:** Jarvis fragt nach der IdP-Anmeldung seinen eigenen TOTP wie bei der
    Kennwortanmeldung (Konten mit TOTP, Admin-2FA-Pflicht). Admin-Rechte gibt es nur damit.
  - **An:** Die IdP-Anmeldung gilt als bestandener zweiter Faktor (`mit_2fa=True`), kein
    Jarvis-TOTP. Admin-Rechte sind ohne weiteren Code möglich.
  - **Nachweis im Token:** Ein Feld nennt Claim und Wert, z. B. `amr` enthält `otp` oder
    `acr` gleich einem Wert aus Phase 0. Ist es gefüllt, wird die MFA **nur** anerkannt,
    wenn das Token den Wert trägt. Fehlt er, gilt die Anmeldung wie bei „aus“. Das ist
    keine Abweisung, Jarvis fragt dann seinen TOTP.
  - Bleibt das Feld leer, vertraut Jarvis der Zusage des Admins, dass der IdP für diesen
    Client MFA erzwingt. Die Oberfläche sagt das neben dem Schalter ausdrücklich, und das
    Umschalten wird im Sicherheitsprotokoll vermerkt.
  - Wächter: Bei „aus“ nie `mit_2fa`; bei „an“ mit Nachweisfeld ergibt ein Token ohne den
    Wert nie `mit_2fa`. Die Gegenprobe beißt, wenn die Bedingung entfernt wird.
- **E2 – Kennwortmaske später ausblenden?** **Entschieden 2026-11-18:** Ausweichweg als
  Vorgabe, Schalter „AD-Anmeldung zusaetzlich“ (siehe Nachtrag oben).
- **E3 – Abmelden auch beim IdP** (RP-initiated Logout)? (Vorgabe: nein, nur Jarvis-Sitzung
  beenden.)
- **E4 – Gilt die Jarvis-Sitzung unabhängig von der IdP-Sitzung?** (Vorgabe: ja, die
  vorhandene Laufzeit und der Leerlauf-Ablauf gelten. Offboarding wirkt über den
  AD-Widerruf, siehe Prüfpunkt in Phase 2.)

## Ausdrücklich nicht Teil dieses Plans

- AI-Maus (Kerberos), Outlook-Add-in, Apps und Programmschlüssel: bleiben, wie sie sind.
- Gruppen-Claim: wird nicht verwendet.
- Jira-/Confluence-PATs bzw. OAuth 2.0 zu Atlassian: unverändert, eigenes Thema.
