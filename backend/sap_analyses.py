"""Katalog der Management-Analysen fuer den SAP-Bereich (``/sap``).

Warum ein eigenes Modul und keine i18n-Keys im Frontend: das hier sind
**Daten**, keine Oberflaechen-Beschriftungen. Jeder Eintrag traegt neben Titel
und Beschreibung auch die SAP-Quellen und einen fertigen Arbeitsauftrag fuer den
Agenten – Titel und Auftrag muessen zusammenpassen. Lagen sie in ``i18n.js`` und
hier, wuerden sie auseinanderlaufen (genau das Muster, das im Projekt schon
mehrfach Stunden gekostet hat). Deshalb: EINE Quelle, beide Sprachen darin.

**Zuschnitt: boersennotierte Aktiengesellschaft.** Die Auswahl folgt dem, was
Vorstand, Aufsichtsrat und Investor Relations tatsaechlich brauchen – also nicht
nur die klassische Betriebsauswertung, sondern auch die kapitalmarktrechtlichen
Pflichten: Segmentberichterstattung (IFRS 8), Wertberichtigung nach dem
Modell erwarteter Kreditverluste (IFRS 9), Konzernkonsolidierung,
Internes Kontrollsystem (§ 91 Abs. 3 AktG), Nachhaltigkeitsberichterstattung
(CSRD/ESRS) und die Frueherkennung ad-hoc-pflichtiger Abweichungen
(Art. 17 Marktmissbrauchsverordnung).

**Read-Only bleibt Read-Only.** Die Auftraege sind reine Lese-Auswertungen; der
``sap_client`` erzwingt das ohnehin hart (OData nur GET, SQL nur SELECT/WITH,
RFC nur Whitelist). Kein Eintrag hier darf einen schreibenden Vorgang
beschreiben.

Die genannten Tabellen sind die ueblichen Fundstellen in S/4HANA bzw. ECC. Sie
sind **Hinweise fuer den Agenten**, keine Zusicherung: welches Feld in einem
konkreten System befuellt ist, haengt vom Customizing ab. Deshalb steht in jedem
Auftrag, dass zuerst die vorhandenen Strukturen zu pruefen sind.
"""

from __future__ import annotations

# ── Kategorien (Reihenfolge = Reihenfolge der Gruppen im Pulldown) ──────────
CATEGORIES: list[dict] = [
    {"id": "finance",    "de": "Finanzen & Rechnungswesen (FI/CO)",
                         "en": "Finance & accounting (FI/CO)"},
    {"id": "sales",      "de": "Vertrieb (SD)",
                         "en": "Sales (SD)"},
    {"id": "purchase",   "de": "Einkauf & Bestand (MM)",
                         "en": "Procurement & inventory (MM)"},
    {"id": "production", "de": "Produktion (PP)",
                         "en": "Production (PP)"},
    {"id": "hr",         "de": "Personal (HCM)",
                         "en": "Human resources (HCM)"},
    {"id": "governance", "de": "Governance, Compliance & Kapitalmarkt",
                         "en": "Governance, compliance & capital markets"},
]

# Gemeinsamer Vorspann jedes Auftrags. Steht EINMAL hier statt 24-mal in den
# Eintraegen – sonst driftet die Read-Only-Zusage zwischen den Analysen.
_PREAMBLE_DE = (
    "Du wertest ein SAP-System LESEND aus. Gehe so vor: (1) Verschaffe dir mit "
    "den SAP-Werkzeugen einen Ueberblick, welche Tabellen bzw. EntitySets "
    "tatsaechlich vorhanden und befuellt sind – die unten genannten Quellen sind "
    "die uebliche Fundstelle, nicht garantiert. (2) Hole die Daten in einer "
    "sinnvoll begrenzten Menge. (3) Antworte mit einer verdichteten Auswertung "
    "fuer die Geschaeftsleitung: Kennzahlen als Tabelle, danach drei bis fuenf "
    "Saetze Einordnung. Nenne Auffaelligkeiten und – falls Daten fehlen – "
    "ausdruecklich, was nicht ermittelbar war. Erfinde keine Zahlen."
)
_PREAMBLE_EN = (
    "You are analysing an SAP system READ-ONLY. Proceed as follows: (1) Use the "
    "SAP tools to find out which tables or entity sets actually exist and hold "
    "data – the sources listed below are the usual location, not a guarantee. "
    "(2) Fetch the data in a sensibly limited volume. (3) Answer with a "
    "condensed analysis for executive management: key figures as a table, then "
    "three to five sentences of interpretation. Name anomalies and – if data is "
    "missing – state explicitly what could not be determined. Never invent "
    "figures."
)

