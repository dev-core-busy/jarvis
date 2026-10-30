/* BSI H4 (CSP ohne Inline-Skript, 2026-10-04): bisher Inline-<script> in
   frontend/portal.html. Eine CSP mit script-src 'self' blockiert Inline-Skripte -
   deshalb hier als Datei, an DERSELBEN Stelle synchron eingebunden
   (kein defer/async): Zeitpunkt und Reihenfolge bleiben gleich. */
(function () {
    var KEYS = window.JarvisSitzung.tokenSchluessel();
    function tok() { for (var i=0;i<KEYS.length;i++){var v=localStorage.getItem(KEYS[i]); if(v) return v;} return ''; }
    var t = tok();
    if (!t) { window.location.replace('/'); return; }
    var H = { 'Authorization': 'Bearer ' + t };
    // Ist der Benutzer-Chat-Skill an? Kommt aus /api/me (permissions.userchat)
    // und steuert Kachel UND Ungelesen-Poll. Hier oben deklariert, damit die
    // Reihenfolge nicht von der Hebung einer spaeteren var abhaengt.
    var _ucAn = false;

    /* ── Sitzung beenden (eine Stelle fuer alle Aufrufer) ──────────────────
       Tokens sind zustandslos und 30 Tage gueltig. Faellt die Berechtigung
       serverseitig weg (401 / 403 NOT_AUTHORIZED), merkt der offene Tab davon
       von sich aus NICHTS – er zeigt einfach ein halb leeres Portal. Deshalb
       wird die Sitzung hier aktiv beendet, statt den Fehler zu verschlucken. */
    var _raus = false;
    function sitzungBeenden() {
        if (_raus) return;            // mehrere Aufrufe laufen parallel
        _raus = true;
        KEYS.forEach(function(k){ try { localStorage.removeItem(k); } catch (e) {} });
        window.location.replace('/');
    }

    /* ── Hinweis, wenn ein Bereich NICHT geprueft werden konnte ────────────
       Eine Kachel, die wegen eines Netzfehlers oder eines Neustarts fehlt,
       sieht exakt aus wie eine fehlende Berechtigung. Der Unterschied ist fuer
       den Benutzer nicht erkennbar – und genau daran ist die Wissen-Kachel
       "oft nicht da" aufgefallen. Wir behaupten deshalb nicht "kein Zugriff",
       sondern sagen, dass wir es nicht wissen, und bieten den Weg zurueck. */
    function ladefehlerZeigen() {
        var b = document.getElementById('pt-load-banner');
        if (!b || b.style.display === '') return;   // schon sichtbar
        b.textContent = '\u26A0 ' + (window.t ? window.t('portal.load_failed')
            : 'Einige Bereiche konnten nicht geprüft werden – hier klicken, um es erneut zu versuchen.');
        b.style.display = '';
        b.addEventListener('click', function(){ window.location.reload(); });
    }

    /* ── Ein Abruf, der seinen Fehlschlag NICHT verschluckt ────────────────
       * 401 / 403 NOT_AUTHORIZED -> Sitzung beenden (wie /api/me),
       * 403 ACCOUNT_BLOCKED      -> Sperr-Bildschirm,
       * 5xx oder Netzfehler      -> EINMAL nachfassen (ein Deploy dauert
         Sekunden; auf ECHT wurde in einer Woche 101x neu gestartet), danach
         den Hinweis zeigen.
       Rueckgabe: Promise auf die Daten oder null. `null` heisst ausdruecklich
       "unbekannt", nicht "nicht berechtigt". */
    function holeGeschuetzt(url, _zweiter) {
        return fetch(url, { headers: H }).then(function(r){
            if (r.status === 401) { sitzungBeenden(); return null; }
            if (r.status === 403) {
                return r.json().catch(function(){ return {}; }).then(function(e){
                    if (e && e.detail === 'ACCOUNT_BLOCKED') {
                        if (window.SecurityIncidents) window.SecurityIncidents.fetchAndShowBlocked();
                    } else {
                        sitzungBeenden();
                    }
                    return null;
                });
            }
            if (r.ok) return r.json().catch(function(){ return null; });
            // 5xx & Co: der Server lebt, konnte aber nicht antworten.
            if (_zweiter) { ladefehlerZeigen(); return null; }
            return new Promise(function(ok){ setTimeout(ok, 1500); })
                .then(function(){ return holeGeschuetzt(url, true); });
        }).catch(function(){
            // Netzfehler (Dienst startet gerade neu, Verbindung weg).
            if (_zweiter) { ladefehlerZeigen(); return null; }
            return new Promise(function(ok){ setTimeout(ok, 1500); })
                .then(function(){ return holeGeschuetzt(url, true); });
        });
    }

    // Sicherheitsschicht (in holeGeschuetzt): gesperrtes Konto -> Sperr-Bildschirm,
    // entzogene Anmeldeberechtigung (401 / 403 NOT_AUTHORIZED) -> abmelden + zur
    // Loginseite. Der 401-Fall fehlte hier bisher und endete in `null`: der
    // Benutzer sah ein halb leeres Portal, ohne zu erfahren, dass seine Sitzung
    // nicht mehr gilt.
    holeGeschuetzt('/api/me').then(function(d){
        if (!d) return;
        if (d.username) {
            var n = document.getElementById('pt-name'); if (n) n.textContent = ', ' + d.username;
            var lo2 = document.getElementById('pt-logout'); if (lo2) lo2.title = d.username + ' ' + (window.t ? window.t('portal.logout_suffix') : 'abmelden');
        }
        // SAP-Analysen: nur fuer freigegebene Benutzer UND nur wenn der
        // Bereich aktiv ist (beides steckt in permissions.sap).
        if (d.permissions && d.permissions.sap) {
            var sapCard = document.getElementById('pt-card-sap');
            if (sapCard) sapCard.classList.remove('hidden');
        }
        // VEMAS-Bereich: dieselbe Logik (Freigabe UND aktiver Skill).
        if (d.permissions && d.permissions.vemas) {
            var vemasCard = document.getElementById('pt-card-vemas');
            if (vemasCard) vemasCard.classList.remove('hidden');
        }
        // E-Mail-Bereich: dieselbe Logik (Freigabe UND aktiver Skill).
        if (d.permissions && d.permissions.email) {
            var mailCard = document.getElementById('pt-card-email');
            if (mailCard) mailCard.classList.remove('hidden');
        }
        // Excel-Assistent: Freigabe UND aktiver Skill (wie sap/email).
        if (d.permissions && d.permissions.excel) {
            var xlCard = document.getElementById('pt-card-excel');
            if (xlCard) xlCard.classList.remove('hidden');
        }
        // Claude Subagent: Freigabe UND aktiver Skill (wie sap/email/excel).
        if (d.permissions && d.permissions.claudesub) {
            var csCard = document.getElementById('pt-card-claudesub');
            if (csCard) csCard.classList.remove('hidden');
        }
        // Short Tracks: haengt NUR am Skill-Zustand (keine eigene Freigabe).
        if (d.permissions && d.permissions.tracks) {
            var trCard = document.getElementById('pt-card-tracks');
            if (trCard) trCard.classList.remove('hidden');
            refreshTracks();
        }
        // AI-Maus: Freigabe UND aktiver Skill.
        if (d.permissions && d.permissions.ai_mouse) {
            var amCard = document.getElementById('pt-card-aimouse');
            if (amCard) amCard.classList.remove('hidden');
        }
        // Feedback: Freigabe UND aktiver Skill.
        if (d.permissions && d.permissions.feedback) {
            var fbCard = document.getElementById('pt-card-feedback');
            if (fbCard) fbCard.classList.remove('hidden');
        }
        // Newsfeed: haengt NUR am Skill-Zustand (Meldungen fuer alle). Die
        // Kachel blendet newsfeed.js erst ein, wenn es Meldungen gibt.
        if (d.permissions && d.permissions.newsfeed && window.JarvisNewsfeed) {
            window.JarvisNewsfeed.portalStart();
        }
        // Jira-Assistent: Freigabe UND aktiver Jira-Skill.
        if (d.permissions && d.permissions.jira_assist) {
            var jaCard = document.getElementById('pt-card-jiraassist');
            if (jaCard) jaCard.classList.remove('hidden');
        }
        // Confluence: haengt NUR am Skill-Zustand (keine eigene Freigabe) –
        // gleiche Logik wie beim Benutzer-Chat, Begruendung im Markup oben.
        if (d.permissions && d.permissions.confluence) {
            var cfCard = document.getElementById('pt-card-confluence');
            if (cfCard) cfCard.classList.remove('hidden');
        }
        // Benutzer-Chat: ebenfalls nur am Skill-Zustand. Der Ungelesen-Poll
        // startet ERST hier – bei ausgeschaltetem Skill antwortet
        // /api/userchat/unread mit 403, und ein Badge-Poll, der alle 30 s in
        // einen 403 laeuft, ist Laerm ohne Aussage.
        if (d.permissions && d.permissions.userchat) {
            var ucCard = document.getElementById('pt-card-userchat');
            if (ucCard) ucCard.classList.remove('hidden');
            _ucAn = true;
            refreshUnread();
        }
        // Lizenz-Warnung (nur Admin, nur wenn wirklich etwas zu melden ist:
        // Widerruf, fremde Hardware, unbrauchbarer Schlüssel, ablaufende Frist).
        // Ein Klick führt direkt in die Einstellungen – eine Warnung ohne Weg
        // zur Abhilfe ist nur Lärm.
        if (d.license_banner) {
            var lb = document.getElementById('pt-lic-banner');
            if (lb) {
                lb.textContent = '⚠ ' + d.license_banner;
                lb.style.display = '';
                lb.addEventListener('click', function(){
                    try { sessionStorage.setItem('jarvis_settings_return','/portal'); } catch(e){}
                    window.location.href = '/settings';
                });
            }
        }
        if (d.is_admin) {
            // Das Zahnrad blendet `settings_btn.js` zentral aus /api/me ein.
            // Versions-/Update-Pill (Admin) – verschoben von /chat
            var uw = document.getElementById('chat-update-wrap');
            if (uw) { uw.style.display = ''; if (window.JarvisUpdateWidget) window.JarvisUpdateWidget.init(); }
            // Desktop/VNC-Button (Admin) – verschoben von /chat
            var vb = document.getElementById('pt-vnc-btn');
            if (vb) vb.style.display = '';
            // Angemeldete Benutzer (Admin): init() blendet den Knopf selbst ein
            if (window.UserSessions) window.UserSessions.init();
            // API-Dokumentation (Admin)
            var apiCard = document.getElementById('pt-card-api');
            if (apiCard) apiCard.classList.remove('hidden');
        }
    });

    holeGeschuetzt('/api/support/status').then(function(d){
        if (d && d.active) { var c = document.getElementById('pt-card-support'); if (c) c.classList.remove('hidden'); }
    });

    // Wissen-Kachel fuer JEDEN angemeldeten Benutzer (seit 2026-10-15): die Seite
    // traegt den Container "Mein Gedaechtnis" (eigenes Gedaechtnis, BSI M9),
    // den jeder sehen muss. Bis dahin erschien sie nur mit Wissensbereich; ohne
    // einen zeigt /wissen jetzt nur diesen Container (wissen.js, _nurEigenes).
    // Ein gueltiges Scope-Ergebnis bleibt Bedingung: es belegt die Sitzung.
    // GEMELDET (2026-08-25): "die Kachel Wissen wird oft nicht angezeigt, dann hilft
    // nur logout + login". Der Abruf verschluckte JEDEN Fehlschlag – ein Neustart
    // (101 in einer Woche auf ECHT), ein Netzhaenger oder ein entzogenes Recht sahen
    // alle gleich aus: Kachel weg, keine Meldung. holeGeschuetzt() unterscheidet die
    // Faelle und fasst bei einem technischen Fehler einmal nach.
    holeGeschuetzt('/api/wissen/scope').then(function(d){
        if (d && d.ok) { var c = document.getElementById('pt-card-wissen'); if (c) c.classList.remove('hidden'); }
    });

    // Ungelesen-Badge auf der Benutzerchat-Karte. Laeuft nur, wenn der Skill
    // aktiv ist (`_ucAn`, gesetzt aus permissions.userchat) – der erste Aufruf
    // kommt von dort, nicht beim Seitenaufbau.
    function refreshUnread(){
        var badge = document.getElementById('pt-userchat-badge');
        if (!badge || !_ucAn) return;
        fetch('/api/userchat/unread', { headers: H }).then(function(r){ return r.ok ? r.json() : null; })
            .then(function(d){
                var n = (d && d.unread) || 0;
                if (n > 0) { badge.textContent = n > 99 ? '99+' : String(n); badge.classList.remove('hidden'); }
                else { badge.classList.add('hidden'); }
            }).catch(function(){});
    }

    // Short-Tracks-Zaehler: fertige, noch nicht angesehene Laeufe. Eigener,
    // winziger Endpunkt statt der vollen Auftragsliste – die enthaelt
    // Ergebnistexte und waere fuer ein Badge die teuerste Quelle.
    // Laeuft gerade etwas, steht ein Punkt im Badge: "es tut sich was" ist die
    // Aussage, eine Zahl waere hier eine Behauptung ueber Fortschritt.
    function refreshTracks(){
        var badge = document.getElementById('pt-tracks-badge');
        if (!badge) return;
        fetch('/api/tracks/count', { headers: H }).then(function(r){ return r.ok ? r.json() : null; })
            .then(function(d){
                if (!d) return;
                var n = d.neu || 0;
                if (n > 0) { badge.textContent = n > 99 ? '99+' : String(n); badge.classList.remove('hidden'); }
                else if (d.aktiv > 0) { badge.textContent = '\u00b7'; badge.classList.remove('hidden'); }
                else { badge.classList.add('hidden'); }
            }).catch(function(){});
    }

    // Beim Zurueckkehren auf die Seite (z.B. nach dem Chatten) aktualisieren
    window.addEventListener('focus', function(){ refreshUnread(); refreshTracks(); });

    var lo = document.getElementById('pt-logout');
    if (lo) lo.addEventListener('click', function(){
        // Erst dem Server sagen, DANN das Token verwerfen – sonst fehlt der
        // Anfrage die Anmeldung. `keepalive` haelt sie ueber die Navigation.
        var _p = (window.JarvisSession ? window.JarvisSession.logout() : Promise.resolve());
        KEYS.forEach(function(k){localStorage.removeItem(k);});
        _p.catch(function(){}).then(function(){ window.location.replace('/'); });
    });

    // LLM-Verbindungsstatus-Pill (wie in /chat, /userchat)
    function pollLlm(){
        var dot = document.getElementById('pt-status-dot'); if(!dot) return;
        fetch('/api/llm/active-status', { headers: H }).then(function(r){
            // Entzogene Anmeldeberechtigung / Sperre greift auch, wenn der Nutzer
            // auf dem Portal sitzen bleibt (sonst schluckt der Poll den 403 still).
            if (r.status === 403) {
                return r.json().catch(function(){ return {}; }).then(function(e){
                    if (e && e.detail === 'ACCOUNT_BLOCKED') {
                        if (window.SecurityIncidents) window.SecurityIncidents.fetchAndShowBlocked();
                    } else {
                        KEYS.forEach(function(k){ localStorage.removeItem(k); });
                        window.location.replace('/');
                    }
                    return null;
                });
            }
            return r.ok ? r.json() : null;
        }).then(function(d){
            var T = window.t || function(k){ return k; };
            if(!d){ dot.className='pt-status-dot disconnected'; dot.title=T('portal.llm_unavail'); return; }
            var reachable=(d.status==='ok'||d.status==='degraded');
            dot.className='pt-status-dot '+(reachable?'connected':'disconnected');
            var name=d.profile_name?' – '+d.profile_name:'';
            var base=(d.status==='ok'?T('sup.llm_ok'):d.status==='degraded'?T('sup.llm_degraded'):T('sup.llm_down'));
            // Zeitpunkt des letzten Zustandswechsels anzeigen (seit wann erreichbar/nicht)
            var since='';
            if(d.since){
                var dt=new Date(d.since);
                var loc=(window._lang==='en'?'en-GB':'de-DE');
                var s=dt.toLocaleString(loc,{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
                since='\n'+(reachable?T('portal.llm_since_ok'):T('portal.llm_since_down'))+s;
            }
            dot.title=base+name+since;
        }).catch(function(){ dot.className='pt-status-dot disconnected'; dot.title=(window.t?window.t('sup.llm_down'):'LLM nicht erreichbar'); });
    }
    pollLlm(); setInterval(pollLlm, 30000);

    // ── SSL-/Verbindungs-Sicherheit: Badge + Warnbanner + Zertifikat-Modal ──
    var certModal = document.getElementById('cert-modal');
    function openCert(){ if (certModal) certModal.classList.remove('hidden'); }
    function closeCert(){ if (certModal) certModal.classList.add('hidden'); }
    var _bh = document.getElementById('btn-cert-close'); if (_bh) _bh.addEventListener('click', closeCert);
    document.querySelectorAll('.cert-tab').forEach(function(btn){
        btn.addEventListener('click', function(){
            document.querySelectorAll('.cert-tab').forEach(function(b){ b.classList.remove('active'); });
            btn.classList.add('active');
            var tt = btn.getAttribute('data-cert-tab');
            ['win','linux','browser'].forEach(function(t){
                var el = document.getElementById('cert-tab-' + t);
                if (el) el.classList.toggle('hidden', t !== tt);
            });
        });
    });
    var _si = document.getElementById('security-indicator'); if (_si) _si.addEventListener('click', openCert);
    var _bhelp = document.getElementById('btn-banner-help'); if (_bhelp) _bhelp.addEventListener('click', openCert);
    var _bclose = document.getElementById('btn-close-banner');
    if (_bclose) _bclose.addEventListener('click', function(){ var b=document.getElementById('security-banner'); if(b) b.style.display='none'; try{localStorage.setItem('jarvis_cert_dismissed','true');}catch(e){} });
    (function checkSecurity(){
        var banner = document.getElementById('security-banner');
        var ind = document.getElementById('security-indicator');
        var isHttps = location.protocol === 'https:';
        var isLocal = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
        var dismissed = false; try { dismissed = localStorage.getItem('jarvis_cert_dismissed') === 'true'; } catch(e){}
        if (!isHttps && !isLocal) {
            if (banner) { var bt=document.getElementById('security-banner-text'); if(bt) bt.textContent=(window.t?window.t('panel.security_banner'):'⚠️ UNSICHERE VERBINDUNG! Bitte HTTPS verwenden.'); banner.hidden=false; banner.style.display='block'; }
            if (ind) { ind.className='security-badge'; ind.title=(window.t?window.t('panel.security_critical'):'Kritisch: Keine Verschlüsselung'); }
            if (!dismissed) setTimeout(openCert, 600);
        } else {
            if (banner) { banner.hidden=true; banner.style.display='none'; }
            if (ind) { ind.className='security-badge secure'; ind.title=(window.t?window.t('panel.security_secure'):'Gesichert'); }
        }
    })();

    // ── 2FA-Setup (verschoben von /chat) ──
    var totpModal = document.getElementById('totp-modal');
    var totpBtn = document.getElementById('btn-totp-setup');
    if (totpModal && totpBtn) {
        var tErr = document.getElementById('totp-modal-error');
        var tActive = document.getElementById('totp-active');
        var tFlow = document.getElementById('totp-setup-flow');
        var tShow = document.getElementById('totp-show-result');
        // Den angezeigten Schluessel nicht im DOM stehen lassen, sobald der Dialog
        // zu ist oder neu geoeffnet wird.
        function _totpAnzeigeLeeren() {
            tShow.classList.add('hidden');
            document.getElementById('totp-show-qr').innerHTML = '';
            document.getElementById('totp-show-secret').textContent = '';
            document.getElementById('totp-show-code').value = '';
        }
        totpBtn.addEventListener('click', function(){
            tErr.textContent=''; tActive.classList.add('hidden'); tFlow.classList.add('hidden');
            _totpAnzeigeLeeren();
            fetch('/api/auth/totp/status', { headers: H }).then(function(r){ return r.json(); }).then(function(d){
                if (d.enabled) { tActive.classList.remove('hidden'); }
                else {
                    fetch('/api/auth/totp/setup', { method:'POST', headers: H }).then(function(r){ return r.json(); }).then(function(sd){
                        document.getElementById('totp-qr').innerHTML = '<img src="'+sd.qr_code+'" alt="QR-Code">';
                        document.getElementById('totp-secret-code').textContent = sd.secret;
                        document.getElementById('totp-verify-code').value = '';
                        tFlow.classList.remove('hidden');
                    });
                }
            }).catch(function(){ tErr.textContent=(window.t?window.t('portal.conn_error'):'Verbindungsfehler'); });
            totpModal.classList.remove('hidden');
        });
        document.getElementById('btn-totp-close').addEventListener('click', function(){
            totpModal.classList.add('hidden'); _totpAnzeigeLeeren();
            document.getElementById('totp-disable-pass').value = '';
        });
        document.getElementById('btn-totp-show').addEventListener('click', function(){
            var pw = document.getElementById('totp-disable-pass').value;
            var code = document.getElementById('totp-show-code').value.trim();
            tErr.textContent = '';
            if (!pw || !code) { tErr.textContent = (window.t?window.t('totp.show_need'):'Bitte Kennwort und aktuellen Code eingeben.'); return; }
            fetch('/api/auth/totp/show', { method:'POST', headers: Object.assign({'Content-Type':'application/json'}, H), body: JSON.stringify({ password: pw, code: code }) })
                .then(function(r){ return r.json(); }).then(function(d){
                    if (d.success && d.qr_code) {
                        var img = document.createElement('img');
                        img.src = d.qr_code; img.alt = 'QR-Code';
                        var qr = document.getElementById('totp-show-qr');
                        qr.innerHTML = ''; qr.appendChild(img);
                        document.getElementById('totp-show-secret').textContent = d.secret;
                        document.getElementById('totp-show-code').value = '';
                        document.getElementById('totp-disable-pass').value = '';
                        tShow.classList.remove('hidden');
                    } else {
                        _totpAnzeigeLeeren();
                        tErr.textContent = d.error || (window.t?window.t('totp.show_failed'):'Anzeige fehlgeschlagen');
                    }
                }).catch(function(){ tErr.textContent=(window.t?window.t('portal.conn_error'):'Verbindungsfehler'); });
        });
        document.getElementById('btn-totp-verify').addEventListener('click', function(){
            var code = document.getElementById('totp-verify-code').value.trim(); if (!code) return; tErr.textContent='';
            fetch('/api/auth/totp/verify', { method:'POST', headers: Object.assign({'Content-Type':'application/json'}, H), body: JSON.stringify({ code }) })
                .then(function(r){ return r.json(); }).then(function(d){
                    if (d.success) { totpModal.classList.add('hidden'); }
                    else { tErr.textContent = d.error || (window.t?window.t('totp.verify_failed'):'Verifizierung fehlgeschlagen'); }
                }).catch(function(){ tErr.textContent=(window.t?window.t('portal.conn_error'):'Verbindungsfehler'); });
        });
        document.getElementById('btn-totp-disable').addEventListener('click', function(){
            var pw = document.getElementById('totp-disable-pass').value; if (!pw) return; tErr.textContent='';
            fetch('/api/auth/totp/disable', { method:'POST', headers: Object.assign({'Content-Type':'application/json'}, H), body: JSON.stringify({ password: pw }) })
                .then(function(r){ return r.json(); }).then(function(d){
                    if (d.success) { totpModal.classList.add('hidden'); document.getElementById('totp-disable-pass').value=''; }
                    else { tErr.textContent = d.error || (window.t?window.t('totp.disable_failed'):'Deaktivierung fehlgeschlagen'); }
                }).catch(function(){ tErr.textContent=(window.t?window.t('portal.conn_error'):'Verbindungsfehler'); });
        });
    }

    // ── Desktop/VNC-Overlay (nur Admin; Button wird nach /api/me eingeblendet) ──
    var _vnc = null;
    var _vncBtn = document.getElementById('pt-vnc-btn');
    if (_vncBtn) _vncBtn.addEventListener('click', function () {
        var ov = document.getElementById('vnc-overlay');
        if (ov) ov.style.display = 'flex';
        if (!_vnc && window.JarvisVNC) {
            _vnc = new window.JarvisVNC();
            fetch('/api/config').then(function (r) { return r.json(); }).then(function (data) {
                if (data.vnc_available) _vnc.connect(data.websockify_port);
                else if (_vnc.showError) _vnc.showError();
            }).catch(function () { if (_vnc && _vnc.showError) _vnc.showError(); });
        }
    });
    var _vncClose = document.getElementById('vnc-close');
    if (_vncClose) _vncClose.addEventListener('click', function () {
        var ov = document.getElementById('vnc-overlay');
        if (ov) ov.style.display = 'none';
    });

    if (window.refreshBranding) try { window.refreshBranding(); } catch(e){}
})();
