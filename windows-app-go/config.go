package main

import (
	"encoding/json"
	"os"
	"path/filepath"
)

type Config struct {
	ServerURL   string `json:"server_url"`
	APIKey      string `json:"api_key"`
	DialogMode  bool   `json:"dialog_mode"`  // true = Mikrofon+Audio, false = Text
	WindowW     int    `json:"window_w"`
	WindowH     int    `json:"window_h"`
	SpeakerID   string `json:"speaker_id"`
	MicID       string `json:"mic_id"`
	SpeakerName string `json:"speaker_name"`
	MicName     string `json:"mic_name"`
}

var defaultConfig = Config{
	ServerURL:  "wss://191.100.144.1/ws",
	APIKey:     "",
	DialogMode: true, // Standard: Dialogmodus
	WindowW:    420,
	WindowH:    650,
	SpeakerID:  "",
	MicID:      "",
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
