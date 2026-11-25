// The selected place: what it is, its actions (with their keys) and its own visits.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

ColumnLayout {
    id: root
    readonly property var place: locations.details
    readonly property bool has: place.row !== undefined
    readonly property bool writable: !app.readOnly
    signal addRequested()
    signal editRequested()
    signal moveRequested()
    signal mergeRequested()
    signal deleteRequested()
    spacing: Theme.s2

    PLabel {
        Layout.fillWidth: true
        kind: "title"
        text: root.has ? root.place.name : qsTr("No place chosen")
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
    }
    PLabel {
        Layout.fillWidth: true
        visible: root.has && root.place.path !== ""
        kind: "caption"
        text: root.has ? root.place.path : ""
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
    }
    Flow {
        Layout.fillWidth: true
        visible: root.has
        spacing: Theme.s1
        Badge { visible: root.has && root.place.kind !== ""; text: root.has ? root.place.kind : ""; neutral: true }
        Badge { visible: root.has && root.place.builtIn; text: qsTr("Built-in"); tone: Theme.info; iconName: "badge-check" }
        Badge { visible: root.has && root.place.code !== ""; text: root.has ? "eBird " + root.place.code : ""; neutral: true }
        Badge { visible: root.has && root.place.private; text: qsTr("Private"); tone: Theme.warning; iconName: "shield-check" }
        Badge { visible: root.has && root.place.hasChecklist; text: qsTr("Own checklist"); tone: Theme.positive; iconName: "check" }
    }

    GridLayout {
        Layout.fillWidth: true
        Layout.topMargin: Theme.s1
        visible: root.has
        columns: 2
        columnSpacing: Theme.s3
        rowSpacing: Theme.s1
        PLabel { kind: "caption"; text: qsTr("Sightings") }
        PLabel { kind: "num"; text: root.has ? Number(root.place.sightings).toLocaleString(Qt.locale("en_US"), "f", 0) : "" }
        PLabel { kind: "caption"; text: qsTr("Coordinates"); visible: root.has && root.place.latitude !== "" }
        PLabel {
            visible: root.has && root.place.latitude !== ""
            kind: "num"
            text: root.has ? root.place.latitude + ", " + root.place.longitude : ""
        }
        PLabel { kind: "caption"; text: qsTr("eBird hotspot"); visible: root.has && root.place.hotspot !== "" }
        PLabel { visible: root.has && root.place.hotspot !== ""; kind: "num"; text: root.has ? root.place.hotspot : "" }
    }
    PLabel {
        Layout.fillWidth: true
        visible: root.has && root.place.description !== ""
        text: root.has ? root.place.description : ""
        color: Theme.textMuted
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
        maximumLineCount: 6
    }

    // Actions, each with its key
    ColumnLayout {
        Layout.fillWidth: true
        Layout.topMargin: Theme.s2
        visible: root.has
        spacing: 0
        ActionRow {
            objectName: "editPlaceButton"
            Layout.fillWidth: true
            text: qsTr("Edit")
            iconName: "pencil"
            keys: "F2"
            enabled: root.writable
            onClicked: root.editRequested()
        }
        ActionRow {
            objectName: "addPlaceButton"
            Layout.fillWidth: true
            text: qsTr("New place inside")
            iconName: "plus"
            keys: "Ins"
            enabled: root.writable
            onClicked: root.addRequested()
        }
        ActionRow {
            objectName: "movePlaceButton"
            Layout.fillWidth: true
            text: qsTr("Move into…")
            iconName: "folder-input"
            keys: "Ctrl+M"
            enabled: root.writable && root.has && !root.place.builtIn
            blockedReason: root.has && root.place.builtIn ? qsTr("Built-in places stay where they are.") : ""
            onClicked: root.moveRequested()
        }
        ActionRow {
            objectName: "mergePlaceButton"
            Layout.fillWidth: true
            text: qsTr("Merge into…")
            iconName: "git-merge"
            keys: "Ctrl+Shift+M"
            enabled: root.writable && root.has && !root.place.builtIn
            blockedReason: root.has && root.place.builtIn ? qsTr("Built-in places can't be merged away.") : ""
            onClicked: root.mergeRequested()
        }
        ActionRow {
            objectName: "deletePlaceButton"
            Layout.fillWidth: true
            text: qsTr("Delete")
            iconName: "trash-2"
            keys: "Del"
            danger: true
            enabled: root.writable && root.has && root.place.deleteBlocked === ""
            blockedReason: root.has ? root.place.deleteBlocked : ""
            onClicked: root.deleteRequested()
        }
    }
    PLabel {
        Layout.fillWidth: true
        visible: root.has && root.place.deleteBlocked !== ""
        kind: "caption"
        text: root.has ? qsTr("Can't delete: %1").arg(root.place.deleteBlocked) : ""
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
    }

    Rectangle { Layout.fillWidth: true; Layout.topMargin: Theme.s2; Layout.preferredHeight: 1; color: Theme.border }
    SectionHeader { text: qsTr("Visits here · %1").arg(visitList.count) }
    PLabel {
        Layout.fillWidth: true
        visible: visitList.count === 0
        color: Theme.textMuted
        text: qsTr("No visits recorded at this place itself.")
        wrapMode: Text.WordWrap
    }
    ListView {
        id: visitList
        objectName: "visitList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: Theme.s1
        model: locations.visits
        boundsBehavior: Flickable.StopAtBounds
        B.ScrollBar.vertical: B.ScrollBar {}
        delegate: Rectangle {
            id: visit
            required property string date
            required property string start
            required property string protocol
            required property string duration
            required property string distance
            required property bool complete
            required property string comments
            required property int sightings
            width: ListView.view.width
            height: column.implicitHeight + 2 * Theme.s2
            radius: Theme.radiusMd
            color: Theme.surface2
            ColumnLayout {
                id: column
                anchors.fill: parent
                anchors.margins: Theme.s2
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s3
                spacing: Theme.s1
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.s2
                    PLabel { kind: "num"; text: visit.date + (visit.start !== "" ? "  " + visit.start : "") }
                    Item { Layout.fillWidth: true }
                    Badge { visible: visit.complete; text: qsTr("Complete"); tone: Theme.positive; iconName: "check" }
                }
                PLabel {
                    Layout.fillWidth: true
                    kind: "caption"
                    text: [visit.protocol, visit.duration, visit.distance,
                           qsTr("%n sighting(s)", "", visit.sightings)].filter(part => part !== "").join(" · ")
                }
                PLabel {
                    Layout.fillWidth: true
                    visible: visit.comments !== ""
                    text: visit.comments
                    color: Theme.textMuted
                    wrapMode: Text.WordWrap
                    elide: Text.ElideRight
                    maximumLineCount: 2
                }
            }
        }
    }
}
