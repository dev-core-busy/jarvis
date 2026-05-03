package main

import (
	"fmt"
	"image/color"
	"sync"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/driver/desktop"
	"fyne.io/fyne/v2/layout"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"
)

type MessageRole string

const (
	RoleUser   MessageRole = "user"
	RoleJarvis MessageRole = "jarvis"
	RoleStatus MessageRole = "status"
)

type ChatMessage struct {
	Role MessageRole
	Text string
	Time time.Time
}

// ── iconBtn – runder Icon-Button mit Hover-Kreis (Android IconButton-Stil) ──

type iconBtn struct {
	widget.BaseWidget
	icon    fyne.Resource
	onTap   func()
	hovered bool
}

func newIconBtn(icon fyne.Resource, onTap func()) *iconBtn {
	b := &iconBtn{icon: icon, onTap: onTap}
	b.ExtendBaseWidget(b)
	return b
}

func (b *iconBtn) Tapped(_ *fyne.PointEvent) {
	if b.onTap != nil {
		b.onTap()
	}
}

func (b *iconBtn) MouseIn(_ *desktop.MouseEvent) {
	b.hovered = true
	b.Refresh()
}
func (b *iconBtn) MouseMoved(_ *desktop.MouseEvent) {}
func (b *iconBtn) MouseOut() {
	b.hovered = false
	b.Refresh()
}
func (b *iconBtn) MinSize() fyne.Size { return fyne.NewSize(36, 36) }

func (b *iconBtn) CreateRenderer() fyne.WidgetRenderer {
	bg := canvas.NewCircle(color.RGBA{0xFF, 0xFF, 0xFF, 0x18})
	bg.Hidden = true
	img := canvas.NewImageFromResource(b.icon)
	img.FillMode = canvas.ImageFillContain
	return &iconBtnRenderer{btn: b, bg: bg, img: img}
}

type iconBtnRenderer struct {
	btn *iconBtn
	bg  *canvas.Circle
	img *canvas.Image
}

func (r *iconBtnRenderer) Layout(size fyne.Size) {
	r.bg.Move(fyne.NewPos(0, 0))
	r.bg.Resize(size)
	pad := float32(6)
	r.img.Move(fyne.NewPos(pad, pad))
	r.img.Resize(fyne.NewSize(size.Width-pad*2, size.Height-pad*2))
}
func (r *iconBtnRenderer) MinSize() fyne.Size { return fyne.NewSize(36, 36) }
func (r *iconBtnRenderer) Refresh() {
	r.bg.Hidden = !r.btn.hovered
	r.bg.Refresh()
	r.img.Resource = r.btn.icon
	r.img.Refresh()
}
func (r *iconBtnRenderer) Objects() []fyne.CanvasObject { return []fyne.CanvasObject{r.bg, r.img} }
func (r *iconBtnRenderer) Destroy()                     {}

// ── SendEntry – Enter sendet, Alt+Enter fügt Zeilenumbruch ein ──────────────

type SendEntry struct {
	widget.Entry
	OnSend func()
}

func newSendEntry() *SendEntry {
	e := &SendEntry{}
	e.MultiLine = true
	e.Wrapping = fyne.TextWrapWord
	e.ExtendBaseWidget(e)
	return e
}

// TypedShortcut fängt Alt+Enter als Zeilenumbruch ab.
func (e *SendEntry) TypedShortcut(shortcut fyne.Shortcut) {
	if cs, ok := shortcut.(*desktop.CustomShortcut); ok {
		if (cs.KeyName == fyne.KeyReturn || cs.KeyName == fyne.KeyEnter) &&
			cs.Modifier&fyne.KeyModifierAlt != 0 {
			e.Entry.TypedRune('\n')
			return
		}
	}
	e.Entry.TypedShortcut(shortcut)
}

// TypedKey fängt Enter ohne Modifier als Senden ab.
func (e *SendEntry) TypedKey(key *fyne.KeyEvent) {
	if key.Name == fyne.KeyReturn || key.Name == fyne.KeyEnter {
		if e.OnSend != nil {
			e.OnSend()
		}
		return
	}
	e.Entry.TypedKey(key)
}

// ── Chat-Manager ──────────────────────────────────────────────────────────────

