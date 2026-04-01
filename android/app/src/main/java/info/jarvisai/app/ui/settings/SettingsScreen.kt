package info.jarvisai.app.ui.settings

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import info.jarvisai.app.BuildConfig
import info.jarvisai.app.R
import info.jarvisai.app.data.prefs.BG_COLOR
import info.jarvisai.app.data.prefs.BG_DEFAULT_URI
import info.jarvisai.app.data.prefs.BG_GRADIENT
import info.jarvisai.app.data.prefs.BG_PHOTO
import info.jarvisai.app.ui.theme.JarvisGreen
import info.jarvisai.app.ui.theme.JarvisPurple

// ─── Wiederverwendbare Bausteine ──────────────────────────────────────────────

@Composable
private fun SectionHeader(title: String) {
    Text(
        text = title,
        fontSize = 15.sp,
        fontWeight = FontWeight.Bold,
        color = Color.White,
        modifier = Modifier.padding(top = 8.dp, bottom = 2.dp),
    )
}

@Composable
private fun SettingRow(
    label: String,
    description: String? = null,
    control: @Composable () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f).padding(end = 12.dp)) {
            Text(label, style = MaterialTheme.typography.bodyMedium)
            if (description != null) {
                Text(
                    description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        control()
    }
}

@Composable
private fun SliderRow(
    label: String,
    description: String? = null,
    value: Float,
    onValueChange: (Float) -> Unit,
    valueRange: ClosedFloatingPointRange<Float>,
    steps: Int = 0,
    enabled: Boolean = true,
    valueLabel: String,
) {
    val contentAlpha = if (enabled) 1f else 0.38f
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    label,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = contentAlpha),
                )
                if (description != null) {
                    Text(
                        description,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = contentAlpha),
                    )
                }
            }
            Text(
                valueLabel,
                style = MaterialTheme.typography.bodySmall,
                fontWeight = FontWeight.Medium,
                color = if (enabled) JarvisGreen else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.38f),
                modifier = Modifier.align(Alignment.CenterVertically).padding(start = 8.dp),
            )
        }
        Slider(
            value = value,
            onValueChange = onValueChange,
            valueRange = valueRange,
            steps = steps,
            enabled = enabled,
            modifier = Modifier.fillMaxWidth(),
            colors = SliderDefaults.colors(thumbColor = JarvisGreen, activeTrackColor = JarvisGreen),
        )
    }
}

