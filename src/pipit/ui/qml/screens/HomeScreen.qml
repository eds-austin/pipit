// Home: the list at a glance. Figures are real queries with Scythebill's counting (life
// list, this year, then every saved report in its saved order); Enter or a click opens one
// in Reports. Recent visits open in Enter Sightings; the newest backup is shown. Keys (F1):
//   arrows      move between figures; Enter opens one in Reports
//   Ctrl+R      into recent visits; Enter edits the visit, Esc goes back
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

Item {
    id: root
    objectName: "homeScreen"
    readonly property bool shown: shell.currentKey === "home"
    readonly property bool working: app.hasList && app.taxaReady

    function openCard(card) {
        if (!card) return
        if (card.saved >= 0) reports.loadSaved(card.saved)
        else reports.showQuery(card.query)
        shell.go("reports")
    }
    function openVisit(visit) {
        if (visit && entry.openVisit(visit.placeId, visit.dateRaw, visit.time)) shell.go("enter")
    }
    function focusVisits() { if (visits.count > 0) { visits.forceActiveFocus(); if (visits.currentIndex < 0) visits.currentIndex = 0 } }

    Shortcut { enabled: root.shown && root.working; sequence: "Ctrl+R"; onActivated: root.focusVisits() }
    onShownChanged: { home.setActive(shown); if (shown && working) Qt.callLater(() => cards.forceActiveFocus()) }
    Component.onCompleted: home.setActive(shown)

    EmptyState {
        anchors.centerIn: parent
        visible: !root.working
        iconName: app.hasList ? "loader-circle" : "house"
        title: app.hasList ? qsTr("Loading the taxonomy…") : qsTr("Open or import a list")
        text: app.hasList ? "" : qsTr("Ctrl+O opens a Pipit list. “Import Scythebill list” in Ctrl+K brings in a .bsxm file.")
    }

    B.ScrollView {
        anchors.fill: parent
        visible: root.working
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            width: parent.width
            spacing: Theme.sectionGap

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: Theme.windowPad
                Layout.leftMargin: Theme.windowPad
                Layout.rightMargin: Theme.windowPad
                PLabel { kind: "display"; text: app.listName }
                Item { Layout.fillWidth: true }
                PLabel { kind: "caption"; text: home.counting ? qsTr("Counting…") : qsTr("Counts in %1").arg(app.displayTaxonomyName) }
            }

            // ------------------------------------------------------------ figures
            GridView {
                id: cards
                objectName: "homeCards"
                Layout.fillWidth: true
                Layout.leftMargin: Theme.windowPad
                Layout.rightMargin: Theme.windowPad - Theme.s3
                readonly property int columns: Math.max(1, Math.floor(width / (Theme.grid(200) + Theme.s3)))
                cellWidth: Math.floor(width / columns)
                cellHeight: Theme.grid(84) + Theme.s3
                Layout.preferredHeight: Math.max(1, Math.ceil(count / columns)) * cellHeight
                interactive: false
                model: home.cards
                currentIndex: 0
                keyNavigationEnabled: true
                highlightMoveDuration: 0
                Keys.onReturnPressed: root.openCard(currentItem)
                Keys.onEnterPressed: root.openCard(currentItem)
                delegate: Item {
                    id: cell
                    required property int index
                    required property string label
                    required property string value
                    required property string sub
                    required property string query
                    required property int saved
                    readonly property bool focused: GridView.isCurrentItem && cards.activeFocus
                    width: cards.cellWidth
                    height: cards.cellHeight
                    KpiCard {
                        anchors.fill: parent
                        anchors.rightMargin: Theme.s3
                        anchors.bottomMargin: Theme.s3
                        label: cell.label
                        value: cell.value
                        sub: cell.sub
                        valueColor: cell.value === "—" ? Theme.textMuted : Theme.text
                        color: hover.hovered ? Theme.surface2 : Theme.surface
                        border.color: cell.focused ? Theme.accent : Theme.border
                        border.width: cell.focused ? 2 : 1
                        HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: { cards.currentIndex = cell.index; root.openCard(cell) } }
                    }
                }
            }
            PLabel {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.windowPad
                Layout.rightMargin: Theme.windowPad
                visible: !home.counting && cards.count <= 2
                wrapMode: Text.WordWrap
                color: Theme.textMuted
                text: qsTr("Reports you save (Reports, Ctrl+S) show here too, in the order of your saved reports.")
            }

            // ------------------------------------------------------------ visits and backups
            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: Theme.windowPad
                Layout.rightMargin: Theme.windowPad
                Layout.bottomMargin: Theme.windowPad
                spacing: Theme.s3

                Card {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop
                    Layout.preferredHeight: Theme.grid(40) + Math.max(1, visits.count) * Theme.rowH + 2 * Theme.cardPadV
                    padH: 0
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: Theme.s2
                        RowLayout {
                            Layout.fillWidth: true
                            Layout.leftMargin: Theme.s4
                            Layout.rightMargin: Theme.s4
                            SectionHeader { Layout.fillWidth: true; text: qsTr("Recent visits") }
                            KeyHint { keys: "Ctrl+R"; subtle: true; visible: visits.count > 0 }
                        }
                        PLabel {
                            visible: visits.count === 0
                            Layout.leftMargin: Theme.s4
                            color: Theme.textMuted
                            text: qsTr("No dated sightings yet.")
                        }
                        ListView {
                            id: visits
                            objectName: "homeVisits"
                            visible: count > 0
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            interactive: false
                            model: home.visits
                            currentIndex: -1
                            highlightMoveDuration: 0
                            Keys.onReturnPressed: root.openVisit(currentItem)
                            Keys.onEnterPressed: root.openVisit(currentItem)
                            Keys.onEscapePressed: cards.forceActiveFocus()
                            delegate: Rectangle {
                                id: visit
                                required property int index
                                required property string date
                                required property string time
                                required property string place
                                required property string placeId
                                required property string dateRaw
                                required property int sightings
                                readonly property bool chosen: ListView.isCurrentItem && visits.activeFocus
                                width: ListView.view.width
                                height: Theme.rowH
                                color: chosen ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
                                     : visitHover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface) : "transparent"
                                Rectangle { visible: visit.chosen; width: 2; height: parent.height; color: Theme.accent }
                                HoverHandler { id: visitHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: { visits.currentIndex = visit.index; root.openVisit(visit) } }
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: Theme.s4
                                    anchors.rightMargin: Theme.s4
                                    spacing: Theme.s3
                                    PLabel { kind: "num"; text: visit.date; Layout.preferredWidth: Theme.grid(110) }
                                    PLabel { kind: "num"; text: visit.time; color: Theme.textMuted; Layout.preferredWidth: Theme.grid(44) }
                                    PLabel { Layout.fillWidth: true; text: visit.place }
                                    PLabel {
                                        kind: "num"
                                        color: Theme.textMuted
                                        text: visit.sightings === 1 ? qsTr("1 sighting") : qsTr("%1 sightings").arg(visit.sightings)
                                    }
                                }
                            }
                        }
                    }
                }

                Card {
                    Layout.preferredWidth: Theme.grid(300)
                    Layout.alignment: Qt.AlignTop
                    Layout.preferredHeight: Theme.grid(120)
                    ColumnLayout {
                        anchors.fill: parent
                        spacing: Theme.s2
                        SectionHeader { text: qsTr("Backups") }
                        RowLayout {
                            spacing: Theme.s2
                            PIcon {
                                name: home.backup !== "" ? "shield-check" : "triangle-alert"
                                color: home.backup !== "" ? Theme.positive : Theme.warning
                            }
                            PLabel {
                                objectName: "homeBackup"
                                kind: "num"
                                text: home.backup !== "" ? qsTr("Latest %1").arg(home.backup) : qsTr("No backup yet")
                            }
                        }
                        PLabel {
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            kind: "caption"
                            text: qsTr("One a day when the list is open, kept 7 daily, 5 weekly, 12 monthly; each holds a .bsxm Scythebill can open.")
                        }
                    }
                }
            }
        }
    }
}
