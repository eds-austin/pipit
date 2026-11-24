// Input: surface2, strong border, accent focus ring. "num" uses the tabular mono face.
import QtQuick
import QtQuick.Controls.Basic as B

B.TextField {
    id: root
    property bool num: false
    property bool bare: false       // borderless until hovered/focused (inline editing)
    property bool focusRing: true   // false where the container already shows focus
    implicitHeight: Theme.controlH
    color: Theme.text
    placeholderTextColor: Theme.textFaint
    selectionColor: Theme.tint(Theme.accent, 0.4)
    selectedTextColor: Theme.text
    font.family: num ? Theme.fontNum : Theme.fontUi
    font.pixelSize: Theme.sizeBody
    font.features: num ? { "tnum": 1 } : {}
    leftPadding: Theme.s2 + 2
    rightPadding: Theme.s2 + 2
    verticalAlignment: TextInput.AlignVCenter
    hoverEnabled: true
    background: Rectangle {
        radius: Theme.radiusMd
        color: root.bare && (!root.focusRing || !root.activeFocus) && !root.hovered ? "transparent" : Theme.surface2
        border.width: root.activeFocus && root.focusRing ? 2 : (root.bare && !root.hovered ? 0 : 1)
        border.color: root.activeFocus ? Theme.accent : Theme.borderStrong
    }
}
