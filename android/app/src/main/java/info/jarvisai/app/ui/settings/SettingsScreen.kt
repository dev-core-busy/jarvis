package info.jarvisai.app.ui.settings

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.filled.VolumeUp
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
import info.jarvisai.app.service.TtsVoice
import info.jarvisai.app.data.model.AvatarType
import info.jarvisai.app.data.prefs.BG_COLOR
import info.jarvisai.app.data.prefs.BG_DEFAULT_URI
import info.jarvisai.app.data.prefs.BG_GRADIENT
import info.jarvisai.app.data.prefs.BG_PHOTO
import info.jarvisai.app.ui.theme.JarvisGreen
import info.jarvisai.app.ui.theme.JarvisPurple

// ─── Stimmen-Auswahl-Dialoge ──────────────────────────────────────────────────

@Composable
private fun ServerVoicePickerDialog(
    currentVoice: String,
    voices: List<TtsVoice>,
    loadingVoices: Boolean,
    onSelect: (String) -> Unit,
    onPreview: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Server-Stimme (edge-tts)") },
        text = {
            when {
                loadingVoices -> Box(
                    modifier = Modifier.fillMaxWidth().height(180.dp),
                    contentAlignment = Alignment.Center,
                ) { CircularProgressIndicator() }
                voices.isEmpty() -> Text(
                    "Keine Stimmen verfügbar.\nServer-URL und API-Key prüfen.",
                    style = MaterialTheme.typography.bodyMedium,
                )
                else -> LazyColumn(modifier = Modifier.height(360.dp)) {
                    items(voices) { voice ->
                        val isSelected = voice.id == currentVoice
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(6.dp))
                                .background(if (isSelected) JarvisPurple.copy(alpha = 0.25f) else Color.Transparent)
                                .clickable { onSelect(voice.id) }
                                .padding(horizontal = 8.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = when (voice.gender.lowercase()) {
                                    "male"   -> "♂"
                                    "female" -> "♀"
                                    else     -> "  "
                                },
                                color = if (voice.gender.lowercase() == "female")
                                    Color(0xFFFF69B4) else Color(0xFF64B5F6),
                                fontSize = 14.sp,
                                modifier = Modifier.width(20.dp),
                            )
                            Text(
                                text = voice.id,
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                                color = if (isSelected) JarvisPurple else Color.Unspecified,
                                modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                                maxLines = 1,
                                overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                            )
                            IconButton(
                                onClick = { onPreview(voice.id) },
                                modifier = Modifier.size(32.dp),
                            ) {
                                Icon(
                                    imageVector = Icons.Filled.VolumeUp,
                                    contentDescription = "Vorschau",
                                    modifier = Modifier.size(18.dp),
                                )
                            }
                        }
                        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f))
                    }
                }
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Schließen") }
        },
    )
}