# ── Der Katalog ────────────────────────────────────────────────────────────
# Pflichtfelder je Eintrag: id, cat, sources, de{title,desc,kpis,task},
# en{title,desc,kpis,task}.
ANALYSES: list[dict] = [
    # ═══ Finanzen & Rechnungswesen ═══════════════════════════════════════
    {
        "id": "pnl_balance", "cat": "finance",
        "sources": "ACDOCA (Universal Journal), BKPF/BSEG, FAGLFLEXT, SKA1/SKAT",
        "de": {
            "title": "GuV & Bilanz (Monats-/Quartalsabschluss)",
            "desc": "Gewinn- und Verlustrechnung sowie Bilanz zum Stichtag, "
                    "gegliedert nach Kontengruppen, mit Vorjahresvergleich. "
                    "Grundlage des Zwischenabschlusses nach § 115 WpHG.",
            "kpis": ["Umsatzerloese", "Materialaufwand", "Personalaufwand",
                     "EBIT", "Jahresergebnis", "Bilanzsumme", "Eigenkapitalquote"],
            "task": "Erstelle GuV und Bilanz zum letzten abgeschlossenen Monat "
                    "je Buchungskreis, gegliedert nach Kontengruppen, mit "
                    "Vorjahresvergleich und prozentualer Abweichung. Weise "
                    "Eigenkapitalquote und Bilanzsumme gesondert aus.",
        },
        "en": {
            "title": "P&L and balance sheet (monthly/quarterly close)",
            "desc": "Profit and loss statement and balance sheet as of the "
                    "reporting date, grouped by account groups, with prior-year "
                    "comparison. Basis of the interim report.",
            "kpis": ["Revenue", "Cost of materials", "Personnel expense",
                     "EBIT", "Net income", "Total assets", "Equity ratio"],
            "task": "Produce a P&L and balance sheet for the last closed month "
                    "per company code, grouped by account groups, with "
                    "prior-year comparison and percentage variance. Show equity "
                    "ratio and total assets separately.",
        },
    },
    {
        "id": "ebit_margin", "cat": "finance",
        "sources": "ACDOCA, CE1*/CE4* (CO-PA), FAGLFLEXT",
        "de": {
            "title": "Ergebnis- und Margenentwicklung (EBIT/EBITDA)",
            "desc": "Entwicklung von Rohertrag, EBITDA und EBIT ueber die "
                    "letzten Perioden – die Kennzahlen, die in jeder "
                    "Quartalsmitteilung und jedem Analystengespraech stehen.",
            "kpis": ["Rohertragsmarge", "EBITDA", "EBITDA-Marge", "EBIT",
                     "EBIT-Marge", "Veraenderung zum Vorjahr"],
            "task": "Ermittle Umsatz, Rohertrag, EBITDA und EBIT je Monat der "
                    "letzten zwoelf Monate, jeweils mit Marge in Prozent und "
                    "Vorjahresvergleich. Benenne die drei groessten Treiber der "
                    "Margenveraenderung.",
        },
        "en": {
            "title": "Earnings and margin development (EBIT/EBITDA)",
            "desc": "Development of gross profit, EBITDA and EBIT over recent "
                    "periods – the figures quoted in every quarterly statement "
                    "and analyst call.",
            "kpis": ["Gross margin", "EBITDA", "EBITDA margin", "EBIT",
                     "EBIT margin", "Year-over-year change"],
            "task": "Determine revenue, gross profit, EBITDA and EBIT per month "
                    "for the last twelve months, each with margin in percent "
                    "and prior-year comparison. Name the three largest drivers "
                    "of the margin change.",
        },
    },
    {
        "id": "cashflow_liquidity", "cat": "finance",
        "sources": "BSIS/BSAS, BSID/BSAD, BSIK/BSAK, FEBEP (Kontoauszug), ACDOCA",
        "de": {
            "title": "Cashflow & Liquiditaetsvorschau",
            "desc": "Zahlungsmittelbestand, operativer Cashflow und die "
                    "erwarteten Ein- und Auszahlungen der naechsten Wochen aus "
                    "faelligen Forderungen und Verbindlichkeiten.",
            "kpis": ["Liquide Mittel", "Operativer Cashflow", "Free Cashflow",
                     "Faellige Forderungen", "Faellige Verbindlichkeiten",
                     "Liquiditaetssaldo je Woche"],
            "task": "Ermittle den aktuellen Bestand liquider Mittel je Bank "
                    "und Waehrung sowie eine Liquiditaetsvorschau ueber die "
                    "naechsten 13 Wochen aus offenen Posten (Debitoren nach "
                    "Netto-Faelligkeit, Kreditoren nach Faelligkeit). Weise "
                    "Wochen mit negativem Saldo gesondert aus.",
        },
        "en": {
            "title": "Cash flow and liquidity forecast",
            "desc": "Cash position, operating cash flow and expected inflows "
                    "and outflows over the coming weeks from due receivables "
                    "and payables.",
            "kpis": ["Cash and equivalents", "Operating cash flow",
                     "Free cash flow", "Receivables due", "Payables due",
                     "Weekly liquidity balance"],
            "task": "Determine the current cash position per bank and currency "
                    "plus a 13-week liquidity forecast from open items "
                    "(customers by net due date, vendors by due date). "
                    "Highlight weeks with a negative balance.",
        },
    },
    {
        "id": "working_capital", "cat": "finance",
        "sources": "BSID/BSAD (Debitoren), BSIK/BSAK (Kreditoren), MBEW/MARD (Bestand), ACDOCA",
        "de": {
            "title": "Working Capital & Cash Conversion Cycle",
            "desc": "Kapitalbindung im operativen Geschaeft: Wie lange dauert "
                    "es vom Materialeinkauf bis zum Geldeingang? Der "
                    "wirksamste Hebel auf den Free Cashflow.",
            "kpis": ["DSO (Forderungslaufzeit)", "DPO (Verbindlichkeitenlaufzeit)",
                     "DIO (Lagerdauer)", "Cash Conversion Cycle",
                     "Net Working Capital", "Kapitalbindung in Tagen"],
            "task": "Berechne DSO, DPO und DIO sowie den Cash Conversion Cycle "
                    "je Buchungskreis fuer die letzten vier Quartale. Stelle "
                    "die Entwicklung dar und beziffere, wieviel Kapital eine "
                    "Verkuerzung des DSO um fuenf Tage freisetzen wuerde.",
        },
        "en": {
            "title": "Working capital and cash conversion cycle",
            "desc": "Capital tied up in operations: how long from buying "
                    "material to receiving cash? The strongest lever on free "
                    "cash flow.",
            "kpis": ["DSO", "DPO", "DIO", "Cash conversion cycle",
                     "Net working capital", "Days of capital tied up"],
            "task": "Calculate DSO, DPO and DIO plus the cash conversion cycle "
                    "per company code for the last four quarters. Show the "
                    "trend and quantify how much capital a five-day DSO "
                    "reduction would release.",
        },
    },
    {
        "id": "ar_aging", "cat": "finance",
        "sources": "BSID/BSAD, KNA1/KNB1 (Debitorenstamm), KNKK (Kreditlimit)",
        "de": {
            "title": "Debitoren-Altersstruktur & Ausfallrisiko",
            "desc": "Offene Forderungen nach Faelligkeitsklassen, je Kunde, "
                    "mit Ueberschreitung des Kreditlimits. Grundlage der "
                    "Wertberichtigung nach dem Modell erwarteter Kreditverluste "
                    "(IFRS 9).",
            "kpis": ["Offene Forderungen gesamt", "Nicht faellig",
                     "1–30 / 31–60 / 61–90 / >90 Tage ueberfaellig",
                     "Ueberfaelligenquote", "Kreditlimit-Ueberschreitungen"],
            "task": "Erstelle eine Altersstrukturliste der offenen Forderungen "
                    "in den Klassen nicht faellig, 1–30, 31–60, 61–90 und ueber "
                    "90 Tage, je Buchungskreis und fuer die 20 groessten "
                    "Debitoren. Markiere Kunden mit ueberschrittenem "
                    "Kreditlimit und schaetze die erwarteten Kreditverluste je "
                    "Klasse ab.",
        },
        "en": {
            "title": "Accounts receivable ageing and credit risk",
            "desc": "Open receivables by ageing bucket and customer, including "
                    "credit limit breaches. Basis of expected credit loss "
                    "impairment under IFRS 9.",
            "kpis": ["Total open receivables", "Not yet due",
                     "1–30 / 31–60 / 61–90 / >90 days overdue",
                     "Overdue ratio", "Credit limit breaches"],
            "task": "Produce an ageing list of open receivables in the buckets "
                    "not due, 1–30, 31–60, 61–90 and over 90 days, per company "
                    "code and for the 20 largest customers. Flag customers "
                    "exceeding their credit limit and estimate expected credit "
                    "losses per bucket.",
        },
    },
    {
        "id": "ap_discount", "cat": "finance",
        "sources": "BSIK/BSAK, LFA1/LFB1 (Kreditorenstamm), RBKP/RSEG (Rechnungspruefung)",
        "de": {
            "title": "Kreditoren & Skonto-Ausnutzung",
            "desc": "Offene Verbindlichkeiten nach Faelligkeit und die Frage, "
                    "wieviel Skonto durch zu spaete Zahlung verfaellt – ein "
                    "still verlorener Ergebnisbeitrag.",
            "kpis": ["Offene Verbindlichkeiten", "Faellig in 7/14/30 Tagen",
                     "Genutztes Skonto", "Verfallenes Skonto",
                     "Skonto-Ausnutzungsquote", "Zahlungsziel im Mittel"],
            "task": "Stelle die offenen Verbindlichkeiten nach Faelligkeit dar "
                    "und ermittle fuer die letzten zwoelf Monate, wieviel "
                    "Skonto genutzt und wieviel verfallen ist – je Lieferant "
                    "und in Summe. Nenne die zehn Lieferanten mit dem groessten "
                    "verfallenen Skontobetrag.",
        },
        "en": {
            "title": "Accounts payable and cash discount usage",
            "desc": "Open payables by due date plus how much cash discount is "
                    "lost to late payment – a silently forfeited contribution "
                    "to earnings.",
            "kpis": ["Open payables", "Due in 7/14/30 days",
                     "Discount taken", "Discount forfeited",
                     "Discount utilisation rate", "Average payment terms"],
            "task": "Show open payables by due date and determine for the last "
                    "twelve months how much cash discount was taken and how "
                    "much was forfeited – per vendor and in total. Name the ten "
                    "vendors with the largest forfeited discount amount.",
        },
    },
    {
        "id": "budget_variance", "cat": "finance",
        "sources": "ACDOCA, COSP/COSS (Kostenstellen-Ist), COSP_BAK/Plandaten, CSKS (Kostenstellenstamm)",
        "de": {
            "title": "Plan-Ist-Abweichung Kostenstellen",
            "desc": "Budgetausschoepfung je Kostenstelle und Kostenart mit "
                    "Hochrechnung auf das Jahresende – die Standardvorlage der "
                    "monatlichen Bereichsleiterrunde.",
            "kpis": ["Planwert", "Istwert", "Abweichung absolut/prozentual",
                     "Budgetausschoepfung", "Hochrechnung Jahresende"],
            "task": "Vergleiche Plan und Ist je Kostenstelle und Kostenart im "
                    "laufenden Geschaeftsjahr, kumuliert bis zum letzten "
                    "abgeschlossenen Monat. Rechne linear auf das Jahresende "
                    "hoch und liste die zehn Kostenstellen mit der groessten "
                    "absoluten Ueberschreitung.",
        },
        "en": {
            "title": "Cost centre plan-actual variance",
            "desc": "Budget consumption per cost centre and cost element with "
                    "a year-end projection – the standard template of the "
                    "monthly department head meeting.",
            "kpis": ["Plan", "Actual", "Variance absolute/percent",
                     "Budget consumption", "Year-end projection"],
            "task": "Compare plan and actual per cost centre and cost element "
                    "for the current fiscal year, cumulative to the last closed "
                    "month. Extrapolate linearly to year end and list the ten "
                    "cost centres with the largest absolute overrun.",
        },
    },
    {
        "id": "profit_center", "cat": "finance",
        "sources": "ACDOCA, CE1*/CE3*/CE4* (CO-PA), CEPC (Profit-Center-Stamm)",
        "de": {
            "title": "Segment-/Profit-Center-Ergebnis (Deckungsbeitrag)",
            "desc": "Ergebnisrechnung je Segment, Profit Center und "
                    "Produktgruppe bis zum Deckungsbeitrag. Liefert zugleich "
                    "die Zahlen fuer die Segmentberichterstattung nach IFRS 8.",
            "kpis": ["Umsatz je Segment", "Deckungsbeitrag I/II",
                     "DB-Marge", "Segmentergebnis", "Anteil am Konzernumsatz"],
            "task": "Erstelle eine mehrstufige Deckungsbeitragsrechnung je "
                    "Profit Center und Segment fuer das laufende Geschaeftsjahr "
                    "mit Vorjahresvergleich. Weise je Segment Umsatz, "
                    "Deckungsbeitrag und Segmentergebnis aus und pruefe, welche "
                    "Segmente die Groessenkriterien des IFRS 8 erfuellen.",
        },
        "en": {
            "title": "Segment / profit centre result (contribution margin)",
            "desc": "Result per segment, profit centre and product group down "
                    "to contribution margin. Also supplies the figures for "
                    "segment reporting under IFRS 8.",
            "kpis": ["Revenue per segment", "Contribution margin I/II",
                     "CM ratio", "Segment result", "Share of group revenue"],
            "task": "Produce a multi-level contribution margin statement per "
                    "profit centre and segment for the current fiscal year with "
                    "prior-year comparison. Show revenue, contribution margin "
                    "and segment result per segment and check which segments "
                    "meet the IFRS 8 quantitative thresholds.",
        },
    },
    {
        "id": "capex_assets", "cat": "finance",
        "sources": "ANLA/ANLC/ANLZ (Anlagenstamm/Werte), ANEP/ANEA (Bewegungen), AUFK (Investitionsauftraege)",
        "de": {
            "title": "Investitionen & Anlagenspiegel",
            "desc": "Zugaenge, Abgaenge und Abschreibungen des "
                    "Anlagevermoegens sowie der Stand laufender "
                    "Investitionsauftraege gegen das Investitionsbudget.",
            "kpis": ["Zugaenge (CAPEX)", "Abgaenge", "Planmaessige AfA",
                     "Restbuchwert", "Budgetausschoepfung Investitionen",
                     "AfA-Vorschau Folgejahr"],
            "task": "Erstelle einen Anlagenspiegel fuer das laufende "
                    "Geschaeftsjahr je Anlagenklasse mit Anfangsbestand, "
                    "Zugaengen, Abgaengen, Abschreibungen und Endbestand. "
                    "Ergaenze den Stand der offenen Investitionsauftraege gegen "
                    "das Budget und eine AfA-Vorschau fuer das Folgejahr.",
        },
        "en": {
            "title": "Capital expenditure and asset movement schedule",
            "desc": "Additions, disposals and depreciation of fixed assets "
                    "plus the status of open investment orders against the "
                    "capex budget.",
            "kpis": ["Additions (capex)", "Disposals", "Scheduled depreciation",
                     "Net book value", "Capex budget consumption",
                     "Depreciation forecast next year"],
            "task": "Produce an asset movement schedule for the current fiscal "
                    "year per asset class with opening balance, additions, "
                    "disposals, depreciation and closing balance. Add the "
                    "status of open investment orders against budget and a "
                    "depreciation forecast for next year.",
        },
    },

    # ═══ Vertrieb ════════════════════════════════════════════════════════
    {
        "id": "revenue_split", "cat": "sales",
        "sources": "VBAK/VBAP (Auftraege), VBRK/VBRP (Fakturen), KNA1, MARA/MVKE",
        "de": {
            "title": "Umsatzanalyse nach Kunde, Region und Produkt",
            "desc": "Fakturierter Umsatz aufgeteilt nach Kunde, "
                    "Vertriebsregion, Produktgruppe und Vertriebsweg, jeweils "
                    "mit Vorjahresvergleich.",
            "kpis": ["Umsatz gesamt", "Umsatz je Region/Produktgruppe",
                     "Wachstum zum Vorjahr", "Durchschnittlicher Auftragswert",
                     "Anzahl aktiver Kunden"],
            "task": "Ermittle den fakturierten Umsatz der letzten zwoelf Monate "
                    "je Vertriebsregion, Produktgruppe und Vertriebsweg mit "
                    "Vorjahresvergleich und Wachstumsrate. Nenne die zehn "
                    "staerksten und die zehn schwaechsten Entwicklungen.",
        },
        "en": {
            "title": "Revenue analysis by customer, region and product",
            "desc": "Invoiced revenue split by customer, sales region, product "
                    "group and distribution channel, each with prior-year "
                    "comparison.",
            "kpis": ["Total revenue", "Revenue per region/product group",
                     "Year-over-year growth", "Average order value",
                     "Active customers"],
            "task": "Determine invoiced revenue of the last twelve months per "
                    "sales region, product group and distribution channel with "
                    "prior-year comparison and growth rate. Name the ten "
                    "strongest and ten weakest developments.",
        },
    },
    {
        "id": "order_backlog", "cat": "sales",
        "sources": "VBAK/VBAP, VBBE (offene Bedarfe), VBUK/VBUP (Status), VBRK",
        "de": {
            "title": "Auftragseingang & Auftragsbestand (Book-to-Bill)",
            "desc": "Der wichtigste Fruehindikator fuer die kommenden "
                    "Quartale: Wie hoch ist der Auftragseingang, wie gross der "
                    "noch nicht fakturierte Bestand, und reicht er fuer die "
                    "Prognose?",
            "kpis": ["Auftragseingang", "Auftragsbestand", "Book-to-Bill-Ratio",
                     "Reichweite in Monaten", "Stornoquote",
                     "Terminverzug im Bestand"],
            "task": "Ermittle Auftragseingang je Monat der letzten zwoelf "
                    "Monate, den aktuellen Auftragsbestand nach geplantem "
                    "Lieferdatum und die Book-to-Bill-Ratio. Weise den Anteil "
                    "terminlich ueberfaelliger Auftragspositionen aus und "
                    "berechne die Reichweite des Bestands in Monatsumsaetzen.",
        },
        "en": {
            "title": "Order intake and backlog (book-to-bill)",
            "desc": "The key leading indicator for coming quarters: how large "
                    "is order intake, how large the backlog not yet invoiced, "
                    "and does it support the guidance?",
            "kpis": ["Order intake", "Order backlog", "Book-to-bill ratio",
                     "Coverage in months", "Cancellation rate",
                     "Overdue backlog"],
            "task": "Determine order intake per month for the last twelve "
                    "months, the current backlog by planned delivery date and "
                    "the book-to-bill ratio. Show the share of overdue order "
                    "items and calculate backlog coverage in months of revenue.",
        },
    },
    {
        "id": "customer_abc", "cat": "sales",
        "sources": "VBRK/VBRP, KNA1/KNVV, BSID (Zahlungsverhalten)",
        "de": {
            "title": "ABC-Kundenanalyse & Klumpenrisiko",
            "desc": "Umsatzkonzentration auf wenige Kunden – fuer eine "
                    "boersennotierte Gesellschaft ein berichtspflichtiges "
                    "Risiko im Lagebericht und ein Thema jeder Due Diligence.",
            "kpis": ["Umsatzanteil Top-1/Top-5/Top-10",
                     "Anzahl Kunden fuer 80 % des Umsatzes (A-Kunden)",
                     "Herfindahl-Index", "Umsatz je Kunde",
                     "Zahlungsverhalten der A-Kunden"],
            "task": "Fuehre eine ABC-Analyse der Kunden nach Umsatz der letzten "
                    "zwoelf Monate durch. Weise den Umsatzanteil der groessten "
                    "1, 5 und 10 Kunden aus, nenne die Zahl der A-Kunden fuer "
                    "80 % des Umsatzes und bewerte das Konzentrationsrisiko. "
                    "Ergaenze je A-Kunde die durchschnittliche "
                    "Zahlungsverzoegerung.",
        },
        "en": {
            "title": "ABC customer analysis and concentration risk",
            "desc": "Revenue concentration on few customers – for a listed "
                    "company a reportable risk in the management report and a "
                    "topic in every due diligence.",
            "kpis": ["Revenue share top-1/top-5/top-10",
                     "Customers making up 80% of revenue (A customers)",
                     "Herfindahl index", "Revenue per customer",
                     "Payment behaviour of A customers"],
            "task": "Run an ABC analysis of customers by revenue of the last "
                    "twelve months. Show the revenue share of the largest 1, 5 "
                    "and 10 customers, state how many A customers make up 80% "
                    "of revenue and assess the concentration risk. Add the "
                    "average payment delay per A customer.",
        },
    },
    {
        "id": "price_discount", "cat": "sales",
        "sources": "VBRP, KONV/PRCD_ELEMENTS (Konditionen), KONP, MVKE",
        "de": {
            "title": "Preis- und Rabattanalyse",
            "desc": "Wieviel des Listenpreises kommt tatsaechlich an? "
                    "Rabatte, Boni und Gutschriften je Kunde und Produkt – der "
                    "haeufigste unbemerkte Margenverlust.",
            "kpis": ["Listenpreis", "Realisierter Nettopreis",
                     "Rabattquote", "Preisnachlass je Kunde",
                     "Gutschriftenquote", "Margenwirkung"],
            "task": "Vergleiche Listenpreis und tatsaechlich realisierten "
                    "Nettopreis je Produktgruppe und Kunde fuer die letzten "
                    "zwoelf Monate. Weise die Rabattquote aus, nenne die zehn "
                    "Kunden mit der hoechsten Rabattquote und beziffere die "
                    "Margenwirkung.",
        },
        "en": {
            "title": "Price and discount analysis",
            "desc": "How much of the list price is actually realised? "
                    "Discounts, rebates and credit notes per customer and "
                    "product – the most common unnoticed margin loss.",
            "kpis": ["List price", "Realised net price", "Discount rate",
                     "Price reduction per customer", "Credit note ratio",
                     "Margin impact"],
            "task": "Compare list price and actually realised net price per "
                    "product group and customer for the last twelve months. "
                    "Show the discount rate, name the ten customers with the "
                    "highest discount rate and quantify the margin impact.",
        },
    },

    # ═══ Einkauf & Bestand ═══════════════════════════════════════════════
    {
        "id": "spend_analysis", "cat": "purchase",
        "sources": "EKKO/EKPO (Bestellungen), EKBE (Historie), LFA1, T023 (Warengruppen)",
        "de": {
            "title": "Einkaufsvolumen nach Lieferant und Warengruppe",
            "desc": "Wohin fliesst das Geld im Einkauf? Volumen je Lieferant "
                    "und Warengruppe, Anteil des Bestellwesens am Aufwand und "
                    "Bestellungen am Rahmenvertrag vorbei (Maverick Buying).",
            "kpis": ["Einkaufsvolumen gesamt", "Volumen je Warengruppe",
                     "Top-Lieferanten", "Anzahl Lieferanten je Warengruppe",
                     "Maverick-Buying-Quote", "Bestellungen ohne Rahmenvertrag"],
            "task": "Ermittle das Einkaufsvolumen der letzten zwoelf Monate je "
                    "Warengruppe und Lieferant. Nenne die 20 groessten "
                    "Lieferanten mit Anteil am Gesamtvolumen, weise je "
                    "Warengruppe die Lieferantenzahl aus und schaetze den "
                    "Anteil der Bestellungen ohne Bezug zu einem Rahmenvertrag.",
        },
        "en": {
            "title": "Purchasing spend by vendor and material group",
            "desc": "Where does procurement money go? Volume per vendor and "
                    "material group, share of purchase orders in total spend "
                    "and orders bypassing contracts (maverick buying).",
            "kpis": ["Total spend", "Spend per material group", "Top vendors",
                     "Vendors per material group", "Maverick buying rate",
                     "Orders without contract reference"],
            "task": "Determine purchasing spend of the last twelve months per "
                    "material group and vendor. Name the 20 largest vendors "
                    "with their share of total spend, show the vendor count per "
                    "material group and estimate the share of orders without a "
                    "contract reference.",
        },
    },
    {
        "id": "supplier_otif", "cat": "purchase",
        "sources": "EKKO/EKPO, EKES (Bestaetigungen), EKBE (Wareneingaenge), LFA1",
        "de": {
            "title": "Lieferantenbewertung & Liefertreue (OTIF)",
            "desc": "Termin- und Mengentreue der Lieferanten sowie "
                    "Preisentwicklung – die Grundlage jedes "
                    "Lieferantengespraechs und der Risikobewertung in der "
                    "Lieferkette.",
            "kpis": ["Liefertreue (OTIF)", "Termintreue", "Mengentreue",
                     "Durchschnittlicher Verzug in Tagen",
                     "Preisentwicklung je Lieferant", "Reklamationsquote"],
            "task": "Bewerte die Liefertreue je Lieferant fuer die letzten "
                    "zwoelf Monate: Anteil termingerechter und mengenrichtiger "
                    "Wareneingaenge (OTIF), durchschnittlicher Verzug in Tagen "
                    "und Preisentwicklung. Nenne die zehn schwaechsten "
                    "Lieferanten mit ihrem Einkaufsvolumen.",
        },
        "en": {
            "title": "Vendor rating and delivery reliability (OTIF)",
            "desc": "On-time and in-full performance of vendors plus price "
                    "development – the basis of every vendor negotiation and of "
                    "supply chain risk assessment.",
            "kpis": ["OTIF", "On-time rate", "In-full rate",
                     "Average delay in days", "Price development per vendor",
                     "Complaint rate"],
            "task": "Rate delivery reliability per vendor for the last twelve "
                    "months: share of on-time and in-full goods receipts "
                    "(OTIF), average delay in days and price development. Name "
                    "the ten weakest vendors together with their spend volume.",
        },
    },
    {
        "id": "inventory", "cat": "purchase",
        "sources": "MARD/MCHB (Bestaende), MBEW (Bewertung), MSEG/MKPF (Bewegungen), MARA",
        "de": {
            "title": "Bestandsreichweite, Ladenhueter & Bewertung",
            "desc": "Wert und Umschlag der Vorraete, Reichweite je Material "
                    "und die Bestaende ohne Bewegung – Kandidaten fuer "
                    "Wertberichtigung und gebundenes Kapital zugleich.",
            "kpis": ["Bestandswert", "Lagerumschlagshaeufigkeit",
                     "Reichweite in Tagen", "Bestand ohne Bewegung > 12 Monate",
                     "Wertberichtigungsbedarf", "Anteil Ladenhueter"],
            "task": "Ermittle den Bestandswert je Werk und Materialgruppe, die "
                    "Lagerumschlagshaeufigkeit und die Reichweite in Tagen. "
                    "Liste Materialien ohne Warenbewegung in den letzten zwoelf "
                    "Monaten mit ihrem Bestandswert und schaetze den "
                    "Wertberichtigungsbedarf.",
        },
        "en": {
            "title": "Inventory coverage, slow movers and valuation",
            "desc": "Value and turnover of inventory, coverage per material "
                    "and stock without movement – candidates for write-down and "
                    "tied-up capital at the same time.",
            "kpis": ["Inventory value", "Inventory turnover",
                     "Coverage in days", "Stock without movement > 12 months",
                     "Write-down requirement", "Slow mover share"],
            "task": "Determine inventory value per plant and material group, "
                    "inventory turnover and coverage in days. List materials "
                    "without goods movement in the last twelve months together "
                    "with their inventory value and estimate the write-down "
                    "requirement.",
        },
    },

    # ═══ Produktion ══════════════════════════════════════════════════════
    {
        "id": "production_costs", "cat": "production",
        "sources": "AFKO/AFPO (Fertigungsauftraege), AUFK, COSP/COSS (Auftragskosten), KEKO/KEPH (Kalkulation)",
        "de": {
            "title": "Fertigungsauftraege: Herstellkosten & Abweichungen",
            "desc": "Soll-Ist-Vergleich der Herstellkosten je Auftrag und "
                    "Produkt, Ausschuss und Termintreue der Produktion.",
            "kpis": ["Plan-Herstellkosten", "Ist-Herstellkosten",
                     "Gesamtabweichung", "Material-/Fertigungsabweichung",
                     "Ausschussquote", "Termintreue Produktion",
                     "Durchlaufzeit"],
            "task": "Vergleiche Plan- und Ist-Herstellkosten je "
                    "Fertigungsauftrag und Produkt fuer die letzten sechs "
                    "Monate, aufgeteilt in Material- und Fertigungsabweichung. "
                    "Weise Ausschussquote, Termintreue und mittlere "
                    "Durchlaufzeit aus und nenne die zehn Produkte mit der "
                    "groessten negativen Abweichung.",
        },
        "en": {
            "title": "Production orders: cost of goods manufactured and variances",
            "desc": "Target-actual comparison of manufacturing cost per order "
                    "and product, scrap and production schedule adherence.",
            "kpis": ["Planned cost", "Actual cost", "Total variance",
                     "Material/production variance", "Scrap rate",
                     "Schedule adherence", "Lead time"],
            "task": "Compare planned and actual manufacturing cost per "
                    "production order and product for the last six months, "
                    "split into material and production variance. Show scrap "
                    "rate, schedule adherence and average lead time, and name "
                    "the ten products with the largest negative variance.",
        },
    },

    # ═══ Personal ════════════════════════════════════════════════════════
    {
        "id": "hr_kpis", "cat": "hr",
        "sources": "PA0000–PA0008 (Infotypen), HRP1000, ACDOCA (Personalaufwand), CSKS",
        "de": {
            "title": "Personalkennzahlen: FTE, Fluktuation, Kosten",
            "desc": "Kopfzahl und Vollzeitaequivalente je Bereich, "
                    "Fluktuation, Personalaufwand je Kopf und Ueberstunden – "
                    "auch Pflichtangaben im Anhang und im Lagebericht.",
            "kpis": ["Kopfzahl", "Vollzeitaequivalente (FTE)",
                     "Fluktuationsquote", "Personalaufwand je FTE",
                     "Ueberstunden", "Altersstruktur",
                     "Frauenanteil in Fuehrungspositionen"],
            "task": "Ermittle Kopfzahl und FTE je Bereich und Kostenstelle zum "
                    "Stichtag, die Fluktuationsquote der letzten zwoelf Monate, "
                    "den Personalaufwand je FTE sowie Ueberstundenbestand und "
                    "Altersstruktur. Weise den Frauenanteil in "
                    "Fuehrungspositionen gesondert aus.",
        },
        "en": {
            "title": "HR key figures: FTE, attrition, cost",
            "desc": "Headcount and full-time equivalents per unit, attrition, "
                    "personnel expense per head and overtime – also mandatory "
                    "disclosures in the notes and management report.",
            "kpis": ["Headcount", "Full-time equivalents (FTE)",
                     "Attrition rate", "Personnel expense per FTE", "Overtime",
                     "Age structure", "Share of women in management"],
            "task": "Determine headcount and FTE per unit and cost centre as of "
                    "the reporting date, the attrition rate of the last twelve "
                    "months, personnel expense per FTE plus overtime balance and "
                    "age structure. Show the share of women in management "
                    "positions separately.",
        },
    },

    # ═══ Governance, Compliance & Kapitalmarkt ═══════════════════════════
    {
        "id": "board_reporting", "cat": "governance",
        "sources": "ACDOCA, CE1*/CE4*, VBAK/VBRK, BSID/BSIK, ANLC",
        "de": {
            "title": "Reporting-Paket Vorstand & Aufsichtsrat (Quartal)",
            "desc": "Das verdichtete Quartalspaket: Ergebnis, Liquiditaet, "
                    "Auftragslage, Investitionen und Risiken auf zwei Seiten – "
                    "Grundlage der Berichterstattung nach § 90 AktG.",
            "kpis": ["Umsatz und EBIT gegen Plan", "Liquiditaet",
                     "Auftragsbestand", "Working Capital", "Investitionen",
                     "Personalstand", "Top-Risiken"],
            "task": "Stelle ein Quartalsberichtspaket zusammen: Umsatz, EBIT "
                    "und Ergebnis gegen Plan und Vorjahr, Liquiditaet und "
                    "Working Capital, Auftragseingang und -bestand, "
                    "Investitionen gegen Budget sowie Personalstand. Fasse die "
                    "Lage in maximal zehn Saetzen zusammen und nenne die drei "
                    "wichtigsten Risiken mit Zahlenbeleg.",
        },
        "en": {
            "title": "Board and supervisory board reporting pack (quarterly)",
            "desc": "The condensed quarterly pack: earnings, liquidity, order "
                    "situation, capex and risks on two pages – basis of "
                    "reporting to the supervisory board.",
            "kpis": ["Revenue and EBIT vs. plan", "Liquidity", "Order backlog",
                     "Working capital", "Capex", "Headcount", "Top risks"],
            "task": "Compile a quarterly reporting pack: revenue, EBIT and net "
                    "result against plan and prior year, liquidity and working "
                    "capital, order intake and backlog, capex against budget "
                    "and headcount. Summarise the situation in at most ten "
                    "sentences and name the three key risks with figures.",
        },
    },
    {
        "id": "intercompany", "cat": "governance",
        "sources": "ACDOCA (RASSC/Partnergesellschaft), BSEG, T880 (Gesellschaften), BUT000",
        "de": {
            "title": "Konzernkonsolidierung & Intercompany-Abstimmung",
            "desc": "Abstimmung der konzerninternen Forderungen, "
                    "Verbindlichkeiten, Umsaetze und Aufwendungen zwischen den "
                    "Gesellschaften – jede Differenz haelt den Konzernabschluss "
                    "auf.",
            "kpis": ["IC-Forderungen und -Verbindlichkeiten je Paar",
                     "Abstimmdifferenzen", "IC-Umsatz und -Aufwand",
                     "Zwischenergebnisse", "Waehrungsdifferenzen"],
            "task": "Stelle die konzerninternen Forderungen und "
                    "Verbindlichkeiten je Gesellschaftspaar gegenueber und "
                    "weise alle Abstimmdifferenzen mit Betrag und Waehrung aus. "
                    "Ergaenze IC-Umsatz und -Aufwand je Paar und markiere "
                    "Differenzen ueber einer Wesentlichkeitsgrenze, die du "
                    "nennst.",
        },
        "en": {
            "title": "Group consolidation and intercompany reconciliation",
            "desc": "Reconciliation of intercompany receivables, payables, "
                    "revenue and expense between entities – every difference "
                    "delays the consolidated financial statements.",
            "kpis": ["IC receivables and payables per pair",
                     "Reconciliation differences", "IC revenue and expense",
                     "Unrealised profits", "Currency differences"],
            "task": "Contrast intercompany receivables and payables per entity "
                    "pair and show all reconciliation differences with amount "
                    "and currency. Add IC revenue and expense per pair and flag "
                    "differences above a materiality threshold that you state.",
        },
    },
    {
        "id": "iks_sod", "cat": "governance",
        "sources": "BKPF (Buchungskopf), CDHDR/CDPOS (Aenderungsbelege), LFBK (Bankdaten), USR02/AGR_USERS (Rollen)",
        "de": {
            "title": "IKS & Compliance: Funktionstrennung und Auffaelligkeiten",
            "desc": "Kontrollpunkte des internen Kontrollsystems (§ 91 Abs. 3 "
                    "AktG): verletzte Funktionstrennung, Buchungen ausserhalb "
                    "der Geschaeftszeiten, geaenderte Lieferanten-Bankdaten – "
                    "die klassischen Indikatoren fuer doloses Handeln.",
            "kpis": ["Verstoesse gegen Funktionstrennung",
                     "Buchungen ausserhalb Geschaeftszeiten/am Wochenende",
                     "Aenderungen an Lieferanten-Bankverbindungen",
                     "Manuelle Buchungen ueber Schwellwert",
                     "Doppelte Rechnungen", "Runde Betraege"],
            "task": "Pruefe die letzten sechs Monate auf Kontrollauffaellig"
                    "keiten: Faelle, in denen derselbe Benutzer Lieferant "
                    "angelegt und Zahlung gebucht hat; Buchungen ausserhalb der "
                    "Geschaeftszeiten oder am Wochenende; Aenderungen an "
                    "Lieferanten-Bankverbindungen mit anschliessender Zahlung; "
                    "moegliche Doppelrechnungen (gleicher Lieferant, Betrag, "
                    "Rechnungsdatum). Ordne jeden Befund nach Risiko und nenne "
                    "Beleg und Benutzer.",
        },
        "en": {
            "title": "Internal controls and compliance: segregation of duties",
            "desc": "Control points of the internal control system: violated "
                    "segregation of duties, postings outside business hours, "
                    "changed vendor bank details – the classic indicators of "
                    "fraudulent activity.",
            "kpis": ["Segregation of duties violations",
                     "Postings outside business hours/at weekends",
                     "Changes to vendor bank details",
                     "Manual postings above threshold",
                     "Duplicate invoices", "Round amounts"],
            "task": "Check the last six months for control anomalies: cases "
                    "where the same user created a vendor and posted a payment; "
                    "postings outside business hours or at weekends; changes to "
                    "vendor bank details followed by a payment; possible "
                    "duplicate invoices (same vendor, amount, invoice date). "
                    "Rank each finding by risk and name document and user.",
        },
    },
    {
        "id": "tax_vat", "cat": "governance",
        "sources": "BSET (Steuerdaten), BKPF/BSEG, T007A (Steuerkennzeichen), EKPO/VBRP (Intrastat)",
        "de": {
            "title": "Umsatzsteuer & Intrastat",
            "desc": "Steuerbemessungsgrundlagen und Steuerbetraege je "
                    "Steuerkennzeichen als Kontrolle der Voranmeldung, dazu die "
                    "innergemeinschaftlichen Warenbewegungen fuer Intrastat und "
                    "die Zusammenfassende Meldung.",
            "kpis": ["Bemessungsgrundlage je Steuerkennzeichen",
                     "Steuerbetrag Ausgangs-/Eingangsseite", "Vorsteuerueberhang",
                     "Innergemeinschaftliche Lieferungen und Erwerbe",
                     "Belege ohne gueltige USt-IdNr."],
            "task": "Ermittle je Steuerkennzeichen und Periode "
                    "Bemessungsgrundlage und Steuerbetrag getrennt nach "
                    "Ausgangs- und Eingangsseite fuer die letzten vier "
                    "Voranmeldungszeitraeume. Weise innergemeinschaftliche "
                    "Lieferungen und Erwerbe je Land aus und liste Belege ohne "
                    "gueltige Umsatzsteuer-Identifikationsnummer.",
        },
        "en": {
            "title": "VAT and Intrastat",
            "desc": "Tax bases and tax amounts per tax code as a check on the "
                    "VAT return, plus intra-community movements of goods for "
                    "Intrastat and the EC sales list.",
            "kpis": ["Tax base per tax code", "Output/input tax amount",
                     "Input tax surplus",
                     "Intra-community supplies and acquisitions",
                     "Documents without valid VAT ID"],
            "task": "Determine tax base and tax amount per tax code and period, "
                    "split into output and input side, for the last four filing "
                    "periods. Show intra-community supplies and acquisitions per "
                    "country and list documents without a valid VAT "
                    "identification number.",
        },
    },
    {
        "id": "esg_csrd", "cat": "governance",
        "sources": "MSEG (Verbrauchsmengen), EKPO (Beschaffung), ANLA (Fuhrpark/Anlagen), LFA1 (Lieferantenlaender)",
        "de": {
            "title": "ESG-/CSRD-Kennzahlen aus SAP-Daten",
            "desc": "Die aus SAP ableitbaren Bausteine der "
                    "Nachhaltigkeitsberichterstattung: Energie- und "
                    "Materialverbraeuche, Abfall, Fuhrpark sowie die "
                    "Laenderstruktur der Lieferkette (Sorgfaltspflichten).",
            "kpis": ["Energieverbrauch je Standort", "Materialeinsatz",
                     "Abfallmengen", "Fuhrpark und Kraftstoffverbrauch",
                     "Beschaffungsvolumen je Land",
                     "Anteil Lieferanten in Risikolaendern"],
            "task": "Leite aus den Bewegungs- und Beschaffungsdaten die in SAP "
                    "verfuegbaren Nachhaltigkeitskennzahlen ab: Energie- und "
                    "Materialverbrauch je Werk, Abfallmengen, Fuhrpark und "
                    "Beschaffungsvolumen je Lieferantenland. Sage ausdruecklich, "
                    "welche der ueblichen ESRS-Angaben sich aus diesem System "
                    "NICHT ableiten lassen.",
        },
        "en": {
            "title": "ESG/CSRD key figures from SAP data",
            "desc": "The sustainability reporting building blocks that can be "
                    "derived from SAP: energy and material consumption, waste, "
                    "vehicle fleet and the country structure of the supply "
                    "chain (due diligence).",
            "kpis": ["Energy consumption per site", "Material input",
                     "Waste volumes", "Fleet and fuel consumption",
                     "Spend per country", "Share of vendors in risk countries"],
            "task": "Derive the sustainability figures available in SAP from "
                    "movement and procurement data: energy and material "
                    "consumption per plant, waste volumes, vehicle fleet and "
                    "spend per vendor country. State explicitly which of the "
                    "usual ESRS disclosures cannot be derived from this system.",
        },
    },
    {
        "id": "forecast_deviation", "cat": "governance",
        "sources": "ACDOCA (Ist), Plandaten/COSP, VBAK (Auftragseingang), CE1*",
        "de": {
            "title": "Prognoseabweichung & Ad-hoc-Frueherkennung",
            "desc": "Laufender Abgleich von Ist und Prognose. Weicht das "
                    "erwartete Jahresergebnis wesentlich von der "
                    "veroeffentlichten Prognose ab, kann daraus eine "
                    "Ad-hoc-Pflicht nach Art. 17 MAR entstehen – diese Analyse "
                    "soll das FRUEH sichtbar machen, sie ersetzt keine "
                    "rechtliche Bewertung.",
            "kpis": ["Ist kumuliert gegen Plan", "Hochrechnung Jahresende",
                     "Abweichung zur Prognose in Prozent",
                     "Auftragseingang als Fruehindikator",
                     "Trend der letzten drei Monate"],
            "task": "Vergleiche das kumulierte Ist mit dem Plan fuer Umsatz und "
                    "EBIT, rechne auf das Jahresende hoch (linear und "
                    "auftragsbestandsgestuetzt) und weise die prozentuale "
                    "Abweichung zur Planung aus. Markiere Abweichungen ueber "
                    "zehn Prozent ausdruecklich als pruefbeduerftig und weise "
                    "darauf hin, dass die rechtliche Bewertung einer "
                    "Ad-hoc-Pflicht nicht Sache dieser Auswertung ist.",
        },
        "en": {
            "title": "Guidance deviation and early warning",
            "desc": "Continuous comparison of actuals and forecast. If the "
                    "expected annual result deviates materially from published "
                    "guidance, a disclosure obligation may arise – this analysis "
                    "surfaces it EARLY, it does not replace a legal assessment.",
            "kpis": ["Cumulative actual vs. plan", "Year-end projection",
                     "Deviation from guidance in percent",
                     "Order intake as leading indicator",
                     "Trend of the last three months"],
            "task": "Compare cumulative actuals with plan for revenue and EBIT, "
                    "project to year end (linear and backlog-based) and show the "
                    "percentage deviation from plan. Explicitly flag deviations "
                    "above ten percent as requiring review and note that the "
                    "legal assessment of any disclosure obligation is not part "
                    "of this analysis.",
        },
    },
]

