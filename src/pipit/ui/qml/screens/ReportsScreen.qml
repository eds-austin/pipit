// Reports: a query built from Scythebill's conditions (rerun as it changes), the species it
// finds with Scythebill's totals, and the sightings of the chosen one. Keyboard map (F1):
//   Ctrl+Shift+A    add a condition (the first kind not used yet, as Scythebill does)
//   Ctrl+S          save the query as a report (Scythebill sees it too)
//   Ctrl+P          print (options, then the browser prints the page)
//   Ctrl+E          save as spreadsheet (options, then where; it opens once saved)
//   Ctrl+T          trip report (options; copied, opened in the browser; Save as Word)
//   Ctrl+Shift+E    save for eBird (Record Format CSV; where, then written)
//   Ctrl+Shift+C    save as Scythebill CSV (every detail; where, then written)
//   Ctrl+L          into the saved reports: Enter loads, F2 renames, Delete, Alt+Up/Down
//   Ctrl+R          into the results; Up/Down choose (family headings skipped)
//   Esc             (in the results) back to the query
import QtCore
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Dialogs
import QtQuick.Layouts
import Pipit
import "reports"

Item {
    id: root
    objectName: "reportsScreen"
    readonly property bool shown: shell.currentKey === "reports"
    readonly property bool working: app.hasList && app.taxaReady
    readonly property bool dialogOpen: saveDialog.visible || renameDialog.visible || deleteDialog.visible
                                       || printDialog.visible || spreadsheetDialog.visible
                                       || tripReportDialog.visible || tripReportResult.visible
    readonly property bool keysOn: shown && working && !dialogOpen

    function focusResults() { if (results.count > 0) { results.forceActiveFocus(); if (reports.selectedIndex < 0) reports.selectStep(0, 1) } }

    Shortcut { enabled: root.keysOn; sequence: "Ctrl+Shift+A"; onActivated: reports.addRow() }
    Shortcut { enabled: root.keysOn; sequence: "Ctrl+R"; onActivated: root.focusResults() }
    Shortcut { enabled: root.keysOn && !app.readOnly; sequence: "Ctrl+S"; onActivated: saveDialog.show() }
    Shortcut { enabled: root.keysOn; sequence: "Ctrl+L"; onActivated: saved.focusList() }
    Shortcut { enabled: root.keysOn && reports.sightingCount > 0; sequence: "Ctrl+P"; onActivated: printDialog.show() }
    Shortcut { enabled: root.keysOn && reports.sightingCount > 0 && !reports.savingSpreadsheet; sequence: "Ctrl+E"; onActivated: spreadsheetDialog.show() }
    Shortcut { enabled: root.keysOn && reports.sightingCount > 0 && !reports.makingTripReport; sequence: "Ctrl+T"; onActivated: tripReportDialog.show() }
    Shortcut { enabled: root.keysOn && reports.sightingCount > 0 && !reports.savingEBird; sequence: "Ctrl+Shift+E"; onActivated: root.saveForEBird() }

    Shortcut { enabled: root.keysOn && reports.sightingCount > 0 && !reports.savingEBird; sequence: "Ctrl+Shift+C"; onActivated: root.saveScythebillCsv() }
    function saveScythebillCsv() {
        csvDialog.selectedFile = csvDialog.currentFolder + "/" + reports.scythebillCsvFileName()
        csvDialog.open()
    }
    FileDialog {
        id: csvDialog
        title: qsTr("Save as Scythebill CSV")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "csv"
        nameFilters: [qsTr("CSV files (*.csv)")]
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: reports.saveScythebillCsv(selectedFile)
    }
    function saveForEBird() {
        ebirdDialog.selectedFile = ebirdDialog.currentFolder + "/" + reports.ebirdFileName()
        ebirdDialog.open()
    }
    // Save for eBird: Record Format CSV, in Clements (eBird's taxonomy), split past 900K
    FileDialog {
        id: ebirdDialog
        title: qsTr("Save for eBird")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "csv"
        nameFilters: [qsTr("CSV files (*.csv)")]
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: reports.saveForEBird(selectedFile)
    }

    // The result opens when a report asked for here is ready.
    property bool awaitingTripReport: false
    Connections {
        target: reports
        function onTripReportChanged() {
            if (root.awaitingTripReport && !reports.makingTripReport) {
                root.awaitingTripReport = false
                if (reports.hasTripReport)
                    tripReportResult.show()
            }
        }
    }

    EmptyState {
        anchors.centerIn: parent
        visible: !root.working
        iconName: app.hasList ? "loader-circle" : "chart-column"
        title: app.hasList ? qsTr("Loading the taxonomy…") : qsTr("Open or import a list")
        text: app.hasList ? "" : qsTr("Ctrl+O opens a Pipit list. “Import Scythebill list” in Ctrl+K brings in a .bsxm file.")
    }

    B.SplitView {
        anchors.fill: parent
        anchors.margins: Theme.windowPad
        visible: root.working
        orientation: Qt.Horizontal
        handle: Rectangle { implicitWidth: Theme.s3; color: "transparent" }

        // ------------------------------------------------------------ the query
        Card {
            B.SplitView.preferredWidth: Theme.grid(400)
            B.SplitView.minimumWidth: Theme.grid(320)
            ColumnLayout {
                anchors.fill: parent
                spacing: Theme.s2
                SavedReports {
                    id: saved
                    Layout.fillWidth: true
                    onRenameRequested: (index, name) => renameDialog.show(index, name)
                    onDeleteRequested: (index, name) => deleteDialog.show(index, name)
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                RowLayout {
                    Layout.fillWidth: true
                    SectionHeader { Layout.fillWidth: true; text: qsTr("Query") }
                    PIconButton {
                        objectName: "saveReport"
                        enabled: !app.readOnly
                        iconName: "save"
                        tip: qsTr("Save as a report (Ctrl+S)")
                        implicitWidth: Theme.controlHCompact
                        implicitHeight: Theme.controlHCompact
                        onClicked: saveDialog.show()
                    }
                    PIconButton {
                        objectName: "printReport"
                        enabled: reports.sightingCount > 0 && !reports.printing
                        iconName: "printer"
                        tip: qsTr("Print (Ctrl+P)")
                        implicitWidth: Theme.controlHCompact
                        implicitHeight: Theme.controlHCompact
                        onClicked: printDialog.show()
                    }
                    PIconButton {
                        objectName: "spreadsheetReport"
                        enabled: reports.sightingCount > 0 && !reports.savingSpreadsheet
                        iconName: "sheet"
                        tip: qsTr("Save as spreadsheet (Ctrl+E)")
                        implicitWidth: Theme.controlHCompact
                        implicitHeight: Theme.controlHCompact
                        onClicked: spreadsheetDialog.show()
                    }
                    PIconButton {
                        objectName: "saveForEBird"
                        enabled: reports.sightingCount > 0 && !reports.savingEBird
                        iconName: "arrow-up-from-line"
                        tip: qsTr("Save for eBird (Ctrl+Shift+E)")
                        implicitWidth: Theme.controlHCompact
                        implicitHeight: Theme.controlHCompact
                        onClicked: root.saveForEBird()
                    }
                    PIconButton {
                        objectName: "saveScythebillCsv"
                        enabled: reports.sightingCount > 0 && !reports.savingEBird
                        iconName: "database"
                        tip: qsTr("Save as Scythebill CSV (Ctrl+Shift+C)")
                        implicitWidth: Theme.controlHCompact
                        implicitHeight: Theme.controlHCompact
                        onClicked: root.saveScythebillCsv()
                    }
                    PIconButton {
                        objectName: "tripReport"
                        enabled: reports.sightingCount > 0 && !reports.makingTripReport
                        iconName: "file-text"
                        tip: qsTr("Trip report (Ctrl+T)")
                        implicitWidth: Theme.controlHCompact
                        implicitHeight: Theme.controlHCompact
                        onClicked: tripReportDialog.show()
                    }
                    PLabel { kind: "caption"; text: qsTr("Show") }
                    PComboBox {
                        objectName: "depthChooser"
                        Layout.preferredWidth: Theme.grid(130)
                        implicitHeight: Theme.controlHCompact
                        model: reports.depths.map(d => d[1])
                        currentIndex: reports.depths.findIndex(d => d[0] === reports.depth)
                        onActivated: i => reports.setDepth(reports.depths[i][0])
                    }
                }
                B.ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentWidth: availableWidth
                    clip: true
                    ColumnLayout {
                        width: parent.width
                        spacing: Theme.s2
                        Repeater {
                            model: reports.rows
                            QueryRow { Layout.fillWidth: true }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            PButton {
                                objectName: "addCondition"
                                compact: true
                                iconName: "plus"
                                text: qsTr("Add condition")
                                onClicked: reports.addRow()
                            }
                            KeyHint { keys: "Ctrl+Shift+A"; subtle: true }
                            Item { Layout.fillWidth: true }
                            PButton {
                                compact: true
                                variant: "ghost"
                                text: qsTr("Start over")
                                onClicked: reports.resetQuery()
                            }
                        }
                    }
                }
            }
        }

        // ------------------------------------------------------------ results
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
                        anchors.right: parent.right
                        anchors.rightMargin: Theme.s4
                        anchors.verticalCenter: parent.verticalCenter
                        PLabel {
                            objectName: "reportTotals"
                            width: parent.width
                            kind: "title"
                            text: reports.error !== "" ? qsTr("This query can't run") : reports.totals
                        }
                        PLabel {
                            width: parent.width
                            kind: "caption"
                            text: reports.error !== "" ? reports.error
                                : reports.families + (reports.sightingCount ? qsTr(" · %1 sightings").arg(Number(reports.sightingCount).toLocaleString(Qt.locale("en_US"), "f", 0)) : "")
                            color: reports.error !== "" ? Theme.warning : Theme.textMuted
                        }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                ListView {
                    id: results
                    objectName: "reportResults"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: reports.results
                    currentIndex: reports.selectedIndex
                    highlightMoveDuration: 0
                    keyNavigationEnabled: false
                    boundsBehavior: Flickable.StopAtBounds
                    reuseItems: true
                    B.ScrollBar.vertical: B.ScrollBar {}
                    onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                    readonly property int page: Math.max(1, Math.floor(height / Theme.rowHDense) - 1)
                    Keys.onPressed: event => {
                        const index = reports.selectedIndex
                        if (event.key === Qt.Key_Down) reports.selectStep(index + 1, 1)
                        else if (event.key === Qt.Key_Up) reports.selectStep(index - 1, -1)
                        else if (event.key === Qt.Key_PageDown) reports.selectStep(index + page, 1)
                        else if (event.key === Qt.Key_PageUp) reports.selectStep(index - page, -1)
                        else if (event.key === Qt.Key_Home) reports.selectStep(0, 1)
                        else if (event.key === Qt.Key_End) reports.selectStep(count - 1, -1)
                        else return
                        event.accepted = true
                    }
                    delegate: Rectangle {
                        id: item
                        required property int index
                        required property bool heading
                        required property string name
                        required property string scientific
                        required property bool countable
                        required property bool lifer
                        required property int sightings
                        readonly property bool selected: index === reports.selectedIndex
                        width: ListView.view.width
                        height: Theme.rowHDense
                        color: selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
                             : hover.hovered && !heading ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface) : "transparent"
                        Rectangle { visible: item.selected; width: 2; height: parent.height; color: results.activeFocus ? Theme.accent : Theme.borderStrong }
                        HoverHandler { id: hover; enabled: !item.heading }
                        TapHandler { enabled: !item.heading; onTapped: { reports.select(item.index); results.forceActiveFocus() } }
                        PLabel {
                            visible: item.heading
                            anchors.left: parent.left
                            anchors.leftMargin: Theme.s3
                            anchors.right: parent.right
                            height: parent.height
                            kind: "overline"
                            text: item.name
                            color: Theme.textFaint
                        }
                        RowLayout {
                            visible: !item.heading
                            anchors.fill: parent
                            anchors.leftMargin: Theme.s5
                            anchors.rightMargin: Theme.s3
                            spacing: Theme.s2
                            PLabel {
                                Layout.fillWidth: true
                                text: item.name
                                // Taxa with no countable sighting are gray, as in Scythebill.
                                color: item.countable ? Theme.text : Theme.textMuted
                            }
                            Badge { visible: item.lifer; text: qsTr("Lifer"); tone: Theme.positive }
                            Badge { visible: !item.countable; text: qsTr("Not countable"); neutral: true }
                            PLabel { kind: "num"; text: item.sightings; color: Theme.textMuted }
                        }
                    }
                }
            }
        }

        // ------------------------------------------------------------ sightings
        Card {
            B.SplitView.preferredWidth: Theme.grid(320)
            B.SplitView.minimumWidth: Theme.grid(240)
            padH: 0
            ColumnLayout {
                anchors.fill: parent
                spacing: Theme.s2
                SectionHeader { Layout.leftMargin: Theme.s4; text: qsTr("Sightings") }
                ListView {
                    objectName: "reportSightings"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: reports.sightings
                    boundsBehavior: Flickable.StopAtBounds
                    B.ScrollBar.vertical: B.ScrollBar {}
                    delegate: Item {
                        id: sighting
                        required property string date
                        required property string time
                        required property string place
                        required property string count
                        required property string details
                        width: ListView.view.width
                        height: Theme.grid(52)
                        ColumnLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.s4
                            anchors.rightMargin: Theme.s4
                            spacing: 0
                            RowLayout {
                                Layout.fillWidth: true
                                PLabel { kind: "num"; text: sighting.date + (sighting.time !== "" ? "  " + sighting.time : "") }
                                Item { Layout.fillWidth: true }
                                PLabel { kind: "num"; text: sighting.count !== "" ? sighting.count : "x"; color: Theme.textMuted }
                            }
                            PLabel { Layout.fillWidth: true; kind: "caption"; text: [sighting.place, sighting.details].filter(p => p !== "").join(" · ") }
                        }
                    }
                }
                PLabel {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.s4
                    Layout.rightMargin: Theme.s4
                    visible: reports.selectedIndex < 0
                    wrapMode: Text.WordWrap
                    color: Theme.textMuted
                    text: qsTr("Choose a species to see its sightings.")
                }
            }
        }
    }

    // ------------------------------------------------------------ dialogs

    PrintDialog { id: printDialog }
    SpreadsheetDialog { id: spreadsheetDialog }
    TripReportDialog {
        id: tripReportDialog
        onClosed: if (reports.makingTripReport) root.awaitingTripReport = true
    }
    TripReportResult { id: tripReportResult }

    PDialog {
        id: saveDialog
        objectName: "saveReportDialog"
        heading: qsTr("Save report")
        readonly property bool taken: reports.nameTaken(saveName.text.trim())
        function show() {
            saveName.text = reports.currentSaved
            open()
            saveName.forceActiveFocus()
            saveName.selectAll()
        }
        function accept() { if (saveName.text.trim() !== "" && reports.saveAs(saveName.text)) close() }
        ColumnLayout {
            width: parent.width
            spacing: Theme.s2
            PLabel { kind: "caption"; text: qsTr("Name") }
            PTextField {
                id: saveName
                objectName: "saveReportName"
                Layout.fillWidth: true
                onAccepted: saveDialog.accept()
            }
            PLabel {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: saveDialog.taken ? Theme.warning : Theme.textMuted
                text: saveDialog.taken ? qsTr("A report has this name: saving replaces it, in its place.")
                                       : qsTr("Saved in the list, so Scythebill shows it too.")
            }
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: saveDialog.close() },
            PButton {
                variant: "primary"
                text: saveDialog.taken ? qsTr("Replace") : qsTr("Save")
                enabled: saveName.text.trim() !== ""
                onClicked: saveDialog.accept()
            }
        ]
    }

    PDialog {
        id: renameDialog
        objectName: "renameReportDialog"
        property int index: -1
        property string oldName
        heading: qsTr("Rename %1").arg(oldName)
        readonly property bool taken: renameField.text.trim() !== oldName && reports.nameTaken(renameField.text.trim())
        function show(index, name) {
            renameDialog.index = index
            oldName = name
            renameField.text = name
            open()
            renameField.forceActiveFocus()
            renameField.selectAll()
        }
        function accept() {
            if (renameField.text.trim() === oldName) { close(); return }
            if (!taken && reports.renameSaved(index, renameField.text)) close()
        }
        onClosed: saved.focusList()
        ColumnLayout {
            width: parent.width
            spacing: Theme.s2
            PTextField {
                id: renameField
                Layout.fillWidth: true
                onAccepted: renameDialog.accept()
            }
            PLabel {
                visible: renameDialog.taken
                Layout.fillWidth: true
                color: Theme.warning
                text: qsTr("Another report has this name.")
            }
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: renameDialog.close() },
            PButton {
                variant: "primary"
                text: qsTr("Rename")
                enabled: renameField.text.trim() !== "" && !renameDialog.taken
                onClicked: renameDialog.accept()
            }
        ]
    }

    PDialog {
        id: deleteDialog
        objectName: "deleteReportDialog"
        property int index: -1
        property string name
        heading: qsTr("Delete %1?").arg(name)
        function show(index, name) { deleteDialog.index = index; deleteDialog.name = name; open() }
        onOpened: confirmDeleteReport.forceActiveFocus()
        onClosed: saved.focusList()
        PLabel {
            width: parent.width
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            text: qsTr("The saved report goes, from Scythebill too; no sightings change. Ctrl+Z undoes this.")
        }
        footerItem: [
            PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: deleteDialog.close() },
            PButton {
                id: confirmDeleteReport
                objectName: "confirmDeleteReport"
                text: qsTr("Delete")
                variant: "danger"
                onClicked: { reports.deleteSaved(deleteDialog.index); deleteDialog.close() }
                Keys.onReturnPressed: clicked()
                Keys.onEnterPressed: clicked()
            }
        ]
    }
}
