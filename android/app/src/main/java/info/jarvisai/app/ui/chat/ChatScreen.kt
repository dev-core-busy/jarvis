package info.jarvisai.app.ui.chat

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import info.jarvisai.app.R
import info.jarvisai.app.data.model.AgentInfo
import info.jarvisai.app.data.model.ChatMessage
import info.jarvisai.app.data.model.ConnectionState
import info.jarvisai.app.data.model.MessageRole
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
    val listState = rememberLazyListState()

    // Automatisch zum Ende scrollen wenn neue Nachricht
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.size - 1)
        }
    }

    // Manuelles Layout ohne Scaffold – vermeidet Inset-Doppelverarbeitung
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .statusBarsPadding(),
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            // TopBar
            JarvisTopBar(
                connectionState = connectionState,
                agentCount = agents.count { it.status == "running" },
                onOpenSettings = onOpenSettings,
                onToggleAgents = viewModel::toggleAgentPanel,
                onReconnect = viewModel::reconnect,
            )

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
                    MessageBubble(msg)
                }
            }

            // Quick-Actions direkt über der Eingabeleiste
            QuickActionRow(quickActions) { viewModel.sendQuickAction(it) }

            // Eingabeleiste mit Navigation-Bar-Inset
            ChatInputBar(
                text = inputText,
                voiceState = voiceState,
                onTextChange = viewModel::onInputChange,
                onSend = viewModel::sendMessage,
                onMicStart = viewModel::startListening,
                onMicStop = viewModel::stopListening,
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

// ─── Nachrichten-Bubble ───────────────────────────────────────────────

@Composable
fun MessageBubble(msg: ChatMessage) {
    val isUser = msg.role == MessageRole.USER
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        if (!isUser) {
            // Jarvis-Avatar
            Box(
                modifier = Modifier
                    .size(32.dp)
                    .clip(CircleShape)
                    .background(
                        Brush.linearGradient(listOf(JarvisPurple, Color(0xFF6A0DAD)))
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Text("J", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
            }
            Spacer(modifier = Modifier.width(8.dp))
        }

        Column(horizontalAlignment = if (isUser) Alignment.End else Alignment.Start) {
            Surface(
                shape = RoundedCornerShape(
                    topStart = if (isUser) 18.dp else 4.dp,
                    topEnd = if (isUser) 4.dp else 18.dp,
                    bottomStart = 18.dp,
                    bottomEnd = 18.dp,
                ),
                color = if (isUser) JarvisPurple.copy(alpha = 0.85f)
                        else MaterialTheme.colorScheme.surfaceVariant,
                tonalElevation = 2.dp,
                modifier = Modifier.widthIn(max = 300.dp),
            ) {
                Column(modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                    Text(
                        text = msg.text,
                        color = if (isUser) Color.White else MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    if (msg.isStreaming) {
                        Spacer(modifier = Modifier.height(4.dp))
                        StreamingDots()
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
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
    onMicStart: () -> Unit,
    onMicStop: () -> Unit,
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
