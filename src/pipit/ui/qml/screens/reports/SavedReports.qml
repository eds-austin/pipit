// Saved reports: the list's stored queries, shared with Scythebill (same names, same order,
// same JSON). Enter loads one into the query; F2 renames; Delete deletes (after asking);
// Alt+Up/Down move it. Total-ticks reports are listed but kept for Scythebill.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

ColumnLayout {
    id: root
    spacing: Theme.s1
    signal renameRequested(int index, string name)
    signal deleteRequested(int index, string name)
    function focusList() { if (list.count > 0) { list.forceActiveFocus(); if (list.currentIndex < 0) list.currentIndex = 0 } }
    readonly property alias listView: list

    RowLayout {
        Layout.fillWidth: true
        SectionHeader { Layout.fillWidth: true; text: qsTr("Saved reports") }
        KeyHint { keys: "Ctrl+L"; subtle: true; visible: list.count > 0 }
    }
    PLabel {
        visible: list.count === 0
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.textMuted
        text: qsTr("None yet. Ctrl+S saves the query below; Scythebill sees it too.")
    }
    ListView {
        id: list
        objectName: "savedReports"
        visible: count > 0
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(count, 5) * Theme.rowHDense
        clip: true
        model: reports.saved
        currentIndex: -1
        highlightMoveDuration: 0
        boundsBehavior: Flickable.StopAtBounds
        B.ScrollBar.vertical: B.ScrollBar {}
        // Keep the loaded report in view.
        Connections {
            target: reports
            function onSavedChanged() { if (reports.currentSavedIndex >= 0) list.positionViewAtIndex(reports.currentSavedIndex, ListView.Contain) }
        }
        Keys.onReturnPressed: reports.loadSaved(currentIndex)
        Keys.onEnterPressed: reports.loadSaved(currentIndex)
        Keys.onPressed: event => {
            if (currentIndex < 0) return
            const item = itemAtIndex(currentIndex)
            if (event.key === Qt.Key_F2 && item) root.renameRequested(currentIndex, item.name)
            else if (event.key === Qt.Key_Delete && item) root.deleteRequested(currentIndex, item.name)
            else if (event.modifiers & Qt.AltModifier && event.key === Qt.Key_Up && currentIndex > 0) {
                reports.moveSaved(currentIndex, currentIndex - 1); currentIndex -= 1
            } else if (event.modifiers & Qt.AltModifier && event.key === Qt.Key_Down && currentIndex < count - 1) {
                reports.moveSaved(currentIndex, currentIndex + 1); currentIndex += 1
            } else return
            event.accepted = true
        }
        delegate: Rectangle {
            id: item
            required property int index
            required property string name
            required property string kind
            required property bool loadable
            readonly property bool current: name === reports.currentSaved
            readonly property bool chosen: ListView.isCurrentItem && list.activeFocus
            width: ListView.view.width
            height: Theme.rowHDense
            radius: Theme.radiusSm
            color: chosen ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
                 : hover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface) : "transparent"
            Rectangle { visible: item.current; width: 2; height: parent.height; color: Theme.accent }
            HoverHandler { id: hover }
            TapHandler {
                onTapped: { list.currentIndex = item.index; list.forceActiveFocus() }
                onDoubleTapped: reports.loadSaved(item.index)
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.s3
                anchors.rightMargin: Theme.s1
                spacing: Theme.s2
                PLabel {
                    Layout.fillWidth: true
                    text: item.name
                    color: item.loadable ? Theme.text : Theme.textMuted
                }
                Badge { visible: item.kind !== ""; text: item.kind; neutral: true }
                Badge { visible: item.current && reports.savedEdited; text: qsTr("Edited"); tone: Theme.warning }
                PIconButton {
                    visible: item.loadable && (hover.hovered || item.chosen)
                    iconName: "play"
                    tip: qsTr("Load into the query (Enter)")
                    implicitWidth: Theme.controlHCompact - Theme.s1
                    implicitHeight: Theme.controlHCompact - Theme.s1
                    onClicked: reports.loadSaved(item.index)
                }
                PIconButton {
                    visible: hover.hovered || item.chosen
                    iconName: "pencil"
                    tip: qsTr("Rename (F2)")
                    implicitWidth: Theme.controlHCompact - Theme.s1
                    implicitHeight: Theme.controlHCompact - Theme.s1
                    onClicked: root.renameRequested(item.index, item.name)
                }
                PIconButton {
                    visible: hover.hovered || item.chosen
                    iconName: "trash-2"
                    tip: qsTr("Delete (Delete)")
                    implicitWidth: Theme.controlHCompact - Theme.s1
                    implicitHeight: Theme.controlHCompact - Theme.s1
                    onClicked: root.deleteRequested(item.index, item.name)
                }
            }
        }
    }
}
