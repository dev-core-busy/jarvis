package info.jarvisai.app.ui.chat

import androidx.activity.compose.BackHandler
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.painter.BitmapPainter
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import info.jarvisai.app.R
import info.jarvisai.app.data.model.AgentInfo
import info.jarvisai.app.data.prefs.BG_COLOR
import info.jarvisai.app.data.prefs.BG_DEFAULT_URI
import info.jarvisai.app.data.prefs.BG_GRADIENT
import info.jarvisai.app.data.prefs.BG_PHOTO
import info.jarvisai.app.data.prefs.SettingsDataStore
import info.jarvisai.app.data.model.ChatMessage
import info.jarvisai.app.data.model.ConnectionState
import info.jarvisai.app.data.model.MessageRole
import info.jarvisai.app.data.model.SegmentType
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import android.app.DownloadManager
import android.content.Intent
import info.jarvisai.app.update.DownloadPhase
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.platform.LocalDensity
import info.jarvisai.app.data.model.AvatarType
import info.jarvisai.app.ui.avatar.IronManAvatar
import info.jarvisai.app.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    onOpenSettings: () -> Unit,
    viewModel: ChatViewModel = hiltViewModel(),
) {
    val messages by viewModel.messages.collectAsState()
    val connectionState by viewModel.connectionState.collectAsState()
    val agents by viewModel.agents.collectAsState()
    val inputText by viewModel.inputText.collectAsState()
    val voiceState by viewModel.voiceState.collectAsState()
    val quickActions by viewModel.quickActions.collectAsState()
    val showAgentPanel by viewModel.showAgentPanel.collectAsState()
    val updateState by viewModel.updateState.collectAsState()
    val settings by viewModel.settings.collectAsState(initial = info.jarvisai.app.data.prefs.JarvisSettings())
    val selectionMode by viewModel.selectionMode.collectAsState()
    val selectedIds by viewModel.selectedIds.collectAsState()
    val isSpeaking by viewModel.isSpeaking.collectAsState()
    val isTtsEnabled by viewModel.ttsEnabled.collectAsState()
    val avatarMouth by viewModel.avatarMouthState.collectAsState()
    val avatarType by viewModel.avatarType.collectAsState()
    val listState = rememberLazyListState()
    val context = LocalContext.current
    val density = LocalDensity.current

    // IME-Höhe reaktiv → Avatar schiebt sich animiert nach oben wenn Tastatur einfährt
    val imeBottomDp = with(density) { WindowInsets.ime.getBottom(density).toDp() }
    val avatarBottomPadding by animateDpAsState(
        targetValue = 88.dp + imeBottomDp,
        animationSpec = tween(durationMillis = 280),
        label = "avatarIme",
    )

    // Hintergrundbild laden: eingebettetes Drawable oder lokales Foto
    val bgBitmap: ImageBitmap? = remember(settings.backgroundImageUri) {
        if (settings.backgroundType == BG_PHOTO && settings.backgroundImageUri.isNotBlank()) {
            runCatching {
                if (settings.backgroundImageUri == BG_DEFAULT_URI) {
                    // Eingebettetes Jarvis-Standardbild aus Drawable-Ressourcen
                    val resId = context.resources.getIdentifier("bg_jarvis", "drawable", context.packageName)
                    context.resources.openRawResource(resId).use {
                        android.graphics.BitmapFactory.decodeStream(it)?.asImageBitmap()
                    }
                } else {
                    val uri = android.net.Uri.parse(settings.backgroundImageUri)
                    context.contentResolver.openInputStream(uri)?.use {
                        android.graphics.BitmapFactory.decodeStream(it)?.asImageBitmap()
                    }
                }
            }.getOrNull()
        } else null
    }

    // Automatisch zum Ende scrollen: neue Nachricht UND wenn Tastatur einfährt
    LaunchedEffect(messages.size, imeBottomDp) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.size - 1)
        }
    }

    // Zurück-Taste beendet Auswahl-Modus statt App zu verlassen
    BackHandler(enabled = selectionMode) { viewModel.exitSelectionMode() }

    // Manuelles Layout ohne Scaffold – vermeidet Inset-Doppelverarbeitung
    Box(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding(),
    ) {
        // ── Hintergrund ───────────────────────────────────────────────
        when (settings.backgroundType) {
            BG_PHOTO -> if (bgBitmap != null) {
                Box(modifier = Modifier.fillMaxSize().background(Color(0xFF060A12)))
                androidx.compose.foundation.Image(
                    painter = BitmapPainter(bgBitmap),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                    alpha = settings.backgroundAlpha,
                )
            } else {
                Box(modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background))
            }
            BG_COLOR -> Box(
                modifier = Modifier.fillMaxSize().background(Color(settings.backgroundColorArgb))
            )
            else -> {
                // BG_GRADIENT — Jarvis HUD (animiertes Hexagon-Gitter + Scan-Linie)
                JarvisHudBackground()
            }
        }

        // ── Iron Man Avatar (zwischen Hintergrund und Chat-Inhalt) ───
        if (avatarType == AvatarType.IRONMAN) {
            IronManAvatar(
                isSpeaking = isSpeaking,
                mouthState = avatarMouth,
                modifier   = Modifier
                    .align(Alignment.BottomEnd)
                    .padding(bottom = avatarBottomPadding, end = 10.dp)
                    .size(width = 170.dp, height = 200.dp)
                    .alpha(if (isSpeaking) 0.97f else 0.90f),
            )
        }

        Column(modifier = Modifier.fillMaxSize().imePadding()) {
            // TopBar – normal oder Auswahl-Modus
            if (selectionMode) {
                SelectionTopBar(
                    selectedCount = selectedIds.size,
                    totalCount = messages.size,
                    onSelectAll = viewModel::selectAll,
                    onDelete = viewModel::deleteSelected,
                    onExit = viewModel::exitSelectionMode,
                )
            } else {
                JarvisTopBar(
                    connectionState = connectionState,
                    agentCount = agents.count { it.status == "running" },
                    onOpenSettings = onOpenSettings,
                    onToggleAgents = viewModel::toggleAgentPanel,
                    onReconnect = viewModel::reconnect,
                )
            }

            // Update-Banner: auto-Install wenn Download fertig
            LaunchedEffect(updateState.phase) {
                if (updateState.phase == DownloadPhase.READY) {
                    val dm = context.getSystemService(DownloadManager::class.java)
                    val uri = dm.getUriForDownloadedFile(updateState.downloadId)
                    if (uri != null) {
                        val intent = Intent(Intent.ACTION_VIEW).apply {
                            setDataAndType(uri, "application/vnd.android.package-archive")
                            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION
                        }
                        context.startActivity(intent)
                    }
                }
            }

            if (updateState.available || updateState.phase != DownloadPhase.IDLE) {
                Surface(
                    color = when (updateState.phase) {
                        DownloadPhase.ERROR -> MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.8f)
                        else -> JarvisGreen.copy(alpha = 0.12f)
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(
                                text = when (updateState.phase) {
                                    DownloadPhase.IDLE     -> "Update ${updateState.versionName} verfügbar"
                                    DownloadPhase.DOWNLOADING -> "Lade herunter… ${updateState.progress} %"
                                    DownloadPhase.READY    -> "Download abgeschlossen – Installation startet…"
                                    DownloadPhase.ERROR    -> "Download fehlgeschlagen"
                                },
                                style = MaterialTheme.typography.bodySmall,
                                color = if (updateState.phase == DownloadPhase.ERROR)
                                    MaterialTheme.colorScheme.error else JarvisGreen,
                            )
                            when (updateState.phase) {
                                DownloadPhase.IDLE -> TextButton(onClick = viewModel::downloadUpdate) {
                                    Text("Installieren", color = JarvisGreen, fontWeight = FontWeight.Bold)
                                }
                                DownloadPhase.ERROR -> TextButton(onClick = viewModel::dismissUpdate) {
                                    Text("Schließen", color = MaterialTheme.colorScheme.error)
                                }
                                else -> {}
                            }
                        }
                        if (updateState.phase == DownloadPhase.DOWNLOADING) {
                            Spacer(Modifier.height(4.dp))
                            LinearProgressIndicator(
                                progress = { updateState.progress / 100f },
                                modifier = Modifier.fillMaxWidth(),
                                color = JarvisGreen,
                                trackColor = JarvisGreen.copy(alpha = 0.2f),
                            )
                        }
                    }
                }
            }

            // Nachrichtenliste füllt verfügbaren Platz
            LazyColumn(
                state = listState,
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = PaddingValues(vertical = 12.dp),
            ) {
                items(messages, key = { it.id }) { msg ->
                    if (msg.role == MessageRole.DATE_SEPARATOR) {
                        DateSeparator(label = msg.text)
                    } else {
                        MessageBubble(
                            msg = msg,
                            debugMode = settings.debugMode,
                            selectionMode = selectionMode,
                            selected = msg.id in selectedIds,
                            onLongPress = { viewModel.enterSelectionMode(msg.id) },
                            onTap = { viewModel.toggleSelection(msg.id) },
                        )
                    }
                }
            }

            // Eingabeleiste mit Navigation-Bar-Inset
            val isAgentRunning by viewModel.isAgentRunning.collectAsState()
            ChatInputBar(
                text = inputText,
                voiceState = voiceState,
                isSpeaking = isSpeaking,
                isAgentRunning = isAgentRunning,
                isTtsEnabled = isTtsEnabled,
                onTextChange = viewModel::onInputChange,
                onSend = viewModel::sendMessage,
                onMicStart = viewModel::startListening,
                onMicStop = viewModel::stopListening,
                onTtsStop = viewModel::stopTts,
                onStopAgent = viewModel::stopAgent,
                onToggleTts = viewModel::toggleTts,
            )
        }

        // Agent-Panel (Overlay von rechts)
        AnimatedVisibility(
            visible = showAgentPanel,
            enter = slideInHorizontally(initialOffsetX = { it }),
            exit = slideOutHorizontally(targetOffsetX = { it }),
            modifier = Modifier.align(Alignment.TopEnd),
        ) {
            AgentPanel(
                agents = agents,
                modifier = Modifier
                    .width(220.dp)
                    .fillMaxHeight(),
            )
        }
    }
}