// ─── Settings Screen ──────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBack: () -> Unit,
    viewModel: SettingsViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val settings by viewModel.settings.collectAsState()
    val saved by viewModel.saved.collectAsState()
    var apiKeyVisible by remember { mutableStateOf(false) }

    LaunchedEffect(saved) {
        if (saved) {
            kotlinx.coroutines.delay(1500)
            viewModel.resetSaved()
            onBack()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.settings_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Zurück")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                )
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {

            // ── Verbindung ────────────────────────────────────────────────
            SectionHeader("Verbindung")

            OutlinedTextField(
                value = settings.serverUrl,
                onValueChange = viewModel::onServerUrlChange,
                label = { Text("Server-URL") },
                placeholder = { Text("z.B. https://100.x.x.x") },
                supportingText = { Text("Tailscale- oder lokale Adresse des Jarvis-Servers") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            OutlinedTextField(
                value = settings.apiKey,
                onValueChange = viewModel::onApiKeyChange,
                label = { Text("Agent API-Key") },
                placeholder = { Text("AGENT_API_KEY aus Jarvis-Einstellungen") },
                supportingText = { Text("Einstellungen → Agent API-Key in der Jarvis Web-UI") },
                visualTransformation = if (apiKeyVisible) VisualTransformation.None
                                       else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                trailingIcon = {
                    IconButton(onClick = { apiKeyVisible = !apiKeyVisible }) {
                        Icon(
                            imageVector = if (apiKeyVisible) Icons.Filled.VisibilityOff
                                          else Icons.Filled.Visibility,
                            contentDescription = if (apiKeyVisible) "Verbergen" else "Anzeigen",
                        )
                    }
                },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )

            HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))

            // ── Spracheingabe ─────────────────────────────────────────────
            SectionHeader("Spracheingabe")

            SettingRow(
                label = "Automatisch senden",
                description = "Transkribierter Text wird nach der Sprech-Pause direkt gesendet",
            ) {
                Switch(
                    checked = settings.autoSendVoice,
                    onCheckedChange = viewModel::onAutoSendVoiceChange,
                )
            }

            SliderRow(
                label = "Sprech-Pause",
                description = "Stille-Dauer bis die Spracheingabe automatisch abgeschlossen wird",
                value = settings.voiceSilenceMs.toFloat(),
                onValueChange = { viewModel.onVoiceSilenceChange(it.toInt()) },
                valueRange = 500f..2000f,
                steps = 5,
                enabled = settings.autoSendVoice,
                valueLabel = "${"%.1f".format(settings.voiceSilenceMs / 1000f)} s",
            )

            HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))

            // ── Hintergrund ───────────────────────────────────────────────
            SectionHeader("Hintergrund")

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                listOf(
                    BG_GRADIENT to "Gradient",
                    BG_PHOTO    to "Foto",
                    BG_COLOR    to "Farbe",
                ).forEach { (type, label) ->
                    FilterChip(
                        selected = settings.backgroundType == type,
                        onClick = { viewModel.onBackgroundTypeChange(type) },
                        label = { Text(label) },
                        modifier = Modifier.weight(1f),
                    )
                }
            }

            if (settings.backgroundType == BG_PHOTO) {
                val imagePicker = rememberLauncherForActivityResult(
                    ActivityResultContracts.GetContent()
                ) { uri: Uri? ->
                    uri?.let { viewModel.onBackgroundImageUriChange(it.toString()) }
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        onClick = { imagePicker.launch("image/*") },
                        modifier = Modifier.weight(1f),
                    ) {
                        Text(
                            when (settings.backgroundImageUri) {
                                BG_DEFAULT_URI -> "Eigenes Foto wählen"
                                ""             -> "Foto auswählen"
                                else           -> "Foto ändern"
                            }
                        )
                    }
                    if (settings.backgroundImageUri != BG_DEFAULT_URI) {
                        OutlinedButton(onClick = { viewModel.onBackgroundImageUriChange(BG_DEFAULT_URI) }) {
                            Text("Standard")
                        }
                    }
                }

                SliderRow(
                    label = "Helligkeit",
                    description = "Transparenz des Hintergrundbilds",
                    value = settings.backgroundAlpha,
                    onValueChange = viewModel::onBackgroundAlphaChange,
                    valueRange = 0.1f..1.0f,
                    valueLabel = "${(settings.backgroundAlpha * 100).toInt()} %",
                )
            }

            if (settings.backgroundType == BG_COLOR) {
                Text(
                    "Hintergrundfarbe auswählen",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                val colorSwatches = listOf(
                    listOf(0xFF000000.toInt(), 0xFF0A0E17.toInt(), 0xFF0D1B2A.toInt(),
                           0xFF16213E.toInt(), 0xFF1A0A2E.toInt(), 0xFF2D1B69.toInt()),
                    listOf(0xFF1C1C1E.toInt(), 0xFF1A2A1A.toInt(), 0xFF0A2A2A.toInt(),
                           0xFF2A0A0A.toInt(), 0xFF2A1A00.toInt(), 0xFF1A1A00.toInt()),
                )
                colorSwatches.forEach { row ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        row.forEach { argb ->
                            Box(
                                modifier = Modifier
                                    .weight(1f).aspectRatio(1f)
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(Color(argb))
                                    .border(
                                        width = if (settings.backgroundColorArgb == argb) 2.dp else 0.dp,
                                        color = JarvisGreen,
                                        shape = RoundedCornerShape(8.dp),
                                    )
                                    .clickable { viewModel.onBackgroundColorChange(argb) },
                            )
                        }
                    }
                }
            }

            HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))

            // ── Anzeige ───────────────────────────────────────────────────
            SectionHeader("Anzeige")

            // ── Avatar & Stimme ────────────────────────────────────────────
            val availableVoices    by viewModel.availableVoices.collectAsState()
            val serverVoices       by viewModel.serverVoices.collectAsState()
            val serverVoicesLoading by viewModel.serverVoicesLoading.collectAsState()
            var voicePickerOpen    by remember { mutableStateOf(false) }
            var serverVoicePickerOpen by remember { mutableStateOf(false) }

            SettingRow(
                label = "Avatar verwenden",
                description = "Iron Man Helm mit Sprachausgabe im Chat-Hintergrund",
            ) {
                Switch(
                    checked = settings.avatarEnabled,
                    onCheckedChange = viewModel::onAvatarEnabledChange,
                )
            }

            if (settings.avatarEnabled) {
                // ── Server-TTS Toggle ──────────────────────────────────────
                SettingRow(
                    label = "Server-Stimme (edge-tts)",
                    description = "Hochwertige Microsoft Neural Voice vom Jarvis-Server statt Android-TTS",
                ) {
                    Switch(
                        checked = settings.serverTtsEnabled,
                        onCheckedChange = viewModel::onServerTtsEnabledChange,
                    )
                }

                if (settings.serverTtsEnabled) {
                    // Server-Stimme auswählen
                    SettingRow(
                        label = "Server-Stimme",
                        description = settings.serverTtsVoice,
                    ) {
                        OutlinedButton(
                            onClick = {
                                viewModel.loadServerVoices()
                                serverVoicePickerOpen = true
                            },
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                        ) {
                            Text("Wählen", fontSize = 12.sp)
                        }
                    }
                } else {
                    // Android-Stimme auswählen
                    val currentVoiceName = settings.ttsVoiceName.ifBlank { "Automatisch (beste männliche Stimme)" }
                    SettingRow(
                        label = "Android-Stimme",
                        description = currentVoiceName,
                    ) {
                        OutlinedButton(
                            onClick = {
                                viewModel.loadAvailableVoices()
                                voicePickerOpen = true
                            },
                            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
                        ) {
                            Text("Wählen", fontSize = 12.sp)
                        }
                    }
                }
            }

            // ── Server-Stimmen Dialog ──────────────────────────────────────
            if (serverVoicePickerOpen) {
                AlertDialog(
                    onDismissRequest = { serverVoicePickerOpen = false },
                    title = { Text("Server-Stimme (edge-tts)") },
                    text = {
                        if (serverVoicesLoading) {
                            Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                                CircularProgressIndicator()
                            }
                        } else {
                            Column(
                                modifier = Modifier.verticalScroll(rememberScrollState()),
                                verticalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                if (serverVoices.isEmpty()) {
                                    Text(
                                        "Keine Stimmen geladen. Server erreichbar?",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                serverVoices.forEach { voice ->
                                    val selected = settings.serverTtsVoice == voice.name
                                    OutlinedButton(
                                        onClick = {
                                            viewModel.onServerTtsVoiceChange(voice.name)
                                            serverVoicePickerOpen = false
                                        },
                                        modifier = Modifier.fillMaxWidth(),
                                        colors = ButtonDefaults.outlinedButtonColors(
                                            containerColor = if (selected) JarvisPurple.copy(alpha = 0.22f) else Color.Transparent,
                                            contentColor   = if (selected) JarvisPurple else Color.White,
                                        ),
                                        border = BorderStroke(
                                            if (selected) 2.dp else 1.dp,
                                            if (selected) JarvisPurple else Color.White.copy(alpha = 0.30f),
                                        ),
                                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
                                    ) {
                                        val genderIcon = if (voice.gender.lowercase() == "male") "♂ " else "♀ "
                                        Text(genderIcon + voice.name, fontSize = 12.sp, maxLines = 1)
                                    }
                                }
                            }
                        }
                    },
                    confirmButton = {
                        TextButton(onClick = { serverVoicePickerOpen = false }) { Text("Schließen") }
                    },
                )
            }

            // ── Voice-Picker Dialog ────────────────────────────────────────
            if (voicePickerOpen) {
                AlertDialog(
                    onDismissRequest = { voicePickerOpen = false },
                    title = { Text("Stimme auswählen") },
                    text = {
                        Column(
                            modifier = Modifier.verticalScroll(rememberScrollState()),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            // Option: Automatisch
                            val autoSelected = settings.ttsVoiceName.isBlank()
                            OutlinedButton(
                                onClick = {
                                    viewModel.onTtsVoiceChange("")
                                    voicePickerOpen = false
                                },
                                modifier = Modifier.fillMaxWidth(),
                                colors = ButtonDefaults.outlinedButtonColors(
                                    containerColor = if (autoSelected) JarvisPurple.copy(alpha = 0.22f) else Color.Transparent,
                                    contentColor   = if (autoSelected) JarvisPurple else Color.White,
                                ),
                                border = BorderStroke(
                                    width = if (autoSelected) 2.dp else 1.dp,
                                    color = if (autoSelected) JarvisPurple else Color.White.copy(alpha = 0.30f),
                                ),
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
                            ) {
                                Text("Automatisch (beste männliche Stimme)", fontSize = 12.sp, maxLines = 1)
                            }
                            if (availableVoices.isEmpty()) {
                                Text(
                                    text = "Keine deutschen Offline-Stimmen gefunden.\nInstalliere Google TTS → Einstellungen → Sprache → Text-in-Sprache → Google → Stimmen herunterladen",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.padding(top = 8.dp),
                                )
                            }
                            availableVoices.forEach { voice ->
                                val selected = settings.ttsVoiceName == voice.name
                                OutlinedButton(
                                    onClick = {
                                        viewModel.onTtsVoiceChange(voice.name)
                                        voicePickerOpen = false
                                    },
                                    modifier = Modifier.fillMaxWidth(),
                                    colors = ButtonDefaults.outlinedButtonColors(
                                        containerColor = if (selected) JarvisPurple.copy(alpha = 0.22f) else Color.Transparent,
                                        contentColor   = if (selected) JarvisPurple else Color.White,
                                    ),
                                    border = BorderStroke(
                                        width = if (selected) 2.dp else 1.dp,
                                        color = if (selected) JarvisPurple else Color.White.copy(alpha = 0.30f),
                                    ),
                                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
                                ) {
                                    Text(
                                        text = voice.name.replace(Regex("^de-DE-language#"), "")
                                                         .replace("-local", ""),
                                        fontSize = 12.sp,
                                        maxLines = 1,
                                    )
                                }
                            }
                        }
                    },
                    confirmButton = {
                        TextButton(onClick = { voicePickerOpen = false }) { Text("Schließen") }
                    },
                )
            }

            SettingRow(
                label = "Debug-Modus",
                description = "Nachrichten als Volltext, fett/weiß — zeigt alle LLM-Details",
            ) {
                Switch(
                    checked = settings.debugMode,
                    onCheckedChange = viewModel::onDebugModeChange,
                )
            }

            HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))

            // ── Speichern ─────────────────────────────────────────────────

            Button(
                onClick = viewModel::save,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (saved) JarvisGreen else MaterialTheme.colorScheme.primary,
                ),
            ) {
                Text(if (saved) "✓ Gespeichert" else stringResource(R.string.settings_save))
            }

            // ── Info & Version ────────────────────────────────────────────
            Spacer(modifier = Modifier.height(8.dp))

            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                ),
            ) {
                Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            "jarvis-ai.info",
                            fontWeight = FontWeight.Medium,
                            color = JarvisGreen,
                            modifier = Modifier.clickable {
                                context.startActivity(
                                    Intent(Intent.ACTION_VIEW, Uri.parse("https://jarvis-ai.info"))
                                )
                            },
                        )
                        Text(
                            "v${BuildConfig.VERSION_NAME} · Build ${BuildConfig.VERSION_CODE}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))
        }
    }
}
