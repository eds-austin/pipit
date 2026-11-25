// F1: the keyboard shortcuts, everywhere and per screen.
import QtQuick
import QtQuick.Layouts
import Pipit

PDialog {
    id: root
    heading: qsTr("Keyboard shortcuts")
    width: Math.min(Theme.grid(720), parent ? parent.width - 2 * Theme.s7 : Theme.grid(720))

    readonly property var globalKeys: [
        ["Ctrl+K", qsTr("Search or run a command")],
        ["Ctrl+N", qsTr("New sightings entry")],
        ["Alt+Left", qsTr("Back")],
        ["Ctrl+B", qsTr("Collapse or expand the sidebar")],
        ["F1", qsTr("Show this list")],
        ["Ctrl+Z", qsTr("Undo the last saved change")],
        ["Ctrl+Shift+Z", qsTr("Redo")],
        ["Ctrl+O", qsTr("Open a list")],
        ["Ctrl+Q", qsTr("Quit")]
    ]
    readonly property var entryKeys: [
        ["t · y · + · −", qsTr("Date: today, yesterday, a day later or earlier")],
        ["Tab", qsTr("Date, place, protocol letter, start, effort…")],
        ["Alt+1…4", qsTr("Location A–D (adds the next one)")],
        ["Alt+Shift+2…4", qsTr("Remove location B–D")],
        ["Ctrl+Enter", qsTr("In a place field: a new place")],
        ["Ctrl+J", qsTr("Species: “mall 12”, “amro a3 b1”, “a/b” sp., “a+b” hybrid")],
        ["↓ · ← →", qsTr("Into the grid; choose a location column")],
        ["0–9 ~ x", qsTr("Type a count in the grid (x: present)")],
        ["Delete", qsTr("Untick the cell (Ctrl+Delete removes the row)")],
        ["Alt+H P M F U J", qsTr("Heard, photo, male, female, adult, immature")],
        ["Ctrl+Shift+L", qsTr("Walk the checklist: digits, Enter; / filters")],
        ["Ctrl+Enter", qsTr("Save the day (one visit per location)")]
    ]
    readonly property var speciesKeys: [
        ["Ctrl+F · /", qsTr("Filter species (or just start typing)")],
        ["Ctrl+Shift+A", qsTr("Every species, or only those seen")],
        ["Enter · Esc", qsTr("Into its sightings; Enter edits one, Esc back")],
        ["Ctrl+S", qsTr("Save the sighting (Enter in a field too)")],
        ["Ctrl+E", qsTr("Edit the sighting's visit")],
        ["Ctrl+Delete", qsTr("Delete the sighting")]
    ]
    readonly property var locationKeys: [
        ["Ctrl+F · /", qsTr("Filter places (or just start typing)")],
        ["→ · ←", qsTr("Open a place, or close it and go up")],
        ["Enter · Esc", qsTr("Into the species seen there, and back")],
        ["Insert", qsTr("New place inside the chosen one")],
        ["F2", qsTr("Edit the place")],
        ["Delete", qsTr("Delete it (sightings move up a level)")],
        ["Ctrl+M", qsTr("Move it into another place")],
        ["Ctrl+Shift+M", qsTr("Merge it into another place")],
        ["Ctrl+E", qsTr("Its visits: Enter opens one to edit")]
    ]

    GridLayout {
        width: parent.width
        columns: 2
        columnSpacing: Theme.s7
        rowSpacing: Theme.s1

        SectionHeader { text: qsTr("Screens"); Layout.columnSpan: 2 }
        Repeater {
            model: shell.screens
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.s3
                PIcon { name: modelData.icon; size: Theme.iconSm }
                PLabel { Layout.fillWidth: true; text: modelData.title }
                KeyHint { keys: modelData.shortcut }
            }
        }
        SectionHeader { text: qsTr("Enter sightings"); Layout.columnSpan: 2; Layout.topMargin: Theme.s3 }
        Repeater {
            model: root.entryKeys
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.s3
                PLabel { Layout.fillWidth: true; text: modelData[1] }
                KeyHint { keys: modelData[0] }
            }
        }
        SectionHeader { text: qsTr("Species"); Layout.columnSpan: 2; Layout.topMargin: Theme.s3 }
        Repeater {
            model: root.speciesKeys
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.s3
                PLabel { Layout.fillWidth: true; text: modelData[1] }
                KeyHint { keys: modelData[0] }
            }
        }
        SectionHeader { text: qsTr("Locations"); Layout.columnSpan: 2; Layout.topMargin: Theme.s3 }
        Repeater {
            model: root.locationKeys
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.s3
                PLabel { Layout.fillWidth: true; text: modelData[1] }
                KeyHint { keys: modelData[0] }
            }
        }
        SectionHeader { text: qsTr("Everywhere"); Layout.columnSpan: 2; Layout.topMargin: Theme.s3 }
        Repeater {
            model: root.globalKeys
            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: Theme.s3
                PLabel { Layout.fillWidth: true; text: modelData[1] }
                KeyHint { keys: modelData[0] }
            }
        }
    }
}
