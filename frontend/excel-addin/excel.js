/* ═══════════════════════════════════════════════════════════════════════
   Excel-Add-in – Aufgabenfenster
   ───────────────────────────────────────────────────────────────────────
   Ein Chat auf die gerade geoeffnete Arbeitsmappe.

   DIE VIER DINGE, DIE HIER ANDERS SIND ALS IM OUTLOOK-ADD-IN:

   1. **Kein SSO – die Anmeldemaske ist der REGELFALL, nicht der Rueckfall.**
      Das Outlook-Fenster meldet sich kennwortlos ueber das
      Exchange-Identity-Token an; das ist eine Mailbox-API und in Excel nicht
      vorhanden.

      HIER STAND ZUNAECHST, ein bestehender Jarvis-Login im Browser genuege –
      das ist fuer Excel am Arbeitsplatz FALSCH: das Aufgabenfenster laeuft
      dort in einer eigenen WebView2-Instanz (Mac: WKWebView) mit **eigenem
      localStorage**. Chrome und Edge sind andere Profile, ihre Anmeldung gilt
      hier nicht. `token()` findet beim ersten Start also nichts, und das ist
      der Normalfall – nicht der Fehlerfall.

      Nur in **Excel im Web** ist das Fenster ein iframe im echten Browser mit
      dem Origin dieses Servers; dort greift die vorhandene Anmeldung ueber
      denselben localStorage – sofern der Browser Speicher fremder Herkunft
      nicht sperrt. Genau dafuer gibt es weiter unten `_tokenRam`.

   2. **Der Ueberblick wird bei JEDER Frage frisch gelesen.** Die Mappe
      aendert sich, waehrend das Fenster offen ist – ein einmal gelesener
      Stand waere nach der ersten Bearbeitung falsch.

   3. **Struktur statt Rohdaten.** Gesendet werden Blattnamen, Dimensionen,
      Kopfzeilen, Datentypen und wenige Beispielzeilen – plus die AUSWAHL
      des Benutzers vollstaendig. Ein ganzes Blatt waere bei einer echten
      Mappe sechsstellig viele Zellen; das Modell saehe davon einen
      Ausschnitt und antwortete darauf (am 2026-08-19 im Projekt gemessen:
      0,4 %, mit plausibel aussehenden falschen Zahlen als Ergebnis).

   4. **Geschrieben wird NUR hier und nur nach Bestaetigung.** Der Server
      schlaegt vor; jede Zelle wird mit altem und neuem Inhalt angezeigt.

   Der Server bleibt die Schranke: /api/excel/ask haengt an
   require_excel_access, der Lauf ist unprivilegiert, und die Formel-
   Sperrliste greift, bevor ein Vorschlag ueberhaupt hier ankommt. Alles
   hier ist Benutzerfuehrung.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    /* Gleiche Kette wie addin.js/email_portal.js. Geschrieben wird auf den
       ersten Schluessel – ein eigener Schluessel wuerde bedeuten, dass man
       sich zweimal anmeldet, obwohl es derselbe Server ist. */
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
    var OFFICE_WARTE_MS = 4000;   // danach gilt: kein Excel-Kontext
    /* Nachforderungs-Deckel. MASSGEBLICH IST DER SERVER: er liefert ihn mit
       jeder Antwort als `max_runden` (aus der Skill-Konfiguration, im
       Admin-Reiter einstellbar). Die Zahl hier ist nur der Rueckfall fuer eine
       Antwort ohne das Feld – eine zweite, fest verdrahtete Quelle fuer
       denselben Deckel war die Drift, die dieser Umbau beseitigt hat. */
    var MAX_RUNDEN_VORGABE = 3;   // = excel_ask.MAX_RUNDEN_VORGABE

    var _office = false;      // Excel-Kontext vorhanden
    var _officeGrund = '';
    var _kann19 = false;      // ExcelApi 1.9 (copyFrom/autoFill/getSpecialCells)
    var _kann110 = false;     // ExcelApi 1.10 (Zellkommentare)
    /* Markierung geschriebener Zellen. Ohne sie weiss nach 30 geaenderten
       Zellen niemand mehr, welche der Assistent angefasst hat – und bei
       automatischer Uebernahme sieht man die Aenderung ueberhaupt nur an den
       Zahlen. Vorgabe AN; abschaltbar, weil eine Markierung in einer Mappe,
       die weitergegeben wird, stoeren kann. */
    var MARK_KEY = 'jarvis_xl_markieren';
    var MARK_FARBE = '#FFF2CC';
    var _markRam = null;
    /* Der zuletzt geschriebene Vorschlag mit seinen ALTWERTEN – die Grundlage
       des Rueckwegs. Office.js-Schreibvorgaenge sind NICHT verlaesslich im
       Undo-Stack von Excel: bekannte Faelle leeren ihn sogar (Formatierungen,
       nicht unterstuetzte Aufrufe). Der frueher hier stehende Hinweis "mit
       Strg+Z rueckgaengig" war deshalb eine Zusage, die Excel nicht einloest. */
    var _rueckweg = null;
    var _laeuft = false;
    var _verlauf = [];        // [{rolle:'user'|'bot', text}]
    var _vorschlag = null;    // {aenderungen, abgelehnt, zusammenfassung}
    // Der bereits GESCHRIEBENE Vorschlag bleibt sichtbar stehen. Bei
    // automatischer Uebernahme sieht der Benutzer den Diff sonst NIE – die
    // Zellen aendern sich, und was geaendert wurde, steht nirgends.
    var _erledigt = null;
    var _updServer = '';
    var _ctxKurz = '';        // letzte gelesene Bezugszeile

    function $(id) { return document.getElementById(id); }
    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    /* Rueckfall im Arbeitsspeicher. NOETIG, nicht vorsorglich: das
       Aufgabenfenster laeuft in Excel im Web in einem iframe, und dort ist
       Speicher fremder Herkunft je nach Browsereinstellung gesperrt. Ohne
       diesen Rueckfall scheitert `localStorage.setItem` still, `start()`
       findet keinen Token und zeigt wieder die Anmeldung – eine
       Endlosschleife mit RICHTIGEM Kennwort und ohne Fehlermeldung. */
    var _tokenRam = '';
    var _speicherGeht = true;

    /* Automatische Uebernahme. VORGABE AN (Vorgabe des Nutzers). Der
       Rueckfall im Arbeitsspeicher ist derselbe Grund wie beim Token: im
       iframe von Excel im Web kann `localStorage` gesperrt sein.
       Gepruefft wird auf die Zeichenkette '0' – ein FEHLENDER Wert heisst
       "noch nie entschieden" und damit AN, nicht AUS. */
    var AUTO_KEY = 'jarvis_xl_autoapply';
    var _autoRam = null;      // null = nichts entschieden
    function autoAn() {
        try {
            var v = localStorage.getItem(AUTO_KEY);
            if (v !== null) return v !== '0';
        } catch (e) { _speicherGeht = false; }
        return _autoRam === null ? true : _autoRam;
    }
    function autoSetzen(an) {
        _autoRam = !!an;
        try { localStorage.setItem(AUTO_KEY, an ? '1' : '0'); }
        catch (e) { _speicherGeht = false; }
    }

    function markAn() {
        try {
            if (!_speicherGeht) return _markRam !== '0';
            var v = localStorage.getItem(MARK_KEY);
            return v !== '0';
        } catch (e) { return _markRam !== '0'; }
    }
    function markSetzen(an) {
        var v = an ? '1' : '0';
        _markRam = v;
        try { localStorage.setItem(MARK_KEY, v); } catch (e) { _speicherGeht = false; }
    }

    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try { var v = localStorage.getItem(TOKEN_KEYS[i]); if (v) return v; }
            catch (e) { _speicherGeht = false; }
        }
        return _tokenRam;
    }
    function tokenSetzen(v) {
        _tokenRam = v || '';
        try { localStorage.setItem(TOKEN_KEYS[0], v); }
        catch (e) { _speicherGeht = false; }
    }
    function tokenLoeschen() {
        _tokenRam = '';
        TOKEN_KEYS.forEach(function (k) {
            try { localStorage.removeItem(k); } catch (e) { }
        });
    }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function melde(id, text, art) {
        var e = $(id);
        if (!e) return;
        e.textContent = text || '';
        e.style.color = art === 'ok' ? 'var(--success)'
            : art === 'fehler' ? 'var(--danger)' : 'var(--text-muted)';
    }

    /* ── Bestaetigung ──────────────────────────────────────────────────
       Ersetzt window.confirm: in Office-Aufgabenfenstern ist es je nach Host
       unterdrueckt und liefert dann keinen Wert – ein `if (!confirm(...))
       return;` bricht WORTLOS ab (im Projekt am 2026-08-19 gemeldet).
       Fehlt das Markup, wird mit `true` aufgeloest: der Benutzer hat den Knopf
       schon gedrueckt, und "tut wortlos nichts" waere genau der Fehler, den
       dieser Dialog behebt. */
    function frage(text, jaText, gefahr) {
        return new Promise(function (aufloesen) {
            var box = $('xl-ask'), txt = $('xl-ask-text');
            var ja = $('xl-ask-yes'), nein = $('xl-ask-no');
            if (!box || !txt || !ja || !nein) { aufloesen(true); return; }
            txt.textContent = text || '';
            ja.textContent = jaText || T('addin.ask_yes', 'Ja');
            ja.className = 'xl-btn' + (gefahr ? ' xl-btn-danger' : ' xl-btn-primary');
            box.classList.remove('hidden');
            // Fokus auf ABBRECHEN, damit Enter nicht versehentlich schreibt.
            nein.focus();

            function schliessen(wert) {
                box.classList.add('hidden');
                ja.onclick = null; nein.onclick = null;
                document.removeEventListener('keydown', taste);
                box.onclick = null;
                aufloesen(wert);
            }
            function taste(e) {
                if (e.key === 'Escape') { e.preventDefault(); schliessen(false); }
            }
            ja.onclick = function () { schliessen(true); };
            nein.onclick = function () { schliessen(false); };
            box.onclick = function (e) { if (e.target === box) schliessen(false); };
            document.addEventListener('keydown', taste);
        });
    }

    /* ── Server ────────────────────────────────────────────────────────── */
    function sende(url, methode, daten) {
        return fetch(url, {
            method: methode,
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: daten === undefined ? undefined : JSON.stringify(daten)
        }).then(function (r) {
            if (r.status === 401) {
                tokenLoeschen();
                zeigeLogin(T('addin.session_over',
                    'Die Anmeldung ist abgelaufen. Bitte erneut anmelden.'));
                throw new Error('401');
            }
            return r.json().catch(function () { return {}; }).then(function (d) {
                if (!r.ok || d.ok === false) {
                    throw new Error(d.error || d.detail || d.message || ('HTTP ' + r.status));
                }
                return d;
            });
        });
    }

    /* ── Office / Excel ────────────────────────────────────────────────── */
    function officeErmitteln() {
        // Office.js kommt aus dem Netz von Microsoft und wird mit `async`
        // geladen – es kann also NACH dieser Pruefung eintreffen. Deshalb im
        // Takt warten statt einmal nachzusehen.
        return new Promise(function (aufloesen) {
            var start = Date.now();
            (function pruefe() {
                if (window.Office && Office.onReady) {
                    Office.onReady(function (info) {
                        if (info && info.host === Office.HostType.Excel) {
                            _office = true;
                            try {
                                _kann19 = !!(Office.context && Office.context.requirements &&
                                    Office.context.requirements.isSetSupported('ExcelApi', '1.9'));
                            } catch (e) { _kann19 = false; }
                            // Zellkommentare brauchen ExcelApi 1.10, das
                            // Manifest verlangt 1.7. Fehlt die Fassung, bleibt
                            // die farbige Markierung – sie allein sagt schon,
                            // WELCHE Zellen der Assistent angefasst hat, und
                            // das ist der wesentliche Teil.
                            try {
                                _kann110 = !!(Office.context && Office.context.requirements &&
                                    Office.context.requirements.isSetSupported('ExcelApi', '1.10'));
                            } catch (e) { _kann110 = false; }
                        } else {
                            _officeGrund = T('xl.no_excel',
                                'Dieses Fenster läuft nicht in Excel. Die Tabellenfunktionen stehen deshalb nicht zur Verfügung.');
                        }
                        aufloesen();
                    });
                    return;
                }
                if (Date.now() - start > OFFICE_WARTE_MS) {
                    _officeGrund = T('xl.no_office',
                        'Die Excel-Verbindung (office.js von Microsoft) konnte nicht geladen werden – vermutlich sperrt das Netz den Zugriff. Ohne sie kann der Assistent die Tabelle nicht lesen.');
                    aufloesen();
                    return;
                }
                setTimeout(pruefe, 100);
            })();
        });
    }

    /* Liest den STRUKTURELLEN Ueberblick der Mappe plus die Auswahl.

       Bewusst NICHT das ganze Blatt: bei einer echten Mappe sind das
       hunderttausende Zellen. Gelesen werden je Blatt Dimension, Kopfzeile,
       Datentypen und bis zu vier Beispielzeilen – das bleibt klein, egal wie
       gross die Mappe ist. */
    /* ── Ueberblick ueber die Mappe ─────────────────────────────────────
       Was hier NICHT gelesen wird, kann das Modell nicht wissen. Bis
       2026-09-08 waren es Werte, 5 Zeilen vom oberen Rand und `valueTypes` –
       ohne Formeln, ohne Zahlenformate, ohne Spaltenbuchstaben. Ein
       Rechenmodell war damit strukturell unverstehbar: auf "warum ist C42
       falsch?" sah das Modell die ZAHL, nicht `=B42*C$3`.

       DIE ROHWERTE GEHEN JETZT UNGEWANDELT HINAUS. Das frueher hier stehende
       `String(z)` war der Typverlust: das Backend konnte Zahl und Text nicht
       unterscheiden und musste den Datentyp aus `valueTypes` der ZWEITEN Zeile
       raten – bei einer Mappe mit zwei Kopfzeilen also aus einer
       Beschriftungszeile. JSON traegt Zahlen als Zahlen; die Erkennung von
       Kopfzeile und Datenanfang liegt seither im Backend
       (`backend/tabellenkopf.py`, dieselbe Regel wie beim Datei-Weg). */

    /* Wie viele Blaetter die AUSFUEHRLICHE Probe bekommen. Bei 30 Blaettern
       waeren 30 x 12 x 40 Zellen mit Wert, Formel und Format eine Antwort von
       ueber hundert Kilobyte – in Excel im Web ueber eine Firmenleitung
       merkbar. Priorisiert wird nach Relevanz (aktives Blatt, Blatt der
       Auswahl), die uebrigen liefern ihren Umriss; das Backend sagt im
       Ueberblick, dass Details fehlen, damit das Modell nachfordern kann. */
    var DETAIL_BLAETTER = 8;
    var PROBE_ZEILEN = 12;     // Suchtiefe der Kopfzeilen-Erkennung
    var PROBE_SPALTEN = 40;
    var UNTEN_ZEILEN = 3;      // Zeilen vom unteren Rand (Summenzeilen!)
    var MAX_FEHLER = 30;

    function ueberblickLesen() {
        if (!_office || !window.Excel) return Promise.resolve(null);
        return Excel.run(function (ctx) {
            var wb = ctx.workbook;
            wb.load('name');
            var blaetter = wb.worksheets;
            blaetter.load('items/name');
            var aktiv = wb.worksheets.getActiveWorksheet();
            aktiv.load('name');
            var sel = wb.getSelectedRange();
            sel.load('address,rowCount,columnCount');
            var selBlatt = sel.worksheet;
            selBlatt.load('name');
            /* Benannte Bereiche. Ein Modell, das `Steuersatz` nicht kennt,
               kann keine Formel damit schreiben – es schreibt die ZAHL hinein,
               und die Mappe verliert ihre eine Stellschraube. */
            var namen = null;
            try { namen = wb.names; namen.load('items/name,items/formula'); }
            catch (e) { namen = null; }

            return ctx.sync().then(function () {
                var ergebnis = {
                    name: wb.name || '',
                    aktiv: aktiv.name || '',
                    namen: [],
                    blaetter: [],
                    auswahl: null
                };
                if (namen && namen.items) {
                    namen.items.slice(0, 40).forEach(function (n) {
                        ergebnis.namen.push({ name: n.name || '', bezug: n.formula || '' });
                    });
                }

                /* REIHENFOLGE IST EINE ENTSCHEIDUNG: aktives Blatt und Blatt
                   der Auswahl zuerst. Sie sind die Blaetter, auf die sich eine
                   Frage in aller Regel bezieht – und nur die ersten
                   DETAIL_BLAETTER bekommen Formeln und untere Zeilen. */
                var vorrang = {};
                if (aktiv.name) vorrang[aktiv.name] = 1;
                if (selBlatt.name) vorrang[selBlatt.name] = 1;
                var namensliste = blaetter.items.map(function (b) { return b.name; });
                var geordnet = namensliste.filter(function (n) { return vorrang[n]; })
                    .concat(namensliste.filter(function (n) { return !vorrang[n]; }));

                var infos = [];
                geordnet.slice(0, 30).forEach(function (bname, idx) {
                    var s = ctx.workbook.worksheets.getItem(bname);
                    var u = s.getUsedRangeOrNullObject();
                    u.load('address,rowCount,columnCount,rowIndex,columnIndex,isNullObject');
                    var tabs = null;
                    try { tabs = s.tables; tabs.load('items/name'); } catch (e) { tabs = null; }
                    infos.push({
                        name: bname, used: u, sheet: s, tabs: tabs,
                        detail: idx < DETAIL_BLAETTER
                    });
                });

                // Auswahl vollstaendig (bis zu einer Grenze) – das ist der
                // Ausschnitt, den der Benutzer selbst gewaehlt hat, und der
                // wichtigste Kontext ueberhaupt.
                var selWerte = null;
                if (sel.rowCount && sel.rowCount <= 50 && sel.columnCount <= 30) {
                    selWerte = sel;
                    sel.load('values,formulas');
                }

                return ctx.sync().then(function () {
                    infos.forEach(function (i) {
                        var eintrag = { name: i.name };
                        if (i.used.isNullObject) {
                            eintrag.bereich = ''; eintrag.zeilen = 0; eintrag.spalten = 0;
                            ergebnis.blaetter.push(eintrag);
                            i.eintrag = eintrag;
                            return;
                        }
                        eintrag.bereich = i.used.address || '';
                        eintrag.zeilen = i.used.rowCount;
                        eintrag.spalten = i.used.columnCount;
                        // OHNE DIESE ZWEI ZAHLEN KANN DAS MODELL KEINE ADRESSE
                        // BILDEN. Beginnt der benutzte Bereich bei C3, ist die
                        // dritte Spalte E – wer ab A zaehlt, schreibt in die
                        // falsche Spalte, und die Diff-Ansicht kann das nicht
                        // zeigen (dort steht die gemeinte Adresse).
                        eintrag.zeile_ab = (i.used.rowIndex || 0) + 1;
                        eintrag.spalte_ab = (i.used.columnIndex || 0) + 1;
                        ergebnis.blaetter.push(eintrag);
                        i.eintrag = eintrag;

                        var zeilen = Math.min(i.used.rowCount, PROBE_ZEILEN);
                        var spalten = Math.min(i.used.columnCount, PROBE_SPALTEN);
                        i.probe = i.sheet.getRangeByIndexes(
                            i.used.rowIndex, i.used.columnIndex, zeilen, spalten);
                        i.probe.load('values');
                        if (i.detail) {
                            // Formeln und Zahlenformate nur fuer die Blaetter,
                            // die ausfuehrlich gehen – sie sind der teure Teil
                            // der Antwort.
                            i.probe.load('formulas,numberFormat');
                        }

                        // Untere Zeilen: Summen und Zwischentotale stehen dort.
                        // Nur wenn sie NICHT ohnehin in der Probe liegen –
                        // sonst stuende dieselbe Zeile zweimal im Ueberblick.
                        if (i.detail && i.used.rowCount > PROBE_ZEILEN) {
                            var ab = i.used.rowIndex + i.used.rowCount - UNTEN_ZEILEN;
                            i.unten = i.sheet.getRangeByIndexes(
                                ab, i.used.columnIndex, UNTEN_ZEILEN, spalten);
                            i.unten.load('values,formulas');
                            eintrag.untenAb = ab + 1;
                        }

                        // Fehlerzellen. `getSpecialCellsOrNullObject` braucht
                        // ExcelApi 1.9; ohne die Fassung bleibt der Weg ueber
                        // die Probewerte (unten) – der findet weniger, aber
                        // NICHTS FALSCHES.
                        if (i.detail && _kann19) {
                            try {
                                i.fehler = i.used.getSpecialCellsOrNullObject(
                                    Excel.SpecialCellType.formulas,
                                    Excel.SpecialCellValueType.errors);
                                i.fehler.load('address,isNullObject');
                            } catch (e) { i.fehler = null; }
                        }
                    });

                    return ctx.sync().then(function () {
                        // Dritte Runde: Tabellen-Bereiche brauchen getRange()
                        // auf dem geladenen Table-Objekt.
                        infos.forEach(function (i) {
                            if (!i.tabs || !i.tabs.items || !i.tabs.items.length) return;
                            i.tabRanges = [];
                            i.tabs.items.slice(0, 10).forEach(function (t) {
                                try {
                                    var r = t.getRange(); r.load('address');
                                    i.tabRanges.push({ name: t.name, r: r });
                                } catch (e) { }
                            });
                        });
                        return ctx.sync().then(function () {
                            infos.forEach(function (i) { probeAuswerten(i); });
                            if (selWerte) {
                                ergebnis.auswahl = {
                                    blatt: selBlatt.name || '',
                                    adresse: (sel.address || '').replace(/^.*!/, ''),
                                    zeilen: sel.values || [],
                                    formeln: sel.formulas || []
                                };
                            } else if (sel.address) {
                                // Zu grosse Auswahl: die ADRESSE ist trotzdem eine
                                // Aussage ("er meint diesen Bereich"), die Werte
                                // waeren es nicht mehr.
                                ergebnis.auswahl = {
                                    blatt: selBlatt.name || '',
                                    adresse: (sel.address || '').replace(/^.*!/, ''),
                                    zeilen: [], formeln: []
                                };
                            }
                            return ergebnis;
                        });
                    });
                });
            });
        }).catch(function (e) {
            console.warn('[excel] Ueberblick nicht lesbar:', e);
            return null;
        });
    }

    /* Traegt die gelesenen Proben in den Blatt-Eintrag ein.
       Eigene Funktion, weil sie sonst dreifach verschachtelt in
       `ueberblickLesen` stehen wuerde – und weil sie einzeln pruefbar ist. */
    function probeAuswerten(i) {
        var e = i.eintrag;
        if (!e || !i.probe) return;
        try {
            e.probe = i.probe.values || [];
            if (i.detail) {
                e.probeFormeln = i.probe.formulas || [];
                e.probeFormate = i.probe.numberFormat || [];
            }
        } catch (err) { }
        if (i.unten) {
            try {
                e.unten = i.unten.values || [];
                e.untenFormeln = i.unten.formulas || [];
            } catch (err) { delete e.untenAb; }
        }
        if (i.tabRanges && i.tabRanges.length) {
            e.tabellen = i.tabRanges.map(function (t) {
                var adr = '';
                try { adr = (t.r.address || '').replace(/^.*!/, ''); } catch (err) { }
                return { name: t.name || '', bereich: adr };
            });
        }
        // Fehlerzellen aus BEIDEN Quellen: die Sonderzellen-Abfrage (findet
        // alle, braucht aber 1.9) und die Probewerte (findet nur die
        // gezeigten, dafuer MIT Fehlerwert). Zusammengefuehrt, ohne Dubletten.
        var fehler = [];
        if (i.fehler) {
            try {
                if (!i.fehler.isNullObject && i.fehler.address) {
                    String(i.fehler.address).split(',').forEach(function (a) {
                        var adr = a.replace(/^.*!/, '').trim();
                        if (adr) fehler.push({ adresse: adr, wert: '' });
                    });
                }
            } catch (err) { }
        }
        var werte = e.probe || [];
        for (var z = 0; z < werte.length; z++) {
            if (!werte[z]) continue;
            for (var sp = 0; sp < werte[z].length; sp++) {
                var c = werte[z][sp];
                if (typeof c !== 'string' || !fehlerwert(c)) continue;
                var adr = indexZuSpalte((e.spalte_ab || 1) + sp) + ((e.zeile_ab || 1) + z);
                var da = false;
                for (var k = 0; k < fehler.length; k++) {
                    if (fehler[k].adresse === adr) { fehler[k].wert = c; da = true; break; }
                }
                if (!da) fehler.push({ adresse: adr, wert: c });
            }
        }
        if (fehler.length) e.fehler = fehler.slice(0, MAX_FEHLER);
    }

    /* Fehlerwerte. Geprueft wird gegen eine LISTE, nicht auf '#': eine Zelle
       mit dem Text '#1 Kunde' ist kein Fehler, und eine Fehlerliste, die
       harmlose Texte aufnimmt, macht die Fehlerzeile unbrauchbar. Deutsche und
       englische Schreibweisen, weil Excel sie in der Sprache des Benutzers
       zurueckgibt. Dieselbe Liste steht in `excel_ask._FEHLERWERTE`; der Test
       vergleicht beide (Drift-Schranke). */
    var FEHLERWERTE = ['#NAME?', '#REF!', '#BEZUG!', '#VALUE!', '#WERT!', '#DIV/0!',
        '#N/A', '#NV', '#NUM!', '#ZAHL!', '#NULL!', '#LEER!',
        '#SPILL!', '#UEBERLAUF!', '#CALC!', '#GETTING_DATA'];
    function fehlerwert(w) {
        if (typeof w !== 'string') return false;
        return FEHLERWERTE.indexOf(w.trim().toUpperCase()) >= 0;
    }

    /* Liest einen vom Modell nachgeforderten Bereich ("Blatt!A1:D200"). */
    function bereichLesen(angabe) {
        if (!_office || !window.Excel) return Promise.resolve(null);
        var teile = String(angabe || '').split('!');
        var blattName = teile.length > 1 ? teile[0].replace(/^'|'$/g, '') : '';
        var adresse = teile.length > 1 ? teile[1] : teile[0];
        if (!/^\$?[A-Z]{1,3}\$?\d{1,7}(:\$?[A-Z]{1,3}\$?\d{1,7})?$/i.test(adresse)) {
            return Promise.resolve(null);
        }
        return Excel.run(function (ctx) {
            var s = blattName ? ctx.workbook.worksheets.getItem(blattName)
                : ctx.workbook.worksheets.getActiveWorksheet();
            var r = s.getRange(adresse);
            r.load('address,values,rowCount,columnCount');
            return ctx.sync().then(function () {
                // Deckel: ein nachgeforderter Bereich soll den Auftrag nicht
                // sprengen. Was wegfaellt, wird ausgewiesen – ein stiller
                // Schnitt liesse das Modell auf einem Ausschnitt antworten,
                // ohne es sagen zu koennen.
                var w = r.values || [];
                var gekuerzt = w.length > 200;
                var zeilen = w.slice(0, 200).map(function (z) {
                    return z.map(function (c) { return c === null ? '' : String(c); }).join(' | ');
                });
                var text = zeilen.join('\n');
                if (gekuerzt) {
                    text += '\n… [gekürzt: 200 von ' + w.length + ' Zeilen gezeigt]';
                }
                return { bereich: angabe, text: text };
            });
        }).catch(function (e) {
            console.warn('[excel] Bereich nicht lesbar:', angabe, e);
            return null;
        });
    }

    /* ── Formelbezuege verschieben ──────────────────────────────────────
       WARUM ES DAS GEBEN MUSS: schreibt man in G2:G40 ueberall dieselbe
       Formel `=E2*F2`, steht sie auch in G40 – Excel passt relative Bezuege
       nur beim KOPIEREN an, nicht beim Setzen von `formulas`. Der Kernfall der
       Anforderung ("trage in G2:G40 die Marge ein") waere damit unbrauchbar.

       Ab ExcelApi 1.9 macht `copyFrom` das richtig und wird bevorzugt – dann
       rechnet Excel selbst. Diese Funktion ist der Rueckfall fuer aeltere
       Staende (das Manifest verlangt nur 1.7, damit Excel 2019 es installieren
       kann).

       Strings werden uebersprungen: in `=IF(A1="B2",...)` ist `B2` KEIN Bezug.
       Absolute Anteile (`$`) bleiben unveraendert – genau das ist ihr Zweck. */
    function formelVerschieben(formel, dZeile, dSpalte) {
        if (!formel || (dZeile === 0 && dSpalte === 0)) return formel;
        var aus = '';
        var i = 0;
        while (i < formel.length) {
            var c = formel[i];
            if (c === '"') {                       // Zeichenkette unveraendert
                var j = i + 1;
                while (j < formel.length) {
                    if (formel[j] === '"') {
                        if (formel[j + 1] === '"') { j += 2; continue; }  // "" = escaptes "
                        break;
                    }
                    j++;
                }
                aus += formel.slice(i, Math.min(j + 1, formel.length));
                i = j + 1;
                continue;
            }
            if (c === "'") {
                // Blattname mit Leerzeichen: ='Q1 2026'!A1. Ohne diesen Zweig
                // wuerde "Q1" als Zellbezug gelesen und verschoben – der
                // Blattname waere danach ein anderer (im Test aufgefallen).
                var k = i + 1;
                while (k < formel.length) {
                    if (formel[k] === "'") {
                        if (formel[k + 1] === "'") { k += 2; continue; }
                        break;
                    }
                    k++;
                }
                aus += formel.slice(i, Math.min(k + 1, formel.length));
                i = k + 1;
                continue;
            }
            var rest = formel.slice(i);
            // Bezug: optional $Spalte, optional $Zeile.
            //
            // DAS LOOKAHEAD MUSS DIE OEFFNENDE KLAMMER AUSSCHLIESSEN. Ohne sie
            // liest der Ausdruck `LOG10(` als Bezug – Spalte "LOG", Zeile 10 –
            // und macht beim Verschieben `=LOG11(` daraus. Die Formel ist damit
            // zerstoert, und zwar lautlos (im Test aufgefallen). Einem echten
            // Zellbezug folgt NIE eine Klammer.
            var m = /^(\$?)([A-Za-z]{1,3})(\$?)(\d{1,7})(?![\dA-Za-z_(])/.exec(rest);
            // Ein vorangehender Buchstabe/Ziffer schliesst einen Treffer aus –
            // sonst wuerde mitten in einem Namen verschoben. `!` gehoert
            // AUSDRUECKLICH NICHT dazu: nach `Blatt2!` steht genau der Bezug,
            // der mitwandern muss.
            var davor = i > 0 ? formel[i - 1] : '';
            if (m && !/[A-Za-z0-9_.$]/.test(davor)) {
                var sAbs = m[1] === '$', zAbs = m[3] === '$';
                var sp = spalteZuIndex(m[2]);
                var zl = parseInt(m[4], 10);
                if (!sAbs) sp += dSpalte;
                if (!zAbs) zl += dZeile;
                if (sp < 1 || zl < 1 || sp > 16384 || zl > 1048576) {
                    // Ausserhalb des Blatts – Excel selbst schreibt hier #REF!.
                    aus += '#REF!';
                } else {
                    aus += m[1] + indexZuSpalte(sp) + m[3] + zl;
                }
                i += m[0].length;
                continue;
            }
            aus += c;
            i++;
        }
        return aus;
    }

    function spalteZuIndex(b) {
        var w = 0;
        b = b.toUpperCase();
        for (var i = 0; i < b.length; i++) w = w * 26 + (b.charCodeAt(i) - 64);
        return w;
    }
    function indexZuSpalte(n) {
        var s = '';
        while (n > 0) {
            var r = (n - 1) % 26;
            s = String.fromCharCode(65 + r) + s;
            n = Math.floor((n - 1) / 26);
        }
        return s;
    }

    /* ── Chat ──────────────────────────────────────────────────────────── */
    function zeichneVerlauf() {
        var box = $('xl-chat');
        if (!box) return;
        var html = _verlauf.map(function (m) {
            if (m.rolle === 'user') {
                return '<div class="xl-msg xl-msg-user">' + esc(m.text) + '</div>';
            }
            if (m.rolle === 'wait') {
                return '<div class="xl-msg xl-msg-wait">' + esc(m.text) + '</div>';
            }
            return '<div class="xl-msg xl-msg-bot' + (m.fehler ? ' xl-msg-err' : '') +
                '">' + esc(m.text) + '</div>';
        }).join('');
        // Erst der erledigte, dann der offene Vorschlag – zeitliche Folge.
        if (_erledigt) html += diffHtml(_erledigt, true);
        if (_vorschlag) html += diffHtml(_vorschlag);
        box.innerHTML = html;
        // ⚠ AUCH BEIM ERLEDIGTEN VORSCHLAG BINDEN. Bis 2026-09-08 stand hier
        // `if (_vorschlag)` – damals gab es im erledigten Diff keine Knoepfe.
        // Seit dem Rueckweg (P2.12) und dem Sprung zur Zelle (P2.13) gibt es
        // sie: ohne diese Zeile ist der "Zuruecknehmen"-Knopf SICHTBAR und
        // UNVERDRAHTET – ein Klick tut nichts, und zwar bei der einzigen
        // Funktion, die eine automatisch geschriebene Aenderung zurueckholt.
        // Vom UI-Waechter gefunden, nicht beim Lesen.
        if (_vorschlag || _erledigt) diffBinden();
        box.scrollTop = box.scrollHeight;
    }

    function zellText(a) {
        if (a.formel) return a.formel;
        if (a.werte && a.werte.length) {
            // VERSCHIEDENE Werte lassen sich nicht in eine Zeile schreiben. Die
            // ersten zeigen und die Zahl nennen ist ehrlicher als ein
            // abgeschnittener Anfang, der wie der ganze Inhalt aussieht.
            var flach = [];
            a.werte.forEach(function (z) {
                (z || []).forEach(function (c) {
                    flach.push(c === null || c === undefined ? '' : String(c));
                });
            });
            var kopf = flach.slice(0, 6).join(', ');
            return flach.length > 6
                ? kopf + ' … (' + flach.length + ' ' + T('xl.values', 'Werte') + ')'
                : kopf;
        }
        if (a.wert !== null && a.wert !== undefined) return String(a.wert);
        // Reiner Format-Eintrag: die Werte bleiben, nur die Anzeige aendert
        // sich. Ein leeres Feld hier saehe wie "wird geleert" aus.
        if (a.format) return T('xl.only_format', '(nur Zahlenformat)');
        return '';
    }

    function diffHtml(v, erledigt) {
        var n = (v.aenderungen || []).length;
        var h = '<div class="xl-diff"><div class="xl-diff-head">' +
            esc(T('xl.diff_head', 'Vorgeschlagene Änderungen') + ' (' + n + ')') +
            '</div>';
        if (v.zusammenfassung) {
            h += '<div class="xl-diff-sum">' + esc(v.zusammenfassung) + '</div>';
        }
        h += '<div class="xl-diff-list">';
        (v.aenderungen || []).forEach(function (a, i) {
            var ort = (a.blatt ? a.blatt + '!' : '') + a.adresse;
            h += '<div class="xl-cell">';
            // DIE ADRESSE IST EIN KNOPF. Ohne den Sprung ist sie eine
            // Zeichenkette, die man in einer Mappe mit 13 Blaettern von Hand
            // sucht – bei 30 Eintraegen liest sie dann niemand mehr nach, und
            // die Bestaetigung wird zur Formsache.
            h += '<button class="xl-cell-adr xl-goto" data-i="' + i + '" type="button" title="' +
                esc(T('xl.goto', 'In der Tabelle anzeigen')) + '">' + esc(ort) + '</button>';
            if (a._neuesBlatt) {
                h += '<span class="xl-cell-new">' +
                    esc(T('xl.sheet_new', 'neues Blatt')) + '</span>';
            }
            if (a.format) {
                h += '<span class="xl-cell-fmt">' + esc(a.format) + '</span>';
            }
            // Der ALTE Inhalt wird erst beim Uebernehmen gelesen; bis dahin
            // steht hier, was das Fenster beim Vorschlag vorgefunden hat.
            if (a._alt !== undefined && a._alt !== '') {
                h += '<span class="xl-cell-alt">' + esc(a._alt) + '</span>';
            }
            h += '<span class="xl-cell-neu">' + esc(zellText(a)) + '</span>';
            if (a.begruendung) {
                h += '<div class="xl-cell-why">' + esc(a.begruendung) + '</div>';
            }
            h += '</div>';
        });
        h += '</div>';
        if ((v.abgelehnt || []).length) {
            h += '<div class="xl-rej"><b>' +
                esc(T('xl.rejected', 'Nicht übernommen:')) + '</b><br>';
            v.abgelehnt.forEach(function (a) {
                var ort = a.adresse ? ((a.blatt ? a.blatt + '!' : '') + a.adresse + ': ') : '';
                h += esc(ort + (a.grund || '')) + '<br>';
            });
            h += '</div>';
        }
        if (erledigt) {
            // KEIN zweites "Uebernehmen": es ist schon geschrieben, und ein
            // Knopf darunter wuerde behaupten, es waere noch offen. Statt
            // dessen der Rueckweg – aber nur, solange DIESER Vorschlag der
            // zuletzt geschriebene ist.
            h += '<div class="xl-diff-done">' + esc(v.auto
                ? T('xl.applied_auto', 'Automatisch übernommen.')
                : T('xl.applied_note', 'Übernommen.'));
            if (v.angelegt && v.angelegt.length) {
                h += ' ' + esc(T('xl.sheets_added', 'Neu angelegt:') + ' ' +
                    v.angelegt.join(', '));
            }
            h += '</div>';
            if (_rueckweg === v) {
                h += '<div class="xl-row"><button class="xl-btn" id="xl-undo" type="button">' +
                    esc(T('xl.undo', 'Zurücknehmen')) + '</button></div>';
            }
            return h + '</div>';
        }
        h += '<div class="xl-row">' +
            '<button class="xl-btn xl-btn-primary" id="xl-apply">' +
            esc(T('xl.apply', 'Übernehmen')) + '</button>' +
            '<button class="xl-btn" id="xl-discard">' +
            esc(T('xl.discard', 'Verwerfen')) + '</button></div></div>';
        return h;
    }

    function diffBinden() {
        var a = $('xl-apply'), d = $('xl-discard'), u = $('xl-undo');
        if (a) a.onclick = uebernehmenFragen;
        if (u) u.onclick = zuruecknehmen;
        if (d) {
            d.onclick = function () {
                _vorschlag = null;
                zeichneVerlauf();
                melde('xl-status', T('xl.discarded', 'Vorschlag verworfen.'));
            };
        }
        // Die Adress-Knoepfe entstehen bei JEDEM Neuzeichnen neu – ein
        // delegierter Zuhoerer am Verlauf statt Bindung je Knopf. Ohne das
        // waeren sie nach dem naechsten `zeichneVerlauf()` tot und saehen
        // bedienbar aus, ohne zu wirken (im Projekt beim Prompt-Pruef-Knopf
        // bezahlt).
        var chat = $('xl-chat');
        if (chat && !chat._gotoGebunden) {
            chat._gotoGebunden = true;
            chat.addEventListener('click', function (ev) {
                var k = ev.target && ev.target.closest ? ev.target.closest('.xl-goto') : null;
                if (!k) return;
                ev.preventDefault();
                // Der EINTRAG wird zur Klickzeit gesucht, nicht gemerkt: der
                // Vorschlag kann inzwischen geschrieben (`_erledigt`) oder
                // verworfen sein.
                var quelle = _vorschlag || _erledigt;
                var i = parseInt(k.getAttribute('data-i'), 10);
                var e = quelle && quelle.aenderungen ? quelle.aenderungen[i] : null;
                if (e) zurZelle(e.blatt, e.adresse);
            });
        }
    }

    function fragen() {
        if (_laeuft) return;
        var feld = $('xl-frage');
        var text = (feld && feld.value || '').trim();
        if (!text) return;
        if (!_office) {
            melde('xl-status', _officeGrund || T('xl.no_excel',
                'Dieses Fenster läuft nicht in Excel.'), 'fehler');
            return;
        }
        feld.value = '';
        _vorschlag = null;
        _erledigt = null;
        _verlauf.push({ rolle: 'user', text: text });
        _verlauf.push({ rolle: 'wait', text: T('xl.reading', 'Lese die Tabelle …') });
        zeichneVerlauf();
        laufStarten(text, [], 1);
    }

    function laufStarten(frageText, nachgeladen, runde) {
        _laeuft = true;
        setzeLaeuft(true);
        ueberblickLesen().then(function (ueberblick) {
            // Zwischenstand ersetzen, nicht anhaengen.
            var letzte = _verlauf[_verlauf.length - 1];
            if (letzte && letzte.rolle === 'wait') {
                letzte.text = T('xl.thinking', 'Denkt nach …');
                zeichneVerlauf();
            }
            return sende('/api/excel/ask', 'POST', {
                frage: frageText,
                ueberblick: ueberblick || {},
                vorgeschichte: _verlauf.filter(function (m) {
                    return m.rolle === 'user' || m.rolle === 'bot';
                }).slice(-6).map(function (m) {
                    return { rolle: m.rolle === 'user' ? 'user' : 'bot', text: m.text };
                }),
                nachgeladen: nachgeladen,
                runde: runde
            });
        }).then(function (d) {
            // Nachforderung: das Modell braucht einen Bereich, den es nicht
            // gesehen hat. Wir lesen ihn und fragen erneut – hoechstens so oft,
            // wie der Server erlaubt, sonst kann ein Modell in einer Schleife
            // immer weitere Bereiche verlangen. Der Deckel kommt MIT der
            // Antwort; fehlt er (aelterer Server), gilt die Vorgabe.
            var maxRunden = parseInt(d.max_runden, 10);
            if (!(maxRunden >= 1)) maxRunden = MAX_RUNDEN_VORGABE;
            if (d.brauche && d.brauche.length && runde < maxRunden) {
                var letzte = _verlauf[_verlauf.length - 1];
                if (letzte && letzte.rolle === 'wait') {
                    letzte.text = T('xl.loading_range', 'Lade Bereich:') + ' ' +
                        d.brauche.join(', ');
                    zeichneVerlauf();
                }
                return Promise.all(d.brauche.map(bereichLesen)).then(function (teile) {
                    var neu = nachgeladen.concat(teile.filter(Boolean));
                    if (!neu.length) {
                        // Kein Bereich lesbar – lieber mit dem antworten, was da
                        // ist, als eine zweite Runde ohne neue Daten zu starten.
                        fertig(d);
                        return;
                    }
                    laufStarten(frageText, neu, runde + 1);
                });
            }
            fertig(d);
        }).catch(function (e) {
            if (String(e && e.message) === '401') return;
            _verlauf = _verlauf.filter(function (m) { return m.rolle !== 'wait'; });
            _verlauf.push({ rolle: 'bot', fehler: true, text: String(e && e.message || e) });
            zeichneVerlauf();
        }).then(function () {
            _laeuft = false;
            setzeLaeuft(false);
        });
    }

    function fertig(d) {
        _verlauf = _verlauf.filter(function (m) { return m.rolle !== 'wait'; });
        if (d.text) _verlauf.push({ rolle: 'bot', text: d.text });
        if ((d.aenderungen && d.aenderungen.length) ||
            (d.abgelehnt && d.abgelehnt.length)) {
            _vorschlag = {
                aenderungen: d.aenderungen || [],
                abgelehnt: d.abgelehnt || [],
                zusammenfassung: d.zusammenfassung || ''
            };
            // Alten Inhalt der betroffenen Zellen holen, damit der Diff beide
            // Seiten zeigt. Ein Diff mit nur einer Seite ist kein Diff.
            //
            // DIE AUTO-UEBERNAHME HAENGT AN DIESEM `then`, nicht am
            // Antworteingang: `uebernehmenJetzt()` verwirft `_vorschlag`, und
            // `alteWerteLesen` schreibt seine Ergebnisse IN dessen Eintraege.
            // Umgekehrte Reihenfolge = ein erledigter Diff ohne die linke
            // Seite, also wieder kein Diff.
            alteWerteLesen(_vorschlag.aenderungen).then(function () {
                zeichneVerlauf();
                if (autoAn() && _vorschlag && _vorschlag.aenderungen.length) {
                    uebernehmenJetzt(true);
                }
            });
        }
        if (!d.text && !(d.aenderungen || []).length) {
            _verlauf.push({
                rolle: 'bot', fehler: true,
                text: T('xl.empty', 'Der Assistent hat keine Antwort formuliert. Formuliere die Frage bitte anders.')
            });
        }
        zeichneVerlauf();
    }

    /* Liest den Zustand VOR dem Schreiben.

       Zwei Aufgaben in einem Zug, und die zweite ist die wichtigere:
       (a) die Vorschau `_alt` fuer die Diff-Ansicht,
       (b) der vollstaendige ALTZUSTAND als Grundlage des Rueckwegs
           (`_altF` Formeln, `_altFmt` Zahlenformate, `_altFuell` Fuellfarbe).

       (b) ist neu. Office.js-Schreibvorgaenge landen NICHT verlaesslich im
       Undo-Stack von Excel – bekannte Faelle leeren ihn sogar. Ein Hinweis
       "mach es mit Strg+Z rueckgaengig" ist damit eine Zusage, die der Browser
       nicht einloest; der Rueckweg muss aus dem Fenster kommen. */
    function alteWerteLesen(aenderungen) {
        if (!_office || !window.Excel || !aenderungen.length) return Promise.resolve();
        return Excel.run(function (ctx) {
            var refs = aenderungen.map(function (a) {
                try {
                    // getItemOrNullObject: ein Vorschlag darf ein Blatt
                    // ANLEGEN (dann gibt es hier nichts zu lesen). Mit
                    // getItem wuerde der ganze Lesevorgang scheitern und die
                    // Diff-Ansicht bekaeme fuer JEDE Zelle keine Altwerte.
                    var s = a.blatt ? ctx.workbook.worksheets.getItemOrNullObject(a.blatt)
                        : ctx.workbook.worksheets.getActiveWorksheet();
                    s.load('isNullObject');
                    return { s: s, a: a };
                } catch (e) { return null; }
            });
            return ctx.sync().then(function () {
                refs.forEach(function (o) {
                    if (!o) return;
                    try {
                        if (o.s.isNullObject) { o.a._neuesBlatt = true; return; }
                        var r = o.s.getRange(o.a.adresse);
                        r.load('formulas,rowCount,columnCount,numberFormat');
                        try { r.format.fill.load('color'); } catch (e) { }
                        o.r = r;
                    } catch (e) { }
                });
                return ctx.sync().then(function () {
                    refs.forEach(function (o) {
                        if (!o || !o.r) return;
                        try {
                            var f = o.r.formulas || [];
                            var flach = [];
                            f.forEach(function (z) {
                                z.forEach(function (c) {
                                    if (c !== '' && c !== null) flach.push(String(c));
                                });
                            });
                            o.a._alt = flach.slice(0, 3).join(', ') +
                                (flach.length > 3 ? ' …' : '');
                            o.a._zeilen = o.r.rowCount;
                            o.a._spalten = o.r.columnCount;
                            o.a._altF = f;
                            o.a._altFmt = o.r.numberFormat || null;
                            try { o.a._altFuell = o.r.format.fill.color || ''; }
                            catch (e) { o.a._altFuell = ''; }
                        } catch (e) { }
                    });
                });
            });
        }).catch(function (e) {
            console.warn('[excel] alte Werte nicht lesbar:', e);
        });
    }

    /* ── Schreiben ─────────────────────────────────────────────────────── */
    function uebernehmenFragen() {
        if (!_vorschlag || !_vorschlag.aenderungen.length) return;
        var n = _vorschlag.aenderungen.length;
        // EINTRAEGE UND ZELLEN SIND NICHT DASSELBE. Ein einziger Eintrag kann
        // `G2:G120` sein – "2 Zellen" waere dann schlicht falsch, und zwar in
        // genau der Rueckfrage, mit der der Benutzer die Verantwortung
        // uebernimmt. Die Zellzahl steht aus `alteWerteLesen()` bereit; ist sie
        // unbekannt, wird sie NICHT behauptet.
        var zellen = 0, bekannt = true;
        _vorschlag.aenderungen.forEach(function (a) {
            if (a._zeilen && a._spalten) zellen += a._zeilen * a._spalten;
            else bekannt = false;
        });
        var umfang = n + ' ' + T('xl.entries', 'Einträge');
        if (bekannt && zellen > n) {
            umfang += ' (' + zellen + ' ' + T('xl.cells', 'Zellen') + ')';
        }
        // Ein NEUES BLATT gehoert in die Rueckfrage. Es ist die einzige
        // Aenderung des Vorschlags, die die Mappe strukturell umbaut – und die
        // einzige, die der Rueckweg unten nicht zurueckdrehen kann.
        var neue = _vorschlag.aenderungen.filter(function (a) { return a._neuesBlatt; })
            .map(function (a) { return a.blatt; })
            .filter(function (b, i, arr) { return b && arr.indexOf(b) === i; });
        var text = T('xl.apply_ask', 'Sollen die Änderungen jetzt in die Tabelle geschrieben werden?') +
            '\n\n' + umfang;
        if (neue.length) {
            text += '\n\n' + T('xl.new_sheets', 'Neu angelegt wird:') + ' ' + neue.join(', ');
        }
        frage(text, T('xl.apply', 'Übernehmen'), false).then(function (ja) {
            if (ja) uebernehmenJetzt();
        });
    }

    /* Schreibt EINEN Eintrag in einen geladenen Bereich.
       Herausgeloest, weil `uebernehmenJetzt` sonst vier Faelle tief
       verschachtelt haette – und weil die Fallunterscheidung einzeln pruefbar
       sein muss: sie entscheidet, ob eine Datenliste als 60 gleiche Werte oder
       als 60 verschiedene in der Mappe landet. */
    function eintragSchreiben(z) {
        var a = z.a, r = z.r;
        var zeilen = r.rowCount || 1;
        var spalten = r.columnCount || 1;

        // (1) Zahlenformat zuerst. Es darf ALLEIN kommen ("formatiere Spalte B
        //     als Währung") – dann bleiben die Werte unangetastet.
        if (a.format) {
            try { r.numberFormat = fuellMatrix(a.format, zeilen, spalten); }
            catch (e) { console.warn('[excel] Format nicht setzbar:', e); }
        }

        // (2) VERSCHIEDENE Werte. Bis 2026-09-08 gab es diesen Weg nicht: ein
        //     `wert` wurde ueber den ganzen Bereich KOPIERT, und fuer 20 Zeilen
        //     x 3 Spalten brauchte das Modell 60 Einzeleintraege – bei einem
        //     Deckel von 200 Eintraegen war "trage die Daten ein" damit
        //     strukturell nicht gut zu machen.
        if (a.werte && a.werte.length) {
            r.values = a.werte;
            return;
        }
        if (a.formel) {
            if (zeilen === 1 && spalten === 1) {
                r.formulas = [[a.formel]];
            } else if (_kann19) {
                // Excel rechnet die Bezuege selbst um – der
                // verlaesslichste Weg, wenn er verfuegbar ist.
                r.getCell(0, 0).formulas = [[a.formel]];
                z._fuellen = true;
            } else {
                var m = [];
                for (var i = 0; i < zeilen; i++) {
                    var reihe = [];
                    for (var j = 0; j < spalten; j++) {
                        reihe.push(formelVerschieben(a.formel, i, j));
                    }
                    m.push(reihe);
                }
                r.formulas = m;
            }
            return;
        }
        if (a.wert !== undefined && a.wert !== null) {
            r.values = fuellMatrix(a.wert, zeilen, spalten);
        }
        // Kein Wert und keine Formel: dann war es ein reiner Format-Eintrag –
        // (1) hat schon alles getan.
    }

    function fuellMatrix(wert, zeilen, spalten) {
        var m = [];
        for (var i = 0; i < zeilen; i++) {
            var reihe = [];
            for (var j = 0; j < spalten; j++) reihe.push(wert);
            m.push(reihe);
        }
        return m;
    }

    function uebernehmenJetzt(auto) {
        var vorschlag = _vorschlag;
        var aenderungen = vorschlag.aenderungen.slice();
        melde('xl-status', T('xl.writing', 'Schreibe …'));
        _laeuft = true;
        setzeLaeuft(true);

        Excel.run(function (ctx) {
            // NEUE BLAETTER ZUERST. `getItem` auf ein fehlendes Blatt WIRFT –
            // bis 2026-09-08 konnte ein Vorschlag deshalb kein Blatt anlegen,
            // und "lege ein Auswertungsblatt an" scheiterte mit einer Meldung,
            // die nach einem Fehler des Assistenten aussah.
            var angelegt = [];
            aenderungen.forEach(function (a) {
                if (!a.blatt || !a._neuesBlatt) return;
                if (angelegt.indexOf(a.blatt) >= 0) return;
                try { ctx.workbook.worksheets.add(a.blatt); angelegt.push(a.blatt); }
                catch (e) { console.warn('[excel] Blatt nicht anlegbar:', e); }
            });

            var ziele = [];
            aenderungen.forEach(function (a) {
                var s = a.blatt ? ctx.workbook.worksheets.getItem(a.blatt)
                    : ctx.workbook.worksheets.getActiveWorksheet();
                var r = s.getRange(a.adresse);
                r.load('formulas,rowCount,columnCount,address');
                ziele.push({ a: a, r: r, s: s });
            });
            return ctx.sync().then(function () {
                ziele.forEach(eintragSchreiben);
                return ctx.sync();
            }).then(function () {
                // Zweiter Schritt fuer die 1.9-Faelle: copyFrom braucht die
                // gesetzte Quellzelle, muss also NACH dem ersten sync laufen.
                var zuFuellen = ziele.filter(function (z) { return z._fuellen; });
                if (!zuFuellen.length) return ctx.sync();
                zuFuellen.forEach(function (z) {
                    z.r.copyFrom(z.r.getCell(0, 0), Excel.RangeCopyType.formulas);
                });
                return ctx.sync();
            }).then(function () {
                // MARKIEREN. Erst nach dem Schreiben, damit eine gescheiterte
                // Aenderung nicht als erledigt markiert dasteht.
                if (!markAn()) return ctx.sync();
                ziele.forEach(function (z) {
                    try { z.r.format.fill.color = MARK_FARBE; } catch (e) { }
                    if (!_kann110 || !z.a.begruendung) return;
                    try {
                        // Der Kommentar traegt die BEGRUENDUNG des Modells. Sie
                        // liegt ohnehin vor (sie steht in der Diff-Ansicht) und
                        // ist an der Zelle die einzige Erklaerung, die auch
                        // morgen noch da ist.
                        ctx.workbook.comments.add(
                            z.r.getCell(0, 0),
                            T('xl.comment_pre', 'Jarvis:') + ' ' + z.a.begruendung);
                    } catch (e) { }
                });
                return ctx.sync();
            }).then(function () {
                // FEHLERWERTE PRUEFEN statt einen Formelparser zu bauen:
                // schreiben, zuruecklesen, auf #NAME?/#BEZUG! pruefen. Das ist
                // ehrlicher als eine Syntaxpruefung, die die Excel-Grammatik nie
                // ganz trifft – und es faengt auch Fehler, die erst im Kontext
                // der Mappe entstehen (fehlendes Blatt, geloeschter Bezug).
                ziele.forEach(function (z) { z.r.load('values'); });
                return ctx.sync().then(function () {
                    var kaputt = [];
                    ziele.forEach(function (z) {
                        (z.r.values || []).forEach(function (zeile) {
                            zeile.forEach(function (c) {
                                if (fehlerwert(c)) kaputt.push(z.a.adresse + ': ' + c);
                            });
                        });
                    });
                    return { kaputt: kaputt, angelegt: angelegt };
                });
            });
        }).then(function (erg) {
            // Der geschriebene Vorschlag bleibt SICHTBAR (ohne Knoepfe) – bei
            // automatischer Uebernahme ist das die einzige Stelle, an der
            // steht, was gerade in die Mappe gelaufen ist.
            vorschlag.auto = !!auto;
            vorschlag.angelegt = erg.angelegt || [];
            _erledigt = vorschlag;
            // Der Rueckweg. Er haengt am ZULETZT geschriebenen Vorschlag: ein
            // Stapel ueber mehrere Vorschlaege waere eine Zusage, die niemand
            // pruefen kann (zwischendurch kann der Benutzer selbst getippt
            // haben, und dann nimmt Schritt 2 seine Arbeit mit zurueck).
            _rueckweg = vorschlag;
            _vorschlag = null;
            if (erg.kaputt.length) {
                // Nicht stillschweigend stehen lassen: der Benutzer soll
                // entscheiden, ob er es behaelt oder zurueckdreht.
                _verlauf.push({
                    rolle: 'bot', fehler: true,
                    text: T('xl.err_cells', 'Achtung – diese Zellen zeigen einen Fehlerwert:') +
                        '\n' + erg.kaputt.slice(0, 10).join('\n') + '\n\n' +
                        T('xl.err_hint', 'Mit „Zurücknehmen" stellst du den Zustand von vorher wieder her.')
                });
                melde('xl-status', T('xl.written_err', 'Geschrieben – mit Fehlerwerten.'), 'fehler');
            } else {
                melde('xl-status', T('xl.written', 'Änderungen wurden übernommen.'), 'ok');
            }
            zeichneVerlauf();
        }).catch(function (e) {
            melde('xl-status', T('xl.write_failed', 'Schreiben fehlgeschlagen:') + ' ' +
                String(e && e.message || e), 'fehler');
        }).then(function () {
            _laeuft = false;
            setzeLaeuft(false);
        });
    }

    /* ── Zurücknehmen ──────────────────────────────────────────────────────
       DER GRUND, WARUM ES DAS GEBEN MUSS: Office.js-Schreibvorgaenge sind
       nicht verlaesslich im Undo-Stack von Excel – manche Aufrufe leeren ihn
       sogar (Formatierungen, nicht unterstuetzte APIs). Das Fenster versprach
       bis 2026-09-08 "mit Strg+Z rueckgaengig"; die skill.json sagte im selben
       Atemzug das Gegenteil ("das Fenster bietet dafuer einen eigenen
       Rueckweg") – den es nicht gab. Zwei Aussagen, beide falsch.

       WAS ES ZURUECKNIMMT: Werte, Formeln, Zahlenformate und die Markierung.
       WAS NICHT: ein neu angelegtes Blatt (es zu loeschen waere eine
       Aenderung, die der Benutzer nicht bestellt hat – er koennte inzwischen
       selbst hineingeschrieben haben). Der Hinweis sagt das. */
    function zuruecknehmen() {
        var v = _rueckweg;
        if (!v || !v.aenderungen || !v.aenderungen.length) return;
        var wieder = v.aenderungen.filter(function (a) { return a._altF; });
        if (!wieder.length) {
            melde('xl-status', T('xl.undo_none',
                'Der Zustand von vorher ist nicht mehr bekannt.'), 'fehler');
            return;
        }
        var hinweis = T('xl.undo_ask', 'Den Zustand vor dieser Änderung wiederherstellen?');
        if (v.angelegt && v.angelegt.length) {
            hinweis += '\n\n' + T('xl.undo_keeps_sheet',
                'Neu angelegte Blätter bleiben bestehen:') + ' ' + v.angelegt.join(', ');
        }
        frage(hinweis, T('xl.undo', 'Zurücknehmen'), true).then(function (ja) {
            if (!ja) return;
            _laeuft = true; setzeLaeuft(true);
            melde('xl-status', T('xl.undoing', 'Nehme zurück …'));
            Excel.run(function (ctx) {
                wieder.forEach(function (a) {
                    try {
                        var s = a.blatt ? ctx.workbook.worksheets.getItem(a.blatt)
                            : ctx.workbook.worksheets.getActiveWorksheet();
                        var r = s.getRange(a.adresse);
                        // FORMELN zurueckschreiben, nicht Werte: `formulas`
                        // traegt bei einer Formelzelle die Formel und bei einer
                        // Wertzelle den Wert. Wer `values` nimmt, macht aus
                        // jeder zurueckgenommenen Formel eine feste Zahl.
                        r.formulas = a._altF;
                        if (a.format && a._altFmt) r.numberFormat = a._altFmt;
                        if (markAn()) {
                            // Die vorherige Fuellfarbe wiederherstellen, wenn
                            // sie bekannt ist. Bei einem Bereich mit
                            // GEMISCHTEN Farben gibt Office.js keinen Wert
                            // heraus – dann wird geleert, und der Hinweis sagt
                            // es. Eine geratene Farbe waere schlechter.
                            try {
                                if (a._altFuell) r.format.fill.color = a._altFuell;
                                else r.format.fill.clear();
                            } catch (e) { }
                        }
                    } catch (e) { console.warn('[excel] Zurücknehmen:', e); }
                });
                return ctx.sync();
            }).then(function () {
                _rueckweg = null;
                if (_erledigt === v) _erledigt = null;
                _verlauf.push({
                    rolle: 'bot',
                    text: T('xl.undone', 'Die Änderung wurde zurückgenommen.')
                });
                melde('xl-status', T('xl.undone', 'Die Änderung wurde zurückgenommen.'), 'ok');
                zeichneVerlauf();
            }).catch(function (e) {
                melde('xl-status', T('xl.undo_failed', 'Zurücknehmen fehlgeschlagen:') +
                    ' ' + String(e && e.message || e), 'fehler');
            }).then(function () {
                _laeuft = false; setzeLaeuft(false);
            });
        });
    }

    /* Springt im Blatt zu einer Zelle und markiert sie.
       Der Gegenwert von Claudes "cell-level citations": eine Adresse in der
       Diff-Ansicht ist ohne diesen Weg eine Zeichenkette, die man von Hand
       suchen muss. */
    function zurZelle(blatt, adresse) {
        if (!_office || !window.Excel) return;
        Excel.run(function (ctx) {
            var s = blatt ? ctx.workbook.worksheets.getItemOrNullObject(blatt)
                : ctx.workbook.worksheets.getActiveWorksheet();
            s.load('isNullObject');
            return ctx.sync().then(function () {
                if (s.isNullObject) return;
                s.activate();
                s.getRange(adresse).select();
                return ctx.sync();
            });
        }).catch(function (e) { console.warn('[excel] Sprung:', e); });
    }

    function setzeLaeuft(an) {
        var s = $('xl-send');
        if (s) {
            s.disabled = !!an;
            s.textContent = an ? T('xl.working', 'Arbeitet …') : T('xl.send', 'Senden');
        }
    }

    /* ── Bezugszeile ───────────────────────────────────────────────────── */
    function ctxZeigen() {
        var e = $('xl-ctx');
        if (!e) return;
        if (!_office) {
            e.innerHTML = '<b>' + esc(T('xl.no_ctx', 'Keine Tabelle verbunden')) + '</b>';
            return;
        }
        e.innerHTML = _ctxKurz || esc(T('xl.ctx_wait', 'Lese Tabelle …'));
    }

    function ctxAktualisieren() {
        if (!_office || !window.Excel) { ctxZeigen(); return; }
        Excel.run(function (ctx) {
            var wb = ctx.workbook;
            wb.load('name');
            var sel = wb.getSelectedRange();
            sel.load('address,rowCount,columnCount');
            var bl = sel.worksheet;
            bl.load('name');
            return ctx.sync().then(function () {
                var adr = (sel.address || '').replace(/^.*!/, '');
                var n = (sel.rowCount || 1) * (sel.columnCount || 1);
                _ctxKurz = '<b>' + esc(wb.name || '') + '</b> · ' +
                    esc(bl.name || '') + '!' + esc(adr) +
                    ' (' + n + ' ' + esc(T('xl.cells', 'Zellen')) + ')';
                ctxZeigen();
            });
        }).catch(function () {
            _ctxKurz = '';
            ctxZeigen();
        });
    }

    /* ── Manifest-Version ──────────────────────────────────────────────── */
    function mvAusUrl() {
        try {
            var m = /[?&]mv=([0-9.]{1,20})(?:&|$)/.exec(window.location.search || '');
            return m ? m[1] : '';
        } catch (e) { return ''; }
    }
    function versionNeuer(a, b) {
        // SEGMENTWEISE NUMERISCH. Ein String-Vergleich haelt "1.10" fuer
        // kleiner als "1.9" – und der Fehler faellt erst beim zehnten
        // Manifest auf.
        var x = String(a || '').split('.'), y = String(b || '').split('.');
        for (var i = 0; i < Math.max(x.length, y.length); i++) {
            var p = parseInt(x[i] || '0', 10) || 0, q = parseInt(y[i] || '0', 10) || 0;
            if (p !== q) return p > q;
        }
        return false;
    }
    function versionPruefen() {
        fetch('/api/excel-addin/version', { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.version) return;
                _updServer = d.version;
                zeichneUpdBand();
            }).catch(function () { });
    }
    function zeichneUpdBand() {
        var band = $('xl-upd');
        if (!band || !_updServer) return;
        var mv = mvAusUrl();
        // NICHTS BEHAUPTEN, WAS WIR NICHT WISSEN: ohne `mv` und ohne
        // Excel-Kontext ist das ein Browseraufruf – dann kein Band.
        if (!mv && !_office) { band.classList.add('hidden'); return; }
        if (mv && !versionNeuer(_updServer, mv)) { band.classList.add('hidden'); return; }
        var text = mv
            ? T('xl.upd_text', 'Installiert ist Fassung {alt}, verfügbar ist {neu}.')
                .replace('{alt}', mv).replace('{neu}', _updServer)
            : T('xl.upd_unknown', 'Die installierte Fassung meldet ihre Version nicht – sie stammt aus einer älteren Installation.');
        band.innerHTML = '<div class="xl-upd-head">' +
            esc(T('xl.upd_head', 'Neue Fassung des Add-ins verfügbar')) + '</div>' +
            '<div class="xl-upd-text">' + esc(text) + '</div>' +
            '<a class="xl-btn" href="/excel-addin/manifest.xml">' +
            esc(T('xl.upd_get', 'Manifest herunterladen')) + '</a>';
        band.classList.remove('hidden');
    }

    /* Nimmt die Startanzeige weg – siehe `#xl-boot` in taskpane.html.
       Wird von JEDEM Weg gerufen, der etwas Sichtbares einblendet; solange sie
       steht, hat das Fenster den Start nicht geschafft. */
    function bootWeg() {
        var b = $('xl-boot');
        if (b) b.classList.add('hidden');
    }

    /* ── Anmeldung ─────────────────────────────────────────────────────── */
    function zeigeLogin(hinweis) {
        bootWeg();
        $('xl-app').classList.add('hidden');
        $('xl-login').classList.remove('hidden');
        $('xl-login-hint').textContent = hinweis ||
            T('addin.login_hint', 'Melde dich mit deinem gewohnten Zugang an – denselben Daten wie im Browser.');
        if (_officeGrund) melde('xl-login-office', _officeGrund, 'fehler');
        else if (_office) melde('xl-login-office', T('xl.office_ok', 'Mit Excel verbunden.'), 'ok');
        zeichneUpdBand();
    }

    function zeigeApp() {
        bootWeg();
        $('xl-login').classList.add('hidden');
        $('xl-app').classList.remove('hidden');
        ctxZeigen();
        ctxAktualisieren();
        // OHNE `await`: die Vorgaben sind ein Nebenfeld, und der Lauf holt sie
        // ohnehin serverseitig – das Fenster darf nicht auf sie warten (dieselbe
        // Regel wie bei der Freigabeliste in /wissen: eine Ansicht wartet nie
        // auf eine nur schmueckende Anfrage).
        anweisungenLaden();
        if (!_verlauf.length) {
            _verlauf.push({
                rolle: 'bot',
                text: T('xl.welcome', 'Frag mich etwas zu dieser Tabelle. Ich sehe den Aufbau der Blätter und deine aktuelle Auswahl – Änderungen zeige ich dir immer erst zur Bestätigung.')
            });
        }
        zeichneVerlauf();
        if (_officeGrund) melde('xl-status', _officeGrund, 'fehler');
        zeichneUpdBand();
    }

    function anmelden() {
        var u = ($('xl-user').value || '').trim();
        var p = $('xl-pass').value || '';
        var totp = ($('xl-totp').value || '').trim();
        if (!u || !p) {
            melde('xl-login-status', T('login.fill', 'Bitte Benutzername und Passwort eingeben.'), 'fehler');
            return;
        }
        melde('xl-login-status', T('login.checking', 'Prüfe …'));
        var rumpf = { username: u, password: p };
        // FELDNAME: der Server liest `totp_code` (so senden es app.js, chat.js,
        // userchat.js und wissen.js). Ein `totp` ginge ins Leere, der Server
        // saehe keinen Code und antwortete erneut mit requires_totp – eine
        // Anmeldeschleife, aus der niemand herauskommt (im Outlook-Add-in
        // genau so passiert).
        if (totp) rumpf.totp_code = totp;
        fetch('/api/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(rumpf)
        }).then(function (r) {
            return r.json().catch(function () { return {}; })
                .then(function (d) { return { status: r.status, d: d }; });
        }).then(function (res) {
            var d = res.d || {};
            if (d.requires_totp) {
                $('xl-totp-wrap').classList.remove('hidden');
                melde('xl-login-status', T('login.totp', 'Bitte den Code aus deiner Authenticator-App eingeben.'));
                return;
            }
            if (res.status !== 200 || !d.token) {
                melde('xl-login-status', d.detail || d.message ||
                    T('login.failed', 'Anmeldung fehlgeschlagen.'), 'fehler');
                return;
            }
            tokenSetzen(d.token);
            var hinweis = _speicherGeht ? '' : T('addin.no_storage',
                'Hinweis: Dieser Browser erlaubt dem Fenster keinen dauerhaften Speicher. Die Anmeldung gilt nur, solange das Fenster offen ist.');
            pruefeFreigabe(hinweis);
        }).catch(function (e) {
            melde('xl-login-status', String(e && e.message || e), 'fehler');
        });
    }

    /* Freigabe VOR dem ersten Chat pruefen. Ohne diesen Schritt liefe der
       Benutzer bei jeder Frage in einen 403 mit technischem Text – die Aussage
       "du bist nicht freigeschaltet" gehoert an den Anfang, mit dem Weg dorthin. */
    function pruefeFreigabe(hinweis) {
        fetch('/api/me', { headers: kopf() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var erlaubt = d && d.permissions && d.permissions.excel;
                if (!erlaubt) {
                    zeigeLogin('');
                    melde('xl-login-status', T('xl.no_access',
                        'Dein Konto ist für den Tabellen-Assistenten nicht freigeschaltet. Ein Administrator trägt dich unter Einstellungen → Sicherheit → Berechtigungen → Excel-Zugriff ein.'),
                        'fehler');
                    return;
                }
                zeigeApp();
                if (hinweis) melde('xl-status', hinweis);
            }).catch(function (e) {
                zeigeLogin('');
                melde('xl-login-status', String(e && e.message || e), 'fehler');
            });
    }

    /* ── Persoenliche Vorgaben ──────────────────────────────────────────
       Sie ersetzen ``data/instructions/*.md``, das seit dem eigenen
       System-Prompt (2026-09-08) nicht mehr in den Excel-Lauf geht. Wer eine
       Hausregel in Excel braucht, traegt sie HIER ein – je Benutzer, weil eine
       Vorgabe ueber Zahlenformate und Beschriftungen zur Arbeitsweise gehoert
       und nicht zur Installation. */
    function anweisungenLaden() {
        var f = $('xl-anw');
        if (!f) return Promise.resolve();
        return sende('/api/excel/instructions', 'GET').then(function (d) {
            if (d && d.ok) f.value = d.instructions || '';
        }).catch(function () {
            // Ein Fehlschlag bleibt STILL: die Vorgaben sind ein Nebenfeld,
            // und eine Fehlermeldung beim Oeffnen des Fensters wuerde nach
            // einem Anmeldeproblem aussehen, das es nicht gibt. Der Lauf
            // arbeitet dann ohne sie – wie vor der Einfuehrung.
        });
    }

    function anweisungenSpeichern() {
        var f = $('xl-anw');
        if (!f) return;
        var k = $('xl-anw-save');
        if (k) k.disabled = true;
        melde('xl-anw-status', T('xl.instr_saving', 'Speichere …'));
        sende('/api/excel/instructions', 'POST', { instructions: f.value })
            .then(function (d) {
                if (d && d.ok) {
                    melde('xl-anw-status', T('xl.instr_saved', 'Gespeichert.'), 'ok');
                } else {
                    melde('xl-anw-status',
                        (d && d.error) || T('xl.instr_failed', 'Nicht gespeichert.'), 'fehler');
                }
            })
            .catch(function (err) {
                melde('xl-anw-status', T('xl.instr_failed', 'Nicht gespeichert.') +
                    ' ' + String(err && err.message || err), 'fehler');
            })
            .then(function () { if (k) k.disabled = false; });
    }

    function abmelden() {
        // Abmelde-Signal VOR dem Verwerfen des Tokens, mit keepalive – ohne
        // das bricht der Browser die Anfrage beim Weiternavigieren ab.
        try {
            fetch('/api/logout', { method: 'POST', headers: kopf(), keepalive: true });
        } catch (e) { }
        tokenLoeschen();
        _verlauf = [];
        _vorschlag = null;
        zeigeLogin('');
    }

    /* ── Start ─────────────────────────────────────────────────────────── */
    function binden() {
        var e;
        if ((e = $('xl-do-login'))) e.addEventListener('click', anmelden);
        if ((e = $('xl-pass'))) e.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') anmelden();
        });
        if ((e = $('xl-totp'))) e.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') anmelden();
        });
        if ((e = $('xl-send'))) e.addEventListener('click', fragen);
        if ((e = $('xl-auto'))) {
            // Zustand ZUERST setzen: das Markup traegt `checked`, aber wer
            // einmal abgewaehlt hat, darf nach dem Neuladen nicht wieder
            // eine automatische Uebernahme bekommen.
            e.checked = autoAn();
            e.addEventListener('change', function () { autoSetzen(e.checked); });
        }
        if ((e = $('xl-mark'))) {
            e.checked = markAn();
            e.addEventListener('change', function () { markSetzen(e.checked); });
        }
        if ((e = $('xl-anw-save'))) e.addEventListener('click', anweisungenSpeichern);
        if ((e = $('xl-logout'))) e.addEventListener('click', abmelden);
        if ((e = $('xl-frage'))) e.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Enter') return;
            // ENTER sendet (Vorgabe des Nutzers). Fuer den mehrzeiligen Fall
            // bleibt Umschalt+Enter – ein Feld, aus dem es GAR KEINEN Weg zum
            // Zeilenumbruch gibt, waere ein Rueckschritt: eine Frage an eine
            // Tabelle ist oft mehrzeilig, und `rows="3"` verspricht das auch.
            if (ev.shiftKey) return;
            // Strg+Enter sendet weiter mit – es war bis hierher der einzige
            // Sendeweg, und wer ihn gewohnt ist, soll nicht ins Leere greifen.
            ev.preventDefault();
            fragen();
        });
        if ((e = $('xl-theme'))) e.addEventListener('click', function () {
            // `theme.js` exportiert `applyTheme`, NICHT `toggleTheme` – die
            // frueher geprueefte Funktion gab es nie, also tat der Knopf
            // NICHTS (kein Fehler, keine Reaktion). Gleicher Fehler wie im
            // Outlook-Add-in, dort schon behoben.
            var hell = !document.body.classList.contains('light');
            // Der Rueckfall schaltet zwar die Klasse, feuert aber KEIN
            // `jarvis:themechange` – branding.js zieht die Hell-Farben der
            // Marke dann nicht nach. Deshalb bevorzugt `applyTheme`.
            if (window.applyTheme) window.applyTheme(hell);
            else document.body.classList.toggle('light', hell);
            try {
                localStorage.setItem('jarvis_theme', hell ? 'light' : 'dark');
            } catch (e2) { }
        });
        if ((e = $('xl-lang'))) e.addEventListener('click', function () {
            var neu = (window._lang === 'en') ? 'de' : 'en';
            if (window.setLang) window.setLang(neu);
            var b = $('xl-lang');
            if (b) b.textContent = neu.toUpperCase();
            // Der Verlauf und das Band werden per innerHTML gesetzt –
            // applyLang() erreicht sie nicht.
            zeichneVerlauf();
            zeichneUpdBand();
            ctxZeigen();
        });
    }

    /* Zeigt die Startanzeige mit Klartext-Grund – fuer den Fall, dass das
       Fenster GAR NICHT arbeiten kann und deshalb weder Anmeldung noch App
       sinnvoll waeren. */
    function bootFehler(text, genau) {
        var d = $('xl-boot-detail'), f = $('xl-boot-err');
        if (d) d.classList.remove('hidden');
        if (f) f.textContent = text || '';
        // Steht die Ursache fest, verschwindet die Vermutungsliste: drei
        // "haeufige Ursachen" neben der gemessenen Antwort lassen den
        // Benutzer raten, obwohl nichts mehr zu raten ist.
        if (genau) {
            var g = $('xl-boot-generic');
            if (g) g.classList.add('hidden');
            if (f) f.classList.add('is-text');
            var k = document.querySelector('.xl-boot-head');
            if (k) k.textContent = T('xl.boot_head_stop',
                'Der Assistent kann in dieser Excel-Fassung nicht laufen');
        }
    }

    function start() {
        // JEDER Schritt einzeln abgesichert. Bis 2026-08-21 brach `start()`
        // beim ersten Fehler ab – und weil Anmeldung UND App verborgen
        // starten, blieb dann ein WEISSES Fenster ohne jede Meldung zurueck
        // (genau so gemeldet). Ein Teilausfall darf hoechstens eine Funktion
        // kosten, nie die ganze Anzeige.
        try { binden(); } catch (e) { }

        // Fehlendes `fetch` ist KEINE vage Vermutung, sondern die Signatur des
        // Trident-WebView (Internet Explorer). Den benutzen die KAUFVERSIONEN
        // bis einschliesslich Office 2019 fuer Aufgabenfenster – am 2026-08-21
        // an einem echten Office Professional Plus 2019 gemessen. Microsoft
        // laesst sie nicht auf WebView2 umstellen (kein Registry-Schalter, die
        // Laufzeitumgebung von Hand zu installieren aendert nichts); WebView2
        // setzt Microsoft 365 bzw. Office LTSC 2021 voraus.
        //
        // Trident kann nur ES5 – und vor allem KEINE CSS-Variablen, auf denen
        // die gesamte Oberflaeche dieses Projekts beruht (109 Fundstellen im
        // Fenster, dazu color-mix). Eine Unterstuetzung waere deshalb kein
        // Nachbessern, sondern ein zweites Designsystem. Microsofts eigene
        // Empfehlung fuer diese WebViews ist ausdruecklich eine klare Absage
        // an den Benutzer – genau die steht hier.
        //
        // Ohne diese Pruefung waere der `fetch`-Aufruf in `versionPruefen()`
        // ein ReferenceError, der `start()` vor jeder Anzeige beendet: das
        // gemeldete weisse Fenster.
        if (typeof fetch !== 'function') {
            bootFehler(T('xl.no_fetch',
                'Dieses Excel benutzt für Aufgabenfenster noch den Internet Explorer. Das betrifft die Kaufversionen bis einschließlich Office 2019 – sie lassen sich nicht umstellen. Der Assistent braucht Microsoft 365 oder Office LTSC 2021 (oder neuer). Bis dahin: dieselben Tabellenfunktionen stehen im Browser im Portal zur Verfügung – Datei dort in den Chat legen.'),
                true);
            return;
        }

        try { versionPruefen(); } catch (e) { }

        var weiter = function () {
            try { zeichneUpdBand(); } catch (e) { }
            if (token()) {
                pruefeFreigabe('');
            } else {
                zeigeLogin('');
            }
            // Auswahlwechsel verfolgen: die Bezugszeile muss sagen, worauf
            // sich die naechste Frage bezieht.
            if (_office && window.Excel) {
                try {
                    Excel.run(function (ctx) {
                        ctx.workbook.worksheets.onSelectionChanged.add(function () {
                            ctxAktualisieren();
                            return Promise.resolve();
                        });
                        return ctx.sync();
                    }).catch(function () { });
                } catch (e) { }
            }
        };
        // Beide Zweige fuehren weiter: scheitert die Excel-Ermittlung, laeuft
        // das Fenster ohne Tabellenbezug – aber es laeuft.
        try {
            officeErmitteln().then(weiter, weiter);
        } catch (e) {
            weiter();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

    // Fuer die Tests: die reinen Funktionen ohne DOM-Bezug.
    window._xlIntern = {
        formelVerschieben: formelVerschieben,
        versionNeuer: versionNeuer,
        spalteZuIndex: spalteZuIndex,
        indexZuSpalte: indexZuSpalte
    };
})();
