from transfs import TransFS

def test_filetype_map_simple():
    fs = TransFS("/tmp")
    mapping, reverse = fs._parse_filetype_map({"Tape": "UEF"})
    assert mapping == {"TAPE": ["UEF"]}
    assert reverse == {}

def test_filetype_map_colon():
    fs = TransFS("/tmp")
    mapping, reverse = fs._parse_filetype_map({"ROM": "BIN:ROM, HEX:ROM"})
    assert mapping == {"ROM": ["BIN", "HEX"]}
    assert reverse == {"BIN": "ROM", "HEX": "ROM"}