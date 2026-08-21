package app.arelis

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

data class FileRow(
    val name: String,
    val dir: Boolean,
    val path: String,
    val bytes: Long,
)

@Composable
fun FilesScreen(
    scope: String,
    label: String,
    cwd: String,
    items: List<FileRow>,
    error: String,
    roomName: String,
    onBack: () -> Unit,
    onScope: (String) -> Unit,
    onOpen: (FileRow) -> Unit,
    onUp: () -> Unit,
) {
    val shape = RoundedCornerShape(12.dp)
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Campfire.bg0)
            .padding(16.dp),
    ) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(
                "← back",
                color = Campfire.dim,
                modifier = Modifier.clickable(onClick = onBack).padding(4.dp),
            )
            Text(label.ifBlank { "files" }, color = Campfire.accent, fontWeight = FontWeight.Medium)
            Text("", modifier = Modifier.padding(4.dp))
        }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            ScopeChip(scope == "room", roomName.ifBlank { "room" }) { onScope("room") }
            ScopeChip(scope == "workspace", "workspace") { onScope("workspace") }
        }
        Spacer(Modifier.height(8.dp))
        if (cwd.isNotBlank()) {
            Text(
                "up",
                color = Campfire.accent2,
                fontSize = 13.sp,
                modifier = Modifier.clickable(onClick = onUp).padding(vertical = 4.dp),
            )
            Text(cwd, color = Campfire.hint, fontSize = 12.sp)
        }
        if (error.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(error, color = Campfire.danger, fontSize = 13.sp)
        }
        Spacer(Modifier.height(8.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            items(items, key = { it.path }) { row ->
                val meta = if (row.dir) "folder" else sizeLabel(row.bytes)
                Text(
                    "${row.name}  $meta",
                    color = if (row.dir) Campfire.accent2 else Campfire.text,
                    fontSize = 15.sp,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(shape)
                        .background(Campfire.bg1)
                        .clickable { onOpen(row) }
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                )
            }
        }
    }
}

@Composable
private fun ScopeChip(on: Boolean, label: String, click: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Text(
        label,
        color = if (on) Campfire.bg0 else Campfire.hint,
        fontSize = 13.sp,
        modifier = Modifier
            .clip(shape)
            .background(if (on) Campfire.accent else Campfire.bg2)
            .clickable(onClick = click)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    )
}

private fun sizeLabel(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    if (bytes < 1024 * 1024) return "${bytes / 1024} KB"
    return "${bytes / (1024 * 1024)} MB"
}
