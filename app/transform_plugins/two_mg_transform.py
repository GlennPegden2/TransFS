"""2MG (2IMG) disk image transform plugin."""

import os
import logging
import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Optional

from transforms import Transform

logger = logging.getLogger(__name__)


@dataclass
class TwoMGTransform(Transform):
    """
    Extract the data payload from a 2MG (2IMG) disk image.

    Uses the 2MG header to determine the data offset and length. Falls back
    to a 64-byte header with block-aligned sizing when header fields are
    unavailable or invalid.

    Auto-detects DOS 3.3 vs ProDOS sector order and sets output_extension accordingly.
    """
    default_header_size: int = 64
    block_size: int = 512
    _data_offset: Optional[int] = field(default=None, init=False, repr=False)
    _data_length: Optional[int] = field(default=None, init=False, repr=False)
    _detected_format: Optional[str] = field(default=None, init=False, repr=False)

    def _detect_format(self, source_file: BinaryIO, data_offset: int) -> str:
        """
        Detect output format from 2MG file.
        Returns 'hdv' for hard disk images (>200KB), 'do'/'po' for floppies.

        Apple II floppy disks are 140KB (35 tracks × 16 sectors × 256 bytes).
        Larger images (800KB, etc.) are HDV hard disk images.
        """
        try:
            source_file.seek(0, os.SEEK_END)
            file_size = source_file.tell()

            # Calculate data size (file minus header)
            data_size = file_size - data_offset

            # If larger than 200KB, it's a hard disk image (HDV)
            if data_size > 200 * 1024:
                logger.info("TwoMGTransform._detect_format: %s bytes = HDV hard disk image", data_size)
                return "hdv"

            # For floppy disks (140KB), check format byte for sector ordering
            source_file.seek(0)
            header = source_file.read(64)
            if len(header) >= 64 and header[:4] == b"2IMG":
                format_byte = struct.unpack("<I", header[16:20])[0]

                # For floppies: format byte indicates sector order
                # 0 = DOS 3.3, 1 = ProDOS
                if format_byte == 0:
                    logger.info("TwoMGTransform._detect_format: 140KB floppy, DOS 3.3 format")
                    return "do"
                logger.info("TwoMGTransform._detect_format: 140KB floppy, ProDOS format")
                return "po"
        except Exception as e:
            logger.warning("TwoMGTransform._detect_format: failed to read header: %s", e)

        # Default to HDV for large files, po for small
        logger.info("TwoMGTransform._detect_format: defaulting based on size")
        return "hdv"

    def _parse_header(self, source_file: BinaryIO, source_size: int) -> tuple[int, int, int]:
        """Return (header_size, data_offset, data_length) from 2MG header."""
        source_file.seek(0)
        header = source_file.read(self.default_header_size)
        header_size = self.default_header_size
        data_offset = self.default_header_size
        data_length = max(0, source_size - data_offset)

        if len(header) >= self.default_header_size and header[:4] == b"2IMG":
            try:
                # Parse 2MG header according to spec:
                # Offset 8-9: Header size (16-bit)
                # Offset 28-31: Data offset (32-bit) - 0 means use header size
                # Offset 32-35: Data length (32-bit) - 0 means calculate from file size
                hdr_size = struct.unpack("<H", header[8:10])[0]
                data_off = struct.unpack("<I", header[28:32])[0]
                data_len = struct.unpack("<I", header[32:36])[0]

                header_size = hdr_size if hdr_size > 0 else header_size
                # Validate data_offset is within file bounds, otherwise use header_size
                data_offset = data_off if (data_off > 0 and data_off < source_size) else header_size
                data_length = data_len if data_len > 0 else max(0, source_size - data_offset)
            except struct.error:
                pass

        # Clamp to file bounds
        if data_offset < 0 or data_offset > source_size:
            data_offset = self.default_header_size
        max_length = max(0, source_size - data_offset)
        if data_length <= 0 or data_length > max_length:
            data_length = max_length

        return header_size, data_offset, data_length

    def _get_effective_length(self, input_size: int) -> int:
        """Fallback output size when header fields are unknown."""
        if input_size <= self.default_header_size:
            return 0
        data_length = input_size - self.default_header_size
        if self.block_size > 0:
            data_length = (data_length // self.block_size) * self.block_size
        return max(0, data_length)

    def get_output_size(self, input_size: int) -> int:
        if self._data_length is not None:
            return self._data_length
        return self._get_effective_length(input_size)

    def detect_format_from_file(self, source_path: str) -> None:
        """
        Detect format by opening and reading the file.
        Called once during pipeline initialization to set _detected_format.
        """
        if self._detected_format is not None:
            return  # Already detected

        try:
            logger.info("TwoMGTransform.detect_format_from_file: detecting format for %s", source_path)
            with open(source_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                source_size = f.tell()
                _, data_offset, _ = self._parse_header(f, source_size)
                self._detected_format = self._detect_format(f, data_offset)
                logger.info("TwoMGTransform.detect_format_from_file: detected format=%s", self._detected_format)
        except Exception as e:
            logger.warning("Failed to detect format for %s: %s", source_path, e)
            # Default to 'hdv' (hard disk) when detection fails
            self._detected_format = "hdv"

    def get_output_extension(self) -> Optional[str]:
        """Return the detected output extension (do or po), if detected."""
        return self._detected_format

    def get_source_offset(self, virtual_offset: int) -> int:
        data_offset = self._data_offset if self._data_offset is not None else self.default_header_size
        return virtual_offset + data_offset

    def transform_read(self, source_file: BinaryIO, virtual_offset: int, length: int) -> bytes:
        source_file.seek(0, os.SEEK_END)
        source_size = source_file.tell()

        _, data_offset, data_length = self._parse_header(source_file, source_size)
        self._data_offset = data_offset
        self._data_length = data_length

        # Detect format on first read if not already done
        if self._detected_format is None:
            self._detected_format = self._detect_format(source_file, data_offset)
            logger.info("TwoMGTransform: auto-detected format=%s on first read", self._detected_format)

        if virtual_offset >= data_length:
            return b""

        max_readable = data_length - virtual_offset
        actual_length = min(length, max_readable)

        source_file.seek(data_offset + virtual_offset)
        return source_file.read(actual_length)

    def can_random_access(self) -> bool:
        return True

    def metadata(self) -> dict:
        meta = {"type": "TwoMG", "header": self.default_header_size}
        if self._data_offset is not None:
            meta["offset"] = self._data_offset
        if self._data_length is not None:
            meta["length"] = self._data_length
        if self._detected_format is not None:
            meta["format"] = self._detected_format
        return meta


TRANSFORM_PLUGINS = {
    "two_mg": TwoMGTransform,
}
