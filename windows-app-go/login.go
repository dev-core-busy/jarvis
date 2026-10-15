package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"jarvis-windows/tlsvertrauen"
)

// doLogin sendet POST /api/login und gibt den Token zurueck.
func doLogin(serverURL, username, password string) (string, error) {
	// Nur Schema + Host extrahieren (Pfad wie /ws weglassen)
	httpURL := toHTTPS(serverURL)
	if parsed, err := url.Parse(httpURL); err == nil {
		httpURL = parsed.Scheme + "://" + parsed.Host
	}
	loginURL := strings.TrimRight(httpURL, "/") + "/api/login"

	// "client" kennzeichnet die App: ein Admin-Konto bekommt hier eine Sitzung
	// OHNE Admin-Rechte (die App kann keinen zweiten Faktor, BSI M3).
	body, _ := json.Marshal(map[string]string{
		"username": username,
		"password": password,
		"client":   "windows",
	})

	client := &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: tlsvertrauen.ServerTLS(httpURL),
		},
	}

	resp, err := client.Post(loginURL, "application/json", bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("Verbindung fehlgeschlagen: %w", err)
	}
	defer resp.Body.Close()

	var result struct {
		Success bool   `json:"success"`
		Token   string `json:"token"`
		Error   string `json:"error"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", fmt.Errorf("Ungueltige Serverantwort")
	}
	if !result.Success {
		return "", fmt.Errorf("%s", result.Error)
	}
	return result.Token, nil
}

// toHTTPS konvertiert wss:// -> https://, ws:// -> http://
func toHTTPS(u string) string {
	if strings.HasPrefix(u, "wss://") {
		return "https://" + u[6:]
	}
	if strings.HasPrefix(u, "ws://") {
		return "http://" + u[5:]
	}
	return u
}
