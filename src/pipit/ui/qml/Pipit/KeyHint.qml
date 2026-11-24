// A keyboard shortcut shown as a small keycap ("Ctrl+K"). Purely informational.
import QtQuick

Rectangle {
    id: root
    property string keys
    property bool subtle: false
    visible: keys !== ""
    implicitHeight: Theme.grid(20)
    implicitWidth: label.implicitWidth + 2 * Theme.s2
    radius: Theme.radiusSm
    color: subtle ? "transparent" : Theme.surface3
    border.width: subtle ? 0 : 1
    border.color: Theme.border
    PLabel {
        id: label
        anchors.centerIn: parent
        kind: "num"
        text: root.keys
        color: Theme.textMuted
        font.pixelSize: Theme.sizeCaption
    }
}
