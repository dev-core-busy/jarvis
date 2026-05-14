package main

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"
)

// PostFeedback sendet Benutzer-Feedback an den Jarvis-Server.
// onAnalysis wird aufgerufen (ggf. aus einem Goroutine), wenn der Server
// eine LLM-Analyse mit besseren Antworten zurückgibt.
func PostFeedback(serverURL, apiKey, rating, userMsg, botResp string, onAnalysis func(string)) {
	go func() {
		baseURL := strings.TrimSuffix(serverURL, "/ws")
		baseURL = strings.TrimSuffix(baseURL, "/")
		baseURL = strings.ReplaceAll(baseURL, "wss://", "https://")
		baseURL = strings.ReplaceAll(baseURL, "ws://", "http://")

		body, _ := json.Marshal(map[string]string{
			"token":        apiKey,
			"rating":       rating,
			"user_message": truncateStr(userMsg, 500),
			"bot_response": truncateStr(botResp, 500),
		})
		client := &http.Client{
			// Großzügiger Timeout: LLM-Analyse kann 20-40s dauern
			Timeout: 90 * time.Second,
			Transport: &http.Transport{
				TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
			},
		}
		req, err := http.NewRequest("POST", baseURL+"/api/feedback", bytes.NewReader(body))
		if err != nil {
			return
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := client.Do(req)
		if err != nil {
			return
		}
		defer resp.Body.Close()

		// Response lesen und Analyse-Text extrahieren
		raw, err := io.ReadAll(resp.Body)
		if err != nil {
			return
		}
		var result struct {
			Analysis string `json:"analysis"`
		}
		if err := json.Unmarshal(raw, &result); err != nil {
			return
		}
		if result.Analysis != "" && onAnalysis != nil {
			onAnalysis(result.Analysis)
		}
	}()
}

func truncateStr(s string, n int) string {
	runes := []rune(s)
	if len(runes) > n {
		return string(runes[:n])
	}
	return s
}
