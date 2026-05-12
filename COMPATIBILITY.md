# System Compatibility

This table tracks which systems are supported on which emulator platforms, along with the file formats available.

| Manufacturer       | System             | MiSTer | Mame | RetroPie | RetroBat | Zaparoo Launch | Notes |
|--------------------|--------------------|--------|------|----------|----------|----------------|-------|
| 3DO Company        | 3DO                | ✅ BIN, CUE, CHD, ISO, ROM    | ❓ (See 1)   |        | ✅ BIN, CUE           | ✅ (See 2)     |  1. Untested as core seemingly doesn't yet have working CD detection, but should work for BIN/CUE, CHD and ISO once it does. 2. Only CUE and ISO          |
| Acetronic          | MPU-1000           | ❓ BIN (See 1)  |  | | | | 1. MiSTer - Listed as Emerson Arcadia 2001. Core seems broken right now.
| Aamber             | Pegasus
| Acorn              | Archimedes         | ✅ ADF, HDF       |        |           |          |❌              | Mister: See notes on how to configure HDs on the archie, they wont boot without cmos config      |
| Acorn              | Atom         | ✅ VHD      | ✅ UEF, DSK  |          | ✅ UEF, DSK          | ✅         | Shift F10 to autoload |
| Acorn              | BBC Master    | ✅ VHD, MMB |   |          |          | ✅         |       |
| Acorn              | BBC Micro A   | ✅ VHD, MMB |   |          |          | ✅         |       |
| Acorn              | BBC Micro B   | ✅ VHD, MMB |   |          |          | ✅         |       |
| Acorn              | Electron     | ✅ VHD, MMB, UEF | |      |          | ✅         |       |
| Adobe              | Flash
| Amazon             | Amazon Prime Gaming
| Amstrad            | CPC        | ✅ DSK, CTD, Exx, ROM      |   |          |          | ✅         | MiSTer takes ages to boot, partly because it looks for 255 files that normally won't exist |
| Amstrad            | GX4000
| Amstrad            | PCW        | ✅ DSK      |   |          |          |       | ✅         |
| APF                | M1000
| Apogee             | BK-0
| Apple              | Apple I            |            |   |          |          |       |          |
| Apple              | Apple II           |  ✅ DSK, PO, DO, HDV, 2MG (via transform to HDV)          |   |          |          |  ✅ (except HDVs)     | Self boot HDVs need a soft reset to boot. Many images don't seem to work for some reason         || 
| Apple              | Apple IIe          |  ✅ DSK, PO, DO, HDV, 2MG (via transform to HDV)          |   |          |          |  ✅ (except HDVs)     | Self boot HDVs need a soft reset to boot. Many images don't seem to work for some reason         || 
| Apple              | Apple IIGS          |  ✅ DSK, PO, DO, HDV, 2MG (via transform to HDV)          |   |          |          |  ✅ (except HDVs)     | Self boot HDVs need a soft reset to boot. Many images don't seem to work for some reason         || 
| Apple              | Macintosh Plus
| Atari              | 130XE          |   |          |          |       |          |
| Atari              | 65XE          |   |          |          |       |          |
| Atari              | 800          |   |          |          |       |          |
| Atari              | 800XL          |   |          |          |       |          |
| Atari              | 2600          |   |          |          |       |          |
| Atari              | 5200           |   |          |          |       |          |
| Atari              | 7800           |   |          |          |       |          |
| Atari              | Jaguar           |   |          |          |       |          |
| Atari              | Jaguar CD          |   |          |          |       |          |
| Atari              | Lynx            |   |          |          |       |          |
| Atari              | ST            |   |          |          |       |          |
| Atari              | STe            |   |          |          |       |          |
| Atari              | XE            |   |          |          |       |          |
| Atmel              | Uzebox
| Bally              | Astrocade 
| Bandai             | RX-78
| Bandai             | SuFami Turbo
| Bandai             | Super Vision 8000
| Bandai             | SwanCrystal
| Bandai             | WonderSwan
| Bandai             | WonderSwan Color
| BBC Enterprises    | BBC Bridge Companion
| Bit Corp           | Gamate
| Camputers          | Lynx
| Casio              | Loop
| Casio              | PV-1000
| Casio              | PV-2000
| CAVE               | CAVE
| Coleco             | Adam
| Coleco             | ColecoVision
| Coleco             | Telstar
| Commodore          | 64
| Commodore          | 128
| Commodore          | C16
| Commodore          | Amiga 500
| Commodore          | Amiga 600
| Commodore          | Amiga 1200
| Commodore          | Amiga 4000
| Commodore          | Amiga AGA
| Commodore          | Amiga CD32
| Commodore          | Amiga CDTV
| Commodore          | Amiga OCS / ECS
| Commodore          | Game System
| Commodore          | PET
| Commodore          | PET 2001
| Commodore          | Plus/4
| Commodore          | Vic-20
| Compukit           | Homelab
| Creatonic          | Mega Duck
| DEC                | PDP-1
| Dick Smith         | System 80 MK I
| Dick Smith         | System 80 MK II
| Dick Smith         | Wizzard
| Donat Temirazov, Alexander Sokolov | Vector-06C (Вектор-06Ц)
| Dragaon Data       | Dragon 32
| Dragaon Data       | Dragon 64
| Dunhuang Technologies | Suoer A'Can
| EACA               | Colour Genie 
| EACA               | Video Genie
| EACA               | Video Genie I 
| EACA               | Video Genie II
| Elektronika        | BK
| Erik Bryntse       | Super-Chip (Chip-8)
| Emerson            | Arcadia 2001 
| Entex              | Adventure Vision
| Epoch Co           | Game Pocket Computer
| Epoch Co           | Super Cassette Vision
| Eureka Informatique | Oric Stratos
| Eureka Informatique | Oric Telestrat
| Fairchild          | Channel F
| Fantasy Console    | PICO-8 
| Fantasy Console    | TIC-80
| Fantasy Console    | Vircon32
| Fantasy Console    | WASM-4
| Fujitsu            | FM Towns
| Fujitsu            | FM-7
| Fujitsu            | Horizon
| Gaelco             | PowerVR
| Game Park          | Game Park 32
| General Instruments | AY-3-8500 (Pong-on-a-chip)
| GCE / MB           | Vectrex
| Grant Searle       | Compkit UK101
| Grant Searle       | MultiComp
| Hartung            | Game Master
| IBM                | PC/XT
| Interact           | Interact Home Computer
| Interton           | VC4000
| Jupiter            | Ace
| Kevin Bates        | Arduboy
| LeapFrog           | Leapster
| Magnavox           | Odyssey 2
| Mattel             | Aquarius
| Mattel             | Intellivision
| Matra & Hachette   | Ordinateur Alice
| Micro Genius       | Dendy (famiclone)
| Micro Genius       | Pegasus (famiclone)
| Microsoft          | DOS
| Microsoft          | MSX
| Microsoft          | MSX2
| Microsoft          | MSX2+
| Microsoft          | MSX3
| Microsoft          | MSX Plus
| Microsoft          | MSX TurboR 
| Microsoft          | Windows 
| Microsoft          | XBOX
| Microsoft          | XBOX 360
| Microsoft          | XBOX One
| Microsoft          | XBOX Series X
| Miles Gordon Technology  | Sam Coupe
| MITS               | Altair 8800
| Namco              | 246 / 256
| Namco              | 357 / 369
| NEC                | PC 8800
| NEC                | PC 8801 MKII SR
| NEC                | PC 9800
| NEC                | PC Engine  
| NEC                | PC Engine Arcade Card 
| NEC                | PC Engine CD
| NEC                | PC Engine CD-ROM2
| NEC                | PC Engine CoreGrafx
| NEC                | PC Engine Dueo
| NEC                | PC Engine LT
| NEC                | PC Engine Shuttle 
| NEC                | PC Engine Super CD-ROM2
| NEC                | PC Engine SuperGrafx
| NEC                | PC Engine TurboExpress
| NEC                | PC FX
| NEC                | TurboGrafx-16
| Nichibutsu         | My Vision
| Nintendo           | Color TV-Game
| Nintendo           | 3DS
| Nintendo           | DS
| Nintendo           | Famicom Disk System
| Nintendo           | Game & Watch
| Nintendo           | Game Boy
| Nintendo           | Game Boy 2 Players
| Nintendo           | Game Boy Advance
| Nintendo           | Game Boy Advance 2 Players
| Nintendo           | Game Boy Color
| Nintendo           | Game Boy Color 2 Players
| Nintendo           | Game Boy MSU
| Nintendo           | GameCube
| Nintendo           | N64
| Nintendo           | N64 DD
| Nintendo           | Nintendo Entertainment System (NES)
| Nintendo           | NSF Music Player
| Nintendo           | Pokemon Mini
| Nintendo           | SPC Music Player
| Nintendo           | Stellaview
| Nintendo           | Super Game Boy
| Nintendo           | Super Game Boy 2
| Nintendo           | Super Nintentendo Entertainment System (SNES)
| Nintendo           | Super Nintentendo Entertainment System (SNES) - MSU-1
| Nintendo           | Switch 
| Nintendo           | Switch 2
| Nintendo           | Wii
| Nintendo           | Wii U
| Nokia              | N-Gage
| Occitane           | OC2000
| Othello            | Multivision    
| PEL Varaždin       | Orao (Eagle)
| Personal Microcomputers | PMC-80
| Personal Microcomputers | PMC-81
| Philips            | CD-i
| Philips            | Odyssey 2
| Philips            | P2000T
| Philips            | VG5000
| Philips            | Videopac G7000
| Radio              | 86-RK (Радио-86РК)
| Radio Shack        | TRS-80
| Reality Labs       | Quest 2
| Sammy              | Atomiswave
| Sega               | 32X
| Sega               | Chihiro
| Sega               | CD
| Sega               | Dreamcast
| Sega               | Game Gear
| Sega               | Genesis
| Sega               | Master System Mark III
| Sega               | Master System
| Sega               | Mega-CD
| Sega               | Mega Drive
| Sega               | Model 2
| Sega               | Model 3
| Sega               | Mega Drive
| Sega               | Naomi
| Sega               | Naomi 2
| Sega               | Pico
| Sega               | Pico Beena
| Sega               | Saturn
| Sega               | SG-1000
| Sega               | ST-V
| Sega               | Triforce
| Sharp              | MZ
| Sharp              | X1
| Sharp              | X68000
| Sinclair           | QL
| Sinclair           | ZX80
| Sinclair           | ZX81
| Sinclair           | ZX Spectrum
| Sinclair           | ZX Spectrum Next
| SNK                | Neo Geo 
| SNK                | Neo Geo CD
| SNK                | Neo Geo AES / MVS
| SNK                | Neo Geo Pocket
| SNK                | Neo Geo Pocket Color
| Sony               | Playstation
| Sony               | Playstation 2
| Sony               | Playstation 3
| Sony               | Playstation 4
| Sony               | Playstation 5
| Sony               | Playstation Portable
| Sony               | Playstation Vita
| Sord               | M5
| Spectravideo       | SV-328S
| Tangerine          | Oric-1
| Tangerine          | Atmos
| Tandy              | Color Computer (CoCo)
| Tandy              | Color Computer 2 (CoCo2)
| Tandy              | Color Computer 3 (Coco3)
| Tandy              | TRS-80
| Tatung             | Einstein TC01
| Tatung             | Einstein 256
| Tesla              | Ondra SPO-186
| Tesla              | PMD 85
| Texas Instruments  | TI-99/4A
| Thomson            | MO / TO
| Tiger Electronics  | Game.com
| Tomy               | Pyuta
| Tomy               | Pyuta Jr
| Tomy               | TomyTronic Scramble
| Tomy               | Tutor
| University of Cambridge | EDSAC
| Voja Antonić.      | Galaksija
| VTech              | CreatiVision
| VTech              | Laser 310
| VTech              | V.Smile
| VTech              | V.Motion
| Wartara            | SuperVision
| Worlds of Wonder   | Actionmax
| | 486DX33 (No FPU) compatible
| | Specialist (Специалист)
| | TRZ-80 (SA Video Genie / TRS-80 clone)
| | TSConf (ZX-Evolution clone/upgrade)


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
- N/A Not supported by platform