type ChatWidget struct {
	mu       sync.Mutex
	messages []ChatMessage

	// Selektionsmodus (analog Android)
	selMode  bool
	selSet   map[int]bool // ausgewählte Nachrichten-Indices

	Scroll    *container.Scroll
	MsgBox    *fyne.Container
	Input     *SendEntry
	SendBtn   *widget.Button
	MicBtn    *widget.Button
	TtsStopBtn    *widget.Button // Stop-Button für laufende TTS (nur sichtbar während Wiedergabe)
	TtsToggleBtn  *widget.Button // Toggle-Button: Sprachausgabe an/aus
	StopAgentBtn  *widget.Button // Abbrechen-Button für laufende Agent-Anfrage
	StatusLbl     *canvas.Text
	ConnDot   *canvas.Circle
	ConnLabel *canvas.Text

	// Header-Elemente (werden bei Moduswechsel umgeschaltet)
	headerNormal    fyne.CanvasObject
	headerSelection fyne.CanvasObject
	headerStack     *fyne.Container // container.NewStack – zeigt immer nur einen Header
	selCountLbl     *canvas.Text

	ironManImg *canvas.Image // Avatar-Bild (für Show/Hide)

	OnSend        func(string)
	OnMicButton   func()
	OnSettings    func()
	OnTTSStop     func()    // laufende TTS-Wiedergabe unterbrechen
	OnTTSToggle   func()    // Sprachausgabe an/aus umschalten
	OnStopAgent   func()   // laufende Agent-Anfrage abbrechen
}

func NewChatWidget() *ChatWidget {
	c := &ChatWidget{selSet: make(map[int]bool)}

	c.MsgBox = container.NewVBox()
	c.Scroll = container.NewScroll(c.MsgBox)
	c.Scroll.Direction = container.ScrollVerticalOnly

	c.Input = newSendEntry()
	c.Input.SetPlaceHolder("Nachricht an Jarvis…")
	c.Input.OnSend = func() { c.submit() }

	sendIcon := widget.NewButton("➤", func() { c.submit() })
	sendIcon.Importance = widget.HighImportance
	c.SendBtn = sendIcon

	micBtn := widget.NewButtonWithIcon("", MicIcon, func() {
		if c.OnMicButton != nil {
			c.OnMicButton()
		}
	})
	micBtn.Importance = widget.MediumImportance
	c.MicBtn = micBtn

	ttsStopBtn := widget.NewButtonWithIcon("", theme.MediaStopIcon(), func() {
		if c.OnTTSStop != nil {
			c.OnTTSStop()
		}
	})
	ttsStopBtn.Importance = widget.DangerImportance
	ttsStopBtn.Hide()
	c.TtsStopBtn = ttsStopBtn

	ttsToggleBtn := widget.NewButtonWithIcon("", theme.VolumeUpIcon(), func() {
		if c.OnTTSToggle != nil {
			c.OnTTSToggle()
		}
	})
	ttsToggleBtn.Importance = widget.MediumImportance
	c.TtsToggleBtn = ttsToggleBtn

	stopAgentBtn := widget.NewButtonWithIcon("Abbrechen", theme.CancelIcon(), func() {
		if c.OnStopAgent != nil {
			c.OnStopAgent()
		}
	})
	stopAgentBtn.Importance = widget.DangerImportance
	stopAgentBtn.Hide()
	c.StopAgentBtn = stopAgentBtn

	c.StatusLbl = canvas.NewText("", jc.muted)
	c.StatusLbl.TextSize = 11
	c.StatusLbl.Alignment = fyne.TextAlignCenter

	// Verbindungs-Dot: startet grau (getrennt)
	c.ConnDot = canvas.NewCircle(jc.danger)
	c.ConnLabel = canvas.NewText("getrennt", jc.muted)
	c.ConnLabel.TextSize = 11

	return c
}

// SetAvatarVisible blendet den Iron Man Avatar ein/aus.
func (c *ChatWidget) SetAvatarVisible(visible bool) {
	if c.ironManImg == nil {
		return
	}
	if visible {
		c.ironManImg.Show()
	} else {
		c.ironManImg.Hide()
	}
	c.ironManImg.Refresh()
}

// SetAgentRunning blendet den Abbrechen-Button ein/aus.
func (c *ChatWidget) SetAgentRunning(running bool) {
	if c.StopAgentBtn == nil {
		return
	}
	if running {
		c.StopAgentBtn.Show()
	} else {
		c.StopAgentBtn.Hide()
	}
	c.StopAgentBtn.Refresh()
}

// SetTTSSpeaking blendet den TTS-Stop-Button ein/aus.
func (c *ChatWidget) SetTTSSpeaking(speaking bool) {
	if c.TtsStopBtn == nil {
		return
	}
	if speaking {
		c.TtsStopBtn.Show()
	} else {
		c.TtsStopBtn.Hide()
	}
	c.TtsStopBtn.Refresh()
}

// SetTTSEnabled aktualisiert das Icon des TTS-Toggle-Buttons.
func (c *ChatWidget) SetTTSEnabled(enabled bool) {
	if c.TtsToggleBtn == nil {
		return
	}
	if enabled {
		c.TtsToggleBtn.SetIcon(theme.VolumeUpIcon())
	} else {
		c.TtsToggleBtn.SetIcon(theme.VolumeMuteIcon())
	}
	c.TtsToggleBtn.Refresh()
}

