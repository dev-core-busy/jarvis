/* ═══════════════════════════════════════════════════════════════════
   Spracheingabe ueber den EIGENEN Server (Whisper lokal, /api/stt)

   Vorher nutzten chat.js und avatar.js window.SpeechRecognition – Chrome
   und Edge schicken das Audio dabei an die Cloud von Google bzw. Microsoft.
   Hier nimmt der Browser nur auf (MediaRecorder), erkannt wird auf dem
   Jarvis-Server; die Aufnahme verlaesst die Installation nicht.

   Ablauf: Mikrofon an -> Pegel beobachten -> nach einer Sprechpause (oder
   per stoppen()) Aufnahme beenden -> Blob an /api/stt -> onText(text).
   Ohne erkannte Sprache wird gar nichts hochgeladen.

   API:  JarvisSTT.verfuegbar() -> bool
         JarvisSTT.starten({ token, lang, onStart, onVerarbeitung, onText, onFehler, onEnde })
   onVerarbeitung: Aufnahme ist zu Ende, der Server erkennt gerade (kann auf
   einer CPU-Installation mehrere Sekunden dauern – die Oberflaeche soll dann
   NICHT mehr "Aufnahme laeuft" zeigen).
             -> { stoppen(), abbrechen() }
   Fehlercodes fuer onFehler(code, detail): 'kein_zugriff', 'kein_mikrofon',
   'nicht_unterstuetzt', 'keine_sprache', 'server'.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var PEGEL_SPRACHE = 0.02;     // RMS ab dem ein Rahmen als Sprache zaehlt
    var PAUSE_MS = 1500;          // Stille nach Sprache -> Ende
    var WARTEN_MS = 8000;         // gar keine Sprache -> aufgeben
    var MAX_MS = 60000;           // harte Obergrenze je Aufnahme

    function verfuegbar() {
        return !!(window.MediaRecorder && navigator.mediaDevices
                  && navigator.mediaDevices.getUserMedia);
    }

    function mimeWaehlen() {
        var kandidaten = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];
        for (var i = 0; i < kandidaten.length; i++) {
            try { if (MediaRecorder.isTypeSupported(kandidaten[i])) return kandidaten[i]; } catch (e) {}
        }
        return '';
    }

    function starten(opt) {
        opt = opt || {};
        var fertig = false, abgebrochen = false, sprache = false;
        var stream = null, rec = null, ctx = null, timer = null;
        var teile = [], t0 = Date.now(), letzteSprache = 0;

        function melde(name) {
            var f = opt[name];
            if (typeof f === 'function') {
                try { f.apply(null, Array.prototype.slice.call(arguments, 1)); } catch (e) {}
            }
        }
        function aufraeumen() {
            if (timer) { clearInterval(timer); timer = null; }
            if (ctx) { try { ctx.close(); } catch (e) {} ctx = null; }
            if (stream) {
                stream.getTracks().forEach(function (t) { try { t.stop(); } catch (e) {} });
                stream = null;
            }
        }
        function beenden(fehler, detail) {
            if (fertig) return;
            fertig = true;
            aufraeumen();
            if (fehler) melde('onFehler', fehler, detail);
            melde('onEnde');
        }
        function stoppen() {
            if (fertig) return;
            if (rec && rec.state !== 'inactive') { try { rec.stop(); } catch (e) { beenden('server'); } }
            else beenden();
        }
        function abbrechen() {
            abgebrochen = true;
            stoppen();
        }

        function hochladen() {
            melde('onVerarbeitung');
            var typ = (rec && rec.mimeType) || 'audio/webm';
            var blob = new Blob(teile, { type: typ });
            var lang = opt.lang === 'en' ? 'en' : (opt.lang === 'de' ? 'de' : '');
            fetch('/api/stt' + (lang ? '?lang=' + lang : ''), {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + (opt.token || ''), 'Content-Type': typ.split(';')[0] },
                body: blob
            }).then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (d) { return { ok: r.ok, d: d || {} }; });
            }).then(function (res) {
                if (!res.ok) { beenden('server', res.d.detail || ''); return; }
                var text = String(res.d.text || '').trim();
                if (!text) { beenden('keine_sprache'); return; }
                melde('onText', text);
                beenden();
            }).catch(function (e) { beenden('server', String(e && e.message || e)); });
        }

        if (!verfuegbar()) {
            setTimeout(function () { beenden('nicht_unterstuetzt'); }, 0);
            return { stoppen: stoppen, abbrechen: abbrechen };
        }

        navigator.mediaDevices.getUserMedia({ audio: true }).then(function (s) {
            stream = s;
            if (fertig) { aufraeumen(); return; }   // vor der Freigabe abgebrochen
            var mime = mimeWaehlen();
            rec = mime ? new MediaRecorder(s, { mimeType: mime }) : new MediaRecorder(s);
            rec.ondataavailable = function (e) { if (e.data && e.data.size) teile.push(e.data); };
            rec.onstop = function () {
                aufraeumen();
                if (abgebrochen) { beenden(); return; }
                // Nie hochladen, was nur Stille war – spart den Whisper-Lauf
                // und verhindert erfundene Saetze aus Rauschen.
                if (!sprache || !teile.length) { beenden('keine_sprache'); return; }
                hochladen();
            };
            rec.start();
            melde('onStart');

            // Pegelmessung fuer das automatische Ende. Ohne AudioContext bleibt
            // nur die harte Obergrenze bzw. ein zweiter Klick.
            var AC = window.AudioContext || window.webkitAudioContext;
            var analyser = null, puffer = null;
            if (AC) {
                try {
                    ctx = new AC();
                    // Entsteht erst nach der Mikrofon-Freigabe (ausserhalb des Klicks) –
                    // ein angehaltener Kontext liefert nur Nullen, die Aufnahme
                    // endete dann nach WARTEN_MS als "keine Sprache".
                    if (ctx.state === 'suspended' && ctx.resume) ctx.resume().catch(function () {});
                    analyser = ctx.createAnalyser();
                    analyser.fftSize = 1024;
                    ctx.createMediaStreamSource(s).connect(analyser);
                    puffer = new Float32Array(analyser.fftSize);
                } catch (e) { analyser = null; sprache = true; }
            } else {
                sprache = true;
            }
            timer = setInterval(function () {
                var jetzt = Date.now();
                if (analyser) {
                    analyser.getFloatTimeDomainData(puffer);
                    var summe = 0;
                    for (var i = 0; i < puffer.length; i++) summe += puffer[i] * puffer[i];
                    if (Math.sqrt(summe / puffer.length) >= PEGEL_SPRACHE) {
                        sprache = true;
                        letzteSprache = jetzt;
                    }
                    if (sprache && letzteSprache && jetzt - letzteSprache > PAUSE_MS) { stoppen(); return; }
                    if (!sprache && jetzt - t0 > WARTEN_MS) { stoppen(); return; }
                }
                if (jetzt - t0 > MAX_MS) stoppen();
            }, 100);
        }).catch(function (e) {
            var name = e && e.name;
            beenden(name === 'NotAllowedError' || name === 'SecurityError' ? 'kein_zugriff'
                    : (name === 'NotFoundError' ? 'kein_mikrofon' : 'server'),
                    String(e && e.message || e));
        });

        return { stoppen: stoppen, abbrechen: abbrechen };
    }

    window.JarvisSTT = { verfuegbar: verfuegbar, starten: starten };
})();
