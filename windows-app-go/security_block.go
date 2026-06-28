package main

// Sicherheitsschicht: Sperr-Ansicht. Holt /api/security/my-block (Grund +
// Protokoll der verdaechtigen Aktivitaeten) und zeigt sie als Dialog.
// Auth: Authorization: Bearer <token> (nur echte Konten koennen gesperrt sein).

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/widget"
)

type secIncident struct {
	Ts      int64  `json:"ts"`
	Channel string `json:"channel"`
	Method  string `json:"method"`
	Pattern string `json:"pattern"`
	Snippet string `json:"snippet"`
}

type secBlockInfo struct {
	Blocked   bool          `json:"blocked"`
	Reason    string        `json:"reason"`
	At        int64         `json:"at"`
	Incidents []secIncident `json:"incidents"`
}

// jarvisBearerGET fuehrt einen GET mit Bearer-Token aus (self-signed TLS ok).
func jarvisBearerGET(url, token string) ([]byte, error) {
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{
		Transport: &http.Transport{TLSClientConfig: &tls.Config{InsecureSkipVerify: true}},
		Timeout:   20 * time.Second,
	}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	return io.ReadAll(resp.Body)
}

// showBlockedDialog holt die eigene Sperr-Info und zeigt einen modalen Dialog
// mit Grund + Protokoll. Laeuft asynchron (HTTP) und baut die UI danach.
func (ja *JarvisApp) showBlockedDialog() {
	go func() {
		var info secBlockInfo
		if data, err := jarvisBearerGET(wsURLToHTTPS(ja.cfg.ServerURL)+"/api/security/my-block", ja.cfg.APIKey); err == nil {
			_ = json.Unmarshal(data, &info)
		}

		intro := widget.NewLabel(t(
			"Dein Konto wurde wegen eines erkannten Sicherheitsverstoßes (Jailbreak-/Manipulationsversuch) gesperrt. Bitte wende dich an einen lokalen Administrator, um es wieder freischalten zu lassen.",
			"Your account was locked due to a detected security violation (jailbreak/manipulation attempt). Please contact a local administrator to restore access."))
		intro.Wrapping = fyne.TextWrapWord

		items := []fyne.CanvasObject{intro}
		if info.Reason != "" {
			items = append(items, widget.NewLabel(t("Grund: ", "Reason: ")+info.Reason))
		}
		items = append(items, widget.NewLabelWithStyle(
			t("Protokoll der verdächtigen Aktivitäten", "Log of suspicious activity"),
			fyne.TextAlignLeading, fyne.TextStyle{Bold: true}))

		if len(info.Incidents) == 0 {
			items = append(items, widget.NewLabel(t("Keine Vorfälle protokolliert.", "No incidents logged.")))
		} else {
			// neueste zuerst
			for i := len(info.Incidents) - 1; i >= 0; i-- {
				it := info.Incidents[i]
				ts := time.Unix(it.Ts, 0).Format("2006-01-02 15:04:05")
				head := widget.NewLabelWithStyle(
					fmt.Sprintf("%s · %s · %s", ts, it.Channel, it.Pattern),
					fyne.TextAlignLeading, fyne.TextStyle{Bold: true})
				snip := widget.NewLabel(it.Snippet)
				snip.Wrapping = fyne.TextWrapWord
				items = append(items, head, snip, widget.NewSeparator())
			}
		}

		scroll := container.NewScroll(container.NewVBox(items...))
		scroll.SetMinSize(fyne.NewSize(520, 360))

		parent := ja.chatWin
		if parent == nil {
			parent = ja.avatarWin
		}
		if parent == nil {
			return
		}
		d := dialog.NewCustom(t("🔒 Konto gesperrt", "🔒 Account locked"),
			t("Schließen", "Close"), scroll, parent)
		d.Resize(fyne.NewSize(560, 440))
		d.Show()
	}()
}
