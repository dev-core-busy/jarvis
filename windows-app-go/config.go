package main

import (
	"encoding/json"
	"os"
	"path/filepath"
)

type Config struct {
	ServerURL   string `json:"server_url"`
	APIKey      string `json:"api_key"`
	DialogMode  bool   `json:"dialog_mode"`
	WindowW     int    `json:"window_w"`
	WindowH     int    `json:"window_h"`
	SpeakerID   string `json:"speaker_id"`
	MicID       string `json:"mic_id"`
	SpeakerName string `json:"speaker_name"`
	MicName     string `json:"mic_name"`
	// Avatar-Fenster Position (beim Beenden gespeichert)
	AvatarX int `json:"avatar_x"`
	AvatarY int `json:"avatar_y"`
	// Wake-Word Einstellungen
	WakeWordEnabled bool   `json:"wakeword_enabled"`
	WakeWord        string `json:"wakeword"`
	SilenceMs       int    `json:"silence_ms"`
	MinSpeechMs     int    `json:"min_speech_ms"`
	VADThreshold    int    `json:"vad_threshold"`
	// TTS-Stimme (Windows SAPI Stimmenname, "" = Standard)
	TTSVoice string `json:"tts_voice"`
	// Hintergrund
	BackgroundType      string  `json:"background_type"`   // "gradient" | "color" | "photo"
	BackgroundColor     int     `json:"background_color"`  // Index in bgPalette
	BackgroundImagePath string  `json:"background_image"`  // Pfad für "photo"
	BackgroundAlpha     float32 `json:"background_alpha"`  // 0.0–1.0, Helligkeit Foto
	// Sprache
	AutoSendVoice bool `json:"auto_send_voice"` // Spracheingabe direkt senden (kein Tipp-Bestätigen)
	// Anzeige
	DebugMode     bool `json:"debug_mode"`       // Agent-Denk-Nachrichten anzeigen
	TTSInTextMode bool `json:"tts_in_text_mode"` // Antworten im Text-Modus vorlesen
}

// AppVersion wird beim Build via -ldflags="-X main.AppVersion=0.8xx" gesetzt.
var AppVersion = "0.800"

// BG_DEFAULT_URI markiert das eingebettete Jarvis-Standardbild (analog Android).
const BG_DEFAULT_URI = "res://bg_jarvis"

var defaultConfig = Config{
	ServerURL:       "wss://191.100.144.1/ws",
	APIKey:          "",
	DialogMode:      true,
	WindowW:         420,
	WindowH:         650,
	SpeakerID:       "",
	MicID:           "",
	WakeWordEnabled: false,
	WakeWord:        "hallo jarvis",
	SilenceMs:       900,
	MinSpeechMs:     200,
	VADThreshold:    150,
	BackgroundType:      "photo",
	BackgroundImagePath: BG_DEFAULT_URI,
	BackgroundColor:     0,
	BackgroundAlpha:     0.5,
	AutoSendVoice:   true,
}

func configPath() string {
	exe, err := os.Executable()
	if err != nil {
		return "config.json"
	}
	return filepath.Join(filepath.Dir(exe), "config.json")
}

func LoadConfig() *Config {
	cfg := defaultConfig
	data, err := os.ReadFile(configPath())
	if err != nil {
		return &cfg
	}
	_ = json.Unmarshal(data, &cfg)
	// Migration: alter VAD-Schwellwert 400 war zu hoch → auf 50 setzen
	if cfg.VADThreshold == 0 || cfg.VADThreshold >= 400 {
		cfg.VADThreshold = 50
	}
	return &cfg
}

func (c *Config) Save() error {
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(configPath(), data, 0644)
}

func (c *Config) IsFirstStart() bool {
	_, err := os.Stat(configPath())
	return os.IsNotExist(err) || c.APIKey == ""
}
