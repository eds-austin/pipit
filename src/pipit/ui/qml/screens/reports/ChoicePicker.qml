// A field that picks a place, family or observer: shows the chosen one's name; typing
// searches (reports.findChoices), Up/Down move in the list, Enter chooses, Esc gives up.
import QtQuick
import QtQuick.Controls.Basic as B
import Pipit

PTextField {
    id: root
    property string kind          // "place", "family" or "user"
    property string chosenId
    signal chosen(string id)
    readonly property string chosenName: reports.choiceName(kind, chosenId)
    property bool searching: false
    implicitHeight: Theme.controlHCompact
    placeholderText: kind === "place" ? qsTr("Any place (type to choose)")
                   : kind === "family" ? qsTr("Type a family or order") : qsTr("Type an observer")
    text: searching ? text : chosenName
    onTextEdited: {
        searching = true
        reports.findChoices(kind, text)
        list.currentIndex = 0
        popup.open()
    }
    onActiveFocusChanged: if (!activeFocus) { searching = false; popup.close(); text = Qt.binding(() => root.chosenName) }
    function choose(index) {
        if (index < 0 || index >= list.count) return
        const item = list.itemAtIndex(index)
        if (item) root.chosen(item.choiceId)
        searching = false
        popup.close()
        text = Qt.binding(() => root.chosenName)
    }
    Keys.onDownPressed: event => { if (popup.opened) list.currentIndex = Math.min(list.count - 1, list.currentIndex + 1); else event.accepted = false }
    Keys.onUpPressed: event => { if (popup.opened) list.currentIndex = Math.max(0, list.currentIndex - 1); else event.accepted = false }
    Keys.onReturnPressed: event => { if (popup.opened) root.choose(list.currentIndex); else event.accepted = false }
    Keys.onEnterPressed: event => { if (popup.opened) root.choose(list.currentIndex); else event.accepted = false }
    Keys.onEscapePressed: event => {
        if (popup.opened || searching) { searching = false; popup.close(); text = Qt.binding(() => root.chosenName) }
        else event.accepted = false
    }

    B.Popup {
        id: popup
        y: root.height + Theme.s1
        width: Math.max(root.width, Theme.grid(280))
        height: Math.min(list.contentHeight + 2 * Theme.s1, Theme.rowH * 8)
        padding: Theme.s1
        background: Rectangle { color: Theme.surface2; radius: Theme.radiusMd; border.color: Theme.border }
        ListView {
            id: list
            anchors.fill: parent
            clip: true
            model: reports.choices
            highlightMoveDuration: 0
            B.ScrollBar.vertical: B.ScrollBar {}
            delegate: Rectangle {
                id: choice
                required property int index
                required property string key
                required property string name
                required property string path
                readonly property string choiceId: key
                width: ListView.view.width
                height: Theme.rowH
                radius: Theme.radiusSm
                color: ListView.isCurrentItem ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface2) : "transparent"
                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    x: Theme.s2
                    width: parent.width - 2 * Theme.s2
                    PLabel { width: parent.width; text: choice.name }
                    PLabel { width: parent.width; kind: "caption"; text: choice.path; visible: choice.path !== "" }
                }
                TapHandler { onTapped: root.choose(choice.index) }
            }
        }
    }
}
