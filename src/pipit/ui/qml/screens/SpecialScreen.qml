// Special reports. The family report counts the Reports screen's query by order, family or
// genus against the checklist of its places (the world without one), as Scythebill's does.
// Keyboard map (F1):
//   Ctrl+G          group by order, family, genus (cycles)
//   Ctrl+R          into the groups; Up/Down, PageUp/PageDown, Home/End choose
//   Ctrl+Shift+Q    edit the query (on Reports)
import QtQuick
import QtQuick.Controls.Basic as B
import QtQuick.Layouts
import Pipit

Item {
    id: root
    objectName: "specialScreen"
    readonly property bool shown: shell.currentKey === "special"
    readonly property bool working: app.hasList && app.taxaReady
    readonly property bool keysOn: shown && working

    onShownChanged: special.setActive(shown)
    Component.onCompleted: special.setActive(shown)

    function cycleGroupBy() {
        const choices = special.groupByChoices
        const at = choices.findIndex(c => c[0] === special.groupBy)
        special.setGroupBy(choices[(at + 1) % choices.length][0])
    }
    function focusGroups() { if (groups.count > 0) { groups.forceActiveFocus(); if (special.selectedIndex < 0) special.select(0) } }

    Shortcut { enabled: root.keysOn; sequence: "Ctrl+G"; onActivated: root.cycleGroupBy() }
    Shortcut { enabled: root.keysOn; sequence: "Ctrl+R"; onActivated: root.focusGroups() }
    Shortcut { enabled: root.keysOn; sequence: "Ctrl+Shift+Q"; onActivated: shell.go("reports") }

    EmptyState {
        anchors.centerIn: parent
        visible: !root.working
        iconName: app.hasList ? "loader-circle" : "sparkles"
        title: app.hasList ? qsTr("Loading the taxonomy…") : qsTr("Open or import a list")
        text: app.hasList ? "" : qsTr("Ctrl+O opens a Pipit list. “Import Scythebill list” in Ctrl+K brings in a .bsxm file.")
    }

    B.SplitView {
        anchors.fill: parent
        anchors.margins: Theme.windowPad
        visible: root.working
        orientation: Qt.Horizontal
        handle: Rectangle { implicitWidth: Theme.s3; color: "transparent" }

        // ------------------------------------------------------------ the reports
        Card {
            B.SplitView.preferredWidth: Theme.grid(232)
            B.SplitView.minimumWidth: Theme.grid(160)
            ColumnLayout {
                anchors.fill: parent
                spacing: Theme.s1
                SectionHeader { Layout.fillWidth: true; text: qsTr("Reports") }
                Repeater {
                    model: [
                        { title: qsTr("Family report"), icon: "list-tree", ready: true },
                        { title: qsTr("Timeline"), icon: "calendar", ready: false },
                        { title: qsTr("Year comparison"), icon: "chart-column", ready: false },
                        { title: qsTr("Splits and lumps"), icon: "git-merge", ready: false },
                        { title: qsTr("Ticks map"), icon: "map-pin", ready: false },
                        { title: qsTr("Lifers map"), icon: "map-pin", ready: false },
                        { title: qsTr("Checklist status"), icon: "badge-check", ready: false }
                    ]
                    Rectangle {
                        id: reportItem
                        required property var modelData
                        required property int index
                        readonly property bool selected: index === 0
                        Layout.fillWidth: true
                        Layout.preferredHeight: Theme.rowH
                        radius: Theme.radiusMd
                        color: selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface) : "transparent"
                        Rectangle { visible: reportItem.selected; width: 2; height: parent.height - Theme.s2; anchors.verticalCenter: parent.verticalCenter; color: Theme.accent }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.s3
                            anchors.rightMargin: Theme.s2
                            spacing: Theme.s2
                            PIcon { name: reportItem.modelData.icon; size: Theme.iconSm; color: reportItem.modelData.ready ? Theme.text : Theme.textFaint }
                            PLabel {
                                Layout.fillWidth: true
                                text: reportItem.modelData.title
                                color: reportItem.modelData.ready ? Theme.text : Theme.textFaint
                                elide: Text.ElideRight
                            }
                            Badge { visible: !reportItem.modelData.ready; text: qsTr("Soon"); neutral: true }
                        }
                    }
                }
                Item { Layout.fillHeight: true }
            }
        }

        // ------------------------------------------------------------ the family report
        Card {
            B.SplitView.fillWidth: true
            B.SplitView.minimumWidth: Theme.grid(560)
            padV: 0
            padH: 0
            clip: true
            ColumnLayout {
                anchors.fill: parent
                spacing: 0
                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.headerH
                    Layout.leftMargin: Theme.s4
                    Layout.rightMargin: Theme.s4
                    spacing: Theme.s2
                    Column {
                        Layout.fillWidth: true
                        PLabel { width: parent.width; kind: "title"; text: qsTr("Family report"); elide: Text.ElideRight }
                        PLabel {
                            objectName: "familyChecklist"
                            width: parent.width
                            kind: "caption"
                            elide: Text.ElideRight
                            text: special.error !== "" ? special.error
                                : special.checklistName !== "" ? qsTr("Checklist: %1").arg(special.checklistName)
                                : qsTr("Every species in the world")
                            color: special.error !== "" ? Theme.warning : Theme.textMuted
                        }
                    }
                    PButton {
                        compact: true
                        variant: "ghost"
                        iconName: "sliders-horizontal"
                        text: qsTr("Edit query")
                        onClicked: shell.go("reports")
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

                // Summary and options
                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: Theme.s4
                    spacing: Theme.s3
                    KpiCard {
                        objectName: "familySpecies"
                        Layout.fillWidth: true
                        Layout.minimumWidth: Theme.grid(112)
                        Layout.maximumWidth: Theme.grid(200)
                        label: qsTr("Species seen")
                        value: special.ready ? Number(special.seenSpecies).toLocaleString(Qt.locale("en_US"), "f", 0) : ""
                        sub: special.ready ? qsTr("of %1 · %2%").arg(Number(special.totalSpecies).toLocaleString(Qt.locale("en_US"), "f", 0))
                                                                 .arg(Math.floor(special.speciesFraction * 100)) : ""
                    }
                    KpiCard {
                        objectName: "familyGroups"
                        Layout.fillWidth: true
                        Layout.minimumWidth: Theme.grid(112)
                        Layout.maximumWidth: Theme.grid(200)
                        label: qsTr("%1 seen").arg(special.groupsLabel)
                        value: special.ready ? Number(special.seenGroups).toLocaleString(Qt.locale("en_US"), "f", 0) : ""
                        sub: special.ready ? qsTr("of %1").arg(Number(special.totalGroups).toLocaleString(Qt.locale("en_US"), "f", 0)) : ""
                    }
                    Item { Layout.fillWidth: true }
                    GridLayout {
                        columns: 2
                        columnSpacing: Theme.s2
                        rowSpacing: Theme.s2
                        PLabel { kind: "caption"; text: qsTr("Group by") }
                        PComboBox {
                            objectName: "familyGroupBy"
                            Layout.preferredWidth: Theme.grid(136)
                            implicitHeight: Theme.controlHCompact
                            model: special.groupByChoices.map(c => c[1])
                            currentIndex: special.groupByChoices.findIndex(c => c[0] === special.groupBy)
                            onActivated: i => special.setGroupBy(special.groupByChoices[i][0])
                        }
                        PLabel { kind: "caption"; text: qsTr("Sort by") }
                        RowLayout {
                            spacing: Theme.s1
                            PComboBox {
                                objectName: "familySort"
                                Layout.preferredWidth: Theme.grid(136)
                                implicitHeight: Theme.controlHCompact
                                model: special.sortChoices.map(c => c[1])
                                currentIndex: special.sortChoices.findIndex(c => c[0] === special.sort)
                                onActivated: i => special.setSort(special.sortChoices[i][0])
                            }
                            PIconButton {
                                objectName: "familyDirection"
                                enabled: special.sort !== "TAXONOMIC"
                                iconName: "arrow-up-down"
                                tip: special.descending ? qsTr("Highest first (click for lowest)") : qsTr("Lowest first (click for highest)")
                                implicitWidth: Theme.controlHCompact
                                implicitHeight: Theme.controlHCompact
                                onClicked: special.setDescending(!special.descending)
                            }
                        }
                    }
                }
                Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }

                // Column headings
                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.rowHDense
                    Layout.leftMargin: Theme.s4
                    Layout.rightMargin: Theme.s4
                    spacing: Theme.s3
                    PLabel { Layout.fillWidth: true; kind: "overline"; text: special.groupBy === "ORDER" ? qsTr("Order") : special.groupBy === "GENUS" ? qsTr("Genus") : qsTr("Family") }
                    PLabel { Layout.preferredWidth: Theme.grid(120); kind: "overline"; text: qsTr("Seen") }
                    PLabel { Layout.preferredWidth: Theme.grid(84); kind: "overline"; text: qsTr("Species"); horizontalAlignment: Text.AlignRight }
                    PLabel { Layout.preferredWidth: Theme.grid(44); kind: "overline"; text: "%"; horizontalAlignment: Text.AlignRight }
                }
                ListView {
                    id: groups
                    objectName: "familyGroupsList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: special.groups
                    currentIndex: special.selectedIndex
                    highlightMoveDuration: 0
                    keyNavigationEnabled: false
                    boundsBehavior: Flickable.StopAtBounds
                    reuseItems: true
                    B.ScrollBar.vertical: B.ScrollBar {}
                    onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                    readonly property int page: Math.max(1, Math.floor(height / Theme.rowH) - 1)
                    Keys.onPressed: event => {
                        const index = special.selectedIndex
                        if (event.key === Qt.Key_Down) special.selectStep(index, 1)
                        else if (event.key === Qt.Key_Up) special.selectStep(index, -1)
                        else if (event.key === Qt.Key_PageDown) special.selectStep(index, page)
                        else if (event.key === Qt.Key_PageUp) special.selectStep(index, -page)
                        else if (event.key === Qt.Key_Home) special.select(0)
                        else if (event.key === Qt.Key_End) special.select(count - 1)
                        else return
                        event.accepted = true
                    }
                    delegate: Rectangle {
                        id: group
                        required property int index
                        required property string name
                        required property string scientific
                        required property int seen
                        required property int total
                        required property string percent
                        required property real fraction
                        required property string counts
                        readonly property bool selected: index === special.selectedIndex
                        width: ListView.view.width
                        height: Theme.rowH
                        color: selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
                             : hover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface) : "transparent"
                        Rectangle { visible: group.selected; width: 2; height: parent.height; color: groups.activeFocus ? Theme.accent : Theme.borderStrong }
                        HoverHandler { id: hover }
                        TapHandler { onTapped: { special.select(group.index); groups.forceActiveFocus() } }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.s4
                            anchors.rightMargin: Theme.s4
                            spacing: Theme.s3
                            Row {
                                Layout.fillWidth: true
                                spacing: Theme.s2
                                clip: true
                                PLabel { text: group.name; color: group.seen > 0 ? Theme.text : Theme.textMuted }
                                PLabel { text: group.scientific; color: Theme.textFaint; font.italic: true; visible: text !== "" }
                            }
                            PProgressBar {
                                Layout.preferredWidth: Theme.grid(120)
                                value: group.fraction
                                tone: group.seen === group.total ? Theme.positive : Theme.accent
                            }
                            PLabel { Layout.preferredWidth: Theme.grid(84); kind: "num"; text: group.counts; horizontalAlignment: Text.AlignRight }
                            PLabel {
                                Layout.preferredWidth: Theme.grid(44)
                                kind: "num"
                                text: group.percent
                                horizontalAlignment: Text.AlignRight
                                color: group.seen === group.total ? Theme.positive : Theme.textMuted
                            }
                        }
                    }
                }
            }
        }

        // ------------------------------------------------------------ one group's species
        Card {
            B.SplitView.preferredWidth: Theme.grid(280)
            B.SplitView.minimumWidth: Theme.grid(200)
            padH: 0
            ColumnLayout {
                anchors.fill: parent
                spacing: Theme.s2
                SectionHeader {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.s4
                    Layout.rightMargin: Theme.s4
                    text: special.selectedName !== "" ? special.selectedName : qsTr("Species")
                }
                PLabel {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.s4
                    Layout.rightMargin: Theme.s4
                    visible: special.selectedIndex < 0
                    kind: "caption"
                    wrapMode: Text.WordWrap
                    text: qsTr("Choose a group to see its species: those seen, and those still to find.")
                }
                ListView {
                    objectName: "familySpeciesList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: special.species
                    boundsBehavior: Flickable.StopAtBounds
                    reuseItems: true
                    B.ScrollBar.vertical: B.ScrollBar {}
                    delegate: Item {
                        id: speciesItem
                        required property string name
                        required property string scientific
                        required property bool seen
                        width: ListView.view.width
                        height: Theme.rowHDense
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.s4
                            anchors.rightMargin: Theme.s4
                            spacing: Theme.s2
                            PIcon {
                                name: speciesItem.seen ? "circle-check" : "circle"
                                size: Theme.iconSm
                                color: speciesItem.seen ? Theme.positive : Theme.textFaint
                            }
                            PLabel {
                                Layout.fillWidth: true
                                text: speciesItem.name
                                elide: Text.ElideRight
                                color: speciesItem.seen ? Theme.text : Theme.textMuted
                            }
                        }
                    }
                }
            }
        }
    }
}
