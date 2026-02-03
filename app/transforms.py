"""
Transform System: On-the-fly file format conversion and processing.

This module provides the core infrastructure for transforming files as they're
read through the FUSE filesystem. Transforms can be chained to create pipelines.
"""
# pyright: reportUnnecessaryTypeIgnoreComment=false

import os
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import BinaryIO

logger = logging.getLogger(__name__)


# ============================================================================
# Core Transform Classes
# ============================================================================

class TransformError(Exception):
    """Base exception for transform errors."""
    ...  # noqa: PIE790  # Ellipsis is idiomatic for empty exception classes


class TransformNotSupportedError(TransformError):
    """Transform not available for this file type."""
    ...  # noqa: PIE790


class TransformCorruptDataError(TransformError):
    """Source file corrupted or invalid format."""
    ...  # noqa: PIE790


@dataclass
class Transform(ABC):
    """
    Base class for all file transformations.

    Transforms must be stateless and thread-safe, as the same instance
    may be used for multiple concurrent read operations.
    """

    @abstractmethod
    def get_output_size(self, input_size: int) -> int:
        """
        Calculate output size from input size.

        Returns:
            Output size in bytes, or -1 if size cannot be determined
            without reading the file (e.g., compressed files).
        """
        ...  # noqa: PIE790  # Ellipsis is standard for abstract methods

    @abstractmethod
    def transform_read(self, source_file: BinaryIO, virtual_offset: int,
                      length: int) -> bytes:
        """
        Transform a read operation.

        Args:
            source_file: Open file handle to source file (seekable)
            virtual_offset: Offset in the virtual/transformed file
            length: Number of bytes requested

        Returns:
            Transformed data bytes (may be shorter than requested at EOF)
        """
        ...  # noqa: PIE790

    @abstractmethod
    def get_source_offset(self, virtual_offset: int) -> int:
        """
        Map virtual file offset to source file offset.

        For simple transforms (like strip_header), this is straightforward.
        For complex transforms (compression), return the offset for sequential reads.

        Args:
            virtual_offset: Offset in virtual/transformed file

        Returns:
            Corresponding offset in source file
        """
        ...  # noqa: PIE790

    def can_random_access(self) -> bool:
        """
        Whether random access (seeking) is supported efficiently.

        Returns:
            True for simple offset transforms, False for compression/archives
            that require sequential processing.
        """
        return True

    def metadata(self) -> dict:
        """
        Return transform metadata for logging/debugging.

        Returns:
            Dictionary with transform details
        """
        return {"type": self.__class__.__name__}

    def __str__(self) -> str:
        """String representation for logging."""
        meta = self.metadata()
        return f"{meta['type']}({', '.join(f'{k}={v}' for k, v in meta.items() if k != 'type')})"


@dataclass
class TransformPipeline:
    """
    Chain of transforms applied to a source file.

    Example:
        source.2mg.zip -> [ZipExtractTransform, StripHeaderTransform] -> HDV
    """
    source_path: str
    stages: list[Transform] = field(default_factory=list)

    def is_passthrough(self) -> bool:
        """True if no transforms (optimization check)."""
        return len(self.stages) == 0

    def get_output_size(self, input_size: int) -> int:
        """
        Calculate final output size through all stages.

        Args:
            input_size: Size of the original source file

        Returns:
            Final output size, or -1 if unknown
        """
        size = input_size
        for transform in self.stages:
            size = transform.get_output_size(size)
            if size < 0:  # Unknown size from this transform
                return -1
        return size

    def apply_transforms(self, source_file: BinaryIO, virtual_offset: int,
                        length: int) -> bytes:
        """
        Apply all transforms in sequence.

        Args:
            source_file: Open handle to source file
            virtual_offset: Offset in final transformed view
            length: Bytes to read

        Returns:
            Transformed data
        """
        if self.is_passthrough():
            # Optimization: no transforms needed
            source_file.seek(virtual_offset)
            return source_file.read(length)

        # For now, simple sequential application
        # NOTE: Could optimize for specific transform combinations
        data: bytes = b""
        offset = virtual_offset

        for i, transform in enumerate(self.stages):
            if i == 0:
                # First stage reads from source
                data = transform.transform_read(source_file, offset, length)
            else:
                # Subsequent stages transform previous output
                # This requires wrapping data in a file-like object
                from io import BytesIO
                temp_file = BytesIO(data)
                data = transform.transform_read(temp_file, 0, len(data))

        return data

    def can_random_access(self) -> bool:
        """True if all stages support random access."""
        return all(stage.can_random_access() for stage in self.stages)

    def __str__(self) -> str:
        """String representation for logging."""
        if self.is_passthrough():
            return f"Pipeline[{self.source_path}] (passthrough)"
        stages_str = " -> ".join(str(stage) for stage in self.stages)
        return f"Pipeline[{self.source_path}] {stages_str}"


# ============================================================================
# Concrete Transform Implementations
# ============================================================================

