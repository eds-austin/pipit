// A status as a badge with an icon: "positive", "warning", "negative", "info" or
// "neutral". The text always carries the meaning (never colour alone).
import QtQuick

Badge {
    property string kind: "neutral"
    neutral: kind === "neutral"
    tone: kind === "positive" ? Theme.positive
        : kind === "warning" ? Theme.warning
        : kind === "negative" ? Theme.negative
        : kind === "info" ? Theme.info
        : Theme.accent
    iconName: kind === "positive" ? "circle-check"
        : kind === "warning" || kind === "negative" ? "triangle-alert"
        : kind === "info" ? "info" : ""
}
