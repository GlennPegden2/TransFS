SELECT DISTINCT 
    SPLIT_PART(
        SUBSTRING(virtual_path FROM 42),
        '/',
        1
    ) AS subdir
FROM files
WHERE virtual_path LIKE '/mnt/transfs/RetroBat/ROMS/AcornAtom/%'
    AND LENGTH(SUBSTRING(virtual_path FROM 42)) > 0
LIMIT 10;
