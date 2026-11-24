// One location of the day (slot A-D): place, protocol, start time, effort, complete, notes.
// Tab moves through the fields; fields the protocol hides are skipped, required ones are
// marked. Ctrl+Enter in the place field starts a new place: type its name, Ctrl+Enter
// again, then choose the place it is inside.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

Card {
    id: root
    required property var slot          // a row of entry.slots
    readonly property string letter: slot.letter
    property string newPlaceName: ""    // non-empty while choosing the parent of a new place
    signal done()                       // Tab past the last field
    raised: slot.active
    implicitHeight: Theme.grid(84)
    padV: Theme.s2
    padH: Theme.s3

    function focusPlace() { place.forceActiveFocus(); place.selectAll() }
    function rebindPlace() { place.text = Qt.binding(() => root.slot.label) }
    function needs(field) { return root.slot.needs.indexOf(field) >= 0 }
    function hides(field) { return root.slot.hides.indexOf(field) >= 0 }

    Rectangle {  // 2px accent bar on the active slot
        visible: root.slot.active
        width: 2; radius: 1; color: Theme.accent
        x: -root.padH; y: Theme.s2 - root.padV
        height: root.height - 2 * Theme.s2
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.s1

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2
            Badge { text: root.letter; solid: root.slot.active; tone: Theme.accent }
            SuggestField {
                id: place
                objectName: "placeField_" + root.letter
                Layout.fillWidth: true
                bare: true
                placeholderText: root.newPlaceName
                    ? qsTr("Inside which place is “%1”? Type, then Enter").arg(root.newPlaceName)
                    : qsTr("Place — type to search, Ctrl+Enter for a new place")
                text: root.slot.label
                suggestions: entry.places
                primaryRole: "label"
                secondaryRole: "kind"
                onQueryEdited: q => entry.searchPlaces(q)
                onActiveFocusChanged: if (activeFocus) entry.setActiveSlot(root.letter)
                onChosen: index => {
                    if (root.newPlaceName) {
                        entry.newPlace(root.letter, root.newPlaceName, index)
                        root.newPlaceName = ""
                    } else {
                        entry.choosePlace(root.letter, index)
                    }
                    root.rebindPlace()
                    protocol.forceActiveFocus()
                }
                onAlternate: {
                    if (!root.newPlaceName && text.trim().length > 0) {
                        root.newPlaceName = text.trim()
                        text = ""
                    }
                }
                onEscaped: { root.newPlaceName = ""; root.rebindPlace() }
                Accessible.name: qsTr("Place %1").arg(root.letter)
            }
            PLabel { kind: "caption"; text: qsTr("%n species", "", root.slot.speciesCount) }
            PIconButton {
                visible: entry.slotCount > 1
                iconName: "x"
                tip: qsTr("Remove location %1").arg(root.letter)
                onClicked: entry.removeSlot(root.letter)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2

            PTextField {
                id: protocol
                objectName: "protocolField_" + root.letter
                Layout.preferredWidth: Theme.grid(150)
                implicitHeight: Theme.controlHCompact
                readOnly: true
                text: root.slot.protocolLabel
                Accessible.name: qsTr("Protocol: T traveling, S stationary, I incidental, H historical, A area, P pelagic, N nocturnal, B banding, F flight calls, R random")
                Keys.onPressed: event => {
                    if (event.text.length === 1 && /[a-zA-Z]/.test(event.text)
                            && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier))) {
                        entry.setProtocolKey(root.letter, event.text)
                        event.accepted = true
                    }
                }
                onActiveFocusChanged: if (activeFocus) entry.setActiveSlot(root.letter)
            }
            Repeater {
                model: [
                    { field: "startTime", label: qsTr("Start"), need: "start-time", width: 72 },
                    { field: "duration", label: qsTr("Duration"), need: "duration", width: 80 },
                    { field: "distance", label: qsTr("km"), need: "distance", width: 72 },
                    { field: "area", label: qsTr("ha"), need: "area", width: 64 },
                    { field: "party", label: qsTr("Party"), need: "party-size", width: 72 }
                ]
                PTextField {
                    id: effort
                    required property var modelData
                    objectName: modelData.field + "Field_" + root.letter
                    visible: !root.hides(modelData.need)
                    Layout.preferredWidth: Theme.grid(modelData.width)
                    implicitHeight: Theme.controlHCompact
                    num: true
                    placeholderText: modelData.label + (root.needs(modelData.need) ? " *" : "")
                    text: root.slot[modelData.field]
                    Accessible.name: modelData.label
                    onEditingFinished: {
                        if (!entry.setField(root.letter, modelData.field, text))
                            effort.text = Qt.binding(() => root.slot[effort.modelData.field])
                    }
                    onActiveFocusChanged: if (activeFocus) entry.setActiveSlot(root.letter)
                }
            }
            PCheckBox {
                id: complete
                objectName: "completeBox_" + root.letter
                visible: !root.hides("complete")
                text: qsTr("Complete")
                checked: root.slot.complete
                onToggled: entry.toggleComplete(root.letter)
            }
            PTextField {
                objectName: "commentsField_" + root.letter
                Layout.fillWidth: true
                implicitHeight: Theme.controlHCompact
                placeholderText: qsTr("Comments")
                text: root.slot.comments
                onEditingFinished: entry.setField(root.letter, "comments", text)
                Keys.onTabPressed: event => { entry.setField(root.letter, "comments", text); root.done(); event.accepted = true }
            }
        }
    }
}
