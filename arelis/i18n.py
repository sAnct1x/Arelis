"""Session language for the window. English, or Simplified Chinese.

The strings live here as English source → 简体中文. Widgets are built in
English. ``localize`` walks them once the window exists, and ``tr`` is for
text that gets set again later (placeholders, the confirm card, status).
"""

from __future__ import annotations

from typing import Any

_LANG = "en"

# English source text. Values are Simplified Chinese. Keep each value unique
# so a second walk can find its way back to the source.
_ZH: dict[str, str] = {
    "Language": "语言",
    "Chat, the window, and her voice follow this.": "聊天、窗口和她的声音都跟着这个走。",
    "Settings": "设置",
    "Drag to move": "拖动可移动",
    "Close": "关闭",
    "Close settings": "关闭设置",
    "Settings tabs": "设置分页",
    "audio": "音频",
    "window": "窗口",
    "allow": "允许",
    "notify": "通知",
    "roots": "目录",
    "memory": "记忆",
    "Microphone": "麦克风",
    "Speaker": "扬声器",
    "Volume": "音量",
    "System default": "系统默认",
    "Voice features": "语音功能",
    "Listen (speech to text)": "听（语音转文字）",
    "Speak (text to speech)": "说（文字转语音）",
    "Test mic": "试麦克风",
    "Test speak": "试说话",
    "Applies when you click Apply.": "点确定后生效。",
    "always on top": "窗口置顶",
    "close to tray": "关闭到托盘",
    "Closing the window leaves Arelis in the tray so inbound Notify keeps working.": (
        "关掉窗口后 Arelis 还在托盘里，手机通知还能进来。"
    ),
    "collapse unused panels": "收起没用的面板",
    "Reset layout": "重置布局",
    "After": "超过",
    "Interface scale": "界面缩放",
    "Chat text size": "聊天字号",
    "Models": "模型",
    "Chat": "聊天",
    "Research": "深入研究",
    "Vision fallback": "看图备用",
    "the ask is the grant": "你说了就算同意",
    "ask me everything": "每件事都问我",
    "never ask about local work": "本地的事不用问",
    "files, memory, calendar, rooms": "文件、记忆、日历、房间",
    "pictures": "图片",
    "her window, when she offers it": "她的窗口，她提出来的时候",
    "the desk, when she offers it": "桌面，她提出来的时候",
    "seeing images and the screen": "看图片和屏幕",
    "mail and texts": "邮件和短信",
    "programs in the project": "项目里的程序",
    "Phone": "手机",
    "Scan with the Arelis app. Same Wi-Fi.": "用 Arelis 应用扫。要在同一个 Wi-Fi。",
    "Create a pairing code": "生成配对码",
    (
        "Phone notifications are turned on but not set up yet. "
        "To finish, open Settings, go to Notify, pick Create a pairing code, then restart Arelis."
    ): "手机通知已经打开，但还没配对好。请打开设置，进入通知，点生成配对码，然后重启 Arelis。",
    "Install the app": "安装应用",
    "Copy link": "复制链接",
    "Copy for the phone": "复制给手机",
    "New code": "新配对码",
    "Copy install link": "复制安装链接",
    "Download offline copy": "下载离线副本",
    "Notices": "通知",
    "Mail": "邮件",
    "Address": "地址",
    "App password": "应用密码",
    "Browse": "浏览",
    "Read-only": "只读",
    "Name": "名称",
    "Path": "路径",
    "Add": "添加",
    "Update": "更新",
    "Remove": "移除",
    "OK": "确定",
    "Cancel": "取消",
    "Confirm": "确认",
    "thinking": "思考",
    "workspace": "工作区",
    "history": "历史",
    "notifications": "通知",
    "camera": "相机",
    "contacts": "联系人",
    "calendar": "日历",
    "Reality": "现实",
    "reset layout": "重置布局",
    "settings…": "设置…",
    "fullscreen": "全屏",
    "larger text": "放大文字",
    "smaller text": "缩小文字",
    "reset text size": "恢复字号",
    "notify url…": "通知地址…",
    "Show and copy the phone companion URL": "显示并复制手机伴侣地址",
    "shortcuts": "快捷键",
    "dictate": "听写",
    "conversation": "对话",
    "themes": "主题",
    "View": "视图",
    "message Arelis…": "跟 Arelis 说…",
    "say yes · or type allow": "说「可以」，或输入允许",
    "Enter = allow · Esc = deny…": "回车 = 允许 · Esc = 拒绝…",
    "listening": "在听",
    'talking, esc to cut': '她在说，Esc 打断',
    "dictate into the message box (Ctrl+M)": "听写进输入框（Ctrl+M）",
    "Dictate": "听写",
    "talk with Arelis (Ctrl+Shift+M) · say goodbye to stop": (
        "和 Arelis 说话（Ctrl+Shift+M）· 说再见结束"
    ),
    "Talk": "对话",
    "stop": "停止",
    'stop current turn, Esc also stops once she has started answering': (
        '停掉这一轮，她开始回答后 Esc 也能停'
    ),
    "Stop": "停止",
    'stop current turn, also the hung-turn unlock': "停掉这一轮，卡住的回合也能解开",
    "send": "发送",
    "Send": "发送",
    'say "hey arelis"': "说「Hey Arelis」",
    "talking · say goodbye": "对话中 · 说再见结束",
    "dictating · ctrl+m to stop": "听写中 · Ctrl+M 停止",
    "getting the ear…": "耳朵还在准备…",
    "what she can do": "她能做什么",
    "new": "新的",
    "new chat": "新对话",
    "what's the weather going to be like tomorrow?": "明天天气怎么样？",
    "what's on my calendar today?": "今天日历上有什么？",
    "remember that I climb on Tuesdays": "记住我周二去攀岩",
    "deny": "拒绝",
    "rest of this ask": "这一问剩下的也允许",
    "further steps in this reply, not forever": "只包括这一次回答里后面的步骤",
    "don't ask again": "以后不用再问",
    "turn off this Allow gate in Settings": "在设置里关掉这一类确认",
    "confirm tool": "确认操作",
    "pause": "暂停",
    "go": "继续",
    'freeze mid-drive, the page stays': '暂停操作，页面留着',
    'abort this turn, the page stays': '停掉这一轮，页面留着',
    "continue from here": "从这里继续",
    "Pause drive": "暂停操作",
    "Stop drive": "停止操作",
    'paused, page stays': '已暂停，页面留着',
    'your turn, page stays': '轮到你，页面留着',
    "✦ thinking…": "✦ 在想…",
    "✦ wrapping up…": "✦ 在收尾…",
    "✦ loading the model…": "✦ 模型还在加载…",
    "✦ waiting for you…": "✦ 等你…",
    "✦ looking at your calendar…": "✦ 在看日历…",
    "✦ reading the table…": "✦ 在读表…",
    "✦ driving the browser…": "✦ 在操作浏览器…",
    "✦ using the desk…": "✦ 在用桌面…",
    "✦ working that out…": "✦ 在算…",
    "✦ working the algebra…": "✦ 在做代数…",
    "✦ running the numbers…": "✦ 在跑计算…",
    "✦ running a program…": "✦ 在跑程序…",
    "✦ running a project task…": "✦ 在跑项目任务…",
    "✦ running my tests…": "✦ 在跑测试…",
    "✦ checking the house watch…": "✦ 在看家里的监控…",
    "✦ looking through the camera…": "✦ 在看摄像头…",
    "✦ reading your clipboard…": "✦ 在读剪贴板…",
    "✦ looking up the contact…": "✦ 在查联系人…",
    "✦ reading the document…": "✦ 在读文档…",
    "✦ writing the file…": "✦ 在写文件…",
    "✦ checking the repo…": "✦ 在看仓库…",
    "✦ checking your goals…": "✦ 在看你的目标…",
    "✦ making a picture…": "✦ 在做图…",
    "✦ editing the picture…": "✦ 在改图…",
    "✦ checking your texts…": "✦ 在看短信…",
    "✦ checking your email…": "✦ 在看邮件…",
    "✦ remembering that…": "✦ 在记…",
    "✦ reading the text in the image…": "✦ 在认图片里的字…",
    "✦ looking back through our conversations…": "✦ 在翻以前的对话…",
    "✦ researching…": "✦ 在查资料…",
    "✦ reading the page…": "✦ 在读网页…",
    "✦ setting up the schedule…": "✦ 在设定时…",
    "✦ writing the email…": "✦ 在写邮件…",
    "✦ writing the text…": "✦ 在写短信…",
    "✦ checking your tasks…": "✦ 在看任务…",
    "✦ working out where you are…": "✦ 在确定你在哪…",
    "✦ looking at the image…": "✦ 在看图片…",
    "✦ checking the weather…": "✦ 在查天气…",
    "✦ searching arXiv…": "✦ 在搜 arXiv…",
    "✦ asking Horizons…": "✦ 在问 Horizons…",
    "✦ getting the astronomy picture…": "✦ 在取天文图…",
    "✦ searching NASA ADS…": "✦ 在搜 NASA ADS…",
    "✦ converting units…": "✦ 在换算单位…",
    "✦ looking up a constant…": "✦ 在查常数…",
    "Stopped.": "停了。",
    (
        "Something went wrong mid-turn, so I stopped rather than guess. "
        "The details are in Thinking (Ctrl+1). Try again, or rephrase."
    ): (
        "这一轮中间出错了，我停下来了，没有瞎猜。"
        "细节在「思考」（Ctrl+1）。再试一次，或者说得再清楚点。"
    ),
    'Skipped, I was not allowed to read the outside-workspace path you named.': (
        "跳过了。你点名的工作区外面那个路径没有被允许读取。"
    ),
    "On her own": "她自己做的时候",
    "Pause every time": "每次都停下来问",
    (
        "A job you named skips Allow for pictures, files, seeing, "
        "and her window. Mail, texts, deletes, Pay, and programs "
        "still pause."
    ): (
        "你点过名的事，图片、文件、看东西、她的窗口不再问。"
        "邮件、短信、删除、付款和程序还是会停。"
    ),
    "Every checked class shows Allow, even a job you named.": (
        "勾上的每一类都会问，就算是你点过名的。"
    ),
    "Pause if she does this without you naming it. Uncheck to never ask.": (
        "你没点名她就去做的时候停下来问。取消勾选就再也不问。"
    ),
    "A checked class always shows Allow. Uncheck to never ask.": (
        "勾上的类每次都问。取消勾选就再也不问。"
    ),
    (
        "When on, a job you already named does not open Allow, "
        "except mail, texts, deletes, Pay, and programs."
    ): (
        "开着的时候，你已经点名的事不再弹出允许，"
        "除了邮件、短信、删除、付款和程序。"
    ),
    "Off: every checked class shows Allow, even a job you named.": (
        "关掉：勾上的每一类都会问，就算你点过名。"
    ),
    "Each mail or text still needs Allow when this is on.": (
        "开着的时候，每封邮件和每条短信都要允许。"
    ),
    "Running a project program still needs Allow when this is on.": (
        "开着的时候，跑项目里的程序还是要允许。"
    ),
    "Restart Arelis to apply interface scale.": "重启 Arelis 后界面缩放才生效。",
    "Arelis settings test.": "这是阿瑞丽丝的语音测试。",
    "Speech is disabled.": "语音关着。",
    "No playback device.": "没有播放设备。",
    "send a text": "发一条短信",
    "send email": "发邮件",
    "write a file": "写一个文件",
    "edit a file": "改一个文件",
    "delete a file": "删一个文件",
    "keep this note": "记下这条",
    "change a file": "改一个文件",
    "remember this": "记住这个",
    "forget this": "忘掉这个",
    "save this preference": "记下这个偏好",
    "remember this decision": "记住这个决定",
    "save this episode": "记下这一段",
    "change memory": "改记忆",
    "read a page": "读一个网页",
}


