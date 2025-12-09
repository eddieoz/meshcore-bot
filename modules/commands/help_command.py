#!/usr/bin/env python3
"""
Help command for the MeshCore Bot
Provides help information for commands and general usage
"""

from .base_command import BaseCommand
from ..models import MeshMessage


class HelpCommand(BaseCommand):
    """Handles the help command"""
    
    # Plugin metadata
    name = "help"
    keywords = ['!help']
    description = "Shows commands. Use 'help <command>' for details."
    category = "basic"
    
    def get_help_text(self) -> str:
        return self.translate('commands.help.description')
    
    async def execute(self, message: MeshMessage) -> bool:
        """Execute the help command"""
        # The help command is now handled by keyword matching in the command manager
        # This is just a placeholder for future functionality
        self.logger.debug("Help command executed (handled by keyword matching)")
        return True
    
    def get_specific_help(self, command_name: str, message: MeshMessage = None) -> str:
        """Get help text for a specific command"""
        # Map command aliases to their actual command names
        command_aliases = {
            't': 't_phrase',
            '!advert': 'advert',
            'test': 'test',
            'ping': 'ping',
            '!help': '!help'
        }
        
        # Normalize the command name
        normalized_name = command_aliases.get(command_name, command_name)
        
        # Get the command instance
        command = self.bot.command_manager.commands.get(normalized_name)
        
        if command:
            # Pass message context to get_help_text if the method supports it
            if hasattr(command, 'get_help_text') and callable(getattr(command, 'get_help_text')):
                try:
                    help_text = command.get_help_text(message)
                except TypeError:
                    # Fallback for commands that don't accept message parameter
                    help_text = command.get_help_text()
            else:
                help_text = self.translate('commands.help.no_help')
            return self.translate('commands.help.specific', command=command_name, help_text=help_text)
        else:
            available = self.get_available_commands_list()
            return self.translate('commands.help.unknown', command=command_name, available=available)
    
    def get_general_help(self) -> str:
        """Get general help text"""
        commands_list = self.get_available_commands_list()
        help_text = self.translate('commands.help.general', commands_list=commands_list)
        help_text += self.translate('commands.help.usage_examples')
        help_text += self.translate('commands.help.custom_syntax')
        return help_text
    
    def get_available_commands_list(self) -> str:
        """Get a formatted list of available commands"""
        commands_list = ""
        
        # Group commands by category
        basic_commands = ['test', 'ping', 'help']
        custom_syntax = ['t_phrase']  # Use the actual command key
        special_commands = ['advert']
        
        commands_list += "**Basic Commands:**\n"
        for cmd in basic_commands:
            if cmd in self.bot.command_manager.commands:
                help_text = self.bot.command_manager.commands[cmd].get_help_text()
                commands_list += f"• `{cmd}` - {help_text}\n"
        
        commands_list += "\n**Custom Syntax:**\n"
        for cmd in custom_syntax:
            if cmd in self.bot.command_manager.commands:
                help_text = self.bot.command_manager.commands[cmd].get_help_text()
                # Add user-friendly aliases
                if cmd == 't_phrase':
                    commands_list += f"• `t phrase` - {help_text}\n"
                else:
                    commands_list += f"• `{cmd}` - {help_text}\n"
        
        commands_list += "\n**Special Commands:**\n"
        for cmd in special_commands:
            if cmd in self.bot.command_manager.commands:
                help_text = self.bot.command_manager.commands[cmd].get_help_text()
                commands_list += f"• `{cmd}` - {help_text}\n"
        
        return commands_list
    

