package app.arelis

import android.Manifest
import android.content.Intent
import android.graphics.Bitmap
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Base64
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : ComponentActivity() {
    private lateinit var prefs: Prefs
    // Cached: a live turn holds one thread on the NDJSON stream. Allow,
    // poll, and glances must not queue behind that wait.
    private val io = Executors.newCachedThreadPool()
    private val main = Handler(Looper.getMainLooper())
    private var wifiWatcher: WifiWatcher? = null
    private val gemma = GemmaEngine()
    private lateinit var voice: VoiceListen
    private var poll: Runnable? = null
    private val gemmaBusy = AtomicBoolean(false)
    private var pendingVoice = "conversation"

    private var screen by mutableStateOf("pair") // pair | talk | hose | files | settings | chats
    private var pairFromSettings by mutableStateOf(false)
    private var headline by mutableStateOf("Waiting to pair.")
    private var grants by mutableStateOf(
        GrantState(restrictedHint = true, sms = false, notifications = false, battery = false, camera = false),
    )
    private var paste by mutableStateOf("")
    private var busy by mutableStateOf(false)
    private var pairing by mutableStateOf(false)
    private var paired by mutableStateOf(false)
    private var mode by mutableStateOf(HouseMode.Pairing)
    private var warmup by mutableStateOf(false)
    private var draft by mutableStateOf("")
    private var bubbles by mutableStateOf(listOf<ChatBubble>())
    private var allow by mutableStateOf<AllowCard?>(null)
    private var allowBusy by mutableStateOf(false)
    private var dismissedConfirmId = ""
    private var previewJpeg by mutableStateOf<ByteArray?>(null)
    private var gemmaProgress by mutableStateOf("")
    private var gemmaInstall by mutableStateOf(GemmaInstall())
    private var error by mutableStateOf("")
    private var voiceMode by mutableStateOf("off")
    private var listening by mutableStateOf(false)
    private var dictateAnchor = ""
    private var glancePreview by mutableStateOf<ByteArray?>(null)
    private var fileScope by mutableStateOf("room")
    private var filePath by mutableStateOf("")
    private var fileParent by mutableStateOf<String?>(null)
    private var fileLabel by mutableStateOf("files")
    private var fileItems by mutableStateOf(listOf<FileRow>())
    private var fileError by mutableStateOf("")
    private var roomName by mutableStateOf("")
    private var chatItems by mutableStateOf(listOf<ChatRow>())
    private var chatError by mutableStateOf("")
    private var chatBusy by mutableStateOf(false)
    private lateinit var talkQueue: TalkQueue
    private lateinit var pocket: PocketThread
    private val seenNotices = mutableSetOf<String>()
    private var personaCache = ""
    private var lastHouse = false

    private val scanLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val payload = result.data?.getStringExtra(ScanActivity.EXTRA_PAYLOAD).orEmpty()
        if (payload.isNotBlank()) applyTicket(payload)
    }

    private val smsPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { refresh() }

    private val notifyPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { refresh() }

    private val micPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) startVoice(pendingVoice) else Toast.makeText(this, "Mic is needed to talk out loud.", Toast.LENGTH_LONG).show()
    }

    private val takePicture = registerForActivityResult(
        ActivityResultContracts.TakePicturePreview(),
    ) { bitmap: Bitmap? ->
        if (bitmap != null) previewJpeg = jpegOf(bitmap)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        talkQueue = TalkQueue(this)
        pocket = PocketThread(this)
        val restored = pocket.lines()
        if (restored.isNotEmpty()) {
            bubbles = restored.mapIndexed { i, line ->
                ChatBubble(id = "p$i", role = line.role, text = line.text)
            }
        }
        gemmaInstall = GemmaInstall(
            ready = GemmaStore.ready(this),
            later = prefs.gemmaLater,
            waitWifi = prefs.gemmaWaitWifi,
            onWifi = onWifi(this),
        )
        voice = VoiceListen(this).also { wireVoice(it) }
        ArelisPings.ensureChannel(this)
        if (Build.VERSION.SDK_INT >= 33) {
            notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        wifiWatcher = WifiWatcher(this).also { it.start() }
        paired = prefs.paired
        screen = if (prefs.paired) "talk" else "pair"
        if (prefs.paired) {
            WorkManager.getInstance(this).enqueueUniqueWork(
                InboundWorker.UNIQUE,
                ExistingWorkPolicy.KEEP,
                OneTimeWorkRequestBuilder<InboundWorker>().build(),
            )
        }
        setContent {
            ArelisTheme {
                val nested = screen != "talk" && !(screen == "pair" && !paired)
                BackHandler(enabled = nested) { stepBack() }
                when (screen) {
                    "settings" -> SettingsScreen(
                        paired = paired,
                        onBack = { stepBack() },
                        onPair = {
                            pairFromSettings = true
                            screen = "pair"
                        },
                        onTexts = {
                            RadioService.start(this)
                            screen = "hose"
                        },
                    )
                    "chats" -> HistoryScreen(
                        items = chatItems,
                        error = chatError,
                        busy = chatBusy,
                        onBack = { stepBack() },
                        onNew = { openChat("new") },
                        onOpen = { openChat("open", it.id) },
                    )
                    "hose" -> HoseScreen(
                        grants = grants,
                        onBack = { stepBack() },
                        onOpenRestricted = { openAppDetails(this) },
                        onGrantSms = { smsPermission.launch(Manifest.permission.SEND_SMS) },
                        onOpenNotifications = { openNotificationAccess(this) },
                        onOpenBattery = { openBatterySettings(this) },
                    )
                    "files" -> FilesScreen(
                        scope = fileScope,
                        label = fileLabel,
                        cwd = filePath,
                        items = fileItems,
                        error = fileError,
                        roomName = roomName,
                        onBack = { stepBack() },
                        onScope = { loadFiles(it, "") },
                        onOpen = { openFileRow(it) },
                        onUp = { loadFiles(fileScope, fileParent ?: "") },
                    )
                    "talk" -> TalkScreen(
                        state = TalkUi(
                            mode = mode,
                            warmup = warmup,
                            busy = busy,
                            draft = draft,
                            bubbles = bubbles,
                            allow = allow,
                            allowBusy = allowBusy,
                            previewJpeg = glancePreview ?: previewJpeg,
                            gemma = gemmaInstall.copy(
                                ready = GemmaStore.ready(this),
                                onWifi = onWifi(this),
                            ).toUi(gemmaProgress),
                            error = error,
                            voiceMode = voiceMode,
                            listening = listening,
                        ),
                        onDraft = { draft = it },
                        onSend = { sendText() },
                        onSettings = { screen = "settings" },
                        onChats = { loadChats() },
                        onFiles = { loadFiles(if (roomName.isNotBlank()) "room" else "workspace", "") },
                        onCamera = { takePicture.launch(null) },
                        onDictate = { askVoice("dictate") },
                        onTalk = { askVoice("conversation") },
                        onAllow = { replyAllow(true) },
                        onDeny = { replyAllow(false) },
                        onGlance = { openGlance(it) },
                        onGemmaInstall = { applyGemma(GemmaEvent.Install) },
                        onGemmaWaitWifi = { applyGemma(GemmaEvent.WaitWifi) },
                        onGemmaLater = { applyGemma(GemmaEvent.Later) },
                        onGemmaUseData = { applyGemma(GemmaEvent.UseData) },
                        onGemmaShow = { applyGemma(GemmaEvent.Show) },
                    )
                    else -> PairScreen(
                        headline = headline,
                        paste = paste,
                        busy = pairing,
                        onBack = if (paired) ({ stepBack() }) else null,
                        onScan = { scanLauncher.launch(Intent(this, ScanActivity::class.java)) },
                        onPasteChange = { paste = it },
                        onPasteApply = { if (paste.isNotBlank()) applyTicket(paste) },
                    )
                }
            }
        }
    }

    private fun stepBack() {
        when (screen) {
            "files" -> {
                if (filePath.isNotBlank()) {
                    loadFiles(fileScope, fileParent ?: "")
                } else {
                    screen = "talk"
                }
            }
            "chats" -> screen = "talk"
            "hose", "pair" -> screen = if (paired) "settings" else "talk"
            else -> screen = "talk"
        }
    }

    override fun onResume() {
        super.onResume()
        refresh()
        startPoll()
        maybeStartWaitedGemma()
    }

    override fun onPause() {
        stopPoll()
        super.onPause()
    }

    override fun onDestroy() {
        wifiWatcher?.stop()
        if (::voice.isInitialized) voice.stop()
        gemma.unload()
        super.onDestroy()
    }

    private fun refresh() {
        grants = grantState(this)
        paired = prefs.paired
        headline = when {
            prefs.paired -> "Paired. Talk."
            prefs.readyToTalk -> "PC address is saved. Scan again if this Wi-Fi moved."
            else -> "Waiting to pair. Open Settings → Notify on the PC and scan the QR."
        }
        if (prefs.paired && screen == "pair" && !pairFromSettings) screen = "talk"
    }

    private fun client(): ArelisClient? {
        if (!prefs.readyToTalk) return null
        return ArelisClient.fromPrefs(prefs)
    }

    private fun startPoll() {
        stopPoll()
        poll = object : Runnable {
            override fun run() {
                pollHouse()
                main.postDelayed(this, 3000)
            }
        }
        main.post(poll!!)
    }

    private fun stopPoll() {
        poll?.let { main.removeCallbacks(it) }
        poll = null
    }

    private fun pollHouse() {
        if (!prefs.paired) return
        io.execute {
            try {
                flushSync()
                val status = client()?.status() ?: throw IllegalStateException("not paired")
                val transcript = status.optJSONArray("transcript")
                val confirm = status.optJSONObject("pending_confirm")
                val notices = status.optJSONArray("notices")
                val session = status.optBoolean("session", false)
                val warm = status.optBoolean("warmup", false)
                val place = status.optJSONObject("place")
                val room = place?.optJSONObject("room")?.optString("name").orEmpty()
                main.post {
                    val wasPhone = mode == HouseMode.OnThePhone
                    mode = HouseMode.AtTheHouse
                    warmup = warm
                    roomName = room
                    maybeStartWaitedGemma()
                    if (!busy) {
                        // Don't stomp an in-flight send with a stale busy flag.
                    }
                    error = if (!session) {
                        "Open Arelis on the PC."
                    } else if (error == "Open Arelis on the PC.") {
                        ""
                    } else {
                        error
                    }
                    if (!allowBusy) {
                        val next = confirm?.let {
                            AllowCard(
                                id = it.optString("id"),
                                headline = it.optString("headline").ifBlank { "Allow" },
                                summary = it.optString("summary"),
                            )
                        }
                        allow = if (next != null && next.id == dismissedConfirmId) null else next
                    }
                    if (transcript != null && !busy) {
                        val next = parseBubbles(transcript)
                        val chatId = status.optJSONObject("chat")?.optString("id").orEmpty()
                        if (next.isNotEmpty() || talkQueue.isEmpty()) {
                            bubbles = next
                            pocket.replace(chatId, talkLines(next))
                        } else if (chatId.isNotBlank()) {
                            pocket.keepSession(chatId)
                        }
                    }
                    pingNotices(notices)
                    if (wasPhone) {
                        gemma.unload()
                        gemmaProgress = ""
                    }
                    lastHouse = true
                }
            } catch (_: Exception) {
                main.post {
                    if (prefs.paired) {
                        mode = HouseMode.OnThePhone
                        allow = null
                        if (screen == "chats" || screen == "files") screen = "talk"
                        if (lastHouse) {
                            ArelisPings.show(
                                this,
                                42,
                                "On the phone",
                                "The PC is gone. Gemma can talk until the house is back.",
                            )
                        }
                        lastHouse = false
                    }
                }
            }
        }
    }

    private fun pingNotices(notices: org.json.JSONArray?) {
        if (notices == null) return
        for (i in 0 until notices.length()) {
            val n = notices.optJSONObject(i) ?: continue
            val id = n.optString("id")
            val kind = n.optString("kind")
            if (!shouldPingNotice(kind)) continue
            if (id.isBlank() || !seenNotices.add(id)) continue
            ArelisPings.show(
                this,
                id.hashCode(),
                n.optString("title").ifBlank { "Arelis" },
                n.optString("body"),
            )
            io.execute {
                runCatching { client()?.ackNotice(id) }
            }
        }
    }

    private fun sendText() {
        val text = draft.trim()
        val photo = previewJpeg
        if (text.isEmpty() && photo == null) return
        draft = ""
        dictateAnchor = ""
        val jpeg = photo?.let { Base64.encodeToString(it, Base64.NO_WRAP) }
        previewJpeg = null
        if (voiceMode == "conversation") voice.pause()
        dispatchTurn(text, jpeg, null)
    }

    private fun askVoice(next: String) {
        pendingVoice = next
        val ok = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED
        if (ok) startVoice(next) else micPermission.launch(Manifest.permission.RECORD_AUDIO)
    }

    private fun startVoice(next: String) {
        val mode = toggleVoiceMode(voiceMode, next)
        if (mode == "off") {
            voice.stop()
            voiceMode = "off"
            listening = false
            return
        }
        dictateAnchor = draft
        voice.start(mode)
        voiceMode = mode
    }

    private fun wireVoice(listen: VoiceListen) {
        listen.onPartial = { text ->
            main.post {
                draft = VoiceDraft(voiceMode, dictateAnchor, draft).partial(text).draft
            }
        }
        listen.onFinal = { text ->
            main.post {
                val (step, send) = VoiceDraft(voiceMode, dictateAnchor, draft).finalHeard(text)
                draft = step.draft
                dictateAnchor = step.anchor
                if (send) {
                    listen.pause()
                    sendText()
                }
            }
        }
        listen.onState = { on -> main.post { listening = on } }
        listen.onError = { msg -> main.post { error = msg } }
    }

    private fun dispatchTurn(text: String, jpeg: String?, wav: String?) {
        val user = ChatBubble(id = UUID.randomUUID().toString(), role = "user", text = text.ifBlank { "Photo" })
        val streamId = UUID.randomUUID().toString()
        bubbles = bubbles + user + ChatBubble(id = streamId, role = "assistant", text = "", streaming = true)
        busy = true
        error = ""
        io.execute {
            try {
                if (mode == HouseMode.OnThePhone) {
                    runGemmaTurn(text, streamId)
                    return@execute
                }
                val acc = StringBuilder()
                client()?.turn(text, jpeg, wav) { line ->
                    when (line.optString("type")) {
                        "delta" -> {
                            acc.append(line.optString("text"))
                            patchAssistant(streamId, acc.toString(), streaming = true)
                        }
                        "retract" -> {
                            acc.setLength(0)
                            patchAssistant(streamId, "", streaming = true)
                        }
                        "done" -> {
                            val final = line.optString("text").ifBlank { acc.toString() }
                            patchAssistant(streamId, final, streaming = false)
                        }
                        "error" -> main.post { error = line.optString("message") }
                        "confirm" -> main.post {
                            allow = AllowCard(
                                id = line.optString("id"),
                                headline = line.optString("headline").ifBlank { "Allow" },
                                summary = line.optString("summary"),
                            )
                        }
                        "glance" -> main.post {
                            bubbles = bubbles.map { b ->
                                if (b.id == streamId) b.copy(
                                    glances = b.glances + GlanceCard(
                                        id = line.optString("id"),
                                        title = line.optString("title"),
                                        kind = line.optString("kind"),
                                    ),
                                ) else b
                            }
                        }
                    }
                }
            } catch (exc: Exception) {
                main.post {
                    error = exc.message ?: "Turn failed."
                    mode = HouseMode.OnThePhone
                }
                try {
                    runGemmaTurn(text, streamId)
                    return@execute
                } catch (inner: Exception) {
                    main.post { error = inner.message ?: "On the phone, but Gemma is not ready." }
                }
            } finally {
                main.post {
                    busy = false
                    if (voiceMode == "conversation" && allow == null) {
                        voice.resumeIfLatched()
                    }
                }
            }
        }
    }

    private fun runGemmaTurn(text: String, streamId: String) {
        if (!GemmaStore.ready(this)) {
            main.post {
                applyGemma(GemmaEvent.Show)
                patchAssistant(
                    streamId,
                    "I am on the phone and the offline brain is not installed yet.",
                    false,
                )
            }
            return
        }
        if (personaCache.isBlank()) {
            personaCache = runCatching { client()?.persona().orEmpty() }.getOrDefault("")
            if (personaCache.isBlank()) {
                personaCache = "You are Arelis. You are on the phone. No tools."
            }
        }
        gemma.ensure(this, GemmaStore.file(this), personaCache)
        val acc = StringBuilder()
        val reply = gemma.reply(text) { piece ->
            acc.append(piece)
            patchAssistant(streamId, acc.toString(), streaming = true)
        }
        val final = reply.ifBlank { acc.toString() }
        patchAssistant(streamId, final, streaming = false)
        talkQueue.add("user", text)
        talkQueue.add("assistant", final)
        pocket.append("user", text)
        pocket.append("assistant", final)
    }

    private fun patchAssistant(id: String, text: String, streaming: Boolean) {
        main.post {
            bubbles = bubbles.map { if (it.id == id) it.copy(text = text, streaming = streaming) else it }
        }
    }

    private fun applyGemma(event: GemmaEvent) {
        val next = gemmaInstall.copy(
            ready = GemmaStore.ready(this),
            onWifi = onWifi(this),
        ).reduce(event)
        gemmaInstall = next
        prefs.gemmaLater = next.later
        prefs.gemmaWaitWifi = next.waitWifi
        if (next.downloading && !next.ready) downloadGemma()
    }

    private fun maybeStartWaitedGemma() {
        applyGemma(GemmaEvent.WifiAppeared)
    }

    private fun downloadGemma() {
        if (GemmaStore.ready(this) || !gemmaBusy.compareAndSet(false, true)) return
        gemmaProgress = "Downloading the offline brain…"
        io.execute {
            try {
                GemmaStore.download(this) { got, total ->
                    val pct = if (total > 0) (got * 100 / total).toInt() else 0
                    main.post { gemmaProgress = "Downloading the offline brain… $pct%" }
                }
                main.post {
                    gemmaProgress = ""
                    gemmaBusy.set(false)
                    applyGemma(GemmaEvent.BecameReady)
                }
            } catch (exc: Exception) {
                main.post {
                    gemmaInstall = gemmaInstall.copy(downloading = false)
                    gemmaProgress = exc.message ?: "Download failed."
                    gemmaBusy.set(false)
                }
            }
        }
    }

    private fun loadFiles(scope: String, path: String) {
        if (mode == HouseMode.OnThePhone) {
            fileError = "Files live on the PC. They come back when the house is up."
            fileItems = emptyList()
            screen = "files"
            return
        }
        fileScope = scope
        filePath = path
        fileError = ""
        screen = "files"
        io.execute {
            try {
                val body = client()?.listFiles(scope, path) ?: throw IllegalStateException("not paired")
                val rows = mutableListOf<FileRow>()
                val arr = body.optJSONArray("items")
                if (arr != null) {
                    for (i in 0 until arr.length()) {
                        val row = arr.optJSONObject(i) ?: continue
                        rows += FileRow(
                            name = row.optString("name"),
                            dir = row.optBoolean("dir"),
                            path = row.optString("path"),
                            bytes = row.optLong("bytes"),
                        )
                    }
                }
                val parent = if (body.isNull("parent")) null else body.optString("parent")
                val label = body.optString("label").ifBlank { scope }
                main.post {
                    fileItems = rows
                    fileParent = parent
                    filePath = body.optString("cwd")
                    fileLabel = label
                }
            } catch (exc: Exception) {
                main.post { fileError = exc.message ?: "Could not list files." }
            }
        }
    }

    private fun openFileRow(row: FileRow) {
        if (row.dir) {
            loadFiles(fileScope, row.path)
            return
        }
        io.execute {
            try {
                val (bytes, mime) = client()?.openPath(row.path) ?: return@execute
                main.post {
                    screen = "talk"
                    if (mime.startsWith("image/")) {
                        glancePreview = bytes
                    } else {
                        val text = bytes.decodeToString().take(4000)
                        bubbles = bubbles + ChatBubble(
                            id = UUID.randomUUID().toString(),
                            role = "assistant",
                            text = "${row.name}\n\n$text",
                        )
                    }
                }
            } catch (exc: Exception) {
                main.post { fileError = exc.message ?: "Could not open that file." }
            }
        }
    }

    private fun parseBubbles(transcript: org.json.JSONArray): List<ChatBubble> {
        val next = mutableListOf<ChatBubble>()
        for (i in 0 until transcript.length()) {
            val row = transcript.optJSONObject(i) ?: continue
            val glances = mutableListOf<GlanceCard>()
            val g = row.optJSONArray("glances")
            if (g != null) {
                for (j in 0 until g.length()) {
                    val card = g.optJSONObject(j) ?: continue
                    glances += GlanceCard(
                        id = card.optString("id"),
                        title = card.optString("title"),
                        kind = card.optString("kind"),
                    )
                }
            }
            next += ChatBubble(
                id = "t$i",
                role = row.optString("role"),
                text = row.optString("text"),
                glances = glances,
            )
        }
        return next
    }

    private fun talkLines(items: List<ChatBubble>): List<TalkLine> =
        items.mapNotNull { row ->
            val role = row.role
            val text = row.text.trim()
            if (role in setOf("user", "assistant") && text.isNotEmpty()) {
                TalkLine(role, text)
            } else {
                null
            }
        }

    private fun loadChats() {
        screen = "chats"
        chatError = ""
        io.execute {
            try {
                val body = client()?.listChats() ?: throw IllegalStateException("not paired")
                val current = body.optJSONObject("current")?.optString("id").orEmpty()
                val arr = body.optJSONArray("chats")
                val next = mutableListOf<ChatRow>()
                if (arr != null) {
                    for (i in 0 until arr.length()) {
                        val row = arr.optJSONObject(i) ?: continue
                        val id = row.optString("id")
                        if (id.isBlank()) continue
                        next += ChatRow(
                            id = id,
                            title = row.optString("title").ifBlank { "(untitled)" },
                            startedAt = row.optString("started_at"),
                            current = id == current,
                        )
                    }
                }
                main.post {
                    chatItems = next
                    chatError = ""
                }
            } catch (exc: Exception) {
                main.post { chatError = exc.message ?: "Could not list chats." }
            }
        }
    }

    private fun openChat(action: String, id: String = "") {
        if (chatBusy) return
        chatBusy = true
        chatError = ""
        io.execute {
            try {
                val body = client()?.switchChat(action, id)
                    ?: throw IllegalStateException("not paired")
                val transcript = body.optJSONArray("transcript")
                main.post {
                    chatBusy = false
                    if (transcript != null) {
                        val next = parseBubbles(transcript)
                        bubbles = next
                        val chatId = body.optJSONObject("chat")?.optString("id").orEmpty()
                        pocket.replace(chatId, talkLines(next))
                    }
                    allow = null
                    screen = "talk"
                }
            } catch (exc: Exception) {
                main.post {
                    chatBusy = false
                    chatError = exc.message ?: "Could not open that chat."
                }
            }
        }
    }

    private fun flushSync() {
        val rows = talkQueue.take()
        if (rows.isEmpty()) return
        try {
            val payload = rows.map { JSONObject().put("role", it.role).put("text", it.text) }
            client()?.sync(payload, pocket.sessionId()) ?: throw IllegalStateException("not paired")
        } catch (_: Exception) {
            talkQueue.restore(rows)
        }
    }

    private fun replyAllow(ok: Boolean) {
        val card = allow ?: return
        if (allowBusy) return
        if (card.id.isBlank()) {
            error = "That Allow card has no id — try again from the PC."
            return
        }
        allowBusy = true
        error = ""
        io.execute {
            try {
                client()?.confirm(card.id, ok)
                    ?: throw IllegalStateException("Not paired.")
                main.post {
                    dismissedConfirmId = card.id
                    allowBusy = false
                    allow = null
                }
            } catch (exc: Exception) {
                main.post {
                    allowBusy = false
                    error = exc.message ?: "Allow did not reach the PC."
                }
            }
        }
    }

    private fun openGlance(card: GlanceCard) {
        io.execute {
            try {
                val (bytes, _) = client()?.fileBytes(card.id) ?: return@execute
                main.post { glancePreview = bytes }
            } catch (exc: Exception) {
                main.post { error = exc.message ?: "Could not fetch that file." }
            }
        }
    }

    private fun applyTicket(raw: String) {
        if (pairing) return
        val ticket = try {
            parsePairTicket(raw)
        } catch (exc: Exception) {
            Toast.makeText(this, exc.message ?: "Could not read pairing.", Toast.LENGTH_LONG).show()
            return
        }
        pairing = true
        headline = "Pairing…"
        prefs.token = ticket.token
        prefs.instanceId = ticket.instance
        prefs.baseUrl = ticket.lanUrls.first()
        prefs.relayUrl = ticket.relayUrl
        prefs.deviceKey
        prefs.listenUrl = ""
        io.execute {
            val errorText = runCatching { pairNow(ticket) }.exceptionOrNull()
            runOnUiThread {
                pairing = false
                if (errorText != null) {
                    headline = errorText.message ?: "Pairing failed."
                    Toast.makeText(this, headline, Toast.LENGTH_LONG).show()
                } else {
                    paste = ""
                    pairFromSettings = false
                    screen = "talk"
                    mode = HouseMode.Connecting
                    refresh()
                    Toast.makeText(this, "Paired. Talk.", Toast.LENGTH_SHORT).show()
                    applyGemma(GemmaEvent.Show)
                }
            }
        }
    }

    private fun pairNow(ticket: PairTicket) {
        val listen = waitForListenUrl(800) ?: listenUrlFor(this, prefs.listenPort) ?: ""
        if (listen.isNotBlank()) prefs.listenUrl = listen
        var last: Exception? = null
        for (url in ticket.urls) {
            prefs.baseUrl = url
            try {
                ArelisClient(url, ticket.token).pair(
                    instance = ticket.instance,
                    pair = ticket.pair,
                    listenUrl = listen,
                    deviceKey = prefs.deviceKey,
                    talk = true,
                )
                last = null
                break
            } catch (exc: Exception) {
                last = exc
            }
        }
        if (last != null) throw last
        prefs.paired = true
        if (listen.isNotBlank()) {
            RadioService.start(this)
            WorkManager.getInstance(this).enqueueUniqueWork(
                InboundWorker.UNIQUE,
                ExistingWorkPolicy.KEEP,
                OneTimeWorkRequestBuilder<InboundWorker>().build(),
            )
        }
    }

    private fun waitForListenUrl(timeoutMs: Long): String? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val url = prefs.listenUrl
            if (url.isNotBlank()) return url
            Thread.sleep(50)
        }
        return listenUrlFor(this, prefs.listenPort)
    }

    private fun jpegOf(bitmap: Bitmap): ByteArray {
        val out = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, 82, out)
        return out.toByteArray()
    }
}
