package main

// DesktopCommand: Backend → Windows App (desktop_command Nachricht)
type DesktopCommand struct {
	Action    string  `json:"action"`
	RequestID string  `json:"request_id"`
	X         float64 `json:"x,omitempty"`
	Y         float64 `json:"y,omitempty"`
	X2        float64 `json:"x2,omitempty"`      // Ziel für drag_and_drop / move_window
	Y2        float64 `json:"y2,omitempty"`      // Ziel für drag_and_drop / move_window
	Button    string  `json:"button,omitempty"`  // "left" | "right" | "middle"
	Text      string  `json:"text,omitempty"`
	Key       string  `json:"key,omitempty"`     // z.B. "ctrl+c", "alt+F4"
	Cmd       string  `json:"cmd,omitempty"`
	URL       string  `json:"url,omitempty"`     // für open_url
	Amount    int     `json:"amount,omitempty"`  // für scroll (Klicks)
	Direction string  `json:"direction,omitempty"` // scroll: "up"|"down"|"left"|"right"
	Width     int     `json:"width,omitempty"`   // für resize_window
	Height    int     `json:"height,omitempty"`  // für resize_window
	WindowID  string  `json:"window_id,omitempty"` // Fenster-Handle als String
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
