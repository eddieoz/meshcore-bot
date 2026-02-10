#!/usr/bin/env python3
"""
Ping command for the MeshCore Bot
Handles the 'ping' keyword response
"""

from .base_command import BaseCommand
from ..models import MeshMessage


class PingCommand(BaseCommand):
    """Handles the ping command"""
    
    # Plugin metadata
    name = "ping"
    keywords = ['ping', '!ping']
    description = "Responds to 'ping' with 'Pong!'"
    category = "basic"
    
    def get_help_text(self) -> str:
        return self.translate('commands.ping.description')
    
    def get_response_format(self) -> str:
        """Get the response format from config"""
        if self.bot.config.has_section('Keywords'):
            format_str = self.bot.config.get('Keywords', 'ping', fallback=None)
            return self._strip_quotes_from_config(format_str) if format_str else None
        return None
    
    async def execute(self, message: MeshMessage) -> bool:
        """Execute the ping command"""
        return await self.handle_keyword_match(message)
