package main

import (
	"crypto/tls"
	"net/url"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

// testConnection prüft ob eine WebSocket-Verbindung hergestellt werden kann.
func testConnection(serverURL, _ string) error {
	u := serverURL
	if strings.HasPrefix(u, "https://") {
		u = "wss://" + u[8:]
	} else if strings.HasPrefix(u, "http://") {
		u = "ws://" + u[7:]
	}

	_, err := url.Parse(u)
	if err != nil {
		return err
	}

	dialer := websocket.Dialer{
		TLSClientConfig:  &tls.Config{InsecureSkipVerify: true},
		HandshakeTimeout: 5 * time.Second,
	}
	conn, _, err := dialer.Dial(u, nil)
	if err != nil {
		return err
	}
	conn.Close()
	return nil
}
