// Bottom status line: save state on the left, help and version on the right.
import QtQuick
import QtQuick.Layouts
import Pipit

Rectangle {
    id: root
    required property string appVersion
    implicitHeight: Theme.statusBarH
    color: Theme.surface

    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.s3
        anchors.rightMargin: Theme.s3
        spacing: Theme.s4
        PIcon { name: "database"; size: Theme.iconSm; color: Theme.textFaint }
        PLabel {
            kind: "caption"
            text: qsTr("No list open · changes are saved as you make them")
        }
        Item { Layout.fillWidth: true }
        PLabel { kind: "caption"; text: qsTr("Keyboard shortcuts") }
        KeyHint { keys: "F1"; subtle: true }
        PLabel { kind: "caption"; color: Theme.textFaint; text: "Pipit " + root.appVersion }
    }
}
