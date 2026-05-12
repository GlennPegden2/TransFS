# Client Logo System

Client logos are displayed next to client names in the Download tab UI, similar to manufacturer and system logos.

## Location
`app/static/logos/clients/`

## Format
- **PNG** with transparency
- Matches the format used for manufacturer and system logos

## Naming Convention
Logo files should be named after the client name in lowercase with spaces removed:
- `MiSTer` → `mister.png`
- `MAME` → `mame.png`
- `RetroPie` → `retropie.png`
- `RetroBat` → `retrobat.png`

## Logo Specifications
- **Size**: 128x128px or larger (will be displayed at 32x32px)
- **Format**: PNG with transparency
- **Style**: Simple, recognizable, works on light backgrounds

## Adding Logos
To add official or custom logos:

1. Obtain the official logo (check project websites/GitHub)
2. Ensure it's 128x128px or larger PNG with transparency
3. Save as `clientname.png` in `app/static/logos/clients/`
4. Refresh your browser to see the changes

## Resources for Official Logos
- **MiSTer**: https://github.com/MiSTer-devel (check org avatar)
- **MAME**: https://www.mamedev.org/
- **RetroPie**: https://retropie.org.uk/
- **RetroBat**: https://www.retrobat.org/

## CSS Styling
Client logos use the `.client-logo` class defined in `app/static/style.css`:
```css
.client-logo {
    width: 32px;
    height: 32px;
    object-fit: contain;
    border-radius: 4px;
    background: transparent;
    vertical-align: middle;
    margin-right: 0.5em;
}
```
