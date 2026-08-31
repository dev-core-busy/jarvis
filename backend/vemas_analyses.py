"""Katalog der vorgefertigten Abfragen fuer den VEMAS-Bereich (``/vemas``).

Warum ein eigenes Modul und keine i18n-Keys im Frontend: das hier sind
**Daten**, keine Oberflaechen-Beschriftungen. Jeder Eintrag traegt neben Titel
und Beschreibung auch die uebliche Datenquelle und einen fertigen
Arbeitsauftrag fuer den Agenten – Titel und Auftrag muessen zusammenpassen.
Lagen sie in ``i18n.js`` und hier, wuerden sie auseinanderlaufen (genau das
Muster, das im Projekt schon mehrfach Stunden gekostet hat). Deshalb: EINE
Quelle, beide Sprachen darin.

**Zuschnitt: VEMAS.NET als CRM/ERP fuer Dienstleistungs- und Projektgeschaeft.**
Die Gliederung folgt den Modulen, die der Hersteller nennt (GF-Cockpit,
Kundenakte/CRM, Projektverwaltung, Zeit-/Leistungserfassung, Hotline/Service,
Abrechnung von Projekten, Vertraegen und Seminaren, Lastplan). Ausgewertet wird,
was ein Geschaeftsfuehrer oder Projektleiter tatsaechlich braucht:
Auslastung, unfakturierte Leistung, Vertragsmargen, Reaktionszeiten,
Forderungen.

⚠ **DIE RESSOURCENNAMEN SIND HINWEISE, KEINE ZUSICHERUNG.** Die REST-API von
Vemas.NextGen ist nicht oeffentlich dokumentiert (siehe ``vemas_client``), und
welche Ressource in einer konkreten Installation wie heisst, haengt von den
lizenzierten Modulen und vom Customizing ab. Der gemeinsame Vorspann weist den
Agenten deshalb an, **zuerst** die tatsaechlich vorhandenen Ressourcen zu
ermitteln (``vemas_resources`` = die vom Administrator gepflegte Zuordnung,
``vemas_discover`` = die Selbstauskunft des Servers) und erst danach zu lesen.
Ohne diesen Schritt raet das Modell Pfade, jeder Fehlgriff kostet einen Schritt
– und bei aktivem Aussetzer einen Fehlversuch.

**Die Auftraege sind reine LESE-Auswertungen.** Nur-Lesen ist die Vorgabe des
Clients; selbst wenn ein Administrator Schreibzugriffe freischaltet, darf kein
Eintrag hier einen schreibenden Vorgang beschreiben – ein Katalogeintrag laeuft
auf Knopfdruck und ohne Rueckfrage.
"""

from __future__ import annotations

# ── Kategorien (Reihenfolge = Reihenfolge der Gruppen im Pulldown) ──────────
CATEGORIES: list[dict] = [
    {"id": "cockpit",    "de": "Geschaeftsfuehrung & Kennzahlen",
                         "en": "Management & key figures"},
    {"id": "crm",        "de": "Kunden & Vertrieb",
                         "en": "Customers & sales"},
    {"id": "projekte",   "de": "Projekte & Auftraege",
                         "en": "Projects & orders"},
    {"id": "zeit",       "de": "Zeit- & Leistungserfassung",
                         "en": "Time & service recording"},
    {"id": "service",    "de": "Hotline & Service",
                         "en": "Helpdesk & service"},
    {"id": "abrechnung", "de": "Abrechnung, Vertraege & Seminare",
                         "en": "Billing, contracts & seminars"},
    {"id": "ressourcen", "de": "Auslastung & Lastplan",
                         "en": "Utilisation & capacity"},
]

# Gemeinsamer Vorspann jedes Auftrags. Steht EINMAL hier statt in jedem der
# Eintraege – sonst driftet die Vorgehensweise zwischen den Abfragen.
#
# Schritt (1) ist der wichtigste und der Grund, warum dieser Vorspann laenger
# ist als der von SAP: dort sind die Tabellennamen ueber alle Systeme hinweg
# gleich, hier ist NICHTS garantiert.
_PREAMBLE_DE = (
    "Du wertest ein VEMAS.NET-System LESEND ueber dessen REST-Schnittstelle "
    "aus. Gehe in dieser Reihenfolge vor: "
    "(1) Ermittle ZUERST mit 'vemas_resources', welche Ressourcen der "
    "Administrator hinterlegt hat. Reicht das nicht, versuche 'vemas_discover' – "
    "das liest die Selbstauskunft des Servers. RATE KEINE PFADE: jeder "
    "Fehlgriff kostet einen Schritt und liefert nur einen 404. "
    "(2) Hole die Daten mit 'vemas_query' in einer sinnvoll begrenzten Menge "
    "und schraenke ueber Parameter ein, statt alles zu laden. "
    "(3) Antworte mit einer verdichteten Auswertung: Kennzahlen als Tabelle, "
    "danach drei bis fuenf Saetze Einordnung. Nenne Auffaelligkeiten und – "
    "falls Daten fehlen – ausdruecklich, was nicht ermittelbar war und warum. "
    "Erfinde keine Zahlen und rechne keine Kennzahl aus Feldern, deren "
    "Bedeutung du nicht belegen kannst."
)
_PREAMBLE_EN = (
    "You are analysing a VEMAS.NET system READ-ONLY via its REST interface. "
    "Proceed in this order: "
    "(1) FIRST use 'vemas_resources' to find out which resources the "
    "administrator has configured. If that is not enough, try 'vemas_discover', "
    "which reads the server's own API description. DO NOT GUESS PATHS: every "
    "wrong guess costs a step and returns only a 404. "
    "(2) Fetch the data with 'vemas_query' in a sensibly limited volume and "
    "restrict via parameters instead of loading everything. "
    "(3) Answer with a condensed analysis: key figures as a table, then three "
    "to five sentences of interpretation. Name anomalies and – if data is "
    "missing – state explicitly what could not be determined and why. Never "
    "invent figures and never derive a key figure from fields whose meaning you "
    "cannot substantiate."
)