# ── BI-/Reporting-Werkzeuge fuer das Pulldown ──────────────────────────────
# ``iface`` verweist auf die Schnittstellenart, ueber die das Werkzeug liest –
# damit die Oberflaeche die passenden Verbindungsangaben aus
# ``sap_client.reporting_endpoints()`` zuordnen kann. ``export`` beschreibt dem
# Agenten, in welcher Form er das Ergebnis aufbereiten soll.
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


BI_TOOLS: list[dict] = [
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
        "id": "powerbi", "name": "Microsoft Power BI", "iface": "OData Feed",
        "export": "Bereite das Ergebnis so auf, dass es in Power BI "
                  "weiterverwendbar ist: flache Tabelle mit eindeutigen "
                  "Spaltennamen ohne Leerzeichen, ein Datensatz je Zeile, "
                  "Datumsangaben im Format JJJJ-MM-TT. Nenne am Ende die "
                  "OData-Entitaeten, aus denen die Daten stammen.",
        "export_en": "Prepare the result for reuse in Power BI: flat table "
                     "with unique column names without spaces, one record per "
                     "row, dates as YYYY-MM-DD. Name the OData entities the "
                     "data came from at the end.",
    },
    {
        "id": "tableau", "name": "Tableau", "iface": "OData Feed",
        "export": "Bereite das Ergebnis als flache Tabelle im Langformat auf "
                  "(je Zeile eine Auspraegung mit Dimension, Kennzahl und "
                  "Wert) – so laesst es sich in Tableau ohne Umbau verwenden.",
        "export_en": "Prepare the result as a flat table in long format (one "
                     "row per combination of dimension, measure and value) so "
                     "it can be used in Tableau without reshaping.",
    },
    {
        "id": "qlik", "name": "Qlik Sense", "iface": "OData Feed",
        "export": "Bereite das Ergebnis als flache Tabelle auf und nenne "
                  "zusaetzlich die Schluesselfelder, ueber die sich die "
                  "Tabellen im Qlik-Datenmodell verknuepfen lassen.",
        "export_en": "Prepare the result as a flat table and additionally name "
                     "the key fields by which the tables can be linked in the "
                     "Qlik data model.",
    },
    {
        "id": "excel", "name": "Microsoft Excel", "iface": "OData Feed",
        "export": "Bereite das Ergebnis als Tabelle mit Kopfzeile auf, "
                  "Zahlenwerte ohne Tausenderpunkte und mit Punkt als "
                  "Dezimaltrenner, damit es sich direkt nach Excel kopieren "
                  "laesst. Ergaenze eine Summenzeile.",
        "export_en": "Prepare the result as a table with a header row, numbers "
                     "without thousand separators and a dot as decimal "
                     "separator so it can be pasted straight into Excel. Add a "
                     "totals row.",
    },
    {
        "id": "sac", "name": "SAP Analytics Cloud", "iface": "SAP HANA (SQL/ODBC/JDBC)",
        "export": "Bereite das Ergebnis modellgerecht auf: trenne Dimensionen "
                  "und Kennzahlen und nenne je Kennzahl die Aggregations"
                  "vorschrift (Summe, Durchschnitt, Endbestand).",
        "export_en": "Prepare the result in model form: separate dimensions and "
                     "measures and state the aggregation rule per measure (sum, "
                     "average, closing balance).",
    },
    {
        "id": "bo", "name": "SAP BusinessObjects", "iface": "SAP BW / RFC / BEx",
        "export": "Bereite das Ergebnis so auf, dass es einer "
                  "Web-Intelligence-Abfrage entspricht: Dimensionen zuerst, "
                  "danach die Kennzahlen, je Zeile eine Auspraegung.",
        "export_en": "Prepare the result to match a Web Intelligence query: "
                     "dimensions first, then measures, one row per combination.",
    },
    {
        "id": "grafana", "name": "Grafana", "iface": "SAP HANA (SQL/ODBC/JDBC)",
        "export": "Bereite das Ergebnis als Zeitreihe auf: erste Spalte "
                  "Zeitstempel (JJJJ-MM-TT), danach je Kennzahl eine Spalte. "
                  "Nenne die SQL-Abfrage, mit der sich die Reihe erzeugen "
                  "laesst.",
        "export_en": "Prepare the result as a time series: first column "
                     "timestamp (YYYY-MM-DD), then one column per measure. Name "
                     "the SQL query that produces the series.",
    },
]