// SetConnectionState aktualisiert Farbe und Text des Verbindungs-Dots im Header.
// state: "connected" | "connecting" | "disconnected" | "error"
func (c *ChatWidget) SetConnectionState(state string) {
	switch state {
	case "connected":
		c.ConnDot.FillColor = jc.success
		c.ConnLabel.Text = "verbunden"
	case "connecting":
		c.ConnDot.FillColor = color.RGBA{0xFF, 0xFF, 0x00, 0xFF} // Gelb
		c.ConnLabel.Text = "verbinde…"
	default:
		c.ConnDot.FillColor = jc.danger
		c.ConnLabel.Text = "getrennt"
	}
	c.ConnDot.Refresh()
	c.ConnLabel.Refresh()
}

// bgPalette enthält vordefinierte Hintergrundfarben (analog Android-Farbpalette).
var bgPalette = []color.RGBA{
	{0x14, 0x0A, 0x28, 0xFF}, // 0: Dunkel-Lila (Standard)
	{0x0D, 0x1B, 0x2A, 0xFF}, // 1: Tief-Blau
	{0x04, 0x06, 0x10, 0xFF}, // 2: Fast Schwarz
	{0x0A, 0x17, 0x0A, 0xFF}, // 3: Dunkel-Grün
	{0x2A, 0x0A, 0x0A, 0xFF}, // 4: Dunkel-Rot
	{0x1A, 0x10, 0x00, 0xFF}, // 5: Dunkel-Gold
}

// BgColorNames sind die Anzeigenamen zu bgPalette (für Settings-Dropdown).
var BgColorNames = []string{
	"Dunkel-Lila (Standard)",
	"Tief-Blau",
	"Fast Schwarz",
	"Dunkel-Grün",
	"Dunkel-Rot",
	"Dunkel-Gold",
}

// Layout gibt das fertige Container-Objekt zurück. cfg bestimmt den Hintergrund.
func (c *ChatWidget) Layout(cfg *Config) fyne.CanvasObject {
	header := c.buildChatHeader()

	// Input-Bar: [🔊] [🎤] [Texteingabe────] [⏹(TTS)] [➤]
	sendWrapped := container.NewGridWrap(fyne.NewSize(44, 44), c.SendBtn)
	ttsStopWrapped := container.NewGridWrap(fyne.NewSize(44, 44), c.TtsStopBtn)
	ttsToggleWrapped := container.NewGridWrap(fyne.NewSize(44, 44), c.TtsToggleBtn)
	micWrapped := container.NewGridWrap(fyne.NewSize(44, 44), c.MicBtn)
	leftBtns := container.NewHBox(ttsToggleWrapped, micWrapped)
	inputRow := container.NewBorder(nil, nil, leftBtns,
		container.NewHBox(ttsStopWrapped, sendWrapped), c.Input)
	// Input-Bar: Gradient surfaceVariant → surface (Android-Elevation-Effekt)
	inputBg := canvas.NewVerticalGradient(
		color.RGBA{0x12, 0x1A, 0x36, 0xFF}, // oben dunkler
		color.RGBA{0x1A, 0x1A, 0x2E, 0xFF}, // surface unten
	)
	sep := canvas.NewLine(color.RGBA{0x9B, 0x59, 0xB6, 0x40}) // lila Trennlinie
	// Statuszeile: [StatusText ──────────────] [Abbrechen]
	statusRow := container.NewBorder(nil, nil, nil,
		c.StopAgentBtn,
		c.StatusLbl,
	)
	inputArea := container.NewStack(inputBg,
		container.NewVBox(
			sep,
			statusRow,
			container.NewPadded(inputRow),
		))

	// Iron Man Avatar (unten-rechts, 70% Opacity – identisch Android)
	ironManRes := fyne.NewStaticResource("ironman", ironManAvatarBytes)
	ironManImg := canvas.NewImageFromResource(ironManRes)
	ironManImg.FillMode = canvas.ImageFillContain
	ironManImg.Translucency = 0.30 // 70% sichtbar = 30% transparent
	c.ironManImg = ironManImg      // Referenz speichern
	ironManSized := container.NewGridWrap(fyne.NewSize(120, 150), ironManImg)
	// Overlay: unsichtbarer Hintergrund + Avatar unten-rechts mit Abstand
	ironManOverlay := container.NewBorder(nil,
		container.NewHBox(layout.NewSpacer(), container.NewPadded(ironManSized)),
		nil, nil,
		canvas.NewRectangle(colorTransparent))

	// Hintergrund je nach Konfiguration
	var bgGlow fyne.CanvasObject
	switch cfg.BackgroundType {
	case "color":
		idx := cfg.BackgroundColor
		if idx < 0 || idx >= len(bgPalette) {
			idx = 0
		}
		bgGlow = canvas.NewRectangle(bgPalette[idx])
	case "photo":
		var img *canvas.Image
		if cfg.BackgroundImagePath == BG_DEFAULT_URI || cfg.BackgroundImagePath == "" {
			res := fyne.NewStaticResource("bg_jarvis.jpg", bgJarvisJPG)
			img = canvas.NewImageFromResource(res)
		} else {
			img = canvas.NewImageFromFile(cfg.BackgroundImagePath)
		}
		img.FillMode = canvas.ImageFillContain
		img.Translucency = float64(1.0 - cfg.BackgroundAlpha)
		bgGlow = img
	default: // "gradient"
		bgGlow = canvas.NewVerticalGradient(
			color.RGBA{0x14, 0x0A, 0x28, 0xFF},
			color.RGBA{0x04, 0x06, 0x10, 0xFF},
		)
	}
	// Scroll-Bereich mit Iron Man Overlay stapeln
	scrollWithAvatar := container.NewStack(c.Scroll, ironManOverlay)

	return container.NewStack(bgGlow,
		container.NewBorder(header, inputArea, nil, nil, scrollWithAvatar))
}