# ── Der Katalog ────────────────────────────────────────────────────────────
# Pflichtfelder je Eintrag: id, cat, sources, de{title,desc,kpis,task},
# en{title,desc,kpis,task}.
ANALYSES: list[dict] = [
    # ═══ Geschaeftsfuehrung & Kennzahlen ═════════════════════════════════
    {
        "id": "gf_cockpit", "cat": "cockpit",
        "sources": "Projekte, Zeiten, Rechnungen, Auftraege",
        "de": {
            "title": "GF-Cockpit: Lage auf einer Seite",
            "desc": "Die Zahlen, die im Geschaeftsfuehrer-Cockpit stehen, in "
                    "einer verdichteten Uebersicht: Umsatz, offene Auftraege, "
                    "erfasste und fakturierte Leistung, Auslastung.",
            "kpis": ["Umsatz laufender Monat", "Auftragsbestand",
                     "erfasste Stunden", "fakturierte Stunden",
                     "Fakturierungsquote", "Auslastung"],
            "task": "Stelle die Lage des laufenden Monats zusammen: Umsatz, "
                    "Auftragsbestand, erfasste und fakturierte Stunden sowie die "
                    "sich daraus ergebende Fakturierungsquote. Vergleiche mit "
                    "dem Vormonat und benenne die groesste Abweichung.",
        },
        "en": {
            "title": "Management cockpit: the situation on one page",
            "desc": "The figures from the management cockpit in one condensed "
                    "overview: revenue, open orders, recorded and billed "
                    "services, utilisation.",
            "kpis": ["Revenue current month", "Order backlog", "Recorded hours",
                     "Billed hours", "Billing ratio", "Utilisation"],
            "task": "Compile the situation for the current month: revenue, "
                    "order backlog, recorded and billed hours and the resulting "
                    "billing ratio. Compare with the previous month and name the "
                    "largest deviation.",
        },
    },
    {
        "id": "umsatz_entwicklung", "cat": "cockpit",
        "sources": "Rechnungen, Rechnungspositionen, Kunden",
        "de": {
            "title": "Umsatzentwicklung nach Monat und Kunde",
            "desc": "Umsatz der letzten zwoelf Monate, aufgeschluesselt nach "
                    "Monat und den groessten Kunden – die Grundlage jedes "
                    "Vertriebsgespraechs.",
            "kpis": ["Umsatz je Monat", "Top-10-Kunden", "Anteil Top-3",
                     "Veraenderung zum Vorjahresmonat"],
            "task": "Ermittle den Rechnungsumsatz der letzten zwoelf Monate je "
                    "Monat und zusaetzlich je Kunde (Top 10). Weise den Anteil "
                    "der drei groessten Kunden am Gesamtumsatz aus und "
                    "vergleiche jeden Monat mit dem Vorjahresmonat.",
        },
        "en": {
            "title": "Revenue development by month and customer",
            "desc": "Revenue of the last twelve months, broken down by month "
                    "and by largest customers – the basis of every sales review.",
            "kpis": ["Revenue per month", "Top 10 customers", "Share of top 3",
                     "Change vs. same month last year"],
            "task": "Determine invoiced revenue for the last twelve months per "
                    "month and additionally per customer (top 10). Show the "
                    "share of the three largest customers in total revenue and "
                    "compare each month with the same month last year.",
        },
    },
    {
        "id": "klumpenrisiko", "cat": "cockpit",
        "sources": "Rechnungen, Kunden, Vertraege",
        "de": {
            "title": "Abhaengigkeit von einzelnen Kunden (Klumpenrisiko)",
            "desc": "Wie stark haengt der Umsatz an wenigen Kunden? Ein hoher "
                    "Anteil weniger Auftraggeber ist das haeufigste Risiko im "
                    "Projektgeschaeft.",
            "kpis": ["Umsatzanteil je Kunde", "Anteil Top-1", "Anteil Top-5",
                     "Anzahl Kunden mit Anteil ueber 10 %"],
            "task": "Berechne den Umsatzanteil je Kunde fuer die letzten zwoelf "
                    "Monate, absteigend sortiert. Weise die Anteile von Top-1 "
                    "und Top-5 aus und liste alle Kunden mit einem Anteil ueber "
                    "zehn Prozent. Ordne das Ergebnis in ein bis zwei Saetzen "
                    "als Risiko ein.",
        },
        "en": {
            "title": "Dependency on individual customers (concentration risk)",
            "desc": "How much does revenue depend on a few customers? A high "
                    "share held by few clients is the most common risk in "
                    "project business.",
            "kpis": ["Revenue share per customer", "Top 1 share", "Top 5 share",
                     "Customers above 10 % share"],
            "task": "Calculate the revenue share per customer for the last "
                    "twelve months, sorted descending. Show the top 1 and top 5 "
                    "shares and list all customers above ten percent. Assess the "
                    "result as a risk in one or two sentences.",
        },
    },

    # ═══ Kunden & Vertrieb ═══════════════════════════════════════════════
    {
        "id": "kundenakte", "cat": "crm",
        "sources": "Kunden, Ansprechpartner, Aktivitaeten, Projekte",
        "de": {
            "title": "Kundenakte: Gesamtbild zu einem Kunden",
            "desc": "Alles zu einem Kunden an einer Stelle: Stammdaten, "
                    "Ansprechpartner, laufende Projekte, Umsatz, offene "
                    "Vorgaenge. Kunde ueber die Zusatzfrage benennen.",
            "kpis": ["Umsatz gesamt", "laufende Projekte", "offene Tickets",
                     "letzte Aktivitaet", "offene Forderungen"],
            "task": "Stelle die Kundenakte des in der Zusatzfrage genannten "
                    "Kunden zusammen: Stammdaten, Ansprechpartner, laufende "
                    "Projekte mit Status, Umsatz der letzten zwoelf Monate, "
                    "offene Vorgaenge und das Datum der letzten Aktivitaet. "
                    "Ist kein Kunde genannt, sage das und nenne die Kunden mit "
                    "dem hoechsten Umsatz zur Auswahl.",
        },
        "en": {
            "title": "Customer file: full picture of one customer",
            "desc": "Everything about one customer in one place: master data, "
                    "contacts, running projects, revenue, open items. Name the "
                    "customer in the additional question.",
            "kpis": ["Total revenue", "Running projects", "Open tickets",
                     "Last activity", "Open receivables"],
            "task": "Compile the customer file for the customer named in the "
                    "additional question: master data, contacts, running "
                    "projects with status, revenue of the last twelve months, "
                    "open items and the date of the last activity. If no "
                    "customer is named, say so and list the customers with the "
                    "highest revenue to choose from.",
        },
    },
    {
        "id": "vertriebs_pipeline", "cat": "crm",
        "sources": "Angebote, Verkaufschancen, Kunden",
        "de": {
            "title": "Angebots- und Verkaufschancen-Pipeline",
            "desc": "Offene Angebote und Verkaufschancen nach Phase und "
                    "erwartetem Abschluss – was in den naechsten Wochen "
                    "entschieden wird.",
            "kpis": ["Anzahl offener Angebote", "Volumen gesamt",
                     "Volumen je Phase", "Abschlussquote", "Alter der Angebote"],
            "task": "Liste die offenen Angebote und Verkaufschancen mit Kunde, "
                    "Volumen, Phase und erwartetem Abschlussdatum. Gruppiere "
                    "nach Phase, weise das Volumen je Phase aus und hebe alle "
                    "Vorgaenge hervor, die aelter als 60 Tage sind.",
        },
        "en": {
            "title": "Quotation and opportunity pipeline",
            "desc": "Open quotations and opportunities by stage and expected "
                    "close – what will be decided over the coming weeks.",
            "kpis": ["Open quotations", "Total volume", "Volume per stage",
                     "Win rate", "Age of quotations"],
            "task": "List open quotations and opportunities with customer, "
                    "volume, stage and expected close date. Group by stage, show "
                    "the volume per stage and highlight everything older than 60 "
                    "days.",
        },
    },
    {
        "id": "kunden_inaktiv", "cat": "crm",
        "sources": "Kunden, Aktivitaeten, Rechnungen",
        "de": {
            "title": "Schlafende Kunden (keine Aktivitaet)",
            "desc": "Kunden mit Umsatzhistorie, aber ohne Aktivitaet in den "
                    "letzten Monaten – die guenstigste Vertriebsliste, die es "
                    "gibt.",
            "kpis": ["Anzahl inaktiver Kunden", "entgangener Umsatz",
                     "Tage seit letzter Aktivitaet"],
            "task": "Finde Kunden mit Umsatz in den letzten 24 Monaten, aber "
                    "ohne Aktivitaet oder Auftrag in den letzten sechs Monaten. "
                    "Sortiere nach frueherem Umsatz absteigend und nenne je "
                    "Kunde das Datum der letzten Aktivitaet.",
        },
        "en": {
            "title": "Dormant customers (no activity)",
            "desc": "Customers with revenue history but no activity in recent "
                    "months – the cheapest sales list there is.",
            "kpis": ["Dormant customers", "Foregone revenue",
                     "Days since last activity"],
            "task": "Find customers with revenue in the last 24 months but no "
                    "activity or order in the last six months. Sort by former "
                    "revenue descending and give the date of the last activity "
                    "per customer.",
        },
    },

    # ═══ Projekte & Auftraege ════════════════════════════════════════════
    {
        "id": "projekt_status", "cat": "projekte",
        "sources": "Projekte, Projektphasen, Auftraege",
        "de": {
            "title": "Projektuebersicht mit Status und Termin",
            "desc": "Alle laufenden Projekte mit Kunde, Projektleiter, Budget, "
                    "Fortschritt und Endtermin – die Liste fuer die "
                    "woechentliche Projektrunde.",
            "kpis": ["laufende Projekte", "Budget gesamt", "Fortschritt",
                     "Projekte mit ueberschrittenem Endtermin"],
            "task": "Liste alle laufenden Projekte mit Kunde, Projektleiter, "
                    "Budget, bisher erfasstem Aufwand, Fortschritt und "
                    "geplantem Endtermin. Hebe Projekte hervor, deren Endtermin "
                    "ueberschritten ist oder in den naechsten 14 Tagen liegt.",
        },
        "en": {
            "title": "Project overview with status and deadline",
            "desc": "All running projects with customer, project manager, "
                    "budget, progress and end date – the list for the weekly "
                    "project review.",
            "kpis": ["Running projects", "Total budget", "Progress",
                     "Projects past their end date"],
            "task": "List all running projects with customer, project manager, "
                    "budget, effort recorded so far, progress and planned end "
                    "date. Highlight projects whose end date has passed or falls "
                    "within the next 14 days.",
        },
    },
    {
        "id": "budget_ampel", "cat": "projekte",
        "sources": "Projekte, Zeiten, Auftraege, Rechnungen",
        "de": {
            "title": "Budgetausschoepfung (Ampel)",
            "desc": "Welche Projekte laufen aus dem Budget? Vergleich von "
                    "geplantem und erfasstem Aufwand je Projekt.",
            "kpis": ["Budget", "erfasster Aufwand", "Ausschoepfung in %",
                     "Restbudget", "Projekte ueber 90 %"],
            "task": "Vergleiche je laufendem Projekt das geplante Budget mit "
                    "dem bisher erfassten Aufwand und weise die Ausschoepfung in "
                    "Prozent aus. Sortiere absteigend und markiere: unter 70 % "
                    "gruen, 70 bis 90 % gelb, ueber 90 % rot. Nenne die drei "
                    "kritischsten Projekte mit Restbudget.",
        },
        "en": {
            "title": "Budget consumption (traffic light)",
            "desc": "Which projects are running out of budget? Comparison of "
                    "planned and recorded effort per project.",
            "kpis": ["Budget", "Recorded effort", "Consumption in %",
                     "Remaining budget", "Projects above 90 %"],
            "task": "For each running project compare the planned budget with "
                    "the effort recorded so far and show consumption in percent. "
                    "Sort descending and mark: below 70 % green, 70 to 90 % "
                    "yellow, above 90 % red. Name the three most critical "
                    "projects with remaining budget.",
        },
    },
    {
        "id": "projekt_marge", "cat": "projekte",
        "sources": "Projekte, Zeiten, Rechnungen, Kostensaetze",
        "de": {
            "title": "Projektmarge (Ertrag gegen Aufwand)",
            "desc": "Was bleibt je Projekt uebrig? Fakturierter Ertrag gegen "
                    "bewerteten Aufwand – die Frage, die am Jahresende zaehlt.",
            "kpis": ["fakturierter Ertrag", "bewerteter Aufwand", "Deckungsbeitrag",
                     "Marge in %", "Projekte mit negativer Marge"],
            "task": "Ermittle je abgeschlossenem und laufendem Projekt den "
                    "fakturierten Ertrag und den bewerteten Aufwand, daraus "
                    "Deckungsbeitrag und Marge in Prozent. Liste zuerst alle "
                    "Projekte mit negativer Marge. Wenn keine Kostensaetze "
                    "verfuegbar sind, sage das ausdruecklich und rechne NICHT "
                    "mit angenommenen Saetzen.",
        },
        "en": {
            "title": "Project margin (revenue vs. effort)",
            "desc": "What is left per project? Billed revenue against valued "
                    "effort – the question that counts at year end.",
            "kpis": ["Billed revenue", "Valued effort", "Contribution margin",
                     "Margin in %", "Projects with negative margin"],
            "task": "For each completed and running project determine billed "
                    "revenue and valued effort, and from these the contribution "
                    "margin and margin in percent. List projects with a negative "
                    "margin first. If no cost rates are available, say so "
                    "explicitly and do NOT calculate with assumed rates.",
        },
    },

    # ═══ Zeit- & Leistungserfassung ══════════════════════════════════════
    {
        "id": "zeiten_erfassung", "cat": "zeit",
        "sources": "Zeiten, Mitarbeiter, Projekte",
        "de": {
            "title": "Erfasste Zeiten je Mitarbeiter und Projekt",
            "desc": "Wer hat wie viel auf welches Projekt gebucht? Grundlage "
                    "fuer Abrechnung und Auslastung.",
            "kpis": ["Stunden gesamt", "Stunden je Mitarbeiter",
                     "Stunden je Projekt", "abrechenbarer Anteil"],
            "task": "Fasse die erfassten Zeiten des letzten abgeschlossenen "
                    "Monats zusammen: Summe je Mitarbeiter, Summe je Projekt und "
                    "der abrechenbare Anteil in Prozent. Nenne die drei Projekte "
                    "mit dem hoechsten Aufwand.",
        },
        "en": {
            "title": "Recorded time per employee and project",
            "desc": "Who booked how much on which project? The basis for "
                    "billing and utilisation.",
            "kpis": ["Total hours", "Hours per employee", "Hours per project",
                     "Billable share"],
            "task": "Summarise the time recorded in the last closed month: total "
                    "per employee, total per project and the billable share in "
                    "percent. Name the three projects with the highest effort.",
        },
    },
    {
        "id": "zeiten_luecken", "cat": "zeit",
        "sources": "Zeiten, Mitarbeiter",
        "de": {
            "title": "Fehlende Zeiterfassung (Luecken)",
            "desc": "Wer hat Arbeitstage ohne Buchung? Fehlende Zeiten kosten "
                    "unmittelbar Umsatz, weil sie nie fakturiert werden.",
            "kpis": ["Mitarbeiter mit Luecken", "fehlende Tage",
                     "geschaetzter Ausfall in Stunden"],
            "task": "Pruefe fuer den letzten abgeschlossenen Monat je Mitarbeiter, "
                    "an welchen Arbeitstagen keine oder auffaellig wenige Zeiten "
                    "erfasst wurden. Liste Mitarbeiter mit den meisten Luecken "
                    "zuerst und nenne die betroffenen Tage. Wochenenden und "
                    "erkennbare Abwesenheiten nicht mitzaehlen.",
        },
        "en": {
            "title": "Missing time entries (gaps)",
            "desc": "Who has working days without entries? Missing time costs "
                    "revenue directly, because it is never billed.",
            "kpis": ["Employees with gaps", "Missing days",
                     "Estimated shortfall in hours"],
            "task": "For the last closed month, check per employee on which "
                    "working days no or conspicuously few hours were recorded. "
                    "List employees with the most gaps first and name the days "
                    "affected. Do not count weekends or recognisable absences.",
        },
    },
    {
        "id": "unfakturiert", "cat": "zeit",
        "sources": "Zeiten, Rechnungen, Projekte",
        "de": {
            "title": "Erbrachte, aber nicht fakturierte Leistung",
            "desc": "Geleistete und abrechenbare Stunden ohne Rechnung – "
                    "gebundenes Geld, das nur abgerufen werden muss.",
            "kpis": ["unfakturierte Stunden", "Wert in Euro", "Alter",
                     "betroffene Projekte"],
            "task": "Ermittle alle abrechenbaren, aber noch nicht fakturierten "
                    "Leistungen je Projekt und Kunde, mit Stunden, Wert und "
                    "Alter der aeltesten Position. Sortiere nach Wert absteigend "
                    "und hebe alles hervor, was aelter als 60 Tage ist.",
        },
        "en": {
            "title": "Delivered but unbilled services",
            "desc": "Billable hours delivered without an invoice – tied-up "
                    "money that only needs to be called in.",
            "kpis": ["Unbilled hours", "Value in euro", "Age",
                     "Projects affected"],
            "task": "Determine all billable but not yet invoiced services per "
                    "project and customer, with hours, value and the age of the "
                    "oldest item. Sort by value descending and highlight "
                    "everything older than 60 days.",
        },
    },

    # ═══ Hotline & Service ═══════════════════════════════════════════════
    {
        "id": "ticket_lage", "cat": "service",
        "sources": "Tickets, Hotline-Vorgaenge, Kunden",
        "de": {
            "title": "Ticket-Lage: offen, alt, unbearbeitet",
            "desc": "Der Zustand der Hotline auf einen Blick: offene Vorgaenge "
                    "nach Alter, Prioritaet und Bearbeiter.",
            "kpis": ["offene Tickets", "aelter als 7 Tage", "ohne Bearbeiter",
                     "je Prioritaet", "je Kunde"],
            "task": "Fasse die offenen Hotline-/Service-Vorgaenge zusammen: "
                    "Anzahl gesamt, gruppiert nach Prioritaet, Bearbeiter und "
                    "Alter. Liste alle Vorgaenge ohne Bearbeiter und alle, die "
                    "aelter als sieben Tage sind, einzeln auf.",
        },
        "en": {
            "title": "Ticket situation: open, ageing, unassigned",
            "desc": "The state of the helpdesk at a glance: open items by age, "
                    "priority and assignee.",
            "kpis": ["Open tickets", "Older than 7 days", "Unassigned",
                     "Per priority", "Per customer"],
            "task": "Summarise open helpdesk/service items: total count, grouped "
                    "by priority, assignee and age. List individually all items "
                    "without an assignee and all older than seven days.",
        },
    },
    {
        "id": "reaktionszeit", "cat": "service",
        "sources": "Tickets, Vertraege (SLA), Kunden",
        "de": {
            "title": "Reaktions- und Loesungszeiten (SLA)",
            "desc": "Wie schnell wird reagiert und geloest – und wo werden "
                    "zugesagte Zeiten gerissen?",
            "kpis": ["mittlere Reaktionszeit", "mittlere Loesungszeit",
                     "SLA-Verletzungen", "Quote innerhalb der Zusage"],
            "task": "Berechne fuer die abgeschlossenen Vorgaenge der letzten drei "
                    "Monate die mittlere Reaktions- und Loesungszeit, je Kunde "
                    "und je Prioritaet. Weise aus, wie viele Vorgaenge die "
                    "vertraglich zugesagte Zeit ueberschritten haben. Ist keine "
                    "SLA-Angabe hinterlegt, sage das und werte nur die "
                    "tatsaechlichen Zeiten aus.",
        },
        "en": {
            "title": "Response and resolution times (SLA)",
            "desc": "How fast is the response and resolution – and where are "
                    "committed times breached?",
            "kpis": ["Mean response time", "Mean resolution time",
                     "SLA breaches", "Share within commitment"],
            "task": "For the closed items of the last three months, calculate "
                    "mean response and resolution time, per customer and per "
                    "priority. Show how many items exceeded the contractually "
                    "committed time. If no SLA is stored, say so and evaluate "
                    "only the actual times.",
        },
    },
    {
        "id": "ticket_ursachen", "cat": "service",
        "sources": "Tickets, Kategorien, Produkte",
        "de": {
            "title": "Haeufige Ursachen und Wiederholungsfaelle",
            "desc": "Welche Themen kommen immer wieder? Wiederkehrende "
                    "Vorgaenge sind der beste Hinweis auf ein Problem, das man "
                    "einmal loesen kann statt zwanzigmal.",
            "kpis": ["Vorgaenge je Kategorie", "Wiederholungsfaelle je Kunde",
                     "Aufwand je Kategorie"],
            "task": "Gruppiere die Vorgaenge der letzten sechs Monate nach "
                    "Kategorie beziehungsweise Betreff-Aehnlichkeit und nenne "
                    "die zehn haeufigsten Themen mit Anzahl und Gesamtaufwand. "
                    "Hebe Kunden hervor, bei denen dasselbe Thema mehr als "
                    "dreimal aufgetreten ist.",
        },
        "en": {
            "title": "Frequent causes and repeat cases",
            "desc": "Which topics keep coming back? Recurring items are the best "
                    "indicator of a problem that can be solved once instead of "
                    "twenty times.",
            "kpis": ["Items per category", "Repeat cases per customer",
                     "Effort per category"],
            "task": "Group the items of the last six months by category or "
                    "subject similarity and name the ten most frequent topics "
                    "with count and total effort. Highlight customers where the "
                    "same topic occurred more than three times.",
        },
    },

    # ═══ Abrechnung, Vertraege & Seminare ════════════════════════════════
    {
        "id": "offene_posten", "cat": "abrechnung",
        "sources": "Rechnungen, Zahlungen, Kunden",
        "de": {
            "title": "Offene Posten und Zahlungsverzug",
            "desc": "Welche Rechnungen sind ueberfaellig, und wie lange? Die "
                    "Liste, mit der das Mahnwesen arbeitet.",
            "kpis": ["offene Forderungen", "ueberfaellig gesamt",
                     "Altersstruktur 30/60/90 Tage", "mittlere Zahlungsdauer"],
            "task": "Liste die offenen Rechnungen mit Kunde, Betrag, "
                    "Faelligkeitsdatum und Verzugstagen. Bilde eine "
                    "Altersstruktur (bis 30, 31 bis 60, 61 bis 90, ueber 90 "
                    "Tage) und berechne die mittlere Zahlungsdauer der bereits "
                    "bezahlten Rechnungen der letzten zwoelf Monate.",
        },
        "en": {
            "title": "Open items and payment delay",
            "desc": "Which invoices are overdue, and by how long? The list "
                    "dunning works with.",
            "kpis": ["Open receivables", "Total overdue",
                     "Ageing 30/60/90 days", "Mean days to payment"],
            "task": "List open invoices with customer, amount, due date and days "
                    "overdue. Build an ageing structure (up to 30, 31 to 60, 61 "
                    "to 90, over 90 days) and calculate the mean days to payment "
                    "for invoices already paid in the last twelve months.",
        },
    },
    {
        "id": "vertraege", "cat": "abrechnung",
        "sources": "Vertraege, Rechnungen, Kunden",
        "de": {
            "title": "Wartungs- und Serviceverträge",
            "desc": "Laufende Vertraege mit Wert, Laufzeit und Kuendigungsfrist "
                    "– und welche in den naechsten Monaten auslaufen.",
            "kpis": ["Anzahl Vertraege", "wiederkehrender Umsatz je Jahr",
                     "auslaufend in 90 Tagen", "Vertraege ohne Abrechnung"],
            "task": "Liste die laufenden Vertraege mit Kunde, Wert, Laufzeit und "
                    "naechstem Kuendigungs- oder Verlaengerungstermin. Weise den "
                    "wiederkehrenden Jahresumsatz aus und hebe alle Vertraege "
                    "hervor, die in den naechsten 90 Tagen enden oder zu denen im "
                    "laufenden Jahr keine Rechnung existiert.",
        },
        "en": {
            "title": "Maintenance and service contracts",
            "desc": "Running contracts with value, term and notice period – and "
                    "which ones expire over the coming months.",
            "kpis": ["Number of contracts", "Recurring revenue per year",
                     "Expiring within 90 days", "Contracts without billing"],
            "task": "List running contracts with customer, value, term and next "
                    "notice or renewal date. Show recurring annual revenue and "
                    "highlight all contracts ending within the next 90 days or "
                    "without an invoice in the current year.",
        },
    },
    {
        "id": "seminare", "cat": "abrechnung",
        "sources": "Seminare, Teilnehmer, Rechnungen",
        "de": {
            "title": "Seminare: Belegung und Ertrag",
            "desc": "Wie voll sind die Veranstaltungen, und was bringen sie? "
                    "Belegung, Teilnehmer und Erloes je Seminar.",
            "kpis": ["Seminare gesamt", "Teilnehmer", "Belegungsquote",
                     "Erloes je Seminar", "Absagen"],
            "task": "Werte die Seminare der letzten zwoelf Monate aus: je "
                    "Veranstaltung Termin, Plaetze, Teilnehmer, Belegungsquote "
                    "und Erloes. Nenne die drei bestbelegten und die drei "
                    "schwaechsten Veranstaltungen sowie anstehende Termine mit "
                    "geringer Belegung.",
        },
        "en": {
            "title": "Seminars: occupancy and revenue",
            "desc": "How full are the events, and what do they earn? Occupancy, "
                    "participants and revenue per seminar.",
            "kpis": ["Total seminars", "Participants", "Occupancy rate",
                     "Revenue per seminar", "Cancellations"],
            "task": "Evaluate the seminars of the last twelve months: per event "
                    "date, seats, participants, occupancy rate and revenue. Name "
                    "the three best attended and the three weakest events, plus "
                    "upcoming dates with low occupancy.",
        },
    },

    # ═══ Auslastung & Lastplan ═══════════════════════════════════════════
    {
        "id": "auslastung", "cat": "ressourcen",
        "sources": "Zeiten, Mitarbeiter, Sollzeiten",
        "de": {
            "title": "Auslastung je Mitarbeiter",
            "desc": "Verhaeltnis von abrechenbarer Zeit zur verfuegbaren Zeit – "
                    "die zentrale Kennzahl im Dienstleistungsgeschaeft.",
            "kpis": ["Sollstunden", "erfasste Stunden", "abrechenbare Stunden",
                     "Auslastung in %", "Abweichung zum Ziel"],
            "task": "Berechne je Mitarbeiter fuer die letzten drei Monate die "
                    "Auslastung als Verhaeltnis abrechenbarer zu verfuegbaren "
                    "Stunden. Zeige den Monatsverlauf und nenne die Mitarbeiter "
                    "mit der niedrigsten und der hoechsten Auslastung. Sind "
                    "keine Sollzeiten hinterlegt, sage das und weise nur die "
                    "absoluten Stunden aus.",
        },
        "en": {
            "title": "Utilisation per employee",
            "desc": "Ratio of billable to available time – the central key "
                    "figure in the services business.",
            "kpis": ["Target hours", "Recorded hours", "Billable hours",
                     "Utilisation in %", "Deviation from target"],
            "task": "For the last three months calculate utilisation per "
                    "employee as the ratio of billable to available hours. Show "
                    "the monthly trend and name the employees with the lowest "
                    "and highest utilisation. If no target hours are stored, say "
                    "so and show absolute hours only.",
        },
    },
    {
        "id": "lastplan", "cat": "ressourcen",
        "sources": "Lastplan, Projekte, Mitarbeiter, Zeiten",
        "de": {
            "title": "Lastplan: verplante Kapazitaet der naechsten Wochen",
            "desc": "Wer ist wann verplant, wo entsteht ein Engpass und wo "
                    "steht Kapazitaet frei?",
            "kpis": ["verplante Stunden je Woche", "freie Kapazitaet",
                     "ueberbuchte Mitarbeiter", "Projekte ohne Zuordnung"],
            "task": "Stelle die Planung der naechsten acht Wochen je Mitarbeiter "
                    "und Woche dar: verplante Stunden gegen verfuegbare "
                    "Kapazitaet. Markiere Ueberbuchungen und nenne die Wochen "
                    "mit der groessten freien Kapazitaet.",
        },
        "en": {
            "title": "Capacity plan: scheduled load of the coming weeks",
            "desc": "Who is scheduled when, where does a bottleneck arise and "
                    "where is capacity free?",
            "kpis": ["Scheduled hours per week", "Free capacity",
                     "Overbooked employees", "Projects without assignment"],
            "task": "Present the plan for the next eight weeks per employee and "
                    "week: scheduled hours against available capacity. Mark "
                    "overbookings and name the weeks with the largest free "
                    "capacity.",
        },
    },
    {
        "id": "engpaesse", "cat": "ressourcen",
        "sources": "Lastplan, Projekte, Qualifikationen, Mitarbeiter",
        "de": {
            "title": "Engpaesse und kritische Zuordnungen",
            "desc": "Welche Projekte haengen an einzelnen Personen? "
                    "Personenabhaengigkeit ist im Projektgeschaeft das Risiko, "
                    "das am spaetesten auffaellt.",
            "kpis": ["Projekte mit nur einem Beteiligten",
                     "Mitarbeiter in mehr als fuenf Projekten",
                     "Projekte ohne Vertretung"],
            "task": "Finde Projekte, an denen nur eine einzige Person arbeitet, "
                    "und Mitarbeiter, die gleichzeitig in mehr als fuenf "
                    "Projekten verplant sind. Nenne je Fall Projekt, Person und "
                    "Umfang und ordne das Risiko in einem Satz ein.",
        },
        "en": {
            "title": "Bottlenecks and critical assignments",
            "desc": "Which projects depend on single individuals? Key-person "
                    "dependency is the project risk noticed last.",
            "kpis": ["Projects with a single contributor",
                     "Employees in more than five projects",
                     "Projects without backup"],
            "task": "Find projects worked on by a single person only, and "
                    "employees scheduled in more than five projects at once. For "
                    "each case name project, person and scope and assess the "
                    "risk in one sentence.",
        },
    },
]

