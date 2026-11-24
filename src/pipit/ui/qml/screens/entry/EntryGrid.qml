// The day's species: one row per bird, one count cell per location (A-D).
// Up/Down choose a row, Left/Right a location. Type a count (digits, "~", ">", "x") to edit
// the cell, Enter to edit it with its current value, Delete to untick it, Ctrl+Delete to
// remove the row. Alt+H heard only, Alt+P photographed, Alt+M male, Alt+F female, Alt+U
// adult, Alt+J immature. Any other letter goes back to the species field.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

Item {
    id: root
    property bool editing: false
    property string seed: ""
    readonly property alias currentIndex: list.currentIndex
    readonly property alias count: list.count
    readonly property var letters: "ABCD".substring(0, entry.slotCount).split("")
    signal typeToSpecies(string text)

    function focusRow(row) {
        list.currentIndex = Math.max(0, Math.min(row, list.count - 1))
        list.positionViewAtIndex(list.currentIndex, ListView.Contain)
        list.forceActiveFocus()
    }
    function showRow(row) {  // select without taking focus (typing continues elsewhere)
        list.currentIndex = row
        list.positionViewAtIndex(row, ListView.Contain)
    }
    function moveSlot(step) {
        const i = letters.indexOf(entry.activeSlot) + step
        if (i >= 0 && i < letters.length) entry.setActiveSlot(letters[i])
    }
    readonly property var flagKeys: ({
        [Qt.Key_H]: "heard_only", [Qt.Key_P]: "photographed", [Qt.Key_M]: "male",
        [Qt.Key_F]: "female", [Qt.Key_U]: "adult", [Qt.Key_J]: "immature"
    })

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // Column headers
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.rowHDense
            Layout.leftMargin: Theme.s3
            Layout.rightMargin: Theme.s3
            spacing: Theme.s2
            PLabel { Layout.fillWidth: true; kind: "overline"; text: qsTr("Species") }
            Repeater {
                model: root.letters
                PLabel {
                    required property string modelData
                    Layout.preferredWidth: Theme.grid(64)
                    horizontalAlignment: Text.AlignHCenter
                    kind: "overline"
                    text: modelData
                    color: modelData === entry.activeSlot ? Theme.accent : Theme.textMuted
                }
            }
            PLabel { Layout.preferredWidth: Theme.grid(160); kind: "overline"; text: qsTr("Notes") }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

        ListView {
            id: list
            objectName: "entryGrid"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: entry.rows
            keyNavigationEnabled: true
            highlightMoveDuration: 0
            reuseItems: true
            B.ScrollBar.vertical: B.ScrollBar {}
            Accessible.name: qsTr("Species entered")

            Keys.onPressed: event => {
                if (root.editing) return
                const alt = event.modifiers & Qt.AltModifier
                const ctrl = event.modifiers & Qt.ControlModifier
                const row = list.currentIndex
                if (alt && root.flagKeys[event.key] !== undefined) {
                    entry.toggleFlag(row, entry.activeSlot, root.flagKeys[event.key])
                } else if (event.key === Qt.Key_Left && !alt) {
                    root.moveSlot(-1)
                } else if (event.key === Qt.Key_Right && !alt) {
                    root.moveSlot(1)
                } else if (event.key === Qt.Key_Delete && ctrl) {
                    entry.removeRow(row)
                } else if (event.key === Qt.Key_Delete || event.key === Qt.Key_Backspace) {
                    entry.untick(row, entry.activeSlot)
                } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && !ctrl && row >= 0) {
                    root.seed = ""
                    root.editing = true
                } else if (/^[0-9~<>xX]$/.test(event.text) && !alt && !ctrl && row >= 0) {
                    root.seed = event.text
                    root.editing = true
                } else if (/^[a-zA-Z ]$/.test(event.text) && !alt && !ctrl) {
                    root.typeToSpecies(event.text)
                } else if (event.key === Qt.Key_Escape) {
                    root.typeToSpecies("")
                } else {
                    return
                }
                event.accepted = true
            }

            delegate: Rectangle {
                id: row
                required property int index
                required property string name
                required property string scientific
                required property var counts
                required property var details
                required property var badges
                required property string notes
                readonly property bool current: ListView.isCurrentItem
                width: ListView.view.width
                height: Theme.rowHDense
                color: current && list.activeFocus ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
                     : current ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface)
                     : "transparent"
                Rectangle {
                    visible: row.current
                    width: 2; height: parent.height; color: Theme.accent
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.s3
                    anchors.rightMargin: Theme.s3
                    spacing: Theme.s2
                    PLabel { text: row.name; Layout.maximumWidth: implicitWidth }
                    PLabel {
                        text: row.scientific
                        color: Theme.textFaint
                        font.italic: true
                        Layout.fillWidth: true
                    }
                    Repeater {
                        model: row.badges
                        Badge {
                            required property string modelData
                            text: modelData
                            tone: modelData === "LIFER" ? Theme.positive
                                : modelData.startsWith("ENDEMIC") ? Theme.info : Theme.warning
                            iconName: modelData === "LIFER" ? "sparkles" : ""
                        }
                    }
                    Repeater {
                        model: root.letters
                        Rectangle {
                            id: cell
                            required property string modelData
                            required property int index
                            readonly property bool active: modelData === entry.activeSlot
                            readonly property string count: row.counts[index]
                            Layout.preferredWidth: Theme.grid(64)
                            Layout.fillHeight: true
                            Layout.topMargin: 2
                            Layout.bottomMargin: 2
                            radius: Theme.radiusSm
                            color: count !== "" ? Theme.soft(Theme.accent) : "transparent"
                            border.width: row.current && active ? 2 : 0
                            border.color: Theme.accent
                            PLabel {
                                anchors.centerIn: parent
                                visible: !(row.current && cell.active && root.editing)
                                kind: "num"
                                text: cell.count === "" ? "·" : cell.count
                                color: cell.count === "" ? Theme.textFaint : Theme.text
                            }
                            PLabel {
                                anchors.right: parent.right
                                anchors.rightMargin: 3
                                anchors.top: parent.top
                                visible: row.details[cell.index] !== ""
                                kind: "caption"
                                text: row.details[cell.index]
                                color: Theme.info
                            }
                            PTextField {
                                anchors.fill: parent
                                visible: row.current && cell.active && root.editing
                                num: true
                                horizontalAlignment: TextInput.AlignHCenter
                                onVisibleChanged: if (visible) {
                                    text = root.seed !== "" ? root.seed : cell.count
                                    forceActiveFocus()
                                    if (root.seed === "") selectAll()
                                }
                                Keys.onReturnPressed: finish(true)
                                Keys.onEnterPressed: finish(true)
                                Keys.onEscapePressed: finish(false)
                                function finish(apply) {
                                    if (apply && !entry.setCount(row.index, cell.modelData, text))
                                        return  // invalid count: keep editing
                                    root.editing = false
                                    list.forceActiveFocus()
                                }
                            }
                        }
                    }
                    PLabel {
                        Layout.preferredWidth: Theme.grid(160)
                        text: row.notes
                        color: Theme.textMuted
                    }
                }
            }
        }
    }
}