// buildChatHeader erstellt den Header-Stack (Normal + Selektion).
// headerStack enthält beide Header; jeweils einer wird ausgeblendet.
func (c *ChatWidget) buildChatHeader() fyne.CanvasObject {
	headerBg := func() fyne.CanvasObject {
		return canvas.NewVerticalGradient(
			color.RGBA{0x1E, 0x28, 0x4A, 0xFF},
			color.RGBA{0x12, 0x1A, 0x36, 0xFF},
		)
	}
	sep := func() fyne.CanvasObject {
		return canvas.NewLine(color.RGBA{0x9B, 0x59, 0xB6, 0x40})
	}

	// ── Normal-Header ─────────────────────────────────────────────────────────
	dot := container.NewGridWrap(fyne.NewSize(10, 10), c.ConnDot)
	title := canvas.NewText("Jarvis", jc.textPrimary)
	title.TextStyle = fyne.TextStyle{Bold: true}
	title.TextSize = 18
	c.ConnLabel.TextSize = 12
	titleRow := container.NewHBox(dot, container.NewPadded(title), c.ConnLabel)

	deleteBtn := newIconBtn(theme.DeleteIcon(), func() { c.enterSelectionMode(-1) })
	settingsBtn := newIconBtn(theme.SettingsIcon(), func() {
		if c.OnSettings != nil {
			c.OnSettings()
		}
	})
	normalRow := container.NewBorder(nil, nil, nil,
		container.NewHBox(deleteBtn, settingsBtn),
		container.NewPadded(titleRow))
	c.headerNormal = container.NewStack(headerBg(),
		container.NewVBox(container.NewPadded(normalRow), sep()))

	// ── Selektion-Header ──────────────────────────────────────────────────────
	c.selCountLbl = canvas.NewText("0 ausgewählt", jc.textPrimary)
	c.selCountLbl.TextStyle = fyne.TextStyle{Bold: true}
	c.selCountLbl.TextSize = 16

	cancelBtn := newIconBtn(theme.CancelIcon(), func() { c.exitSelectionMode() })
	selectAllBtn := widget.NewButton("Alle", func() { c.selectAll() })
	selectAllBtn.Importance = widget.LowImportance
	confirmDeleteBtn := newIconBtn(theme.DeleteIcon(), func() { c.deleteSelected() })
	selRow := container.NewBorder(nil, nil, cancelBtn,
		container.NewHBox(selectAllBtn, confirmDeleteBtn),
		container.NewCenter(c.selCountLbl))
	c.headerSelection = container.NewStack(headerBg(),
		container.NewVBox(container.NewPadded(selRow), sep()))
	c.headerSelection.Hide()

	c.headerStack = container.NewStack(c.headerNormal, c.headerSelection)
	return c.headerStack
}

// ── Selektionsmodus ───────────────────────────────────────────────────────────

// enterSelectionMode wechselt in den Selektionsmodus.
// preselect >= 0 wählt diese Nachricht direkt aus.
func (c *ChatWidget) enterSelectionMode(preselect int) {
	c.selMode = true
	c.selSet = make(map[int]bool)
	if preselect >= 0 {
		c.selSet[preselect] = true
	}
	c.headerNormal.Hide()
	c.headerSelection.Show()
	c.updateSelCount()
	c.rebuildAll()
}

func (c *ChatWidget) exitSelectionMode() {
	c.selMode = false
	c.selSet = make(map[int]bool)
	c.headerSelection.Hide()
	c.headerNormal.Show()
	c.rebuildAll()
}

func (c *ChatWidget) toggleSelection(idx int) {
	if c.selSet[idx] {
		delete(c.selSet, idx)
	} else {
		c.selSet[idx] = true
	}
	c.updateSelCount()
	c.rebuildAll()
}

func (c *ChatWidget) updateSelCount() {
	n := len(c.selSet)
	if n == 0 {
		c.selCountLbl.Text = "Tippe zum Auswählen"
	} else {
		c.selCountLbl.Text = fmt.Sprintf("%d ausgewählt", n)
	}
	c.selCountLbl.Refresh()
}

