import QtQuick
import QtQuick.Controls.Basic as B

B.CheckBox {
    id: root
    spacing: Theme.s2
    padding: 0
    hoverEnabled: true
    indicator: Rectangle {
        implicitWidth: 16
        implicitHeight: 16
        x: root.leftPadding
        y: (root.height - height) / 2
        radius: Theme.radiusSm
        color: root.checked ? Theme.accent : Theme.surface2
        border.width: root.visualFocus ? 2 : 1
        border.color: root.visualFocus ? Theme.accent : root.checked ? Theme.accent : Theme.borderStrong
        PIcon {
            anchors.centerIn: parent
            visible: root.checked
            name: "check"
            size: Theme.grid(12)
            color: Theme.textOnAccent
        }
    }
    contentItem: PLabel {
        text: root.text
        leftPadding: root.indicator.width + (root.text ? root.spacing : 0)
        color: root.enabled ? Theme.text : Theme.textFaint
    }
}
