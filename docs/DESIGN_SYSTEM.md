# Pipit design system

> A **soft dark** desktop UI that matches Eric's other apps, **portfolio-tracker** and **perfect-audio-copy**: quiet surfaces, crisp tabular numbers, and colour used only for meaning.
> The tokens are shared with portfolio-tracker's `ui/theme/tokens.py`, which is the reference. The QML theme and components are forked from perfect-audio-copy.
> Implementation: `src/pipit/ui/qml/Pipit/Theme.qml` is a QML singleton and the single source of truth. The Qt palette in `ui/backend/theme.py` mirrors the same colours for popups, tooltips and scroll bars.
> Rule: **components never hard-code a colour, font size or spacing value.** They reference `Theme`.

Pipit draws every control itself on top of Qt Quick Controls' **Basic** style. It does not follow the Plasma colour scheme, on purpose, so it looks the same as the other apps.

## 1. Principles

1. **Lists are the content.** Counts, dates, times and totals use JetBrains Mono with tabular figures, so digits line up down columns.
2. **Colour means something.** Neutral greys carry structure. Every coloured status also has text or an icon, never colour alone.
3. **Calm density.** 4 px grid, flat surfaces, hairline borders, no shadows or gradients. Elevation comes from stepping `bg → surface → surface2 → surface3`.
4. **Made for a maximized window.** Panes stretch and split; only the sidebar has a fixed width. Text is larger than Scythebill's.
5. **Keyboard first.** Every screen and action has a shortcut or is in the Ctrl+K palette. Focus is always visible as a 2 px accent ring.

## 2. Colour tokens

| Token | Hex | Use |
|---|---|---|
| `bg` | `#0E1116` | Window, title strip |
| `surface` | `#151A21` | Sidebar, cards, tables, status bar |
| `surface2` | `#1B222C` | Inputs, table headers, dialogs, the palette |
| `surface3` | `#232B37` | Pressed and hover states, neutral badges, keycaps |
| `border` / `borderStrong` | `#2A3340` / `#3A4555` | Hairlines / input borders |
| `text` / `textMuted` / `textFaint` | `#E6EDF3` / `#8B97A6` / `#5D6876` | Primary / labels / placeholders and disabled |
| `textOnAccent` | `#0B0E12` | Text on accent fills |

Semantic colours, as they apply to birding:

| Token | Hex | Meaning here |
|---|---|---|
| `accent` | `#4C9AFF` | Primary action, focus ring, selection, the active location slot |
| `positive` | `#2FBF71` | Lifer, year tick, saved |
| `warning` | `#E3B341` | Rarity, needs review, unresolved sp. |
| `negative` | `#F2545B` | Errors, destructive actions, failed checks |
| `info` | `#9A8CFF` | Endemic, subspecies or group, informational |

Tints: `soft` = 12% over surface (badges), `rowTint` = 6% (whole-row highlight), hover 6%, selected 14% plus a 2 px left accent bar.

## 3. Typography and scale

Pipit adds one token to the shared set: **`scale`**, the "Text size" setting (`ui_scale` in `settings.toml`, default **1.15**, range 0.9 to 1.6). Type sizes are multiplied by it and rounded. Control and row heights are multiplied and snapped to the 4 px grid with `Theme.grid()`. Spacing and radii never scale.

| Kind (`PLabel.kind`) | Family | px at 1.0 | px at 1.15 | Weight | Use |
|---|---|---|---|---|---|
| `display` | Inter | 28 | 32 | 600 | (reserved) |
| `kpi` | JetBrains Mono | 20 | 23 | 600 | KPI card values |
| `title` | Inter | 15 | 17 | 600 | Screen and dialog titles |
| `body` / `strong` | Inter | 13 | 15 | 400 / 600 | Default text / headers |
| `num` | JetBrains Mono | 13 | 15 | 400 | Counts, dates, times (`tnum`) |
| `caption` / `overline` | Inter | 11 | 13 | 500 | Secondary lines / uppercase labels and badges (+0.04em) |

Fonts are bundled under `ui/assets/fonts` (SIL OFL). If they cannot be loaded, the system UI and monospace fonts are used.

## 4. Spacing and sizes

Spacing `s1…s8` = 4, 8, 12, 16, 20, 24, 32, 40. Radii 4 (badges) / 6 (inputs, buttons) / 10 (cards, dialogs). Window padding 16, gap between sections 12, card padding 12/16.

Heights at scale 1.0, scaled with `grid()`: header 56, title strip 40, status bar 24, controls 32 (28 compact), table rows 40, **dense rows 28** (sightings and checklists), badges 22. Sidebar 200 wide (48 collapsed), side panes 320, dialogs 560, palette 640.

## 5. Shell

- **Sidebar**: one entry per screen, Settings pinned to the bottom. Selected = 14% accent tint plus the 2 px bar. The shortcut appears in the tooltip. Ctrl+B collapses it to icons.
- **Title strip**: back button (Alt+Left), screen title, list status chip, and a search-field button that opens the palette.
- **Command palette** (Ctrl+K): `surface2` popup near the top, word-prefix matching ("ensi" finds "Enter sightings"), category overline, keycap on the right. Up/Down choose, Enter runs, Esc closes.
- **Status bar**: save state on the left, F1 and the version on the right.
- **Key overlay** (F1): every global shortcut. Screens add their own sections as they are built.

## 6. Components (`ui/qml/Pipit`)

- **Card**: `surface`, 1 px `border`, radius 10.
- **Badge / StatusChip**: uppercase caption on a soft tint. `StatusChip.kind` is `positive`, `warning`, `negative`, `info` or `neutral`, and adds the matching icon.
- **PButton**: `primary` (accent fill), `secondary` (surface2 + border), `ghost`, `danger` (negative on soft tint). Focus ring 2 px accent.
- **PTextField**: `surface2`, strong border, accent focus ring. `num` uses the mono face. `bare` hides the border until hover or focus. `focusRing: false` is only for fields inside a container that already shows focus, such as the palette.
- **KeyHint**: a keycap showing a shortcut in the mono face; `subtle` drops the cap.
- **SidebarItem**, **EmptyState**, **KpiCard** (overline label, mono value, caption sub-line), **PDialog** (`surface2`, radius 10, title row with close button, footer actions on the right), **SectionHeader**, **PCheckBox**, **PSwitch**, **PComboBox**, **PProgressBar**, **PIconButton**.
- **Icons**: Lucide outline icons (ISC licence, `ui/assets/icons`), tinted from tokens by the `image://icon/<name>/<RRGGBB>` provider at a 1.75 stroke.
