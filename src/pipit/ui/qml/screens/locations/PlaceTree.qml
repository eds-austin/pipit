// The place tree. Up/Down choose a place, Right opens it (again: the first place inside),
// Left closes it (again: the place it is in), Home/End/PageUp/PageDown jump. Enter or Tab
// goes to the species list, "/" to the filter. Insert, F2, Delete: see LocationsScreen.
import QtQuick
import QtQuick.Controls.Basic as B
import Pipit

ListView {
    id: list
    objectName: "placeTree"
    signal enterSpecies()
    signal filterRequested(string text)
    signal addRequested()
    signal editRequested()
    signal deleteRequested()

    clip: true
    model: locations.tree
    currentIndex: locations.currentIndex
    highlightMoveDuration: 0
    keyNavigationEnabled: false
    boundsBehavior: Flickable.StopAtBounds
    reuseItems: true
    B.ScrollBar.vertical: B.ScrollBar {}
    Accessible.name: qsTr("Places")
    onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)

    readonly property int page: Math.max(1, Math.floor(height / Theme.rowHDense) - 1)

    Keys.onPressed: event => {
        const index = locations.currentIndex
        switch (event.key) {
        case Qt.Key_Up: locations.selectIndex(index - 1); break
        case Qt.Key_Down: locations.selectIndex(index + 1); break
        case Qt.Key_PageUp: locations.selectIndex(index - page); break
        case Qt.Key_PageDown: locations.selectIndex(index + page); break
        case Qt.Key_Home: locations.selectIndex(0); break
        case Qt.Key_End: locations.selectIndex(count - 1); break
        case Qt.Key_Right: locations.expandOrEnter(); break
        case Qt.Key_Left: locations.collapseOrLeave(); break
        case Qt.Key_Return:
        case Qt.Key_Enter:
        case Qt.Key_Tab: list.enterSpecies(); break
        case Qt.Key_Insert: list.addRequested(); break
        case Qt.Key_F2: list.editRequested(); break
        case Qt.Key_Delete: list.deleteRequested(); break
        default:
            if (event.text === "/" ) { list.filterRequested(""); break }
            if (event.text.length === 1 && /\S/.test(event.text) && !(event.modifiers & Qt.ControlModifier)) {
                list.filterRequested(event.text)  // type to filter
                break
            }
            return
        }
        event.accepted = true
    }

    delegate: Rectangle {
        id: item
        required property int index
        required property int row
        required property string name
        required property int depth
        required property bool hasChildren
        required property bool expanded
        required property int sightings
        required property bool builtIn
        required property bool matched
        readonly property bool selected: row === locations.selectedRow
        width: ListView.view.width
        height: Theme.rowHDense
        color: selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
             : hover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface) : "transparent"
        Accessible.role: Accessible.TreeItem
        Accessible.name: name

        Rectangle {
            visible: item.selected
            width: 2
            height: parent.height
            color: list.activeFocus ? Theme.accent : Theme.borderStrong
        }
        Item {
            id: chevron
            x: Theme.s2 + item.depth * Theme.s4
            width: Theme.iconSm
            height: parent.height
            PIcon {
                anchors.centerIn: parent
                visible: item.hasChildren
                name: item.expanded ? "chevron-down" : "chevron-right"
                size: Theme.iconSm
                color: Theme.textFaint
            }
            TapHandler { enabled: item.hasChildren; onTapped: locations.toggle(item.row) }
        }
        PLabel {
            anchors.left: chevron.right
            anchors.leftMargin: Theme.s1
            anchors.right: count.left
            anchors.rightMargin: Theme.s2
            height: parent.height
            text: item.name
            color: item.sightings > 0 || item.selected ? Theme.text : Theme.textMuted
            font.weight: item.matched ? Font.DemiBold : Font.Normal
        }
        PLabel {
            id: count
            anchors.right: parent.right
            anchors.rightMargin: Theme.s3
            height: parent.height
            kind: "num"
            text: item.sightings > 0 ? Number(item.sightings).toLocaleString(Qt.locale("en_US"), "f", 0) : ""
            color: Theme.textMuted
        }
        HoverHandler { id: hover }
        TapHandler {
            onTapped: { locations.select(item.row); list.forceActiveFocus() }
            onDoubleTapped: locations.toggle(item.row)
        }
    }
}
