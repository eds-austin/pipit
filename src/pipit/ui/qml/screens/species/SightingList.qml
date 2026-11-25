// The chosen entry's sightings, newest first. Up/Down/PageUp/PageDown/Home/End choose;
// Enter edits the chosen one; Esc or Shift+Tab goes back to the species list.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

ListView {
    id: list
    objectName: "sightingList"
    signal back()
    signal edit()

    clip: true
    model: species.sightings
    currentIndex: species.sightingIndex
    highlightMoveDuration: 0
    keyNavigationEnabled: false
    boundsBehavior: Flickable.StopAtBounds
    reuseItems: true
    spacing: 0
    B.ScrollBar.vertical: B.ScrollBar {}
    Accessible.name: qsTr("Sightings")
    onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)

    readonly property int rowHeight: Theme.grid(52)
    readonly property int page: Math.max(1, Math.floor(height / rowHeight) - 1)

    Keys.onPressed: event => {
        const index = species.sightingIndex
        switch (event.key) {
        case Qt.Key_Up: species.selectSightingIndex(index - 1); break
        case Qt.Key_Down: species.selectSightingIndex(index + 1); break
        case Qt.Key_PageUp: species.selectSightingIndex(index - page); break
        case Qt.Key_PageDown: species.selectSightingIndex(index + page); break
        case Qt.Key_Home: species.selectSightingIndex(0); break
        case Qt.Key_End: species.selectSightingIndex(count - 1); break
        case Qt.Key_Return:
        case Qt.Key_Enter: list.edit(); break
        case Qt.Key_Escape:
        case Qt.Key_Backtab: list.back(); break
        default: return
        }
        event.accepted = true
    }

    delegate: Rectangle {
        id: item
        required property int index
        required property int sightingId
        required property string date
        required property string time
        required property string place
        required property string asRecorded
        required property string count
        required property string flags
        required property string status
        required property string notes
        required property string trip
        readonly property bool selected: index === species.sightingIndex
        width: ListView.view.width
        height: list.rowHeight
        color: selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
             : hover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface)
             : index % 2 ? Theme.tint(Theme.text, 0.02, Theme.surface) : "transparent"
        Rectangle {
            visible: item.selected
            width: 2
            height: parent.height
            color: list.activeFocus ? Theme.accent : Theme.borderStrong
        }
        HoverHandler { id: hover }
        TapHandler { onTapped: { species.selectSighting(item.sightingId); list.forceActiveFocus() } }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.s4
            anchors.rightMargin: Theme.s4
            spacing: Theme.s3
            ColumnLayout {
                Layout.preferredWidth: Theme.grid(120)
                spacing: 0
                PLabel { kind: "num"; text: item.date }
                PLabel { kind: "num"; text: item.time; color: Theme.textMuted; visible: item.time !== "" }
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                spacing: 0
                PLabel { Layout.fillWidth: true; text: item.place }
                PLabel {
                    Layout.fillWidth: true
                    kind: "caption"
                    text: [item.asRecorded, item.flags, item.status !== "(None)" ? item.status : "",
                           item.trip !== "" ? qsTr("Trip: %1").arg(item.trip) : "", item.notes]
                          .filter(part => part !== "").join(" · ")
                    visible: text !== ""
                }
            }
            PLabel {
                Layout.preferredWidth: Theme.grid(56)
                horizontalAlignment: Text.AlignRight
                kind: "num"
                text: item.count !== "" ? item.count : "x"
                color: item.count !== "" ? Theme.text : Theme.textFaint
            }
        }
    }
}
