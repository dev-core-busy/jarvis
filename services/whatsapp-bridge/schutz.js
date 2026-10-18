/**
 * Schutz der Bridge-HTTP-API (Code-Review 2026-10-18).
 *
 * Bis dahin lauschte die Bridge nur auf 127.0.0.1 und pruefte sonst nichts:
 * jeder lokale Prozess konnte senden, die Kopplung loeschen, das Adressbuch
 * lesen und ueber /send-media eine BELIEBIGE Datei (z. B. .env) an eine
 * beliebige Nummer schicken. Jetzt:
 *   - jede Anfrage traegt das Geheimnis aus data/.wa_bridge_secret
 *     (Gegenstueck: backend/wa_bruecke.py, gleiche Datei, gleiche Kopfzeile);
 *   - /send-media liest nur aus data/generated_images.
 * Eigenes Modul ohne Baileys-Abhaengigkeit, damit es ohne laufende Bridge
 * pruefbar ist (tests/test_wa_bruecke_schutz.js).
 */
'use strict';

const crypto = require('crypto');
const fs = require('fs');
const https = require('https');
const tls = require('tls');
const path = require('path');

const KOPF = 'X-Jarvis-Bridge';

function erzeuge(datenDir) {
    const datei = path.join(datenDir, '.wa_bridge_secret');
    const bilder = path.join(datenDir, 'generated_images');
    let zwischenspeicher = null;

    function laden() {
        fs.mkdirSync(datenDir, { recursive: true });
        try {
            // 'wx' = O_EXCL: wer zuerst startet (Backend oder Bridge), legt an
            fs.writeFileSync(datei, crypto.randomBytes(32).toString('hex'), { flag: 'wx', mode: 0o600 });
        } catch (e) {
            if (e.code !== 'EEXIST') throw e;
        }
        const wert = fs.readFileSync(datei, 'utf-8').trim();
        if (wert.length < 32) throw new Error('Bridge-Geheimnis zu kurz');
        return wert;
    }

    function geheimnis(neu = false) {
        if (neu || !zwischenspeicher) zwischenspeicher = laden();
        return zwischenspeicher;
    }

    function gleich(a, b) {
        const x = Buffer.from(String(a));
        const y = Buffer.from(String(b));
        return x.length === y.length && crypto.timingSafeEqual(x, y);
    }

    /** Stimmt der mitgeschickte Wert? Einmal neu lesen, falls das Backend die
     *  Datei gerade ersetzt hat. Ohne lesbares Geheimnis: nein. */
    function kopfStimmt(wert) {
        if (typeof wert !== 'string' || !wert) return false;
        try {
            if (gleich(wert, geheimnis())) return true;
            return gleich(wert, geheimnis(true));
        } catch (e) {
            return false;
        }
    }

    /** Express-Middleware: ohne gueltiges Geheimnis 401. */
    function pruefen(req, res, next) {
        if (!kopfStimmt(req.get(KOPF))) {
            return res.status(401).json({ error: 'Nicht autorisiert' });
        }
        return next();
    }

    /** Liefert den echten Pfad, wenn die Datei direkt in data/generated_images
     *  liegt (nach Aufloesen aller Links), sonst null. */
    function medienPfad(roh) {
        if (typeof roh !== 'string' || !roh) return null;
        let echt;
        let basis;
        try {
            echt = fs.realpathSync(roh);
            basis = fs.realpathSync(bilder);
        } catch (e) {
            return null;
        }
        if (path.dirname(echt) !== basis) return null;
        try {
            if (!fs.statSync(echt).isFile()) return null;
        } catch (e) {
            return null;
        }
        return echt;
    }

    function kopfzeilen() {
        return { [KOPF]: geheimnis() };
    }

    // Zertifikat des Backends fuer den Webhook an https://localhost – GEPINNT
    // (Code-Review 2026-10-18). Bis dahin setzte der Docker-Start
    // NODE_TLS_REJECT_UNAUTHORIZED=0 fuer den GANZEN Prozess, also auch fuer
    // Baileys' Verbindungen zu WhatsApp. Das Zertifikat traegt in der Regel
    // nicht den Namen "localhost" – deshalb gilt hier genau DIESES Zertifikat
    // (Fingerabdruck der Datei certs/server.crt), sonst keines.
    const zertDatei = path.join(datenDir, '..', 'certs', 'server.crt');

    function gepinnt() {
        const pem = fs.readFileSync(zertDatei, 'utf-8');
        const fp = new crypto.X509Certificate(pem).fingerprint256;
        return { pem, fp };
    }

    function webhookOptionen(url) {
        const u = new URL(url);
        const pin = gepinnt();
        return {
            hostname: u.hostname, port: u.port || 443, path: u.pathname + u.search, method: 'POST',
            // Systemwurzeln + die Datei: eine Let's-Encrypt-Kette prueft gegen die
            // Wurzeln, ein selbst ausgestelltes Zertifikat gegen sich selbst.
            ca: [...tls.rootCertificates, pin.pem],
            checkServerIdentity: (_host, zert) => (zert && zert.fingerprint256 === pin.fp)
                ? undefined
                : new Error('Webhook: Zertifikat entspricht nicht certs/server.crt'),
        };
    }

    /** POST an den Webhook, Antwort {status} – ohne globale TLS-Abschaltung. */
    function webhookSenden(url, daten) {
        return new Promise((ok, fehl) => {
            const koerper = Buffer.from(JSON.stringify(daten));
            let opt;
            try {
                opt = webhookOptionen(url);
            } catch (e) {
                return fehl(e);
            }
            opt.headers = { 'Content-Type': 'application/json', 'Content-Length': koerper.length,
                            ...kopfzeilen() };
            const req = https.request(opt, (res) => { res.resume(); ok({ status: res.statusCode }); });
            req.setTimeout(30000, () => req.destroy(new Error('Webhook: Zeitueberschreitung')));
            req.on('error', fehl);
            req.end(koerper);
        });
    }

    return { KOPF, datei, bilder, geheimnis, kopfStimmt, pruefen, medienPfad, kopfzeilen,
             zertDatei, webhookOptionen, webhookSenden };
}

module.exports = { erzeuge, KOPF };
