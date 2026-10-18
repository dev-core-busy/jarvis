package main

import (
	"encoding/json"
	"math/rand"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"

	"jarvis-windows/hilfen"
	"jarvis-windows/tlsvertrauen"
)

// Zeitgrenzen gegen halboffene Verbindungen.
//
// Code-Review 2026-10-18: ohne Lese-Deadline blieb ReadMessage nach einem
// stillen Verbindungsabriss (WLAN-Wechsel, Standby, NAT-Timeout) beliebig
// lange haengen – die App zeigte "verbunden", und gesendete Auftraege gingen
// ins Leere. Jetzt schickt der Client alle wsPingAbstand einen Ping; kommt
// binnen wsLeseFrist weder Pong noch Nachricht, gilt die Verbindung als tot.
const (
	wsLeseFrist    = 60 * time.Second
	wsPingAbstand  = 25 * time.Second
	wsSchreibFrist = 10 * time.Second
)

type WSMessage struct {
	Type         string `json:"type"`
	Message      string `json:"message,omitempty"`
	Event        string `json:"event,omitempty"`
	Data         string `json:"data,omitempty"`
	Highlight    bool   `json:"highlight,omitempty"`
	Intermediate bool   `json:"intermediate,omitempty"` // LLM-Zwischenantwort neben Tool-Aufrufen
	Text         string `json:"text,omitempty"`
	// LLM-Statistiken
	DurationMs   int `json:"duration_ms,omitempty"`
	InputTokens  int `json:"input_tokens,omitempty"`
	OutputTokens int `json:"output_tokens,omitempty"`
	TotalTokens  int `json:"total_tokens,omitempty"`
	Steps        int `json:"steps,omitempty"`
	// Desktop-Steuerung
	Action    string  `json:"action,omitempty"`
	RequestID string  `json:"request_id,omitempty"`
	X         float64 `json:"x,omitempty"`
	Y         float64 `json:"y,omitempty"`
	X2        float64 `json:"x2,omitempty"`
	Y2        float64 `json:"y2,omitempty"`
	Button    string  `json:"button,omitempty"`
	Key       string  `json:"key,omitempty"`
	Cmd       string  `json:"cmd,omitempty"`
	URL       string  `json:"url,omitempty"`
	Amount    int     `json:"amount,omitempty"`
	Direction string  `json:"direction,omitempty"`
	Width     int     `json:"width,omitempty"`
	Height    int     `json:"height,omitempty"`
	WindowID  string  `json:"window_id,omitempty"`
}

type WSClient struct {
	cfg       *Config
	mu        sync.Mutex
	conn      *websocket.Conn
	connected bool
	stopCh    chan struct{}
	sendCh    chan []byte

	OnMessage         func(WSMessage)
	OnConnected       func(bool)
	OnTTSAudio        func([]byte)
	OnWakeWordResult  func(transcript string, detected bool)
	OnVoiceTranscript func(transcript string) // Transkript einer Spracheingabe
	OnDesktopCommand  func(DesktopCommand)    // Desktop-Steuerungsbefehle vom Backend
}

func NewWSClient(cfg *Config) *WSClient {
	return &WSClient{
		cfg:    cfg,
		stopCh: make(chan struct{}),
		sendCh: make(chan []byte, 64),
	}
}

func (c *WSClient) Start() {
	go c.connectLoop()
}

func (c *WSClient) Stop() {
	close(c.stopCh)
	c.mu.Lock()
	if c.conn != nil {
		_ = c.conn.Close()
	}
	c.mu.Unlock()
}

func (c *WSClient) SendTask(text string, lang string) {
	if lang == "" {
		lang = "de"
	}
	payload := map[string]string{
		"type":  "task",
		"text":  text,
		"token": c.cfg.SchluesselJetzt(),
		"lang":  lang,
	}
	data, _ := json.Marshal(payload)
	select {
	case c.sendCh <- data:
	default:
	}
}

