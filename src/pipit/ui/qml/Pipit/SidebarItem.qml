// One navigation entry: icon and title, with the shortcut in a tooltip. Selected = 14%
// accent tint plus a 2px left accent bar; hover = 6% tint. Collapsed shows the icon.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts

B.AbstractButton {
    id: root
    property string iconName
    property string shortcut
    property bool selected: false
    property bool collapsed: false
    implicitHeight: Theme.controlH + Theme.s1
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    Accessible.name: text

    background: Rectangle {
        radius: Theme.radiusMd
        color: root.selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
             : root.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface)
             : "transparent"
        border.width: root.visualFocus ? 2 : 0
        border.color: Theme.accent
        Rectangle {
            visible: root.selected
            width: 2
            radius: 1
            color: Theme.accent
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.topMargin: Theme.s1 + 2
            anchors.bottomMargin: Theme.s1 + 2
        }
    }
    contentItem: RowLayout {
        spacing: Theme.s3
        PIcon {
            Layout.leftMargin: root.collapsed ? (root.width - Theme.iconMd) / 2 : Theme.s3
            name: root.iconName
            color: root.selected ? Theme.accent : root.hovered ? Theme.text : Theme.textMuted
        }
        PLabel {
            visible: !root.collapsed
            Layout.fillWidth: true
            text: root.text
            kind: root.selected ? "strong" : "body"
            color: root.selected || root.hovered ? Theme.text : Theme.textMuted
        }
    }
    B.ToolTip.visible: hovered
    B.ToolTip.text: collapsed ? text + "  " + shortcut : shortcut
    B.ToolTip.delay: collapsed ? 300 : 700
}
