// Importing an eBird "My Data" file: the backend (imports) walks through Scythebill's
// questions, one page each — only the new dates?, names Pipit didn't know, sightings already
// in the list — then a review of what will change. Import stores it as one undo step (after
// a backup); closing at any point before that changes nothing.
import QtQuick
import QtQuick.Layouts
import Pipit

PDialog {
    id: root
    objectName: "importDialog"
    heading: imports.formatName ? qsTr("Import: %1").arg(imports.formatName) : qsTr("Import sightings")
    width: Math.min(Theme.grid(680), parent ? parent.width - 2 * Theme.s7 : Theme.grid(680))
    readonly property string stage: imports.stage
    readonly property var d: imports.details || ({})

    function show() { open(); focusPage() }
    function focusPage() {
        if (stage === "names") nameField.forceActiveFocus()
        else if (stage === "dates") onlyNew.forceActiveFocus()
        else if (stage === "allDates") anyway.forceActiveFocus()
        else if (stage === "duplicates") (d.all ? importAll : drop).forceActiveFocus()
        else if (stage === "review") importButton.forceActiveFocus()
        else if (stage === "failed") closeButton.forceActiveFocus()
        else body.forceActiveFocus()  // working: nothing to press
    }
    onStageChanged: {
        if (stage === "idle" || stage === "done") close()
        else Qt.callLater(focusPage)
    }
    onRejected: imports.cancel()

    ColumnLayout {
        id: body
        width: parent.width
        spacing: Theme.s4
        activeFocusOnTab: false

        PLabel {
            Layout.fillWidth: true
            kind: "caption"
            elide: Text.ElideMiddle
            text: imports.fileName
        }

        // Working
        RowLayout {
            visible: root.stage === "reading" || root.stage === "storing"
            spacing: Theme.s3
            PIcon { name: "loader-circle"; size: Theme.iconMd; color: Theme.accent }
            PLabel {
                text: root.stage === "storing" ? qsTr("Saving the import (a backup first)…")
                                               : qsTr("Reading the file…")
            }
        }

        // Only the new dates?
        PLabel {
            visible: root.stage === "dates"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: qsTr("%1 of the %2 dates in this file have no sightings in your list yet (%3 to %4). Import only those dates? The others look like ones you imported before.")
                .arg(root.d.new).arg(root.d.inFile).arg(root.d.first).arg(root.d.last)
        }
        PLabel {
            visible: root.stage === "allDates"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: qsTr("Every date in this file (%1) already has sightings in your list, so it was probably imported before. Import it anyway?").arg(root.d.inFile)
        }

        // Names Pipit didn't know
        ColumnLayout {
            visible: root.stage === "names"
            Layout.fillWidth: true
            spacing: Theme.s3
            readonly property var current: imports.currentName || ({})
            PLabel {
                kind: "overline"
                text: qsTr("Name %1 of %2 Pipit didn't recognize").arg(imports.nameIndex + 1).arg(imports.nameCount)
            }
            PLabel { kind: "title"; Layout.fillWidth: true; wrapMode: Text.WordWrap; text: parent.current.common || parent.current.scientific || "" }
            PLabel {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: Theme.textMuted
                visible: text !== ""
                text: [parent.current.common ? parent.current.scientific : "", parent.current.subspecies]
                    .filter(t => t).join(" ")
            }
            PLabel {
                Layout.fillWidth: true
                kind: "caption"
                wrapMode: Text.WordWrap
                visible: (parent.current.places || "") !== ""
                text: qsTr("Seen at %1").arg(parent.current.places || "")
            }
            SuggestField {
                id: nameField
                objectName: "importNameField"
                Layout.fillWidth: true
                placeholderText: qsTr("Which species is it? Type part of a name, Enter picks it")
                suggestions: imports.matches
                primaryRole: "name"
                secondaryRole: "scientific"
                onQueryEdited: q => imports.searchSpecies(q)
                onChosen: index => { imports.pickMatch(index); text = "" }
                onEscaped: if (text === "") root.reject()
            }
            PLabel {
                kind: "caption"
                text: qsTr("Leave it out (Ctrl+L) to import everything else; its rows can be saved to a file afterwards.")
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
        }

        // Sightings already in the list
        PLabel {
            visible: root.stage === "duplicates"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: root.d.all
                ? qsTr("All %1 sightings are already in your list (same date, time and species).").arg(root.d.total)
                : qsTr("%1 of the %2 sightings are already in your list (same date, time and species).").arg(root.d.duplicates).arg(root.d.total)
        }

        // Review
        ColumnLayout {
            visible: root.stage === "review"
            Layout.fillWidth: true
            spacing: Theme.s4
            RowLayout {
                spacing: Theme.s3
                KpiCard { label: qsTr("Sightings to add"); value: String(root.d.added || 0) }
                KpiCard {
                    label: qsTr("Replaced"); value: String(root.d.removed || 0)
                    sub: qsTr("already in your list")
                    visible: (root.d.removed || 0) > 0
                }
                KpiCard { label: qsTr("New places"); value: String(root.d.newPlaces || 0) }
                KpiCard {
                    label: qsTr("Checklists"); value: String((root.d.visitsAdded || 0) + (root.d.visitsReplaced || 0))
                    sub: (root.d.visitsReplaced || 0) > 0 ? qsTr("%1 replaced").arg(root.d.visitsReplaced) : ""
                }
            }
            PLabel { kind: "overline"; text: qsTr("New places"); visible: placeList.count > 0 }
            ListView {
                id: placeList
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(count, 6) * Theme.rowHDense
                visible: count > 0
                clip: true
                model: root.d.places || []
                delegate: PLabel {
                    required property var modelData
                    width: ListView.view.width
                    height: Theme.rowHDense
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    text: modelData
                }
            }
            ColumnLayout {
                spacing: Theme.s1
                StatusChip {
                    visible: (root.d.failed || 0) > 0
                    kind: "warning"
                    text: qsTr("%n rows not imported (names left out, or unreadable)", "", root.d.failed || 0)
                }
                StatusChip {
                    visible: (root.d.updatedPlaces || 0) > 0
                    kind: "info"
                    text: qsTr("%n of your places get coordinates or an eBird hotspot", "", root.d.updatedPlaces || 0)
                }
                StatusChip {
                    visible: (root.d.spuhsDropped || 0) > 0
                    kind: "neutral"
                    text: qsTr("%n eBird “sp.” rows left out", "", root.d.spuhsDropped || 0)
                }
                StatusChip {
                    visible: (root.d.spToResolve || 0) > 0
                    kind: "info"
                    text: qsTr("%n names fit more than one species there; imported as a “sp.”", "", root.d.spToResolve || 0)
                }
            }
        }

        // Failed
        RowLayout {
            visible: root.stage === "failed"
            Layout.fillWidth: true
            spacing: Theme.s3
            PIcon { name: "octagon-alert"; size: Theme.iconMd; color: Theme.negative; Layout.alignment: Qt.AlignTop }
            PLabel {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("The file was not imported: %1").arg(imports.error)
            }
        }
    }

    // The page's main answer (what Enter does unless a button has the focus).
    function primary() {
        if (stage === "dates") imports.answerDates(true)
        else if (stage === "allDates") imports.importAnyway()
        else if (stage === "duplicates") imports.answerDuplicates(d.all ? "importAll" : "drop")
        else if (stage === "review") imports.confirm()
        else if (stage === "failed") reject()
    }
    // Enter presses the focused button, else gives the page's main answer; on the names
    // page the species field takes Enter itself.
    Shortcut {
        enabled: root.visible && root.stage !== "names"
        sequences: ["Return", "Enter"]
        onActivated: {
            const focused = closeButton.Window.activeFocusItem
            if (focused && focused.clicked && focused.visible && focused.enabled) focused.clicked()
            else root.primary()
        }
    }
    Shortcut { enabled: root.visible && root.stage === "names"; sequence: "Ctrl+L"; onActivated: imports.leaveOut() }
    Shortcut { enabled: root.visible && root.stage === "names"; sequence: "Alt+Left"; onActivated: imports.previousName() }

    footerItem: [
        PButton {
            id: closeButton
            text: root.stage === "failed" ? qsTr("Close") : qsTr("Cancel")
            variant: "ghost"
            enabled: root.stage !== "storing"
            onClicked: root.reject()
        },
        // dates
        PButton { visible: root.stage === "dates"; text: qsTr("All dates"); variant: "secondary"; onClicked: imports.answerDates(false) },
        PButton { id: onlyNew; objectName: "importOnlyNew"; visible: root.stage === "dates"; text: qsTr("Only new dates"); variant: "primary"; onClicked: imports.answerDates(true) },
        // allDates
        PButton { id: anyway; visible: root.stage === "allDates"; text: qsTr("Import anyway"); variant: "primary"; onClicked: imports.importAnyway() },
        // names
        PButton { visible: root.stage === "names" && imports.nameIndex > 0; text: qsTr("Back"); variant: "ghost"; onClicked: imports.previousName() },
        PButton { objectName: "importLeaveOut"; visible: root.stage === "names"; text: qsTr("Leave out"); variant: "secondary"; onClicked: imports.leaveOut() },
        // duplicates
        PButton { id: drop; objectName: "importDrop"; visible: root.stage === "duplicates" && !root.d.all; text: qsTr("Leave them out"); variant: "primary"; onClicked: imports.answerDuplicates("drop") },
        PButton { visible: root.stage === "duplicates"; text: qsTr("Replace them"); variant: "secondary"; onClicked: imports.answerDuplicates("overwrite") },
        PButton { id: importAll; visible: root.stage === "duplicates"; text: qsTr("Import them too"); variant: root.d.all ? "primary" : "secondary"; onClicked: imports.answerDuplicates("importAll") },
        // review
        PButton { visible: root.stage === "review" && (root.d.failed || 0) > 0; text: qsTr("Save rows not imported"); variant: "ghost"; onClicked: imports.saveFailedRows() },
        PButton {
            id: importButton
            objectName: "importStore"
            visible: root.stage === "review"
            text: qsTr("Import")
            variant: "primary"
            onClicked: imports.confirm()
        }
    ]
}