// ─── TopBar (Auswahl-Modus) ───────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SelectionTopBar(
    selectedCount: Int,
    totalCount: Int,
    onSelectAll: () -> Unit,
    onDelete: () -> Unit,
    onExit: () -> Unit,
) {
    TopAppBar(
        navigationIcon = {
            IconButton(onClick = onExit) {
                Icon(Icons.Filled.Close, contentDescription = "Auswahl beenden")
            }
        },
        title = {
            Text(
                text = if (selectedCount == 0) "Auswählen" else "$selectedCount ausgewählt",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
        },
        actions = {
            TextButton(onClick = onSelectAll) {
                Text(
                    text = if (selectedCount == totalCount) "Keine" else "Alle",
                    color = JarvisPurple,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            IconButton(onClick = onDelete, enabled = selectedCount > 0) {
                Icon(
                    Icons.Filled.Delete,
                    contentDescription = "Löschen",
                    tint = if (selectedCount > 0) JarvisError
                           else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f),
                )
            }
        },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    )
}

// ─── TopBar ───────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun JarvisTopBar(
    connectionState: ConnectionState,
    agentCount: Int,
    onOpenSettings: () -> Unit,
    onToggleAgents: () -> Unit,
    onReconnect: () -> Unit,
) {
    TopAppBar(
        title = {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                // Verbindungs-Dot
                Box(
                    modifier = Modifier
                        .size(10.dp)
                        .clip(CircleShape)
                        .background(
                            when (connectionState) {
                                ConnectionState.CONNECTED -> JarvisGreen
                                ConnectionState.CONNECTING -> Color.Yellow
                                else -> JarvisError
                            }
                        )
                )
                Text(
                    "Jarvis",
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    when (connectionState) {
                        ConnectionState.CONNECTED -> "verbunden"
                        ConnectionState.CONNECTING -> "verbinde…"
                        ConnectionState.ERROR -> "Fehler"
                        ConnectionState.DISCONNECTED -> "getrennt"
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        actions = {
            // Agents-Button mit Badge
            BadgedBox(
                badge = {
                    if (agentCount > 0) Badge { Text("$agentCount") }
                }
            ) {
                IconButton(onClick = onToggleAgents) {
                    Icon(Icons.Filled.AccountTree, contentDescription = "Agents")
                }
            }
            // Reconnect bei Fehler
            if (connectionState == ConnectionState.ERROR || connectionState == ConnectionState.DISCONNECTED) {
                IconButton(onClick = onReconnect) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Reconnect")
                }
            }
            // Settings
            IconButton(onClick = onOpenSettings) {
                Icon(Icons.Filled.Settings, contentDescription = "Einstellungen")
            }
        },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    )
}

// ─── Datums-Separator ────────────────────────────────────────────────

@Composable
fun DateSeparator(label: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        HorizontalDivider(modifier = Modifier.weight(1f), color = Color.White.copy(alpha = 0.12f))
        Text(
            text = label,
            color = Color.White.copy(alpha = 0.45f),
            fontSize = 11.sp,
            modifier = Modifier.padding(horizontal = 10.dp),
        )
        HorizontalDivider(modifier = Modifier.weight(1f), color = Color.White.copy(alpha = 0.12f))
    }
}

// ─── Nachrichten-Bubble ───────────────────────────────────────────────

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun MessageBubble(
    msg: ChatMessage,
    debugMode: Boolean = false,
    selectionMode: Boolean = false,
    selected: Boolean = false,
    onLongPress: () -> Unit = {},
    onTap: () -> Unit = {},
) {
    val isUser = msg.role == MessageRole.USER

    // Auswahl-Hintergrund wenn markiert
    val rowBg = if (selected) JarvisPurple.copy(alpha = 0.15f) else Color.Transparent

    if (debugMode) {
        // Debug: alles sichtbar, STATUS grau, ANSWER weiß-fett, monospace
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(rowBg)
                .combinedClickable(onClick = { if (selectionMode) onTap() }, onLongClick = onLongPress)
                .padding(vertical = 2.dp, horizontal = 4.dp),
            verticalAlignment = Alignment.Top,
        ) {
            if (selectionMode) {
                Checkbox(
                    checked = selected,
                    onCheckedChange = { onTap() },
                    colors = CheckboxDefaults.colors(checkedColor = JarvisPurple, checkmarkColor = Color.White),
                )
            }
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = if (isUser) "▶ Du:" else "◀ Jarvis:",
                    color = if (isUser) JarvisGreen else JarvisPurple,
                    fontWeight = FontWeight.Bold,
                    fontSize = 11.sp,
                )
                if (isUser || msg.segments.isEmpty()) {
                    Text(
                        text = msg.text,
                        color = Color.White,
                        fontWeight = FontWeight.Bold,
                        fontSize = 13.sp,
                        fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                    )
                } else {
                    msg.segments.forEach { seg ->
                        Text(
                            text = seg.text,
                            color = if (seg.type == SegmentType.ANSWER) Color.White
                                    else Color.White.copy(alpha = 0.40f),
                            fontWeight = if (seg.type == SegmentType.ANSWER) FontWeight.Bold
                                         else FontWeight.Normal,
                            fontSize = 13.sp,
                            fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                            lineHeight = if (seg.type == SegmentType.ANSWER) 20.sp else 17.sp,
                        )
                    }
                }
                if (msg.isStreaming) StreamingDots()
            }
        }
        return
    }

    // ── Normal-Modus ─────────────────────────────────────────────────
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(rowBg)
            .combinedClickable(onClick = { if (selectionMode) onTap() }, onLongClick = onLongPress),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Checkbox links (auch bei User-Nachrichten)
        if (selectionMode) {
            Checkbox(
                checked = selected,
                onCheckedChange = { onTap() },
                colors = CheckboxDefaults.colors(checkedColor = JarvisPurple, checkmarkColor = Color.White),
            )
        }
        if (!isUser) {
            Box(
                modifier = Modifier
                    .size(32.dp)
                    .clip(CircleShape)
                    .background(Brush.linearGradient(listOf(JarvisPurple, Color(0xFF6A0DAD)))),
                contentAlignment = Alignment.Center,
            ) {
                Text("J", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
            }
            Spacer(modifier = Modifier.width(8.dp))
        }

        Column(horizontalAlignment = if (isUser) Alignment.End else Alignment.Start) {
            val timeStr = remember(msg.timestamp) {
                SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(msg.timestamp))
            }
            Text(
                text = timeStr,
                color = Color.White.copy(alpha = 0.35f),
                fontSize = 10.sp,
                modifier = Modifier.padding(start = 4.dp, end = 4.dp, bottom = 2.dp),
            )
            Surface(
                shape = RoundedCornerShape(
                    topStart = if (isUser) 18.dp else 4.dp,
                    topEnd = if (isUser) 4.dp else 18.dp,
                    bottomStart = 18.dp,
                    bottomEnd = 18.dp,
                ),
                color = if (isUser) JarvisPurple.copy(alpha = 0.45f)
                        else Color.White.copy(alpha = 0.07f),
                tonalElevation = 0.dp,
                modifier = Modifier.widthIn(max = 300.dp),
            ) {
                Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                    if (isUser || msg.segments.isEmpty()) {
                        // User-Nachricht oder Legacy ohne Segmente
                        Text(
                            text = msg.text,
                            color = Color.White,
                            fontWeight = FontWeight.SemiBold,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    } else {
                        // Jarvis-Nachricht: nur ANSWER-Segmente anzeigen, STATUS unsichtbar
                        val answerText = msg.segments
                            .filter { it.type == SegmentType.ANSWER }
                            .joinToString("\n") { it.text }
                        val statsText = msg.segments
                            .filter { it.type == SegmentType.STATS }
                            .joinToString(" ") { it.text }
                        if (answerText.isNotBlank()) {
                            // Antwort vorhanden → anzeigen, KEINE Punkte
                            Text(
                                text = answerText,
                                color = Color.White,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 15.sp,
                                lineHeight = 22.sp,
                            )
                        } else if (msg.isStreaming) {
                            // Noch keine Antwort → Punkte als Platzhalter
                            Spacer(modifier = Modifier.height(4.dp))
                            StreamingDots()
                        }
                        // Stats immer anzeigen (auch im Standard-Modus)
                        if (statsText.isNotBlank()) {
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = statsText,
                                color = Color.White.copy(alpha = 0.4f),
                                fontSize = 11.sp,
                                fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                            )
                        }
                    }
                }
            }
        }

        if (isUser) Spacer(modifier = Modifier.width(8.dp))
    }
}

