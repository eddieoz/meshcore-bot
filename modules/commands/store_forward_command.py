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
        return "Retrieves any messages stored for your node while you were offline. The bot stores messages directed to you and broadcasts (if enabled) for a limited time. Usage: !get"


    async def execute(self, message: MeshMessage):
        if not hasattr(self.bot, 'store_forward_manager') or not self.bot.store_forward_manager:
            await self.bot.command_manager.send_response(message, "Store & Forward is not enabled.")
            return False

        await self.bot.store_forward_manager.deliver_messages(message.sender_id)
        return True
