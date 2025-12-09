#!/usr/bin/env python3
"""
Roll command for the MeshCore Bot
Handles random number generation between 1 and X (default 100)
"""

import random
import re
from .base_command import BaseCommand
from ..models import MeshMessage


class RollCommand(BaseCommand):
    """Handles random number rolling commands"""
    
    # Plugin metadata
    name = "roll"
    keywords = ['!roll']
    description = "Roll a random number between 1 and X (default 100). Use 'roll' for 1-100, 'roll 50' for 1-50, etc."
    category = "games"
    
    def get_help_text(self) -> str:
        return self.translate('commands.roll.help')
    
    def matches_keyword(self, message: MeshMessage) -> bool:
        """Override to handle roll-specific matching"""
        content = message.content.strip().lower()
        
        # Handle command-style messages
        # if content.startswith('!'):
        #     content = content[1:].strip().lower()
        
        # Check for exact "roll" match
        if content == "!roll":
            return True
        
        # Check for roll with parameters (roll 50, roll 1000, etc.)
        # Ensure "roll" is the first word and followed by valid number
        if content.startswith("!roll "):
            words = content.split()
            if len(words) >= 2 and words[0] == "!roll":
                roll_part = content[6:].strip()  # Get everything after "roll "
                # Check if the roll part is valid number notation (not just any word)
                max_num = self.parse_roll_notation(roll_part)
                return max_num is not None  # Only match if it's valid number notation
        
        return False
    
    def parse_roll_notation(self, roll_input: str) -> int:
        """
        Parse roll notation and return the maximum number
        Supports: 50, 100, 1000, etc.
        Returns the maximum number or None if invalid
        """
        roll_input = roll_input.strip()
        
        # Handle direct number (e.g., "50", "100", "1000")
        if roll_input.isdigit():
            max_num = int(roll_input)
            if 1 <= max_num <= 10000:  # Reasonable limit
                return max_num
            else:
                return None
        
        return None
    
    def roll_number(self, max_num: int) -> int:
        """Roll a random number between 1 and max_num (inclusive)"""
        return random.randint(1, max_num)
    
    def format_roll_result(self, max_num: int, result: int) -> str:
        """Format roll result into a readable string"""
        return self.translate('commands.roll.result', max=max_num, result=result)
    
    async def execute(self, message: MeshMessage) -> bool:
        """Execute the roll command"""
        content = message.content.strip()
        
        # Handle command-style messages
        if content.startswith('!'):
            content = content[1:].strip()
        
        # Default to 1-100 if no specification
        if content.lower() == "roll":
            max_num = 100
        else:
            # Parse roll specification
            roll_part = content[5:].strip()  # Get everything after "roll "
            max_num = self.parse_roll_notation(roll_part)
            
            if max_num is None:
                # Invalid roll specification
                response = self.translate('commands.roll.invalid_number')
                return await self.send_response(message, response)
        
        # Roll the number
        result = self.roll_number(max_num)
        
        # Format and send response
        response = self.format_roll_result(max_num, result)
        return await self.send_response(message, response)
