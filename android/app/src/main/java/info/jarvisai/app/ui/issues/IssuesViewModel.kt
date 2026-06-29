package info.jarvisai.app.ui.issues

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import info.jarvisai.app.data.repository.IssuesRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import javax.inject.Inject

/** UI-Model fuer ein Issue (Snapshot eines JSONObject). */
data class IssueItem(
    val id: String,
    val title: String,
    val body: String,
    val author: String,
    val type: String,
    val status: String,
    val priority: String,
    val created: String,
    val updated: String,
    val jarvisComment: String,
    val attachments: List<String>,
    val canEdit: Boolean,
    val canDelete: Boolean,
) {
    companion object {
        fun from(raw: JSONObject): IssueItem {
            // GET/POST /api/issues[/{id}] liefern den Issue gewrappt:
            // {"ok":true,"issue":{...},"can_edit":...}. Listen-Eintraege sind
            // dagegen direkt das Issue-Objekt. Beides unterstuetzen.
            val o = raw.optJSONObject("issue") ?: raw
            val canEdit = if (raw.has("can_edit")) raw.optBoolean("can_edit", false)
                          else o.optBoolean("can_edit", false)
            val canDelete = if (raw.has("can_delete")) raw.optBoolean("can_delete", false)
                            else o.optBoolean("can_delete", false)
            val atts = o.optJSONArray("attachments") ?: JSONArray()
            val list = (0 until atts.length()).mapNotNull { atts.optString(it) }
            return IssueItem(
                id = o.optString("id"),
                title = o.optString("title"),
                body = o.optString("body"),
                author = o.optString("author"),
                type = o.optString("type", "bug"),
                status = o.optString("status", "open"),
                priority = o.optString("priority", "medium"),
                created = o.optString("created"),
                updated = o.optString("updated"),
                jarvisComment = o.optString("jarvis_comment"),
                attachments = list,
                canEdit = canEdit,
                canDelete = canDelete,
            )
        }
    }
}

data class IssueFilter(
    val mineOnly: Boolean = false,
    val status: String? = null,  // open | in_progress | closed | null
    val type: String? = null,    // bug | feature | improvement | null
)

@HiltViewModel
class IssuesViewModel @Inject constructor(
    private val repo: IssuesRepository,
) : ViewModel() {

    private val _issues = MutableStateFlow<List<IssueItem>>(emptyList())
    val issues: StateFlow<List<IssueItem>> = _issues.asStateFlow()

    private val _loading = MutableStateFlow(false)
    val loading: StateFlow<Boolean> = _loading.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    private val _filter = MutableStateFlow(IssueFilter())
    val filter: StateFlow<IssueFilter> = _filter.asStateFlow()

    private val _selected = MutableStateFlow<IssueItem?>(null)
    val selected: StateFlow<IssueItem?> = _selected.asStateFlow()

    private val _currentUser = MutableStateFlow("")
    val currentUser: StateFlow<String> = _currentUser.asStateFlow()

    init { refresh() }

    fun setFilter(f: IssueFilter) {
        _filter.value = f
        refresh()
    }

    fun refresh() {
        _loading.value = true
        _error.value = null
        viewModelScope.launch {
            try {
                _currentUser.value = repo.currentUser()
                val arr = repo.list(
                    mine = _filter.value.mineOnly,
                    status = _filter.value.status,
                    type = _filter.value.type,
                )
                val list = (0 until arr.length()).map { IssueItem.from(arr.getJSONObject(it)) }
                _issues.value = list
            } catch (e: Exception) {
                _error.value = e.message ?: "Fehler"
            } finally {
                _loading.value = false
            }
        }
    }

    fun select(item: IssueItem?) {
        if (item == null) { _selected.value = null; return }
        viewModelScope.launch {
            try {
                _selected.value = IssueItem.from(repo.get(item.id))
            } catch (e: Exception) {
                _error.value = e.message ?: "Fehler"
            }
        }
    }

    fun reloadSelected() {
        val id = _selected.value?.id ?: return
        viewModelScope.launch {
            try { _selected.value = IssueItem.from(repo.get(id)) }
            catch (e: Exception) { _error.value = e.message ?: "Fehler" }
        }
    }

    fun create(title: String, body: String, type: String, priority: String, onDone: (IssueItem?) -> Unit) {
        viewModelScope.launch {
            try {
                val obj = repo.create(title, body, type, priority)
                val item = IssueItem.from(obj)
                onDone(item)
                refresh()
            } catch (e: Exception) {
                _error.value = e.message ?: "Fehler"
                onDone(null)
            }
        }
    }

    fun update(id: String, patch: JSONObject, onDone: () -> Unit = {}) {
        viewModelScope.launch {
            try {
                val obj = repo.update(id, patch)
                _selected.value = IssueItem.from(obj)
                refresh()
                onDone()
            } catch (e: Exception) {
                _error.value = e.message ?: "Fehler"
            }
        }
    }

    fun delete(id: String, onDone: () -> Unit = {}) {
        viewModelScope.launch {
            try {
                repo.delete(id)
                _selected.value = null
                refresh()
                onDone()
            } catch (e: Exception) {
                _error.value = e.message ?: "Fehler"
            }
        }
    }

    fun uploadAttachment(id: String, filename: String, mime: String, bytes: ByteArray) {
        viewModelScope.launch {
            try {
                val obj = repo.uploadAttachment(id, filename, mime, bytes)
                _selected.value = IssueItem.from(obj)
            } catch (e: Exception) {
                _error.value = e.message ?: "Fehler"
            }
        }
    }

    suspend fun attachmentUrl(id: String, name: String): String = repo.attachmentUrl(id, name)

    fun clearError() { _error.value = null }
}
