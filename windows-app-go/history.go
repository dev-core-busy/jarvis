package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// persistedMessage ist das JSON-Format für gespeicherte Nachrichten.
type persistedMessage struct {
	Role string `json:"role"`
	Text string `json:"text"`
	Time int64  `json:"time"` // Unix-Timestamp Millisekunden
}

const historyMaxMessages = 100

func historyPath() string {
	exe, err := os.Executable()
	if err != nil {
		return "messages.json"
	}
	return filepath.Join(filepath.Dir(exe), "messages.json")
}

// SaveHistory speichert die letzten N Nachrichten (nur User + Jarvis, keine Status).
func SaveHistory(messages []ChatMessage) {
	var out []persistedMessage
	for _, m := range messages {
		if m.Role == RoleStatus {
			continue
		}
		out = append(out, persistedMessage{
			Role: string(m.Role),
			Text: m.Text,
			Time: m.Time.UnixMilli(),
		})
	}
	// Maximal historyMaxMessages behalten (neueste)
	if len(out) > historyMaxMessages {
		out = out[len(out)-historyMaxMessages:]
	}
	data, err := json.MarshalIndent(out, "", "  ")
	if err != nil {
		return
	}
	_ = os.WriteFile(historyPath(), data, 0644)
}

// LoadHistory lädt gespeicherte Nachrichten und gibt sie als ChatMessage-Slice zurück.
func LoadHistory() []ChatMessage {
	data, err := os.ReadFile(historyPath())
	if err != nil {
		return nil
	}
	var raw []persistedMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil
	}
	msgs := make([]ChatMessage, 0, len(raw))
	for _, r := range raw {
		role := MessageRole(r.Role)
		if role != RoleUser && role != RoleJarvis {
			continue
		}
		msgs = append(msgs, ChatMessage{
			Role: role,
			Text: r.Text,
			Time: time.UnixMilli(r.Time),
		})
	}
	return msgs
}

// DeleteHistory löscht die gespeicherte Konversation von Disk.
func DeleteHistory() {
	_ = os.Remove(historyPath())
}