def ui_language() -> str:
    return _LANG


def set_ui_language(raw: Any) -> str:
    """Pin the window language. Returns ``en`` or ``zh``."""
    global _LANG
    from arelis.talk_language import normalize

    _LANG = "zh" if normalize(raw) == "zh" else "en"
    return _LANG


def tr(text: str) -> str:
    """Translate one source string. Unknown text comes back unchanged."""
    if _LANG != "zh" or not text:
        return text
    return _ZH.get(text, text)


def _source(current: str, stored: Any) -> str | None:
    if isinstance(stored, str) and stored:
        return stored
    if current in _ZH:
        return current
    reverse = _REVERSE.get(current)
    if reverse:
        return reverse
    return None


_REVERSE: dict[str, str] = {value: key for key, value in _ZH.items() if value != key}


def _apply_text(current: str, stored: Any) -> tuple[str, str] | None:
    source = _source(current, stored)
    if source is None:
        return None
    shown = tr(source) if _LANG == "zh" else source
    return source, shown


def localize(root: Any) -> None:
    """Retitle widgets whose text is in the catalog. Safe to call twice."""
    if root is None:
        return
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QLabel,
        QLineEdit,
        QMenu,
        QPlainTextEdit,
        QPushButton,
        QTabWidget,
        QTextEdit,
        QToolButton,
        QWidget,
    )

    widgets = [root]
    if isinstance(root, QWidget):
        widgets.extend(root.findChildren(QWidget))
    for widget in widgets:
        _localize_one(widget)
        if isinstance(widget, QTabWidget):
            _localize_tabs(widget)
        if isinstance(widget, QComboBox) and widget.objectName() != "LanguageChoice":
            _localize_combo(widget)
        if isinstance(widget, (QLineEdit, QPlainTextEdit, QTextEdit)):
            _localize_placeholder(widget)
        if isinstance(widget, (QLabel, QPushButton, QCheckBox, QToolButton)):
            _localize_prop(widget, "text", widget.text(), widget.setText)
            _localize_prop(widget, "tip", widget.toolTip(), widget.setToolTip)
        elif isinstance(widget, QWidget):
            _localize_prop(widget, "title", widget.windowTitle(), widget.setWindowTitle)
            tip = widget.toolTip()
            if tip:
                _localize_prop(widget, "tip", tip, widget.setToolTip)
    if isinstance(root, QWidget):
        for action in root.findChildren(QAction):
            _localize_prop(action, "text", action.text(), action.setText)
            tip = action.toolTip()
            if tip:
                _localize_prop(action, "tip", tip, action.setToolTip)
        for menu in root.findChildren(QMenu):
            _localize_prop(menu, "title", menu.title(), menu.setTitle)