@Composable
private fun AndroidVoicePickerDialog(
    currentVoice: String,
    voices: List<Pair<String, String>>,
    onSelect: (String) -> Unit,
    onPreview: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Android-Stimme") },
        text = {
            LazyColumn(modifier = Modifier.height(360.dp)) {
                item {
                    val isAuto = currentVoice.isBlank()
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(6.dp))
                            .background(if (isAuto) JarvisPurple.copy(alpha = 0.25f) else Color.Transparent)
                            .clickable { onSelect("") }
                            .padding(horizontal = 8.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("♂", color = Color(0xFF64B5F6), fontSize = 14.sp,
                            modifier = Modifier.width(20.dp))
                        Text(
                            text = "Automatisch (beste männliche Stimme)",
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = if (isAuto) FontWeight.Bold else FontWeight.Normal,
                            color = if (isAuto) JarvisPurple else Color.Unspecified,
                            modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                        )
                        IconButton(
                            onClick = { onPreview("") },
                            modifier = Modifier.size(32.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Filled.VolumeUp,
                                contentDescription = "Vorschau",
                                modifier = Modifier.size(18.dp),
                            )
                        }
                    }
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f))
                }
                items(voices) { (id, display) ->
                    val isSelected = id == currentVoice
                    val genderIcon = when {
                        display.startsWith("♀") -> "♀"
                        display.startsWith("♂") -> "♂"
                        else -> "  "
                    }
                    val voiceName = display.removePrefix("♀ ").removePrefix("♂ ")
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(6.dp))
                            .background(if (isSelected) JarvisPurple.copy(alpha = 0.25f) else Color.Transparent)
                            .clickable { onSelect(id) }
                            .padding(horizontal = 8.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = genderIcon,
                            color = if (genderIcon == "♀") Color(0xFFFF69B4) else Color(0xFF64B5F6),
                            fontSize = 14.sp,
                            modifier = Modifier.width(20.dp),
                        )
                        Text(
                            text = voiceName,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                            color = if (isSelected) JarvisPurple else Color.Unspecified,
                            modifier = Modifier.weight(1f).padding(horizontal = 8.dp),
                            maxLines = 1,
                            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        )
                        IconButton(
                            onClick = { onPreview(id) },
                            modifier = Modifier.size(32.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Filled.VolumeUp,
                                contentDescription = "Vorschau",
                                modifier = Modifier.size(18.dp),
                            )
                        }
                    }
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f))
                }
            }
        },
        confirmButton = {},
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Schließen") }
        },
    )
}

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
    val serverVoices by viewModel.serverVoices.collectAsState()
    val androidVoices by viewModel.androidVoices.collectAsState()
    val loadingVoices by viewModel.loadingVoices.collectAsState()
    val loginState by viewModel.loginState.collectAsState()
    var apiKeyVisible by remember { mutableStateOf(false) }
    var domainPasswordVisible by remember { mutableStateOf(false) }
    var showServerVoicePicker by remember { mutableStateOf(false) }
    var showAndroidVoicePicker by remember { mutableStateOf(false) }
    var domainPassword by remember { mutableStateOf("") }


    LaunchedEffect(showServerVoicePicker) {
        if (showServerVoicePicker) viewModel.fetchServerVoices()
    }
    LaunchedEffect(showAndroidVoicePicker) {
        if (showAndroidVoicePicker) viewModel.loadAndroidVoices()
    }

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
        if (showServerVoicePicker) {
            ServerVoicePickerDialog(
                currentVoice  = settings.serverTtsVoice,
                voices        = serverVoices,
                loadingVoices = loadingVoices,
                onSelect      = { voice -> viewModel.onServerTtsVoiceChange(voice); showServerVoicePicker = false },
                onPreview     = viewModel::previewServerVoice,
                onDismiss     = { showServerVoicePicker = false },
            )
        }
        if (showAndroidVoicePicker) {
            AndroidVoicePickerDialog(
                currentVoice = settings.androidTtsVoice,
                voices       = androidVoices,
                onSelect     = { voice -> viewModel.onAndroidTtsVoiceChange(voice); showAndroidVoicePicker = false },
                onPreview    = viewModel::previewAndroidVoice,
                onDismiss    = { showAndroidVoicePicker = false },
            )
        }
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

            // ── Domain-Anmeldung (optional) ───────────────────────────
            SectionHeader("Domain-Anmeldung (optional)")

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value = settings.domainUsername,
                    onValueChange = viewModel::onDomainUsernameChange,
                    label = { Text("Benutzername") },
                    placeholder = { Text("user@domain.com oder DOMAIN\\user") },
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
                OutlinedTextField(
                    value = domainPassword,
                    onValueChange = { domainPassword = it },
                    label = { Text("Passwort") },
                    visualTransformation = if (domainPasswordVisible) VisualTransformation.None
                                           else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    trailingIcon = {
                        IconButton(onClick = { domainPasswordVisible = !domainPasswordVisible }) {
                            Icon(
                                imageVector = if (domainPasswordVisible) Icons.Filled.VisibilityOff
                                              else Icons.Filled.Visibility,
                                contentDescription = if (domainPasswordVisible) "Verbergen" else "Anzeigen",
                            )
                        }
                    },
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
            }

            Text(
                "Format: DOMAIN\\Benutzername  oder  benutzername@domain.com",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.5f),
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Button(
                    onClick = {
                        viewModel.loginWithCredentials(settings.serverUrl, settings.domainUsername, domainPassword)
                    },
                    enabled = loginState != "loading",
                ) {
                    if (loginState == "loading") {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    } else {
                        Text("Anmelden")
                    }
                }
                when {
                    loginState == "ok" -> Text(
                        "✓ Angemeldet!",
                        color = JarvisGreen,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    loginState.startsWith("error:") -> Text(
                        loginState.removePrefix("error:").trim(),
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                    )
                    settings.domainUsername.isNotBlank() && settings.apiKey.isNotBlank() -> Text(
                        "✓ Aktive Domain-Sitzung",
                        color = JarvisGreen,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            Text(
                "── oder API-Key direkt eingeben ──",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
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
                                BG_DEFAULT_URI -> "Jarvis Standard-Bild"
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

            SettingRow(
                label = "Avatar verwenden",
                description = "Iron Man Helm mit Sprachausgabe im Chat-Hintergrund",
            ) {
                Switch(
                    checked = settings.avatarType == AvatarType.IRONMAN,
                    onCheckedChange = { viewModel.onAvatarEnabledChange(it) },
                )
            }

            SettingRow(
                label = "Server-Stimme (edge-tts)",
                description = "Sprachausgabe via Jarvis-Server (höhere Qualität)",
            ) {
                Switch(
                    checked = settings.serverTtsEnabled,
                    onCheckedChange = viewModel::onServerTtsEnabledChange,
                )
            }

            if (settings.serverTtsEnabled) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f).padding(end = 12.dp)) {
                        Text("Server-Stimme", style = MaterialTheme.typography.bodyMedium)
                        Text(
                            settings.serverTtsVoice.ifBlank { "de-DE-ConradNeural" },
                            style = MaterialTheme.typography.bodySmall,
                            color = JarvisGreen,
                        )
                    }
                    OutlinedButton(onClick = { showServerVoicePicker = true }) {
                        Text("Wählen")
                    }
                }
            } else {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f).padding(end = 12.dp)) {
                        Text("Android-Stimme", style = MaterialTheme.typography.bodyMedium)
                        Text(
                            if (settings.androidTtsVoice.isBlank())
                                "Automatisch (beste männliche Stimme)"
                            else settings.androidTtsVoice,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    OutlinedButton(onClick = { showAndroidVoicePicker = true }) {
                        Text("Wählen")
                    }
                }
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

            val canSave = settings.serverUrl.isNotBlank() &&
                (settings.apiKey.isNotBlank() || loginState == "ok")
            Button(
                onClick = viewModel::save,
                enabled = canSave,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (saved) JarvisGreen else MaterialTheme.colorScheme.primary,
                ),
            ) {
                Text(if (saved) "✓ Gespeichert" else stringResource(R.string.settings_save))
            }
            if (!canSave) {
                Text(
                    "Bitte API-Key eingeben oder via Domain-Anmeldung anmelden",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.padding(top = 4.dp),
                )
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