@dataclass
class StripHeaderTransform(Transform):
    """
    Remove N bytes from the start of a file.

    Common use case: 2MG disk images have a 64-byte header that must be
    removed to create HDV format for MiSTer.

    Example:
        StripHeaderTransform(bytes=64)  # Strip 64 bytes from start
    """
    bytes_to_strip: int

    def __post_init__(self):
        if self.bytes_to_strip < 0:
            raise ValueError("bytes_to_strip must be non-negative")

    def get_output_size(self, input_size: int) -> int:
        """Output is input_size - bytes_to_strip (minimum 0)."""
        return max(0, input_size - self.bytes_to_strip)

    def get_source_offset(self, virtual_offset: int) -> int:
        """Virtual offset maps to source offset + bytes_to_strip."""
        return virtual_offset + self.bytes_to_strip

    def transform_read(self, source_file: BinaryIO, virtual_offset: int,
                      length: int) -> bytes:
        """Read from source at offset + bytes_to_strip."""
        source_offset = self.get_source_offset(virtual_offset)
        source_file.seek(source_offset)
        return source_file.read(length)

    def can_random_access(self) -> bool:
        """Strip header supports random access (just an offset)."""
        return True

    def metadata(self) -> dict:
        return {
            "type": "StripHeader",
            "bytes": self.bytes_to_strip
        }


@dataclass
class StripFooterTransform(Transform):
    """
    Remove N bytes from the end of a file.

    Example:
        StripFooterTransform(bytes=128)  # Strip 128 bytes from end
    """
    bytes_to_strip: int

    def __post_init__(self):
        if self.bytes_to_strip < 0:
            raise ValueError("bytes_to_strip must be non-negative")

    def get_output_size(self, input_size: int) -> int:
        """Output is input_size - bytes_to_strip (minimum 0)."""
        return max(0, input_size - self.bytes_to_strip)

    def get_source_offset(self, virtual_offset: int) -> int:
        """Virtual offset maps directly to source offset."""
        return virtual_offset

    def transform_read(self, source_file: BinaryIO, virtual_offset: int,
                      length: int) -> bytes:
        """
        Read from source, but limit to effective file size.

        If read would extend into stripped footer region, truncate.
        """
        # Get source file size
        source_file.seek(0, os.SEEK_END)
        source_size = source_file.tell()

        # Calculate effective size (without footer)
        effective_size = self.get_output_size(source_size)

        # Limit read to not exceed effective size
        if virtual_offset >= effective_size:
            return b''  # Reading past end

        max_readable = effective_size - virtual_offset
        actual_length = min(length, max_readable)

        # Read from source
        source_file.seek(virtual_offset)
        return source_file.read(actual_length)

    def can_random_access(self) -> bool:
        """Strip footer supports random access."""
        return True

    def metadata(self) -> dict:
        return {
            "type": "StripFooter",
            "bytes": self.bytes_to_strip
        }


@dataclass
class PadHeaderTransform(Transform):
    """
    Add N bytes of padding to the start of a file.

    Useful for format conversions that require a different header size.

    Example:
        PadHeaderTransform(bytes=64, fill=0x00)  # Pad 64 null bytes
    """
    bytes_to_pad: int
    fill_byte: int = 0x00

    def __post_init__(self):
        if self.bytes_to_pad < 0:
            raise ValueError("bytes_to_pad must be non-negative")
        if not 0 <= self.fill_byte <= 255:
            raise ValueError("fill_byte must be 0-255")

    def get_output_size(self, input_size: int) -> int:
        """Output is input_size + bytes_to_pad."""
        return input_size + self.bytes_to_pad

    def get_source_offset(self, virtual_offset: int) -> int:
        """
        Map virtual offset to source offset.

        First bytes_to_pad bytes are synthetic, rest map to source.
        """
        if virtual_offset < self.bytes_to_pad:
            return 0  # Still in padded region
        return virtual_offset - self.bytes_to_pad

    def transform_read(self, source_file: BinaryIO, virtual_offset: int,
                      length: int) -> bytes:
        """
        Read, synthesizing padding bytes if in header region.
        """
        result = bytearray()

        # If reading starts in padded region
        if virtual_offset < self.bytes_to_pad:
            pad_bytes_to_read = min(length, self.bytes_to_pad - virtual_offset)
            result.extend([self.fill_byte] * pad_bytes_to_read)
            length -= pad_bytes_to_read
            virtual_offset += pad_bytes_to_read

        # Read remainder from source
        if length > 0 and virtual_offset >= self.bytes_to_pad:
            source_offset = virtual_offset - self.bytes_to_pad
            source_file.seek(source_offset)
            result.extend(source_file.read(length))

        return bytes(result)

    def can_random_access(self) -> bool:
        """Pad header supports random access."""
        return True

    def metadata(self) -> dict:
        return {
            "type": "PadHeader",
            "bytes": self.bytes_to_pad,
            "fill": f"0x{self.fill_byte:02x}"
        }


