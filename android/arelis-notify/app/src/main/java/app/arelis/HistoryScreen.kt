package app.arelis

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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

data class ChatRow(
    val id: String,
    val title: String,
    val startedAt: String,
    val current: Boolean,
    val room: String = "",
)

@Composable
fun HistoryScreen(
    items: List<ChatRow>,
    error: String,
    busy: Boolean,
    onPhone: Boolean = false,
    onBack: () -> Unit,
    onNew: () -> Unit,
    onOpen: (ChatRow) -> Unit,
) {
    EmberScreen {
        ScreenTop(title = "chats", onBack = onBack, backLabel = "← talk")
        Spacer(Modifier.height(16.dp))
        EmberButton(
            if (busy) "opening…" else "new chat",
            onClick = onNew,
            modifier = Modifier.fillMaxWidth(),
            enabled = !busy,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            if (onPhone) {
                "The house is away. New chat starts on this phone. It copies back when Arelis is up."
            } else {
                "Same conversations as the PC. A new chat starts on both."
            },
            color = Campfire.dim,
            fontSize = 13.sp,
        )
        if (error.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(error, color = Campfire.danger, fontSize = 13.sp)
        }
        Spacer(Modifier.height(16.dp))
        if (items.isEmpty() && error.isBlank() && !busy) {
            Box(
                Modifier.weight(1f).fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                EmptyHint(
                    if (onPhone) "no thread on this phone" else "no threads yet",
                    if (onPhone) {
                        "Tap new chat. Gemma will talk here until the house is back."
                    } else {
                        "Start one here or on the PC. They stay in sync."
                    },
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(items, key = { it.id }) { row ->
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .clip(EmberShape)
                            .background(if (row.current) Campfire.bg2 else Campfire.bg1)
                            .border(
                                1.dp,
                                if (row.current) Campfire.accent.copy(alpha = 0.5f) else Campfire.rim,
                                EmberShape,
                            )
                            .clickable(enabled = !busy) { onOpen(row) }
                            .padding(horizontal = 14.dp, vertical = 12.dp),
                    ) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text(
                                row.title,
                                color = Campfire.text,
                                fontSize = 16.sp,
                                fontWeight = if (row.current) FontWeight.SemiBold else FontWeight.Normal,
                                modifier = Modifier.weight(1f),
                            )
                            Row(
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                if (row.room.isNotBlank()) StatusPill(row.room)
                                if (row.current) StatusPill("now", hot = true)
                            }
                        }
                        if (row.startedAt.isNotBlank()) {
                            Spacer(Modifier.height(4.dp))
                            Text(row.startedAt.take(10), color = Campfire.hint, fontSize = 12.sp)
                        }
                    }
                }
            }
        }
    }
}
