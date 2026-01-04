"""
Post-processing operations for pack installation.

Provides declarative operations for common tasks like extracting archives,
moving/organizing files, and cleanup - eliminating the need for bash scripts
in most cases.
"""
import glob
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List

import py7zr

class PostProcessor:
    """Handles declarative post-processing operations for downloaded pack content."""
    
    def __init__(self, base_path: str, skip_existing: bool = True):
        """
        Initialize the post processor.
        
        Args:
            base_path: Base directory for all operations
            skip_existing: Skip operations if target files already exist
        """
        self.base_path = Path(base_path)
        self.skip_existing = skip_existing
        self.log_callback = None
        
    def set_log_callback(self, callback):
        """Set a callback function for logging: callback(message: str)"""
        self.log_callback = callback
        
    def log(self, message: str):
        """Log a message via callback or print."""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)
    
    def process(self, operations: List[Dict[str, Any]]) -> bool:
        """
        Execute a list of post-processing operations.
        
        Args:
            operations: List of operation dictionaries
            
        Returns:
            True if all operations succeeded, False otherwise
        """
        for i, operation in enumerate(operations, 1):
            self.log(f"\n[Operation {i}/{len(operations)}]")
            
            try:
                if 'extract' in operation:
                    self._extract(operation['extract'])
                elif 'mkdir' in operation:
                    self._mkdir(operation['mkdir'])
                elif 'move' in operation:
                    self._move(operation['move'])
                elif 'move_by_pattern' in operation:
                    self._move_by_pattern(operation['move_by_pattern'])
                elif 'copy' in operation:
                    self._copy(operation['copy'])
                elif 'rename' in operation:
                    self._rename(operation['rename'])
                elif 'cleanup' in operation:
                    self._cleanup(operation['cleanup'])
                else:
                    self.log(f"⚠ Unknown operation type: {operation}")
                    
            except Exception as e:  # pylint: disable=broad-except
                self.log(f"✗ Operation failed: {str(e)}")
                return False
                
        return True
    
    def _extract(self, config: Dict[str, Any]):
        """
        Extract archive files.
        
        Config:
            files: Glob pattern for files to extract (e.g., "Collections/*.zip")
            dest: Destination directory for extracted content
            formats: Optional list of formats to extract [zip, 7z, tar, tar.gz]
        """
        files_pattern = config.get('files')
        dest = config.get('dest')
        
        if not files_pattern or not dest:
            raise ValueError("extract requires 'files' and 'dest'")
        
        dest_path = self.base_path / dest
        dest_path.mkdir(parents=True, exist_ok=True)
        
        # Find files matching pattern
        pattern_path = self.base_path / files_pattern
        matching_files = glob.glob(str(pattern_path), recursive=True)
        
        if not matching_files:
            self.log(f"⚠ No files found matching: {files_pattern}")
            return
        
        self.log(f"📦 Extracting {len(matching_files)} archive(s) to {dest}")
        
        for archive_path in matching_files:
            archive_name = os.path.basename(archive_path)
            
            # Check if already extracted
            marker_file = dest_path / f".extracted_{archive_name}"
            if self.skip_existing and marker_file.exists():
                self.log(f"   ⏭ Skipping {archive_name} (already extracted)")
                continue
            
            self.log(f"   📦 Extracting: {archive_name}")
            
            try:
                if archive_path.endswith('.zip'):
                    with zipfile.ZipFile(archive_path, 'r') as zf:
                        zf.extractall(dest_path)
                elif archive_path.endswith('.7z'):
                    with py7zr.SevenZipFile(archive_path, 'r') as sz:
                        sz.extractall(dest_path)
                elif archive_path.endswith(('.tar.gz', '.tgz')):
                    with tarfile.open(archive_path, 'r:gz') as tf:
                        tf.extractall(dest_path)
                elif archive_path.endswith('.tar'):
                    with tarfile.open(archive_path, 'r') as tf:
                        tf.extractall(dest_path)
                else:
                    self.log(f"   ⚠ Unsupported archive format: {archive_name}")
                    continue
                
                # Create marker file
                marker_file.touch()
                self.log(f"   ✓ Extracted: {archive_name}")
                
            except Exception as e:
                self.log(f"   ✗ Failed to extract {archive_name}: {str(e)}")
                raise
    
    def _mkdir(self, config: Dict[str, Any]):
        """
        Create directories.
        
        Config:
            paths: List of directory paths to create
        """
        paths = config.get('paths', [])
        if isinstance(paths, str):
            paths = [paths]
        
        self.log(f"📁 Creating {len(paths)} directory(ies)")
        
        for path in paths:
            dir_path = self.base_path / path
            dir_path.mkdir(parents=True, exist_ok=True)
            self.log(f"   ✓ Created: {path}")
    
    def _move(self, config: Dict[str, Any]):
        """
        Move files or directories.
        
        Config:
            from: Source path or glob pattern
            to: Destination path
            flatten: If True, remove directory structure (default: False)
        """
        from_pattern = config.get('from')
        to_path = config.get('to')
        flatten = config.get('flatten', False)
        
        if not from_pattern or not to_path:
            raise ValueError("move requires 'from' and 'to'")
        
        dest = self.base_path / to_path
        dest.mkdir(parents=True, exist_ok=True)
        
        # Handle glob patterns
        source_path = self.base_path / from_pattern
        matching = glob.glob(str(source_path), recursive=True)
        
        if not matching:
            self.log(f"⚠ No files found matching: {from_pattern}")
            return
        
        self.log(f"📁 Moving {len(matching)} item(s) to {to_path}")
        moved_count = 0
        
        for src in matching:
            src_path = Path(src)
            
            if not src_path.exists():
                continue
            
            # Determine destination filename
            if flatten or src_path.is_file():
                dest_file = dest / src_path.name
            else:
                # Preserve directory structure
                rel_path = src_path.relative_to(self.base_path / from_pattern.split('*')[0])
                dest_file = dest / rel_path
            
            # Skip if exists
            if self.skip_existing and dest_file.exists():
                self.log(f"   ⏭ Skipping {src_path.name} (already exists)")
                continue
            
            # Ensure parent directory exists
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Move file/directory
            try:
                shutil.move(str(src_path), str(dest_file))
                moved_count += 1
                self.log(f"   ✓ Moved: {src_path.name}")
            except Exception as e:  # pylint: disable=broad-except
                self.log(f"   ✗ Failed to move {src_path.name}: {str(e)}")
        
        self.log(f"   ✓ Moved {moved_count} item(s)")
    
    def _move_by_pattern(self, config: Dict[str, Any]):
        """
        Move files based on multiple pattern rules.
        
        Config:
            from: Base path to search from
            rules: List of {match: pattern, dest: destination}
            flatten: If True, remove directory structure (default: False)
        """
        from_base = config.get('from')
        rules = config.get('rules', [])
        flatten = config.get('flatten', False)
        
        if not from_base or not rules:
            raise ValueError("move_by_pattern requires 'from' and 'rules'")
        
        self.log(f"📁 Moving files by {len(rules)} pattern rule(s)")
        
        for rule in rules:
            match_pattern = rule.get('match')
            dest_path = rule.get('dest')
            
            if not match_pattern or not dest_path:
                self.log(f"   ⚠ Skipping invalid rule: {rule}")
                continue
            
            # Construct full pattern
            full_pattern = self.base_path / from_base / match_pattern
            matching = glob.glob(str(full_pattern), recursive=True)
            
            if not matching:
                continue
            
            dest = self.base_path / dest_path
            dest.mkdir(parents=True, exist_ok=True)
            
            self.log(f"   📁 Rule: {match_pattern} → {dest_path} ({len(matching)} files)")
            
            for src in matching:
                src_path = Path(src)
                dest_file = dest / src_path.name if flatten else dest / src_path.relative_to(self.base_path / from_base)
                
                if self.skip_existing and dest_file.exists():
                    continue
                
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                
                try:
                    shutil.move(str(src_path), str(dest_file))
                except Exception:  # pylint: disable=broad-except
                    self.log(f"      ✗ Failed: {src_path.name}")
    
    def _copy(self, config: Dict[str, Any]):
        """Copy files (similar to move but preserves source)."""
        from_pattern = config.get('from')
        to_path = config.get('to')
        
        if not from_pattern or not to_path:
            raise ValueError("copy requires 'from' and 'to'")
        
        dest = self.base_path / to_path
        dest.mkdir(parents=True, exist_ok=True)
        
        source_path = self.base_path / from_pattern
        matching = glob.glob(str(source_path), recursive=True)
        
        self.log(f"📋 Copying {len(matching)} item(s) to {to_path}")
        
        for src in matching:
            src_path = Path(src)
            dest_file = dest / src_path.name
            
            if self.skip_existing and dest_file.exists():
                continue
            
            if src_path.is_file():
                shutil.copy2(str(src_path), str(dest_file))
            else:
                shutil.copytree(str(src_path), str(dest_file), dirs_exist_ok=True)
            
            self.log(f"   ✓ Copied: {src_path.name}")
    
    def _rename(self, config: Dict[str, Any]):
        """Rename a file or directory."""
        from_path = config.get('from')
        to_name = config.get('to')
        
        if not from_path or not to_name:
            raise ValueError("rename requires 'from' and 'to'")
        
        src = self.base_path / from_path
        dest = self.base_path / to_name
        
        if not src.exists():
            self.log(f"⚠ Source not found: {from_path}")
            return
        
        if self.skip_existing and dest.exists():
            self.log(f"⏭ Skipping rename (target exists): {to_name}")
            return
        
        src.rename(dest)
        self.log(f"✓ Renamed: {from_path} → {to_name}")
    
    def _cleanup(self, config):
        """
        Remove files or directories.
        
        Config can be:
            - List of paths: ["tmp/", "cache/"]
            - Dict with 'paths': {paths: ["tmp/", "cache/"]}
        """
        if isinstance(config, list):
            paths = config
        elif isinstance(config, dict):
            paths = config.get('paths', [])
        else:
            paths = [config]
        
        self.log(f"🗑️  Cleaning up {len(paths)} path(s)")
        
        for path in paths:
            target = self.base_path / path
            
            if not target.exists():
                continue
            
            try:
                if target.is_file():
                    target.unlink()
                else:
                    shutil.rmtree(target)
                self.log(f"   ✓ Removed: {path}")
            except Exception as e:  # pylint: disable=broad-except
                self.log(f"   ⚠ Failed to remove {path}: {str(e)}")
