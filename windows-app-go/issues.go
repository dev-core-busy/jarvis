package main

// Issues-UI für den Windows-Client: Liste, Detail, Erstellen, Bearbeiten,
// Attachments. Berechtigung wird vom Backend geprüft – die UI zeigt nur
// die Buttons, die das Backend in der GET-Response als erlaubt markiert.

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"sort"
	"strings"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/storage"
	"fyne.io/fyne/v2/widget"
)

// ─── Datenmodell ──────────────────────────────────────────────────────

type Issue struct {
	ID            string   `json:"id"`
	Author        string   `json:"author"`
	Created       string   `json:"created"`
	Updated       string   `json:"updated"`
	Title         string   `json:"title"`
	Body          string   `json:"body"`
	Type          string   `json:"type"`
	Status        string   `json:"status"`
	Priority      string   `json:"priority"`
	JarvisComment string   `json:"jarvis_comment"`
	Attachments   []string `json:"attachments"`
}

type issueListResp struct {
	OK          bool    `json:"ok"`
	Issues      []Issue `json:"issues"`
	CurrentUser string  `json:"current_user"`
	IsAdmin     bool    `json:"is_admin"`
}

type issueDetailResp struct {
	OK          bool   `json:"ok"`
	Issue       Issue  `json:"issue"`
	CurrentUser string `json:"current_user"`
	IsAdmin     bool   `json:"is_admin"`
	CanEdit     bool   `json:"can_edit"`
	CanDelete   bool   `json:"can_delete"`
}

// ─── HTTP-Helper ──────────────────────────────────────────────────────

func issuesBaseURL(serverURL string) string {
	u := strings.TrimSuffix(serverURL, "/ws")
	u = strings.TrimSuffix(u, "/")
	u = strings.ReplaceAll(u, "wss://", "https://")
	u = strings.ReplaceAll(u, "ws://", "http://")
	return u
}

func issuesClient() *http.Client {
	return &http.Client{
		Timeout: 30 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		},
	}
}