// SendTaskWithTruncate sendet eine bearbeitete Nachricht und weist das Backend an,
// die History auf die ersten `truncateUserMsgIndex` User-Nachrichten zu kuerzen,
// bevor die neue Nachricht hinzugefuegt wird. truncateUserMsgIndex ist 0-basiert
// und entspricht der Position der bearbeiteten User-Nachricht (zaehlt nur user-Rollen).
func (c *WSClient) SendTaskWithTruncate(text string, lang string, truncateUserMsgIndex int) {
	if lang == "" {
		lang = "de"
	}
	payload := map[string]interface{}{
		"type":                    "task",
		"text":                    text,
		"token":                   c.cfg.SchluesselJetzt(),
		"lang":                    lang,
		"truncate_user_msg_index": truncateUserMsgIndex,
	}
	data, _ := json.Marshal(payload)
	select {
	case c.sendCh <- data:
	default:
	}
}

func (c *WSClient) SendStop(agentID string) {
	payload := map[string]interface{}{
		"type":   "control",
		"action": "stop",
		"token":  c.cfg.SchluesselJetzt(),
	}
	if agentID != "" {
		payload["agent_id"] = agentID
	}
	data, _ := json.Marshal(payload)
	select {
	case c.sendCh <- data:
	default:
	}
}

func (c *WSClient) SendScreenResult(action, data string) {
	payload := map[string]string{
		"type":   "screen_result",
		"action": action,
		"data":   data,
	}
	b, _ := json.Marshal(payload)
	select {
	case c.sendCh <- b:
	default:
	}
}

// SendDesktopResult sendet das Ergebnis eines Desktop-Befehls ans Backend.
func (c *WSClient) SendDesktopResult(res DesktopResult) {
	b, _ := json.Marshal(map[string]interface{}{
		"type":       "desktop_result",
		"token":      c.cfg.SchluesselJetzt(),
		"action":     res.Action,
		"request_id": res.RequestID,
		"output":     res.Output,
		"data":       res.Data,
		"error":      res.Error,
		"exit_code":  res.ExitCode,
	})
	select {
	case c.sendCh <- b:
	default:
	}
}

// sendRegister meldet die Windows App als Desktop-Client beim Backend an.
func (c *WSClient) sendRegister() {
	payload := map[string]string{
		"type":        "register",
		"client_type": "windows_desktop",
		"token":       c.cfg.SchluesselJetzt(),
	}
	b, _ := json.Marshal(payload)
	select {
	case c.sendCh <- b:
	default:
	}
}

// SendTranscribeOnly sendet Audio zur reinen Transkription (kein Agent).
// Das Backend antwortet mit voice_transcript. Wird bei deaktiviertem AutoSend verwendet.
func (c *WSClient) SendTranscribeOnly(audioB64 string) {
	payload := map[string]string{
		"type":  "transcribe_only",
		"audio": audioB64,
		"token": c.cfg.SchluesselJetzt(),
	}
	data, _ := json.Marshal(payload)
	select {
	case c.sendCh <- data:
	default:
	}
}

// SendWakeWordCheck sendet Audio zur Wake-Word-Erkennung (kein LLM).
func (c *WSClient) SendWakeWordCheck(audioB64, phrase string) {
	payload := map[string]string{
		"type":   "wakeword_check",
		"audio":  audioB64,
		"phrase": phrase,
		"token":  c.cfg.SchluesselJetzt(),
	}
	data, _ := json.Marshal(payload)
	select {
	case c.sendCh <- data:
	default:
	}
}

func (c *WSClient) connectLoop() {
	attempt := 0
	for {
		select {
		case <-c.stopCh:
			return
		default:
		}
		c.setConnected(false)
		verbunden, err := c.runConn()
		// Code-Review 2026-10-18: der Zaehler wurde nie zurueckgesetzt, weil
		// runConn auch nach einer langen, erfolgreichen Verbindung mit dem
		// Lesefehler endet – nach ein paar Abrissen wartete der Client dann
		// immer 60 s. Jetzt zaehlt nur, wer gar nicht erst verbinden konnte.
		if verbunden {
			attempt = 0
		}
		if err == nil {
			continue
		}
		attempt++
		delay := hilfen.Backoff(attempt, rand.Float64())
		select {
		case <-c.stopCh:
			return
		case <-time.After(delay):
		}
	}
}