func (c *ChatWidget) deleteSelected() {
	if len(c.selSet) == 0 {
		return
	}
	c.mu.Lock()
	// Neue messages-Liste ohne die ausgewählten Indizes aufbauen
	newMsgs := make([]ChatMessage, 0, len(c.messages))
	for i, m := range c.messages {
		if !c.selSet[i] {
			newMsgs = append(newMsgs, m)
		}
	}
	c.messages = newMsgs
	snap := append([]ChatMessage(nil), c.messages...)
	c.mu.Unlock()
	go SaveHistory(snap)
	c.exitSelectionMode()
}

func (c *ChatWidget) selectAll() {
	c.mu.Lock()
	allSelected := len(c.selSet) == len(c.messages)
	if allSelected {
		c.selSet = make(map[int]bool)
	} else {
		for i := range c.messages {
			c.selSet[i] = true
		}
	}
	c.mu.Unlock()
	c.updateSelCount()
	c.rebuildAll()
}

// rebuildAll rendert alle Nachrichten neu (z.B. nach Moduswechsel).
func (c *ChatWidget) rebuildAll() {
	c.mu.Lock()
	msgs := append([]ChatMessage(nil), c.messages...)
	c.mu.Unlock()
	c.MsgBox.Objects = nil
	var lastDate time.Time
	for i, m := range msgs {
		if lastDate.IsZero() || !sameDay(lastDate, m.Time) {
			c.MsgBox.Objects = append(c.MsgBox.Objects, buildDateSeparator(m.Time))
			lastDate = m.Time
		}
		c.MsgBox.Add(c.buildRowAt(m, i))
	}
	c.MsgBox.Refresh()
}

func (c *ChatWidget) submit() {
	text := c.Input.Text
	if text == "" {
		return
	}
	c.Input.SetText("")
	if c.OnSend != nil {
		c.OnSend(text)
	}
}

// Submit sendet Text direkt über OnSend – kein Umweg über das Input-Widget.
func (c *ChatWidget) Submit(text string) {
	if text == "" {
		return
	}
	if c.OnSend != nil {
		c.OnSend(text)
	}
}

// buildDateSeparator erstellt eine zentrierte Datumszeile (z.B. "Mittwoch, 9. April 2025")
func buildDateSeparator(t time.Time) fyne.CanvasObject {
	weekdays := []string{"Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"}
	months := []string{"", "Januar", "Februar", "März", "April", "Mai", "Juni",
		"Juli", "August", "September", "Oktober", "November", "Dezember"}
	label := fmt.Sprintf("%s, %d. %s %d",
		weekdays[t.Weekday()], t.Day(), months[t.Month()], t.Year())
	lbl := widget.NewLabel(label)
	lbl.Importance = widget.LowImportance
	lbl.Alignment = fyne.TextAlignCenter
	sep1 := widget.NewSeparator()
	sep2 := widget.NewSeparator()
	return container.NewVBox(
		vSpacer(4),
		container.NewBorder(nil, nil, sep1, sep2, container.NewCenter(lbl)),
		vSpacer(4),
	)
}

// sameDay returns true if two times are on the same calendar day.
func sameDay(t1, t2 time.Time) bool {
	ay, am, ad := t1.Date()
	by, bm, bd := t2.Date()
	return ay == by && am == bm && ad == bd
}

// ── Nachrichten hinzufügen ────────────────────────────────────────────────────

func (c *ChatWidget) AddMessage(role MessageRole, text string) {
	c.mu.Lock()
	msg := ChatMessage{Role: role, Text: text, Time: time.Now()}
	// Datum-Trenner wenn erster Eintrag des Tages
	var addSep bool
	if len(c.messages) == 0 || !sameDay(c.messages[len(c.messages)-1].Time, msg.Time) {
		addSep = true
	}
	c.messages = append(c.messages, msg)
	snap := append([]ChatMessage(nil), c.messages...)
	c.mu.Unlock()

	if addSep {
		c.MsgBox.Add(buildDateSeparator(msg.Time))
	}
	row := c.buildRow(msg)
	c.MsgBox.Add(row)
	c.MsgBox.Refresh()
	c.scrollToBottom()
	go SaveHistory(snap)
}

// AppendToLast hängt Text an die letzte Jarvis-Nachricht an (Streaming).
func (c *ChatWidget) AppendToLast(text string) {
	c.mu.Lock()
	if len(c.messages) == 0 || c.messages[len(c.messages)-1].Role != RoleJarvis {
		c.mu.Unlock()
		c.AddMessage(RoleJarvis, text)
		return
	}
	c.messages[len(c.messages)-1].Text += text
	last := c.messages[len(c.messages)-1]
	snap := append([]ChatMessage(nil), c.messages...)
	c.mu.Unlock()

	idx := len(c.MsgBox.Objects) - 1
	if idx >= 0 {
		c.MsgBox.Objects[idx] = c.buildRow(last)
		c.MsgBox.Refresh()
	}
	c.scrollToBottom()
	go SaveHistory(snap)
}

