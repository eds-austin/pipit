// Save as spreadsheet: Scythebill's spreadsheet options (ReportXlsDialog), remembered between
// uses, then where to save the .xlsx; it opens once written, as in Scythebill.
// Families and the order of a species' sightings only apply in taxonomic order; the
// subspecies column only when showing groups or subspecies; observers only when the list
// has any. Enter goes on to choosing the file.
import QtCore
import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import Pipit

PDialog {
    id: root
    objectName: "spreadsheetDialog"
    heading: qsTr("Save as spreadsheet")
    width: Math.min(Theme.grid(720), parent ? parent.width - 2 * Theme.s7 : Theme.grid(720))
    readonly property bool taxonomic: speciesSort.currentIndex === 0
    readonly property var userOutputs: [
        ["NONE", qsTr("None")], ["USER_NAMES", qsTr("Names")],
        ["USER_ABBREVIATIONS", qsTr("Abbreviations")], ["BOTH", qsTr("Names and abbreviations")]
    ]

    function show() {
        const o = reports.spreadsheetOptions
        scientific.checked = o.includeScientific
        families.checked = o.showFamilies
        status.checked = o.showStatus
        notes.checked = o.showNotes
        subspeciesColumn.checked = o.subspeciesInSeparateColumn
        onlyCountable.checked = o.onlyCountable
        omitSp.checked = o.omitSpAndHybrid
        speciesSort.currentIndex = Math.max(0, reports.sortTypes.findIndex(s => s[0] === o.sortType))
        sightingSort.currentIndex = Math.max(0, reports.sortTypes.findIndex(s => s[0] === o.sortSightingsType))
        observers.currentIndex = Math.max(0, root.userOutputs.findIndex(u => u[0] === o.userOutput))
        howMany.text = String(o.maximumSightings)
        open()
        scientific.forceActiveFocus()
    }
    function options() {
        return {
            includeScientific: scientific.checked, showFamilies: families.checked,
            showStatus: status.checked, showNotes: notes.checked,
            subspeciesInSeparateColumn: subspeciesColumn.checked,
            onlyCountable: onlyCountable.checked, omitSpAndHybrid: omitSp.checked,
            sortType: reports.sortTypes[speciesSort.currentIndex][0],
            sortSightingsType: reports.sortTypes[sightingSort.currentIndex][0],
            userOutput: root.userOutputs[observers.currentIndex][0],
            maximumSightings: Math.min(100, Math.max(0, parseInt(howMany.text) || 0))
        }
    }
    function accept() {
        fileDialog.chosenOptions = root.options()
        fileDialog.selectedFile = fileDialog.currentFolder + "/" + reports.spreadsheetFileName()
        close()
        fileDialog.open()
    }

    FileDialog {
        id: fileDialog
        property var chosenOptions: ({})
        title: qsTr("Save as spreadsheet")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "xlsx"
        nameFilters: [qsTr("Spreadsheets (*.xlsx)")]
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: reports.saveSpreadsheet(chosenOptions, selectedFile)
    }

    // Enter goes on, wherever the focus is in the dialog.
    Shortcut { enabled: root.visible && !reports.savingSpreadsheet; sequences: ["Return", "Enter"]; onActivated: root.accept() }

    ColumnLayout {
        width: parent.width
        spacing: Theme.s5
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s6
            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 1
                Layout.fillWidth: true
                spacing: Theme.s2
                PLabel { kind: "overline"; text: qsTr("What data?"); color: Theme.textMuted }
                PCheckBox { id: scientific; objectName: "xlsxScientific"; text: qsTr("Scientific names") }
                PCheckBox { id: families; text: qsTr("Families"); enabled: root.taxonomic }
                PCheckBox { id: status; text: qsTr("Threatened status") }
                PCheckBox { id: notes; objectName: "xlsxNotes"; text: qsTr("Notes, numbers and details") }
                PCheckBox {
                    id: subspeciesColumn
                    text: qsTr("Subspecies in their own column")
                    visible: reports.depth !== "species"
                }
                PLabel {
                    kind: "caption"; text: qsTr("Observers"); Layout.topMargin: Theme.s1
                    visible: reports.hasObservers
                }
                PComboBox {
                    id: observers
                    objectName: "xlsxObservers"
                    Layout.fillWidth: true
                    visible: reports.hasObservers
                    model: root.userOutputs.map(u => u[1])
                }
            }
            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 1
                Layout.fillWidth: true
                spacing: Theme.s2
                PLabel { kind: "overline"; text: qsTr("Which species?"); color: Theme.textMuted }
                PCheckBox { id: onlyCountable; text: qsTr("Omit uncountable") }
                PCheckBox { id: omitSp; text: qsTr("Omit sp. and hybrids") }
                PLabel { kind: "caption"; text: qsTr("Sort species by"); Layout.topMargin: Theme.s1 }
                PComboBox {
                    id: speciesSort
                    objectName: "xlsxSpeciesSort"
                    Layout.fillWidth: true
                    model: reports.sortTypes.map(s => s[1])
                }
            }
            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 1
                Layout.fillWidth: true
                spacing: Theme.s2
                PLabel { kind: "overline"; text: qsTr("Which sightings?"); color: Theme.textMuted }
                PLabel { kind: "caption"; text: qsTr("Sightings per species") }
                PTextField {
                    id: howMany
                    objectName: "xlsxHowMany"
                    Layout.preferredWidth: Theme.grid(72)
                    validator: IntValidator { bottom: 0; top: 100 }
                    onAccepted: root.accept()
                }
                PLabel { kind: "caption"; text: qsTr("Sort sightings by"); Layout.topMargin: Theme.s1; color: root.taxonomic ? Theme.text : Theme.textFaint }
                PComboBox {
                    id: sightingSort
                    Layout.fillWidth: true
                    enabled: root.taxonomic
                    model: reports.sortTypes.map(s => s[2])
                }
            }
        }
        PLabel {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            kind: "caption"
            color: Theme.textMuted
            text: qsTr("An .xlsx with the same cells as Scythebill's. It opens once saved.")
        }
    }
    footerItem: [
        PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: root.close() },
        PButton {
            objectName: "xlsxSaveButton"
            variant: "primary"
            text: qsTr("Save…")
            enabled: !reports.savingSpreadsheet
            onClicked: root.accept()
        }
    ]
}
