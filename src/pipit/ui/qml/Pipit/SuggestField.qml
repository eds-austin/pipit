// A text field with a suggestion list below it, driven from the keyboard: typing asks for
// suggestions (queryEdited), Up/Down move through them, Enter picks one (chosen), Ctrl+Enter
// asks for the secondary action (alternate), Esc closes the list or clears the field.
// The list never takes focus, so typing continues uninterrupted.
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts

PTextField {
    id: root
    property var suggestions            // a list model with "primaryRole"/"secondaryRole"
    property string primaryRole: "label"
    property string secondaryRole: ""
    property string tertiaryRole: ""
    property int currentIndex: 0
    // The model's own row count: ListView.count can lag until the next layout pass.
    function rows() { return root.suggestions ? root.suggestions.rowCount() : 0 }
    readonly property int count: list.count
    readonly property bool open: popup.visible
    signal queryEdited(string text)
    signal chosen(int index)
    signal alternate()
    signal escaped()

    onTextEdited: {
        currentIndex = 0
        queryEdited(text)
        if (text.length > 0)
            popup.open()
        else
            popup.close()
    }
    onActiveFocusChanged: if (!activeFocus) popup.close()

    Keys.onUpPressed: event => {
        if (popup.visible && rows() > 0) currentIndex = Math.max(0, currentIndex - 1)
        else event.accepted = false
    }
    Keys.onDownPressed: event => {
        if (popup.visible && rows() > 0) currentIndex = Math.min(rows() - 1, currentIndex + 1)
        else event.accepted = false
    }
    Keys.onPressed: event => {
        const enter = event.key === Qt.Key_Return || event.key === Qt.Key_Enter
        if (enter && (event.modifiers & Qt.ControlModifier)) {
            popup.close()
            root.alternate()
            event.accepted = true
        } else if (enter && rows() > 0 && root.text.length > 0) {
            const index = currentIndex
            popup.close()
            root.chosen(index)
            event.accepted = true
        } else if (event.matches(StandardKey.Undo) && !root.canUndo && typeof app !== "undefined") {
            app.undo()  // nothing typed to undo here: undo the last saved change instead
            event.accepted = true
        } else if (event.matches(StandardKey.Redo) && !root.canRedo && typeof app !== "undefined") {
            app.redo()
            event.accepted = true
        } else if (event.key === Qt.Key_Escape) {
            if (popup.visible) popup.close()
            else root.escaped()
            event.accepted = true
        }
    }

    B.Popup {
        id: popup
        // Below the field, or above it when the window has no room below.
        readonly property real below: root.Window.height - root.mapToItem(null, 0, root.height).y
        y: below >= height + Theme.s2 ? root.height + 2 : -height - 2
        width: Math.max(root.width, Theme.grid(420))
        height: Math.min(list.contentHeight, Theme.rowHDense * 10) + 2 * Theme.s1
        padding: Theme.s1
        focus: false
        closePolicy: B.Popup.CloseOnPressOutsideParent
        visible: false
        background: Rectangle {
            color: Theme.surface2
            radius: Theme.radiusMd
            border.color: Theme.borderStrong
        }
        contentItem: ListView {
            id: list
            objectName: "suggestions"
            clip: true
            model: root.suggestions
            currentIndex: root.currentIndex
            highlightMoveDuration: 0
            delegate: Rectangle {
                id: row
                required property int index
                required property var model
                width: ListView.view.width
                height: Theme.rowHDense
                radius: Theme.radiusSm
                color: index === root.currentIndex ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface2)
                     : hover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface2) : "transparent"
                HoverHandler { id: hover }
                TapHandler { onTapped: { popup.close(); root.chosen(row.index) } }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.s2
                    anchors.rightMargin: Theme.s2
                    spacing: Theme.s2
                    PLabel {
                        Layout.fillWidth: true
                        text: row.model[root.primaryRole] ?? ""
                        color: row.index === root.currentIndex ? Theme.text : Theme.textMuted
                    }
                    PLabel {
                        visible: root.secondaryRole !== "" && text !== ""
                        Layout.maximumWidth: parent.width * 0.4
                        text: root.secondaryRole ? (row.model[root.secondaryRole] ?? "") : ""
                        color: Theme.textFaint
                        font.italic: true
                    }
                    Badge {
                        visible: root.tertiaryRole !== "" && text !== ""
                        text: root.tertiaryRole ? (row.model[root.tertiaryRole] ?? "") : ""
                        tone: text === "not on checklist" || text === "rarity" ? Theme.warning : Theme.info
                    }
                }
            }
        }
    }
}
