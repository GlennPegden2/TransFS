"""Example transform plugin.

Copy this file, rename it, and adjust the transform class to add new formats.
"""

from dataclasses import dataclass
from typing import BinaryIO

from transforms import Transform


@dataclass
class ExampleStripFirstByteTransform(Transform):
    """Example transform that strips the first byte from a file."""

    def get_output_size(self, input_size: int) -> int:
        return max(0, input_size - 1)

    def get_source_offset(self, virtual_offset: int) -> int:
        return virtual_offset + 1

    def transform_read(self, source_file: BinaryIO, virtual_offset: int, length: int) -> bytes:
        source_file.seek(self.get_source_offset(virtual_offset))
        return source_file.read(length)


TRANSFORM_PLUGINS = {
    "example_strip_first_byte": ExampleStripFirstByteTransform,
}
