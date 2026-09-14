# Edit pixels by hand

Auto-restoration gets the grid and palette right, but sometimes a few cells need
a human touch — a stray color, a cleaned-up edge, a tweaked highlight. The web
app includes a built-in pixel editor for exactly this.

## Open the editor

1. Restore an image (drag-and-drop → **Make pixel-perfect**).
2. Click **✎ Edit pixels** (in the Result panel header). The editor opens as a
   full-screen overlay, pre-loaded with the restored image, its palette, and the
   confidence heatmap. Close it with **✕**, **Esc**, or by clicking the dimmed
   backdrop — your edits are kept if you reopen it for the same result.

## Tools

| Tool | Key | What it does |
|------|-----|--------------|
| ✏️ Pencil | `B` | Paint cells with the active color. Click, or click-drag. |
| ⌫ Eraser | `E` | Make cells transparent. |
| 🪣 Fill | `G` | Flood-fill a connected region of one color. |
| 💧 Eyedropper | `I` | Pick a cell's color as the active color. |
| ↶ / ↷ Undo / Redo | `Ctrl/⌘+Z` / `Shift+…` | Step through edit history. |
| − / + Zoom | `-` / `+` | Zoom the canvas. |

Toggle **Grid** for cell boundaries and **Heatmap** to overlay the confidence
map — red cells are where auto-detection was least sure, so they're the first
place to look for fixes.

## Colors: palette first, any color when you need it

- The **palette** swatches (default) come from the restored image. Click one to
  make it active. This keeps your edits on-palette.
- Need a color that isn't there? Pick any RGB color with the color well and
  click **+ Add color** — it's added as a swatch and selected.
- **Double-click a swatch to recolor it.** Because the editor stores an *indexed*
  image, recoloring a swatch updates **every pixel** using that color at once —
  handy for global tweaks (e.g. shift all shadows slightly darker).

## Export

- **Download 1×** — the true native-resolution PNG (one image pixel per logical
  pixel). This is your pixel-perfect asset.
- **Download 8×** — a nearest-neighbor upscaled PNG for previews/sharing.

Both go through the same server-side render path as the rest of the tool, so the
output is guaranteed pixel-perfect (uniform grid, exact palette colors,
transparency preserved).

## Notes

- Edits live in your browser. **Re-running restore** (changing params and
  clicking *Make pixel-perfect* again) starts fresh — the app warns you before
  discarding unsaved edits, and before closing the tab.
- Transparency is first-class: the eraser writes truly transparent pixels, and
  the PNG export preserves the alpha channel.

## Automation

The same indexed render is available without the UI via the
[`POST /api/export`](../reference/api.md#post-apiexport) endpoint and the
`pixelperfect.render_indexed()` / `export_indexed()` library functions — useful
for programmatic touch-ups or building your own editor.
