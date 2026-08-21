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

data class ChatRow(
    val id: String,
    val title: String,
    val startedAt: String,
    val current: Boolean,
)

@Composable
fun HistoryScreen(
    items: List<ChatRow>,
    error: String,
    busy: Boolean,
    onBack: () -> Unit,
    onNew: () -> Unit,
    onOpen: (ChatRow) -> Unit,
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
                "← talk",
                color = Campfire.accent,
                modifier = Modifier.clickable(onClick = onBack).padding(4.dp),
            )
            Text("Chats", color = Campfire.accent, fontWeight = FontWeight.Medium)
            Text("", modifier = Modifier.padding(4.dp))
        }
        Spacer(Modifier.height(12.dp))
        Text(
            if (busy) "Opening…" else "New chat",
            color = Campfire.bg0,
            fontWeight = FontWeight.Medium,
            modifier = Modifier
                .fillMaxWidth()
                .clip(shape)
                .background(if (busy) Campfire.coal else Campfire.accent)
                .clickable(enabled = !busy, onClick = onNew)
                .padding(horizontal = 14.dp, vertical = 12.dp),
        )
        Spacer(Modifier.height(8.dp))
        Text(
            "Same conversations as the PC. New chat starts a fresh one on both.",
            color = Campfire.dim,
            fontSize = 13.sp,
        )
        if (error.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(error, color = Campfire.danger, fontSize = 13.sp)
        }
        Spacer(Modifier.height(12.dp))
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(items, key = { it.id }) { row ->
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(shape)
                        .background(if (row.current) Campfire.bg2 else Campfire.bg1)
                        .clickable(enabled = !busy) { onOpen(row) }
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                ) {
                    Text(
                        row.title,
                        color = Campfire.text,
                        fontSize = 15.sp,
                        fontWeight = if (row.current) FontWeight.Medium else FontWeight.Normal,
                    )
                    if (row.startedAt.isNotBlank()) {
                        Text(
                            row.startedAt.take(10),
                            color = Campfire.hint,
                            fontSize = 12.sp,
                        )
                    }
                }
            }
        }
    }
}