# ── Zugriff ────────────────────────────────────────────────────────────────
def _lang(lang: str) -> str:
    """Normalisiert die Sprachangabe. Alles ausser ``en`` ist Deutsch – die
    Oberflaeche kennt nur zwei Sprachen, und ein unbekanntes Kuerzel darf keine
    leere Liste liefern."""
    return "en" if str(lang or "").strip().lower().startswith("en") else "de"


def normalize_hidden(value) -> list[str]:
    """Macht aus einem gespeicherten Wert eine saubere Liste von Analyse-Ids.

    Nimmt Liste ODER kommagetrennten Text an (eine handgeschriebene
    settings.json darf den Bereich nicht lahmlegen) und **verwirft unbekannte
    Ids, statt sie zu raten**. Das ist wichtig, wenn eine Analyse aus dem
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
    """Liefert Kategorien, Analysen und BI-Werkzeuge in EINER Sprache.

    Die Oberflaeche bekommt bewusst nur die aktive Sprache – sie soll nicht
    selbst zwischen ``de`` und ``en`` waehlen muessen (zwei Auswahlstellen
    laufen erfahrungsgemaess auseinander).

    ``hidden`` sind die vom Administrator ausgeblendeten Analyse-Ids
    (*Einstellungen → SAP*). Sie fallen hier heraus – **und ebenso jede
    Kategorie, die dadurch leer wird**: eine Gruppenueberschrift ohne Eintraege
    sieht im Pulldown wie ein Fehler aus.

    ``hidden=None`` bedeutet "nichts ausgeblendet", NICHT "nichts sichtbar".
    Das ist Absicht und der Unterschied zu einer Berechtigung: wer den Bereich
    betreten darf, hat die Freigabe bereits; dies hier ist nur eine
    Aufraeum-Einstellung. Waere leer = nichts, stuende nach dem Einschalten
    des Skills ein leeres Pulldown da, und eine spaeter ergaenzte Analyse waere
    still unsichtbar."""
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
             for b in BI_TOOLS]
    return {"lang": lg, "categories": cats, "analyses": items, "bi_tools": tools}


def admin_catalog(lang: str = "de", hidden=None) -> dict:
    """Vollstaendiger Katalog MIT Sichtbarkeitsmerker – fuer den Reiter
    *Einstellungen → SAP*.

    Bewusst getrennt von ``catalog()``: dort darf eine ausgeblendete Analyse
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
    """True, wenn die Analyse vom Administrator ausgeblendet wurde."""
    return analysis_id in set(normalize_hidden(hidden))


