#!/usr/bin/env python3
"""
Solar Command - Provides solar conditions and HF band information
"""

from .base_command import BaseCommand
from ..solar_conditions import solar_conditions, hf_band_conditions
from ..models import MeshMessage


class SolarCommand(BaseCommand):
    """Command to get solar conditions"""
    
    # Plugin metadata
    name = "solar"
    keywords = ['!solar']
    description = "Get solar conditions and HF band status"
    category = "solar"
    
    def __init__(self, bot):
        super().__init__(bot)
    
    async def execute(self, message: MeshMessage) -> bool:
        """Execute the solar command"""
        try:
            # Get solar conditions (more readable format)
            solar_info = solar_conditions()
            
            # Send response (solar only, more readable)
            response = self.translate('commands.solar.response', info=solar_info)
            
            # Use the unified send_response method
            return await self.send_response(message, response)
            
        except Exception as e:
            error_msg = self.translate('commands.solar.error', error=str(e))
            await self.send_response(message, error_msg)
            return False
