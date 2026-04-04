package main

import (
	"crypto/tls"
	"encoding/json"
	"log"
	"math"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

type WSMessage struct {
	Type    string `json:"type"`
	Message string `json:"message,omitempty"`
	Event   string `json:"event,omitempty"`
	Data    string `json:"data,omitempty"`
}

type WSClient struct {
	cfg       *Config
	mu        sync.Mutex
	conn      *websocket.Conn
	connected bool
	stopCh    chan struct{}
	sendCh    chan []byte

	OnMessage    func(WSMessage)
	OnConnected  func(bool)
	OnTTSAudio   func([]byte)
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

func (c *WSClient) connectLoop() {
	const maxAttempts = 20
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
			if attempt >= maxAttempts {
				log.Printf("ws: max reconnect attempts reached")
				return
			}
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
