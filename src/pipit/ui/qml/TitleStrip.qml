// Top strip: back, current screen title, list status, and the command-palette field.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

Rectangle {
    id: root
    signal paletteRequested()
    implicitHeight: Theme.titleStripH
    color: Theme.bg

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.s3
        anchors.rightMargin: Theme.windowPad
        spacing: Theme.s3

        PIconButton {
            iconName: "chevron-left"
            tip: qsTr("Back") + "  Alt+Left"
            enabled: shell.canGoBack
            onClicked: shell.back()
        }
        PLabel {
            kind: "title"
            text: shell.screens[shell.currentIndex].title
        }
        StatusChip {
            kind: !app.hasList ? "neutral" : app.readOnly ? "warning" : "info"
            text: !app.hasList ? qsTr("No list open")
                : app.readOnly ? qsTr("%1 · read-only").arg(app.listName) : app.listName
        }
        Item { Layout.fillWidth: true }

        // Looks like a search field; opens the palette (Ctrl+K).
        B.AbstractButton {
            id: search
            Layout.preferredWidth: Theme.grid(360)
            Layout.preferredHeight: Theme.controlHCompact
            hoverEnabled: true
            focusPolicy: Qt.TabFocus
            Accessible.name: qsTr("Search or run a command")
            onClicked: root.paletteRequested()
            background: Rectangle {
                radius: Theme.radiusMd
                color: search.hovered ? Theme.surface3 : Theme.surface2
                border.width: search.visualFocus ? 2 : 1
                border.color: search.visualFocus ? Theme.accent : Theme.border
            }
            contentItem: RowLayout {
                spacing: Theme.s2
                PIcon { Layout.leftMargin: Theme.s2; name: "search"; size: Theme.iconSm }
                PLabel {
                    Layout.fillWidth: true
                    text: qsTr("Search or run a command…")
                    color: Theme.textFaint
                }
                KeyHint { Layout.rightMargin: Theme.s1; keys: "Ctrl+K" }
            }
        }
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
}
