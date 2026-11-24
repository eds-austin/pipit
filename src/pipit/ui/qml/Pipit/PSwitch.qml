import QtQuick
import QtQuick.Controls.Basic as B

B.Switch {
    id: root
    spacing: Theme.s3
    padding: 0
    hoverEnabled: true
    indicator: Rectangle {
        implicitWidth: 34
        implicitHeight: 18
        x: root.width - width
        y: (root.height - height) / 2
        radius: height / 2
        color: root.checked ? Theme.accent : Theme.surface3
        border.width: root.visualFocus ? 2 : 1
        border.color: root.visualFocus ? Theme.accent : root.checked ? Theme.accent : Theme.borderStrong
        Rectangle {
            width: 12
            height: 12
            radius: 6
            y: 3
            x: root.checked ? parent.width - width - 3 : 3
            color: root.checked ? Theme.textOnAccent : Theme.textMuted
            Behavior on x { NumberAnimation { duration: 120 } }
        }
    }
    contentItem: PLabel {
        text: root.text
        rightPadding: root.indicator.width + root.spacing
        wrapMode: Text.WordWrap
        elide: Text.ElideNone
    }
}