func issuesRequest(method, url, token string, body []byte) ([]byte, int, error) {
	var rdr io.Reader
	if body != nil {
		rdr = bytes.NewReader(body)
	}
	req, err := http.NewRequest(method, url, rdr)
	if err != nil {
		return nil, 0, err
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := issuesClient().Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	return raw, resp.StatusCode, nil
}

// ─── Formatter ────────────────────────────────────────────────────────

func typeLabel(t string) string {
	switch t {
	case "bug":
		return "Bug"
	case "feature":
		return "Feature"
	case "improvement":
		return "Verbesserung"
	}
	return t
}

func statusLabel(s string) string {
	switch s {
	case "open":
		return "Offen"
	case "in_progress":
		return "In Arbeit"
	case "closed":
		return "Geschlossen"
	}
	return s
}

func prioLabel(p string) string {
	switch p {
	case "low":
		return "Niedrig"
	case "medium":
		return "Mittel"
	case "high":
		return "Hoch"
	}
	return p
}

func fmtIssueDate(iso string) string {
	if iso == "" {
		return ""
	}
	t, err := time.Parse(time.RFC3339, iso)
	if err != nil {
		return iso
	}
	return t.Local().Format("02.01.2006 15:04")
}

// ─── Hauptfenster: Liste ──────────────────────────────────────────────

func ShowIssuesWindow(ja *JarvisApp) {
	w := ja.fyneApp.NewWindow("Issues – Feedback & Bugs")
	w.Resize(fyne.NewSize(820, 600))

	statusLbl := widget.NewLabel("")

	// Filter
	statusFilter := widget.NewSelect(
		[]string{"alle", "Offen", "In Arbeit", "Geschlossen"},
		nil,
	)
	statusFilter.SetSelected("alle")
	typeFilter := widget.NewSelect(
		[]string{"alle", "Bug", "Feature", "Verbesserung"},
		nil,
	)
	typeFilter.SetSelected("alle")
	mineOnly := widget.NewCheck("nur meine", nil)

	listVbox := container.NewVBox()
	scroll := container.NewVScroll(listVbox)

	var allIssues []Issue
	var currentUser string
	var isAdmin bool
	var refresh func()

	refresh = func() {
		token := ja.cfg.APIKey
		base := issuesBaseURL(ja.cfg.ServerURL)
		raw, code, err := issuesRequest("GET", base+"/api/issues", token, nil)
		if err != nil {
			statusLbl.SetText("Fehler: " + err.Error())
			return
		}
		if code != 200 {
			statusLbl.SetText(fmt.Sprintf("HTTP %d: %s", code, string(raw)))
			return
		}
		var resp issueListResp
		if err := json.Unmarshal(raw, &resp); err != nil {
			statusLbl.SetText("JSON-Fehler: " + err.Error())
			return
		}
		allIssues = resp.Issues
		currentUser = resp.CurrentUser
		isAdmin = resp.IsAdmin
		statusLbl.SetText(fmt.Sprintf("%d Issue(s) – angemeldet als %s%s",
			len(allIssues), currentUser, map[bool]string{true: " (Admin)", false: ""}[isAdmin]))
		applyFilter(allIssues, listVbox, statusFilter, typeFilter, mineOnly,
			currentUser, ja, w, refresh)
	}

	statusFilter.OnChanged = func(string) {
		applyFilter(allIssues, listVbox, statusFilter, typeFilter, mineOnly,
			currentUser, ja, w, refresh)
	}
	typeFilter.OnChanged = func(string) {
		applyFilter(allIssues, listVbox, statusFilter, typeFilter, mineOnly,
			currentUser, ja, w, refresh)
	}
	mineOnly.OnChanged = func(bool) {
		applyFilter(allIssues, listVbox, statusFilter, typeFilter, mineOnly,
			currentUser, ja, w, refresh)
	}

	newBtn := widget.NewButton("+ Neues Issue", func() {
		showIssueForm(ja, nil, refresh)
	})
	reloadBtn := widget.NewButton("⟳", refresh)

	top := container.NewBorder(
		nil, nil,
		container.NewHBox(
			widget.NewLabel("Status:"), statusFilter,
			widget.NewLabel("Typ:"), typeFilter,
			mineOnly,
		),
		container.NewHBox(reloadBtn, newBtn),
		statusLbl,
	)

	w.SetContent(container.NewBorder(top, nil, nil, nil, scroll))
	w.Show()
	go refresh()
}

func applyFilter(all []Issue, vbox *fyne.Container,
	sf, tf *widget.Select, mc *widget.Check,
	currentUser string, ja *JarvisApp, parent fyne.Window, onRefresh func()) {

	filtered := make([]Issue, 0, len(all))
	for _, i := range all {
		if sf.Selected != "alle" && statusLabel(i.Status) != sf.Selected {
			continue
		}
		if tf.Selected != "alle" && typeLabel(i.Type) != tf.Selected {
			continue
		}
		if mc.Checked && !strings.EqualFold(i.Author, currentUser) {
			continue
		}
		filtered = append(filtered, i)
	}
	sort.Slice(filtered, func(i, j int) bool {
		return filtered[i].Created > filtered[j].Created
	})

	vbox.RemoveAll()
	if len(filtered) == 0 {
		vbox.Add(widget.NewLabel("(keine Issues)"))
	}
	for _, isObj := range filtered {
		is := isObj // copy für Closure
		title := widget.NewLabelWithStyle(is.Title,
			fyne.TextAlignLeading, fyne.TextStyle{Bold: true})
		title.Wrapping = fyne.TextWrapWord
		meta := widget.NewLabel(fmt.Sprintf("[%s · %s · %s] %s · %s",
			typeLabel(is.Type), prioLabel(is.Priority),
			statusLabel(is.Status), is.Author, fmtIssueDate(is.Created)))
		openBtn := widget.NewButton("Öffnen", func() {
			showIssueDetail(ja, is.ID, onRefresh)
		})
		card := container.NewBorder(nil, nil, nil, openBtn,
			container.NewVBox(title, meta))
		vbox.Add(widget.NewCard("", "", card))
	}
}

// ─── Detail-Fenster ───────────────────────────────────────────────────

func showIssueDetail(ja *JarvisApp, id string, onListRefresh func()) {
	w := ja.fyneApp.NewWindow("Issue-Details")
	w.Resize(fyne.NewSize(720, 600))

	body := container.NewVBox(widget.NewLabel("Lade…"))
	scroll := container.NewVScroll(body)
	w.SetContent(scroll)
	w.Show()

	loadAndRender := func() {
		token := ja.cfg.APIKey
		base := issuesBaseURL(ja.cfg.ServerURL)
		raw, code, err := issuesRequest("GET", base+"/api/issues/"+id, token, nil)
		if err != nil {
			body.RemoveAll()
			body.Add(widget.NewLabel("Fehler: " + err.Error()))
			return
		}
		if code != 200 {
			body.RemoveAll()
			body.Add(widget.NewLabel(fmt.Sprintf("HTTP %d: %s", code, string(raw))))
			return
		}
		var resp issueDetailResp
		if err := json.Unmarshal(raw, &resp); err != nil {
			body.RemoveAll()
			body.Add(widget.NewLabel("JSON-Fehler: " + err.Error()))
			return
		}
		renderIssueDetail(ja, w, body, resp, onListRefresh)
	}

	go loadAndRender()
}

func renderIssueDetail(ja *JarvisApp, w fyne.Window, body *fyne.Container,
	r issueDetailResp, onListRefresh func()) {
	is := r.Issue
	body.RemoveAll()

	title := widget.NewLabelWithStyle(is.Title, fyne.TextAlignLeading,
		fyne.TextStyle{Bold: true})
	title.Wrapping = fyne.TextWrapWord
	body.Add(title)
	body.Add(widget.NewLabel(fmt.Sprintf("[%s · %s · %s]",
		typeLabel(is.Type), prioLabel(is.Priority), statusLabel(is.Status))))
	body.Add(widget.NewLabel("Autor: " + is.Author))
	body.Add(widget.NewLabel("Erstellt: " + fmtIssueDate(is.Created)))
	body.Add(widget.NewLabel("Aktualisiert: " + fmtIssueDate(is.Updated)))
	body.Add(widget.NewSeparator())

	body.Add(widget.NewLabelWithStyle("Beschreibung:", fyne.TextAlignLeading,
		fyne.TextStyle{Bold: true}))
	bodyText := widget.NewLabel(is.Body)
	bodyText.Wrapping = fyne.TextWrapWord
	body.Add(bodyText)

	if is.JarvisComment != "" {
		body.Add(widget.NewSeparator())
		body.Add(widget.NewLabelWithStyle("Antwort von Jarvis:",
			fyne.TextAlignLeading, fyne.TextStyle{Bold: true}))
		jc := widget.NewLabel(is.JarvisComment)
		jc.Wrapping = fyne.TextWrapWord
		body.Add(jc)
	}

	body.Add(widget.NewSeparator())
	body.Add(widget.NewLabelWithStyle("Anhänge:", fyne.TextAlignLeading,
		fyne.TextStyle{Bold: true}))
	if len(is.Attachments) == 0 {
		body.Add(widget.NewLabel("(keine)"))
	}
	for _, att := range is.Attachments {
		name := att // closure
		row := container.NewHBox(
			widget.NewLabel("📎 " + name),
			widget.NewButton("Herunterladen", func() {
				downloadAttachment(ja, w, is.ID, name)
			}),
		)
		if r.CanEdit {
			row.Add(widget.NewButton("Löschen", func() {
				dialog.ShowConfirm("Anhang löschen?",
					"Anhang \""+name+"\" wirklich löschen?",
					func(ok bool) {
						if !ok {
							return
						}
						go func() {
							base := issuesBaseURL(ja.cfg.ServerURL)
							_, code, err := issuesRequest("DELETE",
								base+"/api/issues/"+is.ID+"/attachments/"+name,
								ja.cfg.APIKey, nil)
							if err != nil {
								dialog.ShowError(err, w)
								return
							}
							if code != 200 {
								dialog.ShowError(fmt.Errorf("HTTP %d", code), w)
								return
							}
							showIssueDetail(ja, is.ID, onListRefresh)
							w.Close()
						}()
					}, w)
			}))
		}
		body.Add(row)
	}

	body.Add(widget.NewSeparator())
	btnRow := container.NewHBox()
	if r.CanEdit {
		btnRow.Add(widget.NewButton("Bearbeiten", func() {
			showIssueForm(ja, &is, func() {
				onListRefresh()
				showIssueDetail(ja, is.ID, onListRefresh)
				w.Close()
			})
		}))
		btnRow.Add(widget.NewButton("+ Anhang", func() {
			uploadAttachment(ja, w, is.ID, onListRefresh)
		}))
	}
	if r.IsAdmin {
		btnRow.Add(widget.NewButton("Jarvis-Bereich", func() {
			showJarvisForm(ja, &is, func() {
				onListRefresh()
				showIssueDetail(ja, is.ID, onListRefresh)
				w.Close()
			})
		}))
	}
	if r.CanDelete {
		btnRow.Add(widget.NewButton("Löschen", func() {
			dialog.ShowConfirm("Issue löschen?",
				"Issue wirklich löschen? Anhänge werden mit entfernt.",
				func(ok bool) {
					if !ok {
						return
					}
					go func() {
						base := issuesBaseURL(ja.cfg.ServerURL)
						_, code, err := issuesRequest("DELETE",
							base+"/api/issues/"+is.ID, ja.cfg.APIKey, nil)
						if err != nil {
							dialog.ShowError(err, w)
							return
						}
						if code != 200 {
							dialog.ShowError(fmt.Errorf("HTTP %d", code), w)
							return
						}
						onListRefresh()
						w.Close()
					}()
				}, w)
		}))
	}
	btnRow.Add(widget.NewButton("Schließen", func() { w.Close() }))
	body.Add(btnRow)
}

// ─── Erstellen / Bearbeiten ───────────────────────────────────────────

func showIssueForm(ja *JarvisApp, existing *Issue, onSaved func()) {
	w := ja.fyneApp.NewWindow(map[bool]string{
		true: "Issue bearbeiten", false: "Neues Issue",
	}[existing != nil])
	w.Resize(fyne.NewSize(600, 480))

	titleEntry := widget.NewEntry()
	titleEntry.SetPlaceHolder("Kurzer aussagekräftiger Titel")
	bodyEntry := widget.NewMultiLineEntry()
	bodyEntry.SetPlaceHolder("Beschreibung – was ist passiert? Was erwartest du?")
	bodyEntry.Wrapping = fyne.TextWrapWord
	bodyEntry.SetMinRowsVisible(8)

	typeSel := widget.NewSelect([]string{"Bug", "Feature", "Verbesserung"}, nil)
	typeSel.SetSelected("Bug")
	prioSel := widget.NewSelect([]string{"Niedrig", "Mittel", "Hoch"}, nil)
	prioSel.SetSelected("Mittel")

	if existing != nil {
		titleEntry.SetText(existing.Title)
		bodyEntry.SetText(existing.Body)
		typeSel.SetSelected(typeLabel(existing.Type))
		prioSel.SetSelected(prioLabel(existing.Priority))
	}

	errLbl := widget.NewLabel("")
	errLbl.Hide()

	saveBtn := widget.NewButton(
		map[bool]string{true: "Speichern", false: "Erstellen"}[existing != nil],
		func() {
			title := strings.TrimSpace(titleEntry.Text)
			if title == "" {
				errLbl.SetText("Titel ist erforderlich.")
				errLbl.Show()
				return
			}
			typeMap := map[string]string{"Bug": "bug", "Feature": "feature", "Verbesserung": "improvement"}
			prioMap := map[string]string{"Niedrig": "low", "Mittel": "medium", "Hoch": "high"}
			payload := map[string]string{
				"title":    title,
				"body":     bodyEntry.Text,
				"type":     typeMap[typeSel.Selected],
				"priority": prioMap[prioSel.Selected],
			}
			body, _ := json.Marshal(payload)
			base := issuesBaseURL(ja.cfg.ServerURL)
			url := base + "/api/issues"
			method := "POST"
			if existing != nil {
				url = base + "/api/issues/" + existing.ID
				method = "PATCH"
			}
			go func() {
				raw, code, err := issuesRequest(method, url, ja.cfg.APIKey, body)
				if err != nil {
					errLbl.SetText("Fehler: " + err.Error())
					errLbl.Show()
					return
				}
				if code != 200 {
					errLbl.SetText(fmt.Sprintf("HTTP %d: %s", code, string(raw)))
					errLbl.Show()
					return
				}
				onSaved()
				w.Close()
			}()
		},
	)
	cancelBtn := widget.NewButton("Abbrechen", func() { w.Close() })

	form := container.NewVBox(
		widget.NewLabel("Titel *"),
		titleEntry,
		container.NewGridWithColumns(2,
			container.NewVBox(widget.NewLabel("Typ"), typeSel),
			container.NewVBox(widget.NewLabel("Priorität"), prioSel),
		),
		widget.NewLabel("Beschreibung"),
		bodyEntry,
		errLbl,
		container.NewHBox(cancelBtn, saveBtn),
	)
	w.SetContent(container.NewVScroll(form))
	w.Show()
}

// ─── Jarvis-Bereich (Status + Comment) ────────────────────────────────

func showJarvisForm(ja *JarvisApp, is *Issue, onSaved func()) {
	w := ja.fyneApp.NewWindow("Issue – Jarvis-Bereich")
	w.Resize(fyne.NewSize(600, 420))

	statusMap := map[string]string{"Offen": "open", "In Arbeit": "in_progress", "Geschlossen": "closed"}
	statusSel := widget.NewSelect([]string{"Offen", "In Arbeit", "Geschlossen"}, nil)
	statusSel.SetSelected(statusLabel(is.Status))

	commentEntry := widget.NewMultiLineEntry()
	commentEntry.Wrapping = fyne.TextWrapWord
	commentEntry.SetMinRowsVisible(6)
	commentEntry.SetText(is.JarvisComment)

	errLbl := widget.NewLabel("")
	errLbl.Hide()

	saveBtn := widget.NewButton("Speichern", func() {
		payload := map[string]string{
			"status":         statusMap[statusSel.Selected],
			"jarvis_comment": commentEntry.Text,
		}
		body, _ := json.Marshal(payload)
		base := issuesBaseURL(ja.cfg.ServerURL)
		go func() {
			raw, code, err := issuesRequest("PATCH",
				base+"/api/issues/"+is.ID, ja.cfg.APIKey, body)
			if err != nil {
				errLbl.SetText("Fehler: " + err.Error())
				errLbl.Show()
				return
			}
			if code != 200 {
				errLbl.SetText(fmt.Sprintf("HTTP %d: %s", code, string(raw)))
				errLbl.Show()
				return
			}
			onSaved()
			w.Close()
		}()
	})
	cancelBtn := widget.NewButton("Abbrechen", func() { w.Close() })

	w.SetContent(container.NewVScroll(container.NewVBox(
		widget.NewLabelWithStyle(
			"Nur Jarvis darf Status setzen und einen öffentlichen Kommentar hinterlassen.",
			fyne.TextAlignLeading, fyne.TextStyle{Italic: true}),
		widget.NewLabel("Status"),
		statusSel,
		widget.NewLabel("Antwort/Kommentar an User (öffentlich sichtbar)"),
		commentEntry,
		errLbl,
		container.NewHBox(cancelBtn, saveBtn),
	)))
	w.Show()
}

// ─── Attachments ──────────────────────────────────────────────────────

func uploadAttachment(ja *JarvisApp, parent fyne.Window, issueID string, onDone func()) {
	dialog.ShowFileOpen(func(rc fyne.URIReadCloser, err error) {
		if err != nil || rc == nil {
			return
		}
		defer rc.Close()
		data, err := io.ReadAll(rc)
		if err != nil {
			dialog.ShowError(err, parent)
			return
		}
		filename := rc.URI().Name()

		var buf bytes.Buffer
		mw := multipart.NewWriter(&buf)
		fw, err := mw.CreateFormFile("file", filename)
		if err != nil {
			dialog.ShowError(err, parent)
			return
		}
		fw.Write(data)
		mw.Close()

		base := issuesBaseURL(ja.cfg.ServerURL)
		req, _ := http.NewRequest("POST",
			base+"/api/issues/"+issueID+"/attachments", &buf)
		req.Header.Set("Authorization", "Bearer "+ja.cfg.APIKey)
		req.Header.Set("Content-Type", mw.FormDataContentType())
		resp, err := issuesClient().Do(req)
		if err != nil {
			dialog.ShowError(err, parent)
			return
		}
		defer resp.Body.Close()
		raw, _ := io.ReadAll(resp.Body)
		if resp.StatusCode != 200 {
			dialog.ShowError(fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(raw)), parent)
			return
		}
		onDone()
		showIssueDetail(ja, issueID, onDone)
		parent.Close()
	}, parent)
}

func downloadAttachment(ja *JarvisApp, parent fyne.Window, issueID, filename string) {
	dialog.ShowFileSave(func(wc fyne.URIWriteCloser, err error) {
		if err != nil || wc == nil {
			return
		}
		defer wc.Close()
		base := issuesBaseURL(ja.cfg.ServerURL)
		raw, code, err := issuesRequest("GET",
			base+"/api/issues/"+issueID+"/attachments/"+filename,
			ja.cfg.APIKey, nil)
		if err != nil {
			dialog.ShowError(err, parent)
			return
		}
		if code != 200 {
			dialog.ShowError(fmt.Errorf("HTTP %d", code), parent)
			return
		}
		if _, err := wc.Write(raw); err != nil {
			dialog.ShowError(err, parent)
			return
		}
		dialog.ShowInformation("Heruntergeladen",
			"Datei gespeichert: "+wc.URI().Path(), parent)
	}, parent)
}

// Vermeide unused-import warning falls storage/os nicht überall benutzt wird
var _ = storage.NewFileURI
var _ = os.Getenv
