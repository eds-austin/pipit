// Species: the display taxonomy (families as headings), the chosen species' sightings, and
// the chosen sighting to edit. Keyboard map (also in F1):
//   Ctrl+F or /     filter species (typing a letter in the list starts a filter too)
//   Ctrl+Shift+A    every species in the taxonomy, or only those seen
//   Up/Down         choose; Enter or Tab into its sightings, Esc back
//   Enter           (in the sightings) edit the chosen one; Ctrl+S saves, Esc reverts
//   Ctrl+E          edit its visit in Enter sightings
//   Ctrl+Delete     delete the sighting (Ctrl+Z undoes)
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit
import "species"

Item {
    id: root
    objectName: "speciesScreen"
    readonly property bool shown: shell.currentKey === "species"
    readonly property bool working: app.hasList && app.taxaReady
    readonly property var chosen: species.entry
    readonly property bool hasEntry: chosen.key !== undefined

    function focusList() { taxonList.forceActiveFocus() }
    function focusSightings() { if (sightingList.count > 0) sightingList.forceActiveFocus() }
    function startFilter(text) {
        filter.forceActiveFocus()
        if (text) {
            filter.text = text
            species.setFilter(text)
        } else {
            filter.selectAll()
        }
    }
    function openVisit() {
        const s = species.sighting
        if (s.sightingId === undefined || !s.canOpenVisit) return
        if (entry.openVisit(s.locationXmlId, s.dateRaw, s.time)) shell.go("enter")
    }
    onShownChanged: if (shown && working) Qt.callLater(focusList)

    Shortcut { enabled: root.shown && root.working && !deleteDialog.visible; sequence: "Ctrl+F"; onActivated: root.startFilter("") }
    Shortcut { enabled: root.shown && root.working; sequence: "Ctrl+Shift+A"; onActivated: species.setOnlySeen(!species.onlySeen) }
    Shortcut { enabled: root.shown && root.working; sequence: "Ctrl+S"; onActivated: editor.save() }
    Shortcut { enabled: root.shown && root.working; sequence: "Ctrl+E"; onActivated: root.openVisit() }
    Shortcut {
        enabled: root.shown && root.working && species.sighting.sightingId !== undefined && !app.readOnly
        sequence: "Ctrl+Del"
        onActivated: deleteDialog.open()
    }

    EmptyState {
        anchors.centerIn: parent
        visible: !root.working
        iconName: app.hasList ? "loader-circle" : "bird"
        title: app.hasList ? qsTr("Loading the taxonomy…") : qsTr("Open or import a list")
        text: app.hasList ? "" : qsTr("Ctrl+O opens a Pipit list. “Import Scythebill list” in Ctrl+K brings in a .bsxm file.")
    }

    B.SplitView {
        anchors.fill: parent
        anchors.margins: Theme.windowPad
        visible: root.working
        orientation: Qt.Horizontal
        handle: Rectangle { implicitWidth: Theme.s3; color: "transparent" }

        // ------------------------------------------------------------ taxonomy
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
                        objectName: "speciesFilter"
                        Layout.fillWidth: true
                        implicitHeight: Theme.controlHCompact
                        bare: true
                        placeholderText: qsTr("Filter species (Ctrl+F)")
                        text: species.filterText
                        onTextEdited: species.setFilter(text)
                        Keys.onDownPressed: root.focusList()
                        Keys.onReturnPressed: root.focusList()
                        Keys.onEnterPressed: root.focusList()
                        Keys.onEscapePressed: { text = ""; species.setFilter(""); root.focusList() }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.s3
                    Layout.rightMargin: Theme.s3
                    PLabel { Layout.fillWidth: true; kind: "caption"; text: qsTr("%1 species seen · %2").arg(species.speciesSeen).arg(app.displayTaxonomyName) }
                    PSwitch {
                        objectName: "onlySeenSwitch"
                        text: qsTr("Seen only")
                        checked: species.onlySeen
                        onToggled: species.setOnlySeen(checked)
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                TaxonList {
                    id: taxonList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    onEnterSightings: root.focusSightings()
                    onFilterRequested: text => root.startFilter(text)
                }
            }
        }

        // ------------------------------------------------------------ sightings
        Card {
            B.SplitView.fillWidth: true
            B.SplitView.minimumWidth: Theme.grid(360)
            padV: 0
            padH: 0
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                // Header, placed by hand: the figures on the right, the name in what's left.
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.headerH
                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: Theme.s4
                        anchors.right: figures.left
                        anchors.rightMargin: Theme.s5
                        anchors.verticalCenter: parent.verticalCenter
                        PLabel {
                            objectName: "speciesTitle"
                            width: parent.width
                            kind: "title"
                            text: root.hasEntry ? root.chosen.common : ""
                        }
                        PLabel {
                            width: parent.width
                            text: root.hasEntry ? root.chosen.scientific : ""
                            font.italic: true
                            color: Theme.textMuted
                        }
                    }
                RowLayout {
                    id: figures
                    anchors.right: parent.right
                    anchors.rightMargin: Theme.s4
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.s5
                    Repeater {
                        model: [
                            [qsTr("Sightings"), root.hasEntry ? String(root.chosen.sightings) : "–"],
                            [qsTr("First"), root.hasEntry && root.chosen.first !== "" ? root.chosen.first : "–"],
                            [qsTr("Latest"), root.hasEntry && root.chosen.last !== "" ? root.chosen.last : "–"]
                        ]
                        ColumnLayout {
                            required property var modelData
                            spacing: 0
                            PLabel { kind: "overline"; text: modelData[0] }
                            PLabel { kind: "num"; text: modelData[1]; font.pixelSize: Theme.sizeTitle }
                        }
                    }
                }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    SightingList {
                        id: sightingList
                        anchors.fill: parent
                        onBack: root.focusList()
                        onEdit: editor.focusEditor()
                    }
                    EmptyState {
                        anchors.centerIn: parent
                        visible: sightingList.count === 0
                        iconName: "binoculars"
                        title: root.hasEntry ? qsTr("Not seen yet") : qsTr("Nothing matches")
                        text: root.hasEntry ? qsTr("Sightings of this species, its subspecies and groups are listed here.") : ""
                    }
                }
            }
        }

        // ------------------------------------------------------------ the sighting
        Card {
            B.SplitView.preferredWidth: Theme.grid(300)
            B.SplitView.minimumWidth: Theme.grid(260)
            SightingEditor {
                id: editor
                anchors.fill: parent
                onBack: root.focusSightings()
                onOpenVisit: root.openVisit()
                onDeleteRequested: deleteDialog.open()
            }
        }
    }

    PDialog {
        id: deleteDialog
        objectName: "deleteSightingDialog"
        heading: qsTr("Delete this sighting?")
        onOpened: confirmDelete.forceActiveFocus()
        onClosed: root.focusSightings()
        PLabel {
            width: parent.width
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            text: species.sighting.sightingId !== undefined
                  ? qsTr("%1 on %2 at %3. Ctrl+Z undoes this.").arg(root.chosen.common)
                        .arg(species.sighting.date).arg(species.sighting.place)
                  : ""
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: deleteDialog.close() },
            PButton {
                id: confirmDelete
                objectName: "confirmDeleteSighting"
                text: qsTr("Delete")
                variant: "danger"
                onClicked: { species.deleteSighting(species.sighting.sightingId); deleteDialog.close() }
                Keys.onReturnPressed: clicked()
                Keys.onEnterPressed: clicked()
            }
        ]
    }
}