# ============================================================================
# Transform Registry and Builder
# ============================================================================

# Registry of available transform types
TRANSFORM_REGISTRY = {
    'strip_header': StripHeaderTransform,
    'strip_footer': StripFooterTransform,
    'pad_header': PadHeaderTransform,
    # More transforms added as implemented:
    # 'extract_zip': ZipExtractTransform,
    # 'decompress_gzip': GzipDecompressTransform,
    # etc.
}

# Common transform shortcuts for config convenience
TRANSFORM_SHORTCUTS = {
    'strip_header_64': {'type': 'strip_header', 'bytes': 64},
    'strip_header_128': {'type': 'strip_header', 'bytes': 128},
    'strip_footer_64': {'type': 'strip_footer', 'bytes': 64},
    'pad_header_64': {'type': 'pad_header', 'bytes': 64},
}


def build_transform(spec: dict | str) -> Transform:
    """
    Build a transform from a configuration specification.

    Args:
        spec: Transform specification, either:
            - String shortcut: "strip_header_64"
            - Dict with 'type' and parameters: {"type": "strip_header", "bytes": 64}

    Returns:
        Configured Transform instance

    Raises:
        TransformNotSupportedError: If transform type is unknown
        ValueError: If transform parameters are invalid
    """
    # Handle string shortcuts
    if isinstance(spec, str):
        if spec in TRANSFORM_SHORTCUTS:
            spec = TRANSFORM_SHORTCUTS[spec]
        else:
            raise TransformNotSupportedError(f"Unknown transform shortcut: {spec}")

    # Extract transform type
    transform_type = spec.get('type')
    if not isinstance(transform_type, str) or not transform_type:
        raise ValueError("Transform spec must include 'type' field as a string")

    # Look up transform class
    transform_class = TRANSFORM_REGISTRY.get(transform_type)
    if not transform_class:
        raise TransformNotSupportedError(
            f"Unknown transform type: {transform_type}. "
            f"Available: {', '.join(TRANSFORM_REGISTRY.keys())}"
        )

    # Build transform with parameters
    try:
        # Remove 'type' from params
        params = {k: v for k, v in spec.items() if k != 'type'}

        # Map common param names
        if 'bytes' in params and 'bytes_to_strip' not in params:
            params['bytes_to_strip'] = params.pop('bytes')
        if 'bytes' in params and 'bytes_to_pad' not in params:
            params['bytes_to_pad'] = params.pop('bytes')
        if 'fill' in params and 'fill_byte' not in params:
            params['fill_byte'] = params.pop('fill')

        return transform_class(**params)
    except TypeError as e:
        raise ValueError(f"Invalid parameters for {transform_type}: {e}") from e


def build_transform_pipeline(source_path: str,
                            transform_specs: list[dict | str]) -> TransformPipeline:
    """
    Build a transform pipeline from configuration specifications.

    Args:
        source_path: Path to source file
        transform_specs: List of transform specifications

    Returns:
        Configured TransformPipeline

    Example:
        build_transform_pipeline(
            "/path/to/file.2mg.zip",
            [
                {"type": "extract_zip"},
                {"type": "strip_header", "bytes": 64}
            ]
        )
    """
    stages = []
    for spec in transform_specs:
        transform = build_transform(spec)
        stages.append(transform)

    pipeline = TransformPipeline(source_path=source_path, stages=stages)
    logger.debug("Built transform pipeline: %s", pipeline)
    return pipeline


# ============================================================================
# Utility Functions
# ============================================================================


def estimate_transform_cost(pipeline: TransformPipeline, file_size: int) -> float:
    """
    Estimate computational cost of applying a transform pipeline.

    Returns a relative cost metric (higher = more expensive).
    Useful for deciding whether to cache transformed results.

    Args:
        pipeline: Transform pipeline to estimate
        file_size: Size of input file in bytes

    Returns:
        Cost estimate (0.0 = free, 1.0 = cheap, 10.0+ = expensive)
    """
    if pipeline.is_passthrough():
        return 0.0

    cost = 0.0
    for stage in pipeline.stages:
        if not stage.can_random_access():
            # Sequential processing more expensive
            cost += 5.0
        else:
            # Simple offset transforms are cheap
            cost += 0.1

    # Large files increase cost
    if file_size > 100 * 1024 * 1024:  # > 100MB
        cost *= 2.0

    return cost


def should_cache_transform(pipeline: TransformPipeline, file_size: int) -> bool:
    """
    Determine if a transform result should be cached.

    Based on computational cost and file size.

    Args:
        pipeline: Transform pipeline
        file_size: Input file size

    Returns:
        True if caching recommended
    """
    if pipeline.is_passthrough():
        return False

    cost = estimate_transform_cost(pipeline, file_size)

    # Cache expensive transforms on small-to-medium files
    if cost > 5.0 and file_size < 50 * 1024 * 1024:  # < 50MB
        return True

    return False
