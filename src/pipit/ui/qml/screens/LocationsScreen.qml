// Locations: the place tree, what was seen in the chosen place (and every place inside
// it), and the place itself with its visits. Keyboard map (also in F1):
//   Ctrl+F or /   filter the tree (typing a letter in the tree starts a filter too)
//   Up/Down       choose a place; Right opens it, Left closes it or goes up
//   Enter, Tab    into the species list; Esc or Shift+Tab back to the tree
//   Insert        a new place inside the chosen one
//   F2            edit the place (name for your own places, coordinates, notes)
//   Ctrl+M        move it into another place; Ctrl+Shift+M merge it into another place
//   Delete        delete it (its sightings and visits move to the place it is in)
//   Ctrl+E        into its visits: Enter opens one in Enter sightings to edit, Esc back
// Every change is one step of Ctrl+Z.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit
import "locations"

Item {
    id: root
    objectName: "locationsScreen"
    readonly property bool shown: shell.currentKey === "locations"
    readonly property bool working: app.hasList
    readonly property var place: locations.details
    readonly property bool has: place.row !== undefined
    readonly property bool dialogOpen: addDialog.visible || editDialog.visible
                                       || pickDialog.visible || deleteDialog.visible
    readonly property bool canChange: root.has && !app.readOnly && !root.dialogOpen

    function focusTree() { tree.forceActiveFocus() }
    function startFilter(text) {
        filter.forceActiveFocus()
        if (text) {
            filter.text = text
            locations.setFilter(text)
        } else {
            filter.selectAll()
        }
    }
    function openAdd() { if (root.canChange) addDialog.show() }
    function openEdit() { if (root.canChange) editDialog.show() }
    function openPick(mode) { if (root.canChange && !root.place.builtIn) pickDialog.show(mode) }
    function openDelete() {
        if (!root.canChange) return
        if (root.place.deleteBlocked !== "") app.message(root.place.deleteBlocked)
        else deleteDialog.open()
    }
    onShownChanged: if (shown && working) Qt.callLater(focusTree)

    Shortcut { enabled: root.shown && root.working && !root.dialogOpen; sequence: "Ctrl+F"; onActivated: root.startFilter("") }
    Shortcut { enabled: root.shown && root.working; sequence: "Ctrl+M"; onActivated: root.openPick("move") }
    Shortcut {
        enabled: root.shown && root.working && !root.dialogOpen
        sequence: "Ctrl+E"
        onActivated: if (!placePane.focusVisits()) app.message(qsTr("No visits recorded at this place itself"))
    }
    Shortcut { enabled: root.shown && root.working; sequence: "Ctrl+Shift+M"; onActivated: root.openPick("merge") }

    EmptyState {
        anchors.centerIn: parent
        visible: !root.working
        iconName: "map-pin"
        title: qsTr("Open or import a list")
        text: qsTr("Ctrl+O opens a Pipit list. “Import Scythebill list” in Ctrl+K brings in a .bsxm file.")
    }

    B.SplitView {
        anchors.fill: parent
        anchors.margins: Theme.windowPad
        visible: root.working
        orientation: Qt.Horizontal
        handle: Rectangle { implicitWidth: Theme.s3; color: "transparent" }

        // ------------------------------------------------------------ tree
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
                        objectName: "placeFilter"
                        Layout.fillWidth: true
                        implicitHeight: Theme.controlHCompact
                        bare: true
                        placeholderText: qsTr("Filter places (Ctrl+F)")
                        text: locations.filterText
                        onTextEdited: locations.setFilter(text)
                        Keys.onDownPressed: root.focusTree()
                        Keys.onReturnPressed: root.focusTree()
                        Keys.onEnterPressed: root.focusTree()
                        Keys.onEscapePressed: { text = ""; locations.setFilter(""); root.focusTree() }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                PlaceTree {
                    id: tree
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    onEnterSpecies: species.focusList()
                    onFilterRequested: text => root.startFilter(text)
                    onAddRequested: root.openAdd()
                    onEditRequested: root.openEdit()
                    onDeleteRequested: root.openDelete()
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
                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.headerH
                    Layout.leftMargin: Theme.s4
                    Layout.rightMargin: Theme.s4
                    spacing: Theme.s3
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        PLabel { kind: "overline"; text: qsTr("Seen in") }
                        PLabel { Layout.fillWidth: true; kind: "title"; text: root.has ? root.place.name : "" }
                    }
                    Badge { visible: app.taxaReady; text: app.displayTaxonomyName; neutral: true }
                    ColumnLayout {
                        spacing: 0
                        PLabel { Layout.alignment: Qt.AlignRight; kind: "overline"; text: qsTr("Species") }
                        PLabel {
                            objectName: "speciesCount"
                            Layout.alignment: Qt.AlignRight
                            kind: "kpi"
                            text: locations.speciesReady ? locations.speciesCount : "–"
                        }
                        PLabel {
                            Layout.alignment: Qt.AlignRight
                            visible: locations.speciesReady && locations.otherSpeciesCount > 0
                            kind: "caption"
                            text: qsTr("+ %n in other taxonomies", "", locations.otherSpeciesCount)
                        }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    SpeciesTable {
                        id: species
                        anchors.fill: parent
                        onBack: root.focusTree()
                    }
                    EmptyState {
                        anchors.centerIn: parent
                        visible: species.count === 0 && locations.speciesReady
                        iconName: "binoculars"
                        title: qsTr("Nothing seen here yet")
                        text: qsTr("Sightings in this place, or in any place inside it, are listed here.")
                    }
                    EmptyState {
                        anchors.centerIn: parent
                        visible: !app.taxaReady
                        iconName: "loader-circle"
                        title: qsTr("Loading the taxonomy…")
                    }
                }
            }
        }

        // ------------------------------------------------------------ the place
        Card {
            B.SplitView.preferredWidth: Theme.grid(280)
            B.SplitView.minimumWidth: Theme.grid(240)
            PlacePane {
                id: placePane
                anchors.fill: parent
                onBack: root.focusTree()
                onVisitChosen: (dateRaw, start) => {
                    if (entry.openVisit(root.place.xmlId, dateRaw, start)) shell.go("enter")
                }
                onAddRequested: root.openAdd()
                onEditRequested: root.openEdit()
                onMoveRequested: root.openPick("move")
                onMergeRequested: root.openPick("merge")
                onDeleteRequested: root.openDelete()
            }
        }
    }

    // ---------------------------------------------------------------- dialogs

    PDialog {
        id: addDialog
        objectName: "addPlaceDialog"
        heading: qsTr("New place in %1").arg(root.has ? root.place.name : "")
        function show() {
            newName.text = ""
            newType.currentIndex = 0
            open()
            newName.forceActiveFocus()
        }
        function save() {
            if (locations.addPlace(root.place.row, newName.text, newType.currentValue)) close()
        }
        onClosed: root.focusTree()
        ColumnLayout {
            width: parent.width
            spacing: Theme.s3
            PLabel { kind: "caption"; text: qsTr("Name") }
            PTextField {
                id: newName
                objectName: "newPlaceName"
                Layout.fillWidth: true
                Keys.onReturnPressed: addDialog.save()
                Keys.onEnterPressed: addDialog.save()
            }
            PLabel { kind: "caption"; text: qsTr("Kind of place (optional)") }
            PComboBox {
                id: newType
                Layout.fillWidth: true
                model: locations.locationTypes
                displayText: currentText === "" ? qsTr("Not set") : currentText
            }
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: addDialog.close() },
            PButton { text: qsTr("Add place"); variant: "primary"; enabled: newName.text.trim() !== ""; onClicked: addDialog.save() }
        ]
    }

    PDialog {
        id: editDialog
        objectName: "editPlaceDialog"
        heading: qsTr("Edit %1").arg(root.has ? root.place.name : "")
        function show() {
            editName.text = root.place.name
            editLatitude.text = root.place.latitude
            editLongitude.text = root.place.longitude
            editHotspot.text = root.place.hotspot
            editDescription.text = root.place.description
            editPrivate.checked = root.place.private
            open()
            if (root.place.builtIn) editLatitude.forceActiveFocus()
            else editName.forceActiveFocus()
        }
        function save() {
            if (locations.updatePlace(root.place.row, editName.text, editLatitude.text,
                                      editLongitude.text, editDescription.text,
                                      editPrivate.checked, editHotspot.text))
                close()
        }
        onClosed: root.focusTree()
        GridLayout {
            width: parent.width
            columns: 2
            columnSpacing: Theme.s3
            rowSpacing: Theme.s3
            PLabel { kind: "caption"; text: qsTr("Name") }
            PTextField {
                id: editName
                objectName: "editPlaceName"
                Layout.fillWidth: true
                enabled: root.has && !root.place.builtIn
                Keys.onReturnPressed: editDialog.save()
                Keys.onEnterPressed: editDialog.save()
            }
            PLabel { kind: "caption"; text: qsTr("Latitude") }
            PTextField {
                id: editLatitude
                Layout.fillWidth: true
                num: true
                placeholderText: "37.9958"
                Keys.onReturnPressed: editDialog.save()
                Keys.onEnterPressed: editDialog.save()
            }
            PLabel { kind: "caption"; text: qsTr("Longitude") }
            PTextField {
                id: editLongitude
                Layout.fillWidth: true
                num: true
                placeholderText: "-123.0215"
                Keys.onReturnPressed: editDialog.save()
                Keys.onEnterPressed: editDialog.save()
            }
            PLabel { kind: "caption"; text: qsTr("eBird hotspot") }
            PTextField {
                id: editHotspot
                Layout.fillWidth: true
                num: true
                placeholderText: "L123456"
                Keys.onReturnPressed: editDialog.save()
                Keys.onEnterPressed: editDialog.save()
            }
            PLabel { kind: "caption"; text: qsTr("Notes") }
            PTextField {
                id: editDescription
                Layout.fillWidth: true
                Keys.onReturnPressed: editDialog.save()
                Keys.onEnterPressed: editDialog.save()
            }
            Item { implicitWidth: 1 }
            PSwitch { id: editPrivate; text: qsTr("Private") }
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: editDialog.close() },
            PButton { text: qsTr("Save"); variant: "primary"; onClicked: editDialog.save() }
        ]
    }

    // Move or merge: choose the other place by typing part of its name.
    PDialog {
        id: pickDialog
        objectName: "pickPlaceDialog"
        property string mode: "move"
        heading: (mode === "move" ? qsTr("Move %1 into…") : qsTr("Merge %1 into…"))
                 .arg(root.has ? root.place.name : "")
        function show(chosenMode) {
            mode = chosenMode
            pickFilter.text = ""
            locations.findPlaces("", root.place.row)
            pickList.currentIndex = 0
            open()
            pickFilter.forceActiveFocus()
        }
        function choose(index) {
            const target = locations.choiceRow(index)
            if (target < 0) return
            const done = mode === "move" ? locations.movePlace(root.place.row, target)
                                         : locations.mergePlace(root.place.row, target)
            if (done) close()
        }
        onClosed: root.focusTree()
        ColumnLayout {
            width: parent.width
            spacing: Theme.s3
            PLabel {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                color: Theme.textMuted
                text: pickDialog.mode === "move"
                      ? qsTr("If the new place already has a place with the same name inside it, the two are merged.")
                      : qsTr("Its sightings, visits and the places inside it all move to the place you choose, and it is removed.")
            }
            PTextField {
                id: pickFilter
                objectName: "pickFilter"
                Layout.fillWidth: true
                placeholderText: qsTr("Type part of a name")
                onTextEdited: { locations.findPlaces(text, root.place.row); pickList.currentIndex = 0 }
                Keys.onDownPressed: pickList.currentIndex = Math.min(pickList.count - 1, pickList.currentIndex + 1)
                Keys.onUpPressed: pickList.currentIndex = Math.max(0, pickList.currentIndex - 1)
                Keys.onReturnPressed: pickDialog.choose(pickList.currentIndex)
                Keys.onEnterPressed: pickDialog.choose(pickList.currentIndex)
            }
            ListView {
                id: pickList
                objectName: "pickList"
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.rowH * 7
                clip: true
                model: locations.choices
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
                    TapHandler { onTapped: pickDialog.choose(choice.index) }
                }
            }
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: pickDialog.close() },
            PButton {
                text: pickDialog.mode === "move" ? qsTr("Move") : qsTr("Merge")
                variant: "primary"
                enabled: pickList.count > 0
                onClicked: pickDialog.choose(pickList.currentIndex)
            }
        ]
    }

    PDialog {
        id: deleteDialog
        objectName: "deletePlaceDialog"
        heading: qsTr("Delete %1?").arg(root.has ? root.place.name : "")
        onOpened: deleteButton.forceActiveFocus()
        onClosed: root.focusTree()
        PLabel {
            width: parent.width
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            text: root.has
                  ? qsTr("Its %n sighting(s) and its visits move to the place it is in. Ctrl+Z undoes this.", "", root.place.sightings)
                  : ""
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: deleteDialog.close() },
            PButton {
                id: deleteButton
                objectName: "confirmDelete"
                text: qsTr("Delete")
                variant: "danger"
                onClicked: { locations.deletePlace(root.place.row); deleteDialog.close() }
                Keys.onReturnPressed: clicked()
                Keys.onEnterPressed: clicked()
            }
        ]
    }
}
