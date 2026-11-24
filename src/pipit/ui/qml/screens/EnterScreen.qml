// Enter sightings: a date, up to four locations (A-D) each with its own visit details, and
// the birds, each with a count per location. Keyboard map (also in F1):
//   date field  "t" today, "y" yesterday, "+"/"-" a day later/earlier, or 2026-11-24
//   Tab         date -> place A -> protocol (one letter) -> start, duration, km, party -> ...
//   Alt+1..4    make location A-D active (adds it if it is the next one) and edit its place
//   Alt+Shift+2..4  remove location B-D
//   Ctrl+J      species field: "mall 12", "amro a3 b1" (counts per location), Enter adds
//   Down        from the species field into the grid (see EntryGrid)
//   Ctrl+Shift+L  walk the checklist of the active location: digits then Enter to add,
//               "/" filters, Tab next location, Esc back
//   Ctrl+Enter  save the day (each location becomes its own visit); Ctrl+Z undoes it
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit
import "entry"

Item {
    id: root
    objectName: "enterScreen"
    readonly property bool shown: shell.currentKey === "enter"
    readonly property bool working: app.hasList && app.taxaReady && entry.ready

    function focusSpecies(text) {
        species.forceActiveFocus()
        if (text !== undefined && text !== "") {
            species.text = species.text + text
            species.queryEdited(species.text)
        }
    }
    function focusSlot(index) {
        if (index >= entry.slotCount) {
            if (index !== entry.slotCount) return
            entry.addSlot()
        }
        entry.setActiveSlot("ABCD"[index])
        Qt.callLater(() => { const card = slotCards.itemAt(index); if (card) card.focusPlace() })
    }
    onShownChanged: if (shown && working) Qt.callLater(() => date.forceActiveFocus())

    Shortcut { enabled: root.shown && root.working; sequence: "Ctrl+J"; onActivated: root.focusSpecies() }
    Shortcut {
        enabled: root.shown && root.working
        sequences: ["Ctrl+Return", "Ctrl+Enter"]
        onActivated: entry.finish()
    }
    Shortcut {
        enabled: root.shown && root.working
        sequence: "Ctrl+Shift+L"
        onActivated: checklistList.forceActiveFocus()
    }
    Instantiator {
        model: 4
        delegate: Shortcut {
            required property int index
            enabled: root.shown && root.working
            sequence: "Alt+" + (index + 1)
            onActivated: root.focusSlot(index)
        }
    }
    Instantiator {
        model: 3
        delegate: Shortcut {
            required property int index
            enabled: root.shown && root.working
            sequence: "Alt+Shift+" + (index + 2)
            onActivated: entry.removeSlot("BCD"[index])
        }
    }

    // ---------------------------------------------------------------- not ready
    EmptyState {
        anchors.centerIn: parent
        visible: !root.working
        iconName: app.hasList && !app.readOnly ? "loader-circle" : "notebook-pen"
        title: !app.hasList ? qsTr("Open or import a list")
             : app.readOnly ? qsTr("This list is read-only")
             : qsTr("Loading the taxonomy…")
        text: !app.hasList ? qsTr("Ctrl+O opens a Pipit list. “Import Scythebill list” in Ctrl+K brings in a .bsxm file.")
            : app.readOnly ? app.problems.join("\n") : ""
    }

    // ---------------------------------------------------------------- entry
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.windowPad
        spacing: Theme.sectionGap
        visible: root.working

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s3
            PIcon { name: "calendar" }
            PTextField {
                id: date
                objectName: "dateField"
                Layout.preferredWidth: Theme.grid(150)
                num: true
                text: entry.dateText
                placeholderText: qsTr("Date")
                Accessible.name: qsTr("Date: t today, y yesterday, + or − a day")
                function apply() { if (!entry.setDate(text)) text = Qt.binding(() => entry.dateText) }
                Keys.onReturnPressed: apply()
                Keys.onEnterPressed: apply()
                Keys.onTabPressed: event => { apply(); root.focusSlot(0); event.accepted = true }
            }
            PLabel { kind: "caption"; text: qsTr("t today · y yesterday · + / − a day") }
            Item { Layout.fillWidth: true }
            Badge { text: app.displayTaxonomyName; neutral: true }
            PLabel { kind: "num"; text: entry.summary; color: Theme.textMuted }
            PButton {
                objectName: "addLocationButton"
                visible: entry.slotCount < 4
                text: qsTr("Add location")
                iconName: "plus"
                compact: true
                onClicked: root.focusSlot(entry.slotCount)
            }
            PButton {
                objectName: "finishButton"
                variant: "primary"
                text: qsTr("Save day")
                enabled: entry.canSave
                onClicked: entry.finish()
            }
            KeyHint { keys: "Ctrl+Enter"; subtle: true }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: Math.min(entry.slotCount, 2)
            columnSpacing: Theme.s2
            rowSpacing: Theme.s2
            Repeater {
                id: slotCards
                model: entry.slots
                SlotCard {
                    required property var model
                    slot: model
                    Layout.fillWidth: true
                    onDone: root.focusSpecies()
                }
            }
        }

        B.SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal
            handle: Rectangle { implicitWidth: Theme.s2; color: "transparent" }

            Card {
                B.SplitView.fillWidth: true
                padV: 0
                padH: 0
                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0
                    EntryGrid {
                        id: grid
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        onTypeToSpecies: text => root.focusSpecies(text)
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.margins: Theme.s2
                        spacing: Theme.s2
                        PIcon { name: "search"; Layout.leftMargin: Theme.s2 }
                        SuggestField {
                            id: species
                            objectName: "speciesField"
                            Layout.fillWidth: true
                            bare: true
                            placeholderText: qsTr("Species (Ctrl+J): “mall 12”, “amro a3 b1”; Enter adds")
                            suggestions: entry.matches
                            primaryRole: "name"
                            secondaryRole: "scientific"
                            tertiaryRole: "status"
                            onQueryEdited: q => entry.searchSpecies(q)
                            onChosen: index => {
                                const row = entry.chooseSpecies(index)
                                text = ""
                                if (row >= 0) grid.showRow(row)
                            }
                            onEscaped: text = ""
                            Keys.onDownPressed: event => {
                                if (open) { event.accepted = false; return }
                                grid.focusRow(grid.count - 1)
                            }
                        }
                    }
                }
            }

            Card {
                B.SplitView.preferredWidth: Theme.sidePaneW
                B.SplitView.minimumWidth: Theme.grid(240)
                ColumnLayout {
                    anchors.fill: parent
                    spacing: Theme.s2
                    RowLayout {
                        Layout.fillWidth: true
                        SectionHeader { Layout.fillWidth: true; text: qsTr("Checklist · location %1").arg(entry.activeSlot) }
                        KeyHint { keys: "Ctrl+Shift+L"; subtle: true }
                    }
                    PTextField {
                        id: checklistFilter
                        objectName: "checklistFilter"
                        Layout.fillWidth: true
                        implicitHeight: Theme.controlHCompact
                        placeholderText: qsTr("Filter (/)")
                        onTextEdited: entry.filterChecklist(text)
                        Keys.onDownPressed: checklistList.forceActiveFocus()
                        Keys.onEscapePressed: { text = ""; entry.filterChecklist(""); checklistList.forceActiveFocus() }
                    }
                    PLabel {
                        visible: checklistList.count === 0
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        color: Theme.textMuted
                        text: qsTr("Choose a place to see its checklist.")
                    }
                    ListView {
                        id: checklistList
                        objectName: "checklistList"
                        property string countBuffer: ""
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: entry.checklist
                        keyNavigationEnabled: true
                        highlightMoveDuration: 0
                        B.ScrollBar.vertical: B.ScrollBar {}
                        onActiveFocusChanged: countBuffer = ""
                        Keys.onPressed: event => {
                            if (/^[0-9~x]$/.test(event.text)) {
                                countBuffer += event.text
                            } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                                       && !(event.modifiers & Qt.ControlModifier)) {
                                entry.checklistEnter(currentIndex, countBuffer)
                                countBuffer = ""
                                incrementCurrentIndex()
                            } else if (event.key === Qt.Key_Backspace) {
                                countBuffer = countBuffer.slice(0, -1)
                            } else if (event.text === "/") {
                                checklistFilter.forceActiveFocus()
                            } else if (event.key === Qt.Key_Tab) {
                                const letters = "ABCD".substring(0, entry.slotCount)
                                entry.setActiveSlot(letters[(letters.indexOf(entry.activeSlot) + 1) % letters.length])
                            } else if (event.key === Qt.Key_Escape) {
                                root.focusSpecies()
                            } else {
                                return
                            }
                            event.accepted = true
                        }
                        delegate: Rectangle {
                            id: item
                            required property int index
                            required property string name
                            required property string status
                            required property string count
                            width: ListView.view.width
                            height: Theme.rowHDense
                            radius: Theme.radiusSm
                            color: ListView.isCurrentItem && checklistList.activeFocus
                                   ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface) : "transparent"
                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.s2
                                anchors.rightMargin: Theme.s2
                                PLabel {
                                    Layout.fillWidth: true
                                    text: item.name
                                    color: item.count !== "" ? Theme.text : Theme.textMuted
                                }
                                Badge { visible: item.status !== ""; text: item.status; tone: Theme.warning }
                                PLabel {
                                    kind: "num"
                                    text: item.ListView.isCurrentItem && checklistList.countBuffer !== ""
                                          ? checklistList.countBuffer + "▏" : item.count
                                    color: Theme.accent
                                }
                            }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                    SectionHeader { text: qsTr("Before saving") }
                    Repeater {
                        model: entry.problems
                        RowLayout {
                            required property string modelData
                            Layout.fillWidth: true
                            spacing: Theme.s2
                            PIcon {
                                name: modelData.startsWith("Note") ? "info" : "triangle-alert"
                                size: Theme.iconSm
                                color: modelData.startsWith("Note") ? Theme.textMuted : Theme.warning
                            }
                            PLabel { Layout.fillWidth: true; text: modelData; wrapMode: Text.WordWrap }
                        }
                    }
                    PLabel {
                        visible: entry.problems.length === 0
                        text: qsTr("Ready to save.")
                        color: Theme.positive
                    }
                }
            }
        }
    }
}
