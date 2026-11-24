// Uppercase caption on a soft tint (or solid fill); optional leading glyph or icon.
// Status is never colour alone: the text always says it.
import QtQuick

Rectangle {
    id: root
    property string text
    property color tone: Theme.accent
    property bool neutral: false
    property bool solid: false
    property string iconName: ""
    implicitHeight: Theme.pillH
    implicitWidth: row.implicitWidth + 2 * Theme.s2
    radius: Theme.radiusSm
    color: solid ? tone : neutral ? Theme.surface3 : Theme.soft(tone)
    Row {
        id: row
        anchors.centerIn: parent
        spacing: Theme.s1
        PIcon {
            visible: root.iconName !== ""
            name: root.iconName
            size: Theme.grid(12)
            anchors.verticalCenter: parent.verticalCenter
            color: label.color
        }
        PLabel {
            id: label
            kind: "overline"
            text: root.text
            color: root.solid ? Theme.textOnAccent : root.neutral ? Theme.textMuted : root.tone
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