def find(analysis_id: str) -> dict | None:
    """Sucht eine Analyse nach Id (None, wenn unbekannt)."""
    for a in ANALYSES:
        if a["id"] == analysis_id:
            return a
    return None


def find_tool(tool_id: str) -> dict | None:
    """Sucht ein BI-Werkzeug nach Id (None, wenn unbekannt)."""
    for b in BI_TOOLS:
        if b["id"] == tool_id:
            return b
    return None


def build_task(analysis_id: str = "", question: str = "", tool_id: str = "",
               instructions: str = "", lang: str = "de") -> str:
    """Baut den Arbeitsauftrag fuer den Agenten aus Vorlage, Freitext,
    Ziel-Werkzeug und den persoenlichen Anweisungen des Benutzers.

    Reihenfolge ist Absicht: erst der allgemeine Vorspann (Read-Only,
    Vorgehen), dann die Vorlage, dann die konkrete Frage, dann die
    Aufbereitung fuer das Zielwerkzeug, zuletzt die persoenlichen Anweisungen –
    Spaeteres praezisiert Frueheres.

    Gibt einen leeren String zurueck, wenn weder Vorlage noch Frage vorliegen;
    der Aufrufer entscheidet dann ueber die Fehlermeldung."""
    lg = _lang(lang)
    parts: list[str] = [_PREAMBLE_EN if lg == "en" else _PREAMBLE_DE]

    a = find(analysis_id) if analysis_id else None
    if a:
        t = a[lg]
        head = "ANALYSIS" if lg == "en" else "ANALYSE"
        src = "Usual SAP sources" if lg == "en" else "Uebliche SAP-Quellen"
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