# ── Zielwerkzeuge (wofuer soll das Ergebnis aufbereitet werden?) ───────────
# Gleiche Rolle wie ``BI_TOOLS`` im SAP-Katalog. ``iface`` beschreibt den Weg,
# auf dem dasselbe System direkt angebunden wuerde – bei VEMAS ist das in allen
# Faellen der REST-Webservice, deshalb steht dort einheitlich "REST/JSON" und
# nicht ein erfundener Connector-Name.
def _werkzeugname(b: dict, lg: str) -> str:
    """Name eines Zielwerkzeugs in der aktiven Sprache.

    Nur der Eintrag ``inline`` braucht das – alle anderen sind Eigennamen und
    heissen in jeder Sprache gleich. Fehlt ``name_en``, gilt ``name``: ein
    kuenftiger Eintrag ohne Uebersetzung faellt damit nicht aus, er erscheint
    nur unuebersetzt.
    """
    if lg == "en":
        return b.get("name_en") or b["name"]
    return b["name"]


TOOLS: list[dict] = [
    {
        "id": "inline", "name": "Direkt hier anzeigen",
        "name_en": "Show here directly", "iface": None,
        "export": "Gib das Ergebnis als Markdown-Tabelle aus. Wenn sich eine "
                  "Zeitreihe oder ein Anteilsvergleich anbietet, ergaenze einen "
                  "```chartjs-Block mit einer gueltigen Chart.js-Konfiguration.",
        "export_en": "Return the result as a Markdown table. If a time series "
                     "or share comparison fits, add a ```chartjs block with a "
                     "valid Chart.js configuration.",
    },
    {
        "id": "excel", "name": "Excel", "iface": "REST/JSON",
        "export": "Bereite das Ergebnis als flache Tabelle auf: eine Kopfzeile "
                  "mit eindeutigen Spaltennamen, ein Datensatz je Zeile, Zahlen "
                  "ohne Tausenderpunkte, Datumsangaben im Format JJJJ-MM-TT. "
                  "Erzeuge daraus zusaetzlich eine Excel-Datei.",
        "export_en": "Prepare the result as a flat table: one header row with "
                     "unique column names, one record per row, numbers without "
                     "thousand separators, dates as YYYY-MM-DD. Additionally "
                     "produce an Excel file from it.",
    },
    {
        "id": "powerbi", "name": "Microsoft Power BI", "iface": "REST/JSON",
        "export": "Bereite das Ergebnis so auf, dass es in Power BI "
                  "weiterverwendbar ist: flache Tabelle mit eindeutigen "
                  "Spaltennamen ohne Leerzeichen, ein Datensatz je Zeile, "
                  "Datumsangaben im Format JJJJ-MM-TT. Nenne am Ende die "
                  "VEMAS-Ressourcen, aus denen die Daten stammen.",
        "export_en": "Prepare the result for reuse in Power BI: flat table with "
                     "unique column names without spaces, one record per row, "
                     "dates as YYYY-MM-DD. Name the VEMAS resources the data "
                     "came from at the end.",
    },
    {
        "id": "bericht", "name": "Bericht (Fliesstext)", "iface": None,
        "export": "Formuliere das Ergebnis als kurzen Bericht in ganzen Saetzen "
                  "– Lage, Auffaelligkeiten, Empfehlung. Zahlen gehoeren in eine "
                  "kleine Tabelle am Ende, nicht in den Fliesstext.",
        "export_en": "Write the result as a short report in full sentences – "
                     "situation, anomalies, recommendation. Figures belong in a "
                     "small table at the end, not in the prose.",
    },
]


