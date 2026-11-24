import QtQuick
import QtQuick.Controls.Basic as B

B.ComboBox {
    id: root
    implicitHeight: Theme.controlH
    font.family: Theme.fontUi
    font.pixelSize: Theme.sizeBody
    hoverEnabled: true
    leftPadding: Theme.s2 + 2
    contentItem: PLabel {
        text: root.displayText
        color: root.enabled ? Theme.text : Theme.textFaint
        rightPadding: root.indicator.width + Theme.s2
    }
    indicator: PIcon {
        x: root.width - width - Theme.s2
        y: (root.height - height) / 2
        name: "chevron-down"
        size: Theme.iconSm
    }
    background: Rectangle {
        radius: Theme.radiusMd
        color: root.hovered || root.down ? Theme.surface3 : Theme.surface2
        border.width: root.visualFocus ? 2 : 1
        border.color: root.visualFocus ? Theme.accent : Theme.borderStrong
    }
    delegate: B.ItemDelegate {
        required property var modelData
        required property int index
        width: ListView.view ? ListView.view.width : 0
        height: Theme.controlH
        highlighted: root.highlightedIndex === index
        contentItem: PLabel {
            text: root.textRole ? modelData[root.textRole] : modelData
            color: index === root.currentIndex ? Theme.accent : Theme.text
        }
        background: Rectangle {
            radius: Theme.radiusSm
            color: parent.highlighted ? Theme.surface3 : "transparent"
        }
    }
    popup: B.Popup {
        y: root.height + 4
        width: root.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        padding: 4
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            B.ScrollIndicator.vertical: B.ScrollIndicator {}
        }
        background: Rectangle {
            color: Theme.surface2
            radius: Theme.radiusMd
            border.color: Theme.border
        }
    }
}
