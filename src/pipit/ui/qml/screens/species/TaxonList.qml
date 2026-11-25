// The display taxonomy as a list: families as headings, species bold when seen and
// italic when not (as in Scythebill). Up/Down/PageUp/PageDown/Home/End choose (headings
// are skipped); Enter or Tab goes to the sightings; typing starts a filter.
import QtQuick
import QtQuick.Controls.Basic as B
import Pipit

ListView {
    id: list
    objectName: "taxonList"
    signal enterSightings()
    signal filterRequested(string text)

    clip: true
    model: species.taxaList
    currentIndex: species.currentIndex
    highlightMoveDuration: 0
    keyNavigationEnabled: false
    boundsBehavior: Flickable.StopAtBounds
    reuseItems: true
    cacheBuffer: Theme.rowHDense * 40
    B.ScrollBar.vertical: B.ScrollBar {}
    Accessible.name: qsTr("Species")
    onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)

    readonly property int page: Math.max(1, Math.floor(height / Theme.rowHDense) - 1)

    Keys.onPressed: event => {
        const index = species.currentIndex
        switch (event.key) {
        case Qt.Key_Up: species.selectIndex(index - 1, -1); break
        case Qt.Key_Down: species.selectIndex(index + 1, 1); break
        case Qt.Key_PageUp: species.selectIndex(index - page, -1); break
        case Qt.Key_PageDown: species.selectIndex(index + page, 1); break
        case Qt.Key_Home: species.selectIndex(0, 1); break
        case Qt.Key_End: species.selectIndex(count - 1, -1); break
        case Qt.Key_Return:
        case Qt.Key_Enter:
        case Qt.Key_Tab: list.enterSightings(); break
        default:
            if (event.text.length === 1 && /\S/.test(event.text) && !(event.modifiers & Qt.ControlModifier)) {
                list.filterRequested(event.text === "/" ? "" : event.text)
                break
            }
            return
        }
        event.accepted = true
    }

    delegate: Rectangle {
        id: item
        required property int index
        required property string key
        required property bool heading
        required property string common
        required property string scientific
        required property int sightings
        readonly property bool selected: !heading && key === species.entry.key
        width: ListView.view.width
        height: Theme.rowHDense
        color: selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
             : hover.hovered && !heading ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface)
             : "transparent"
        Accessible.role: Accessible.ListItem
        Accessible.name: common

        Rectangle {
            visible: item.selected
            width: 2
            height: parent.height
            color: list.activeFocus ? Theme.accent : Theme.borderStrong
        }
        // A family heading
        PLabel {
            visible: item.heading
            anchors.left: parent.left
            anchors.leftMargin: Theme.s3
            anchors.right: parent.right
            anchors.rightMargin: Theme.s3
            height: parent.height
            kind: "overline"
            text: item.common
            color: Theme.textFaint
        }
        // A species (or sp., hybrid, other taxonomy)
        PLabel {
            visible: !item.heading
            anchors.left: parent.left
            anchors.leftMargin: Theme.s5
            anchors.right: count.left
            anchors.rightMargin: Theme.s2
            height: parent.height
            text: item.common
            color: item.sightings > 0 || item.selected ? Theme.text : Theme.textMuted
            font.weight: item.sightings > 0 ? Font.DemiBold : Font.Normal
            font.italic: item.sightings === 0
        }
        PLabel {
            id: count
            visible: !item.heading
            anchors.right: parent.right
            anchors.rightMargin: Theme.s3
            height: parent.height
            kind: "num"
            text: item.sightings > 0 ? item.sightings : ""
            color: Theme.textMuted
        }
        HoverHandler { id: hover; enabled: !item.heading }
        TapHandler {
            enabled: !item.heading
            onTapped: { species.select(item.key); list.forceActiveFocus() }
        }
    }
}
