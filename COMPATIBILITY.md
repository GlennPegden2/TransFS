# System Compatibility

This table tracks which systems are supported on which emulator platforms, along with the file formats available.

| System             | MiSTer | Mame | RetroPie | RetroBat | Notes |
|--------------------|--------|------|----------|----------|-------|
| Acorn Archimedes   | ✅ ADF, HDF |   |          |          |       |
| Acorn Atom         | ✅ VHD      |   |          |          | Shift F10 launches the StarDot collection |
| Acorn BBC Micro    | ✅ VHD, MMB |   |          |          |       |
| Acorn Electron     | ✅ VHD, MMB, UEF | |      |          |       |
| Amstrad CPC        | ❌ DSK,       |   |          |          | Takes ages to boot, broken when it does. There is something weird going on as I can see CDT / DSK files mounted at the command line, but not visible in the file browers |
| Amstrad PCW        | ✅ DSK      |   |          |          |       |
| Apple II           |            |   |          |          |       |
| Atari 2600         |            |   |          |          |       |
| Atari 5200         |            |   |          |          |       |
| Atari 7800         |            |   |          |          |       |
| Atari 800          |            |   |          |          |       |
| Atari Lynx         |            |   |          |          |       |
| ColecoVision       |            |   |          |          |       |
| Commoder Amiga     |            |   |          |          |       |
| Commodore 128      |            |   |          |          |       |
| Commodore 64       |            |   |          |          |       |
| Commodore PET      |            |   |          |          |       |
| Commodore Plus4    |            |   |          |          |       |
| Vectrex            |            |   |          |          |       |
| Intellivision      |            |   |          |          |       |
| MSX                |            |   |          |          |       |
| Altair 8800        |            |   |          |          |       |
| PC-Engine          |            |   |          |          |       |
| TurboGrafx 16      |            |   |          |          |       |
| GameBoy            |            |   |          |          |       |
| GameBoy Advance    |            |   |          |          |       |
| GameBoy Color      |            |   |          |          |       |
| NES                |            |   |          |          |       |
| SNES               |            |   |          |          |       |
| SegaGameGear       |            |   |          |          |       |
| SegaGenesis        |            |   |          |          |       |
| SegaMasterSystem   |            |   |          |          |       |
| ZX Spectrum        |            |   |          |          |       |
| NeoGeo             |            |   |          |          |       |
| AliceMC10          |            |   |          |          |       |

## Adding New Systems

To add support for a new system:
1. Add configuration in `app/config/systems/`
2. Create build scripts if needed in `app/build_scripts/`
3. Update this compatibility table
4. Test with the target emulator platform

## Status Indicators

- ✅ - Tested and working
- ❌ - Known issues
- Empty - Not yet implemented
