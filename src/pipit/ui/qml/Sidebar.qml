// Left navigation: app mark, one entry per screen (Settings pinned to the bottom),
// collapsible to icons with Ctrl+B.
import QtQuick
import QtQuick.Layouts
import Pipit

Rectangle {
    id: root
    readonly property bool collapsed: shell.sidebarCollapsed
    implicitWidth: collapsed ? Theme.sidebarCollapsedW : Theme.sidebarW
    color: Theme.surface

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.s2
        spacing: Theme.s1

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: Theme.titleStripH - Theme.s2
            spacing: Theme.s2
            PIcon {
                visible: !root.collapsed
                Layout.leftMargin: Theme.s2
                name: "bird"
                color: Theme.accent
                size: Theme.iconMd + Theme.s1
            }
            PLabel {
                visible: !root.collapsed
                Layout.fillWidth: true
                kind: "title"
                text: "Pipit"
            }
            PIconButton {
                Layout.alignment: root.collapsed ? Qt.AlignHCenter : Qt.AlignRight
                iconName: root.collapsed ? "panel-left-open" : "panel-left-close"
                tip: (root.collapsed ? qsTr("Expand sidebar") : qsTr("Collapse sidebar")) + "  Ctrl+B"
                onClicked: shell.toggleSidebar()
            }
        }

        Repeater {
            model: shell.screens.slice(0, shell.screens.length - 1)
            SidebarItem {
                required property var modelData
                required property int index
                Layout.fillWidth: true
                text: modelData.title
                iconName: modelData.icon
                shortcut: modelData.shortcut
                collapsed: root.collapsed
                selected: shell.currentIndex === index
                onClicked: shell.go(modelData.key)
            }
        }

        Item { Layout.fillHeight: true }

        SidebarItem {
            readonly property var settingsScreen: shell.screens[shell.screens.length - 1]
            Layout.fillWidth: true
            text: settingsScreen.title
            iconName: settingsScreen.icon
            shortcut: settingsScreen.shortcut
            collapsed: root.collapsed
            selected: shell.currentKey === settingsScreen.key
            onClicked: shell.go(settingsScreen.key)
        }
    }
}
