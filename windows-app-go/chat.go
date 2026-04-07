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
	StatusLbl *canvas.Text
	ConnDot   *canvas.Circle
	ConnLabel *canvas.Text

	// Header-Elemente (werden bei Moduswechsel umgeschaltet)
	headerNormal    fyne.CanvasObject
	headerSelection fyne.CanvasObject
	headerStack     *fyne.Container // container.NewStack – zeigt immer nur einen Header
	selCountLbl     *canvas.Text

	OnSend      func(string)
	OnMicButton func()
	OnSettings  func()
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

	c.StatusLbl = canvas.NewText("", jc.muted)
	c.StatusLbl.TextSize = 11
	c.StatusLbl.Alignment = fyne.TextAlignCenter

	// Verbindungs-Dot: startet grau (getrennt)
	c.ConnDot = canvas.NewCircle(jc.danger)
	c.ConnLabel = canvas.NewText("getrennt", jc.muted)
	c.ConnLabel.TextSize = 11

	return c
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

	// Input-Bar horizontal: [🎤] [Texteingabe────] [➤]  (identisch Android)
	// Buttons quadratisch (44×44) → wirken runder, ähnlich Android FAB
	sendWrapped := container.NewGridWrap(fyne.NewSize(44, 44), c.SendBtn)
	micWrapped := container.NewGridWrap(fyne.NewSize(44, 44), c.MicBtn)
	inputRow := container.NewBorder(nil, nil, micWrapped, sendWrapped, c.Input)
	// Input-Bar: Gradient surfaceVariant → surface (Android-Elevation-Effekt)
	inputBg := canvas.NewVerticalGradient(
		color.RGBA{0x12, 0x1A, 0x36, 0xFF}, // oben dunkler
		color.RGBA{0x1A, 0x1A, 0x2E, 0xFF}, // surface unten
	)
	sep := canvas.NewLine(color.RGBA{0x9B, 0x59, 0xB6, 0x40}) // lila Trennlinie
	inputArea := container.NewStack(inputBg,
		container.NewVBox(
			sep,
			c.StatusLbl,
			container.NewPadded(inputRow),
		))

	// Iron Man Avatar (unten-rechts, 70% Opacity – identisch Android)
	ironManRes := fyne.NewStaticResource("ironman", ironManAvatarBytes)
	ironManImg := canvas.NewImageFromResource(ironManRes)
	ironManImg.FillMode = canvas.ImageFillContain
	ironManImg.Translucency = 0.30 // 70% sichtbar = 30% transparent
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
	confirmDeleteBtn := newIconBtn(theme.DeleteIcon(), func() { c.deleteSelected() })
	selRow := container.NewBorder(nil, nil, cancelBtn, confirmDeleteBtn,
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
	// Nur die betroffene Zeile neu rendern
	if idx < len(c.MsgBox.Objects) {
		c.mu.Lock()
		msg := c.messages[idx]
		c.mu.Unlock()
		c.MsgBox.Objects[idx] = c.buildRowAt(msg, idx)
		c.MsgBox.Refresh()
	}
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
	// Indices absteigend löschen damit Verschiebungen korrekt sind
	c.mu.Lock()
	indices := make([]int, 0, len(c.selSet))
	for i := range c.selSet {
		indices = append(indices, i)
	}
	// Sortieren absteigend
	for i := 0; i < len(indices)-1; i++ {
		for j := i + 1; j < len(indices); j++ {
			if indices[j] > indices[i] {
				indices[i], indices[j] = indices[j], indices[i]
			}
		}
	}
	for _, idx := range indices {
		if idx < len(c.messages) {
			c.messages = append(c.messages[:idx], c.messages[idx+1:]...)
		}
	}
	snap := append([]ChatMessage(nil), c.messages...)
	c.mu.Unlock()
	go SaveHistory(snap)
	c.exitSelectionMode()
}

// rebuildAll rendert alle Nachrichten neu (z.B. nach Moduswechsel).
func (c *ChatWidget) rebuildAll() {
	c.mu.Lock()
	msgs := append([]ChatMessage(nil), c.messages...)
	c.mu.Unlock()
	c.MsgBox.Objects = nil
	for i, m := range msgs {
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

// ── Nachrichten hinzufügen ────────────────────────────────────────────────────

func (c *ChatWidget) AddMessage(role MessageRole, text string) {
	c.mu.Lock()
	msg := ChatMessage{Role: role, Text: text, Time: time.Now()}
	c.messages = append(c.messages, msg)
	snap := append([]ChatMessage(nil), c.messages...)
	c.mu.Unlock()

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
	for _, m := range msgs {
		c.MsgBox.Add(c.buildRow(m))
	}
	c.MsgBox.Refresh()
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

// deleteMessageAt löscht die Nachricht an Index idx (MsgBox-Index entspricht messages-Index).
func (c *ChatWidget) deleteMessageAt(idx int) {
	c.mu.Lock()
	if idx < 0 || idx >= len(c.messages) {
		c.mu.Unlock()
		return
	}
	c.messages = append(c.messages[:idx], c.messages[idx+1:]...)
	c.mu.Unlock()
	if idx < len(c.MsgBox.Objects) {
		c.MsgBox.Objects = append(c.MsgBox.Objects[:idx], c.MsgBox.Objects[idx+1:]...)
		c.MsgBox.Refresh()
	}
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
	onTap   func() // Linksklick (z.B. Auswahl umschalten im Selektionsmodus)
	onRight func() // Rechtsklick (z.B. Selektionsmodus betreten)
}

func newTappableBubble(inner fyne.CanvasObject, onTap func(), onRight func()) *tappableBubble {
	t := &tappableBubble{inner: inner, onTap: onTap, onRight: onRight}
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

func (t *tappableBubble) TappedSecondary(_ *fyne.PointEvent) {
	if t.onRight != nil {
		t.onRight()
	}
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
		bubble := newTappableBubble(inner, leftClickFn, rightClickFn)
		var row fyne.CanvasObject
		if c.selMode {
			row = container.NewHBox(checkBox, layout.NewSpacer(), bubble)
		} else {
			row = container.NewHBox(layout.NewSpacer(), bubble)
		}
		return container.NewVBox(
			container.NewGridWrap(fyne.NewSize(1, 8), spacing),
			row,
		)

	default: // RoleJarvis
		bg := canvas.NewRectangle(color.RGBA{0xFF, 0xFF, 0xFF, 0x38})
		bg.CornerRadius = 18
		inner := container.NewStack(bg, container.NewPadded(newBoldWhiteText(msg.Text, true)))
		bubble := newTappableBubble(inner, leftClickFn, rightClickFn)
		avatar := newJAvatarSmall()
		gap := container.NewGridWrap(fyne.NewSize(8, 1), canvas.NewRectangle(colorTransparent))
		rightSpacer := container.NewGridWrap(fyne.NewSize(60, 1), canvas.NewRectangle(colorTransparent))
		var leftPart fyne.CanvasObject
		if c.selMode {
			leftPart = container.NewHBox(checkBox, avatar, gap)
		} else {
			leftPart = container.NewHBox(avatar, gap)
		}
		return container.NewVBox(
			container.NewGridWrap(fyne.NewSize(1, 8), spacing),
			container.NewBorder(nil, nil, leftPart, rightSpacer, bubble),
		)
	}
}

func (c *ChatWidget) scrollToBottom() {
	go func() {
		time.Sleep(60 * time.Millisecond)
		c.Scroll.ScrollToBottom()
	}()
}
