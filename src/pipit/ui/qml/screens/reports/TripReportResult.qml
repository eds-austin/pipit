// The trip report just made: its title and totals, and what can be done with it. It's
// already on the clipboard and open in the browser; Save as Word asks where, writes the
// .docx (as Scythebill's "Save as Word Document") and opens it.
import QtCore
import QtQuick
import QtQuick.Dialogs
import QtQuick.Layouts
import Pipit

PDialog {
    id: root
    objectName: "tripReportResult"
    heading: qsTr("Trip report")
    width: Math.min(Theme.grid(520), parent ? parent.width - 2 * Theme.s7 : Theme.grid(520))

    function show() {
        open()
        saveButton.forceActiveFocus()
    }

    FileDialog {
        id: wordDialog
        title: qsTr("Save as Word document")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "docx"
        nameFilters: [qsTr("Word documents (*.docx)")]
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: reports.saveTripReportAsWord(selectedFile)
    }

    ColumnLayout {
        width: parent.width
        spacing: Theme.s4
        PLabel {
            Layout.fillWidth: true
            kind: "title"
            elide: Text.ElideRight
            text: reports.tripReportTitle
        }
        RowLayout {
            spacing: Theme.s6
            Repeater {
                model: reports.tripReportSummary
                ColumnLayout {
                    required property var modelData
                    spacing: 0
                    PLabel { kind: "kpi"; text: modelData[0] }
                    PLabel { kind: "overline"; text: modelData[1]; color: Theme.textMuted }
                }
            }
        }
        PLabel {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: Theme.textMuted
            text: qsTr("Copied to the clipboard, to paste into Word or Pages, and opened in your browser to read.")
        }
    }
    footerItem: [
        PButton { text: qsTr("Close"); variant: "ghost"; onClicked: root.close() },
        PButton { text: qsTr("Open again"); variant: "secondary"; onClicked: reports.openTripReport() },
        PButton { text: qsTr("Copy"); variant: "secondary"; onClicked: reports.copyTripReport() },
        PButton {
            id: saveButton
            objectName: "tripSaveWord"
            variant: "primary"
            text: qsTr("Save as Word…")
            onClicked: {
                wordDialog.selectedFile = wordDialog.currentFolder + "/" + reports.tripReportFileName()
                wordDialog.open()
            }
        }
    ]
}
