package main

import (
	"crypto/tls"
	"encoding/json"
	"math"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

type WSMessage struct {
	Type      string `json:"type"`
	Message   string `json:"message,omitempty"`
	Event     string `json:"event,omitempty"`
	Data      string `json:"data,omitempty"`
	Highlight bool   `json:"highlight,omitempty"`
	Text      string `json:"text,omitempty"`
	// Desktop-Steuerung
	Action    string  `json:"action,omitempty"`
	RequestID string  `json:"request_id,omitempty"`
	X         float64 `json:"x,omitempty"`
	Y         float64 `json:"y,omitempty"`
	Button    string  `json:"button,omitempty"`
	Key       string  `json:"key,omitempty"`
	Cmd       string  `json:"cmd,omitempty"`
	URL       string  `json:"url,omitempty"`
}

type WSClient struct {
	cfg       *Config
	mu        sync.Mutex
	conn      *websocket.Conn
	connected bool
	stopCh    chan struct{}
	sendCh    chan []byte

	OnMessage          func(WSMessage)
	OnConnected        func(bool)
	OnTTSAudio         func([]byte)
	OnWakeWordResult   func(transcript string, detected bool)
	OnVoiceTranscript  func(transcript string) // Transkript einer Spracheingabe
	OnDesktopCommand   func(DesktopCommand)    // Desktop-Steuerungsbefehle vom Backend
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

func (c *WSClient) SendTask(text string) {
	payload := map[string]string{
		"type":  "task",
		"text":  text,
		"token": c.cfg.APIKey,
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
		"token":      c.cfg.APIKey,
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
		"token":       c.cfg.APIKey,
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
		"token": c.cfg.APIKey,
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
		"token":  c.cfg.APIKey,
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
		err := c.runConn()
		if err != nil {
			attempt++
			delay := time.Duration(math.Min(float64(int(3)<<minInt(attempt, 6)), 60)) * time.Second
			select {
			case <-c.stopCh:
				return
			case <-time.After(delay):
			}
		} else {
			attempt = 0
		}
	}
}

func (c *WSClient) runConn() error {
	url := c.cfg.ServerURL
	if strings.HasPrefix(url, "https://") {
		url = "wss://" + url[8:]
	} else if strings.HasPrefix(url, "http://") {
		url = "ws://" + url[7:]
	}

	dialer := websocket.Dialer{
		TLSClientConfig:  &tls.Config{InsecureSkipVerify: true},
		HandshakeTimeout: 10 * time.Second,
	}
	conn, _, err := dialer.Dial(url, nil)
	if err != nil {
		return err
	}
	defer conn.Close()

	c.mu.Lock()
	c.conn = conn
	c.mu.Unlock()
	c.setConnected(true)

	// Als Windows-Desktop-Client registrieren
	go c.sendRegister()

	// Sender-Goroutine
	go func() {
		for {
			select {
			case <-c.stopCh:
				return
			case data := <-c.sendCh:
				if err := conn.WriteMessage(websocket.TextMessage, data); err != nil {
					return
				}
			}
		}
	}()

	// Empfangen
	for {
		msgType, data, err := conn.ReadMessage()
		if err != nil {
			return err
		}
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
					Button:    msg.Button,
					Text:      msg.Text,
					Key:       msg.Key,
					Cmd:       msg.Cmd,
					URL:       msg.URL,
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

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}
