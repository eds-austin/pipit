// Label (uppercase caption) over a value in the tabular mono face, optional sub-line.
import QtQuick

Card {
    id: root
    property string label
    property string value
    property string sub: ""
    property color valueColor: Theme.text
    implicitWidth: Theme.grid(148)
    implicitHeight: Theme.grid(84)
    Column {
        anchors.fill: parent
        spacing: 2
        PLabel { kind: "overline"; text: root.label; width: parent.width }
        PLabel { kind: "kpi"; text: root.value; color: root.valueColor; width: parent.width }
        PLabel { kind: "caption"; text: root.sub; visible: root.sub !== ""; width: parent.width }
    }
}
