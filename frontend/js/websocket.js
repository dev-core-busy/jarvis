/**
 * Jarvis WebSocket Manager
 * Verwaltet die WebSocket-Verbindung mit Auto-Reconnect.
 */
class JarvisWebSocket {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 20;
        this.reconnectDelay = 2000;
        this.handlers = {};
        this.connected = false;
    }

    /**
     * Verbindung herstellen
     */
    connect() {
        try {
            this.ws = new WebSocket(this.url);

            this.ws.onopen = () => {
                this.connected = true;
                this.reconnectAttempts = 0;
                this.emit('connected');
            };

            this.ws.onclose = (event) => {
                this.connected = false;
                this.emit('disconnected', event);
                this._scheduleReconnect();
            };

            this.ws.onerror = (error) => {
                this.emit('error', error);
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.emit('message', data);

                    // Typ-spezifische Events
                    if (data.type) {
                        this.emit(data.type, data);
                    }
                } catch (e) {
                    console.error('WebSocket Parse-Fehler:', e);
                }
            };
        } catch (e) {
            console.error('WebSocket Verbindungs-Fehler:', e);
            this._scheduleReconnect();
        }
    }

    /**
     * Nachricht senden
     */
    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
            return true;
        }
        return false;
    }

    /**
     * Verbindung schließen
     */
    disconnect() {
        this.maxReconnectAttempts = 0; // Reconnect deaktivieren
        if (this.ws) {
            this.ws.close();
        }
    }

    /**
     * Event-Handler registrieren
     */
    on(event, handler) {
        if (!this.handlers[event]) {
            this.handlers[event] = [];
        }
        this.handlers[event].push(handler);
    }

    /**
     * Event auslösen
     */
    emit(event, data) {
        const handlers = this.handlers[event] || [];
        handlers.forEach(h => {
            try {
                h(data);
            } catch (e) {
                console.error(`Handler-Fehler für '${event}':`, e);
            }
        });
    }

    /**
     * Reconnect planen
     */
    _scheduleReconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            this.emit('reconnect_failed');
            return;
        }

        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.min(this.reconnectAttempts, 5);

        setTimeout(() => {
            this.emit('reconnecting', this.reconnectAttempts);
            this.connect();
        }, delay);
    }
}
