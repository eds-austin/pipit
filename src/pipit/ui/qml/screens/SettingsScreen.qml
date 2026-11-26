// Settings: so far, eBird's web service (off until turned on) and the API key it needs,
// kept in the system keyring. The rest of Scythebill's preferences come later.
import QtQuick
import QtQuick.Layouts
import Pipit

Item {
    id: root
    readonly property var screen: shell.screens.find(s => s.key === "settings")

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.windowPad
        spacing: Theme.sectionGap

        PLabel { kind: "caption"; text: root.screen.description }

        Card {
            Layout.fillWidth: true
            Layout.maximumWidth: Theme.grid(720)
            Layout.preferredHeight: ebirdBody.implicitHeight + 2 * Theme.cardPadV
            ColumnLayout {
                id: ebirdBody
                width: parent.width
                spacing: Theme.s4
                SectionHeader { Layout.fillWidth: true; text: qsTr("eBird") }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.s4
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Theme.s1
                        PLabel { kind: "strong"; text: qsTr("Ask eBird where downloaded checklists were") }
                        PLabel {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            color: Theme.textMuted
                            text: qsTr("A checklist downloaded from its page on eBird doesn't say which state or county it's in. With this on, Pipit sends the checklist's ID and your API key to api.ebird.org to find out. Nothing else is sent, and nothing at all while this is off.")
                        }
                    }
                    PSwitch {
                        objectName: "ebirdOnline"
                        checked: settings.ebirdOnline
                        onToggled: settings.setEbirdOnline(checked)
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.s3
                    PTextField {
                        id: keyField
                        objectName: "ebirdKey"
                        Layout.fillWidth: true
                        echoMode: TextInput.Password
                        placeholderText: settings.hasEbirdKey
                            ? qsTr("A key is saved; type a new one to replace it")
                            : qsTr("Your eBird API key (from ebird.org/api/keygen)")
                        onAccepted: if (settings.saveEbirdKey(text)) text = ""
                    }
                    PButton {
                        text: qsTr("Save key")
                        variant: "primary"
                        enabled: keyField.text.trim().length > 0
                        onClicked: if (settings.saveEbirdKey(keyField.text)) keyField.text = ""
                    }
                    PButton {
                        text: qsTr("Forget key")
                        variant: "ghost"
                        visible: settings.hasEbirdKey
                        onClicked: settings.forgetEbirdKey()
                    }
                }
                StatusChip {
                    kind: settings.hasEbirdKey ? "positive" : "neutral"
                    text: settings.hasEbirdKey ? qsTr("Key saved in the system keyring") : qsTr("No key saved")
                }
            }
        }

        Card {
            Layout.fillWidth: true
            Layout.maximumWidth: Theme.grid(720)
            Layout.preferredHeight: laterBody.implicitHeight + 2 * Theme.cardPadV
            ColumnLayout {
                id: laterBody
                width: parent.width
                spacing: Theme.s2
                SectionHeader { Layout.fillWidth: true; text: qsTr("Coming later") }
                Repeater {
                    model: [qsTr("Name display and language"), qsTr("Countability rules"),
                            qsTr("Text size, units and backups")]
                    RowLayout {
                        required property string modelData
                        spacing: Theme.s2
                        PIcon { name: "check"; size: Theme.iconSm; color: Theme.textFaint }
                        PLabel { text: modelData; color: Theme.textMuted }
                    }
                }
            }
        }
        Item { Layout.fillHeight: true }
    }
}
