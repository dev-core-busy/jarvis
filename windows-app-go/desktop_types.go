package main

// DesktopCommand: Backend → Windows App (desktop_command Nachricht)
type DesktopCommand struct {
	Action    string  `json:"action"`
	RequestID string  `json:"request_id"`
	X         float64 `json:"x,omitempty"`
	Y         float64 `json:"y,omitempty"`
	Button    string  `json:"button,omitempty"` // "left" | "right" | "middle"
	Text      string  `json:"text,omitempty"`
	Key       string  `json:"key,omitempty"` // z.B. "ctrl+c", "alt+F4"
	Cmd       string  `json:"cmd,omitempty"`
}

// DesktopResult: Windows App → Backend (desktop_result Nachricht)
type DesktopResult struct {
	Action    string `json:"action"`
	RequestID string `json:"request_id"`
	Output    string `json:"output,omitempty"`
	Data      string `json:"data,omitempty"` // base64 PNG für screenshot
	Error     string `json:"error,omitempty"`
	ExitCode  int    `json:"exit_code,omitempty"`
}
