// Trips: the trips newest first, the species seen on the chosen one (its own sightings,
// and any inside its place within its dates, as in Scythebill), and the trip to edit.
// Keyboard map (also in F1):
//   Ctrl+F or /     filter trips by name or notes (typing in the list starts a filter too)
//   Up/Down         choose a trip; Enter or Tab into its species, Esc back
//   F2              edit the trip: Enter or Ctrl+S saves, Esc puts it back
//   Ctrl+P          choose the trip's place
//   Ctrl+Delete     delete the trip (its sightings stay; Ctrl+Z undoes)
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit
import "locations"

Item {
    id: root
    objectName: "tripsScreen"
    readonly property bool shown: shell.currentKey === "trips"
    readonly property bool working: app.hasList && trips.tripCount > 0
    readonly property var current: trips.trip
    readonly property bool has: current.row !== undefined
    readonly property bool writable: !app.readOnly
    readonly property bool dialogOpen: placeDialog.visible || deleteDialog.visible
    property var edited: ({})
    readonly property bool dirty: Object.keys(edited).length > 0

    function value(name) { return edited[name] !== undefined ? edited[name] : current[name] }
    function set(name, newValue) {
        const copy = Object.assign({}, edited)
        if (newValue === current[name]) delete copy[name]
        else copy[name] = newValue
        edited = copy
    }
    function revert() {
        edited = {}
        for (const field of [nameField, startField, endField, notesField])
            field.text = Qt.binding(() => root.current[field.key] || "")
    }
    function save() {
        if (!has || !dirty) return
        if (trips.saveTrip(current.row, value("name"), value("start"), value("end"),
                           value("placeXmlId"), value("notes"))) {
            edited = {}
            focusList()
        }
    }
    function focusList() { tripList.forceActiveFocus() }
    function startFilter(text) {
        filter.forceActiveFocus()
        if (text) { filter.text = text; trips.setFilter(text) } else filter.selectAll()
    }
    onCurrentChanged: revert()
    onShownChanged: if (shown && working) Qt.callLater(focusList)

    Shortcut { enabled: root.shown && root.working && !root.dialogOpen; sequence: "Ctrl+F"; onActivated: root.startFilter("") }
    Shortcut { enabled: root.shown && root.working && !root.dialogOpen; sequence: "Ctrl+S"; onActivated: root.save() }
    Shortcut { enabled: root.shown && root.working && root.has && root.writable && !root.dialogOpen; sequence: "F2"; onActivated: nameField.forceActiveFocus() }
    Shortcut { enabled: root.shown && root.working && root.has && root.writable && !root.dialogOpen; sequence: "Ctrl+P"; onActivated: placeDialog.show() }
    Shortcut { enabled: root.shown && root.working && root.has && root.writable && !root.dialogOpen; sequence: "Ctrl+Del"; onActivated: deleteDialog.open() }

    EmptyState {
        anchors.centerIn: parent
        visible: !root.working
        iconName: "route"
        title: app.hasList ? qsTr("No trips in this list") : qsTr("Open or import a list")
        text: app.hasList
              ? qsTr("Trips come with lists made in Scythebill. Creating trips in Pipit comes later.")
              : qsTr("Ctrl+O opens a Pipit list. “Import Scythebill list” in Ctrl+K brings in a .bsxm file.")
    }

    B.SplitView {
        anchors.fill: parent
        anchors.margins: Theme.windowPad
        visible: root.working
        orientation: Qt.Horizontal
        handle: Rectangle { implicitWidth: Theme.s3; color: "transparent" }

        // ------------------------------------------------------------ trips
        Card {
            B.SplitView.preferredWidth: Theme.grid(300)
            B.SplitView.minimumWidth: Theme.grid(220)
            padV: Theme.s2
            padH: 0
            ColumnLayout {
                anchors.fill: parent
                spacing: Theme.s2
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.s2
                    Layout.rightMargin: Theme.s2
                    spacing: Theme.s2
                    PIcon { name: "search"; size: Theme.iconSm; Layout.leftMargin: Theme.s1 }
                    PTextField {
                        id: filter
                        objectName: "tripFilter"
                        Layout.fillWidth: true
                        implicitHeight: Theme.controlHCompact
                        bare: true
                        placeholderText: qsTr("Filter trips (Ctrl+F)")
                        text: trips.filterText
                        onTextEdited: trips.setFilter(text)
                        Keys.onDownPressed: root.focusList()
                        Keys.onReturnPressed: root.focusList()
                        Keys.onEnterPressed: root.focusList()
                        Keys.onEscapePressed: { text = ""; trips.setFilter(""); root.focusList() }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                ListView {
                    id: tripList
                    objectName: "tripList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: trips.trips
                    currentIndex: trips.currentIndex
                    highlightMoveDuration: 0
                    keyNavigationEnabled: false
                    boundsBehavior: Flickable.StopAtBounds
                    B.ScrollBar.vertical: B.ScrollBar {}
                    Accessible.name: qsTr("Trips")
                    onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                    Keys.onPressed: event => {
                        const index = trips.currentIndex
                        if (event.key === Qt.Key_Up) trips.selectIndex(index - 1)
                        else if (event.key === Qt.Key_Down) trips.selectIndex(index + 1)
                        else if (event.key === Qt.Key_Home) trips.selectIndex(0)
                        else if (event.key === Qt.Key_End) trips.selectIndex(count - 1)
                        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Tab)
                            speciesTable.focusList()
                        else if (event.text.length === 1 && /\S/.test(event.text) && !(event.modifiers & Qt.ControlModifier))
                            root.startFilter(event.text === "/" ? "" : event.text)
                        else return
                        event.accepted = true
                    }
                    delegate: Rectangle {
                        id: item
                        required property int row
                        required property string name
                        required property string dates
                        required property string place
                        readonly property bool selected: row === root.current.row
                        width: ListView.view.width
                        height: Theme.grid(52)
                        color: selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
                             : hover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface) : "transparent"
                        Rectangle { visible: item.selected; width: 2; height: parent.height; color: tripList.activeFocus ? Theme.accent : Theme.borderStrong }
                        HoverHandler { id: hover }
                        TapHandler { onTapped: { trips.select(item.row); tripList.forceActiveFocus() } }
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.s3
                            anchors.rightMargin: Theme.s3
                            spacing: 0
                            Item { Layout.fillHeight: true }
                            PLabel { Layout.fillWidth: true; text: item.name; font.weight: Font.DemiBold }
                            PLabel {
                                Layout.fillWidth: true
                                kind: "caption"
                                text: item.place !== "" ? item.dates + " · " + item.place : item.dates
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }
                }
            }
        }

        // ------------------------------------------------------------ species
        Card {
            B.SplitView.fillWidth: true
            B.SplitView.minimumWidth: Theme.grid(360)
            padV: 0
            padH: 0
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.headerH
                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: Theme.s4
                        anchors.right: figures.left
                        anchors.rightMargin: Theme.s5
                        anchors.verticalCenter: parent.verticalCenter
                        PLabel { width: parent.width; kind: "title"; text: root.has ? root.current.name : "" }
                        PLabel { width: parent.width; kind: "caption"; text: root.has ? root.current.dates : "" }
                    }
                    RowLayout {
                        id: figures
                        anchors.right: parent.right
                        anchors.rightMargin: Theme.s4
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Theme.s5
                        ColumnLayout {
                            spacing: 0
                            PLabel { kind: "overline"; text: qsTr("Species") }
                            PLabel { objectName: "tripSpeciesCount"; kind: "kpi"; text: trips.speciesCount }
                        }
                        ColumnLayout {
                            spacing: 0
                            PLabel { kind: "overline"; text: qsTr("Sightings") }
                            PLabel { kind: "kpi"; text: trips.sightingCount }
                        }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                SpeciesTable {
                    id: speciesTable
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    source: trips.species
                    onBack: root.focusList()
                }
            }
        }

        // ------------------------------------------------------------ the trip
        Card {
            B.SplitView.preferredWidth: Theme.grid(300)
            B.SplitView.minimumWidth: Theme.grid(260)
            ColumnLayout {
                anchors.fill: parent
                spacing: Theme.s2
                enabled: root.has
                SectionHeader { text: qsTr("Trip") }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: Theme.s3
                    rowSpacing: Theme.s2
                    enabled: root.writable
                    PLabel { kind: "caption"; text: qsTr("Name") }
                    PTextField {
                        id: nameField
                        objectName: "tripName"
                        readonly property string key: "name"
                        Layout.fillWidth: true
                        text: root.current.name || ""
                        onTextEdited: root.set("name", text)
                        Keys.onReturnPressed: root.save()
                        Keys.onEnterPressed: root.save()
                        Keys.onEscapePressed: { root.revert(); root.focusList() }
                    }
                    PLabel { kind: "caption"; text: qsTr("From") }
                    PTextField {
                        id: startField
                        objectName: "tripStart"
                        readonly property string key: "start"
                        Layout.fillWidth: true
                        num: true
                        placeholderText: "2026-05-01"
                        text: root.current.start || ""
                        onTextEdited: root.set("start", text)
                        Keys.onReturnPressed: root.save()
                        Keys.onEnterPressed: root.save()
                        Keys.onEscapePressed: { root.revert(); root.focusList() }
                    }
                    PLabel { kind: "caption"; text: qsTr("To") }
                    PTextField {
                        id: endField
                        objectName: "tripEnd"
                        readonly property string key: "end"
                        Layout.fillWidth: true
                        num: true
                        placeholderText: "2026-05-08"
                        text: root.current.end || ""
                        onTextEdited: root.set("end", text)
                        Keys.onReturnPressed: root.save()
                        Keys.onEnterPressed: root.save()
                        Keys.onEscapePressed: { root.revert(); root.focusList() }
                    }
                    PLabel { kind: "caption"; text: qsTr("Place") }
                    PButton {
                        objectName: "tripPlaceButton"
                        Layout.fillWidth: true
                        compact: true
                        iconName: "map-pin"
                        text: root.edited.placeLabel !== undefined ? root.edited.placeLabel
                              : (root.current.place || qsTr("No place"))
                        onClicked: placeDialog.show()
                    }
                    PLabel { kind: "caption"; text: qsTr("Notes") }
                    PTextField {
                        id: notesField
                        objectName: "tripNotes"
                        readonly property string key: "notes"
                        Layout.fillWidth: true
                        text: root.current.notes || ""
                        onTextEdited: root.set("notes", text)
                        Keys.onReturnPressed: root.save()
                        Keys.onEnterPressed: root.save()
                        Keys.onEscapePressed: { root.revert(); root.focusList() }
                    }
                }
                PLabel {
                    Layout.fillWidth: true
                    visible: root.has && (root.current.links > 0 || root.current.photos > 0)
                    kind: "caption"
                    wrapMode: Text.WordWrap
                    elide: Text.ElideNone
                    text: root.has ? qsTr("%1 links and %2 photos, kept as they are.")
                                         .arg(root.current.links).arg(root.current.photos) : ""
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.s2
                    PButton {
                        objectName: "saveTrip"
                        variant: "primary"
                        text: qsTr("Save")
                        enabled: root.writable && root.dirty
                        onClicked: root.save()
                    }
                    KeyHint { keys: "Ctrl+S"; subtle: true }
                    Item { Layout.fillWidth: true }
                    PButton { visible: root.dirty; variant: "ghost"; text: qsTr("Revert"); onClicked: root.revert() }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                ActionRow {
                    Layout.fillWidth: true
                    text: qsTr("Edit the trip")
                    iconName: "pencil"
                    keys: "F2"
                    enabled: root.writable
                    onClicked: nameField.forceActiveFocus()
                }
                ActionRow {
                    objectName: "deleteTripButton"
                    Layout.fillWidth: true
                    text: qsTr("Delete trip")
                    iconName: "trash-2"
                    keys: "Ctrl+Del"
                    danger: true
                    enabled: root.writable
                    onClicked: deleteDialog.open()
                }
                Item { Layout.fillHeight: true }
            }
        }
    }

    // The trip's place: type part of a name; "No place" makes it anywhere.
    PDialog {
        id: placeDialog
        objectName: "tripPlaceDialog"
        heading: qsTr("Place of %1").arg(root.has ? root.current.name : "")
        function show() {
            placeFilter.text = ""
            trips.findPlaces("")
            placeList.currentIndex = 0
            open()
            placeFilter.forceActiveFocus()
        }
        function choose(index) {
            const xmlId = trips.choiceXmlId(index)
            if (xmlId === "?") return
            const copy = Object.assign({}, root.edited)
            if (xmlId === (root.current.placeXmlId || "")) {
                delete copy.placeXmlId
                delete copy.placeLabel
            } else {
                copy.placeXmlId = xmlId
                copy.placeLabel = xmlId === "" ? qsTr("No place") : trips.choiceLabel(index)
            }
            root.edited = copy
            close()
        }
        onClosed: nameField.forceActiveFocus()
        ColumnLayout {
            width: parent.width
            spacing: Theme.s3
            PLabel {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                color: Theme.textMuted
                text: qsTr("Sightings on the trip at its present place move to the new one when you save, as in Scythebill.")
            }
            PTextField {
                id: placeFilter
                objectName: "tripPlaceFilter"
                Layout.fillWidth: true
                placeholderText: qsTr("Type part of a name")
                onTextEdited: { trips.findPlaces(text); placeList.currentIndex = 0 }
                Keys.onDownPressed: placeList.currentIndex = Math.min(placeList.count - 1, placeList.currentIndex + 1)
                Keys.onUpPressed: placeList.currentIndex = Math.max(0, placeList.currentIndex - 1)
                Keys.onReturnPressed: placeDialog.choose(placeList.currentIndex)
                Keys.onEnterPressed: placeDialog.choose(placeList.currentIndex)
            }
            ListView {
                id: placeList
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.rowH * 7
                clip: true
                model: trips.choices
                highlightMoveDuration: 0
                B.ScrollBar.vertical: B.ScrollBar {}
                delegate: Rectangle {
                    id: choice
                    required property int index
                    required property string name
                    required property string path
                    width: ListView.view.width
                    height: Theme.rowH
                    radius: Theme.radiusSm
                    color: ListView.isCurrentItem ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface2) : "transparent"
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.s3
                        anchors.rightMargin: Theme.s3
                        spacing: 0
                        PLabel { Layout.fillWidth: true; text: choice.name }
                        PLabel { Layout.fillWidth: true; kind: "caption"; text: choice.path; visible: choice.path !== "" }
                    }
                    TapHandler { onTapped: placeDialog.choose(choice.index) }
                }
            }
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: placeDialog.close() },
            PButton { text: qsTr("Choose"); variant: "primary"; enabled: placeList.count > 0; onClicked: placeDialog.choose(placeList.currentIndex) }
        ]
    }

    PDialog {
        id: deleteDialog
        objectName: "deleteTripDialog"
        heading: qsTr("Delete %1?").arg(root.has ? root.current.name : "")
        onOpened: confirmDelete.forceActiveFocus()
        onClosed: root.focusList()
        PLabel {
            width: parent.width
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            text: qsTr("No sightings are deleted, but the trip's name, notes, links and photos go. Sightings without their own date get the dates the trip's start and end share. Ctrl+Z undoes this.")
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: deleteDialog.close() },
            PButton {
                id: confirmDelete
                objectName: "confirmDeleteTrip"
                text: qsTr("Delete")
                variant: "danger"
                onClicked: { trips.deleteTrip(root.current.row); deleteDialog.close() }
                Keys.onReturnPressed: clicked()
                Keys.onEnterPressed: clicked()
            }
        ]
    }
}
