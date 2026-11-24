// Panel: surface, 1px border, large radius. No shadows (elevation by surface steps).
import QtQuick

Rectangle {
    default property alias content: inner.data
    property int padV: Theme.cardPadV
    property int padH: Theme.cardPadH
    property bool raised: false
    color: raised ? Theme.surface2 : Theme.surface
    border.color: Theme.border
    border.width: 1
    radius: Theme.radiusLg
    Item {
        id: inner
        anchors.fill: parent
        anchors.topMargin: parent.padV
        anchors.bottomMargin: parent.padV
        anchors.leftMargin: parent.padH
        anchors.rightMargin: parent.padH
    }
}
