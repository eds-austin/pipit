// A place's own checklist, edited as in Scythebill (nothing is stored until Save).
//   Up/Down          choose a species
//   0-7              its status: 0 Regular, 1 Introduced, 2 Provisional, 3 Not established,
//                    4 Rarity, 5 Rarity from introduced, 6 Endemic, 7 Extinct
//   Delete           take it off the list
//   typing, Ctrl+J   add a species: type part of its name, Enter adds it
//   Ctrl+S           save (one Ctrl+Z); Esc closes (twice if there are unsaved changes)
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

PDialog {
    id: root
    objectName: "checklistEditor"
    heading: qsTr("Checklist of %1").arg(checklist.placeName)
    width: Math.min(Theme.grid(760), parent ? parent.width - 2 * Theme.s7 : Theme.grid(760))
    closePolicy: B.Popup.NoAutoClose
    property bool discardArmed: false
    signal deleteRequested()

    function show(xmlId, name) {
        if (!checklist.open(xmlId, name)) return
        discardArmed = false
        addField.text = ""
        open()
        rows.currentIndex = rows.count > 0 ? 0 : -1
        if (rows.count > 0) rows.forceActiveFocus()
        else addField.forceActiveFocus()
    }
    function tryClose() {
        if (checklist.dirty && !discardArmed) {
            discardArmed = true
            app.message(qsTr("Unsaved changes: Ctrl+S saves, Esc again discards them"))
            return
        }
        checklist.close()
        close()
    }
    function save() { if (checklist.save()) close() }

    // Closed by the backend too (deleted, or another list opened).
    Connections {
        target: checklist
        function onChanged() { if (!checklist.isOpen && root.visible) root.close() }
    }
    Shortcut { enabled: root.visible; sequence: "Ctrl+S"; onActivated: root.save() }
    Shortcut { enabled: root.visible; sequence: "Ctrl+J"; onActivated: addField.forceActiveFocus() }

    ColumnLayout {
        width: parent.width
        spacing: Theme.s3

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2
            PIcon { name: "plus"; size: Theme.iconSm }
            SuggestField {
                id: addField
                objectName: "checklistAdd"
                Layout.fillWidth: true
                placeholderText: qsTr("Add a species (Ctrl+J): type part of its name, Enter adds it")
                suggestions: checklist.matches
                primaryRole: "name"
                secondaryRole: "scientific"
                onQueryEdited: q => checklist.searchSpecies(q)
                onChosen: index => {
                    const row = checklist.addMatch(index)
                    text = ""
                    checklist.searchSpecies("")
                    if (row >= 0) { rows.currentIndex = row; rows.positionViewAtIndex(row, ListView.Center) }
                }
                onEscaped: {
                    if (text === "") root.tryClose()
                    else { text = ""; checklist.searchSpecies(""); rows.forceActiveFocus() }
                }
                Keys.onDownPressed: event => { if (open) { event.accepted = false; return } rows.forceActiveFocus() }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            PLabel { Layout.fillWidth: true; kind: "overline"; text: qsTr("%n species", "", checklist.count) }
            PLabel { kind: "caption"; text: qsTr("0–7 status · Delete removes") }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
        ListView {
            id: rows
            objectName: "checklistRows"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(Theme.rowHDense * 6,
                                             (root.parent ? root.parent.height : 900) - Theme.grid(360))
            clip: true
            model: checklist.rows
            highlightMoveDuration: 0
            keyNavigationEnabled: true
            reuseItems: true
            boundsBehavior: Flickable.StopAtBounds
            B.ScrollBar.vertical: B.ScrollBar {}
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Escape) {
                    root.tryClose()
                } else if (/^[0-7]$/.test(event.text) && currentIndex >= 0) {
                    checklist.setStatus(currentIndex, Number(event.text))
                } else if ((event.key === Qt.Key_Delete || event.key === Qt.Key_Backspace) && currentIndex >= 0) {
                    const keep = currentIndex
                    checklist.removeRow(currentIndex)
                    currentIndex = Math.min(keep, count - 1)
                } else if (event.text.length === 1 && /[A-Za-z]/.test(event.text) && !(event.modifiers & Qt.ControlModifier)) {
                    addField.forceActiveFocus()
                    addField.text = event.text
                    addField.queryEdited(event.text)
                } else {
                    return
                }
                event.accepted = true
            }
            delegate: Rectangle {
                id: item
                required property int index
                required property string common
                required property string scientific
                required property string status
                required property int statusIndex
                readonly property bool current: ListView.isCurrentItem
                width: ListView.view.width
                height: Theme.rowHDense
                color: current && rows.activeFocus ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface2)
                     : current ? Theme.surface3 : hover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface2)
                     : "transparent"
                HoverHandler { id: hover }
                TapHandler { onTapped: { rows.currentIndex = item.index; rows.forceActiveFocus() } }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.s3
                    anchors.rightMargin: Theme.s3
                    spacing: Theme.s2
                    // The common name keeps its full width first; the scientific name gives way.
                    Item {
                        id: nameCell
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.preferredWidth: 0
                        PLabel {
                            id: commonName
                            width: Math.min(implicitWidth, nameCell.width)
                            height: parent.height
                            text: item.common
                        }
                        PLabel {
                            x: commonName.width + Theme.s2
                            width: Math.max(0, nameCell.width - x)
                            height: parent.height
                            visible: width > Theme.s7
                            text: item.scientific
                            font.italic: true
                            color: Theme.textFaint
                        }
                    }
                    Badge {
                        visible: item.status !== ""
                        text: item.status
                        tone: item.statusIndex === 4 || item.statusIndex === 5 ? Theme.warning
                            : item.statusIndex === 6 ? Theme.positive : Theme.info
                    }
                    PIconButton {
                        visible: hover.hovered || item.current
                        iconName: "x"
                        tip: qsTr("Remove (Delete)")
                        implicitWidth: Theme.controlHCompact
                        implicitHeight: Theme.controlHCompact
                        onClicked: checklist.removeRow(item.index)
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2
            visible: rows.currentIndex >= 0 && rows.count > 0
            PLabel { kind: "caption"; text: qsTr("Status") }
            PComboBox {
                id: statusBox
                objectName: "checklistStatus"
                Layout.preferredWidth: Theme.grid(240)
                model: checklist.statusLabels
                currentIndex: rows.currentItem ? rows.currentItem.statusIndex : 0
                onActivated: index => checklist.setStatus(rows.currentIndex, index)
            }
            Item { Layout.fillWidth: true }
        }
    }
    footerItem: [
        PButton {
            visible: checklist.exists
            objectName: "deleteChecklist"
            text: qsTr("Delete checklist")
            variant: "danger"
            onClicked: root.deleteRequested()
        },
        Item { Layout.fillWidth: true; implicitWidth: Theme.s7 },
        PButton { text: qsTr("Cancel"); variant: "ghost"; onClicked: { checklist.close(); root.close() } },
        PButton {
            objectName: "saveChecklist"
            text: qsTr("Save")
            variant: "primary"
            enabled: checklist.dirty && checklist.count > 0
            onClicked: root.save()
        }
    ]
}
