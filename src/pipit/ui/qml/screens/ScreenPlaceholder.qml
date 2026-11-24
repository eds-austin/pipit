// Stand-in for a screen that a later milestone builds: header plus what is coming.
import QtQuick
import QtQuick.Layouts
import Pipit

Item {
    id: root
    required property string screenKey
    property string milestone
    property var planned: []
    readonly property var screen: shell.screens.find(s => s.key === screenKey)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.windowPad
        spacing: Theme.sectionGap

        PLabel { kind: "caption"; text: root.screen.description }

        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ColumnLayout {
                anchors.centerIn: parent
                spacing: Theme.s4
                EmptyState {
                    Layout.alignment: Qt.AlignHCenter
                    iconName: root.screen.icon
                    title: qsTr("%1 arrives in %2").arg(root.screen.title).arg(root.milestone)
                    text: qsTr("This screen is part of the build plan.")
                }
                ColumnLayout {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: Theme.s1
                    Repeater {
                        model: root.planned
                        RowLayout {
                            required property string modelData
                            spacing: Theme.s2
                            PIcon { name: "check"; size: Theme.iconSm; color: Theme.textFaint }
                            PLabel { text: modelData; color: Theme.textMuted }
                        }
                    }
                }
            }
        }
    }
}
