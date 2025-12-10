#!/usr/bin/env python3
"""
Store & Forward Manager
Handles storage and delivery of messages for offline nodes or on-demand retrieval.
"""

import json
import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import deque

# Security utilities
from .security_utils import sanitize_input, validate_node_id, validate_packet_json

class StoreForwardManager:
    """
    Manages Store & Forward functionality.
    - Stores directed messages for specific nodes.
    - Stores broadcast messages for all nodes (if configured).
    - Delivers messages upon request (!get).
    """
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = bot.logger
        self.db_manager = bot.db_manager
        
        # Load configuration
        self.enabled = self.bot.config.getboolean('StoreForward', 'enabled', fallback=True)
        self.ttl_hours = self.bot.config.getint('StoreForward', 'ttl_hours', fallback=48)
        self.delivered_retention_hours = self.bot.config.getint('StoreForward', 'delivered_retention_hours', fallback=2)
        self.max_messages_per_node = self.bot.config.getint('StoreForward', 'max_messages_per_node', fallback=500)
        self.store_broadcasts = self.bot.config.getboolean('StoreForward', 'store_broadcasts', fallback=True)
        
        # Load filters
        self.to_allow = self._load_list_config('to_allow')
        self.to_disallow = self._load_list_config('to_disallow')
        self.from_allow = self._load_list_config('from_allow')
        self.from_disallow = self._load_list_config('from_disallow')
        self.monitor_channels = self._load_list_config('monitor_channels')
        
        # Security: Rate limiting configuration
        self.max_total_messages = self.bot.config.getint('StoreForward', 'max_total_messages', fallback=10000)
        self.rate_limit_window = self.bot.config.getint('StoreForward', 'rate_limit_window', fallback=60)
        self.rate_limit_count = self.bot.config.getint('StoreForward', 'rate_limit_count', fallback=100)
        self._message_timestamps = deque(maxlen=self.rate_limit_count * 2)  # Rolling window
        
        if self.enabled:
            self._init_database()
            self.logger.info("Store & Forward Manager initialized")
            
    def _load_list_config(self, key: str) -> List[str]:
        """Load comma-separated list from config"""
        val = self.bot.config.get('StoreForward', key, fallback='')
        return [x.strip() for x in val.split(',') if x.strip()]

    def _init_database(self):
        """Initialize database tables"""
        # Messages table
        self.db_manager.create_table('store_forward_messages', '''
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            to_node TEXT NOT NULL,
            from_node TEXT NOT NULL,
            packet_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            delivered INTEGER DEFAULT 0,
            delivered_at INTEGER
        ''')
        
        # Broadcast receipts table (to track who has received which broadcast)
        self.db_manager.create_table('store_forward_receipts', '''
            message_id INTEGER NOT NULL,
            node_id TEXT NOT NULL,
            delivered_at INTEGER NOT NULL,
            PRIMARY KEY (message_id, node_id),
            FOREIGN KEY (message_id) REFERENCES store_forward_messages(id) ON DELETE CASCADE
        ''')

    def _node_id_to_hex(self, node_id: Any) -> str:
        """Convert node ID to hex format (!xxxxxxxx)"""
        try:
            node_int = int(node_id)
            return f"!{node_int:08x}"
        except (ValueError, TypeError):
            return str(node_id)

    def _format_timestamp(self, timestamp: int) -> str:
        """Format unix timestamp to readable string"""
        try:
            dt = datetime.fromtimestamp(int(timestamp))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError, OSError) as e:
            self.logger.debug(f"Timestamp formatting failed for {timestamp}: {e}")
            return str(timestamp)
    
    def _check_rate_limit(self) -> bool:
        """
        Check if message storage is within rate limits.
        Returns True if allowed, False if rate limited.
        """
        now = time.time()
        cutoff = now - self.rate_limit_window
        
        # Remove timestamps outside the window
        while self._message_timestamps and self._message_timestamps[0] < cutoff:
            self._message_timestamps.popleft()
        
        if len(self._message_timestamps) >= self.rate_limit_count:
            self.logger.warning(f"S&F: Rate limit exceeded ({self.rate_limit_count} messages in {self.rate_limit_window}s)")
            return False
        
        return True
    
    def _check_total_message_limit(self) -> bool:
        """
        Check if total stored messages is within limits.
        Returns True if allowed, False if at limit.
        """
        try:
            rows = self.db_manager.execute_query('''
                SELECT COUNT(*) as count FROM store_forward_messages
                WHERE delivered = 0
            ''')
            if rows and rows[0]['count'] >= self.max_total_messages:
                self.logger.warning(f"S&F: Total message limit reached ({self.max_total_messages})")
                return False
            return True
        except Exception as e:
            self.logger.error(f"S&F: Error checking total message limit: {e}")
            return True  # Allow on error to avoid blocking legitimate messages

    def _check_filter(self, node_id: str, allow_list: List[str], disallow_list: List[str]) -> bool:
        """
        Check if node passes filters.
        - If disallow list has entries and node is in it -> False
        - If allow list has entries and node is NOT in it -> False
        - Otherwise -> True
        """
        if not node_id:
            return False
            
        if disallow_list and node_id in disallow_list:
            return False
            
        if allow_list and node_id not in allow_list:
            return False
            
        return True

    def _is_broadcast(self, to_node: str) -> bool:
        """Check if destination is a broadcast address"""
        return to_node in ['^all', '4294967295', 'ffffffff']

    def process_message(self, message) -> bool:
        """
        Process an incoming message for storage.
        Returns True if stored, False otherwise.
        """
        # self.logger.info("S&F: process_message called")
        
        if not self.enabled:
            self.logger.info("S&F: Disabled")
            return False
        
        # Security: Check rate limits before processing
        if not self._check_rate_limit():
            return False
        
        if not self._check_total_message_limit():
            return False
            
        # Extract packet from message if available, otherwise try to reconstruct or fail
        packet = getattr(message, 'packet', None)
        if not packet:
            # Try to use raw packet if available
            packet = getattr(message, 'raw', None)
            
        if not packet:
            # Attempt to reconstruct packet from MeshMessage attributes
            if hasattr(message, 'content') and hasattr(message, 'sender_id'):
                self.logger.info("S&F: Reconstructing packet from MeshMessage")
                packet = {
                    'from': message.sender_id,
                    'to': '^all' if not message.is_dm else 'self', # Approximate
                    'decoded': {'text': message.content},
                    'channel_name': message.channel,
                    'id': getattr(message, 'id', None) or int(time.time())
                }
            else:
                self.logger.info("S&F: No packet found in message and cannot reconstruct")
                return False
            
        # Ensure packet has decoded text
        if 'decoded' not in packet or 'text' not in packet['decoded']:
            self.logger.info("S&F: No decoded text in packet")
            return False
            
        text = packet['decoded']['text']
        # Ignore commands (starting with !)
        if text.startswith('!'):
            self.logger.info(f"S&F: Ignoring command message: {text}")
            return False

        from_node = str(packet.get('from', packet.get('fromId')))
        to_node = str(packet.get('to', packet.get('toId')))
        
        self.logger.info(f"S&F: Processing msg from {from_node} to {to_node} on channel {getattr(message, 'channel', 'None')}")
        
        if not from_node or not to_node:
            self.logger.info("S&F: Missing from/to node")
            return False
            
        # Check channel monitoring if configured
        # Use message.channel if available (MeshMessage), otherwise try to find it in packet
        channel = getattr(message, 'channel', None)
        if channel is None:
            # Try to extract from packet if possible (usually not directly available in raw packet without context)
            # But MeshMessage should have it.
            pass
            
        if channel:
            # Store channel name in packet for retrieval
            packet['channel_name'] = channel
            
        if self.monitor_channels and channel:
            # If monitor_channels is set, message channel MUST be in it
            if channel not in self.monitor_channels:
                self.logger.info(f"S&F: Channel '{channel}' not in monitor list {self.monitor_channels}")
                return False

        # Check filters
        if not self._check_filter(from_node, self.from_allow, self.from_disallow):
            self.logger.info(f"S&F: Node {from_node} blocked by filters")
            return False

        is_broadcast = self._is_broadcast(to_node)
        
        if is_broadcast:
            if not self.store_broadcasts:
                self.logger.info("S&F: Broadcast storage disabled")
                return False
                
            # Broadcast Logic
            if self.to_allow:
                # Fan-Out: Store for specific allowed nodes
                stored_count = 0
                for target in self.to_allow:
                    self._store_single_message(packet, target, from_node)
                    stored_count += 1
                return stored_count > 0
            else:
                # Store as generic broadcast
                self.logger.info(f"S&F: Storing broadcast from {from_node}")
                self._store_single_message(packet, '^all', from_node)
                return True
        else:
            # Directed Logic
            if not self._check_filter(to_node, self.to_allow, self.to_disallow):
                self.logger.info(f"S&F: Destination {to_node} blocked by filters")
                return False
            
            self.logger.info(f"S&F: Storing directed message for {to_node}")
            self._store_single_message(packet, to_node, from_node)
            return True

    def _store_single_message(self, packet: Dict, to_node: str, from_node: str):
        """Store a single message in the database with security validation"""
        try:
            # Security: Sanitize message content before storage
            if 'decoded' in packet and 'text' in packet['decoded']:
                original_text = packet['decoded']['text']
                packet['decoded']['text'] = sanitize_input(
                    original_text, 
                    max_length=1000,  # Reasonable limit for mesh messages
                    strip_controls=True
                )
            
            packet_json = json.dumps(packet)
            
            # Security: Validate packet JSON size (prevent DoS via oversized packets)
            if len(packet_json) > 10000:  # 10KB limit
                self.logger.warning(f"S&F: Packet JSON too large ({len(packet_json)} bytes), dropping")
                return
            
            now = int(time.time())
            expires_at = now + (self.ttl_hours * 3600)
            
            self.db_manager.execute_update('''
                INSERT INTO store_forward_messages 
                (to_node, from_node, packet_json, created_at, expires_at, delivered)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (to_node, from_node, packet_json, now, expires_at))
            
            # Record timestamp for rate limiting
            self._message_timestamps.append(now)
            
            self._enforce_node_limit(to_node)
            
        except Exception as e:
            self.logger.error(f"Failed to store message: {e}")

    def _enforce_node_limit(self, node_id: str):
        """Enforce max messages per node"""
        try:
            # Get count
            rows = self.db_manager.execute_query('''
                SELECT COUNT(*) as count FROM store_forward_messages
                WHERE to_node = ? AND delivered = 0
            ''', (node_id,))
            
            if rows and rows[0]['count'] > self.max_messages_per_node:
                limit = rows[0]['count'] - self.max_messages_per_node
                # Delete oldest
                self.db_manager.execute_update('''
                    DELETE FROM store_forward_messages
                    WHERE id IN (
                        SELECT id FROM store_forward_messages
                        WHERE to_node = ? AND delivered = 0
                        ORDER BY created_at ASC
                        LIMIT ?
                    )
                ''', (node_id, limit))
        except Exception as e:
            self.logger.error(f"Failed to enforce limit: {e}")

    async def deliver_messages(self, message, requesting_node_id: str, channel_filter: Optional[str] = None):
        """
        Deliver stored messages to the requesting node via DM (for privacy).
        Always responds via DM even if command was issued in a channel.
        
        Includes:
        1. Directed messages (marked delivered).
        2. Broadcast messages (tracked via receipts).
        
        Args:
            message: The original MeshMessage (used for send_response).
            requesting_node_id: The hex node ID requesting messages (for DB queries).
            channel_filter: If set, only return broadcast messages from this channel. 
                            If None, return NO broadcast messages (only DMs).
        """
        if not self.enabled or not requesting_node_id:
            return

        requesting_node_id = str(requesting_node_id)
        
        # For privacy: always send via DM. Determine how to send based on message source.
        # - If message is a DM: use send_response (works like !path, !help)
        # - If message is from channel: look up sender name and use send_dm directly
        
        sender_name = None
        if not message.is_dm:
            # Channel message - need to look up sender name for DM
            # For channel messages, message.sender_id is usually the name (e.g., "🛸 mc/M2")
            sender_name = message.sender_id
            self.logger.info(f"S&F: Channel message from '{sender_name}', will respond via DM for privacy")
        
        # 1. Get Directed Messages (Always deliver DMs)
        directed_msgs = self.db_manager.execute_query('''
            SELECT id, packet_json, from_node, created_at
            FROM store_forward_messages
            WHERE to_node = ? AND delivered = 0
            ORDER BY created_at ASC
        ''', (requesting_node_id,))
        
        # 2. Get Broadcast Messages (Only if channel_filter is set)
        broadcast_msgs = []
        if channel_filter:
            # Select messages where to_node is ^all AND id is NOT in receipts for this node
            raw_broadcasts = self.db_manager.execute_query('''
                SELECT m.id, m.packet_json, m.from_node, m.created_at
                FROM store_forward_messages m
                WHERE m.to_node = '^all' 
                AND m.expires_at > ?
                AND NOT EXISTS (
                    SELECT 1 FROM store_forward_receipts r 
                    WHERE r.message_id = m.id AND r.node_id = ?
                )
                ORDER BY m.created_at ASC
            ''', (int(time.time()), requesting_node_id))
            
            # Filter by channel in Python with validation
            for msg in raw_broadcasts:
                # Security: Validate JSON before parsing
                packet = validate_packet_json(msg['packet_json'])
                if packet:
                    msg_channel = packet.get('channel_name')
                    if msg_channel and msg_channel.lower() == channel_filter.lower():
                        broadcast_msgs.append(msg)
                else:
                    self.logger.warning(f"S&F: Invalid packet JSON in message {msg['id']}, skipping")
        
        self.logger.info(f"S&F: Found {len(directed_msgs)} directed and {len(broadcast_msgs)} broadcast messages for {requesting_node_id} (Filter: {channel_filter})")
        
        all_messages = directed_msgs + broadcast_msgs
        
        # Helper function to send message (DM for privacy)
        async def send_private(content: str) -> bool:
            if message.is_dm:
                # DM: use send_response like other commands (!path, !help)
                return await self.bot.command_manager.send_response(message, content)
            else:
                # Channel: send DM to sender for privacy
                return await self.bot.command_manager.send_dm(sender_name, content)
        
        if not all_messages:
            await send_private("No stored messages found.")
            return

        self.logger.info(f"Delivering {len(all_messages)} messages to {sender_name or message.sender_id}")
        
        count = 0
        for msg in all_messages:
            try:
                # Security: Validate JSON before use
                packet = validate_packet_json(msg['packet_json'])
                if not packet:
                    self.logger.warning(f"S&F: Skipping message {msg['id']} with invalid JSON")
                    continue
                    
                decoded = packet.get('decoded', {})
                text = decoded.get('text', '')
                
                # Format message
                timestamp = self._format_timestamp(msg['created_at'])
                # If it's a broadcast, indicate channel
                prefix = ""
                if packet.get('to') == '^all':
                    channel_name = packet.get('channel_name', 'Unknown')
                    prefix = f"[{channel_name}] "
                
                msg_content = f"{prefix}[{timestamp}] {msg['from_node']}: {text}"
                
                # Send via DM for privacy
                if await send_private(msg_content):
                    count += 1
                    # Mark as delivered or add receipt
                    if packet.get('to') == '^all':
                        # Add receipt for broadcast
                        self.db_manager.execute_update('''
                            INSERT OR IGNORE INTO store_forward_receipts (message_id, node_id, delivered_at)
                            VALUES (?, ?, ?)
                        ''', (msg['id'], requesting_node_id, int(time.time())))
                    else:
                        # Mark directed message as delivered
                        self.db_manager.execute_update('''
                            UPDATE store_forward_messages 
                            SET delivered = 1, delivered_at = ? 
                            WHERE id = ?
                        ''', (int(time.time()), msg['id']))
                else:
                    self.logger.warning(f"Failed to deliver message {msg['id']} to {sender_name or message.sender_id}")
                    
            except Exception as e:
                self.logger.error(f"Error delivering message {msg['id']}: {e}")
                
        await send_private(f"Delivered {count} messages.")

    def _format_message_for_delivery(self, packet: Dict, from_node: str, created_at: int) -> str:
        """Format the message with metadata"""
        original_text = packet['decoded']['text']
        from_hex = self._node_id_to_hex(from_node)
        timestamp_str = self._format_timestamp(created_at)
        
        # Try to get channel name/index
        channel = packet.get('channel_name')
        if channel is None:
            channel = packet.get('channel')
        if channel is None:
            channel = packet.get('channelId')
        
        channel_str = f"Channel: {channel}" if channel is not None else "Channel: Primary"
        
        return f"[Stored Message]\nFrom: {from_hex}\nSent: {timestamp_str}\n{channel_str}\n---\n{original_text}"

    def _mark_directed_delivered(self, message_id: int):
        """Mark directed message as delivered"""
        self.db_manager.execute_update('''
            UPDATE store_forward_messages
            SET delivered = 1, delivered_at = ?
            WHERE id = ?
        ''', (int(time.time()), message_id))

    def _add_broadcast_receipt(self, message_id: int, node_id: str):
        """Add receipt for broadcast message"""
        self.db_manager.execute_update('''
            INSERT INTO store_forward_receipts (message_id, node_id, delivered_at)
            VALUES (?, ?, ?)
        ''', (message_id, node_id, int(time.time())))

    def cleanup_old_messages(self):
        """Cleanup expired and delivered messages"""
        if not self.enabled:
            return
            
        now = int(time.time())
        
        # 1. Delete delivered directed messages past retention
        retention_limit = now - (self.delivered_retention_hours * 3600)
        self.db_manager.execute_update('''
            DELETE FROM store_forward_messages
            WHERE delivered = 1 AND delivered_at < ?
        ''', (retention_limit,))
        
        # 2. Delete expired messages (directed and broadcast)
        self.db_manager.execute_update('''
            DELETE FROM store_forward_messages
            WHERE expires_at < ?
        ''', (now,))
        
        # 3. Cleanup orphaned receipts
        self.db_manager.execute_update('''
            DELETE FROM store_forward_receipts
            WHERE message_id NOT IN (SELECT id FROM store_forward_messages)
        ''')

    def get_stats_for_node(self, node_id: str) -> Dict[str, int]:
        """Get Store & Forward statistics for a specific node"""
        if not self.enabled:
            return {}
            
        node_id = str(node_id)
        now = int(time.time())
        
        # Count directed messages waiting
        directed_count = self.db_manager.execute_query('''
            SELECT COUNT(*) as count FROM store_forward_messages
            WHERE to_node = ? AND delivered = 0
        ''', (node_id,))
        directed = directed_count[0]['count'] if directed_count else 0
        
        # Count broadcast messages waiting
        broadcast_count = self.db_manager.execute_query('''
            SELECT COUNT(*) as count FROM store_forward_messages m
            WHERE m.to_node = '^all' 
            AND m.expires_at > ?
            AND NOT EXISTS (
                SELECT 1 FROM store_forward_receipts r 
                WHERE r.message_id = m.id AND r.node_id = ?
            )
        ''', (now, node_id))
        broadcast = broadcast_count[0]['count'] if broadcast_count else 0
        
        return {
            'directed': directed,
            'broadcast': broadcast,
            'total': directed + broadcast
        }
