"""
Samba SMB configuration management.

Sets up Samba users, passwords, and access control based on app.yaml configuration at startup.
This allows credentials and security settings to be managed at the app level without rebuilding the container.
"""

import subprocess
import logging
from pathlib import Path
from typing import Optional
import re

logger = logging.getLogger(__name__)


def get_smb_mode(config: dict) -> str:
    """Return normalized SMB ownership mode.

    Supported values:
    - transfs_managed (default for backward compatibility)
    - retronas_managed
    - disabled
    """
    smb_config = (config or {}).get('smb', {}) or {}
    mode = str(smb_config.get('mode', 'transfs_managed')).strip().lower()
    if mode not in {'transfs_managed', 'retronas_managed', 'disabled'}:
        logger.warning("Unknown smb.mode '%s'; defaulting to transfs_managed", mode)
        return 'transfs_managed'
    return mode


def is_samba_managed_by_transfs(config: dict) -> bool:
    """Return True when TransFS should manage Samba configuration/services."""
    return get_smb_mode(config) == 'transfs_managed'


def configure_samba_user(username: str, password: str) -> bool:
    """
    Configure a Samba user with the given password.
    
    Args:
        username: Samba username to configure
        password: Password for the user
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Use smbpasswd to add/update the user with the password
        # The -s flag reads password from stdin, -a flag adds the user
        process = subprocess.Popen(
            ['smbpasswd', '-s', '-a', username],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=f"{password}\n{password}\n")
        
        if process.returncode == 0:
            logger.info(f"✓ Configured Samba user: {username}")
            return True
        else:
            logger.warning(f"✗ Failed to configure Samba user {username}: {stderr}")
            return False
    except FileNotFoundError:
        logger.error("smbpasswd not found - Samba may not be installed in this environment")
        return False
    except Exception as e:
        logger.error(f"Error configuring Samba user {username}: {e}")
        return False


def update_smb_conf_guest_access(allow_guest: bool) -> bool:
    """
    Update smb.conf to enable or disable guest access.
    
    Args:
        allow_guest: True to allow guest access, False to require authentication
        
    Returns:
        True if successful, False otherwise
    """
    smb_conf_path = Path("/etc/samba/smb.conf")
    
    if not smb_conf_path.exists():
        logger.warning("smb.conf not found at /etc/samba/smb.conf")
        return False
    
    try:
        content = smb_conf_path.read_text()
        
        # Set map to guest setting in [global] section
        if allow_guest:
            # Allow guest access (Bad User maps failed auth to guest)
            content = re.sub(
                r'map to guest\s*=\s*\w+',
                'map to guest = Bad User',
                content
            )
            guest_setting = "guest ok = yes"
            logger.info("✓ Guest access ENABLED")
        else:
            # Reject guest access (Never rejects unauthenticated connections)
            content = re.sub(
                r'map to guest\s*=\s*\w+',
                'map to guest = Never',
                content
            )
            guest_setting = "guest ok = no"
            logger.info("✓ Guest access DISABLED (authentication required)")
        
        # Update guest/auth settings for all managed shares
        managed_shares = ["TransFS", "TransFSNative"]
        for share_name in managed_shares:
            section_marker = f'[{share_name}]'
            if section_marker not in content:
                continue

            # Replace existing or add guest ok setting within this section
            if re.search(rf'(\[{share_name}\][\s\S]*?)guest ok\s*=\s*\w+', content):
                content = re.sub(
                    rf'(\[{share_name}\][\s\S]*?)guest ok\s*=\s*\w+',
                    rf'\1guest ok = {"yes" if allow_guest else "no"}',
                    content
                )
            else:
                content = re.sub(
                    rf'(\[{share_name}\])',
                    rf'\1\nguest ok = {"yes" if allow_guest else "no"}',
                    content
                )

            # When authentication is required, ensure valid users and force user are set
            if not allow_guest:
                section_block_match = re.search(rf'(\[{share_name}\][\s\S]*?)(\n\[[^\]]+\]|\Z)', content)
                if section_block_match:
                    section_block = section_block_match.group(1)
                    if 'valid users' not in section_block:
                        content = re.sub(
                            rf'(\[{share_name}\])',
                            r'\1\nvalid users = root',
                            content
                        )
                    if 'force user' not in section_block:
                        content = re.sub(
                            rf'(\[{share_name}\])',
                            r'\1\nforce user = root',
                            content
                        )

        if not allow_guest:
            logger.info("✓ SMB authentication configured for user 'root'")
        
        smb_conf_path.write_text(content)
        return True
        
    except Exception as e:
        logger.error(f"Error updating smb.conf: {e}")
        return False


def setup_samba_from_config(config: dict) -> bool:
    """
    Set up Samba credentials and access control from app configuration.
    
    Reads smb.username, smb.password, and smb.allow_guest from the app config
    and configures the Samba environment accordingly.
    
    Args:
        config: Application configuration dictionary (from app.yaml)
        
    Returns:
        True if successful, False otherwise
    """
    smb_mode = get_smb_mode(config)
    if smb_mode != 'transfs_managed':
        logger.info("Skipping Samba setup because smb.mode=%s", smb_mode)
        return True

    smb_config = config.get('smb', {})
    username = smb_config.get('username', 'root')
    password = smb_config.get('password', '1')
    allow_guest = smb_config.get('allow_guest', False)
    
    logger.info(f"Setting up Samba user: {username}")
    
    # Update smb.conf guest access setting
    if not update_smb_conf_guest_access(allow_guest):
        logger.warning("Failed to update smb.conf guest access setting")
    
    # Configure the user
    return configure_samba_user(username, password)
