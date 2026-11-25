// One condition of the query: And/Or/Never, the field, its comparison, and the editor its
// kind needs. Every change goes straight to the backend, which reruns the query.
import QtQuick
import QtQuick.Layouts
import Pipit

Rectangle {
    id: root
    required property int index
    required property string type
    required property string operation
    required property string editor
    required property var options
    required property var value
    readonly property string comparison: value.type !== undefined ? value.type : ""
    function keyIndex(list, key) { return list.findIndex(item => item[0] === key) }
    function set(key, newValue) { reports.setRowValue(index, key, newValue) }
    function needsTo() { return comparison === "BETWEEN" || comparison === "BEFORE" }
    function needsFrom() { return ["DURING", "BETWEEN", "AFTER", "NOT_DURING"].indexOf(comparison) >= 0 }

    implicitHeight: content.implicitHeight + 2 * Theme.s2
    radius: Theme.radiusMd
    color: Theme.surface2
    border.color: Theme.border

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: Theme.s2
        spacing: Theme.s2

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2
            PComboBox {
                objectName: "rowOperation"
                Layout.preferredWidth: Theme.grid(112)
                implicitHeight: Theme.controlHCompact
                model: reports.operations.map(o => o[1])
                currentIndex: root.keyIndex(reports.operations, root.operation)
                onActivated: i => reports.setRowOperation(root.index, reports.operations[i][0])
            }
            PComboBox {
                objectName: "rowType"
                Layout.fillWidth: true
                implicitHeight: Theme.controlHCompact
                model: reports.fieldTypes.map(o => o[1])
                currentIndex: root.keyIndex(reports.fieldTypes, root.type)
                onActivated: i => reports.setRowType(root.index, reports.fieldTypes[i][0])
            }
            PIconButton {
                iconName: "x"
                tip: qsTr("Remove this condition")
                implicitWidth: Theme.controlHCompact
                implicitHeight: Theme.controlHCompact
                onClicked: reports.removeRow(root.index)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.s2
            visible: root.options.length > 0 || root.editor === "heard"
            PComboBox {
                visible: root.options.length > 0
                Layout.preferredWidth: root.editor === "none" ? -1 : Theme.grid(150)
                Layout.fillWidth: root.editor === "none" || root.editor === "place" && root.comparison === "IS_NOT_SET"
                implicitHeight: Theme.controlHCompact
                model: root.options.map(o => o[1])
                currentIndex: root.keyIndex(root.options, root.comparison)
                onActivated: i => root.set("type", root.options[i][0])
            }
            // The heard-only field: its whole value is true, false or null.
            PComboBox {
                visible: root.editor === "heard"
                Layout.fillWidth: true
                implicitHeight: Theme.controlHCompact
                readonly property var choices: [[true, qsTr("is heard only")], [false, qsTr("is not heard only")], [null, qsTr("either")]]
                model: choices.map(c => c[1])
                currentIndex: choices.findIndex(c => c[0] === root.value.value)
                onActivated: i => root.set("value", choices[i][0])
            }
            ChoicePicker {
                visible: root.editor === "place" && root.comparison !== "IS_NOT_SET"
                    || root.editor === "family"
                    || root.editor === "user" && root.comparison !== "ARE_EMPTY"
                Layout.fillWidth: true
                kind: root.editor
                chosenId: root.value.id || ""
                onChosen: id => root.set("id", id)
            }
            // Status lists
            PComboBox {
                visible: ["iucn", "status", "breeding", "sphybrid"].indexOf(root.editor) >= 0
                    && !(root.editor === "status" && root.comparison === "ANY")
                    && !(root.editor === "breeding" && root.comparison === "ANY")
                Layout.fillWidth: true
                implicitHeight: Theme.controlHCompact
                readonly property string key: root.editor === "iucn" || root.editor === "status" ? "statusId"
                                             : root.editor === "breeding" ? "level" : "statusType"
                readonly property var choices: root.editor === "iucn" ? reports.iucnChoices
                                             : root.editor === "status" ? reports.statusChoices
                                             : root.editor === "breeding" ? reports.breedingChoices
                                             : reports.spChoices
                model: choices.map(c => c[1])
                currentIndex: root.keyIndex(choices, root.value[key])
                onActivated: i => root.set(key, choices[i][0])
            }
            PTextField {
                visible: root.editor === "text"
                Layout.fillWidth: true
                implicitHeight: Theme.controlHCompact
                placeholderText: qsTr("Text")
                text: root.value.text || ""
                onEditingFinished: root.set("text", text)
            }
            PTextField {
                visible: root.editor === "count"
                Layout.preferredWidth: Theme.grid(72)
                implicitHeight: Theme.controlHCompact
                num: true
                text: root.value.count !== undefined ? String(root.value.count) : ""
                validator: IntValidator { bottom: 0; top: 99999 }
                onEditingFinished: root.set("count", text === "" ? 0 : Number(text))
            }
            PLabel { visible: root.editor === "count"; text: qsTr("times") ; color: Theme.textMuted }
        }

        // Dates: from (and to); partial dates such as 2024, 2024-05 or M12 work.
        RowLayout {
            Layout.fillWidth: true
            visible: root.editor === "dates" && (root.needsFrom() || root.needsTo())
            spacing: Theme.s2
            PTextField {
                objectName: "dateFrom"
                visible: root.needsFrom()
                Layout.fillWidth: true
                implicitHeight: Theme.controlHCompact
                num: true
                placeholderText: qsTr("2024, 2024-05 or M12")
                text: root.value.from || ""
                onEditingFinished: root.set("from", text.trim())
            }
            PLabel { visible: root.needsFrom() && root.needsTo(); text: qsTr("and"); color: Theme.textMuted }
            PTextField {
                visible: root.needsTo()
                Layout.fillWidth: true
                implicitHeight: Theme.controlHCompact
                num: true
                placeholderText: qsTr("2025 or M02")
                text: root.value.to || ""
                onEditingFinished: root.set("to", text.trim())
            }
        }

        // Nearer than: a distance and its unit.
        RowLayout {
            Layout.fillWidth: true
            visible: root.editor === "place" && root.comparison === "IS_NEARER_THAN"
            spacing: Theme.s2
            PTextField {
                Layout.preferredWidth: Theme.grid(90)
                implicitHeight: Theme.controlHCompact
                num: true
                text: root.value.distance !== undefined ? String(root.value.distance) : ""
                validator: DoubleValidator { bottom: 0 }
                onEditingFinished: root.set("distance", text === "" ? null : Number(text))
            }
            PComboBox {
                Layout.preferredWidth: Theme.grid(120)
                implicitHeight: Theme.controlHCompact
                model: [qsTr("kilometers"), qsTr("miles")]
                currentIndex: root.value.milesOrKilometers === "MILES" ? 1 : 0
                onActivated: i => root.set("milesOrKilometers", i === 1 ? "MILES" : "KILOMETERS")
            }
            Item { Layout.fillWidth: true }
        }
    }
}
