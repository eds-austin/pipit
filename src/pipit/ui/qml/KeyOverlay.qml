// F1: the keyboard shortcuts that work everywhere. Screens add their own later.
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
        ["Ctrl+Q", qsTr("Quit")]
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