def _localize_one(widget: Any) -> None:
    name = widget.accessibleName() if hasattr(widget, "accessibleName") else ""
    if not name:
        return
    applied = _apply_text(name, widget.property("_i18n_acc"))
    if applied is None:
        return
    source, shown = applied
    widget.setProperty("_i18n_acc", source)
    if shown != name:
        widget.setAccessibleName(shown)


def _localize_prop(obj: Any, key: str, current: str, setter: Any) -> None:
    if not current:
        return
    prop = f"_i18n_{key}"
    applied = _apply_text(current, obj.property(prop))
    if applied is None:
        return
    source, shown = applied
    obj.setProperty(prop, source)
    if shown != current:
        setter(shown)


def _localize_tabs(tabs: Any) -> None:
    stored = tabs.property("_i18n_tabs")
    sources: list[str] = list(stored) if isinstance(stored, list) else []
    if len(sources) != tabs.count():
        sources = []
        for i in range(tabs.count()):
            current = tabs.tabText(i)
            source = _source(current, None) or current
            sources.append(source)
        tabs.setProperty("_i18n_tabs", sources)
    for i, source in enumerate(sources):
        if i >= tabs.count():
            break
        shown = tr(source) if _LANG == "zh" else source
        if tabs.tabText(i) != shown and source in _ZH:
            tabs.setTabText(i, shown)
        elif _LANG != "zh" and tabs.tabText(i) != source and source in _ZH:
            tabs.setTabText(i, source)


