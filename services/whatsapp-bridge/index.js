/**
 * Jarvis WhatsApp Bridge – Baileys + Express HTTP API
 *
 * Verbindet sich als "verknuepftes Geraet" mit WhatsApp (Multi-Device).
 * Stellt QR-Code und Status via HTTP bereit.
 * Leitet eingehende Nachrichten per Webhook an das Python-Backend weiter.
 */

const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, downloadMediaMessage, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');
const express = require('express');
const fs = require('fs');
const path = require('path');
const http = require('http');

// ─── Konfiguration ───────────────────────────────────────────────
const PORT = parseInt(process.env.WA_BRIDGE_PORT || '3001');
const JARVIS_WEBHOOK = process.env.JARVIS_WEBHOOK || 'https://localhost/api/whatsapp/incoming';
const AUTH_DIR = path.join(__dirname, 'auth');
const VOICE_DIR = '/tmp/jarvis_wa_voice';
const LOG_LEVEL = process.env.LOG_LEVEL || 'warn';

const LOG_DIR = path.join(__dirname, '..', '..', 'data', 'logs');
const BRIDGE_LOG_FILE = path.join(LOG_DIR, 'whatsapp-bridge.log');
const MAX_LOG_LINES = 2000;

// Verzeichnisse sicherstellen
fs.mkdirSync(AUTH_DIR, { recursive: true });
fs.mkdirSync(VOICE_DIR, { recursive: true });
fs.mkdirSync(LOG_DIR, { recursive: true });

// ─── State ───────────────────────────────────────────────────────
let sock = null;
let currentQR = null;
let connectionState = 'disconnected'; // disconnected, qr_pending, connecting, connected
let connectedNumber = null;
let connectedLid = null;  // Linked ID fuer Self-Chat Erkennung
let lastError = null;
let messageCount = 0;
const sentByBridge = new Set();  // Nachrichten-IDs die wir selbst gesendet haben (Feedback-Loop Schutz)

// ─── Logger ──────────────────────────────────────────────────────
const logger = pino({ level: LOG_LEVEL });

/**
 * Strukturiertes Bridge-Logging in JSON-Lines Datei.
 */
function bridgeLog(level, category, message, meta = null) {
    const entry = {
        ts: new Date().toISOString(),
        level: level.toUpperCase(),
        cat: category,
        msg: message,
    };
    if (meta) entry.meta = meta;

    const line = JSON.stringify(entry);
    console.log(`[WA-Bridge/${category}] ${level}: ${message}`);

    try {
        fs.appendFileSync(BRIDGE_LOG_FILE, line + '\n', 'utf-8');

        // Rotation: max MAX_LOG_LINES Eintraege
        const content = fs.readFileSync(BRIDGE_LOG_FILE, 'utf-8');
        const lines = content.trim().split('\n');
        if (lines.length > MAX_LOG_LINES) {
            const keep = lines.slice(-MAX_LOG_LINES);
            fs.writeFileSync(BRIDGE_LOG_FILE, keep.join('\n') + '\n', 'utf-8');
        }
    } catch (e) {
        console.error('[WA-Bridge/Logger] Schreibfehler:', e.message);
    }
}

// ─── Express API ─────────────────────────────────────────────────
const app = express();
app.use(express.json());

// Status-Endpoint
app.get('/status', (req, res) => {
    res.json({
        state: connectionState,
        connected_number: connectedNumber,
        has_qr: currentQR !== null,
        message_count: messageCount,
        last_error: lastError,
    });
});

// QR-Code als Text (fuer Frontend-Rendering)
app.get('/qr', (req, res) => {
    if (currentQR) {
        res.json({ qr: currentQR, state: connectionState });
    } else if (connectionState === 'connected') {
        res.json({ qr: null, state: 'connected', message: 'Bereits verbunden' });
    } else {
        res.json({ qr: null, state: connectionState, message: 'Kein QR-Code verfuegbar' });
    }
});

