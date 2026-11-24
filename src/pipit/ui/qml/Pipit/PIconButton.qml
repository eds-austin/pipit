// Square ghost button with an icon and a tooltip.
import QtQuick
import QtQuick.Controls.Basic as B

B.ToolButton {
    id: root
    property string iconName
    property string tip
    property color iconColor: hovered ? Theme.text : Theme.textMuted
    implicitWidth: Theme.controlH
    implicitHeight: Theme.controlH
    hoverEnabled: true
    contentItem: Item {
        PIcon {
            anchors.centerIn: parent
            name: root.iconName
            color: root.enabled ? root.iconColor : Theme.textFaint
        }
    }
    background: Rectangle {
        radius: Theme.radiusMd
        color: root.down || root.checked ? Theme.surface3 : root.hovered ? Theme.surface2 : "transparent"
        border.width: root.visualFocus ? 2 : 0
        border.color: Theme.accent
    }
    B.ToolTip.visible: hovered && tip !== ""
    B.ToolTip.text: tip
    B.ToolTip.delay: 500
}
