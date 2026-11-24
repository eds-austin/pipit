// Text in one of the type tokens: display, kpi, title, body, strong, num, caption, overline.
import QtQuick

Text {
    property string kind: "body"
    color: kind === "caption" || kind === "overline" ? Theme.textMuted : Theme.text
    font.family: kind === "num" || kind === "kpi" ? Theme.fontNum : Theme.fontUi
    font.pixelSize: kind === "display" ? Theme.sizeDisplay
        : kind === "kpi" ? Theme.sizeKpi
        : kind === "title" ? Theme.sizeTitle
        : kind === "caption" || kind === "overline" ? Theme.sizeCaption
        : Theme.sizeBody
    font.weight: kind === "display" || kind === "kpi" || kind === "title" || kind === "strong" ? Font.DemiBold
        : kind === "caption" || kind === "overline" ? Font.Medium : Font.Normal
    font.capitalization: kind === "overline" ? Font.AllUppercase : Font.MixedCase
    font.letterSpacing: kind === "overline" ? Theme.captionTracking : 0
    font.features: kind === "num" || kind === "kpi" ? { "tnum": 1 } : {}
    elide: Text.ElideRight
    verticalAlignment: Text.AlignVCenter
    textFormat: Text.PlainText
}