// Nachricht senden
app.post('/send', async (req, res) => {
    const { to, message, type } = req.body;

    if (!sock || connectionState !== 'connected') {
        return res.status(503).json({ error: 'WhatsApp nicht verbunden' });
    }

    if (!to || !message) {
        return res.status(400).json({ error: 'to und message sind Pflichtfelder' });
    }

    try {
        // Nummer normalisieren: +49... → 49...@s.whatsapp.net
        const jid = to.replace(/[^0-9]/g, '') + '@s.whatsapp.net';
        const result = await sock.sendMessage(jid, { text: message });
        // Message-ID merken um Feedback-Loop bei Self-Chat zu verhindern
        if (result?.key?.id) {
            sentByBridge.add(result.key.id);
            setTimeout(() => sentByBridge.delete(result.key.id), 60000);
        }
        res.json({ success: true, to: jid });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Logout / Verbindung trennen
app.post('/logout', async (req, res) => {
    try {
        if (sock) {
            await sock.logout();
        }
        // Auth-Daten loeschen
        fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        fs.mkdirSync(AUTH_DIR, { recursive: true });
        connectionState = 'disconnected';
        connectedNumber = null;
        currentQR = null;
        res.json({ success: true });
        // Neustart der Verbindung
        setTimeout(startConnection, 2000);
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Reconnect erzwingen
app.post('/reconnect', async (req, res) => {
    try {
        if (sock) {
            sock.end(undefined);
        }
        connectionState = 'disconnected';
        currentQR = null;
        setTimeout(startConnection, 1000);
        res.json({ success: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Bridge-Logs abrufen
app.get('/logs', (req, res) => {
    const lines = parseInt(req.query.lines || '100');
    const level = req.query.level || null;
    const category = req.query.category || null;

    try {
        if (!fs.existsSync(BRIDGE_LOG_FILE)) {
            return res.json({ logs: [], total: 0 });
        }
        const content = fs.readFileSync(BRIDGE_LOG_FILE, 'utf-8');
        let entries = content.trim().split('\n')
            .filter(l => l.trim())
            .map(l => { try { return JSON.parse(l); } catch { return null; } })
            .filter(e => e !== null);

        if (level) entries = entries.filter(e => e.level === level.toUpperCase());
        if (category) entries = entries.filter(e => e.cat === category);

        const result = entries.slice(-lines);
        res.json({ logs: result, total: result.length });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Bridge-Logs loeschen
app.delete('/logs', (req, res) => {
    try {
        if (fs.existsSync(BRIDGE_LOG_FILE)) fs.unlinkSync(BRIDGE_LOG_FILE);
        bridgeLog('INFO', 'config', 'Logs geloescht');
        res.json({ status: 'ok' });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// ─── Baileys Connection ──────────────────────────────────────────
async function startConnection() {
    try {
        const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
        const { version } = await fetchLatestBaileysVersion();

        bridgeLog('INFO', 'connection', `Starte Baileys v${version.join('.')}...`);

        sock = makeWASocket({
            version,
            auth: state,
            logger,
            browser: ['Jarvis', 'Desktop', '1.0.0'],
            connectTimeoutMs: 60000,
            keepAliveIntervalMs: 30000,
        });

        // ── Connection Updates ──
        sock.ev.on('connection.update', (update) => {
            const { connection, lastDisconnect, qr } = update;

            if (qr) {
                currentQR = qr;
                connectionState = 'qr_pending';
                bridgeLog('INFO', 'connection', 'QR-Code bereit. Bitte mit WhatsApp scannen.');
            }

            if (connection === 'connecting') {
                connectionState = 'connecting';
                currentQR = null;
                bridgeLog('INFO', 'connection', 'Verbinde...');
            }

            if (connection === 'open') {
                connectionState = 'connected';
                currentQR = null;
                lastError = null;

                // Eigene Nummer + LID ermitteln
                if (sock.user) {
                    connectedNumber = sock.user.id.split(':')[0].split('@')[0];
                    if (sock.user.lid) {
                        connectedLid = sock.user.lid.split(':')[0].split('@')[0];
                    }
                    bridgeLog('INFO', 'connection', `Verbunden als +${connectedNumber}` + (connectedLid ? ` (LID: ${connectedLid})` : ''));
                }
            }

            if (connection === 'close') {
                connectionState = 'disconnected';
                const statusCode = lastDisconnect?.error?.output?.statusCode;
                const reason = DisconnectReason[statusCode] || statusCode;
                lastError = `Verbindung getrennt: ${reason}`;
                bridgeLog('WARN', 'connection', lastError, { statusCode, reason });

                // Automatisch reconnecten (ausser bei Logout)
                if (statusCode !== DisconnectReason.loggedOut) {
                    bridgeLog('INFO', 'connection', 'Reconnect in 5s...');
                    setTimeout(startConnection, 5000);
                } else {
                    bridgeLog('INFO', 'connection', 'Ausgeloggt. Warte auf neuen QR-Scan.');
                    // Auth loeschen bei Logout
                    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
                    fs.mkdirSync(AUTH_DIR, { recursive: true });
                    setTimeout(startConnection, 2000);
                }
            }
        });

        // ── Credentials speichern ──
        sock.ev.on('creds.update', saveCreds);

        // ── Eingehende Nachrichten ──
        sock.ev.on('messages.upsert', async ({ messages, type }) => {
            for (const msg of messages) {
                const jid = msg.key.remoteJid || '';
                const jidBase = jid.split('@')[0].split(':')[0];
                const isSelfChat = (connectedNumber && jidBase === connectedNumber) ||
                                   (connectedLid && jidBase === connectedLid);

                // Debug: Alle Events loggen um Probleme zu erkennen
                bridgeLog('DEBUG', 'upsert', `type=${type} fromMe=${msg.key.fromMe} jid=${jid} jidBase=${jidBase} num=${connectedNumber} lid=${connectedLid} self=${isSelfChat}`);

                // Feedback-Loop Schutz: Nachrichten die WIR gesendet haben ignorieren
                if (msg.key.id && sentByBridge.has(msg.key.id)) {
                    sentByBridge.delete(msg.key.id);
                    bridgeLog('DEBUG', 'upsert', `Ueberspringe eigene Bridge-Nachricht: ${msg.key.id}`);
                    continue;
                }

                // Nur 'notify' verarbeiten – Self-Chat kann auch als 'append' kommen
                if (type !== 'notify' && !(isSelfChat && msg.key.fromMe)) continue;

                // Eigene ausgehende Nachrichten ignorieren – aber Self-Chat durchlassen
                if (msg.key.fromMe && !isSelfChat) continue;

                // Broadcast/Status ignorieren
                if (msg.key.remoteJid === 'status@broadcast') continue;

                await handleIncomingMessage(msg);
            }
        });

    } catch (e) {
        lastError = e.message;
        bridgeLog('ERROR', 'connection', `Startfehler: ${e.message}`);
        bridgeLog('INFO', 'connection', 'Retry in 10s...');
        setTimeout(startConnection, 10000);
    }
}

// ─── Nachrichtenverarbeitung ─────────────────────────────────────
async function handleIncomingMessage(msg) {
    let from = msg.key.remoteJid.replace('@s.whatsapp.net', '').replace('@g.us', '').replace('@lid', '');
    // Bei Self-Chat LID durch echte Telefonnummer ersetzen
    if (connectedLid && from.startsWith(connectedLid)) {
        from = connectedNumber;
    }
    const pushName = msg.pushName || '';
    const timestamp = new Date((msg.messageTimestamp || 0) * 1000).toISOString();

    let payload = {
        from: from,
        push_name: pushName,
        timestamp: timestamp,
        message_id: msg.key.id,
    };

    try {
        const content = msg.message;
        if (!content) return;

        // ── Textnachricht ──
        if (content.conversation || content.extendedTextMessage) {
            const text = content.conversation || content.extendedTextMessage?.text || '';
            payload.type = 'text';
            payload.text = text;
            bridgeLog('INFO', 'incoming', `Text von +${from}: ${text.substring(0, 100)}`);
        }
        // ── Sprachnachricht ──
        else if (content.audioMessage) {
            payload.type = 'voice';
            payload.duration = content.audioMessage.seconds || 0;
            payload.mimetype = content.audioMessage.mimetype || 'audio/ogg; codecs=opus';

            // Audio herunterladen
            try {
                const buffer = await downloadMediaMessage(msg, 'buffer', {}, {
                    logger,
                    reuploadRequest: sock.updateMediaMessage,
                });
                const filename = `voice_${Date.now()}_${from}.ogg`;
                const filepath = path.join(VOICE_DIR, filename);
                fs.writeFileSync(filepath, buffer);
                payload.media_path = filepath;
                bridgeLog('INFO', 'incoming', `Voice von +${from}: ${payload.duration}s -> ${filepath}`);
            } catch (dlErr) {
                bridgeLog('ERROR', 'incoming', `Voice-Download Fehler: ${dlErr.message}`);
                payload.error = 'Download fehlgeschlagen: ' + dlErr.message;
            }
        }
        // ── Bild ──
        else if (content.imageMessage) {
            payload.type = 'image';
            payload.caption = content.imageMessage.caption || '';
            // Bilder erstmal nicht downloaden, nur melden
            bridgeLog('INFO', 'incoming', `Bild von +${from}: ${payload.caption}`);
        }
        // ── Sonstige ──
        else {
            payload.type = 'other';
            payload.raw_type = Object.keys(content).join(', ');
            bridgeLog('INFO', 'incoming', `Sonstige Nachricht von +${from}: ${payload.raw_type}`);
        }

        messageCount++;

        // Webhook an Jarvis Backend senden
        await sendWebhook(payload);

    } catch (e) {
        bridgeLog('ERROR', 'incoming', `Verarbeitungsfehler: ${e.message}`);
    }
}

// ─── Webhook an Python-Backend ───────────────────────────────────
async function sendWebhook(payload) {
    try {
        const resp = await fetch(JARVIS_WEBHOOK, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            bridgeLog('ERROR', 'webhook', `Webhook Fehler: ${resp.status} ${resp.statusText}`);
        }
    } catch (e) {
        // Backend nicht erreichbar - nicht kritisch beim Start
        bridgeLog('WARN', 'webhook', `Webhook nicht erreichbar: ${e.message}`);
    }
}

// ─── Server starten ──────────────────────────────────────────────
app.listen(PORT, '127.0.0.1', () => {
    bridgeLog('INFO', 'config', `HTTP-API auf http://127.0.0.1:${PORT}`);
    bridgeLog('INFO', 'config', `Webhook-Ziel: ${JARVIS_WEBHOOK}`);
    startConnection();
});
