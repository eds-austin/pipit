// Centred icon, title and explanation for empty and not-yet-available states.
import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string iconName: "info"
    property string title
    property string text
    spacing: Theme.s3

    Rectangle {
        Layout.alignment: Qt.AlignHCenter
        implicitWidth: Theme.grid(88)
        implicitHeight: implicitWidth
        radius: implicitWidth / 2
        color: Theme.surface
        border.color: Theme.border
        PIcon {
            anchors.centerIn: parent
            name: root.iconName
            size: Theme.grid(40)
            color: Theme.textMuted
        }
    }
    PLabel {
        Layout.alignment: Qt.AlignHCenter
        Layout.topMargin: Theme.s2
        kind: "title"
        text: root.title
    }
    PLabel {
        Layout.alignment: Qt.AlignHCenter
        Layout.maximumWidth: Theme.grid(480)
        color: Theme.textMuted
        text: root.text
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
        visible: text !== ""
    }
}