// runConn baut eine Verbindung auf und bedient sie bis zum Abbruch.
// verbunden meldet, ob der Aufbau gelang (fuer den Backoff-Zaehler).
func (c *WSClient) runConn() (verbunden bool, err error) {
	url := c.cfg.ServerURLJetzt()
	if strings.HasPrefix(url, "https://") {
		url = "wss://" + url[8:]
	} else if strings.HasPrefix(url, "http://") {
		url = "ws://" + url[7:]
	}

	dialer := websocket.Dialer{
		TLSClientConfig:  tlsvertrauen.ServerTLS(url),
		HandshakeTimeout: 10 * time.Second,
	}
	conn, _, err := dialer.Dial(url, nil)
	if err != nil {
		return false, err
	}
	defer conn.Close()

	// Code-Review 2026-10-18: done gehoert zu GENAU dieser Verbindung. Vorher
	// lief die Sender-Goroutine der alten Verbindung nach einem Abriss weiter
	// (sie kannte nur stopCh), griff Nachrichten der neuen Verbindung aus dem
	// gemeinsamen sendCh und schrieb sie in den toten Socket – verloren.
	// close(done) laeuft als Erstes beim Verlassen (defer-Reihenfolge).
	done := make(chan struct{})
	defer close(done)

	c.mu.Lock()
	c.conn = conn
	c.mu.Unlock()
	c.setConnected(true)

	_ = conn.SetReadDeadline(time.Now().Add(wsLeseFrist))
	conn.SetPongHandler(func(string) error {
		return conn.SetReadDeadline(time.Now().Add(wsLeseFrist))
	})

	// Als Windows-Desktop-Client registrieren
	go c.sendRegister()

	// Sender-Goroutine (einziger Schreiber dieser Verbindung, auch fuer Pings)
	go func() {
		ticker := time.NewTicker(wsPingAbstand)
		defer ticker.Stop()
		for {
			select {
			case <-c.stopCh:
				return
			case <-done:
				return
			case <-ticker.C:
				_ = conn.SetWriteDeadline(time.Now().Add(wsSchreibFrist))
				if err := conn.WriteMessage(websocket.PingMessage, nil); err != nil {
					_ = conn.Close() // weckt den Leser auf
					return
				}
			case data := <-c.sendCh:
				_ = conn.SetWriteDeadline(time.Now().Add(wsSchreibFrist))
				if err := conn.WriteMessage(websocket.TextMessage, data); err != nil {
					// Nachricht nicht verlieren: zurueck in die Warteschlange
					// fuer die naechste Verbindung (ohne zu blockieren).
					select {
					case c.sendCh <- data:
					default:
					}
					_ = conn.Close()
					return
				}
			}
		}
	}()

	// Empfangen
	for {
		msgType, data, err := conn.ReadMessage()
		if err != nil {
			return true, err
		}
		// Jede Nachricht (auch das "ping" des Servers) belegt eine lebende Verbindung
		_ = conn.SetReadDeadline(time.Now().Add(wsLeseFrist))
		if msgType == websocket.BinaryMessage {
			if c.OnTTSAudio != nil {
				c.OnTTSAudio(data)
			}
			continue
		}
		var msg WSMessage
		if err := json.Unmarshal(data, &msg); err != nil {
			continue
		}
		if msg.Type == "ping" {
			continue
		}
		if msg.Type == "wakeword_result" {
			if c.OnWakeWordResult != nil {
				c.OnWakeWordResult(msg.Text, msg.Data == "true" || msg.Highlight)
			}
			continue
		}
		if msg.Type == "voice_transcript" {
			if c.OnVoiceTranscript != nil {
				c.OnVoiceTranscript(msg.Text)
			}
			continue
		}
		if msg.Type == "desktop_command" {
			if c.OnDesktopCommand != nil {
				cmd := DesktopCommand{
					Action:    msg.Action,
					RequestID: msg.RequestID,
					X:         msg.X,
					Y:         msg.Y,
					X2:        msg.X2,
					Y2:        msg.Y2,
					Button:    msg.Button,
					Text:      msg.Text,
					Key:       msg.Key,
					Cmd:       msg.Cmd,
					URL:       msg.URL,
					Amount:    msg.Amount,
					Direction: msg.Direction,
					Width:     msg.Width,
					Height:    msg.Height,
					WindowID:  msg.WindowID,
				}
				go c.OnDesktopCommand(cmd)
			}
			continue
		}
		if c.OnMessage != nil {
			c.OnMessage(msg)
		}
	}
}

func (c *WSClient) setConnected(v bool) {
	c.mu.Lock()
	c.connected = v
	c.mu.Unlock()
	if c.OnConnected != nil {
		c.OnConnected(v)
	}
}
