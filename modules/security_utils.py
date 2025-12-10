#!/usr/bin/env python3
"""
Security Utilities for MeshCore Bot
Provides centralized security validation functions to prevent common attacks
"""

import re
import ipaddress
import socket
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
import logging

logger = logging.getLogger('MeshCoreBot.Security')


def validate_external_url(url: str, allow_localhost: bool = False) -> bool:
    """
    Validate that URL points to safe external resource (SSRF protection)
    
    Args:
        url: URL to validate
        allow_localhost: Whether to allow localhost/private IPs (default: False)
    
    Returns:
        True if URL is safe, False otherwise
    
    Raises:
        ValueError: If URL is invalid or unsafe
    """
    try:
        parsed = urlparse(url)
        
        # Only allow HTTP/HTTPS
        if parsed.scheme not in ['http', 'https']:
            logger.warning(f"URL scheme not allowed: {parsed.scheme}")
            return False
        
        # Reject file:// and other dangerous schemes
        if not parsed.netloc:
            logger.warning(f"URL missing network location: {url}")
            return False
        
        # Resolve and check if IP is internal/private
        try:
            ip = socket.gethostbyname(parsed.hostname)
            ip_obj = ipaddress.ip_address(ip)
            
            # If localhost is not allowed, reject private/internal IPs
            if not allow_localhost:
                # Reject private/internal IPs
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                    logger.warning(f"URL resolves to private/internal IP: {ip}")
                    return False
                
                # Reject reserved ranges
                if ip_obj.is_reserved or ip_obj.is_multicast:
                    logger.warning(f"URL resolves to reserved/multicast IP: {ip}")
                    return False
        
        except socket.gaierror as e:
            logger.warning(f"Failed to resolve hostname {parsed.hostname}: {e}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"URL validation failed: {e}")
        return False


def validate_safe_path(file_path: str, base_dir: str = '.', allow_absolute: bool = False) -> Path:
    """
    Validate that path is safe and within base directory (path traversal protection)
    
    Args:
        file_path: Path to validate
        base_dir: Base directory that path must be within (default: current dir)
        allow_absolute: Whether to allow absolute paths outside base_dir
    
    Returns:
        Resolved Path object if safe
    
    Raises:
        ValueError: If path is unsafe or attempts traversal
    """
    try:
        # Resolve absolute paths
        base = Path(base_dir).resolve()
        target = Path(file_path).resolve()
        
        # If absolute paths are not allowed, ensure target is within base
        if not allow_absolute:
            # Check if target is within base directory
            try:
                target.relative_to(base)
            except ValueError:
                raise ValueError(
                    f"Path traversal detected: {file_path} is not within {base_dir}"
                )
        
        # Reject certain dangerous system paths
        dangerous_prefixes = ['/etc', '/sys', '/proc', '/dev', '/bin', '/sbin', '/boot']
        target_str = str(target)
        if any(target_str.startswith(prefix) for prefix in dangerous_prefixes):
            raise ValueError(f"Access to system directory denied: {file_path}")
        
        return target
        
    except Exception as e:
        raise ValueError(f"Invalid or unsafe file path: {file_path} - {e}")


def sanitize_input(content: str, max_length: int = 500, strip_controls: bool = True) -> str:
    """
    Sanitize user input to prevent injection attacks
    
    Args:
        content: Input string to sanitize
        max_length: Maximum allowed length (default: 500 chars)
        strip_controls: Whether to remove control characters (default: True)
    
    Returns:
        Sanitized string
    """
    if not isinstance(content, str):
        content = str(content)
    
    # Limit length to prevent DoS
    if len(content) > max_length:
        content = content[:max_length]
        logger.debug(f"Input truncated to {max_length} characters")
    
    # Remove control characters except newline, carriage return, tab
    if strip_controls:
        # Keep only printable characters plus common whitespace
        content = ''.join(
            char for char in content 
            if ord(char) >= 32 or char in '\n\r\t'
        )
    
    # Remove null bytes (can cause issues in C libraries)
    content = content.replace('\x00', '')
    
    return content.strip()


def validate_api_key_format(api_key: str, min_length: int = 16) -> bool:
    """
    Validate API key format
    
    Args:
        api_key: API key to validate
        min_length: Minimum required length (default: 16)
    
    Returns:
        True if format is valid, False otherwise
    """
    if not isinstance(api_key, str):
        return False
    
    # Check minimum length
    if len(api_key) < min_length:
        return False
    
    # Check for obviously invalid patterns
    invalid_patterns = [
        'your_api_key_here',
        'placeholder',
        'example',
        'test_key',
        '12345',
        'aaaa',
    ]
    
    api_key_lower = api_key.lower()
    if any(pattern in api_key_lower for pattern in invalid_patterns):
        return False
    
    # Check that it's not all the same character
    if len(set(api_key)) < 3:
        return False
    
    return True


def validate_pubkey_format(pubkey: str, expected_length: int = 64) -> bool:
    """
    Validate public key format (hex string)
    
    Args:
        pubkey: Public key to validate
        expected_length: Expected length in characters (default: 64 for ed25519)
    
    Returns:
        True if format is valid, False otherwise
    """
    if not isinstance(pubkey, str):
        return False
    
    # Check exact length
    if len(pubkey) != expected_length:
        return False
    
    # Check hex format
    if not re.match(r'^[0-9a-fA-F]+$', pubkey):
        return False
    
    return True


def validate_node_id(node_id: str, allow_broadcast: bool = False) -> Optional[str]:
    """
    Validate and normalize a MeshCore node ID.
    
    Node IDs can be:
    - Short ID: 12 hex characters (e.g., "85efbcc27971")
    - Full pubkey: 64 hex characters
    - With ! prefix: "!85efbcc27971"
    - Broadcast: "^all", "ffffffff", "4294967295"
    
    Args:
        node_id: The node ID to validate
        allow_broadcast: Whether to accept broadcast addresses
    
    Returns:
        Normalized node ID (lowercase, no ! prefix) or None if invalid
    
    Raises:
        ValueError: If node ID format is invalid
    """
    if not node_id or not isinstance(node_id, str):
        raise ValueError("Node ID must be a non-empty string")
    
    node_id = node_id.strip()
    
    # Check for broadcast addresses
    broadcast_addresses = ['^all', 'ffffffff', '4294967295']
    if node_id.lower() in broadcast_addresses:
        if allow_broadcast:
            return node_id.lower()
        else:
            raise ValueError("Broadcast addresses not allowed")
    
    # Remove ! prefix if present
    if node_id.startswith('!'):
        node_id = node_id[1:]
    
    # Must be valid hex
    if not re.match(r'^[0-9a-fA-F]+$', node_id):
        raise ValueError(f"Node ID must be hexadecimal, got: {node_id[:20]}...")
    
    # Validate length: short ID (8-12 chars) or full pubkey (64 chars)
    valid_lengths = [8, 10, 12, 64]  # Common MeshCore ID lengths
    if len(node_id) not in valid_lengths:
        # For IDs that are too long but not pubkeys, log warning and truncate
        if len(node_id) > 12 and len(node_id) != 64:
            logger.warning(f"Non-standard node ID length {len(node_id)}, truncating to 12 chars")
            node_id = node_id[:12]
        elif len(node_id) < 8:
            raise ValueError(f"Node ID too short: {len(node_id)} chars (minimum 8)")
    
    return node_id.lower()


def validate_packet_json(packet_json: str, max_size: int = 10000) -> Optional[dict]:
    """
    Validate and parse a stored packet JSON string.
    
    Args:
        packet_json: JSON string to validate
        max_size: Maximum allowed size in bytes (default: 10KB)
    
    Returns:
        Parsed dict if valid, None if invalid
    """
    if not packet_json or not isinstance(packet_json, str):
        logger.warning("Invalid packet JSON: empty or not a string")
        return None
    
    # Size check to prevent DoS
    if len(packet_json) > max_size:
        logger.warning(f"Packet JSON too large: {len(packet_json)} bytes (max {max_size})")
        return None
    
    try:
        import json
        data = json.loads(packet_json)
        
        # Must be a dictionary
        if not isinstance(data, dict):
            logger.warning("Packet JSON must be a dictionary")
            return None
        
        # Validate required structure
        # Must have 'from' or 'from_node' field
        if 'from' not in data and 'from_node' not in data:
            logger.warning("Packet JSON missing 'from' or 'from_node' field")
            return None
        
        # Must have decoded.text or be reconstructable
        decoded = data.get('decoded', {})
        if not isinstance(decoded, dict):
            logger.warning("Packet 'decoded' field must be a dictionary")
            return None
        
        return data
        
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in packet: {e}")
        return None


def validate_port_number(port: int, allow_privileged: bool = False) -> bool:
    """
    Validate port number
    
    Args:
        port: Port number to validate
        allow_privileged: Whether to allow privileged ports <1024 (default: False)
    
    Returns:
        True if port is valid, False otherwise
    """
    if not isinstance(port, int):
        return False
    
    min_port = 1 if allow_privileged else 1024
    max_port = 65535
    
    return min_port <= port <= max_port


def validate_integer_range(value: int, min_value: int, max_value: int, name: str = "value") -> bool:
    """
    Validate integer is within range
    
    Args:
        value: Integer to validate
        min_value: Minimum allowed value (inclusive)
        max_value: Maximum allowed value (inclusive)
        name: Name of the value for error messages
    
    Returns:
        True if valid
    
    Raises:
        ValueError: If value is out of range
    """
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {type(value).__name__}")
    
    if value < min_value or value > max_value:
        raise ValueError(
            f"{name} must be between {min_value} and {max_value}, got {value}"
        )
    
    return True
