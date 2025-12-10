from .base_command import BaseCommand
from ..models import MeshMessage

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


    async def execute(self, message: MeshMessage):
        if not hasattr(self.bot, 'store_forward_manager') or not self.bot.store_forward_manager:
            await self.bot.command_manager.send_response(message, "Store & Forward is not enabled.")
            return False

        # Use sender_id which should be the hex ID. 
        # If sender_id is a name (e.g. from some message sources), we need to look up the hex ID.
        node_id = message.sender_id
        
        # Check if sender_id looks like a name (not a hex string)
        # Simple heuristic: if it contains non-hex chars or is long/short
        is_hex = False
        try:
            int(node_id, 16)
            is_hex = True
        except ValueError:
            is_hex = False
            
        if not is_hex:
            # Try to resolve name to hex ID from contacts
            if hasattr(self.bot, 'meshcore') and hasattr(self.bot.meshcore, 'contacts'):
                for contact_key, contact_data in self.bot.meshcore.contacts.items():
                    if contact_data.get('adv_name') == node_id:
                        # Found the contact by name, use the key (which is the hex ID)
                        # The contact_key in meshcore.contacts is usually the hex ID (e.g. !85efbcc27971)
                        # We need to strip the ! if present
                        if contact_key.startswith('!'):
                            node_id = contact_key[1:]
                        else:
                            node_id = contact_key
                        break
        
        # If node_id is very long (like a full pubkey), try to use the short ID (last 8 chars? or first 8?)
        # Meshtastic node IDs are typically 8 hex chars (4 bytes).
        # The log showed: 85efbcc27971bb58470fd3e8fcbcde5072002adba4ef501257f1b01dea792d92
        # The short ID seen in other logs is 85efbcc2.
        # Wait, the log "Received DM from 85efbcc27971" suggests 12 chars?
        # Let's look at the contacts list from the log: "🛸 mc/M2 CLI 85efbcc27971 0 hop"
        # So the ID is 12 chars (6 bytes).
        
        # If the ID is the full 64-char key, we should probably extract the ID from it if possible,
        # OR check if the DB has the full key.
        # But the DB stores what was in the packet 'from' field.
        # When we stored the message, we used: packet.get('from', packet.get('fromId'))
        # If that was the short ID, we need to match it.
        
        # If node_id is significantly longer than 12 chars, it's likely a full key.
        # We should try to find the corresponding contact to get the correct ID.
        if len(node_id) > 12:
             if hasattr(self.bot, 'meshcore') and hasattr(self.bot.meshcore, 'contacts'):
                # Try to find contact by full pubkey
                for contact_key, contact_data in self.bot.meshcore.contacts.items():
                    if contact_data.get('public_key') == node_id:
                        if contact_key.startswith('!'):
                            node_id = contact_key[1:]
                        else:
                            node_id = contact_key
                        break
                else:
                    # If not found, maybe just take the first 12 chars? Or last?
                    # Meshtastic ID is usually derived from the last 4 bytes of the MAC/Key.
                    # But here we see 85efbcc27971.
                    # Let's try to match the beginning.
                    pass
            
        # Fallback: if node_id is still long, truncate it to 12 chars (standard Meshtastic ID length in this setup)
        # This handles cases where the full public key is passed as sender_id
        # Fallback: if node_id is still long, truncate it to 12 chars (standard Meshtastic ID length in this setup)
        # This handles cases where the full public key is passed as sender_id
        if len(node_id) > 12:
            node_id = node_id[:12]
            
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
                # Use the second argument as channel filter
                channel_filter = parts[1]
                # Strip leading # if user typed it, but channel names in bot usually have # or not?
                # Config says: monitor_channels = Public,#bot,#bot-test
                # So channel names can have #.
                # If user types "!get bot-test", we might need to match "#bot-test".
                # But let's assume user types exact name or we do loose matching in deliver_messages (we did case-insensitive).
                # Let's just pass what they typed.
            else:
                # No argument in DM -> No broadcast messages (only DMs)
                channel_filter = None
        
        await self.bot.store_forward_manager.deliver_messages(message, node_id, channel_filter)
        return True
