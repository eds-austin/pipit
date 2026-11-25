// The chosen sighting: where and when, and its details to edit. Enter or Ctrl+S saves (one
// undo step) and returns to the list; Esc puts the fields back and returns to the list. Place, date and species change
// through its visit (Enter sightings), as in Scythebill.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit
import "../locations"

ColumnLayout {
    id: root
    readonly property var current: species.sighting
    readonly property bool has: current.sightingId !== undefined
    readonly property bool writable: !app.readOnly
    readonly property var flagNames: [
        ["heardOnly", qsTr("Heard only")], ["photographed", qsTr("Photographed")],
        ["male", qsTr("Male")], ["female", qsTr("Female")],
        ["adult", qsTr("Adult")], ["immature", qsTr("Immature")]
    ]
    property var edited: ({})
    readonly property bool dirty: Object.keys(edited).length > 0
    signal back()
    signal deleteRequested()
    signal openVisit()

    function value(name) { return edited[name] !== undefined ? edited[name] : current[name] }
    function set(name, newValue) {
        const copy = Object.assign({}, edited)
        if (newValue === current[name]) delete copy[name]
        else copy[name] = newValue
        edited = copy
    }
    function revert() { edited = {}; countField.text = Qt.binding(() => root.current.count || "") ; notesField.text = Qt.binding(() => root.current.notes || "") }
    function save() {
        if (!has || !dirty) return
        const values = {}
        for (const name of ["count", "heardOnly", "photographed", "male", "female", "adult",
                            "immature", "status", "breeding", "notes"])
            values[name] = value(name)
        if (species.saveSighting(current.sightingId, values)) {
            edited = {}
            back()  // to the list, where Ctrl+Z undoes the save (text fields keep their own)
        }
    }
    function focusEditor() { if (has) countField.forceActiveFocus() }
    onCurrentChanged: revert()
    spacing: Theme.s2

    PLabel {
        Layout.fillWidth: true
        kind: "title"
        text: root.has ? root.current.date + (root.current.time !== "" ? "  " + root.current.time : "") : qsTr("No sighting chosen")
    }
    PLabel {
        Layout.fillWidth: true
        visible: root.has
        kind: "caption"
        text: root.has ? root.current.place : ""
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
    }
    Flow {
        Layout.fillWidth: true
        visible: root.has && (root.current.asRecorded !== "" || root.current.trip !== "")
        spacing: Theme.s1
        Badge { visible: root.has && root.current.asRecorded !== ""; text: root.has ? root.current.asRecorded : ""; tone: Theme.info }
        Badge { visible: root.has && root.current.trip !== ""; text: root.has ? qsTr("Trip: %1").arg(root.current.trip) : ""; neutral: true; iconName: "route" }
    }

    GridLayout {
        Layout.fillWidth: true
        Layout.topMargin: Theme.s2
        visible: root.has
        columns: 2
        columnSpacing: Theme.s3
        rowSpacing: Theme.s2
        enabled: root.writable

        PLabel { kind: "caption"; text: qsTr("Count") }
        PTextField {
            id: countField
            objectName: "sightingCount"
            Layout.fillWidth: true
            num: true
            placeholderText: qsTr("x (present)")
            text: root.current.count || ""
            onTextEdited: root.set("count", text)
            Keys.onReturnPressed: root.save()
            Keys.onEnterPressed: root.save()
            Keys.onEscapePressed: { root.revert(); root.back() }
        }
        PLabel { kind: "caption"; text: qsTr("Status") }
        PComboBox {
            id: statusBox
            objectName: "sightingStatus"
            Layout.fillWidth: true
            model: species.statusLabels
            currentIndex: species.statuses.indexOf(root.value("status") || "none")
            onActivated: index => root.set("status", species.statuses[index])
        }
        PLabel { kind: "caption"; text: qsTr("Breeding") }
        PComboBox {
            Layout.fillWidth: true
            model: species.breedingCodes
            displayText: currentText === "" ? qsTr("(None)") : currentText
            currentIndex: species.breedingCodes.indexOf(root.value("breeding") || "")
            onActivated: index => root.set("breeding", species.breedingCodes[index])
        }
        PLabel { kind: "caption"; text: qsTr("Notes") }
        PTextField {
            id: notesField
            objectName: "sightingNotes"
            Layout.fillWidth: true
            text: root.current.notes || ""
            onTextEdited: root.set("notes", text)
            Keys.onReturnPressed: root.save()
            Keys.onEnterPressed: root.save()
            Keys.onEscapePressed: { root.revert(); root.back() }
        }
    }
    GridLayout {
        Layout.fillWidth: true
        visible: root.has
        enabled: root.writable
        columns: 2
        columnSpacing: Theme.s3
        rowSpacing: Theme.s1
        Repeater {
            model: root.flagNames
            PCheckBox {
                required property var modelData
                Layout.fillWidth: true
                text: modelData[1]
                checked: root.has ? !!root.value(modelData[0]) : false
                onToggled: root.set(modelData[0], checked)
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: Theme.s2
        visible: root.has
        spacing: Theme.s2
        PButton {
            objectName: "saveSighting"
            variant: "primary"
            text: qsTr("Save")
            enabled: root.writable && root.dirty
            onClicked: root.save()
        }
        KeyHint { keys: "Ctrl+S"; subtle: true }
        Item { Layout.fillWidth: true }
        PButton {
            visible: root.dirty
            variant: "ghost"
            text: qsTr("Revert")
            onClicked: root.revert()
        }
    }

    Rectangle { Layout.fillWidth: true; Layout.topMargin: Theme.s2; Layout.preferredHeight: 1; color: Theme.border; visible: root.has }
    ColumnLayout {
        Layout.fillWidth: true
        visible: root.has
        spacing: 0
        ActionRow {
            objectName: "openVisitButton"
            Layout.fillWidth: true
            text: qsTr("Edit its visit")
            iconName: "notebook-pen"
            keys: "Ctrl+E"
            enabled: root.has && root.current.canOpenVisit && root.writable
            blockedReason: root.has && root.current.trip !== "" ? qsTr("Trip sightings are edited with their trip.") : ""
            onClicked: root.openVisit()
        }
        ActionRow {
            objectName: "deleteSightingButton"
            Layout.fillWidth: true
            text: qsTr("Delete sighting")
            iconName: "trash-2"
            keys: "Ctrl+Del"
            danger: true
            enabled: root.has && root.writable
            onClicked: root.deleteRequested()
        }
    }
    Item { Layout.fillHeight: true }
}
