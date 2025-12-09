#!/usr/bin/env python3
"""
Dice command for the MeshCore Bot
Handles dice rolling for D&D and other tabletop games
"""

import random
import re
from .base_command import BaseCommand
from ..models import MeshMessage


class DiceCommand(BaseCommand):
    """Handles dice rolling commands"""
    
    # Plugin metadata
    name = "dice"
    keywords = ['!dice']
    description = "Roll dice for D&D and tabletop games. Use '!dice' for d6, '!dice d20' for d20, '!dice 2d6' for 2d6, etc."
    category = "games"
    
    # Standard D&D dice types
    DICE_TYPES = {
        'd4': 4,
        'd6': 6,
        'd8': 8,
        'd10': 10,
        'd12': 12,
        'd16': 16,
        'd20': 20
    }
    
    def get_help_text(self) -> str:
        return self.translate('commands.dice.help')
    
    def matches_keyword(self, message: MeshMessage) -> bool:
        """Override to handle dice-specific matching"""
        content = message.content.strip().lower()
        
        # # Handle command-style messages
        # if content.startswith('!'):
        #     content = content[1:].strip().lower()
        
        # Check for exact "dice" match
        if content == "!dice":
            return True
        
        # Check for dice with parameters (dice d20, dice 20, dice d6, etc.)
        # Ensure "dice" is the first word and followed by valid dice notation
        if content.startswith("!dice "):
            words = content.split()
            if len(words) >= 2 and words[0] == "!dice":
                dice_part = content[6:].strip()  # Get everything after "dice "
                # Check if the dice part is valid dice notation (not just any word)
                sides, count = self.parse_dice_notation(dice_part)
                return sides is not None  # Only match if it's valid dice notation
        
        return False
    
    def parse_dice_notation(self, dice_input: str) -> tuple:
        """
        Parse dice notation and return (sides, count)
        Supports: d20, 20, d6, 6, 2d6, 4d10, etc.
        Returns (sides, count) or (None, None) if invalid
        """
        dice_input = dice_input.strip().lower()
        
        # Handle multiple dice notation (e.g., "2d6", "4d10", "3d20")
        if 'd' in dice_input:
            parts = dice_input.split('d')
            if len(parts) == 2:
                count_str, sides_str = parts
                
                # Handle cases like "d6" (no count specified)
                if not count_str:
                    count = 1
                else:
                    try:
                        count = int(count_str)
                        if count < 1 or count > 10:  # Reasonable limit
                            return None, None
                    except ValueError:
                        return None, None
                
                # Parse sides
                try:
                    sides = int(sides_str)
                    if sides in self.DICE_TYPES.values():
                        return sides, count
                    else:
                        return None, None
                except ValueError:
                    return None, None
        
        # Handle direct number (e.g., "20" -> d20)
        if dice_input.isdigit():
            sides = int(dice_input)
            if sides in self.DICE_TYPES.values():
                return sides, 1
            else:
                return None, None
        
        # Handle dice type names (e.g., "d20", "d6")
        if dice_input in self.DICE_TYPES:
            return self.DICE_TYPES[dice_input], 1
        
        return None, None
    
    def roll_dice(self, sides: int, count: int = 1) -> list:
        """Roll dice and return list of results"""
        return [random.randint(1, sides) for _ in range(count)]
    
    def format_dice_result(self, sides: int, count: int, results: list) -> str:
        """Format dice roll results into a readable string"""
        if count == 1:
            # Single die roll
            return self.translate('commands.dice.single_die', sides=sides, result=results[0])
        else:
            # Multiple dice
            total = sum(results)
            results_str = ", ".join(map(str, results))
            return self.translate('commands.dice.multiple_dice', count=count, sides=sides, results=results_str, total=total)
    
    async def execute(self, message: MeshMessage) -> bool:
        """Execute the dice command"""
        content = message.content.strip()
        
        # Handle command-style messages
        if content.startswith('!'):
            content = content[1:].strip()
        
        # Default to d6 if no specification
        if content.lower() == "dice":
            sides = 6
            count = 1
        else:
            # Parse dice specification
            dice_part = content[5:].strip()  # Get everything after "dice "
            sides, count = self.parse_dice_notation(dice_part)
            
            if sides is None:
                # Invalid dice specification
                available_dice = ", ".join(self.DICE_TYPES.keys())
                response = self.translate('commands.dice.invalid_dice_type', available=available_dice)
                return await self.send_response(message, response)
        
        # Roll the dice
        results = self.roll_dice(sides, count)
        
        # Format and send response
        response = self.format_dice_result(sides, count, results)
        return await self.send_response(message, response)
