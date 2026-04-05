package main

import (
	"image/color"
	"sync"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/canvas"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/layout"
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

// ── Chat-Manager ──────────────────────────────────────────────────────────────

type ChatWidget struct {
	mu       sync.Mutex
	messages []ChatMessage

	Scroll    *container.Scroll
	MsgBox    *fyne.Container
	Input     *widget.Entry
	SendBtn   *widget.Button
	MicBtn    *widget.Button
	StatusLbl *canvas.Text

	OnSend      func(string)
	OnMicButton func()
}

func NewChatWidget() *ChatWidget {
	c := &ChatWidget{}

	c.MsgBox = container.NewVBox()
	c.Scroll = container.NewScroll(c.MsgBox)
	c.Scroll.Direction = container.ScrollVerticalOnly

	c.Input = widget.NewMultiLineEntry()
	c.Input.SetPlaceHolder("Nachricht an Jarvis…")
	c.Input.Wrapping = fyne.TextWrapWord

	sendIcon := widget.NewButton("➤", func() { c.submit() })
	sendIcon.Importance = widget.HighImportance
	c.SendBtn = sendIcon

	micBtn := widget.NewButton("🎤", func() {
		if c.OnMicButton != nil {
			c.OnMicButton()
		}
	})
	micBtn.Importance = widget.MediumImportance
	c.MicBtn = micBtn

	c.StatusLbl = canvas.NewText("", jc.muted)
	c.StatusLbl.TextSize = 11
	c.StatusLbl.Alignment = fyne.TextAlignCenter

	return c
}

// Layout gibt das fertige Container-Objekt zurück.
func (c *ChatWidget) Layout() fyne.CanvasObject {
	// Header: "J" Logo + Titel + Status
	header := buildChatHeader()

	inputRow := container.NewBorder(nil, nil, nil,
		container.NewHBox(c.MicBtn, c.SendBtn),
		container.NewPadded(c.Input))
	inputBg := canvas.NewRectangle(color.RGBA{0x0F, 0x17, 0x2A, 0xFF})
	inputArea := container.NewStack(inputBg,
		container.NewVBox(
			canvas.NewLine(color.RGBA{0xFF, 0xFF, 0xFF, 0x14}),
			c.StatusLbl,
			inputRow,
		))

	bg := canvas.NewRectangle(jc.bg)
	return container.NewStack(bg,
		container.NewBorder(header, inputArea, nil, nil, c.Scroll))
}

func buildChatHeader() fyne.CanvasObject {
	// J-Kreis
	jCircle := canvas.NewCircle(jc.accent)
	jLetter := canvas.NewText("J", color.White)
	jLetter.TextStyle = fyne.TextStyle{Bold: true}
	jLetter.TextSize = 16
	jLetter.Alignment = fyne.TextAlignCenter
	jAvatar := container.NewGridWrap(fyne.NewSize(36, 36),
		container.NewStack(jCircle, container.NewCenter(jLetter)))

	title := canvas.NewText("Jarvis AI", jc.textPrimary)
	title.TextStyle = fyne.TextStyle{Bold: true}
	title.TextSize = 15

	subtitle := canvas.NewText("Intelligenter Assistent", jc.muted)
	subtitle.TextSize = 11

	titleStack := container.NewVBox(title, subtitle)
	row := container.NewHBox(jAvatar, container.NewPadded(titleStack))

	headerBg := canvas.NewRectangle(color.RGBA{0x0F, 0x17, 0x2A, 0xFF})
	sep := canvas.NewLine(color.RGBA{0xFF, 0xFF, 0xFF, 0x14})
	return container.NewStack(headerBg,
		container.NewVBox(container.NewPadded(row), sep))
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
	c.mu.Unlock()

	row := c.buildRow(msg)
	c.MsgBox.Add(row)
	c.MsgBox.Refresh()
	c.scrollToBottom()
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
	c.mu.Unlock()

	idx := len(c.MsgBox.Objects) - 1
	if idx >= 0 {
		c.MsgBox.Objects[idx] = c.buildRow(last)
		c.MsgBox.Refresh()
	}
	c.scrollToBottom()
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

// SetMicActive setzt den visuellen Zustand des Mikrofon-Buttons (Aufnahme läuft = rot).
func (c *ChatWidget) SetMicActive(active bool) {
	if active {
		c.MicBtn.SetText("🔴")
		c.MicBtn.Importance = widget.DangerImportance
	} else {
		c.MicBtn.SetText("🎤")
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

// ── Bubble-Rendering Android-Stil ─────────────────────────────────────────────

const maxBubbleW float32 = 300

func newJAvatarSmall() fyne.CanvasObject {
	circle := canvas.NewCircle(jc.accent)
	letter := canvas.NewText("J", color.White)
	letter.TextStyle = fyne.TextStyle{Bold: true}
	letter.TextSize = 12
	letter.Alignment = fyne.TextAlignCenter
	return container.NewGridWrap(fyne.NewSize(28, 28),
		container.NewStack(circle, container.NewCenter(letter)))
}

func (c *ChatWidget) buildRow(msg ChatMessage) fyne.CanvasObject {
	switch msg.Role {
	case RoleStatus:
		lbl := canvas.NewText(msg.Text, jc.muted)
		lbl.TextSize = 11
		lbl.Alignment = fyne.TextAlignCenter
		return container.NewPadded(container.NewCenter(lbl))

	case RoleUser:
		bg := canvas.NewRectangle(jc.userBubble)
		bg.CornerRadius = 16
		ts := canvas.NewText(msg.Time.Format("15:04"), jc.muted)
		ts.TextSize = 10
		lbl := widget.NewLabel(msg.Text)
		lbl.Wrapping = fyne.TextWrapWord
		inner := container.NewVBox(lbl, container.NewHBox(layout.NewSpacer(), ts))
		content := container.NewStack(bg, container.NewPadded(inner))
		sized := container.NewGridWrap(fyne.NewSize(maxBubbleW, 0), content)
		return container.NewPadded(container.NewHBox(layout.NewSpacer(), sized))

	default: // RoleJarvis
		bg := canvas.NewRectangle(color.RGBA{0x1E, 0x29, 0x3B, 0xFF})
		bg.CornerRadius = 16
		ts := canvas.NewText(msg.Time.Format("15:04"), jc.muted)
		ts.TextSize = 10
		lbl := widget.NewLabel(msg.Text)
		lbl.Wrapping = fyne.TextWrapWord
		inner := container.NewVBox(lbl, ts)
		content := container.NewStack(bg, container.NewPadded(inner))
		sized := container.NewGridWrap(fyne.NewSize(maxBubbleW, 0), content)
		avatar := newJAvatarSmall()
		return container.NewPadded(container.NewHBox(avatar, sized, layout.NewSpacer()))
	}
}

func (c *ChatWidget) scrollToBottom() {
	go func() {
		time.Sleep(60 * time.Millisecond)
		c.Scroll.ScrollToBottom()
	}()
}
