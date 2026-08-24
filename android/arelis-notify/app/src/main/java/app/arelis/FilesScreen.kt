package app.arelis

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
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
    canUp: Boolean = false,
    onBack: () -> Unit,
    onScope: (String) -> Unit,
    onOpen: (FileRow) -> Unit,
    onUp: () -> Unit,
) {
    EmberScreen {
        ScreenTop(title = label.ifBlank { "files" }, onBack = onBack)
        Spacer(Modifier.height(16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            LatchChip(roomName.ifBlank { "room" }, scope == "room") { onScope("room") }
            LatchChip("workspace", scope == "workspace") { onScope("workspace") }
        }
        if (canUp) {
            Spacer(Modifier.height(10.dp))
            GhostLink("↑ up", onUp)
            Text(cwd, color = Campfire.hint, fontSize = 12.sp)
        }
        if (error.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(error, color = Campfire.danger, fontSize = 13.sp)
        }
        Spacer(Modifier.height(12.dp))
        if (items.isEmpty() && error.isBlank()) {
            Box(
                Modifier.weight(1f).fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                EmptyHint("nothing here", "Room files when you're in a room. Workspace is the rest.")
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(items, key = { it.path }) { row ->
                    val meta = if (row.dir) "folder" else sizeLabel(row.bytes)
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clip(EmberShapeTight)
                            .background(Campfire.bg1)
                            .border(1.dp, Campfire.rim, EmberShapeTight)
                            .clickable { onOpen(row) }
                            .padding(horizontal = 14.dp, vertical = 12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            row.name,
                            color = if (row.dir) Campfire.accent2 else Campfire.text,
                            fontSize = 15.sp,
                            fontWeight = if (row.dir) FontWeight.Medium else FontWeight.Normal,
                            modifier = Modifier.weight(1f),
                        )
                        Text(meta, color = Campfire.coal, fontSize = 12.sp)
                    }
                }
            }
        }
    }
}

private fun sizeLabel(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    if (bytes < 1024 * 1024) return "${bytes / 1024} KB"
    return "${bytes / (1024 * 1024)} MB"
}
