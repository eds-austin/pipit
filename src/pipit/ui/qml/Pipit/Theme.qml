// Design tokens: the single source of truth for colors, type, spacing and sizes.
// Same tokens as portfolio-tracker and perfect-audio-copy (docs/DESIGN_SYSTEM.md).
// Components never hard-code a color, size or spacing.
//
// Pipit addition: `scale` (the font-scale setting, default 1.15) enlarges type and
// control heights so a maximized window reads comfortably. Spacing stays on the
// fixed 4px grid; scaled heights are snapped back onto it.
pragma Singleton
import QtQuick

QtObject {
    id: theme

    // UI scale from settings (context property set by app.py); 1.15 = 15px body text.
    readonly property real scale: (typeof pipitUiScale !== "undefined") ? pipitUiScale : 1.15
    function grid(v) { return 4 * Math.round(v * scale / 4) }
    function type(v) { return Math.round(v * scale) }

    // Surfaces & lines (elevation = stepping bg -> surface -> surface2 -> surface3)
    readonly property color bg: "#0E1116"
    readonly property color surface: "#151A21"
    readonly property color surface2: "#1B222C"
    readonly property color surface3: "#232B37"
    readonly property color border: "#2A3340"
    readonly property color borderStrong: "#3A4555"
    // Text
    readonly property color text: "#E6EDF3"
    readonly property color textMuted: "#8B97A6"
    readonly property color textFaint: "#5D6876"
    readonly property color textOnAccent: "#0B0E12"
    // Semantic: colour always means something
    readonly property color accent: "#4C9AFF"      // primary action, focus, selection
    readonly property color positive: "#2FBF71"    // lifer, saved, OK
    readonly property color negative: "#F2545B"    // errors, destructive
    readonly property color warning: "#E3B341"     // rarity, needs attention
    readonly property color info: "#9A8CFF"        // informational (endemic, subspecies)

    // Tints (semantic colour over surface)
    readonly property real softAlpha: 0.12
    readonly property real rowAlpha: 0.06
    readonly property real hoverAlpha: 0.06
    readonly property real selectedAlpha: 0.14
    function tint(c, a, over) { return Qt.tint(over === undefined ? surface : over, Qt.rgba(c.r, c.g, c.b, a)) }
    function soft(c) { return tint(c, softAlpha) }
    function rowTint(c) { return tint(c, rowAlpha) }

    // Spacing: 4px grid (not scaled)
    readonly property int s1: 4
    readonly property int s2: 8
    readonly property int s3: 12
    readonly property int s4: 16
    readonly property int s5: 20
    readonly property int s6: 24
    readonly property int s7: 32
    readonly property int s8: 40
    readonly property int radiusSm: 4
    readonly property int radiusMd: 6
    readonly property int radiusLg: 10

    // Sizes (heights scale with type, snapped to the grid)
    readonly property int headerH: grid(56)
    readonly property int titleStripH: grid(40)
    readonly property int statusBarH: grid(24)
    readonly property int controlH: grid(32)
    readonly property int controlHCompact: grid(28)
    readonly property int rowH: grid(40)
    readonly property int rowHDense: grid(28)       // dense tables (sightings, checklists)
    readonly property int pillH: grid(22)
    readonly property int progressH: 4
    readonly property int windowPad: 16
    readonly property int sectionGap: 12
    readonly property int cardPadV: 12
    readonly property int cardPadH: 16
    readonly property int iconSm: grid(16)
    readonly property int iconMd: grid(18)
    readonly property int brandMark: grid(24)   // app mark in the sidebar
    readonly property int sidebarW: grid(200)
    readonly property int sidebarCollapsedW: grid(48)
    readonly property int sidePaneW: grid(320)
    readonly property int dialogW: grid(560)
    readonly property int paletteW: grid(640)

    // Type: Inter for UI, JetBrains Mono (tabular) for numbers, dates, counts
    readonly property string fontUi: Qt.application.font.family
    readonly property string fontNum: (typeof pipitMonoFamily !== "undefined") ? pipitMonoFamily : "monospace"
    readonly property int sizeDisplay: type(28)
    readonly property int sizeKpi: type(20)
    readonly property int sizeTitle: type(15)
    readonly property int sizeBody: type(13)
    readonly property int sizeCaption: type(11)
    readonly property real captionTracking: 0.04 * sizeCaption   // +0.04em
}