def _localize_combo(combo: Any) -> None:
    stored = combo.property("_i18n_items")
    sources: list[str] = list(stored) if isinstance(stored, list) else []
    if len(sources) != combo.count():
        sources = []
        for i in range(combo.count()):
            data = combo.itemData(i)
            if data in {"en", "zh", "fast", "research"}:
                sources.append("")
                continue
            current = combo.itemText(i)
            sources.append(_source(current, None) or current)
        combo.setProperty("_i18n_items", sources)
    for i, source in enumerate(sources):
        if not source or i >= combo.count() or source not in _ZH:
            continue
        shown = tr(source) if _LANG == "zh" else source
        if combo.itemText(i) != shown:
            combo.setItemText(i, shown)


def _localize_placeholder(edit: Any) -> None:
    current = edit.placeholderText()
    if not current:
        return
    applied = _apply_text(current, edit.property("_i18n_ph"))
    if applied is None:
        return
    source, shown = applied
    edit.setProperty("_i18n_ph", source)
    if shown != current:
        edit.setPlaceholderText(shown)


def cjk_family() -> str | None:
    """A Simplified Chinese face already on this machine, if there is one."""
    from PySide6.QtGui import QFontDatabase

    have = set(QFontDatabase.families())
    for name in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "Noto Sans SC",
        "Source Han Sans SC",
        "SimHei",
        "SimSun",
    ):
        if name in have:
            return name
    return None


