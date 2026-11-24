// 4px bar: surface3 track, accent (or given tone) fill.
import QtQuick

Rectangle {
    id: root
    property real value: 0      // 0..1
    property color tone: Theme.accent
    implicitHeight: Theme.progressH
    radius: height / 2
    color: Theme.surface3
    Rectangle {
        width: Math.max(0, Math.min(1, root.value)) * parent.width
        height: parent.height
        radius: parent.radius
        color: root.tone
        Behavior on width { NumberAnimation { duration: 150 } }
    }
}
