"""
公共样式常量 — 全局复用的 Qt 样式表片段
"""

# 统一滚动条样式（垂直 + 水平）
SCROLLBAR_STYLE = """
    QScrollBar:vertical {
        background: transparent;
        width: 6px;
        margin: 0;
    }
    QScrollBar::handle:vertical {
        background: rgba(0,0,0,0.18);
        border-radius: 3px;
        min-height: 30px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(0,0,0,0.3);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

    QScrollBar:horizontal {
        background: transparent;
        height: 6px;
        margin: 0;
    }
    QScrollBar::handle:horizontal {
        background: rgba(0,0,0,0.18);
        border-radius: 3px;
        min-width: 30px;
    }
    QScrollBar::handle:horizontal:hover {
        background: rgba(0,0,0,0.3);
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
"""

# QDateEdit 样式（不含日历弹窗，日历样式单独设）
DATE_EDIT_STYLE = """
    QDateEdit {
        background: #ffffff;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 6px 12px;
        padding-right: 32px;
        color: #374151;
    }
    QDateEdit:focus { border-color: #3B82F6; }
    QDateEdit::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 30px;
        border: none;
        border-left: 1px solid #D1D5DB;
        border-top-right-radius: 8px;
        border-bottom-right-radius: 8px;
        background: #F9FAFB;
    }
    QDateEdit::drop-down:hover {
        background: #EFF6FF;
    }
    QDateEdit::down-arrow {
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid #6B7280;
    }
    QDateEdit::down-arrow:hover {
        border-top-color: #3B82F6;
    }
"""

# QCalendarWidget 样式 — 必须直接 set 到 calendarWidget() 实例上
# （QDateEdit 的 popup 日历是独立窗口，不继承父级样式表）
CALENDAR_STYLE = """
    QCalendarWidget {
        background: #ffffff;
    }
    QCalendarWidget QWidget#qt_calendar_navigationbar {
        background: #F3F4F6;
    }
    QCalendarWidget QToolButton {
        color: #374151;
        background: #ffffff;
        border: 1px solid #D1D5DB;
        border-radius: 4px;
        padding: 4px 10px;
        min-width: 24px;
        min-height: 24px;
    }
    QCalendarWidget QToolButton:hover {
        background: #EFF6FF;
        border-color: #3B82F6;
        color: #1D4ED8;
    }
    QCalendarWidget QToolButton#qt_calendar_prevmonth,
    QCalendarWidget QToolButton#qt_calendar_nextmonth {
        min-width: 30px;
        min-height: 26px;
        font-size: 14pt;
        font-weight: bold;
        color: #374151;
        background: #ffffff;
        border: 1px solid #D1D5DB;
        border-radius: 4px;
    }
    QCalendarWidget QToolButton#qt_calendar_prevmonth:hover,
    QCalendarWidget QToolButton#qt_calendar_nextmonth:hover {
        background: #EFF6FF;
        border-color: #3B82F6;
    }
    QCalendarWidget QToolButton#qt_calendar_monthbutton {
        min-width: 90px;
        padding: 4px 14px;
    }
    QCalendarWidget QToolButton#qt_calendar_yearbutton {
        min-width: 60px;
        padding: 4px 14px;
    }
    QCalendarWidget QSpinBox {
        background: #ffffff;
        border: 1px solid #D1D5DB;
        border-radius: 4px;
        padding: 2px 6px;
        color: #374151;
        min-width: 50px;
    }
    QCalendarWidget QAbstractItemView {
        background: #ffffff;
        color: #374151;
        selection-background-color: #3B82F6;
        selection-color: #ffffff;
        outline: none;
        border: none;
    }
    QCalendarWidget QAbstractItemView:enabled {
        color: #374151;
    }
    QCalendarWidget QAbstractItemView:disabled {
        color: #D1D5DB;
    }
"""

# ComboBox 通用样式
COMBO_STYLE = """
    QComboBox {
        background: #ffffff;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 6px 12px;
        color: #374151;
    }
    QComboBox:hover { border-color: #3B82F6; }
    QComboBox::drop-down { border: none; width: 20px; }
    QComboBox QAbstractItemView {
        background: #ffffff;
        border: 1px solid #E5E7EB;
        color: #374151;
        selection-background-color: #3B82F6;
        selection-color: #ffffff;
    }
"""

# QLineEdit 通用样式
INPUT_STYLE = """
    QLineEdit {
        background: #ffffff;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 6px 12px;
        color: #374151;
    }
    QLineEdit:focus { border-color: #3B82F6; }
"""

# QCheckBox 通用样式 — 白底上可见
CHECKBOX_STYLE = """
    QCheckBox {
        color: #374151;
        background: transparent;
        spacing: 6px;
    }
    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 2px solid #D1D5DB;
        border-radius: 4px;
        background: #ffffff;
    }
    QCheckBox::indicator:hover {
        border-color: #3B82F6;
    }
    QCheckBox::indicator:checked {
        background: #3B82F6;
        border-color: #3B82F6;
        image: none;
    }
"""

# QDoubleSpinBox 通用样式（无箭头）
SPINBOX_STYLE = """
    QDoubleSpinBox {
        background: #ffffff;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 6px 12px;
        color: #374151;
    }
    QDoubleSpinBox:focus { border-color: #3B82F6; }
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
        width: 0; height: 0; border: none;
    }
"""

# QTableWidget 通用样式（含排序箭头、去焦点框、滚动条）
TABLE_STYLE = """
    QTableWidget {
        background: #ffffff;
        border: none;
        border-radius: 10px;
        gridline-color: transparent;
        alternate-background-color: #FAFBFC;
        outline: none;
    }
    QTableWidget::item {
        padding: 10px 14px;
        color: #374151;
        border: none;
        outline: none;
    }
    QTableWidget::item:selected {
        background-color: #EFF6FF;
        color: #1D4ED8;
    }
    QHeaderView::section {
        background: #F9FAFB;
        border: none;
        padding: 10px 14px;
        font-weight: 600;
        color: #6B7280;
    }
    QHeaderView::down-arrow {
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid #6B7280;
        width: 0;
        height: 0;
        subcontrol-position: center right;
        subcontrol-origin: padding;
        padding-right: 6px;
    }
    QHeaderView::up-arrow {
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 5px solid #6B7280;
        width: 0;
        height: 0;
        subcontrol-position: center right;
        subcontrol-origin: padding;
        padding-right: 6px;
    }
""" + SCROLLBAR_STYLE
