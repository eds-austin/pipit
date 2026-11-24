// Button variants: "primary" (accent fill), "secondary" (surface2 + border),
// "ghost" (transparent), "danger" (negative text on soft tint).
import QtQuick
import QtQuick.Controls.Basic as B

B.Button {
    id: root
    property string variant: "secondary"
    property string iconName: ""
    property bool compact: false
    implicitHeight: compact ? Theme.controlHCompact : Theme.controlH
    leftPadding: text ? Theme.s3 + (iconName ? -2 : 0) : Theme.s2
    rightPadding: text ? Theme.s3 : Theme.s2
    font.family: Theme.fontUi
    font.pixelSize: Theme.sizeBody
    font.weight: Font.DemiBold
    hoverEnabled: true
    focusPolicy: Qt.TabFocus

    readonly property color fg: !enabled ? Theme.textFaint
        : variant === "primary" ? Theme.textOnAccent
        : variant === "danger" ? Theme.negative
        : variant === "ghost" ? (hovered ? Theme.text : Theme.textMuted)
        : Theme.text

    contentItem: Row {
        spacing: Theme.s2
        PIcon {
            visible: root.iconName !== ""
            name: root.iconName
            size: Theme.iconSm
            color: root.fg
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            visible: root.text !== ""
            text: root.text
            font: root.font
            color: root.fg
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    background: Rectangle {
        radius: Theme.radiusMd
        color: {
            if (!root.enabled)
                return root.variant === "primary" ? Theme.surface3 : (root.variant === "ghost" ? "transparent" : Theme.surface2)
            if (root.variant === "primary")
                return root.down ? Qt.darker(Theme.accent, 1.15) : root.hovered ? Qt.lighter(Theme.accent, 1.08) : Theme.accent
            if (root.variant === "danger")
                return root.down ? Theme.tint(Theme.negative, 0.22) : root.hovered ? Theme.tint(Theme.negative, 0.18) : Theme.soft(Theme.negative)
            if (root.variant === "ghost")
                return root.down ? Theme.surface3 : root.hovered ? Theme.surface2 : "transparent"
            return root.down ? Theme.surface3 : root.hovered ? Theme.tint(Theme.text, 0.04, Theme.surface2) : Theme.surface2
        }
        border.width: root.visualFocus ? 2 : (root.variant === "secondary" ? 1 : 0)
        border.color: root.visualFocus ? Theme.accent : Theme.borderStrong
    }
}
