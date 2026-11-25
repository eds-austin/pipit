// Print: Scythebill's print options (ReportPrintDialog), remembered between uses. The page
// opens in the browser, which prints it (as in Scythebill, so it prints the same).
// Families only apply in taxonomic order; how many sightings and their order only when not
// compact and in taxonomic order. Enter prints.
import QtQuick
import QtQuick.Layouts
import Pipit

PDialog {
    id: root
    objectName: "printDialog"
    heading: qsTr("Print")
    width: Math.min(Theme.grid(680), parent ? parent.width - 2 * Theme.s7 : Theme.grid(680))
    readonly property bool taxonomic: speciesSort.currentIndex === 0
    readonly property bool sightingsApply: !compact.checked && taxonomic

    function show() {
        const o = reports.printOptions
        compact.checked = o.compact
        scientific.checked = o.includeScientific
        families.checked = o.showFamilies
        status.checked = o.showStatus
        onlyCountable.checked = o.onlyCountable
        omitSp.checked = o.omitSpAndHybrid
        speciesSort.currentIndex = Math.max(0, reports.sortTypes.findIndex(s => s[0] === o.sortType))
        sightingSort.currentIndex = Math.max(0, reports.sortTypes.findIndex(s => s[0] === o.sortSightingsType))
        howMany.text = String(o.maximumSightings)
        open()
        compact.forceActiveFocus()
    }
    function accept() {
        reports.printReport({
            compact: compact.checked, includeScientific: scientific.checked,
            showFamilies: families.checked, showStatus: status.checked,
            onlyCountable: onlyCountable.checked, omitSpAndHybrid: omitSp.checked,
            sortType: reports.sortTypes[speciesSort.currentIndex][0],
            sortSightingsType: reports.sortTypes[sightingSort.currentIndex][0],
            maximumSightings: Math.min(100, Math.max(0, parseInt(howMany.text) || 0))
        })
        close()
    }

    // Enter prints, wherever the focus is in the dialog.
    Shortcut { enabled: root.visible && !reports.printing; sequences: ["Return", "Enter"]; onActivated: root.accept() }

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
                PCheckBox { id: compact; objectName: "printCompact"; text: qsTr("Compact (three columns)") }
                PCheckBox { id: scientific; text: qsTr("Scientific names") }
                PCheckBox { id: families; text: qsTr("Families"); enabled: root.taxonomic }
                PCheckBox { id: status; text: qsTr("Threatened status") }
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
                    objectName: "printSpeciesSort"
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
                PLabel { kind: "caption"; text: qsTr("Sightings per species"); color: root.sightingsApply ? Theme.text : Theme.textFaint }
                PTextField {
                    id: howMany
                    objectName: "printHowMany"
                    Layout.preferredWidth: Theme.grid(72)
                    enabled: root.sightingsApply
                    validator: IntValidator { bottom: 0; top: 100 }
                    onAccepted: root.accept()
                }
                PLabel { kind: "caption"; text: qsTr("Sort sightings by"); Layout.topMargin: Theme.s1; color: root.sightingsApply ? Theme.text : Theme.textFaint }
                PComboBox {
                    id: sightingSort
                    Layout.fillWidth: true
                    enabled: root.sightingsApply
                    model: reports.sortTypes.map(s => s[2])
                }
            }
        }
        PLabel {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            kind: "caption"
            color: Theme.textMuted
            text: qsTr("The page opens in your browser, which prints it, as from Scythebill.")
        }
    }
    footerItem: [
        PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: root.close() },
        PButton {
            objectName: "printButton"
            variant: "primary"
            text: qsTr("Print")
            enabled: !reports.printing
            onClicked: root.accept()
        }
    ]
}
