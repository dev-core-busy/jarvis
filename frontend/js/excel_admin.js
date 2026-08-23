/* ═══════════════════════════════════════════════════════════════════════
   Einstellungen → Excel: Add-in verteilen und Grenzen pflegen.

   Der Reiter hat zwei Aufgaben, und die erste ist die wichtigere:

   1. **Das Manifest zum Verteilen bereitstellen.** Anders als beim
      Outlook-Add-in gibt es keinen Exchange-Katalog, der die Datei ausrollt –
      Add-ins fuer Arbeitsmappen verteilt ein Exchange nicht. Der Administrator
      legt sie in einen Netzwerkordner, den die Arbeitsplaetze als
      vertrauenswuerdigen Katalog eintragen. Ohne diesen Knopf muesste er die
      URL kennen; das ist genau die Art verstecktes Wissen, die eine Funktion
      unbenutzbar macht.

   2. Die beiden Grenzwerte des Skills pflegen.

   WARUM DER DOWNLOAD EIN <a> IST UND KEIN fetch: der Endpunkt liefert
   `Content-Disposition: attachment` samt Branding-Dateinamen. Ein Umweg ueber
   fetch + Blob muesste den Dateinamen selbst bilden – und liefe damit dem
   Branding hinterher. Im Hochlade-Modus (unten) wird deshalb der Dateiname AUS
   DEM ANTWORTKOPF gelesen, nicht nachgebaut.

   DER KNOPF HAT ZWEI ZUSTAENDE (seit 2026-08-23, gemeldet):
   Ist ein Katalogpfad gespeichert, ist "herunterladen" die falsche Ansage – die
   Datei soll ja nicht in den Download-Ordner, sondern in genau diese Freigabe.
   Dann heisst der Knopf "Manifest hochladen" und oeffnet ein
   Speichern-unter-Fenster (File System Access API), das direkt dorthin
   schreibt. Massgeblich ist der GESPEICHERTE Pfad, nicht der Feldinhalt: der
   Knopf soll den Zustand zeigen, den auch `/excel` den Benutzern zeigt.

   WAS DIESER WEG NICHT KANN, und warum der Hinweistext es ausspricht: der
   Zielordner laesst sich im Dialog **nicht vorbelegen**. `startIn` nimmt nur
   Standardordner ("desktop", "documents", …), `suggestedName` keine
   Pfadtrenner. Deshalb daneben ein "Pfad kopieren"-Knopf – im Windows-Dialog
   fuehrt der eingefuegte Pfad im Feld "Dateiname" per Enter in den Ordner.
   Eine Zusage "landet automatisch dort" waere unhaltbar; der Server erreicht
   die Freigabe nicht, nur der Arbeitsplatz tut das.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var SKILL = 'excel-addin';
    var _gebunden = false;
    var _laeuft = false;
    // Der GESPEICHERTE Katalogpfad (nicht der Feldinhalt) – er entscheidet ueber
    // die Betriebsart des Knopfes.
    var _katalog = '';
    // Der Server hat den Abruf abgelehnt (localhost-Basis). Dann darf auch der
    // Hochlade-Weg nichts tun: er wuerde eine Datei in die Freigabe legen, die
    // auf jedem Arbeitsplatz ins Leere zeigt.
    var _adresseKaputt = false;
    var _DL_TEXT = 'Manifest herunterladen';
    var _UP_TEXT = 'Manifest hochladen';

    function $(id) { return document.getElementById(id); }
    function token() {
        try { return localStorage.getItem('jarvis_token') || ''; } catch (e) { return ''; }
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

    /* Die Manifest-Version kommt vom Server. Sie steht auch im Manifest selbst,
       aber ein Administrator soll sie sehen, OHNE die Datei zu oeffnen – sonst
       ist "habe ich die aktuelle verteilt?" nicht beantwortbar. */
    function ladeVersion() {
        fetch('/api/excel-addin/version', { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.version) {
                    melde('xa-version', 'Manifest-Fassung ' + d.version);
                }
            }).catch(function () { });
    }

    /* Ein Manifest, das ueber "localhost" abgerufen wurde, zeigt auf jedem
       Arbeitsplatz ins Leere – Excel installiert es klaglos, das Fenster bleibt
       danach leer. Der Server weist den Abruf deshalb ab (HTTP 400); hier wird
       der Grund SICHTBAR gemacht, statt den Administrator eine kaputte Datei
       verteilen zu lassen. */
    function pruefeAdresse() {
        var warn = $('xa-warn');
        var dl = $('xa-download');
        if (!warn) return;
        fetch('/excel-addin/manifest.xml', { method: 'GET', cache: 'no-store' })
            .then(function (r) {
                if (r.ok) { _adresseKaputt = false; warn.style.display = 'none'; return; }
                return r.json().catch(function () { return {}; }).then(function (d) {
                    _adresseKaputt = true;
                    warn.textContent = '⚠ ' + (d.error ||
                        'Das Manifest kann über diese Adresse nicht erzeugt werden.');
                    warn.style.color = 'var(--danger)';
                    warn.style.display = '';
                    if (dl) { dl.style.opacity = '.5'; dl.style.pointerEvents = 'none'; }
                });
            }).catch(function () { });
    }

    /* Kann dieser Browser in einen frei gewaehlten Ordner schreiben?
       Die File System Access API gibt es in Chrome und Edge, NICHT in Firefox
       und Safari – und nur im sicheren Kontext. Ohne sie bleibt es beim
       Download; das ist kein Fehler, sondern der Normalfall dieser Browser, und
       der Hinweistext sagt es. */
    function kannSpeichern() {
        return typeof window.showSaveFilePicker === 'function';
    }

    /* Beschriftung, Zusatzknopf und Hinweis an den gespeicherten Pfad
       anpassen. MUSS nach JEDEM Speichern des Pfades laufen – sonst bewirbt der
       Knopf weiter einen Download, waehrend `/excel` den Benutzern bereits die
       Freigabe nennt. */
    function knopfAktualisieren() {
        var dl = $('xa-download');
        var copy = $('xa-pfad-copy');
        var hint = $('xa-dl-hint');
        var hoch = !!_katalog && kannSpeichern();
        if (dl) dl.textContent = hoch ? _UP_TEXT : _DL_TEXT;
        if (copy) copy.style.display = _katalog ? '' : 'none';
        if (!hint) return;
        if (hoch) {
            hint.innerHTML = 'Der Knopf öffnet ein <b>Speichern unter</b>-Fenster mit dem ' +
                'fertigen Manifest. <b>Der Zielordner lässt sich technisch nicht ' +
                'vorbelegen</b> – fügen Sie den Pfad im Dialog in das Feld ' +
                '<b>Dateiname</b> ein und drücken Sie Enter, dann sind Sie im Ordner. ' +
                'Der Knopf <b>Pfad kopieren</b> legt ihn dafür in die Zwischenablage.';
            hint.style.color = '';
            hint.style.display = '';
        } else if (_katalog) {
            hint.innerHTML = 'Ihr Browser kann nicht direkt in einen Ordner schreiben – das ' +
                'können nur <b>Chrome und Edge</b>. Laden Sie das Manifest herunter und ' +
                'legen Sie es von Hand in den Katalog-Ordner.';
            hint.style.color = '';
            hint.style.display = '';
        } else {
            hint.style.display = 'none';
        }
    }

    /* Dateiname aus dem Antwortkopf statt nachgebaut – so folgt er dem Branding
       ohne zweite Fassung derselben Regel im Frontend. Der Rueckfall greift nur,
       wenn der Kopf fehlt. */
    function dateinameAus(antwort) {
        var cd = '';
        try { cd = antwort.headers.get('content-disposition') || ''; } catch (e) { }
        var m = /filename\*=utf-8''([^;]+)/i.exec(cd);
        if (m) { try { return decodeURIComponent(m[1].trim()); } catch (e) { } }
        m = /filename="([^"]+)"/i.exec(cd) || /filename=([^;]+)/i.exec(cd);
        if (m) return m[1].trim();
        return 'jarvis-excel-addin.xml';
    }

    /* ERST holen, DANN den Dialog oeffnen – nicht umgekehrt.
       Der Picker legt die Zieldatei bereits beim Auswaehlen an; scheiterte
       danach der Abruf, laege eine 0-Byte-Datei im Katalog und Excel meldete den
       Arbeitsplaetzen ein ungueltiges Manifest. Der Preis: die Benutzergeste
       kann theoretisch ablaufen (Chrome: ~5 s). Das Manifest wird lokal erzeugt
       und ist in Millisekunden da; tritt es doch ein, sagt die Meldung
       ausdruecklich, dass ein erneuter Klick genuegt. */
    function hochladen() {
        if (_adresseKaputt) return;
        melde('xa-dl-status', 'Manifest wird geholt …');
        var name = 'jarvis-excel-addin.xml';
        fetch('/excel-addin/manifest.xml', { cache: 'no-store' })
            .then(function (r) {
                if (!r.ok) {
                    return r.json().catch(function () { return {}; }).then(function (d) {
                        throw new Error(d.error || 'HTTP ' + r.status);
                    });
                }
                name = dateinameAus(r);
                return r.blob();
            })
            .then(function (blob) {
                melde('xa-dl-status', '');
                return window.showSaveFilePicker({
                    suggestedName: name,
                    types: [{
                        description: 'Office-Add-in-Manifest',
                        accept: { 'application/xml': ['.xml'] }
                    }]
                }).then(function (handle) {
                    return handle.createWritable().then(function (w) {
                        return w.write(blob).then(function () { return w.close(); });
                    }).then(function () { return handle.name || name; });
                });
            })
            .then(function (geschrieben) {
                // Die FOLGE benennen, nicht nur "gespeichert": ob die Datei im
                // richtigen Ordner gelandet ist, sieht man von hier aus nicht –
                // der Browser gibt den Pfad nicht heraus.
                melde('xa-dl-status', '✓ ' + geschrieben + ' geschrieben – im Katalog-Ordner ' +
                      'sehen die Arbeitsplätze sie beim nächsten Excel-Start.', 'ok');
                setTimeout(function () { melde('xa-dl-status', ''); }, 12000);
            })
            .catch(function (e) {
                // Abbrechen im Dialog ist KEIN Fehler – eine rote Meldung darauf
                // wuerde eine bewusste Entscheidung als Stoerung ausgeben.
                if (e && (e.name === 'AbortError' || e.code === 20)) {
                    melde('xa-dl-status', '');
                    return;
                }
                var txt = (e && e.message) || String(e);
                if (e && e.name === 'SecurityError') {
                    txt = 'Der Speichern-Dialog ließ sich nicht öffnen. Bitte den Knopf ' +
                          'noch einmal drücken.';
                }
                melde('xa-dl-status', 'Fehler: ' + txt, 'fehler');
            });
    }

    /* Der Pfad in die Zwischenablage – ohne ihn ist der Dialog eine Sucherei.
       Gleiche Rueckmeldung wie auf der Benutzerseite (`xp-pfad-copy`): in der
       Zwischenablage ist nichts sichtbar, ein stiller Klick sieht wie ein
       wirkungsloser aus. `navigator.clipboard` fehlt in unsicherem Kontext. */
    function pfadKopieren() {
        var schief = function () {
            melde('xa-dl-status', 'Kopieren nicht möglich – Pfad im Feld markieren ' +
                  'und mit Strg+C kopieren.', 'fehler');
        };
        var fertig = function () {
            melde('xa-dl-status', 'Pfad kopiert.', 'ok');
            setTimeout(function () { melde('xa-dl-status', ''); }, 4000);
        };
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(_katalog).then(fertig, schief);
            } else { schief(); }
        } catch (e) { schief(); }
    }

    function ladeGrenzen() {
        return fetch('/api/skills/' + SKILL + '/config', { headers: kopf() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                // Der Endpunkt antwortet VERSCHACHTELT ({config: {...}}). Genau
                // das wurde am 2026-08-12 beim E-Mail-Reiter uebersehen: eine
                // Ebene zu hoch gegriffen, alle Felder undefined – und das
                // naechste Speichern schrieb die Leere fest.
                var c = (d && d.config) || {};
                var r1 = $('xa-l-runden'); if (r1) r1.value = c.max_runden || 3;
                var r2 = $('xa-l-aenderungen'); if (r2) r2.value = c.max_aenderungen || 200;
                var k = $('xa-katalog');
                // `|| ''` waere hier richtig, `|| vorgabe` nicht: ein leerer
                // Pfad ist die AUSSAGE "wir verteilen nicht zentral".
                _katalog = String(c.katalog_pfad || '').trim();
                if (k) k.value = _katalog;
                knopfAktualisieren();
            }).catch(function () { });
    }

    /* Eigener Knopf, eigene Teilmenge. `update_skill_config` merged – ein Knopf,
       der den ganzen Formularstand schickt, ueberschriebe den jeweils anderen
       Teil (Lehre von den SAP-Sichtbarkeiten und den beiden E-Mail-Knoepfen). */
    function speichereKatalog() {
        if (_laeuft) return;
        _laeuft = true;
        var feld = $('xa-katalog');
        var pfad = (feld ? feld.value : '').trim();
        melde('xa-katalog-status', 'Speichert …');
        fetch('/api/skills/' + SKILL + '/config', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ katalog_pfad: pfad })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            // Erst JETZT gilt der Pfad – und mit ihm die Betriebsart des Knopfes
            // darueber. Ohne diesen Aufruf bewuerbe er weiter einen Download,
            // waehrend /excel den Benutzern schon die Freigabe nennt.
            _katalog = pfad;
            knopfAktualisieren();
            // Die Folge benennen, nicht nur "gespeichert": der Knopf schaltet
            // die Benutzerseite zwischen Download und Pfad um, und das sieht
            // man von hier aus nicht.
            melde('xa-katalog-status', pfad
                ? 'Gespeichert – /excel zeigt jetzt diesen Pfad statt des Downloads.'
                : 'Gespeichert – /excel bietet wieder den Download an.', 'ok');
            setTimeout(function () { melde('xa-katalog-status', ''); }, 5000);
        }).catch(function (e) {
            melde('xa-katalog-status', 'Fehler: ' + (e && e.message || e), 'fehler');
        }).then(function () { _laeuft = false; });
    }

    function speichere() {
        if (_laeuft) return;
        _laeuft = true;
        melde('xa-save-status', 'Speichert …');
        var runden = parseInt(($('xa-l-runden') || {}).value, 10);
        var aend = parseInt(($('xa-l-aenderungen') || {}).value, 10);
        if (!(runden >= 1 && runden <= 5)) runden = 3;
        if (!(aend >= 10 && aend <= 500)) aend = 200;
        // NUR die eigenen Felder senden. `update_skill_config` merged – ein
        // Knopf, der den ganzen Formularstand schickt, ueberschriebe fremde
        // Teile der Konfiguration (Lehre von den SAP-Sichtbarkeiten).
        fetch('/api/skills/' + SKILL + '/config', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ max_runden: runden, max_aenderungen: aend })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            melde('xa-save-status', 'Gespeichert.', 'ok');
            setTimeout(function () { melde('xa-save-status', ''); }, 3000);
        }).catch(function (e) {
            melde('xa-save-status', 'Fehler: ' + (e && e.message || e), 'fehler');
        }).then(function () { _laeuft = false; });
    }

    function binde() {
        if (_gebunden) return;
        _gebunden = true;
        // Klapp-Container verdrahten. MUSS hier passieren: das Markup traegt nur
        // die Klassen, gebunden wird ueber _collapseInit in app.js – das merkt
        // sich zusaetzlich den Auf-/Zu-Zustand je Container.
        if (window.initExcelCollapse) window.initExcelCollapse();
        var b = $('xa-save');
        if (b) b.addEventListener('click', speichere);
        var kb = $('xa-katalog-save');
        if (kb) kb.addEventListener('click', speichereKatalog);
        // EIN Handler fuer beide Betriebsarten, der den Modus selbst prueft.
        // Listener je nach Zustand an- und abzuhaengen ist die Variante, bei der
        // irgendwann zwei gebunden sind und der Klick doppelt feuert.
        var dl = $('xa-download');
        if (dl) dl.addEventListener('click', function (ev) {
            if (!(_katalog && kannSpeichern())) return;   // normaler Download
            ev.preventDefault();
            hochladen();
        });
        var pc = $('xa-pfad-copy');
        if (pc) pc.addEventListener('click', pfadKopieren);
        var g = $('xa-guide-btn');
        if (g) {
            g.addEventListener('click', function () {
                var box = $('xa-guide');
                if (!box) return;
                var auf = box.style.display !== 'none';
                box.style.display = auf ? 'none' : '';
                g.setAttribute('aria-expanded', auf ? 'false' : 'true');
                // Ein Umschalter mit unveraenderlicher Beschriftung sieht beim
                // Zuklappen wie ein wirkungsloser Klick aus (Lehre vom
                // Broker-Audit-Knopf).
                g.textContent = auf ? 'Anleitung für den Arbeitsplatz anzeigen'
                                    : 'Anleitung ausblenden';
            });
        }
    }

    window.ExcelAdmin = {
        onShow: function () {
            binde();
            ladeVersion();
            ladeGrenzen();
            pruefeAdresse();
        }
    };
})();
