// A Lucide outline icon tinted with a token colour (rendered by the "icon" image provider).
// An Item wrapper so layouts see the icon's real size (an Image's implicit size is
// its 2x source size and is read-only).
import QtQuick

Item {
    id: root
    property string name
    property color color: Theme.textMuted
    property int size: Theme.iconMd
    implicitWidth: size
    implicitHeight: size
    Image {
        anchors.fill: parent
        sourceSize.width: root.size * 2
        sourceSize.height: root.size * 2
        fillMode: Image.PreserveAspectFit
        smooth: true
        source: root.name ? "image://icon/" + root.name + "/" + String(root.color).replace("#", "") : ""
    }
}
