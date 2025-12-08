#!/usr/bin/env python3
"""
Cmd command for the MeshCore Bot
Lists available commands in a compact, comma-separated format for LoRa
"""

from .base_command import BaseCommand
from ..models import MeshMessage


class CmdCommand(BaseCommand):
    """Handles the cmd command"""
    
    def get_help_text(self) -> str:
        return "Lists commands in compact format."
    
    async def execute(self, message: MeshMessage) -> bool:
        """Execute the cmd command"""
        # The cmd command is handled by keyword matching in the command manager
        # This is just a placeholder for future functionality
        self.logger.debug("Cmd command executed (handled by keyword matching)")
        return True