// AddDebugMessage zeigt eine gedimmte Debug-Zeile (Agent-Denk-Nachrichten).
func (c *ChatWidget) AddDebugMessage(text string) {
	lbl := widget.NewLabel("🔍 " + text)
	lbl.TextStyle = fyne.TextStyle{}
	lbl.Importance = widget.LowImportance
	lbl.Wrapping = fyne.TextWrapWord
	c.MsgBox.Add(container.NewPadded(lbl))
	c.MsgBox.Refresh()
	c.scrollToBottom()
}

// AddStatsMessage zeigt eine kleine LLM-Stats-Zeile (Dauer + Token-Verbrauch).
func (c *ChatWidget) AddStatsMessage(text string) {
	lbl := widget.NewLabel(text)
	lbl.TextStyle = fyne.TextStyle{Italic: true}
	lbl.Importance = widget.LowImportance
	lbl.Wrapping = fyne.TextWrapWord
	c.MsgBox.Add(lbl)
	c.MsgBox.Refresh()
	c.scrollToBottom()
}

func (c *ChatWidget) SetStatus(text string) {
	c.StatusLbl.Text = text
	c.StatusLbl.Refresh()
}

// SetMicActive setzt den visuellen Zustand des Mikrofon-Buttons.
// Aktiv = grün (JarvisGreen wie Android), inaktiv = normal.
func (c *ChatWidget) SetMicActive(active bool) {
	if active {
		c.MicBtn.SetIcon(MicActiveIcon)
		c.MicBtn.Importance = widget.DangerImportance
	} else {
		c.MicBtn.SetIcon(MicIcon)
		c.MicBtn.Importance = widget.MediumImportance
	}
	c.MicBtn.Refresh()
}

// SetInput setzt den Text im Eingabefeld (z.B. nach Spracheingabe).
func (c *ChatWidget) SetInput(text string) {
	c.Input.SetText(text)
	c.Input.CursorRow = 0
	c.Input.Refresh()
}

// TriggerSend sendet den aktuellen Inhalt des Eingabefelds (wie Enter-Taste).
func (c *ChatWidget) TriggerSend() {
	c.submit()
}


func (c *ChatWidget) SetInputEnabled(enabled bool) {
	if enabled {
		c.Input.Enable()
		c.SendBtn.Enable()
	} else {
		c.Input.Disable()
		c.SendBtn.Disable()
	}
}

// LoadHistory lädt gespeicherte Nachrichten und rendert sie.
func (c *ChatWidget) LoadHistory() {
	msgs := LoadHistory()
	if len(msgs) == 0 {
		return
	}
	c.mu.Lock()
	c.messages = msgs
	c.mu.Unlock()
	c.rebuildAll()
	c.scrollToBottom()
}

// ClearMessages löscht alle Nachrichten aus dem Chat und von Disk.
func (c *ChatWidget) ClearMessages() {
	c.mu.Lock()
	c.messages = nil
	c.mu.Unlock()
	c.MsgBox.Objects = nil
	c.MsgBox.Refresh()
	DeleteHistory()
}

// deleteMessageAt löscht die Nachricht an Index idx und baut die MsgBox komplett neu auf.
// Direkter Slice-Zugriff auf Objects ist falsch da AddDebugMessage Objects aber nicht messages befüllt.
func (c *ChatWidget) deleteMessageAt(idx int) {
	c.mu.Lock()
	if idx < 0 || idx >= len(c.messages) {
		c.mu.Unlock()
		return
	}
	c.messages = append(c.messages[:idx], c.messages[idx+1:]...)
	c.mu.Unlock()
	c.rebuildAll()
}

// newBoldWhiteText erstellt einen fett-weißen Textblock mit Zeilenumbruch.
// widget.RichText erlaubt explizite Farbe + Bold + Wrapping.
// newBoldWhiteText: fett-weißer Text, optional mit Zeilenumbruch.
// wrap=false für User-Bubbles (textbreit, kein Umbruch), wrap=true für Jarvis-Bubbles.
func newBoldWhiteText(text string, wrap bool) *widget.RichText {
	rt := widget.NewRichText(&widget.TextSegment{
		Text: text,
		Style: widget.RichTextStyle{
			ColorName: theme.ColorNameForeground,
			TextStyle: fyne.TextStyle{Bold: true},
		},
	})
	if wrap {
		rt.Wrapping = fyne.TextWrapWord
	}
	return rt
}

// ── tappableBubble: Bubble mit Links- und Rechtsklick ────────────────────────

type tappableBubble struct {
	widget.BaseWidget
	inner   fyne.CanvasObject
	text    string // Originaltext der Nachricht (fuer Kopieren)
	onTap   func() // Linksklick (z.B. Auswahl umschalten im Selektionsmodus)
	onRight func() // Rechtsklick (z.B. Selektionsmodus betreten)
}

