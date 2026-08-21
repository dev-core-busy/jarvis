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
    var MAX_RUNDEN = 3;           // muss zu excel_ask.MAX_RUNDEN passen

    var _office = false;      // Excel-Kontext vorhanden
    var _officeGrund = '';
    var _kann19 = false;      // ExcelApi 1.9 (copyFrom/autoFill)
    var _laeuft = false;
    var _verlauf = [];        // [{rolle:'user'|'bot', text}]
    var _vorschlag = null;    // {aenderungen, abgelehnt, zusammenfassung}
    var _rueckgaengig = null; // [{blatt, adresse, formeln}] fuer eigenes Undo
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

            return ctx.sync().then(function () {
                var ergebnis = {
                    name: wb.name || '',
                    aktiv: aktiv.name || '',
                    blaetter: [],
                    auswahl: null
                };
                // Zweite Runde: je Blatt den benutzten Bereich, und daraus nur
                // die ersten Zeilen. `getUsedRangeOrNullObject` ist Pflicht –
                // `getUsedRange` WIRFT bei einem leeren Blatt, und ein leeres
                // Blatt in der Mappe darf den ganzen Ueberblick nicht kippen.
                var infos = [];
                blaetter.items.slice(0, 30).forEach(function (b) {
                    var s = ctx.workbook.worksheets.getItem(b.name);
                    var u = s.getUsedRangeOrNullObject();
                    u.load('address,rowCount,columnCount,rowIndex,columnIndex,isNullObject');
                    infos.push({ name: b.name, used: u, sheet: s });
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
                        if (i.used.isNullObject) {
                            ergebnis.blaetter.push({ name: i.name, bereich: '', zeilen: 0, spalten: 0 });
                            return;
                        }
                        var zeilen = Math.min(i.used.rowCount, 5);
                        var spalten = Math.min(i.used.columnCount, 30);
                        var probe = i.sheet.getRangeByIndexes(
                            i.used.rowIndex, i.used.columnIndex, zeilen, spalten);
                        probe.load('values,valueTypes');
                        i.probe = probe;
                        ergebnis.blaetter.push({
                            name: i.name,
                            bereich: i.used.address || '',
                            zeilen: i.used.rowCount,
                            spalten: i.used.columnCount
                        });
                    });

                    return ctx.sync().then(function () {
                        infos.forEach(function (i, idx) {
                            if (!i.probe) return;
                            var w = i.probe.values || [];
                            var t = i.probe.valueTypes || [];
                            var eintrag = ergebnis.blaetter[idx];
                            if (!w.length) return;
                            eintrag.kopf = w[0].map(function (z) { return z === null ? '' : String(z); });
                            // Datentypen aus der ZWEITEN Zeile: die erste ist in
                            // aller Regel die Ueberschrift und damit ueberall Text –
                            // aus ihr abgeleitete Typen waeren wertlos.
                            if (t.length > 1) {
                                eintrag.typen = t[1].map(typName);
                            }
                            eintrag.beispiele = w.slice(1).map(function (zeile) {
                                return zeile.map(function (z) { return z === null ? '' : String(z); });
                            });
                        });
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
        }).catch(function (e) {
            console.warn('[excel] Ueberblick nicht lesbar:', e);
            return null;
        });
    }

    function typName(t) {
        switch (t) {
            case 'Double': case 'Integer': return 'Zahl';
            case 'String': return 'Text';
            case 'Boolean': return 'Wahrheitswert';
            case 'Error': return 'Fehler';
            case 'Empty': return '';
            default: return t ? String(t) : '';
        }
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
        if (_vorschlag) html += diffHtml(_vorschlag);
        box.innerHTML = html;
        if (_vorschlag) diffBinden();
        box.scrollTop = box.scrollHeight;
    }

    function zellText(a) {
        if (a.formel) return a.formel;
        return a.wert === null || a.wert === undefined ? '' : String(a.wert);
    }

    function diffHtml(v) {
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
            h += '<div class="xl-cell"><span class="xl-cell-adr">' + esc(ort) + '</span>';
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
        h += '<div class="xl-row">' +
            '<button class="xl-btn xl-btn-primary" id="xl-apply">' +
            esc(T('xl.apply', 'Übernehmen')) + '</button>' +
            '<button class="xl-btn" id="xl-discard">' +
            esc(T('xl.discard', 'Verwerfen')) + '</button></div></div>';
        return h;
    }

    function diffBinden() {
        var a = $('xl-apply'), d = $('xl-discard');
        if (a) a.onclick = uebernehmenFragen;
        if (d) {
            d.onclick = function () {
                _vorschlag = null;
                zeichneVerlauf();
                melde('xl-status', T('xl.discarded', 'Vorschlag verworfen.'));
            };
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
            // gesehen hat. Wir lesen ihn und fragen erneut – hoechstens
            // MAX_RUNDEN mal, sonst kann ein Modell in einer Schleife immer
            // weitere Bereiche verlangen.
            if (d.brauche && d.brauche.length && runde < MAX_RUNDEN) {
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
            alteWerteLesen(_vorschlag.aenderungen).then(zeichneVerlauf);
        }
        if (!d.text && !(d.aenderungen || []).length) {
            _verlauf.push({
                rolle: 'bot', fehler: true,
                text: T('xl.empty', 'Der Assistent hat keine Antwort formuliert. Formuliere die Frage bitte anders.')
            });
        }
        zeichneVerlauf();
    }

    function alteWerteLesen(aenderungen) {
        if (!_office || !window.Excel || !aenderungen.length) return Promise.resolve();
        return Excel.run(function (ctx) {
            var refs = aenderungen.map(function (a) {
                try {
                    var s = a.blatt ? ctx.workbook.worksheets.getItem(a.blatt)
                        : ctx.workbook.worksheets.getActiveWorksheet();
                    var r = s.getRange(a.adresse);
                    r.load('formulas,rowCount,columnCount');
                    return r;
                } catch (e) { return null; }
            });
            return ctx.sync().then(function () {
                refs.forEach(function (r, i) {
                    if (!r) return;
                    try {
                        var f = r.formulas || [];
                        var flach = [];
                        f.forEach(function (z) {
                            z.forEach(function (c) {
                                if (c !== '' && c !== null) flach.push(String(c));
                            });
                        });
                        aenderungen[i]._alt = flach.slice(0, 3).join(', ') +
                            (flach.length > 3 ? ' …' : '');
                        aenderungen[i]._zeilen = r.rowCount;
                        aenderungen[i]._spalten = r.columnCount;
                    } catch (e) { }
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
        frage(T('xl.apply_ask', 'Sollen die Änderungen jetzt in die Tabelle geschrieben werden?') +
            '\n\n' + umfang,
            T('xl.apply', 'Übernehmen'), false).then(function (ja) {
                if (ja) uebernehmenJetzt();
            });
    }

    function uebernehmenJetzt() {
        var aenderungen = _vorschlag.aenderungen.slice();
        melde('xl-status', T('xl.writing', 'Schreibe …'));
        setzeLaeuft(true);

        Excel.run(function (ctx) {
            var schnappschuss = [];
            var ziele = [];
            aenderungen.forEach(function (a) {
                var s = a.blatt ? ctx.workbook.worksheets.getItem(a.blatt)
                    : ctx.workbook.worksheets.getActiveWorksheet();
                var r = s.getRange(a.adresse);
                r.load('formulas,rowCount,columnCount,address');
                ziele.push({ a: a, r: r, s: s });
            });
            return ctx.sync().then(function () {
                // SNAPSHOT VOR DEM SCHREIBEN. Office.js-Schreibvorgaenge landen
                // nicht im Undo-Stack von Excel – Strg+Z holt sie nicht zurueck.
                // Ohne diesen Schnappschuss gaebe es keinen Rueckweg.
                ziele.forEach(function (z) {
                    schnappschuss.push({
                        blatt: z.a.blatt || '',
                        adresse: z.a.adresse,
                        formeln: JSON.parse(JSON.stringify(z.r.formulas || []))
                    });
                });

                ziele.forEach(function (z) {
                    var zeilen = z.r.rowCount || 1;
                    var spalten = z.r.columnCount || 1;
                    if (z.a.formel) {
                        if (zeilen === 1 && spalten === 1) {
                            z.r.formulas = [[z.a.formel]];
                        } else if (_kann19) {
                            // Excel rechnet die Bezuege selbst um – der
                            // verlaesslichste Weg, wenn er verfuegbar ist.
                            var erste = z.r.getCell(0, 0);
                            erste.formulas = [[z.a.formel]];
                            z._fuellen = true;
                        } else {
                            var m = [];
                            for (var i = 0; i < zeilen; i++) {
                                var reihe = [];
                                for (var j = 0; j < spalten; j++) {
                                    reihe.push(formelVerschieben(z.a.formel, i, j));
                                }
                                m.push(reihe);
                            }
                            z.r.formulas = m;
                        }
                    } else {
                        var w = z.a.wert === undefined ? '' : z.a.wert;
                        var mv = [];
                        for (var k = 0; k < zeilen; k++) {
                            var rw = [];
                            for (var l = 0; l < spalten; l++) rw.push(w);
                            mv.push(rw);
                        }
                        z.r.values = mv;
                    }
                });
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
                                if (typeof c === 'string' && /^#(NAME\?|REF!|VALUE!|DIV\/0!|N\/A|NUM!|NULL!|BEZUG!|WERT!|NAME\?)/.test(c)) {
                                    kaputt.push(z.a.adresse + ': ' + c);
                                }
                            });
                        });
                    });
                    return { schnappschuss: schnappschuss, kaputt: kaputt };
                });
            });
        }).then(function (erg) {
            _rueckgaengig = erg.schnappschuss;
            var u = $('xl-undo');
            if (u) u.style.display = '';
            _vorschlag = null;
            if (erg.kaputt.length) {
                // Nicht stillschweigend stehen lassen: der Benutzer soll
                // entscheiden, ob er es behaelt oder zurueckdreht.
                _verlauf.push({
                    rolle: 'bot', fehler: true,
                    text: T('xl.err_cells', 'Achtung – diese Zellen zeigen einen Fehlerwert:') +
                        '\n' + erg.kaputt.slice(0, 10).join('\n') + '\n\n' +
                        T('xl.err_hint', 'Du kannst die Änderung mit „Letzte Änderung zurücknehmen" rückgängig machen.')
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
            setzeLaeuft(false);
        });
    }

    function rueckgaengig() {
        if (!_rueckgaengig || !_rueckgaengig.length) return;
        frage(T('xl.undo_ask', 'Die zuletzt geschriebenen Zellen auf ihren vorherigen Inhalt zurücksetzen?'),
            T('xl.undo_yes', 'Zurücknehmen'), true).then(function (ja) {
                if (!ja) return;
                setzeLaeuft(true);
                Excel.run(function (ctx) {
                    _rueckgaengig.forEach(function (s) {
                        var sh = s.blatt ? ctx.workbook.worksheets.getItem(s.blatt)
                            : ctx.workbook.worksheets.getActiveWorksheet();
                        // `formulas` stellt BEIDES wieder her: eine Zelle mit
                        // festem Wert traegt dort schlicht diesen Wert.
                        sh.getRange(s.adresse).formulas = s.formeln;
                    });
                    return ctx.sync();
                }).then(function () {
                    _rueckgaengig = null;
                    var u = $('xl-undo');
                    if (u) u.style.display = 'none';
                    melde('xl-status', T('xl.undone', 'Änderung zurückgenommen.'), 'ok');
                }).catch(function (e) {
                    melde('xl-status', T('xl.undo_failed', 'Zurücknehmen fehlgeschlagen:') +
                        ' ' + String(e && e.message || e), 'fehler');
                }).then(function () { setzeLaeuft(false); });
            });
    }

    function setzeLaeuft(an) {
        var s = $('xl-send');
        if (s) {
            s.disabled = !!an;
            s.textContent = an ? T('xl.working', 'Arbeitet …') : T('xl.send', 'Fragen');
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
        if ((e = $('xl-undo'))) e.addEventListener('click', rueckgaengig);
        if ((e = $('xl-logout'))) e.addEventListener('click', abmelden);
        if ((e = $('xl-frage'))) e.addEventListener('keydown', function (ev) {
            // Strg+Enter sendet; Enter allein macht einen Zeilenumbruch – eine
            // Frage an eine Tabelle ist oft mehrzeilig.
            if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) {
                ev.preventDefault();
                fragen();
            }
        });
        if ((e = $('xl-theme'))) e.addEventListener('click', function () {
            if (window.toggleTheme) window.toggleTheme();
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
    function bootFehler(text) {
        var d = $('xl-boot-detail'), f = $('xl-boot-err');
        if (d) d.classList.remove('hidden');
        if (f) f.textContent = text || '';
    }

    function start() {
        // JEDER Schritt einzeln abgesichert. Bis 2026-08-21 brach `start()`
        // beim ersten Fehler ab – und weil Anmeldung UND App verborgen
        // starten, blieb dann ein WEISSES Fenster ohne jede Meldung zurueck
        // (genau so gemeldet). Ein Teilausfall darf hoechstens eine Funktion
        // kosten, nie die ganze Anzeige.
        try { binden(); } catch (e) { }

        // Ohne `fetch` kann das Fenster nichts abrufen – aber es muss das
        // SAGEN statt leer zu bleiben. Der Aufruf in `versionPruefen()` waere
        // sonst ein ReferenceError, der `start()` vor jeder Anzeige beendet.
        if (typeof fetch !== 'function') {
            bootFehler(T('xl.no_fetch',
                'Dieses Aufgabenfenster läuft in einer veralteten Browser-Umgebung. Nötig ist Excel 2019 oder Microsoft 365 (mit WebView2).'));
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
