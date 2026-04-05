package main

import _ "embed"

// Iron Man Helm – wird als Tray-Icon UND als Avatar verwendet
//
//go:embed jarvis_tray.ico
var jarvisTrayICO []byte

//go:embed ironman_avatar.png
var ironManAvatarBytes []byte
