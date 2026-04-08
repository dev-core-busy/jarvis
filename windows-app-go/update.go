package main

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type WindowsVersionInfo struct {
	VersionCode int    `json:"versionCode"`
	VersionName string `json:"versionName"`
	DownloadURL string `json:"downloadUrl"`
}

// currentBuildNum parst die Build-Nummer aus AppVersion ("0.836" → 836).
func currentBuildNum() int {
	parts := strings.Split(AppVersion, ".")
	if len(parts) < 2 {
		return 0
	}
	n, _ := strconv.Atoi(parts[len(parts)-1])
	return n
}

// CheckForUpdate prüft version_windows.json auf jarvis-ai.info.
// Gibt nil zurück wenn kein Update verfügbar oder bei Fehler.
func CheckForUpdate() *WindowsVersionInfo {
	url := fmt.Sprintf("https://jarvis-ai.info/version_windows.json?t=%d", time.Now().UnixMilli())
	client := &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: false},
		},
	}
	resp, err := client.Get(url)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil
	}
	var info WindowsVersionInfo
	if err := json.Unmarshal(body, &info); err != nil {
		return nil
	}
	if info.VersionCode > currentBuildNum() {
		return &info
	}
	return nil
}
