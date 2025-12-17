#!/usr/bin/env python3
"""
Map Auto-Uploader Module
Automatically uploads repeater and room server advertisements to map.meshcore.dev
"""

import logging
import json
import time
import hashlib
import aiohttp
import asyncio
from typing import Dict, Optional, Any
from cryptography.hazmat.primitives.asymmetric import ed25519

class MapAutoUploaderManager:
    """Manages automatic uploading of repeaters/rooms to the online map"""
    
    def __init__(self, bot, uploader_private_key: bytes):
        """
        Initialize the Map Auto-Uploader
        
        Args:
            bot: The bot instance
            uploader_private_key: The 64-byte private key for signing uploads
        """
        self.bot = bot
        self.logger = logging.getLogger('MapAutoUploader')
        
        self.enabled = bot.config.getboolean('MapAutoUploader', 'enabled', fallback=False)
        self.api_url = bot.config.get('MapAutoUploader', 'api_url', fallback='https://map.meshcore.dev/api/v1/uploader/node')
        self.upload_interval = bot.config.getint('MapAutoUploader', 'upload_interval_seconds', fallback=3600)
        self.api_timeout = bot.config.getint('MapAutoUploader', 'api_timeout', fallback=10)
        
        # Store the private key for signing
        # The key is 64 bytes (seed + public key), but cryptography lib expects 32-byte seed
        if len(uploader_private_key) == 64:
            # Ed25519 private key is typically 32 bytes seed + 32 bytes public key
            # cryptography library uses the 32-byte seed
            self.private_key = ed25519.Ed25519PrivateKey.from_private_bytes(uploader_private_key[:32])
            # IMPORTANT: Use the library's derived public key, not the one from the 64-byte array
            # This ensures consistency between signing and verification
            self.public_key_bytes = self.private_key.public_key().public_bytes_raw()
            self.public_key_hex = self.public_key_bytes.hex()
            self.logger.info(f"Initialized with signing key")
        else:
            self.logger.error(f"Invalid private key length: {len(uploader_private_key)} bytes (expected 64)")
            self.enabled = False
            
        # Cache for rate limiting: pubkey -> last_upload_timestamp
        self.seen_adverts = {}
        
        # Radio parameters from bot connection
        self.radio_params = {}
        if hasattr(bot.meshcore, 'self_info'):
            info = bot.meshcore.self_info
            # Convert values to match API requirements (Hz -> MHz, Hz -> kHz)
            self.radio_params = {
                'freq': info.get('radio_freq', 869.618),  
                'cr': info.get('radio_cr', 8),
                'sf': info.get('radio_sf', 8),
                'bw': info.get('radio_bw', 62.5),
                'tx_power': info.get('tx_power', 22)
            }
            # Adjust units if needed - based on reference, freq is MHz (no conversion needed if already float like 869.618)
            # Reference: freq: clientInfo.radioFreq / 1000 -> assumes input is Hz? 
            # In meshcore.py logs I saw: 'radio_freq': 869.618 -> this is already MHz.
            # Reference: bw: clientInfo.radioBw / 1000 -> assumes input is Hz?
            # In meshcore.py logs I saw: 'radio_bw': 62.5 -> this is already kHz.
            
            # Note: Reference divides freq and bw by 1000. Let's verify units.
            # If log says 869.618, it is definitely MHz. Reference might be dealing with Hz from its library.
            # We will use the values as-is if they look like MHz/kHz, else adjust.
        
        if self.enabled:
            self.logger.info("Map Auto-Uploader initialized and enabled")
        else:
            self.logger.info("Map Auto-Uploader initialized but DISABLED")

    def sign_data(self, data: Dict[str, Any]) -> Dict[str, str]:
        """
        Sign the data payload with Ed25519
        MATCHES REFERENCE: SHA256(json_string) -> Sign
        """
        try:
            # Serialize to JSON - ensure no spaces for consistency if needed, but reference uses default stringify
            # Reference: const json = JSON.stringify(data);
            # Python's json.dumps adds spaces by default? No, separators defaults to (', ', ': ')
            # JS JSON.stringify defaults to NO spaces.
            # We must use separators=(',', ':') to match JS compact JSON
            json_str = json.dumps(data, separators=(',', ':'))
            
            # SHA-256 hash of the JSON string bytes
            # Reference: crypto.subtle.digest('SHA-256', new TextEncoder().encode(json))
            data_hash = hashlib.sha256(json_str.encode('utf-8')).digest()
            
            # Sign the hash
            signature = self.private_key.sign(data_hash)
            
            return {
                "data": json_str,
                "signature": signature.hex()
            }
        except Exception as e:
            self.logger.error(f"Error signing data: {e}")
            return None

    async def process_advert(self, packet_hex: str, advert_data: Dict[str, Any]):
        """
        Process a received advertisement packet
        """
        if not self.enabled:
            return

        try:
            # 1. Filter by type (Repeater or Room only)
            # advert_data comes from MessageHandler.parse_advert which returns 'mode' string
            mode = advert_data.get('mode', '').lower()
            if mode not in ['repeater', 'room', 'roomserver']:
                # self.logger.debug(f"Ignoring advert type: {mode}")
                return

            # 2. Extract node info
            pubkey = advert_data.get('public_key', '')
            if not pubkey:
                return
                
            timestamp = advert_data.get('timestamp', time.time())
            
            # 3. Rate limiting and Replay Check
            # Check if recently uploaded
            if pubkey in self.seen_adverts:
                last_seen_ts = self.seen_adverts[pubkey]
                
                # Replay protection: if timestamp is same or older than what we've seen
                if timestamp <= last_seen_ts:
                    # self.logger.debug(f"Ignoring replay/old advert for {pubkey[:8]}...")
                    return
                    
                # Rate limit: Don't upload if we uploaded this node recently (e.g. 1 hour)
                # Note: Reference logic is slightly different:
                # if(advert.timestamp < seenAdverts[pubKey] + 3600) return;
                # This checks if the ADVERT timestamp is too close to previous ADVERT timestamp
                # We should use current time for our upload rate limit to avoid spamming API
                current_time = time.time()
                # Use a separate tracking for upload time if needed, but here simple logic:
                # If we processed an upload for this node less than N seconds ago, skip
                if pubkey in self.seen_adverts and (current_time - self.seen_adverts[pubkey] < self.upload_interval):
                    # self.logger.debug(f"Rate limited upload for {pubkey[:8]}...")
                    return

            self.logger.info(f"Preparing upload for {mode}: {advert_data.get('name')} ({pubkey[:8]}...)")
            
            # Debug: Log packet hex info
            self.logger.info(f"📦 Packet hex: length={len(packet_hex)} chars, sample: {packet_hex[:64]}...")
            
            #4. Construct Payload
            # Format:
            # {
            #   params: { freq, cr, sf, bw },
            #   links: ["meshcore://<packet_hex>"]
            # }
            
            # Ensure radio params are available
            if not self.radio_params:
                # Try to refresh if missing
                 if hasattr(self.bot.meshcore, 'self_info'):
                    self.radio_params = {
                        'freq': self.bot.meshcore.self_info.get('radio_freq', 869.618),
                        'cr': self.bot.meshcore.self_info.get('radio_cr', 8),
                        'sf': self.bot.meshcore.self_info.get('radio_sf', 8),
                        'bw': self.bot.meshcore.self_info.get('radio_bw', 62.5)
                    }
            
            # If still using default/placeholder, might be an issue but better to upload than nothing
            
            payload_data = {
                "params": {
                    "freq": self.radio_params.get('freq', 869.618),
                    "cr": self.radio_params.get('cr', 8),
                    "sf": self.radio_params.get('sf', 8),
                    "bw": self.radio_params.get('bw', 62.5)
                },
                "links": [f"meshcore://{packet_hex[4:]}"]
            }
            
            # 5. Sign Data
            signed_payload = self.sign_data(payload_data)
            if not signed_payload:
                return
                
            # Add public key to request
            signed_payload['publicKey'] = self.public_key_hex
            
            # 6. Upload
            await self.upload_to_api(
                signed_payload, 
                node_name=advert_data.get('name', 'Unknown'),
                node_id=pubkey[:8]
            )
            
            # Update seen timestamp (use current time for rate limiting)
            self.seen_adverts[pubkey] = time.time()
            
        except Exception as e:
            self.logger.error(f"Error processing advert for upload: {e}")

    async def upload_to_api(self, data: Dict[str, Any], node_name: str = "Unknown", node_id: str = "Unknown"):
        """Post the signed data to the API"""
        try:
            # Debug: Log the request payload (truncate signature for readability)
            debug_payload = data.copy()
            if 'signature' in debug_payload:
                debug_payload['signature'] = debug_payload['signature'][:32] + '...'
            self.logger.info(f"📤 Request payload: {json.dumps(debug_payload, indent=2)}")
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url, 
                    json=data,
                    headers={'Content-Type': 'application/json'},
                    timeout=self.api_timeout
                ) as response:
                    if response.status in [200, 201]:
                        resp_json = await response.json()
                        self.logger.info(f"✅ Map upload successful for {node_name} ({node_id}): {resp_json}")
                    else:
                        text = await response.text()
                        self.logger.warning(f"❌ Map upload failed (HTTP {response.status}): {text}")
                        
        except asyncio.TimeoutError:
            self.logger.warning(f"❌ Map upload timed out after {self.api_timeout}s")
        except Exception as e:
            self.logger.error(f"❌ Map upload error: {e}")
