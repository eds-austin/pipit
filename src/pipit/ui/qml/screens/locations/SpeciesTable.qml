// What was seen in the selected place and every place inside it, in taxonomic order.
// Up/Down/PageUp/PageDown/Home/End move; Esc or Shift+Tab goes back to the tree.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

Item {
    id: root
    signal back()
    // The rows (a list model with common, scientific, sightings, first, last, heardOnly):
    // what was seen in a place, or on a trip. Back to the top whenever it is refilled.
    property var source: locations.species
    readonly property alias count: list.count
    readonly property int numberW: Theme.grid(72)
    readonly property int dateW: Theme.grid(100)

    function focusList() {
        if (list.currentIndex < 0 && list.count > 0) list.currentIndex = 0
        list.forceActiveFocus()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.rowHDense
            Layout.leftMargin: Theme.s4
            Layout.rightMargin: Theme.s4
            spacing: Theme.s3
            PLabel { Layout.fillWidth: true; kind: "overline"; text: qsTr("Species") }
            PLabel { Layout.preferredWidth: root.numberW; kind: "overline"; text: qsTr("Sightings"); horizontalAlignment: Text.AlignRight }
            PLabel { Layout.preferredWidth: root.dateW; kind: "overline"; text: qsTr("First") }
            PLabel { Layout.preferredWidth: root.dateW; kind: "overline"; text: qsTr("Latest") }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

        ListView {
            id: list
            objectName: "speciesTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.source
            reuseItems: true
            highlightMoveDuration: 0
            keyNavigationEnabled: true
            boundsBehavior: Flickable.StopAtBounds
            B.ScrollBar.vertical: B.ScrollBar {}
            Accessible.name: qsTr("Species seen here")
            Connections {
                target: root.source
                function onModelReset() { list.currentIndex = list.activeFocus && list.count ? 0 : -1; list.positionViewAtBeginning() }
            }
            readonly property int page: Math.max(1, Math.floor(height / Theme.rowHDense) - 1)
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Escape || event.key === Qt.Key_Backtab) root.back()
                else if (event.key === Qt.Key_PageDown) currentIndex = Math.min(count - 1, currentIndex + page)
                else if (event.key === Qt.Key_PageUp) currentIndex = Math.max(0, currentIndex - page)
                else if (event.key === Qt.Key_Home) currentIndex = 0
                else if (event.key === Qt.Key_End) currentIndex = count - 1
                else return
                event.accepted = true
            }

            delegate: Rectangle {
                id: item
                required property int index
                required property string common
                required property string scientific
                required property int sightings
                required property string first
                required property string last
                required property bool heardOnly
                readonly property bool current: ListView.isCurrentItem && list.activeFocus
                width: ListView.view.width
                height: Theme.rowHDense
                color: current ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
                     : hover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface)
                     : index % 2 ? Theme.tint(Theme.text, 0.02, Theme.surface) : "transparent"
                Rectangle { visible: item.current; width: 2; height: parent.height; color: Theme.accent }
                HoverHandler { id: hover }
                TapHandler { onTapped: { list.currentIndex = item.index; list.forceActiveFocus() } }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.s4
                    anchors.rightMargin: Theme.s4
                    spacing: Theme.s3
                    // Name cell, placed by hand: the common name keeps its full width first,
                    // then the badge; the scientific name takes what is left.
                    Item {
                        id: nameCell
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredWidth: 0  // takes what the number columns leave
                        readonly property int badgeSpace: item.heardOnly ? heard.implicitWidth + Theme.s2 : 0
                        PLabel {
                            id: commonName
                            width: Math.min(implicitWidth, nameCell.width - nameCell.badgeSpace)
                            height: parent.height
                            text: item.common
                        }
                        Badge {
                            id: heard
                            visible: item.heardOnly
                            x: commonName.width + Theme.s2
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("Heard only")
                            tone: Theme.info
                        }
                        PLabel {
                            x: commonName.width + nameCell.badgeSpace + Theme.s2
                            width: Math.max(0, nameCell.width - x)
                            height: parent.height
                            visible: width > Theme.s7
                            text: item.scientific
                            font.italic: true
                            color: Theme.textFaint
                        }
                    }
                    PLabel { Layout.preferredWidth: root.numberW; kind: "num"; text: item.sightings; horizontalAlignment: Text.AlignRight; color: Theme.textMuted }
                    PLabel { Layout.preferredWidth: root.dateW; kind: "num"; text: item.first; color: Theme.textMuted }
                    PLabel { Layout.preferredWidth: root.dateW; kind: "num"; text: item.last; color: Theme.textMuted }
                }
            }
        }
    }
}