func newTappableBubble(inner fyne.CanvasObject, text string, onTap func(), onRight func()) *tappableBubble {
	t := &tappableBubble{inner: inner, text: text, onTap: onTap, onRight: onRight}
	t.ExtendBaseWidget(t)
	return t
}

func (t *tappableBubble) CreateRenderer() fyne.WidgetRenderer {
	return widget.NewSimpleRenderer(t.inner)
}

func (t *tappableBubble) Tapped(_ *fyne.PointEvent) {
	if t.onTap != nil {
		t.onTap()
	}
}

func (t *tappableBubble) TappedSecondary(ev *fyne.PointEvent) {
	// Kontextmenue mit "Text kopieren" und "Auswählen"
	c := fyne.CurrentApp().Driver().CanvasForObject(t)
	if c == nil {
		if t.onRight != nil {
			t.onRight()
		}
		return
	}

	copyItem := fyne.NewMenuItem("Text kopieren", func() {
		fyne.CurrentApp().Driver().AllWindows()[0].Clipboard().SetContent(t.text)
	})
	selectItem := fyne.NewMenuItem("Auswählen", func() {
		if t.onRight != nil {
			t.onRight()
		}
	})

	menu := fyne.NewMenu("", copyItem, selectItem)
	popUp := widget.NewPopUpMenu(menu, c)
	popUp.ShowAtPosition(ev.AbsolutePosition)
}

// ── Bubble-Rendering – Android-identisches Design ────────────────────────────

// newJAvatarSmall erstellt den 32×32 Jarvis-Avatar für Jarvis-Bubbles.
// Gradient: JarvisPurple → #6A0DAD (wie Android LinearGradient).
// Fyne unterstützt keinen Gradient auf Circles – wir nutzen accentDark als Näherung.
func newJAvatarSmall() fyne.CanvasObject {
	// Äußerer Kreis (accentDark = #6A0DAD, dunklerer Gradient-Ton)
	outer := canvas.NewCircle(jc.accentDark)
	// Innerer Kreis (accent = #9B59B6, hellerer Gradient-Ton) – leicht kleiner
	inner := canvas.NewCircle(jc.accent)
	letter := canvas.NewText("J", color.White)
	letter.TextStyle = fyne.TextStyle{Bold: true}
	letter.TextSize = 14
	letter.Alignment = fyne.TextAlignCenter
	return container.NewGridWrap(fyne.NewSize(32, 32),
		container.NewStack(outer, inner, container.NewCenter(letter)))
}

// ── selCheckbox – eigene Checkbox ohne Fokusring ──────────────────────────────

type selCheckbox struct {
	widget.BaseWidget
	checked  bool
	onChange func(bool)
}

func newSelCheckbox(checked bool, onChange func(bool)) *selCheckbox {
	c := &selCheckbox{checked: checked, onChange: onChange}
	c.ExtendBaseWidget(c)
	return c
}

func (c *selCheckbox) Tapped(_ *fyne.PointEvent) {
	c.checked = !c.checked
	c.Refresh()
	if c.onChange != nil {
		c.onChange(c.checked)
	}
}

func (c *selCheckbox) MinSize() fyne.Size { return fyne.NewSize(24, 24) }

func (c *selCheckbox) CreateRenderer() fyne.WidgetRenderer {
	border := canvas.NewRectangle(colorTransparent)
	border.StrokeColor = jc.accent
	border.StrokeWidth = 2
	border.CornerRadius = 3
	check := canvas.NewImageFromResource(theme.ConfirmIcon())
	check.FillMode = canvas.ImageFillContain
	return &selCheckboxRenderer{cb: c, border: border, check: check}
}

type selCheckboxRenderer struct {
	cb     *selCheckbox
	border *canvas.Rectangle
	check  *canvas.Image
}

func (r *selCheckboxRenderer) Layout(size fyne.Size) {
	r.border.Resize(size)
	pad := float32(3)
	r.check.Move(fyne.NewPos(pad, pad))
	r.check.Resize(fyne.NewSize(size.Width-pad*2, size.Height-pad*2))
}
func (r *selCheckboxRenderer) MinSize() fyne.Size { return fyne.NewSize(24, 24) }
func (r *selCheckboxRenderer) Refresh() {
	if r.cb.checked {
		r.border.FillColor = jc.accent
		r.check.Hidden = false
	} else {
		r.border.FillColor = colorTransparent
		r.check.Hidden = true
	}
	r.border.Refresh()
	r.check.Refresh()
}
func (r *selCheckboxRenderer) Objects() []fyne.CanvasObject {
	return []fyne.CanvasObject{r.border, r.check}
}
func (r *selCheckboxRenderer) Destroy() {}

// ─────────────────────────────────────────────────────────────────────────────

func (c *ChatWidget) buildRow(msg ChatMessage) fyne.CanvasObject {
	return c.buildRowAt(msg, -1)
}

