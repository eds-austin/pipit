// Modal dialog: surface2 body, large radius, title row with a close button.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts

B.Dialog {
    id: root
    property string heading
    default property alias body: bodyItem.data
    property alias footerItem: footerRow.data
    modal: true
    anchors.centerIn: B.Overlay.overlay
    width: Math.min(Theme.dialogW, parent ? parent.width - 2 * Theme.s7 : Theme.dialogW)
    padding: 0
    closePolicy: B.Popup.CloseOnEscape
    B.Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.55) }
    background: Rectangle {
        color: Theme.surface2
        radius: Theme.radiusLg
        border.color: Theme.border
    }
    header: Item {
        implicitHeight: Theme.grid(52)
        PLabel {
            kind: "title"
            text: root.heading
            anchors.left: parent.left
            anchors.leftMargin: Theme.s5
            anchors.verticalCenter: parent.verticalCenter
        }
        PIconButton {
            iconName: "x"
            tip: qsTr("Close")
            anchors.right: parent.right
            anchors.rightMargin: Theme.s2
            anchors.verticalCenter: parent.verticalCenter
            onClicked: root.reject()
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
    }
    contentItem: Item {
        implicitHeight: bodyItem.childrenRect.height + 2 * Theme.s5
        Item {
            id: bodyItem
            anchors.fill: parent
            anchors.margins: Theme.s5
        }
    }
    footer: Item {
        implicitHeight: footerRow.children.length ? Theme.grid(60) : 0
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border; visible: footerRow.children.length > 0 }
        RowLayout {
            id: footerRow
            anchors.right: parent.right
            anchors.rightMargin: Theme.s5
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.s2
        }
    }
}
