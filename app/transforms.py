"""
Transform System: On-the-fly file format conversion and processing.

This module provides the core infrastructure for transforming files as they're
read through the FUSE filesystem. Transforms can be chained to create pipelines.
"""
# pyright: reportUnnecessaryTypeIgnoreComment=false

import os
import logging
import struct
import importlib.util
import inspect
from pathlib import Path
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import BinaryIO, Optional

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
    output_extension: Optional[str] = None  # Optional file extension for output (e.g., 'dsk' for 2MG files)

    def is_passthrough(self) -> bool:
        """True if no transforms (optimization check)."""
        return len(self.stages) == 0
    
    def get_effective_output_extension(self) -> Optional[str]:
        """
        Get the output extension, checking last transform for dynamic extension.
        
        Returns the transform's detected extension if available, otherwise
        falls back to the static output_extension from config.
        """
        # Check if last transform has dynamic extension (e.g., TwoMGTransform)
        if self.stages:
            last_transform = self.stages[-1]
            if hasattr(last_transform, 'get_output_extension'):
                dynamic_ext = last_transform.get_output_extension()
                if dynamic_ext:
                    return dynamic_ext
        
        # Fall back to static extension from config
        return self.output_extension

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
                logger.info(f"TwoMGTransform._detect_format: {data_size} bytes = HDV hard disk image")
                return 'hdv'
            
            # For floppy disks (140KB), check format byte for sector ordering
            source_file.seek(0)
            header = source_file.read(64)
            if len(header) >= 64 and header[:4] == b"2IMG":
                import struct
                format_byte = struct.unpack('<I', header[16:20])[0]
                
                # For floppies: format byte indicates sector order
                # 0 = DOS 3.3, 1 = ProDOS
                if format_byte == 0:
                    logger.info(f"TwoMGTransform._detect_format: 140KB floppy, DOS 3.3 format")
                    return 'do'
                else:
                    logger.info(f"TwoMGTransform._detect_format: 140KB floppy, ProDOS format")
                    return 'po'
        except Exception as e:
            logger.warning(f"TwoMGTransform._detect_format: failed to read header: {e}")
        
        # Default to HDV for large files, po for small
        logger.info(f"TwoMGTransform._detect_format: defaulting based on size")
        return 'hdv'

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
                import struct
                hdr_size = struct.unpack('<H', header[8:10])[0]
                data_off = struct.unpack('<I', header[28:32])[0]
                data_len = struct.unpack('<I', header[32:36])[0]
                
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
            logger.info(f"TwoMGTransform.detect_format_from_file: detecting format for {source_path}")
            with open(source_path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                source_size = f.tell()
                _, data_offset, _ = self._parse_header(f, source_size)
                self._detected_format = self._detect_format(f, data_offset)
                logger.info(f"TwoMGTransform.detect_format_from_file: detected format={self._detected_format}")
        except Exception as e:
            logger.warning(f"Failed to detect format for {source_path}: {e}")
            # Default to 'hdv' (hard disk) when detection fails
            self._detected_format = 'hdv'
    
    def get_output_extension(self) -> Optional[str]:
        """Return the detected output extension (do or po), if detected."""
        return self._detected_format

    def get_source_offset(self, virtual_offset: int) -> int:
        data_offset = self._data_offset if self._data_offset is not None else self.default_header_size
        return virtual_offset + data_offset

    def transform_read(self, source_file: BinaryIO, virtual_offset: int,
                      length: int) -> bytes:
        source_file.seek(0, os.SEEK_END)
        source_size = source_file.tell()

        header_size, data_offset, data_length = self._parse_header(source_file, source_size)
        self._data_offset = data_offset
        self._data_length = data_length
        
        # Detect format on first read if not already done
        if self._detected_format is None:
            self._detected_format = self._detect_format(source_file, data_offset)
            logger.info(f"TwoMGTransform: auto-detected format={self._detected_format} on first read")

        if virtual_offset >= data_length:
            return b''

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

# Built-in transforms shipped with TransFS
BUILTIN_TRANSFORMS = {
    'strip_header': StripHeaderTransform,
    'strip_footer': StripFooterTransform,
    'pad_header': PadHeaderTransform,
    'two_mg': TwoMGTransform,
    # More transforms added as implemented:
    # 'extract_zip': ZipExtractTransform,
    # 'decompress_gzip': GzipDecompressTransform,
    # etc.
}

_PLUGIN_REGISTRY_CACHE: Optional[dict[str, type[Transform]]] = None


def _load_plugin_transforms() -> dict[str, type[Transform]]:
    """
    Load transform plugins from app/transform_plugins.

    Plugin files can expose either:
      - TRANSFORM_PLUGINS = {"name": TransformClass, ...}
      - def register_transforms(registry: dict[str, type[Transform]]) -> None
    """
    plugin_dir = Path(__file__).resolve().parent / "transform_plugins"
    if not plugin_dir.is_dir():
        return {}

    registry: dict[str, type[Transform]] = {}
    for plugin_file in plugin_dir.glob("*.py"):
        if plugin_file.name.startswith("_") or plugin_file.name == "__init__.py":
            continue

        module_name = f"transform_plugins.{plugin_file.stem}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        if not spec or not spec.loader:
            logger.warning("Transform plugin skipped (no loader): %s", plugin_file)
            continue

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logger.warning("Failed to load transform plugin %s: %s", plugin_file, e)
            continue

        plugin_registry: dict[str, type[Transform]] = {}
        if hasattr(module, "register_transforms") and callable(module.register_transforms):
            try:
                module.register_transforms(plugin_registry)
            except Exception as e:
                logger.warning("Plugin register_transforms failed for %s: %s", plugin_file, e)
                continue
        elif hasattr(module, "TRANSFORM_PLUGINS"):
            plugin_registry = getattr(module, "TRANSFORM_PLUGINS")
        else:
            logger.warning("No TRANSFORM_PLUGINS or register_transforms in %s", plugin_file)
            continue

        if not isinstance(plugin_registry, dict):
            logger.warning("Plugin registry must be a dict in %s", plugin_file)
            continue

        for name, cls in plugin_registry.items():
            if not isinstance(name, str) or not name:
                logger.warning("Invalid plugin transform name in %s: %r", plugin_file, name)
                continue
            if not inspect.isclass(cls) or not issubclass(cls, Transform):
                logger.warning("Invalid transform class for '%s' in %s", name, plugin_file)
                continue
            registry[name] = cls

    return registry


def get_transform_registry() -> dict[str, type[Transform]]:
    """Return combined registry of built-in and plugin transforms."""
    global _PLUGIN_REGISTRY_CACHE
    if _PLUGIN_REGISTRY_CACHE is None:
        registry = dict(BUILTIN_TRANSFORMS)
        plugin_transforms = _load_plugin_transforms()
        for name, cls in plugin_transforms.items():
            if name in registry:
                logger.warning("Plugin transform '%s' overrides built-in transform", name)
            registry[name] = cls
        _PLUGIN_REGISTRY_CACHE = registry
    return _PLUGIN_REGISTRY_CACHE

# Common transform shortcuts for config convenience
TRANSFORM_SHORTCUTS = {
    'strip_header_64': {'type': 'strip_header', 'bytes': 64},
    'strip_header_128': {'type': 'strip_header', 'bytes': 128},
    'strip_footer_64': {'type': 'strip_footer', 'bytes': 64},
    'pad_header_64': {'type': 'pad_header', 'bytes': 64},
    'two_mg': {'type': 'two_mg'},
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
    registry = get_transform_registry()
    transform_class = registry.get(transform_type)
    if not transform_class:
        raise TransformNotSupportedError(
            f"Unknown transform type: {transform_type}. "
            f"Available: {', '.join(registry.keys())}"
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
                            transform_specs: list[dict | str] | dict) -> TransformPipeline:
    """
    Build a transform pipeline from configuration specifications.

    Args:
        source_path: Path to source file
        transform_specs: List of transform specifications, each can have optional output_extension field

    Returns:
        Configured TransformPipeline

    Example:
        build_transform_pipeline(
            "/path/to/file.2mg",
            [
                {"type": "strip_header", "bytes": 512, "output_extension": "dsk"}
            ]
        )
    """
    output_extension = None
    stages = []
    
    specs_list = transform_specs if isinstance(transform_specs, list) else [transform_specs]
    
    if isinstance(transform_specs, list):
        logger.debug(f"build_transform_pipeline: processing list of {len(specs_list)} specs")
    else:
        logger.debug(f"build_transform_pipeline: processing dict spec: {transform_specs}")
    
    for spec in specs_list:
        logger.debug(f"build_transform_pipeline: processing spec type={type(spec)}, spec={spec}")
        # Extract output_extension if present
        if isinstance(spec, dict):
            if 'output_extension' in spec:
                output_extension = spec['output_extension']
                logger.info(f"Found output_extension={output_extension} in spec")
            
            # Filter out non-transform fields when building transform
            if 'type' in spec:
                # Create a copy without output_extension
                transform_spec = {k: v for k, v in spec.items() if k != 'output_extension'}
                transform = build_transform(transform_spec)
                stages.append(transform)
        elif isinstance(spec, str):
            transform = build_transform(spec)
            stages.append(transform)

    pipeline = TransformPipeline(source_path=source_path, stages=stages, output_extension=output_extension)
    
    # Trigger eager format detection for TwoMG transforms
    for stage in stages:
        if hasattr(stage, 'detect_format_from_file') and source_path:
            try:
                stage.detect_format_from_file(source_path)
            except Exception as e:
                logger.debug(f"Could not detect format for {source_path}: {e}")
    
    # Log effective extension
    effective_ext = pipeline.get_effective_output_extension()
    if effective_ext:
        logger.info(f"Built transform pipeline with output_extension={effective_ext}: {pipeline}")
    else:
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
