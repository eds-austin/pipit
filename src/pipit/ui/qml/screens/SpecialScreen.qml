// Special reports. The family report counts the Reports screen's query by order, family or
// genus against the checklist of its places (the world without one), as Scythebill's does;
// the checklist status report lists species seen where their place's checklist gives them a
// status (not on it, rarity, endemic, ...); splits and lumps shows how the query's species
// would count in another taxonomy version; the year comparison shows each species' sightings
// year by year. Keyboard map (F1):
//   Alt+1…4         family report, checklist status, splits and lumps, year comparison
//   Ctrl+G          (family) group by order, family, genus (cycles)
//   Ctrl+R          into the list; Up/Down, PageUp/PageDown, Home/End choose
//   Enter           (checklist status) show the species' place on Locations
//   Left/Right      (year comparison) choose a year; Esc clears it
//   Ctrl+Shift+Q    (family, splits, years) edit the query (on Reports)
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

    readonly property bool family: special.report === "family"
    function focusStatus() { if (statusList.count > 0) { statusList.forceActiveFocus(); if (statusList.currentIndex < 0) statusList.moveTo(0, 1) } }

    Shortcut { enabled: root.keysOn; sequence: "Alt+1"; onActivated: special.setReport("family") }
    Shortcut { enabled: root.keysOn; sequence: "Alt+2"; onActivated: special.setReport("status") }
    Shortcut { enabled: root.keysOn; sequence: "Alt+3"; onActivated: special.setReport("splits") }
    Shortcut { enabled: root.keysOn; sequence: "Alt+4"; onActivated: special.setReport("years") }
    Shortcut { enabled: root.keysOn && root.family; sequence: "Ctrl+G"; onActivated: root.cycleGroupBy() }
    Shortcut { enabled: root.keysOn; sequence: "Ctrl+R"; onActivated: root.family ? root.focusGroups() : root.focusStatus() }
    Shortcut { enabled: root.keysOn && special.report !== "status"; sequence: "Ctrl+Shift+Q"; onActivated: shell.go("reports") }

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
                        { key: "family", title: qsTr("Family report"), icon: "list-tree", ready: true },
                        { key: "status", title: qsTr("Checklist status"), icon: "badge-check", ready: true },
                        { key: "splits", title: qsTr("Splits and lumps"), icon: "git-merge", ready: true },
                        { key: "years", title: qsTr("Year comparison"), icon: "chart-column", ready: true },
                        { key: "", title: qsTr("Timeline"), icon: "calendar", ready: false },
                        { key: "", title: qsTr("Ticks map"), icon: "map-pin", ready: false },
                        { key: "", title: qsTr("Lifers map"), icon: "map-pin", ready: false }
                    ]
                    Rectangle {
                        id: reportItem
                        required property var modelData
                        required property int index
                        readonly property bool selected: modelData.key === special.report
                        objectName: "specialReport_" + modelData.key
                        Layout.fillWidth: true
                        Layout.preferredHeight: Theme.rowH
                        radius: Theme.radiusMd
                        color: selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
                             : reportHover.hovered && modelData.ready ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface) : "transparent"
                        HoverHandler { id: reportHover; enabled: reportItem.modelData.ready }
                        TapHandler { enabled: reportItem.modelData.ready; onTapped: special.setReport(reportItem.modelData.key) }
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
                            KeyHint { visible: reportItem.modelData.ready; keys: "Alt+" + (reportItem.index + 1); subtle: true }
                        }
                    }
                }
                Item { Layout.fillHeight: true }
            }
        }

        StackLayout {
            B.SplitView.fillWidth: true
            B.SplitView.minimumWidth: Theme.grid(560)
            currentIndex: ["family", "status", "splits", "years"].indexOf(special.report)

            B.SplitView {
                orientation: Qt.Horizontal
                handle: Rectangle { implicitWidth: Theme.s3; color: "transparent" }

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

            // ------------------------------------------------------------ checklist status
            Card {
                objectName: "statusReport"
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
                        spacing: Theme.s3
                        Column {
                            Layout.fillWidth: true
                            PLabel { width: parent.width; kind: "title"; text: qsTr("Checklist status"); elide: Text.ElideRight }
                            PLabel {
                                objectName: "statusSummary"
                                width: parent.width
                                kind: "caption"
                                elide: Text.ElideRight
                                text: special.statusSummary
                            }
                        }
                        PLabel { kind: "caption"; text: qsTr("Status") }
                        PComboBox {
                            objectName: "statusChoice"
                            Layout.preferredWidth: Theme.grid(200)
                            implicitHeight: Theme.controlHCompact
                            model: special.statusChoices.map(c => c[1])
                            currentIndex: special.statusChoices.findIndex(c => c[0] === special.statusChoice)
                            onActivated: i => special.setStatusChoice(special.statusChoices[i][0])
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                    PLabel {
                        Layout.fillWidth: true
                        Layout.margins: Theme.s4
                        Layout.bottomMargin: 0
                        visible: special.statusNote !== ""
                        wrapMode: Text.WordWrap
                        color: Theme.warning
                        text: special.statusNote
                    }
                    ListView {
                        id: statusList
                        objectName: "statusList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.topMargin: Theme.s2
                        clip: true
                        model: special.statusRows
                        currentIndex: -1
                        highlightMoveDuration: 0
                        keyNavigationEnabled: false
                        boundsBehavior: Flickable.StopAtBounds
                        reuseItems: true
                        B.ScrollBar.vertical: B.ScrollBar {}
                        onCountChanged: currentIndex = -1
                        onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                        readonly property int page: Math.max(1, Math.floor(height / Theme.rowH) - 1)
                        // Chooses the species row at or past ``target`` in direction ``dir`` (headings
                        // are skipped), or the nearest one back the other way.
                        function moveTo(target, dir) {
                            target = Math.max(0, Math.min(count - 1, target))
                            for (let i = target; i >= 0 && i < count; i += dir)
                                if (!special.statusIsHeading(i)) { currentIndex = i; return }
                            for (let i = target; i >= 0 && i < count; i -= dir)
                                if (!special.statusIsHeading(i)) { currentIndex = i; return }
                        }
                        function open() {
                            if (currentIndex < 0) return
                            locations.showPlace(special.statusPlace(currentIndex))
                            shell.go("locations")
                        }
                        Keys.onPressed: event => {
                            const index = currentIndex
                            if (event.key === Qt.Key_Down) moveTo(index + 1, 1)
                            else if (event.key === Qt.Key_Up) moveTo(index - 1, -1)
                            else if (event.key === Qt.Key_PageDown) moveTo(index + page, 1)
                            else if (event.key === Qt.Key_PageUp) moveTo(index - page, -1)
                            else if (event.key === Qt.Key_Home) moveTo(0, 1)
                            else if (event.key === Qt.Key_End) moveTo(count - 1, -1)
                            else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) open()
                            else return
                            event.accepted = true
                        }
                        delegate: Rectangle {
                            id: statusRow
                            required property int index
                            required property bool heading
                            required property string name
                            required property string scientific
                            required property string range
                            required property bool custom
                            readonly property bool selected: index === statusList.currentIndex
                            width: ListView.view.width
                            height: heading ? Theme.rowH + Theme.s2 : (range !== "" ? Theme.rowH + Theme.s4 : Theme.rowH)
                            color: selected ? Theme.tint(Theme.accent, Theme.selectedAlpha, Theme.surface)
                                 : rowHover.hovered && !heading ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface) : "transparent"
                            Rectangle { visible: statusRow.selected; width: 2; height: parent.height; color: statusList.activeFocus ? Theme.accent : Theme.borderStrong }
                            HoverHandler { id: rowHover; enabled: !statusRow.heading }
                            TapHandler {
                                enabled: !statusRow.heading
                                onTapped: { statusList.currentIndex = statusRow.index; statusList.forceActiveFocus() }
                                onDoubleTapped: { statusList.currentIndex = statusRow.index; statusList.open() }
                            }
                            RowLayout {
                                visible: statusRow.heading
                                anchors.left: parent.left
                                anchors.leftMargin: Theme.s4
                                anchors.right: parent.right
                                anchors.rightMargin: Theme.s4
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: Theme.s1
                                spacing: Theme.s2
                                PIcon { name: "map-pin"; size: Theme.iconSm; color: Theme.textMuted }
                                PLabel { kind: "strong"; text: statusRow.name }
                                Badge { visible: statusRow.custom; text: qsTr("Your checklist"); tone: Theme.info }
                                Item { Layout.fillWidth: true }
                            }
                            Column {
                                visible: !statusRow.heading
                                anchors.left: parent.left
                                anchors.leftMargin: Theme.s4 + Theme.s5
                                anchors.right: parent.right
                                anchors.rightMargin: Theme.s4
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 0
                                Row {
                                    spacing: Theme.s2
                                    PLabel { text: statusRow.name }
                                    PLabel { text: statusRow.scientific; color: Theme.textFaint; font.italic: true }
                                }
                                PLabel {
                                    visible: statusRow.range !== ""
                                    width: parent.width
                                    kind: "caption"
                                    elide: Text.ElideRight
                                    text: qsTr("Expected range: %1").arg(statusRow.range)
                                }
                            }
                        }
                    }
                }
            }

            // ------------------------------------------------------------ splits and lumps
            Card {
                objectName: "splitsReport"
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
                        spacing: Theme.s3
                        Column {
                            Layout.fillWidth: true
                            PLabel { width: parent.width; kind: "title"; text: qsTr("Splits and lumps"); elide: Text.ElideRight }
                            PLabel {
                                objectName: "splitsTotals"
                                width: parent.width
                                kind: "caption"
                                elide: Text.ElideRight
                                text: special.splitsError !== "" ? special.splitsError : special.splitsTotals
                                color: special.splitsError !== "" ? Theme.warning : Theme.textMuted
                            }
                        }
                        PLabel { kind: "caption"; text: qsTr("Compare") }
                        PComboBox {
                            objectName: "splitsVersion"
                            Layout.preferredWidth: Theme.grid(260)
                            implicitHeight: Theme.controlHCompact
                            model: special.splitsVersions.map(v => v[1])
                            currentIndex: special.splitsVersions.findIndex(v => v[0] === special.splitsVersion)
                            onActivated: i => special.setSplitsVersion(special.splitsVersions[i][0])
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
                    ListView {
                        id: splitsList
                        objectName: "splitsList"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        Layout.topMargin: Theme.s2
                        clip: true
                        model: special.splitsRows
                        boundsBehavior: Flickable.StopAtBounds
                        B.ScrollBar.vertical: B.ScrollBar {}
                        delegate: Item {
                            id: splitsRow
                            required property bool heading
                            required property string text
                            width: ListView.view.width
                            height: line.implicitHeight + (heading ? Theme.s5 : Theme.s3)
                            PLabel {
                                id: line
                                anchors.left: parent.left
                                anchors.leftMargin: splitsRow.heading ? Theme.s4 : Theme.s4 + Theme.s3
                                anchors.right: parent.right
                                anchors.rightMargin: Theme.s4
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: splitsRow.heading ? Theme.s1 : Theme.s1
                                kind: splitsRow.heading ? "overline" : "body"
                                textFormat: splitsRow.heading ? Text.PlainText : Text.StyledText
                                wrapMode: Text.WordWrap
                                text: splitsRow.text
                            }
                        }
                    }
                }
            }

            // ------------------------------------------------------------ year comparison
            Card {
                id: yearsCard
                objectName: "yearsReport"
                padV: 0
                padH: 0
                clip: true
                readonly property var span: special.yearsSpan
                readonly property int nameWidth: Theme.grid(240)
                readonly property real cellWidth: span.length === 0 ? 0
                    : Math.max(4, Math.min(Theme.grid(28), (width - nameWidth - Theme.s4 * 2 - Theme.s3) / span.length))
                readonly property int selectedIndex: special.selectedYear === 0 ? -1 : span.indexOf(special.selectedYear)
                property string hoverText: ""
                function bucketColor(level) {
                    return level === 1 ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.5)
                         : level === 2 ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.75)
                         : level === 3 ? Theme.accent
                         : level >= 4 ? Qt.tint(Theme.accent, Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, 0.35)) : "transparent"
                }
                Keys.onPressed: event => {
                    if (span.length === 0) return
                    if (event.key === Qt.Key_Left || event.key === Qt.Key_Right) {
                        const step = event.key === Qt.Key_Left ? -1 : 1
                        const at = selectedIndex < 0 ? (step < 0 ? span.length - 1 : 0)
                                                     : Math.max(0, Math.min(span.length - 1, selectedIndex + step))
                        special.selectYear(span[at])
                        event.accepted = true
                    } else if (event.key === Qt.Key_Escape && selectedIndex >= 0) {
                        special.selectYear(0)
                        event.accepted = true
                    }
                }
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
                            PLabel { width: parent.width; kind: "title"; text: qsTr("Year comparison"); elide: Text.ElideRight }
                            PLabel {
                                objectName: "yearsSummary"
                                width: parent.width
                                kind: "caption"
                                elide: Text.ElideRight
                                text: special.yearsError !== "" ? special.yearsError : special.yearsSummary
                                color: special.yearsError !== "" ? Theme.warning : Theme.textMuted
                            }
                        }
                        PLabel { kind: "caption"; text: qsTr("From") }
                        PTextField {
                            id: fromYear
                            objectName: "yearsFrom"
                            num: true
                            Layout.preferredWidth: Theme.grid(72)
                            implicitHeight: Theme.controlHCompact
                            placeholderText: qsTr("Year")
                            text: special.yearsFrom
                            validator: IntValidator { bottom: 1; top: 9999 }
                            onEditingFinished: if (!special.setYearRange(fromYear.text, toYear.text)) fromYear.text = special.yearsFrom
                        }
                        PLabel { kind: "caption"; text: qsTr("to") }
                        PTextField {
                            id: toYear
                            objectName: "yearsTo"
                            num: true
                            Layout.preferredWidth: Theme.grid(72)
                            implicitHeight: Theme.controlHCompact
                            placeholderText: qsTr("Year")
                            text: special.yearsTo
                            validator: IntValidator { bottom: 1; top: 9999 }
                            onEditingFinished: if (!special.setYearRange(fromYear.text, toYear.text)) toYear.text = special.yearsTo
                        }
                        PLabel { kind: "caption"; text: qsTr("Sort"); Layout.leftMargin: Theme.s2 }
                        PComboBox {
                            objectName: "yearsSort"
                            Layout.preferredWidth: Theme.grid(160)
                            implicitHeight: Theme.controlHCompact
                            model: special.yearsSorts.map(s => s[1])
                            currentIndex: special.yearsSorts.findIndex(s => s[0] === special.yearsSort)
                            onActivated: i => special.setYearsSort(special.yearsSorts[i][0])
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

                    // Species per year: a bar for each year, aligned with the grid's columns
                    Item {
                        id: strip
                        objectName: "yearsStrip"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Theme.grid(112)
                        readonly property var counts: special.speciesPerYear
                        readonly property int most: counts.length ? Math.max.apply(null, counts) : 0
                        PLabel {
                            x: Theme.s4
                            y: Theme.s3
                            width: yearsCard.nameWidth - Theme.s3
                            kind: "overline"
                            text: qsTr("Species per year")
                        }
                        PLabel {
                            x: Theme.s4
                            y: Theme.s3 + Theme.s5
                            width: yearsCard.nameWidth - Theme.s3
                            kind: "caption"
                            wrapMode: Text.WordWrap
                            visible: special.selectedYear === 0
                            text: qsTr("Click a year (or use Left and Right) to see what was new or missing.")
                        }
                        PLabel {
                            x: Theme.s4
                            y: Theme.s3 + Theme.s5
                            kind: "kpi"
                            visible: special.selectedYear !== 0
                            text: yearsCard.selectedIndex >= 0 ? special.selectedYear + ": " + strip.counts[yearsCard.selectedIndex] : ""
                        }
                        Repeater {
                            model: yearsCard.span.length
                            Item {
                                id: bar
                                required property int index
                                readonly property bool chosen: index === yearsCard.selectedIndex
                                x: Theme.s4 + yearsCard.nameWidth + index * yearsCard.cellWidth
                                y: Theme.s3
                                width: yearsCard.cellWidth
                                height: strip.height - Theme.s3 - Theme.s5
                                Rectangle {
                                    anchors.bottom: parent.bottom
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: Math.max(2, parent.width - 2)
                                    height: strip.most > 0 ? Math.max(1, parent.height * strip.counts[bar.index] / strip.most) : 0
                                    radius: 2
                                    color: bar.chosen ? Theme.accent : barHover.hovered ? Theme.borderStrong : Theme.surface3
                                }
                                HoverHandler { id: barHover }
                                TapHandler {
                                    onTapped: {
                                        special.selectYear(bar.chosen ? 0 : yearsCard.span[bar.index])
                                        yearsCard.forceActiveFocus()
                                    }
                                }
                                PLabel {
                                    anchors.top: parent.bottom
                                    anchors.topMargin: 2
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    kind: "caption"
                                    font.family: Theme.fontNum
                                    visible: bar.chosen || (yearsCard.selectedIndex < 0 && (bar.index === 0 || bar.index === yearsCard.span.length - 1
                                             || (yearsCard.span[bar.index] % 10 === 0 && bar.index > 1 && bar.index < yearsCard.span.length - 2)))
                                    color: bar.chosen ? Theme.text : Theme.textMuted
                                    text: yearsCard.span[bar.index]
                                }
                            }
                        }
                    }

                    // All, or new or missing in the chosen year
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.s4
                        Layout.rightMargin: Theme.s4
                        Layout.bottomMargin: Theme.s2
                        spacing: Theme.s2
                        Repeater {
                            model: [
                                { key: "ALL", label: qsTr("All species") },
                                { key: "NEW", label: special.selectedYear ? qsTr("New in %1").arg(special.selectedYear) : qsTr("New in the year") },
                                { key: "MISSING", label: special.selectedYear ? qsTr("Missing in %1").arg(special.selectedYear) : qsTr("Missing in the year") }
                            ]
                            PButton {
                                required property var modelData
                                objectName: "yearsFilter_" + modelData.key
                                compact: true
                                enabled: modelData.key === "ALL" || special.selectedYear !== 0
                                variant: special.yearsFilter === modelData.key ? "primary" : "secondary"
                                text: modelData.label
                                onClicked: special.setYearsFilter(modelData.key)
                            }
                        }
                        Item { Layout.fillWidth: true }
                        PLabel {
                            kind: "caption"
                            text: qsTr("%1 rows").arg(Number(special.yearsRowCount).toLocaleString(Qt.locale("en_US"), "f", 0))
                        }
                        // Legend: Scythebill's buckets
                        Repeater {
                            model: [[1, "1"], [2, "2–4"], [3, "5–19"], [4, "20+"]]
                            Row {
                                required property var modelData
                                spacing: Theme.s1
                                Rectangle {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: Theme.s3; height: Theme.s3; radius: 2
                                    color: yearsCard.bucketColor(modelData[0])
                                }
                                PLabel { kind: "caption"; text: modelData[1] }
                            }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                    ListView {
                        id: yearsGrid
                        objectName: "yearsGrid"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: special.yearsRows
                        boundsBehavior: Flickable.StopAtBounds
                        reuseItems: true
                        B.ScrollBar.vertical: B.ScrollBar {}
                        // The chosen year's column
                        Rectangle {
                            visible: yearsCard.selectedIndex >= 0
                            x: Theme.s4 + yearsCard.nameWidth + yearsCard.selectedIndex * yearsCard.cellWidth
                            y: 0
                            z: -1
                            width: yearsCard.cellWidth
                            height: yearsGrid.height
                            color: Theme.tint(Theme.accent, Theme.rowAlpha, Theme.surface)
                        }
                        delegate: Item {
                            id: yearsRow
                            required property int index
                            required property string name
                            required property var buckets
                            required property int total
                            width: ListView.view.width
                            height: Theme.rowHDense
                            Rectangle {
                                anchors.fill: parent
                                color: rowHover.hovered ? Theme.tint(Theme.text, Theme.hoverAlpha, Theme.surface) : "transparent"
                            }
                            HoverHandler {
                                id: rowHover
                                onPointChanged: {
                                    const column = Math.floor((point.position.x - Theme.s4 - yearsCard.nameWidth) / yearsCard.cellWidth)
                                    yearsCard.hoverText = column >= 0 && column < yearsCard.span.length
                                        ? special.yearsCellText(yearsRow.index, column) : yearsRow.name
                                }
                                onHoveredChanged: if (!hovered) yearsCard.hoverText = ""
                            }
                            PLabel {
                                x: Theme.s4
                                width: yearsCard.nameWidth - Theme.s3
                                anchors.verticalCenter: parent.verticalCenter
                                text: yearsRow.name
                                elide: Text.ElideRight
                            }
                            Repeater {
                                model: yearsRow.buckets
                                Rectangle {
                                    required property int index
                                    required property int modelData
                                    x: Theme.s4 + yearsCard.nameWidth + index * yearsCard.cellWidth + 1
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: Math.max(2, yearsCard.cellWidth - 2)
                                    height: Math.min(width, Theme.rowHDense - Theme.s2)
                                    radius: 2
                                    color: modelData > 0 ? yearsCard.bucketColor(modelData) : "transparent"
                                    border.width: modelData > 0 ? 0 : 1
                                    border.color: Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.6)
                                }
                            }
                        }
                    }
                    Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: Theme.border }
                    PLabel {
                        objectName: "yearsHover"
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.s4
                        Layout.rightMargin: Theme.s4
                        Layout.preferredHeight: Theme.rowHDense
                        verticalAlignment: Text.AlignVCenter
                        kind: "caption"
                        elide: Text.ElideRight
                        text: yearsCard.hoverText !== "" ? yearsCard.hoverText
                            : qsTr("Point at a year to see its sightings and dates.")
                    }
                }
            }
        }
    }
}
