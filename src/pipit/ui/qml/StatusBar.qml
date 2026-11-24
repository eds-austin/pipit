// Bottom status line: save state on the left, help and version on the right.
import QtQuick
import QtQuick.Layouts
import Pipit

Rectangle {
    id: root
    required property string appVersion
    property string message: ""
    Connections {
        target: app
        function onMessage(text) { root.message = text; clearTimer.restart() }
    }
    Timer { id: clearTimer; interval: 6000; onTriggered: root.message = "" }
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
            objectName: "statusMessage"
            text: root.message !== "" ? root.message
                : !app.hasList ? qsTr("No list open · Ctrl+O opens one")
                : qsTr("%1 · %2 sightings · saved as you go%3").arg(app.listName)
                      .arg(app.sightingCount.toLocaleString(Qt.locale(), "f", 0))
                      .arg(app.undoLabel ? qsTr(" · Ctrl+Z undoes “%1”").arg(app.undoLabel) : "")
        }
        Item { Layout.fillWidth: true }
        PLabel { kind: "caption"; text: qsTr("Keyboard shortcuts") }
        KeyHint { keys: "F1"; subtle: true }
        PLabel { kind: "caption"; color: Theme.textFaint; text: "Pipit " + root.appVersion }
    }
}