@Composable
private fun StreamingDots() {
    val infiniteTransition = rememberInfiniteTransition(label = "dots")
    val alpha by infiniteTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(600),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "alpha",
    )
    Text("●●●", color = JarvisMuted.copy(alpha = alpha), fontSize = 10.sp)
}

// ─── Quick-Actions ────────────────────────────────────────────────────

@Composable
private fun QuickActionRow(actions: List<String>, onAction: (String) -> Unit) {
    LazyRow(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(actions) { action ->
            SuggestionChip(
                onClick = { onAction(action) },
                label = { Text(action, style = MaterialTheme.typography.labelSmall) },
                colors = SuggestionChipDefaults.suggestionChipColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            )
        }
    }
}

// ─── Eingabe-Leiste ───────────────────────────────────────────────────

@Composable
private fun ChatInputBar(
    text: String,
    voiceState: VoiceState,
    isSpeaking: Boolean = false,
    isAgentRunning: Boolean = false,
    isTtsEnabled: Boolean = true,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    onMicStart: () -> Unit,
    onMicStop: () -> Unit,
    onTtsStop: () -> Unit = {},
    onStopAgent: () -> Unit = {},
    onToggleTts: () -> Unit = {},
) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = 4.dp,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            // TTS-Toggle-Button (🔊/🔇)
            IconButton(onClick = onToggleTts) {
                Icon(
                    imageVector = if (isTtsEnabled) Icons.AutoMirrored.Filled.VolumeUp
                                  else Icons.AutoMirrored.Filled.VolumeOff,
                    contentDescription = if (isTtsEnabled) "Sprachausgabe deaktivieren"
                                         else "Sprachausgabe aktivieren",
                    tint = if (isTtsEnabled) MaterialTheme.colorScheme.primary
                           else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            // Mic-Button
            val micColor = when (voiceState) {
                VoiceState.LISTENING -> JarvisGreen
                VoiceState.ERROR -> JarvisError
                VoiceState.IDLE -> MaterialTheme.colorScheme.onSurfaceVariant
            }
            IconButton(
                onClick = {
                    if (voiceState == VoiceState.LISTENING) onMicStop() else onMicStart()
                },
            ) {
                Icon(
                    imageVector = if (voiceState == VoiceState.LISTENING)
                        Icons.Filled.MicOff else Icons.Filled.Mic,
                    contentDescription = stringResource(R.string.chat_mic),
                    tint = micColor,
                )
            }

            // Abbrechen-Button – nur sichtbar wenn Agent läuft
            if (isAgentRunning) {
                IconButton(onClick = onStopAgent) {
                    Icon(
                        imageVector = Icons.Filled.Cancel,
                        contentDescription = "Anfrage abbrechen",
                        tint = MaterialTheme.colorScheme.error,
                    )
                }
            }

            // TTS-Stop-Button (⏹) – nur sichtbar wenn Jarvis gerade spricht
            if (isSpeaking) {
                IconButton(onClick = onTtsStop) {
                    Icon(
                        imageVector = Icons.Filled.StopCircle,
                        contentDescription = "Vorlesen stoppen",
                        tint = MaterialTheme.colorScheme.error,
                    )
                }
            }

            // Texteingabe
            OutlinedTextField(
                value = text,
                onValueChange = onTextChange,
                placeholder = { Text(stringResource(R.string.chat_hint)) },
                modifier = Modifier.weight(1f),
                maxLines = 4,
                shape = RoundedCornerShape(24.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = MaterialTheme.colorScheme.primary,
                    unfocusedBorderColor = MaterialTheme.colorScheme.outline,
                ),
            )

            // Senden-Button
            FilledIconButton(
                onClick = onSend,
                enabled = text.isNotBlank(),
                colors = IconButtonDefaults.filledIconButtonColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                ),
            ) {
                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = stringResource(R.string.chat_send))
            }
        }
    }
}

// ─── Agent-Panel ──────────────────────────────────────────────────────

@Composable
fun AgentPanel(agents: List<AgentInfo>, modifier: Modifier = Modifier) {
    Surface(
        modifier = modifier,
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.95f),
        tonalElevation = 8.dp,
        shape = RoundedCornerShape(topStart = 16.dp, bottomStart = 16.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                "Agents",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(bottom = 4.dp),
            )
            if (agents.isEmpty()) {
                Text("Keine aktiven Agents", style = MaterialTheme.typography.bodySmall)
            } else {
                agents.forEach { agent -> AgentCard(agent) }
            }
        }
    }
}

@Composable
private fun AgentCard(agent: AgentInfo) {
    val isMain = !agent.is_sub_agent
    val statusColor = when (agent.status) {
        "running" -> if (isMain) JarvisGreen else JarvisPurple
        "finished" -> JarvisMuted
        else -> JarvisMuted
    }
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(statusColor)
            )
            Column {
                Text(
                    agent.label.ifBlank { if (isMain) "Hauptagent" else "Sub-Agent" },
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    agent.status,
                    style = MaterialTheme.typography.labelSmall,
                    color = statusColor,
                )
            }
        }
    }
}
