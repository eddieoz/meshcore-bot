import re
from .base_command import BaseCommand
from ..models import MeshMessage
from ..security_utils import validate_node_id, sanitize_input


class StoreForwardCommand(BaseCommand):
    def __init__(self, bot):
        super().__init__(bot)
        self.name = 'get'
        self.keywords = ['!get']
        self.description = 'Retrieve stored messages'
        self.requires_dm = False
        self.category = 'Utility'

    def get_help_text(self) -> str:
        return "Retrieves stored messages. In a channel, gets messages for that channel. In DM, gets your DMs. Use '!get <channel>' in DM to get broadcasts for a specific channel."

    def _resolve_node_id(self, message: MeshMessage) -> str:
        """
        Resolve the sender's node ID from message with security validation.
        
        Returns:
            Validated and normalized node ID, or None if invalid
        """
        node_id = message.sender_id
        
        # First, check if sender_id looks like a name (not a hex string)
        is_hex = False
        try:
            int(node_id, 16)
            is_hex = True
        except (ValueError, TypeError):
            is_hex = False
        
        if not is_hex:
            # Try to resolve name to hex ID from contacts
            if hasattr(self.bot, 'meshcore') and hasattr(self.bot.meshcore, 'contacts'):
                for contact_key, contact_data in self.bot.meshcore.contacts.items():
                    if contact_data.get('adv_name') == node_id:
                        # Found the contact by name, use the key (which is the hex ID)
                        if contact_key.startswith('!'):
                            node_id = contact_key[1:]
                        else:
                            node_id = contact_key
                        break
        
        # If node_id is a full pubkey (64 chars), try to find the short ID from contacts
        if len(node_id) == 64:
            if hasattr(self.bot, 'meshcore') and hasattr(self.bot.meshcore, 'contacts'):
                for contact_key, contact_data in self.bot.meshcore.contacts.items():
                    if contact_data.get('public_key') == node_id:
                        if contact_key.startswith('!'):
                            node_id = contact_key[1:]
                        else:
                            node_id = contact_key
                        break
        
        # Security: Validate and normalize the node ID using security_utils
        try:
            validated_id = validate_node_id(node_id, allow_broadcast=False)
            return validated_id
        except ValueError as e:
            self.bot.logger.warning(f"S&F: Invalid node ID '{node_id[:20]}...': {e}")
            return None

    def _validate_channel_filter(self, channel_input: str) -> str:
        """
        Validate and sanitize channel filter input.
        
        Returns:
            Sanitized channel name, or None if invalid
        """
        if not channel_input:
            return None
        
        # Sanitize input
        channel = sanitize_input(channel_input, max_length=64, strip_controls=True)
        
        # Validate channel name format (alphanumeric, hyphens, underscores, optional # prefix)
        if not re.match(r'^[#]?[\w-]+$', channel):
            self.bot.logger.warning(f"S&F: Invalid channel filter format: {channel[:20]}")
            return None
        
        return channel

    async def execute(self, message: MeshMessage):
        if not hasattr(self.bot, 'store_forward_manager') or not self.bot.store_forward_manager:
            await self.bot.command_manager.send_response(message, "Store & Forward is not enabled.")
            return False

        # Security: Resolve and validate node ID
        node_id = self._resolve_node_id(message)
        if not node_id:
            await self.bot.command_manager.send_response(message, "Unable to identify your node. Please try again.")
            return False
        
        # Update contact with public key if available in message
        # This is critical for send_dm to work if the contact was previously incomplete
        if hasattr(message, 'sender_pubkey') and message.sender_pubkey:
            if hasattr(self.bot, 'meshcore') and hasattr(self.bot.meshcore, 'contacts'):
                contact_key = node_id
                # Try with ! prefix if not present
                if contact_key not in self.bot.meshcore.contacts and f"!{contact_key}" in self.bot.meshcore.contacts:
                    contact_key = f"!{contact_key}"
                
                if contact_key in self.bot.meshcore.contacts:
                    contact = self.bot.meshcore.contacts[contact_key]
                    if not contact.get('public_key'):
                        self.bot.logger.info(f"Updating contact {node_id} with public key from message")
                        contact['public_key'] = message.sender_pubkey
        
        # Determine channel filter
        channel_filter = None
        
        if not message.is_dm:
            # In a channel: filter by that channel
            channel_filter = message.channel
        else:
            # In DM: check for arguments
            # message.content is "!get" or "!get #channel"
            parts = message.content.split()
            if len(parts) > 1:
                # Security: Validate and sanitize channel filter input
                channel_filter = self._validate_channel_filter(parts[1])
                if parts[1] and not channel_filter:
                    await self.bot.command_manager.send_response(message, "Invalid channel name format.")
                    return False
            else:
                # No argument in DM -> No broadcast messages (only DMs)
                channel_filter = None
        
        await self.bot.store_forward_manager.deliver_messages(message, node_id, channel_filter)
        return True
