// Trip report: Scythebill's trip report options (TripReportDialog), remembered between uses,
// plus what to show (species, groups or subspecies; the Reports screen's to start) and the
// distance unit. From the Reports screen it reports on the query; given trips (the Trips
// screen), on their sightings. Enter makes the report, which is copied to the clipboard and opened in the browser;
// then TripReportResult offers it again, and Save as Word.
import QtQuick
import QtQuick.Layouts
import Pipit

PDialog {
    id: root
    objectName: "tripReportDialog"
    heading: qsTr("Trip report")
    width: Math.min(Theme.grid(620), parent ? parent.width - 2 * Theme.s7 : Theme.grid(620))
    property var tripIds: []

    function show(ids) {
        tripIds = ids || []
        const o = reports.tripReportOptions
        scientific.checked = o.includeScientific
        itinerary.checked = o.itinerary
        table.checked = o.speciesTable
        list.checked = o.speciesList
        status.checked = o.showStatus
        lifers.checked = o.lifersInBold
        depth.currentIndex = Math.max(0, reports.depths.findIndex(d => d[0] === o.depth))
        miles.currentIndex = o.useMiles ? 1 : 0
        open()
        itinerary.forceActiveFocus()
    }
    function accept() {
        const options = {
            includeScientific: scientific.checked, itinerary: itinerary.checked,
            speciesTable: table.checked, speciesList: list.checked,
            showStatus: status.checked, lifersInBold: lifers.checked,
            depth: reports.depths[depth.currentIndex][0], useMiles: miles.currentIndex === 1
        }
        if (tripIds.length > 0)
            reports.makeTripsTripReport(options, tripIds)
        else
            reports.makeTripReport(options)
        close()
    }

    // Enter makes the report, wherever the focus is in the dialog.
    Shortcut { enabled: root.visible && !reports.makingTripReport; sequences: ["Return", "Enter"]; onActivated: root.accept() }

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
                PLabel { kind: "overline"; text: qsTr("What to include?"); color: Theme.textMuted }
                PCheckBox { id: itinerary; objectName: "tripItinerary"; text: qsTr("Itinerary") }
                PCheckBox { id: table; text: qsTr("Species by day (table)") }
                PCheckBox { id: list; text: qsTr("Species list") }
            }
            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                Layout.preferredWidth: 1
                Layout.fillWidth: true
                spacing: Theme.s2
                PLabel { kind: "overline"; text: qsTr("How?"); color: Theme.textMuted }
                PCheckBox { id: scientific; text: qsTr("Scientific names") }
                PCheckBox { id: status; text: qsTr("Threatened status") }
                PCheckBox { id: lifers; text: qsTr("Lifers in bold") }
                RowLayout {
                    Layout.topMargin: Theme.s1
                    spacing: Theme.s3
                    PLabel { kind: "caption"; text: qsTr("Show") }
                    PComboBox {
                        id: depth
                        objectName: "tripDepth"
                        Layout.preferredWidth: Theme.grid(130)
                        model: reports.depths.map(d => d[1])
                    }
                    PLabel { kind: "caption"; text: qsTr("Distances in") }
                    PComboBox {
                        id: miles
                        Layout.preferredWidth: Theme.grid(120)
                        model: [qsTr("kilometers"), qsTr("miles")]
                    }
                }
            }
        }
        PLabel {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            kind: "caption"
            color: Theme.textMuted
            text: qsTr("The report is copied to the clipboard, to paste into Word or Pages, and opens in your browser. It can then be saved as a Word document. The species table is left out for more than 200 visits.")
        }
    }
    footerItem: [
        PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: root.close() },
        PButton {
            objectName: "tripReportButton"
            variant: "primary"
            text: qsTr("Make report")
            enabled: !reports.makingTripReport
            onClicked: root.accept()
        }
    ]
}