func (c *ChatWidget) buildRowAt(msg ChatMessage, idx int) fyne.CanvasObject {
	spacing := canvas.NewRectangle(colorTransparent)

	// resolveIdx bestimmt den aktuellen Index zur Laufzeit (Löschungen können ihn verschieben).
	resolveIdx := func() int {
		c.mu.Lock()
		defer c.mu.Unlock()
		for i, m := range c.messages {
			if m.Time == msg.Time && m.Role == msg.Role {
				return i
			}
		}
		return -1
	}

	// Rechtsklick: Selektionsmodus betreten und diese Nachricht vorauswählen.
	rightClickFn := func() {
		cur := resolveIdx()
		if cur >= 0 {
			c.enterSelectionMode(cur)
		}
	}

	// Linksklick auf Bubble: Auswahl umschalten (nur im Selektionsmodus).
	var leftClickFn func()
	if c.selMode {
		leftClickFn = func() {
			cur := resolveIdx()
			if cur >= 0 {
				c.toggleSelection(cur)
			}
		}
	}

	// Eigene Checkbox ohne Fokusring (nur im Selektionsmodus sichtbar).
	var checkBox fyne.CanvasObject
	if c.selMode {
		cb := newSelCheckbox(c.selSet[idx], func(checked bool) {
			cur := resolveIdx()
			if cur < 0 {
				return
			}
			if checked {
				c.selSet[cur] = true
			} else {
				delete(c.selSet, cur)
			}
			c.updateSelCount()
		})
		checkBox = container.NewCenter(container.NewGridWrap(fyne.NewSize(28, 28), cb))
	}

	switch msg.Role {

	case RoleStatus:
		lbl := canvas.NewText(msg.Text, jc.muted)
		lbl.TextSize = 11
		lbl.Alignment = fyne.TextAlignCenter
		return container.NewVBox(
			container.NewGridWrap(fyne.NewSize(1, 4), spacing),
			container.NewCenter(lbl),
			container.NewGridWrap(fyne.NewSize(1, 4), spacing),
		)

	case RoleUser:
		bg := canvas.NewRectangle(jc.userBubble)
		bg.CornerRadius = 18
		inner := container.NewStack(bg, container.NewPadded(newBoldWhiteText(msg.Text, false)))
		bubble := newTappableBubble(inner, msg.Text, leftClickFn, rightClickFn)
		var row fyne.CanvasObject
		if c.selMode {
			row = container.NewHBox(checkBox, layout.NewSpacer(), bubble)
		} else {
			row = container.NewHBox(layout.NewSpacer(), bubble)
		}
		timeLabel := canvas.NewText(msg.Time.Format("15:04"), jc.muted)
		timeLabel.TextSize = 10
		return container.NewVBox(
			container.NewGridWrap(fyne.NewSize(1, 8), spacing),
			container.NewHBox(layout.NewSpacer(), timeLabel),
			container.NewGridWrap(fyne.NewSize(1, 2), canvas.NewRectangle(colorTransparent)),
			row,
		)

	default: // RoleJarvis
		bg := canvas.NewRectangle(color.RGBA{0xFF, 0xFF, 0xFF, 0x38})
		bg.CornerRadius = 18
		inner := container.NewStack(bg, container.NewPadded(newBoldWhiteText(msg.Text, true)))
		bubble := newTappableBubble(inner, msg.Text, leftClickFn, rightClickFn)
		avatar := newJAvatarSmall()
		gap := container.NewGridWrap(fyne.NewSize(8, 1), canvas.NewRectangle(colorTransparent))
		rightSpacer := container.NewGridWrap(fyne.NewSize(60, 1), canvas.NewRectangle(colorTransparent))
		var leftPart fyne.CanvasObject
		if c.selMode {
			leftPart = container.NewHBox(checkBox, avatar, gap)
		} else {
			leftPart = container.NewHBox(avatar, gap)
		}
		// Einrückung passend zur Avatar-Breite (32dp) + Gap (8dp)
		avatarIndent := container.NewGridWrap(fyne.NewSize(40, 1), canvas.NewRectangle(colorTransparent))
		timeLabel := canvas.NewText(msg.Time.Format("15:04"), jc.muted)
		timeLabel.TextSize = 10
		return container.NewVBox(
			container.NewGridWrap(fyne.NewSize(1, 8), spacing),
			container.NewHBox(avatarIndent, timeLabel),
			container.NewGridWrap(fyne.NewSize(1, 2), canvas.NewRectangle(colorTransparent)),
			container.NewBorder(nil, nil, leftPart, rightSpacer, bubble),
		)
	}
}

func (c *ChatWidget) scrollToBottom() {
	go func() {
		// Kurz warten damit Fyne das Layout berechnen kann
		time.Sleep(80 * time.Millisecond)
		c.Scroll.ScrollToBottom()
		// Zweiter Versuch für große Historien (Fyne braucht ggf. mehrere Frames)
		time.Sleep(150 * time.Millisecond)
		c.Scroll.ScrollToBottom()
	}()
}
