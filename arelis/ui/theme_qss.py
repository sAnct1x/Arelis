from __future__ import annotations

from arelis.ui.theme_tokens import COLORS, FONT_PX, FONTS, GLASS, METRICS, TYPE


def dock_tab_bar_qss() -> str:
    """Opaque ember tabs. Translucent QSS on a Windows QTabBar shows grey through."""
    c = COLORS
    return f"""
    QTabBar {{
        background: transparent;
    }}
    QTabBar::tab {{
        background-color: {c['raised']};
        color: {c['text_dim']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 6px 16px;
        margin-right: 4px;
        min-width: 52px;
        font-size: 12px;
        letter-spacing: {TYPE['track_mid']};
    }}
    QTabBar::tab:selected {{
        color: {c['accent2']};
        background-color: {c['tab_selected']};
        border-color: {c['edge_hot']};
    }}
    QTabBar::tab:hover {{
        color: {c['accent']};
        background-color: {c['hover_strong']};
        border-color: {c['edge_strong']};
    }}
    """


def stylesheet() -> str:
    c = COLORS
    f = FONTS
    m = METRICS
    t = TYPE
    return f"""
    QMainWindow {{
        background: transparent;
        color: {c['text']};
        font-family: {f['body']};
        font-size: {FONT_PX}px;
    }}
    #StageRoot {{
        background: transparent;
        color: {c['text']};
        font-family: {f['body']};
        font-size: {FONT_PX}px;
    }}
    QWidget {{
        color: {c['text']};
        font-family: {f['body']};
        font-size: {FONT_PX}px;
        font-weight: {t['body_weight']};
    }}
    /* Glass panels: painted in code — keep stylesheets transparent */
    #GlassPanel, #GlassDockContent, #ChatStage, #ChatPanelInner, #ComposerInner,
    #FilamentChatGlass, #FilamentChatBody,
    #SettingsGlass, #NotifyInboxGlass, #CalendarWindowGlass, #NotifyCard,
    #DriveStrip, #RoomStrip, #ChatEmpty, #VoidPromptHost,
    #VoidVoiceHost, #GlassDialogGlass {{
        background: transparent;
        border: none;
    }}
    #TitleBar {{
        background-color: {c['veil']};
        border-bottom: 1px solid {c['hairline_faint']};
    }}
    #FloatingTitleBar {{
        background: transparent;
        border: none;
    }}
    #FloatingDockTitle {{
        color: {c['text_dim']};
        font-family: {f['display']};
        font-size: 11px;
        font-weight: 400;
        letter-spacing: {t['track_mid']};
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }}
    #ChromeTitle {{
        color: {c['dim']};
        font-family: {f['mono']};
        font-size: 12px;
        font-weight: 400;
        letter-spacing: {t['track_wide']};
        background: transparent;
        border: none;
        padding: 0 8px 0 0;
    }}
    #ChromeTitle:hover {{
        color: {c['accent']};
        background: transparent;
        border: none;
    }}
    #ChromeViewBtn, #ChromeRoomsBtn, #ChromeSettingsBtn {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 4px 10px;
        color: {c['text_dim']};
        font-size: 12px;
    }}
    #ChromeViewBtn:hover, #ChromeRoomsBtn:hover, #ChromeSettingsBtn:hover {{
        color: {c['accent']};
        background: {c['hover']};
    }}
    #ChromeSpanBtn, #ChromeHandsBtn {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 2px 8px;
        color: {c['text_dim']};
        font-family: {f['mono']};
        font-size: 11px;
        letter-spacing: {t['track_mid']};
    }}
    #ChromeSpanBtn:hover, #ChromeHandsBtn:hover {{
        color: {c['accent']};
        background: {c['hover']};
    }}
    #ChromeSpanBtn:checked, #ChromeHandsBtn:checked {{
        color: {c['accent']};
    }}
    #SettingsDialog, #ContactsInbox, #NotificationsInbox, #SmsChat,
    #GlassDialog, #CalendarWindow {{
        background: {c['plate']};
        border: none;
        color: {c['text']};
    }}
    #SettingsHeading {{
        color: {c['accent2']};
        font-family: {f['display']};
        font-size: 15px;
        font-weight: 400;
        letter-spacing: {t['track_heading']};
        background: transparent;
        padding: 2px 0;
    }}
    #SettingsClose, #SettingsMinimize {{
        background: transparent;
        border: 1px solid {c['edge_soft']};
        border-radius: 8px;
        color: {c['text_dim']};
        font-size: 12px;
    }}
    /* Close is the only chrome button that turns red. Minimize puts the window
       away and is undone by clicking the tray; it does not deserve the same
       alarm, and wearing #SettingsClose is how the SMS tile came to have one. */
    #SettingsClose:hover {{
        background: {c['danger_fill']};
        border-color: {c['danger_edge']};
        color: {c['status_white']};
    }}
    #SettingsMinimize:hover {{
        background: {c['hover']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #SettingsHint, #SettingsNotifyUrl {{
        color: {c['accent2']};
        font-size: 12px;
        background: transparent;
    }}
    #SettingsHint {{
        color: {c['hint']};
    }}
    #SettingsNotifyUrl {{
        color: {c['text']};
        font-family: {f['mono']};
        padding: 10px 12px;
        background: {c['well_soft']};
        border: 1px solid {c['edge_warm']};
        border-radius: 10px;
    }}
    #SettingsPairQr {{
        background: {c['text']};
        border-radius: 12px;
    }}
    #SettingsSection {{
        color: {c['accent2']};
        font-size: 13px;
        font-weight: 600;
        background: transparent;
        padding-top: 6px;
    }}
    #SettingsFieldLabel {{
        color: {c['text']};
        font-size: 13px;
        background: transparent;
        padding-right: 8px;
    }}
    #SettingsTabs {{
        background: transparent;
        border: none;
    }}
    #SettingsTabs::pane {{
        border: 1px solid {c['edge_strong']};
        border-radius: {int(GLASS['radius'])}px;
        background: {c['panel_fill']};
        top: 8px;
        padding: 8px;
    }}
    #SettingsTabBody {{
        background: {c['panel_fill']};
        border: none;
    }}
    #SettingsTabs QTabBar {{
        background: transparent;
    }}
    #SettingsTabs QTabBar::tab {{
        background-color: {c['raised']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text_dim']};
        padding: 6px 14px;
        margin-right: 6px;
        min-width: 52px;
    }}
    #SettingsTabs QTabBar::tab:hover {{
        color: {c['accent']};
        border-color: {c['edge_strong']};
        background: {c['hover']};
    }}
    #SettingsTabs QTabBar::tab:selected {{
        color: {c['accent2']};
        border-color: {c['edge_hot']};
        background: {c['tab_selected']};
    }}
    #SettingsField {{
        min-width: 180px;
    }}
    #SettingsList {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text']};
        outline: none;
        padding: 4px;
    }}
    #SettingsList::item {{
        color: {c['text']};
        padding: 6px 8px;
        border-radius: 6px;
    }}
    #SettingsList::item:selected {{
        background-color: {c['tab_selected']};
        color: {c['accent2']};
    }}
    #SettingsList::item:hover {{
        background-color: {c['hover_strong']};
        color: {c['accent']};
    }}
    #SettingsSlider::groove:horizontal {{
        height: 6px;
        border-radius: 3px;
        background: {c['groove']};
        border: 1px solid {c['edge']};
    }}
    #SettingsSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
        background: {c['accent']};
        border: 1px solid {c['edge_bright']};
    }}
    #SettingsButtons QPushButton {{
        min-width: 72px;
        padding: 6px 16px;
        background-color: {c['raised']};
        color: {c['text']};
        border: 1px solid {c['edge_strong']};
    }}
    #SettingsTabBody QPushButton {{
        background-color: {c['raised']};
        color: {c['text']};
        border: 1px solid {c['edge']};
    }}
    QCheckBox {{
        color: {c['text']};
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border-radius: 4px;
        border: 1px solid {c['edge_mid']};
        background: {c['inset']};
    }}
    QCheckBox::indicator:checked {{
        background: {c['accent']};
        border-color: {c['accent']};
    }}
    #ChromeMin, #ChromeMax, #ChromeClose {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
        color: {c['text_dim']};
        font-size: 11px;
        padding: 0;
    }}
    #ChromeMin:hover, #ChromeMax:hover {{
        background: {c['hover']};
        border-color: {c['rim']};
    }}
    #ChromeClose:hover {{
        background: {c['danger_fill']};
        border-color: {c['danger_edge']};
    }}
    #ChromeMin:pressed, #ChromeMax:pressed {{
        background: {c['sunk_soft']};
    }}
    QToolBar#ChromeToolBar {{
        background: transparent;
        border: none;
        spacing: 0;
        padding: 0;
        margin: 0;
    }}
    #ChromeStack {{
        background: transparent;
        border: none;
    }}
    #ReadinessStrip {{
        background-color: transparent;
        border-bottom: 1px solid {c['hairline_faint']};
    }}
    /* Borderless by design, so these carry colour and nothing else. The
       status rules used to set border-color as well, on a rule that has
       declared `border: none` two lines above. */
    #ReadinessChip {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 1px 8px;
        color: {c['dim']};
        font-size: 10px;
        font-family: {f['mono']};
        letter-spacing: {t['track_mid']};
    }}
    #ReadinessChip[status="ok"] {{
        color: {c['accent']};
    }}
    #ReadinessChip[status="warn"] {{
        color: {c['warn']};
    }}
    #ReadinessChip[status="off"] {{
        color: {c['text_dim']};
    }}
    #ReadinessChip[status="wait"] {{
        color: {c['danger']};
        background-color: {c['danger_fill_soft']};
    }}
    #ReadinessChip[status="wait_dim"] {{
        color: {c['danger']};
        background-color: {c['danger_wash']};
    }}
    /* The notification count on the strip is a button, not a label: it opens
       the mailbox. It wore #ReadinessChip, a rule written for QLabels, so it
       had no pressed or hover state and no edge to aim at. */
    #ReadinessNotifyChip {{
        background-color: {c['chip']};
        border: 1px solid {c['edge_soft']};
        border-radius: 9px;
        padding: 1px 10px;
        min-height: 18px;
        color: {c['warn']};
        font-size: 10px;
        font-family: {f['mono']};
        letter-spacing: {t['track_mid']};
    }}
    #ReadinessNotifyChip:hover {{
        background-color: {c['hover']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #ReadinessNotifyChip:pressed {{
        background-color: {c['sunk_soft']};
    }}
    #NotifyPill {{
        background-color: {c['chip_solid']};
        border: 1px solid {c['edge_mid']};
        border-radius: 10px;
        padding: 4px 12px;
        color: {c['accent']};
        font-size: 11px;
        font-family: {f['mono']};
        letter-spacing: 0.04em;
        min-height: 26px;
    }}
    #NotifyPill:hover {{
        border-color: {c['accent']};
        color: {c['status_white']};
    }}
    #NotifyCardTitle {{
        color: {c['text']};
        font-size: 13px;
        font-family: {f['display']};
        font-weight: 600;
    }}
    #NotifyCardBody {{
        color: {c['text_dim']};
        font-size: 12px;
        font-family: {f['body']};
    }}
    /* The tracking on the idle words lives here and only here. void_idle.py
       also set it through setFont, which is a second author for one property
       and left the label's measured width disagreeing with its painted one. */
    #VoidListenWord {{
        color: {c['dim']};
        font-size: 12px;
        font-family: {f['mono']};
        letter-spacing: {t['track_idle']};
        background: transparent;
        border: none;
    }}
    /* Talk / dictate latched on the empty orbit: amber, not dim grey. */
    #VoidListenWord[live="true"] {{
        color: {c['accent']};
    }}
    #VoidListenWord[wake="true"] {{
        color: {c['accent']};
        font-size: 18px;
        font-family: {f['body']};
        font-weight: {t['body_weight']};
        letter-spacing: 0.01em;
    }}
    #VoidGhostKey {{
        color: {c['dim']};
        font-size: 9px;
        font-family: {f['mono']};
        letter-spacing: {t['track_wide']};
        background: transparent;
        border: none;
    }}
    #VoidGhostValue {{
        color: {c['text_soft']};
        font-size: {FONT_PX}px;
        font-family: {f['body']};
        background: transparent;
        border: none;
    }}
    #VoidReadoutKey {{
        color: {c['text_faint']};
        font-size: 10px;
        font-family: {f['mono']};
        letter-spacing: 0.05em;
        background: transparent;
        border: none;
    }}
    #VoidReadoutValue {{
        color: {c['accent2']};
        font-size: 10px;
        font-family: {f['mono']};
        font-weight: 400;
        letter-spacing: 0.05em;
        background: transparent;
        border: none;
    }}
    #VoidHairline {{
        background: {c['hairline']};
    }}
    #ShortcutsSheet {{
        background-color: {c['bg1']};
    }}
    #ShortcutsTitle {{
        color: {c['text']};
        font-size: 18px;
        font-family: {f['body']};
        letter-spacing: 0.04em;
        background: transparent;
    }}
    #ShortcutsGroup {{
        color: {c['dim']};
        font-size: 9px;
        font-family: {f['mono']};
        letter-spacing: {t['track_wide']};
        background: transparent;
        padding-bottom: 4px;
    }}
    #ShortcutsChord {{
        color: {c['accent2']};
        font-size: 11px;
        font-family: {f['mono']};
        background: transparent;
    }}
    #ShortcutsWhat {{
        color: {c['text_soft']};
        font-size: 12px;
        font-family: {f['body']};
        background: transparent;
    }}
    #ShortcutsAbout {{
        color: {c['dim']};
        font-size: 10px;
        font-family: {f['mono']};
        background: transparent;
        padding-top: 10px;
    }}
    #ReadinessSystems {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 1px 8px;
        color: {c['dim']};
        font-size: 10px;
        font-family: {f['mono']};
        letter-spacing: {t['track_mid']};
    }}
    #ReadinessSystems:hover {{
        color: {c['accent']};
    }}
    #ReadinessSystems[status="ok"] {{
        color: {c['accent']};
    }}
    #ReadinessSystems[status="warn"] {{
        color: {c['warn']};
    }}
    #ReadinessSystems[status="off"] {{
        color: {c['text_dim']};
    }}
    #ReadinessSystems[status="wait"] {{
        color: {c['danger']};
        background-color: {c['danger_fill_soft']};
    }}
    #ReadinessSystems[status="wait_dim"] {{
        color: {c['danger']};
        background-color: {c['danger_wash']};
    }}
    /* A readout that drops down, not a menu. Every row is a fact about a
       subsystem and none of them is a command, so nothing here highlights on
       hover and nothing pretends to be pressable. The previous
       `::item:disabled {{ color: text }}` un-greyed the whole menu, which is
       exactly what made it read as nine dead buttons. */
    #ReadinessSystemsMenu {{
        background-color: {c['menu_fill']};
        border: 1px solid {c['edge']};
        border-radius: 10px;
        padding: 4px;
        color: {c['text']};
        font-size: 12px;
    }}
    #ReadinessSystemsMenu::item {{
        padding: 4px 10px;
        border-radius: 0;
        background: transparent;
        color: {c['text_dim']};
    }}
    #ReadinessSystemsMenu::item:selected {{
        background: transparent;
        color: {c['text_dim']};
    }}
    #ReadinessSystemsMenu::item:disabled {{
        color: {c['text_dim']};
    }}
    #ReadinessSystemsCaption {{
        color: {c['dim']};
        font-size: 9px;
        font-family: {f['mono']};
        letter-spacing: {t['track_idle']};
        background: transparent;
        padding: 4px 10px 2px 10px;
    }}
    /* Contacts is a hole in the glass on both pages — the people list and the
       card read as one layer of the plate, same as the notifications inbox.
       These containers must stay plain: a background here is only ever drawn
       because none of them sets WA_OpaquePaintEvent (see panels/contacts.py). */
    #ContactsPanel, #ContactsStack, #ContactsListPage, #ContactsCardPage,
    #ContactsCardScroll, #ContactsCardViewport, #ContactsFormHost {{
        background: transparent;
        border: none;
    }}
    /* Glass lists — no native inset wells; no H-scroll gutters.
       BrowseList is here rather than on #OutputView, which is the code editor
       rule: filenames were being set in the mono face because the workspace
       dock borrowed the editor's object name to get a transparent background. */
    #HistoryList, #FactsList, #ActiveFactsList, #NotificationsList,
    #ContactsList, #BrowseList, #DeskList {{
        background: transparent;
        border: none;
        outline: none;
        padding: 2px 0;
        color: {c['text']};
        font-size: 12px;
        font-family: {f['body']};
        show-decoration-selected: 1;
    }}
    #BrowseList::item, #HistoryList::item, #FactsList::item,
    #ActiveFactsList::item, #DeskList::item,
    #NotificationsList::item, #ContactsList::item {{
        background: transparent;
        border: none;
        outline: none;
        border-radius: 10px;
        padding: 8px 10px;
        margin: 1px 0;
        color: {c['text']};
    }}
    #FactsList::item, #ActiveFactsList::item {{
        /* Long facts wrap inside the dock instead of clipping mid-word. */
        padding: 8px 10px;
    }}
    #BrowseList::item:hover, #HistoryList::item:hover, #FactsList::item:hover,
    #ActiveFactsList::item:hover, #DeskList::item:hover,
    #NotificationsList::item:hover, #ContactsList::item:hover {{
        background: {c['row_hover']};
        border-color: transparent;
    }}
    #BrowseList::item:selected, #HistoryList::item:selected,
    #FactsList::item:selected, #DeskList::item:selected,
    #ActiveFactsList::item:selected, #NotificationsList::item:selected,
    #ContactsList::item:selected {{
        background: {c['row_selected']};
        border-color: transparent;
        color: {c['text']};
    }}
    /* Seated chat — a lamp, not a brick. Keep the wash when the composer
       has focus; Fusion paints this instead of a native Windows plate. */
    #HistoryList::item:selected,
    #HistoryList::item:selected:active,
    #HistoryList::item:selected:!active {{
        background: {c['row_selected']};
        border: none;
        color: {c['text']};
    }}
    #InstrumentTitle {{
        color: {c['dim']};
        font-size: 11px;
        font-weight: 400;
        letter-spacing: {t['track_mid']};
        background: transparent;
        padding: 0 0 2px 2px;
    }}
    #CalendarTabs {{
        background: transparent;
        border: none;
    }}
    #CalendarTabs::pane {{
        border: none;
        background: transparent;
        top: 6px;
        padding: 0;
    }}
    #CalendarTabBody, #CalendarTasksPage, #CalendarJobsPage, #CalendarEventSheet {{
        background: transparent;
        border: none;
    }}
    #CalendarTabs QTabBar {{
        background: transparent;
    }}
    #CalendarTabs QTabBar::tab {{
        background-color: {c['raised']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text_dim']};
        padding: 6px 14px;
        margin-right: 6px;
        min-width: 52px;
    }}
    #CalendarTabs QTabBar::tab:hover {{
        color: {c['accent']};
        border-color: {c['edge_strong']};
        background: {c['hover']};
    }}
    #CalendarTabs QTabBar::tab:selected {{
        color: {c['accent2']};
        border-color: {c['edge_hot']};
        background: {c['tab_selected']};
    }}
    #CalendarMonthTitle {{
        color: {c['accent2']};
        font-size: 15px;
        font-family: {f['display']};
        letter-spacing: 0.04em;
        background: transparent;
        padding: 0 8px;
    }}
    #CalendarDate, #CalendarTime {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text']};
        padding: 2px 8px;
        font-size: 12px;
        font-family: {f['body']};
        min-height: {m['row'] - 8}px;
    }}
    #CalendarDate:focus, #CalendarTime:focus {{
        border: 1px solid {c['accent']};
        background-color: {c['well_focus']};
    }}
    #CalendarAgendaList, #CalendarTaskList, #CalendarJobList {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text']};
        outline: none;
        padding: 4px;
    }}
    #CalendarAgendaList::item, #CalendarTaskList::item, #CalendarJobList::item {{
        color: {c['text']};
        padding: 6px 8px;
        border-radius: 6px;
    }}
    #CalendarAgendaList::item:selected,
    #CalendarTaskList::item:selected,
    #CalendarJobList::item:selected {{
        background-color: {c['tab_selected']};
        color: {c['accent2']};
    }}
    #CalendarAgendaList::item:hover, #CalendarTaskList::item:hover, #CalendarJobList::item:hover {{
        background-color: {c['hover_strong']};
        color: {c['accent']};
    }}
    #CalendarTaskTitle {{
        color: {c['text']};
        background: transparent;
        font-size: {FONT_PX}px;
        font-family: {f['body']};
    }}
    #CalendarJobPrompt {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text']};
        padding: 6px 8px;
        font-size: {FONT_PX}px;
        font-family: {f['body']};
    }}
    #CalendarDelete {{
        background-color: {c['danger_fill_soft']};
        border: 1px solid {c['danger_edge_soft']};
        color: {c['danger']};
    }}
    #CalendarDelete:hover {{
        background-color: {c['danger_fill']};
        border-color: {c['danger_edge']};
        color: {c['danger']};
    }}
    #CalendarEventSheet QLabel, #CalendarJobsPage QLabel {{
        color: {c['text_dim']};
        background: transparent;
    }}
    #InstrumentHint {{
        color: {c['hint']};
        font-size: 12px;
        font-family: {f['body']};
        background: transparent;
        padding: 0 0 2px 2px;
        border: none;
    }}
    #HistoryEmpty, #DeskEmpty {{
        color: {c['text_muted']};
        font-size: 12px;
        font-family: {f['body']};
        background: transparent;
        padding: 28px 12px 12px 12px;
        border: none;
    }}
    #DeskHint {{
        color: {c['hint']};
        font-size: 12px;
        font-family: {f['body']};
        background: transparent;
        padding: 0 2px 2px 2px;
        border: none;
    }}
    #DeskPreview {{
        font-family: {f['body']};
        font-size: 13px;
        background-color: transparent;
        border: none;
        color: {c['text']};
        padding: 8px 2px;
    }}
    #SmsChatScroll, #SmsChatThread {{
        background: {c['panel_fill']};
        border: none;
    }}
    #SmsBubbleIn {{
        color: {c['text']};
        font-size: {FONT_PX}px;
        background: {c['raised']};
        border: 1px solid {c['edge']};
        border-radius: 10px;
        padding: 8px 10px;
    }}
    #SmsBubbleOut {{
        color: {c['accent2']};
        font-size: {FONT_PX}px;
        background: {c['raised_warm']};
        border: 1px solid {c['edge_mid']};
        border-radius: 10px;
        padding: 8px 10px;
    }}
    #SmsBubbleSys {{
        color: {c['text_dim']};
        font-size: 12px;
        background: transparent;
        border: none;
        padding: 4px 2px;
    }}
    #SmsBubbleIn QLabel, #SmsBubbleOut QLabel {{
        background: transparent;
        border: none;
        color: inherit;
        padding: 0;
    }}
    #SmsBubbleIn a, #SmsBubbleOut a {{
        color: {c['accent']};
        text-decoration: underline;
    }}
    #SmsPhotoChip {{
        color: {c['text']};
        font-size: 11px;
        background: {c['card_fill']};
        border: 1px solid {c['edge']};
        border-radius: 10px;
        padding: 4px 10px;
    }}
    #SmsBubbleImage {{
        background: transparent;
        border: none;
        padding: 0;
    }}
    #NotificationDetail {{
        color: {c['text']};
        font-size: {FONT_PX}px;
        font-family: {f['body']};
        background: {c['raised']};
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 10px 12px;
    }}
    #InstrumentSearch {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 5px 8px;
        color: {c['text']};
        font-size: 12px;
        font-family: {f['body']};
        selection-background-color: {c['selection']};
    }}
    #InstrumentSearch:focus {{
        border: 1px solid {c['accent']};
        background-color: {c['well_focus']};
    }}
    /* A picker beside a filled field has to be a filled field too, or it reads
       as an unstyled hole in the row — which is what the workspace project
       combo and the camera device combo were. Same well as #InstrumentSearch
       plus the drop-down chrome a QLineEdit rule cannot give a QComboBox. */
    #InstrumentCombo {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 2px 22px 2px 8px;
        color: {c['text']};
        font-size: 12px;
        font-family: {f['body']};
        min-height: {m['row'] - 8}px;
    }}
    #InstrumentCombo:hover {{
        border-color: {c['edge_mid']};
        background-color: {c['well_focus']};
    }}
    #InstrumentCombo:focus, #InstrumentCombo:on {{
        border: 1px solid {c['accent']};
        background-color: {c['well_focus']};
    }}
    #InstrumentCombo:disabled {{
        color: {c['text_dim']};
        border-color: {c['edge_soft']};
    }}
    #InstrumentCombo::drop-down {{
        border: none;
        width: 18px;
        subcontrol-origin: padding;
        subcontrol-position: center right;
    }}
    /* The row is 28px including the 1px border. min/max here are the
       content box — padding used to steal another 8px and land on 26. */
    #InstrumentAction {{
        background-color: {c['button_fill']};
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 0px 10px;
        color: {c['accent2']};
        font-size: 11px;
        font-family: {f['mono']};
        font-weight: 400;
        min-height: {m['row'] - 2}px;
        max-height: {m['row'] - 2}px;
    }}
    #InstrumentAction:hover {{
        background-color: {c['button_hover']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #InstrumentAction:pressed {{
        background-color: {c['sunk']};
    }}
    /* Square siblings of #InstrumentAction. Padding 0 so the glyph sits
       in the same 28px row without the word-button's horizontal inset. */
    QToolButton#InstrumentIcon {{
        background-color: {c['button_fill']};
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 0px;
        color: {c['accent2']};
        min-width: {m['row'] - 2}px;
        max-width: {m['row'] - 2}px;
        min-height: {m['row'] - 2}px;
        max-height: {m['row'] - 2}px;
    }}
    QToolButton#InstrumentIcon:hover {{
        background-color: {c['button_hover']};
        border-color: {c['accent']};
    }}
    QToolButton#InstrumentIcon:pressed {{
        background-color: {c['sunk']};
    }}
    QDockWidget {{
        color: {c['text_dim']};
        background: transparent;
        border: none;
        titlebar-close-icon: none;
    }}
    QDockWidget::title {{
        background: transparent;
        border: none;
        padding: 0px;
        margin: 0px;
        height: 0px;
    }}
    QDockWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QMainWindow::separator {{
        background: {c['hairline_mid']};
        width: 1px;
        height: 1px;
    }}
    QDockWidget QTabBar, #DockTabBar {{
        background: transparent;
    }}
    QDockWidget QTabBar::tab, #DockTabBar::tab {{
        background-color: {c['raised']};
        color: {c['text_dim']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 5px 14px;
        font-size: 11px;
        letter-spacing: {t['track_mid']};
        margin-right: 4px;
    }}
    QDockWidget QTabBar::tab:selected, #DockTabBar::tab:selected {{
        color: {c['accent2']};
        background-color: {c['tab_selected']};
        border-color: {c['edge_hot']};
    }}
    QDockWidget QTabBar::tab:hover, #DockTabBar::tab:hover {{
        color: {c['accent']};
        background-color: {c['hover_strong']};
        border-color: {c['edge_strong']};
    }}
    QTextEdit, QPlainTextEdit {{
        background-color: transparent;
        border: none;
        border-radius: 10px;
        padding: 10px;
        selection-background-color: {c['selection']};
        font-family: {f['body']};
    }}
    #ChatView {{
        background-color: transparent;
        border: none;
        padding: 12px 28px 16px 18px;
        font-size: 15px;
        font-weight: {t['body_weight']};
        color: {c['text']};
    }}
    #ThinkingView {{
        color: {c['thinking']};
        font-family: {f['body']};
        font-size: {FONT_PX}px;
        font-weight: {t['body_weight']};
        background-color: transparent;
        border: none;
        padding: 4px 2px;
    }}
    #ThinkingFooter {{
        color: {c['dim']};
        font-family: {f['body']};
        font-size: 11px;
        background: transparent;
        padding: 0 2px 4px 2px;
        border: none;
    }}
    #Editor {{
        font-family: {f['mono']};
        font-size: 12px;
        background-color: transparent;
        border: none;
        border-radius: 0;
        color: {c['text']};
        padding: 8px 2px;
    }}
    #OutputView {{
        font-family: {f['mono']};
        font-size: 12px;
        background-color: transparent;
        border: none;
        border-top: 1px solid {c['hairline_faint']};
        border-radius: 0;
        color: {c['text_dim']};
        padding: 6px 2px;
    }}
    #WorkspaceImageWell {{
        border: none;
        border-radius: 0;
        color: {c['text_dim']};
        background: transparent;
    }}
    #ComposerInput {{
        background-color: transparent;
        border: none;
        padding: 6px 4px;
        border-radius: 0;
        color: {c['text']};
        font-size: 16px;
        font-weight: {t['body_weight']};
        letter-spacing: 0.01em;
        selection-background-color: {c['selection']};
    }}
    #ComposerInput:focus {{
        border: none;
    }}
    #ComposerInput::placeholder {{
        color: {c['text_muted']};
    }}
    #VoidIdlePlaceholder {{
        color: {c['text_muted']};
        font-size: 18px;
        font-family: {f['body']};
        font-weight: {t['body_weight']};
        letter-spacing: 0.01em;
        background: transparent;
        border: none;
    }}
    #FilamentFloat {{
        background: transparent;
        border: none;
        color: {c['accent']};
        font-size: 16px;
        font-family: {f['body']};
        font-weight: {t['body_weight']};
        letter-spacing: {t['track_mid']};
        padding: 2px 6px;
    }}
    #FilamentFloat:hover {{
        color: {c['accent2']};
    }}
    #FilamentFloat[live="true"] {{
        color: {c['accent2']};
    }}
    #FilamentBead {{
        background: transparent;
        border: none;
        padding: 0;
    }}
    QLineEdit {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 5px 10px;
        color: {c['text']};
        selection-background-color: {c['selection']};
    }}
    QLineEdit:focus {{
        border: 1px solid {c['accent']};
    }}
    QPushButton {{
        background-color: {c['raised']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 4px 12px;
        color: {c['text']};
        font-size: 11px;
        font-family: {f['mono']};
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {c['button_hover_soft']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    QPushButton:pressed {{
        background-color: {c['sunk_soft']};
    }}
    #SendButton, #AttachButton, #MicButton, #ConversationButton {{
        background: transparent;
        border: none;
        border-radius: 0;
        padding: 3px;
    }}
    #SendButton:hover, #AttachButton:hover,
    #MicButton:hover, #ConversationButton:hover {{
        background: transparent;
        border: none;
        color: {c['accent']};
    }}
    #AttachButton:disabled, #MicButton:disabled, #ConversationButton:disabled {{
        border: none;
        background: transparent;
    }}
    /* Live capture is the one state that leaves the accent palette, because it
       is the one state where the user has to notice without looking for it. */
    #MicButton:checked, #ConversationButton:checked {{
        background: {c['live_fill']};
        border: 1px solid {c['status_amber']};
    }}
    #StopButton {{
        background: transparent;
        border: 1px solid {c['danger_edge_soft']};
        border-radius: 8px;
        padding: 2px 10px;
        color: {c['danger']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #StopButton:hover {{
        background: {c['danger_fill_soft']};
        border-color: {c['danger']};
    }}
    #RoomName {{
        color: {c['accent2']};
        font-family: {f['body']};
        font-size: 12px;
        background: transparent;
        letter-spacing: 0.04em;
    }}
    #RoomDetail {{
        color: {c['text_muted']};
        font-family: {f['body']};
        font-size: 12px;
        background: transparent;
    }}
    #RoomLeaveButton, #RoomWorldButton {{
        background: transparent;
        border: none;
        border-radius: 0;
        padding: 2px 6px;
        color: {c['dim']};
        font-family: {f['body']};
        font-size: 12px;
    }}
    #RoomLeaveButton:hover, #RoomWorldButton:hover {{
        background: transparent;
        color: {c['accent']};
    }}
    #ComposerClear {{
        background: transparent;
        border: none;
        padding: 0;
    }}
    #ComposerClear:hover {{
        background: transparent;
    }}
    #WorldChooserHands, #WorldChooserSolar,
    #WorldPauseResume, #WorldPauseSettings, #WorldPauseExit {{
        background: {c['bg2']};
        border: 1px solid {c['edge_mid']};
        border-radius: 10px;
        padding: 10px 18px;
        color: {c['text']};
        font-family: {f['mono']};
        font-size: 14px;
        min-height: 44px;
    }}
    #WorldChooserHands:hover, #WorldChooserSolar:hover,
    #WorldPauseResume:hover, #WorldPauseExit:hover {{
        background: {c['button_hover_soft']};
        color: {c['accent']};
        border-color: {c['accent']};
    }}
    #WorldPauseSettings:disabled {{
        color: {c['text_dim']};
    }}
    #DriveBrand {{
        color: {c['accent']};
        font-family: {f['mono']};
        font-size: 11px;
        background: transparent;
    }}
    #DriveStatus {{
        color: {c['text_dim']};
        font-family: {f['mono']};
        font-size: 11px;
        background: transparent;
    }}
    /* Pause was the one cyan control in an amber application. It is the quiet
       half of a pair with #GoButton, so it is the same amber a step down in
       weight rather than a different colour entirely. */
    #PauseButton {{
        background: transparent;
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 2px 10px;
        color: {c['hint']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #PauseButton:hover {{
        background: {c['live_fill']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #GoButton {{
        background: transparent;
        border: 1px solid {c['edge_strong']};
        border-radius: 8px;
        padding: 2px 10px;
        color: {c['accent']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #GoButton:hover {{
        background: {c['live_fill']};
        border-color: {c['accent']};
    }}
    #ConfirmCard {{
        background-color: {c['card_fill']};
        border: 1px solid {c['rim']};
        border-radius: 10px;
    }}
    #ConfirmSummary {{
        color: {c['text']};
        font-family: {f['mono']};
        font-size: 12px;
        background: transparent;
    }}
    #ConfirmDetail {{
        color: {c['text']};
        font-family: {f['mono']};
        font-size: 12px;
        background-color: {c['inset']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 6px;
    }}
    #ConfirmNote {{
        color: {c['danger']};
        font-size: 11px;
        background: transparent;
    }}
    #ConfirmAllowTurn {{
        color: {c['text_dim']};
        font-size: 11px;
        spacing: 6px;
    }}
    #ConfirmAllow, #FactApprove, #DialogConfirm {{
        min-width: 72px;
        background-color: {c['selection']};
        border: 1px solid {c['accent']};
        color: {c['text']};
        font-family: {f['body']};
        font-size: 12px;
        font-weight: 600;
    }}
    #ConfirmAllow:hover, #FactApprove:hover, #DialogConfirm:hover {{
        background-color: {c['button_hover_hot']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    /* A destructive confirm is still an amber button — the app does not have a
       red one and inventing it here would make Delete louder than Stop. The
       note above it carries the warning, in {c['danger']}. */
    #DialogConfirm[destructive="true"] {{
        background-color: {c['danger_fill_soft']};
        border-color: {c['danger_edge']};
        color: {c['text']};
    }}
    #DialogConfirm[destructive="true"]:hover {{
        background-color: {c['danger_fill']};
        border-color: {c['danger']};
        color: {c['status_white']};
    }}
    #ConfirmSkip, #FactReject, #FactRejectAll, #FactForget, #DialogCancel {{
        color: {c['text_dim']};
        font-family: {f['mono']};
        font-size: 11px;
        font-weight: 500;
        background-color: transparent;
        border: 1px solid {c['edge']};
    }}
    #ConfirmSkip:hover, #FactReject:hover, #FactRejectAll:hover,
    #FactForget:hover, #DialogCancel:hover {{
        color: {c['text']};
        border-color: {c['edge_strong']};
        background-color: {c['hover_soft']};
    }}
    #DialogCancel:focus {{
        border-color: {c['accent']};
        color: {c['text']};
    }}
    QMenu::item {{
        padding: 6px 14px;
        border-radius: 6px;
        min-height: 22px;
    }}
    QMenu::separator {{
        height: 1px;
        background: {c['edge']};
        margin: 6px 8px;
    }}
    QComboBox {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 0px 18px 0px 8px;
        color: {c['dim']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #RoleSelect {{
        min-width: 78px;
        max-width: 96px;
        padding: 0px 14px 0px 8px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 14px;
        subcontrol-origin: padding;
        subcontrol-position: center right;
    }}
    QComboBox::down-arrow {{
        width: 8px;
        height: 8px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['menu_fill']};
        selection-background-color: {c['hover_strong']};
        selection-color: {c['text']};
        color: {c['text']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        outline: none;
        padding: 4px;
    }}
    QComboBox QAbstractItemView::item {{
        padding: 6px 10px;
        min-height: 22px;
        border-radius: 6px;
        color: {c['text']};
        background: transparent;
    }}
    QComboBox QAbstractItemView::item:selected,
    QComboBox QAbstractItemView::item:hover {{
        background: {c['hover_strong']};
        color: {c['text']};
    }}
    #ComboPopup {{
        background-color: {c['menu_fill']};
        border: 1px solid {c['edge']};
        border-radius: 10px;
    }}
    /* Opaque track. The global vertical bar is transparent and reads as a
       black gutter on the unstyled popup frame. */
    QComboBox QAbstractItemView QScrollBar:vertical {{
        background: {c['menu_fill']};
        width: 8px;
        margin: 4px 2px 4px 0;
        border: none;
    }}
    QComboBox QAbstractItemView QScrollBar::handle:vertical {{
        background: {c['edge_mid']};
        border-radius: 3px;
        min-height: 20px;
    }}
    #RoleSelect QAbstractItemView {{
        min-width: 88px;
    }}
    #RoleSelect QAbstractItemView QScrollBar:vertical {{
        width: 0px;
        background: {c['menu_fill']};
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['edge_mid']};
        border-radius: 4px;
        min-height: 28px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 0px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: transparent;
        height: 0px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
        height: 0;
    }}
    QMenu {{
        background-color: {c['menu_fill']};
        border: 1px solid {c['edge']};
        border-radius: 10px;
        padding: 4px;
        color: {c['text']};
    }}
    QMenu::item:selected {{
        background: {c['hover_strong']};
        border-radius: 6px;
    }}
    QSplitter::handle {{
        background-color: transparent;
        width: 1px;
        height: 1px;
    }}
    QToolTip {{
        background-color: {c['bg2']};
        color: {c['text']};
        border: 1px solid {c['edge']};
        padding: 6px 8px;
    }}
    /* Composer attachment rail. Tiles paint themselves; QSS must not plate
       them with card_fill — that read as a full-width grey slab on Windows. */
    #AttachBar, #AttachBarScroll, #AttachBarInner, AttachmentTile {{
        background: transparent;
        border: none;
    }}
    #AttachmentTileRemove {{
        color: {c['text']};
        font-size: 12px;
        border: none;
        background: transparent;
        padding: 0;
    }}
    #AttachmentTileRemove:hover {{
        color: {c['accent']};
        background: transparent;
    }}
    #AttachmentTileRemoveOnPhoto {{
        color: {c['text']};
        font-size: 12px;
        border: none;
        background: {c['code_fill']};
        border-radius: 8px;
        padding: 0;
    }}
    #AttachmentTileRemoveOnPhoto:hover {{
        color: {c['accent']};
        background: {c['plate']};
    }}
    #AttachBarScroll QScrollBar:horizontal {{
        background: transparent;
        height: 4px;
        margin: 0;
        border: none;
    }}
    #AttachBarScroll QScrollBar::handle:horizontal {{
        background: {c['rim']};
        min-width: 24px;
        border-radius: 2px;
    }}
    #AttachBarScroll QScrollBar::add-line:horizontal,
    #AttachBarScroll QScrollBar::sub-line:horizontal {{
        width: 0;
        height: 0;
        background: transparent;
    }}
    #DropOverlay {{
        background: {c['scrim']};
        border-radius: {int(GLASS['radius'])}px;
    }}
    #DropOverlayTitle {{
        color: {c['accent']};
        background: transparent;
        font-size: 18px;
    }}
    #DropOverlayHint {{
        color: {c['text_dim']};
        background: transparent;
        font-size: 12px;
    }}
    #ChatProgress {{
        color: {c['status_amber']};
        background: transparent;
        border: none;
        border-bottom: 1px solid {c['hairline_faint']};
        font-size: {FONT_PX}px;
        padding: 10px 8px 8px 8px;
        letter-spacing: 0.04em;
        text-decoration: none;
    }}
    #ChatProgress:hover {{
        color: {c['accent2']};
        border-bottom: 1px solid {c['hairline_mid']};
        text-decoration: none;
    }}
    /* Frameless in-app dialogs: first run, confirms, the update prompt. */
    #DialogHeading, #GlassDialogHeading {{
        color: {c['accent2']};
        font-family: {f['display']};
        font-size: 15px;
        font-weight: 400;
        letter-spacing: {t['track_heading']};
        background: transparent;
        padding: 2px 0;
    }}
    #DialogBody {{
        color: {c['text']};
        font-size: {FONT_PX}px;
        background: transparent;
    }}
    #DialogNote {{
        color: {c['text_dim']};
        font-size: 11px;
        background: transparent;
    }}
    #DialogWarning {{
        color: {c['danger']};
        font-size: 11px;
        background: transparent;
    }}
    #DialogPath {{
        color: {c['accent2']};
        font-family: {f['mono']};
        font-size: 12px;
        background: {c['well_soft']};
        border: 1px solid {c['edge_warm']};
        border-radius: 8px;
        padding: 10px 12px;
    }}
    #DialogProgress {{
        background: {c['inset']};
        border: 1px solid {c['edge']};
        border-radius: 6px;
        height: 10px;
        text-align: center;
        color: transparent;
    }}
    #DialogProgress::chunk {{
        background: {c['accent']};
        border-radius: 5px;
    }}
    #SetupChoice {{
        color: {c['text']};
        font-size: {FONT_PX}px;
        spacing: 10px;
        padding: 4px 0;
        background: transparent;
    }}
    #SetupChoice::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 7px;
        border: 1px solid {c['edge_mid']};
        background: {c['inset']};
    }}
    #SetupChoice::indicator:checked {{
        background: {c['accent']};
        border-color: {c['edge_hot']};
    }}
    #DialogButton, #DialogPrimary {{
        background: {c['button_fill']};
        color: {c['text']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 6px 18px;
        font-size: {FONT_PX}px;
    }}
    #DialogButton:hover, #DialogPrimary:hover {{
        background: {c['button_hover']};
        border-color: {c['edge_mid']};
    }}
    #DialogPrimary {{
        background: {c['raised_warm']};
        color: {c['accent2']};
        border-color: {c['edge_strong']};
    }}
    #DialogPrimary:hover {{
        background: {c['button_hover_hot']};
        border-color: {c['edge_hot']};
    }}
    /* The destroying answer is the one that has to look like it. Colour is the
       only warning left once the safe answer holds focus. */
    #DialogButton[tone="danger"] {{
        background: {c['danger_fill_soft']};
        color: {c['danger']};
        border-color: {c['danger_edge_soft']};
    }}
    #DialogButton[tone="danger"]:hover {{
        background: {c['danger_fill']};
        border-color: {c['danger_edge']};
    }}
    #DialogButton:focus, #DialogPrimary:focus {{
        border-color: {c['edge_hot']};
    }}
    """
