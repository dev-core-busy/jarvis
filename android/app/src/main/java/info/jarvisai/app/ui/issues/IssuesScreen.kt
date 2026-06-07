package info.jarvisai.app.ui.issues

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import info.jarvisai.app.ui.theme.JarvisGreen
import info.jarvisai.app.ui.theme.JarvisPurple
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Status-Farbe analog Windows/Web. */
private fun statusColor(status: String): Color = when (status) {
    "open" -> Color(0xFFEF4444)        // rot
    "in_progress" -> Color(0xFFF59E0B) // gelb
    "closed" -> Color(0xFF10B981)      // gruen
    else -> Color.Gray
}

private fun typeLabel(t: String): String = when (t) {
    "bug" -> "Bug"
    "feature" -> "Feature"
    "improvement" -> "Verbesserung"
    else -> t
}

private fun statusLabel(s: String): String = when (s) {
    "open" -> "Offen"
    "in_progress" -> "In Arbeit"
    "closed" -> "Geschlossen"
    else -> s
}

private fun priorityLabel(p: String): String = when (p) {
    "low" -> "Niedrig"
    "medium" -> "Mittel"
    "high" -> "Hoch"
    else -> p
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IssuesScreen(
    onBack: () -> Unit,
    vm: IssuesViewModel = hiltViewModel(),
) {
    val issues by vm.issues.collectAsState()
    val loading by vm.loading.collectAsState()
    val error by vm.error.collectAsState()
    val filter by vm.filter.collectAsState()
    val selected by vm.selected.collectAsState()
    var showCreate by remember { mutableStateOf(false) }

    // Detail-Ansicht hat Vorrang
    if (selected != null) {
        IssueDetailScreen(
            vm = vm,
            issue = selected!!,
            onBack = { vm.select(null) },
        )
        return
    }

    if (showCreate) {
        IssueFormScreen(
            initial = null,
            onCancel = { showCreate = false },
            onSubmit = { title, body, type, priority ->
                vm.create(title, body, type, priority) {
                    showCreate = false
                    if (it != null) vm.select(it)
                }
            },
        )
        return
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Issues / Feedback") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Zurueck")
                    }
                },
                actions = {
                    IconButton(onClick = { vm.refresh() }) {
                        Icon(Icons.Filled.Refresh, contentDescription = "Aktualisieren")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = { showCreate = true },
                containerColor = JarvisPurple,
                contentColor = Color.White,
            ) { Icon(Icons.Filled.Add, contentDescription = "Neues Issue") }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize(),
        ) {
            // Filter-Leiste
            FilterBar(filter, vm::setFilter)

            if (error != null) {
                Surface(
                    color = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.4f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier.padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(error ?: "", color = MaterialTheme.colorScheme.error, fontSize = 13.sp)
                        TextButton(onClick = vm::clearError) { Text("OK") }
                    }
                }
            }

            if (loading && issues.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = JarvisPurple)
                }
            } else if (issues.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(
                        "Keine Issues vorhanden.\nTippe auf '+' um eines zu erstellen.",
                        textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                        color = Color.White.copy(alpha = 0.6f),
                    )
                }
            } else {
                LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(issues, key = { it.id }) { issue ->
                        IssueRow(issue, onClick = { vm.select(issue) })
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FilterBar(filter: IssueFilter, onChange: (IssueFilter) -> Unit) {
    var statusMenu by remember { mutableStateOf(false) }
    var typeMenu by remember { mutableStateOf(false) }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Status-Filter
        Box {
            AssistChip(
                onClick = { statusMenu = true },
                label = { Text(filter.status?.let(::statusLabel) ?: "Status: alle") },
            )
            DropdownMenu(expanded = statusMenu, onDismissRequest = { statusMenu = false }) {
                DropdownMenuItem(text = { Text("Alle") }, onClick = {
                    onChange(filter.copy(status = null)); statusMenu = false
                })
                listOf("open", "in_progress", "closed").forEach { s ->
                    DropdownMenuItem(text = { Text(statusLabel(s)) }, onClick = {
                        onChange(filter.copy(status = s)); statusMenu = false
                    })
                }
            }
        }
        // Type-Filter
        Box {
            AssistChip(
                onClick = { typeMenu = true },
                label = { Text(filter.type?.let(::typeLabel) ?: "Typ: alle") },
            )
            DropdownMenu(expanded = typeMenu, onDismissRequest = { typeMenu = false }) {
                DropdownMenuItem(text = { Text("Alle") }, onClick = {
                    onChange(filter.copy(type = null)); typeMenu = false
                })
                listOf("bug", "feature", "improvement").forEach { t ->
                    DropdownMenuItem(text = { Text(typeLabel(t)) }, onClick = {
                        onChange(filter.copy(type = t)); typeMenu = false
                    })
                }
            }
        }
        FilterChip(
            selected = filter.mineOnly,
            onClick = { onChange(filter.copy(mineOnly = !filter.mineOnly)) },
            label = { Text("Nur meine") },
        )
    }
}

@Composable
private fun IssueRow(issue: IssueItem, onClick: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(10.dp),
        color = Color.White.copy(alpha = 0.06f),
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
    ) {
        Row(modifier = Modifier.padding(12.dp), verticalAlignment = Alignment.Top) {
            Box(
                modifier = Modifier
                    .size(10.dp)
                    .clip(RoundedCornerShape(5.dp))
                    .background(statusColor(issue.status))
            )
            Spacer(Modifier.width(10.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    issue.title,
                    color = Color.White,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 15.sp,
                    maxLines = 2,
                )
                Spacer(Modifier.height(4.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SmallChip(typeLabel(issue.type))
                    SmallChip(statusLabel(issue.status))
                    SmallChip("@${issue.author}")
                }
            }
        }
    }
}

@Composable
private fun SmallChip(text: String) {
    Surface(
        shape = RoundedCornerShape(4.dp),
        color = Color.White.copy(alpha = 0.08f),
    ) {
        Text(
            text = text,
            color = Color.White.copy(alpha = 0.7f),
            fontSize = 11.sp,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Detail-Screen
// ───────────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IssueDetailScreen(
    vm: IssuesViewModel,
    issue: IssueItem,
    onBack: () -> Unit,
) {
    var editMode by remember(issue.id) { mutableStateOf(false) }
    var jarvisMode by remember(issue.id) { mutableStateOf(false) }
    var deleteConfirm by remember(issue.id) { mutableStateOf(false) }
    val currentUser by vm.currentUser.collectAsState()
    val isJarvis = currentUser.lowercase() == "jarvis"

    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    // File-Picker fuer Attachments
    val pickFile = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        val cr = context.contentResolver
        val mime = cr.getType(uri) ?: "application/octet-stream"
        val name = uri.lastPathSegment?.substringAfterLast('/') ?: "attachment"
        val bytes = cr.openInputStream(uri)?.use { it.readBytes() } ?: return@rememberLauncherForActivityResult
        vm.uploadAttachment(issue.id, name, mime, bytes)
    }

    if (editMode) {
        IssueFormScreen(
            initial = issue,
            onCancel = { editMode = false },
            onSubmit = { title, body, type, priority ->
                val patch = JSONObject().apply {
                    put("title", title)
                    put("body", body)
                    put("type", type)
                    put("priority", priority)
                }
                vm.update(issue.id, patch) { editMode = false }
            },
        )
        return
    }

    if (jarvisMode) {
        JarvisFormScreen(
            issue = issue,
            onCancel = { jarvisMode = false },
            onSubmit = { status, comment ->
                val patch = JSONObject().apply {
                    put("status", status)
                    put("jarvis_comment", comment)
                }
                vm.update(issue.id, patch) { jarvisMode = false }
            },
        )
        return
    }

    if (deleteConfirm) {
        AlertDialog(
            onDismissRequest = { deleteConfirm = false },
            title = { Text("Issue loeschen?") },
            text = { Text("Diese Aktion kann nicht rueckgaengig gemacht werden.") },
            confirmButton = {
                TextButton(onClick = {
                    deleteConfirm = false
                    vm.delete(issue.id) { onBack() }
                }) { Text("Loeschen", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { deleteConfirm = false }) { Text("Abbrechen") }
            },
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Issue-Details", maxLines = 1) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Zurueck")
                    }
                },
                actions = {
                    if (isJarvis) {
                        TextButton(onClick = { jarvisMode = true }) { Text("Jarvis") }
                    }
                    if (issue.canEdit) {
                        IconButton(onClick = { editMode = true }) {
                            Icon(Icons.Filled.Edit, contentDescription = "Bearbeiten")
                        }
                    }
                    if (issue.canDelete) {
                        IconButton(onClick = { deleteConfirm = true }) {
                            Icon(Icons.Filled.Delete, contentDescription = "Loeschen",
                                tint = MaterialTheme.colorScheme.error)
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(issue.title, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                SmallChip(typeLabel(issue.type))
                SmallChip(statusLabel(issue.status))
                SmallChip("Prio: ${priorityLabel(issue.priority)}")
                SmallChip("@${issue.author}")
            }
            Text("Erstellt: ${issue.created}", color = Color.White.copy(alpha = 0.5f), fontSize = 11.sp)
            if (issue.updated != issue.created) {
                Text("Aktualisiert: ${issue.updated}", color = Color.White.copy(alpha = 0.5f), fontSize = 11.sp)
            }

            HorizontalDivider(color = Color.White.copy(alpha = 0.12f))

            if (issue.body.isNotBlank()) {
                Text(issue.body, color = Color.White, fontSize = 14.sp)
            } else {
                Text("(keine Beschreibung)", color = Color.White.copy(alpha = 0.4f), fontSize = 13.sp)
            }

            if (issue.jarvisComment.isNotBlank()) {
                HorizontalDivider(color = Color.White.copy(alpha = 0.12f))
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = JarvisPurple.copy(alpha = 0.18f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text("Antwort von Jarvis", color = JarvisPurple, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
                        Spacer(Modifier.height(4.dp))
                        Text(issue.jarvisComment, color = Color.White, fontSize = 14.sp)
                    }
                }
            }

            HorizontalDivider(color = Color.White.copy(alpha = 0.12f))

            // Attachments
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Anhaenge (${issue.attachments.size})", color = Color.White, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                if (issue.canEdit) {
                    TextButton(onClick = { pickFile.launch("*/*") }) {
                        Icon(Icons.Filled.Attachment, contentDescription = null)
                        Spacer(Modifier.width(4.dp))
                        Text("Hinzufuegen")
                    }
                }
            }
            issue.attachments.forEach { name ->
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable {
                            scope.launch {
                                val url = vm.attachmentUrl(issue.id, name)
                                val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                                runCatching { context.startActivity(intent) }
                            }
                        }
                        .padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Filled.AttachFile, contentDescription = null,
                        tint = Color.White.copy(alpha = 0.7f))
                    Spacer(Modifier.width(8.dp))
                    Text(name, color = Color(0xFF60A5FA), fontSize = 13.sp)
                }
            }
        }
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Form-Screen (Neu + Bearbeiten)
// ───────────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IssueFormScreen(
    initial: IssueItem?,
    onCancel: () -> Unit,
    onSubmit: (title: String, body: String, type: String, priority: String) -> Unit,
) {
    var title by remember { mutableStateOf(initial?.title ?: "") }
    var body by remember { mutableStateOf(initial?.body ?: "") }
    var type by remember { mutableStateOf(initial?.type ?: "bug") }
    var priority by remember { mutableStateOf(initial?.priority ?: "medium") }
    var typeMenu by remember { mutableStateOf(false) }
    var prioMenu by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (initial == null) "Neues Issue" else "Bearbeiten") },
                navigationIcon = {
                    IconButton(onClick = onCancel) {
                        Icon(Icons.Filled.Close, contentDescription = "Abbrechen")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            OutlinedTextField(
                value = title,
                onValueChange = { title = it.take(200) },
                label = { Text("Titel *") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = body,
                onValueChange = { body = it.take(20000) },
                label = { Text("Beschreibung") },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 180.dp),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
            )
            // Typ
            ExposedDropdown(
                label = "Typ",
                value = typeLabel(type),
                expanded = typeMenu,
                onExpandedChange = { typeMenu = it },
                options = listOf("bug" to "Bug", "feature" to "Feature", "improvement" to "Verbesserung"),
                onSelect = { type = it; typeMenu = false },
            )
            // Prioritaet
            ExposedDropdown(
                label = "Prioritaet",
                value = priorityLabel(priority),
                expanded = prioMenu,
                onExpandedChange = { prioMenu = it },
                options = listOf("low" to "Niedrig", "medium" to "Mittel", "high" to "Hoch"),
                onSelect = { priority = it; prioMenu = false },
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = onCancel) { Text("Abbrechen") }
                Spacer(Modifier.width(8.dp))
                Button(
                    onClick = { onSubmit(title.trim(), body.trim(), type, priority) },
                    enabled = title.trim().isNotEmpty(),
                    colors = ButtonDefaults.buttonColors(containerColor = JarvisPurple),
                ) { Text(if (initial == null) "Erstellen" else "Speichern") }
            }
        }
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Jarvis-Form (Status + Kommentar setzen)
// ───────────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun JarvisFormScreen(
    issue: IssueItem,
    onCancel: () -> Unit,
    onSubmit: (status: String, comment: String) -> Unit,
) {
    var status by remember(issue.id) { mutableStateOf(issue.status) }
    var comment by remember(issue.id) { mutableStateOf(issue.jarvisComment) }
    var menu by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Jarvis-Antwort") },
                navigationIcon = {
                    IconButton(onClick = onCancel) {
                        Icon(Icons.Filled.Close, contentDescription = "Abbrechen")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                ),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(issue.title, color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
            ExposedDropdown(
                label = "Status",
                value = statusLabel(status),
                expanded = menu,
                onExpandedChange = { menu = it },
                options = listOf("open" to "Offen", "in_progress" to "In Arbeit", "closed" to "Geschlossen"),
                onSelect = { status = it; menu = false },
            )
            OutlinedTextField(
                value = comment,
                onValueChange = { comment = it.take(20000) },
                label = { Text("Kommentar (sichtbar fuer Autor)") },
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = 160.dp),
            )
            Row(horizontalArrangement = Arrangement.End, modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(onClick = onCancel) { Text("Abbrechen") }
                Spacer(Modifier.width(8.dp))
                Button(
                    onClick = { onSubmit(status, comment.trim()) },
                    colors = ButtonDefaults.buttonColors(containerColor = JarvisGreen),
                ) { Text("Speichern") }
            }
        }
    }
}

// ───────────────────────────────────────────────────────────────────────────
// Helper: ExposedDropdown
// ───────────────────────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ExposedDropdown(
    label: String,
    value: String,
    expanded: Boolean,
    onExpandedChange: (Boolean) -> Unit,
    options: List<Pair<String, String>>, // (id, displayLabel)
    onSelect: (String) -> Unit,
) {
    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = onExpandedChange,
    ) {
        OutlinedTextField(
            value = value,
            onValueChange = {},
            readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            modifier = Modifier
                .fillMaxWidth()
                .menuAnchor(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { onExpandedChange(false) }) {
            options.forEach { (id, lbl) ->
                DropdownMenuItem(text = { Text(lbl) }, onClick = { onSelect(id) })
            }
        }
    }
}