def _lang(lang: str) -> str:
    """Normalisiert die Sprachangabe. Alles ausser ``en`` ist Deutsch – die
    Oberflaeche kennt nur zwei Sprachen, und ein unbekanntes Kuerzel darf keine
    leere Liste liefern."""
    return "en" if str(lang or "").strip().lower().startswith("en") else "de"


def normalize_hidden(value) -> list[str]:
    """Macht aus einem gespeicherten Wert eine saubere Liste von Abfrage-Ids.

    Nimmt Liste ODER kommagetrennten Text an (eine handgeschriebene
    settings.json darf den Bereich nicht lahmlegen) und **verwirft unbekannte
    Ids, statt sie zu raten**. Das ist wichtig, wenn eine Abfrage aus dem
    Katalog verschwindet: ihre Id wuerde sonst dauerhaft in der Konfiguration
    stehenbleiben und beim naechsten Speichern wieder mitgeschrieben."""
    if value is None:
        return []
    if isinstance(value, str):
        raw = [p.strip() for p in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw = [str(p).strip() for p in value]
    else:
        return []
    known = {a["id"] for a in ANALYSES}
    seen, out = set(), []
    for r in raw:
        if r in known and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def catalog(lang: str = "de", hidden=None) -> dict:
    """Liefert Kategorien, Abfragen und Zielwerkzeuge in EINER Sprache.

    Die Oberflaeche bekommt bewusst nur die aktive Sprache – sie soll nicht
    selbst zwischen ``de`` und ``en`` waehlen muessen (zwei Auswahlstellen
    laufen erfahrungsgemaess auseinander).

    ``hidden`` sind die vom Administrator ausgeblendeten Ids (*Einstellungen →
    Vemas*). Sie fallen hier heraus – **und ebenso jede Kategorie, die dadurch
    leer wird**: eine Gruppenueberschrift ohne Eintraege sieht im Pulldown wie
    ein Fehler aus.

    ``hidden=None`` bedeutet "nichts ausgeblendet", NICHT "nichts sichtbar".
    Das ist Absicht und der Unterschied zu einer Berechtigung: wer den Bereich
    betreten darf, hat die Freigabe bereits; dies hier ist nur eine
    Aufraeum-Einstellung."""
    lg = _lang(lang)
    skip = set(normalize_hidden(hidden))
    items = []
    for a in ANALYSES:
        if a["id"] in skip:
            continue
        t = a[lg]
        items.append({
            "id": a["id"], "cat": a["cat"], "title": t["title"],
            "desc": t["desc"], "kpis": t["kpis"], "sources": a["sources"],
        })
    used = {i["cat"] for i in items}
    cats = [{"id": c["id"], "title": c[lg]} for c in CATEGORIES if c["id"] in used]
    tools = [{"id": b["id"], "name": _werkzeugname(b, lg), "iface": b["iface"]}
             for b in TOOLS]
    return {"lang": lg, "categories": cats, "analyses": items, "tools": tools}


def admin_catalog(lang: str = "de", hidden=None) -> dict:
    """Vollstaendiger Katalog MIT Sichtbarkeitsmerker – fuer den Reiter
    *Einstellungen → Vemas*.

    Bewusst getrennt von ``catalog()``: dort darf eine ausgeblendete Abfrage
    nicht auftauchen, hier MUSS sie es (man kann sonst nichts wieder
    einblenden). Alle Kategorien bleiben erhalten, auch leere – der
    Administrator soll die Gliederung vollstaendig sehen."""
    lg = _lang(lang)
    skip = set(normalize_hidden(hidden))
    cats = [{"id": c["id"], "title": c[lg]} for c in CATEGORIES]
    items = [{"id": a["id"], "cat": a["cat"], "title": a[lg]["title"],
              "desc": a[lg]["desc"], "visible": a["id"] not in skip}
             for a in ANALYSES]
    return {"lang": lg, "categories": cats, "analyses": items,
            "hidden": sorted(skip), "total": len(ANALYSES)}


def is_hidden(analysis_id: str, hidden=None) -> bool:
    """True, wenn die Abfrage vom Administrator ausgeblendet wurde."""
    return analysis_id in set(normalize_hidden(hidden))


def find(analysis_id: str) -> dict | None:
    """Sucht eine Abfrage nach Id (None, wenn unbekannt)."""
    for a in ANALYSES:
        if a["id"] == analysis_id:
            return a
    return None


def find_tool(tool_id: str) -> dict | None:
    """Sucht ein Zielwerkzeug nach Id (None, wenn unbekannt)."""
    for b in TOOLS:
        if b["id"] == tool_id:
            return b
    return None


def build_task(analysis_id: str = "", question: str = "", tool_id: str = "",
               instructions: str = "", lang: str = "de") -> str:
    """Baut den Arbeitsauftrag fuer den Agenten aus Vorlage, Freitext,
    Zielwerkzeug und den persoenlichen Anweisungen des Benutzers.

    Reihenfolge ist Absicht: erst der allgemeine Vorspann (Vorgehen), dann die
    Vorlage, dann die konkrete Frage, dann die Aufbereitung fuer das
    Zielwerkzeug, zuletzt die persoenlichen Anweisungen – Spaeteres praezisiert
    Frueheres. Kippt die Reihenfolge, gewinnt die Vorlage gegen die
    ausdrueckliche Anweisung des Benutzers (dieselbe Lehre wie beim Vorfall
    2026-08-17, als eine Stilvorgabe die Bedingung einer E-Mail-Regel aufhob).

    Gibt einen leeren String zurueck, wenn weder Vorlage noch Frage vorliegen;
    der Aufrufer entscheidet dann ueber die Fehlermeldung."""
    lg = _lang(lang)
    parts: list[str] = [_PREAMBLE_EN if lg == "en" else _PREAMBLE_DE]

    a = find(analysis_id) if analysis_id else None
    if a:
        t = a[lg]
        head = "ANALYSIS" if lg == "en" else "AUSWERTUNG"
        src = ("Usual VEMAS resources (hint, not guaranteed – verify first)"
               if lg == "en" else
               "Uebliche VEMAS-Ressourcen (Hinweis, nicht garantiert – zuerst pruefen)")
        kpi = "Key figures" if lg == "en" else "Kennzahlen"
        parts.append(
            "%s: %s\n%s\n\n%s: %s\n%s: %s" % (
                head, t["title"], t["task"], kpi, ", ".join(t["kpis"]),
                src, a["sources"]))

    q = (question or "").strip()
    if q:
        lbl = ("Additional question from the user (takes precedence over the "
               "template where it conflicts)") if lg == "en" else \
              ("Zusaetzliche Frage des Benutzers (geht bei Widerspruch der "
               "Vorlage vor)")
        parts.append("%s:\n%s" % (lbl, q))

    b = find_tool(tool_id) if tool_id else None
    if b:
        lbl = "Target tool" if lg == "en" else "Zielwerkzeug"
        exp = b.get("export_en" if lg == "en" else "export") or ""
        parts.append("%s: %s\n%s" % (lbl, _werkzeugname(b, lg), exp))

    ins = (instructions or "").strip()
    if ins:
        lbl = ("Personal instructions of the user (always apply)"
               if lg == "en" else
               "Persoenliche Anweisungen des Benutzers (gelten immer)")
        parts.append("%s:\n%s" % (lbl, ins[:4000]))

    if not a and not q:
        return ""
    return "\n\n".join(parts)
