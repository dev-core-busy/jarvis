package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	"jarvis-windows/hilfen"
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

// historySpeicher ist der EINE Schreiber fuer messages.json.
//
// Code-Review 2026-10-18: SaveHistory lief pro Streaming-Teil als eigene
// Goroutine (AppendToLast) – bei einer langen Antwort Dutzende gleichzeitige
// os.WriteFile auf dieselbe Datei, ein aelterer Stand konnte den neueren
// ueberholen, und ein Abbruch mittendrin hinterliess eine halbe Datei. Jetzt
// sammelt ein Entpreller die Staende und schreibt 500 ms nach dem letzten
// Aufruf genau einmal, atomar ueber Temp-Datei + Umbenennen.
var historySpeicher = hilfen.NeuerEntpreller(500*time.Millisecond, saveHistoryJetzt)

// SaveHistory merkt den Stand zum Speichern vor (entprellt, kehrt sofort zurueck).
func SaveHistory(messages []ChatMessage) {
	historySpeicher.Setze(messages)
}

// FlushHistory schreibt einen vorgemerkten Stand sofort (beim Beenden).
func FlushHistory() {
	historySpeicher.Jetzt()
}

// saveHistoryJetzt speichert die letzten N Nachrichten (nur User + Jarvis, keine Status).
func saveHistoryJetzt(messages []ChatMessage) {
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
	_ = hilfen.SchreibeAtomar(historyPath(), data, 0644)
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
	// Code-Review 2026-10-18: einen noch vorgemerkten Stand verwerfen – sonst
	// schriebe der Entpreller den geloeschten Verlauf 500 ms spaeter zurueck.
	historySpeicher.Verwerfen()
	_ = os.Remove(historyPath())
}
