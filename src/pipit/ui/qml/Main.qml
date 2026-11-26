// Main window: sidebar, title strip, the current screen and a status line.
// Opens maximized; every screen and action is reachable from the keyboard.
// Styling comes only from the Pipit theme (design tokens).
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Dialogs
import QtQuick.Layouts
import Pipit

B.ApplicationWindow {
    id: win
    required property string appVersion
    required property bool maximized
    width: 1440
    height: 900
    minimumWidth: 1024
    minimumHeight: 640
    visible: true
    visibility: maximized ? Window.Maximized : Window.Windowed
    title: shell.screens[shell.currentIndex].title + " · Pipit"
    color: Theme.bg
    font.family: Theme.fontUi
    font.pixelSize: Theme.sizeBody

    // Opens the command palette or the shortcut list (also used by screenshots).
    function openOverlay(name, query) {
        if (name === "palette")
            palette.show(query)
        else if (name === "keys")
            keys.open()
    }

    Instantiator {
        model: shell.screens
        delegate: Shortcut {
            required property var modelData
            sequence: modelData.shortcut
            context: Qt.ApplicationShortcut
            onActivated: shell.go(modelData.key)
        }
    }
    Shortcut { sequence: "Ctrl+N"; context: Qt.ApplicationShortcut; onActivated: shell.runCommand("app.new-entry") }
    Shortcut { sequence: "Ctrl+B"; context: Qt.ApplicationShortcut; onActivated: shell.toggleSidebar() }
    Shortcut { sequence: "Ctrl+K"; context: Qt.ApplicationShortcut; onActivated: win.openOverlay("palette", "") }
    Shortcut { sequence: "F1"; context: Qt.ApplicationShortcut; onActivated: win.openOverlay("keys", "") }
    Shortcut { sequence: "Alt+Left"; context: Qt.ApplicationShortcut; onActivated: shell.back() }
    Shortcut { sequence: "Ctrl+Q"; context: Qt.ApplicationShortcut; onActivated: Qt.quit() }
    Shortcut { sequence: "Ctrl+O"; context: Qt.ApplicationShortcut; onActivated: openDialog.open() }
    // Undo/redo of saved changes. Text fields keep Ctrl+Z for their own typing.
    Shortcut { sequences: [StandardKey.Undo]; context: Qt.ApplicationShortcut; onActivated: app.undo() }
    Shortcut { sequences: [StandardKey.Redo, "Ctrl+Shift+Z"]; context: Qt.ApplicationShortcut; onActivated: app.redo() }

    FileDialog {
        id: openDialog
        title: qsTr("Open a Pipit list")
        nameFilters: [qsTr("Pipit lists (*.pipit)")]
        onAccepted: app.openList(selectedFile)
    }
    FileDialog {
        id: importDialog
        title: qsTr("Import a Scythebill list")
        nameFilters: [qsTr("Scythebill lists (*.bsxm)")]
        onAccepted: app.importScythebill(selectedFile)
    }
    FileDialog {
        id: ebirdFileDialog
        title: qsTr("Import from eBird: My Data download, or a Record Format file")
        nameFilters: [qsTr("eBird files (*.csv *.zip)")]
        onAccepted: { imports.start(selectedFile); ebirdImport.show() }
    }

    Connections {
        target: shell
        function onActionRequested(key) {
            if (key === "app.keyboard")
                win.openOverlay("keys", "")
            else if (key === "app.undo")
                app.undo()
            else if (key === "app.redo")
                app.redo()
            else if (key === "app.open-list")
                openDialog.open()
            else if (key === "app.import-scythebill")
                importDialog.open()
            else if (key === "app.import-ebird")
                ebirdFileDialog.open()
            else if (key === "app.quit")
                Qt.quit()
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Sidebar { Layout.fillHeight: true }
        Rectangle { Layout.fillHeight: true; Layout.preferredWidth: 1; color: Theme.border }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            TitleStrip {
                Layout.fillWidth: true
                onPaletteRequested: win.openOverlay("palette", "")
            }
            StackLayout {
                id: stack
                objectName: "screenStack"
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: shell.currentIndex
                Repeater {
                    model: shell.screens
                    Loader {
                        required property var modelData
                        required property int index
                        // Screens load on first visit and stay loaded (keeps their state).
                        active: index === shell.currentIndex || status === Loader.Ready
                        source: "screens/" + modelData.key.charAt(0).toUpperCase()
                                + modelData.key.slice(1) + "Screen.qml"
                    }
                }
            }
            StatusBar { Layout.fillWidth: true; appVersion: win.appVersion }
        }
    }

    ImportDialog { id: ebirdImport }
    CommandPalette { id: palette }
    KeyOverlay { id: keys }
}
