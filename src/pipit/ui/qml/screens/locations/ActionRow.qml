// One action in the place pane: icon, label and its key, like a menu item.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

B.AbstractButton {
    id: root
    property string iconName
    property string keys
    property bool danger: false
    property string blockedReason: ""
    implicitHeight: Theme.controlHCompact
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    readonly property color fg: !enabled ? Theme.textFaint : danger ? Theme.negative : Theme.text
    contentItem: RowLayout {
        spacing: Theme.s2
        PIcon { name: root.iconName; size: Theme.iconSm; color: root.enabled && !root.danger ? Theme.textMuted : root.fg }
        PLabel { Layout.fillWidth: true; text: root.text; color: root.fg }
        KeyHint { keys: root.keys; subtle: true }
    }
    leftPadding: Theme.s2
    rightPadding: Theme.s1
    background: Rectangle {
        radius: Theme.radiusMd
        color: !root.enabled ? "transparent"
             : root.down ? Theme.surface3
             : root.hovered ? (root.danger ? Theme.soft(Theme.negative) : Theme.surface2) : "transparent"
        border.width: root.visualFocus ? 2 : 0
        border.color: Theme.accent
    }
    B.ToolTip.visible: hovered && blockedReason !== ""
    B.ToolTip.text: blockedReason
    B.ToolTip.delay: 300
}