_LATIN_BODY = ""
_LATIN_DISPLAY = ""


def apply_language_face(code: str) -> str | None:
    """Point the desk face at a Chinese font, or put the Latin face back.

    Returns the family Qt should use as the application font.
    """
    global _LATIN_BODY, _LATIN_DISPLAY
    from arelis.ui.theme_tokens import FONTS

    if not _LATIN_BODY:
        _LATIN_BODY = FONTS["body"]
        _LATIN_DISPLAY = FONTS["display"]
    if code != "zh":
        FONTS["body"] = _LATIN_BODY
        FONTS["display"] = _LATIN_DISPLAY
        return _quoted_family(_LATIN_BODY)
    family = cjk_family()
    if not family:
        return _quoted_family(_LATIN_BODY)
    stack = f'"{family}", "Segoe UI", sans-serif'
    FONTS["body"] = stack
    FONTS["display"] = stack
    return family


def _quoted_family(stack: str) -> str:
    text = stack.strip()
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 1:
            return text[1:end]
    return "Segoe UI"


def apply_language(window: Any, raw: Any) -> str:
    """Persist nothing. Switch the live window, face, and reply language."""
    code = set_ui_language(raw)
    family = apply_language_face(code)
    try:
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication

        from arelis.ui.theme import app_font, stylesheet
        from arelis.ui.theme_tokens import FONT_PX

        css = stylesheet()
        if window is not None:
            window.setStyleSheet(css)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(css)
            if family:
                font = QFont(family)
                font.setPixelSize(FONT_PX)
                app.setFont(font)
            else:
                app.setFont(app_font())
    except Exception:
        # Styling is cosmetic: a failed font or stylesheet must not stop the
        # language switch, and the text below is still translated.
        family = None
    localize(window)
    _refresh_live_copy(window)
    return code


def _refresh_live_copy(window: Any) -> None:
    if window is None:
        return
    conv = getattr(window, "conversation", None)
    sync = getattr(conv, "_sync_composer_buttons", None)
    if callable(sync):
        sync()
    chat = getattr(window, "chat", None)
    idle = getattr(chat, "empty", None) if chat is not None else None
    if idle is None or not hasattr(idle, "set_sessions"):
        return
    try:
        from arelis.ui.idle_host import sync_idle_voice_mode

        sync_idle_voice_mode(window)
        history = getattr(window, "history", None)
        recent = getattr(history, "recent_sessions", None)
        sessions = recent(3) if callable(recent) else []
        idle.set_sessions(sessions)
        window._idle_ghosts = sessions
    except Exception:
        # The idle screen is a nicety; a failure here must not break the switch.
        return
