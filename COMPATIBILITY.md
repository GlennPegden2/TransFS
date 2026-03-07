# System Compatibility

This table tracks which systems are supported on which emulator platforms, along with the file formats available.

| System             | MiSTer | Mame | RetroPie | RetroBat | Zaparoo Launch | Notes |
|--------------------|--------|------|----------|----------|-------|
| Acorn Archimedes   | ✅ ADF, HDF |   |          |          | ❌        | Mister: HDs require CMOS config to boot; real-world validation reconfirmed March 2026 |
| Acorn Atom         | ✅ VHD      | ✅ UEF, DSK  |          | ✅ UEF, DSK          | ✅         | Shift F10 to autoload |
| Acorn BBC Micro    | ✅ VHD, MMB |   |          |          | ✅         |       |
| Acorn Electron     | ✅ VHD, MMB, UEF | |      |          | ✅         |       |
| Amstrad CPC        | ✅ DSK, CTD, Exx, ROM      |   |          |          | ✅         | MiSTer takes ages to boot, partly because it looks for 255 files tht normally won't exist |
| Amstrad PCW        | ✅ DSK      |   |          |          |       | ✅         |
| Apple I           |            |   |          |          |       |          |
| Apple II           |  ✅ DSK, PO, DO, HDV, 2MG (via transform to HDV)          |   |          |          |  ✅ (except HDVs)     | Self boot HDVs need a soft reset to boot. Many images don't seem to work for some reasons         |
| Atari 2600         |            |   |          |          |       |          |
| Atari 5200         | ✅ (core validation) |   |          |          |       | Real-world MiSTer core validation completed March 2026 |
| Atari 7800         |            |   |          |          |       |          |
| Atari 800          |            |   |          |          |       |          |
| Atari Lynx         |            |   |          |          |       |          |
| ColecoVision       |            |   |          |          |       |          |
| Commoder Amiga     |            |   |          |          |       |          |
| Commodore 128      |            |   |          |          |       |          |
| Commodore 64       |            |   |          |          |       |          |
| Commodore PET      |            |   |          |          |       |          |
| Commodore Plus4    |            |   |          |          |       |          |
| Vectrex            |            |   |          |          |       |          |
| Intellivision      |            |   |          |          |       |          |
| MSX                |            |   |          |          |       |          |
| Altair 8800        |            |   |          |          |       |          |
| PC-Engine          |            |   |          |          |       |          |
| TurboGrafx 16      |            |   |          |          |       |          |
| GameBoy            |            |   |          |          |       |          |
| GameBoy Advance    |            |   |          |          |       |          |
| GameBoy Color      |            |   |          |          |       |          |
| NES                |            |   |          |          |       |          |
| SNES               |            |   |          |          |       |          |
| SegaGameGear       |            |   |          |          |       |          |
| SegaGenesis        |            |   |          |          |       |          |
| SegaMasterSystem   |            |   |          |          |       |          |
| ZX Spectrum        |            |   |          |          |       |          |
| NeoGeo             |            |   |          |          |       |          |
| AliceMC10          |            |   |          |          |       |          |

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
