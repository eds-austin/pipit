// Ctrl+K: type to filter every screen and action, Up/Down to choose, Enter to run,
// Esc to close. Matching is word-prefix ("ensi" finds "Enter sightings").
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

B.Popup {
    id: root
    function show(query) {
        field.text = query || ""
        shell.setPaletteQuery(field.text)
        list.currentIndex = 0
        open()
    }

    modal: true
    focus: true
    x: (parent.width - width) / 2
    y: Theme.grid(80)
    width: Math.min(Theme.paletteW, parent.width - 2 * Theme.s7)
    height: Math.min(implicitHeight, parent.height - y - Theme.s7)
    padding: 0
    closePolicy: B.Popup.CloseOnEscape | B.Popup.CloseOnPressOutside
    B.Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }
    onOpened: field.forceActiveFocus()

    background: Rectangle {
        color: Theme.surface2
        radius: Theme.radiusLg
        border.color: Theme.borderStrong
    }

    contentItem: ColumnLayout {
        spacing: 0
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.headerH - Theme.s2
            Layout.leftMargin: Theme.s4
            Layout.rightMargin: Theme.s3
            spacing: Theme.s2
            PIcon { name: "search"; color: Theme.textMuted }
            PTextField {
                id: field
                Layout.fillWidth: true
                bare: true
                focusRing: false
                placeholderText: qsTr("Go to a screen or run a command")
                Accessible.name: qsTr("Command")
                onTextEdited: {
                    shell.setPaletteQuery(text)
                    list.currentIndex = 0
                }
                Keys.onUpPressed: list.decrementCurrentIndex()
                Keys.onDownPressed: list.incrementCurrentIndex()
                Keys.onReturnPressed: root.runCurrent()
                Keys.onEnterPressed: root.runCurrent()
            }
            KeyHint { keys: "Esc"; subtle: true }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
        ListView {
            id: list
            objectName: "paletteList"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, Theme.rowHDense * 12) + Theme.s4
            Layout.topMargin: Theme.s2
            Layout.bottomMargin: Theme.s2
            clip: true
            model: shell.palette
            highlightMoveDuration: 0
            keyNavigationWraps: true
            delegate: B.ItemDelegate {
                id: row
                required property int index
                required property string title
                required property string category
                required property string shortcut
                width: ListView.view.width
                height: Theme.rowH - Theme.s1
                hoverEnabled: true
                onClicked: { list.currentIndex = index; root.runCurrent() }
                background: Rectangle {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.s2
                    anchors.rightMargin: Theme.s2
                    radius: Theme.radiusMd
                    color: row.ListView.isCurrentItem ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface2)
                         : row.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface2) : "transparent"
                    Rectangle {
                        visible: row.ListView.isCurrentItem
                        width: 2; radius: 1; color: Theme.accent
                        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
                        anchors.topMargin: Theme.s1 + 2; anchors.bottomMargin: Theme.s1 + 2
                    }
                }
                contentItem: RowLayout {
                    spacing: Theme.s3
                    PLabel {
                        Layout.leftMargin: Theme.s4
                        Layout.preferredWidth: Theme.grid(72)
                        kind: "overline"
                        text: row.category
                        color: Theme.textFaint
                    }
                    PLabel {
                        Layout.fillWidth: true
                        text: row.title
                        color: row.ListView.isCurrentItem ? Theme.text : Theme.textMuted
                    }
                    KeyHint { Layout.rightMargin: Theme.s4; keys: row.shortcut }
                }
            }
            PLabel {
                visible: list.count === 0
                anchors.centerIn: parent
                color: Theme.textMuted
                text: qsTr("No matching commands")
            }
        }
    }

    function runCurrent() {
        if (list.count === 0)
            return
        const row = list.currentIndex
        close()
        shell.runPaletteRow(row)
    }
}
