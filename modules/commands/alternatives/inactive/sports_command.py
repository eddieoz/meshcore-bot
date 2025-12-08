#!/usr/bin/env python3
"""
Sports command for the MeshCore Bot
Provides sports scores and schedules using ESPN API
API description via https://github.com/zuplo/espn-openapi/

Team ID Stability:
ESPN team IDs are generally stable but can change in certain circumstances:
- Team relocation or renaming
- Expansion teams (new teams added to leagues)
- ESPN data system updates

If a team returns "No games found", verify the team_id using:
  python3 test_scripts/find_espn_team_id.py <sport> <league> <team_name>

Team IDs should be periodically verified, especially after:
- League expansion announcements
- Team relocations or rebranding
- When users report "no games found" for known active teams
"""

import re
import json
import requests
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from .base_command import BaseCommand
from ..models import MeshMessage


class SportsCommand(BaseCommand):
    """Handles sports commands with ESPN API integration"""
    
    # Plugin metadata
    name = "sports"
    keywords = ['sports', 'score', 'scores']
    description = "Get sports scores and schedules (usage: sports [team/league])"
    category = "sports"
    cooldown_seconds = 3  # 3 second cooldown per user to prevent API abuse
    
    # ESPN API base URL
    ESPN_BASE_URL = "http://site.api.espn.com/apis/site/v2/sports"
    
    # Sport emojis for easy identification
    SPORT_EMOJIS = {
        'football': '🏈',
        'baseball': '⚾',
        'basketball': '🏀',
        'hockey': '🏒',
        'soccer': '⚽'
    }
    
    # Custom team abbreviations to distinguish between leagues
    # Only use -W suffixes for women's leagues
    WOMENS_TEAM_ABBREVIATIONS = {
        # NWSL teams - use custom abbreviations to distinguish from MLS
        '21422': 'LA-W',   # Angel City FC (Women's)
        '22187': 'BAY-W',  # Bay FC (Women's)
        '15360': 'CHI-W',  # Chicago Stars FC (Women's)
        '15364': 'GFC-W',  # Gotham FC (Women's)
        '17346': 'HOU-W',  # Houston Dash (Women's)
        '20907': 'KC-W',   # Kansas City Current (Women's)
        '15366': 'NC-W',   # North Carolina Courage (Women's)
        '18206': 'ORL-W',  # Orlando Pride (Women's)
        '15362': 'POR-W',  # Portland Thorns FC (Women's)
        '20905': 'LOU-W',  # Racing Louisville FC (Women's)
        '21423': 'SD-W',   # San Diego Wave FC (Women's)
        '15363': 'SEA-W',  # Seattle Reign FC (Women's)
        '19141': 'UTA-W',  # Utah Royals (Women's)
        '15365': 'WAS-W',  # Washington Spirit (Women's)
        # WNBA teams - use custom abbreviations to distinguish from NBA
        '14': 'SEA-W',     # Seattle Storm (Women's)
        '9': 'NY-W',       # New York Liberty (Women's)
        '6': 'LA-W',       # Los Angeles Sparks (Women's)
        '19': 'CHI-W',     # Chicago Sky (Women's)
        '20': 'ATL-W',     # Atlanta Dream (Women's)
        '18': 'CON-W',     # Connecticut Sun (Women's)
        '3': 'DAL-W',      # Dallas Wings (Women's)
        '129689': 'GS-W',  # Golden State Valkyries (Women's)
        '5': 'IND-W',      # Indiana Fever (Women's)
        '17': 'LV-W',      # Las Vegas Aces (Women's)
        '8': 'MIN-W',      # Minnesota Lynx (Women's)
        '11': 'PHX-W',     # Phoenix Mercury (Women's)
        '16': 'WSH-W',     # Washington Mystics (Women's)
    }
    
    # Team mappings for common searches
    # NOTE: Team IDs can change over time (see module docstring).
    # Use test_scripts/find_espn_team_id.py to verify/update team IDs.
    TEAM_MAPPINGS = {
        # NFL Teams
        'seahawks': {'sport': 'football', 'league': 'nfl', 'team_id': '26'},
        'hawks': {'sport': 'football', 'league': 'nfl', 'team_id': '26'},
        '49ers': {'sport': 'football', 'league': 'nfl', 'team_id': '25'},
        'niners': {'sport': 'football', 'league': 'nfl', 'team_id': '25'},
        'sf': {'sport': 'football', 'league': 'nfl', 'team_id': '25'},
        'bears': {'sport': 'football', 'league': 'nfl', 'team_id': '3'},
        'chicago': {'sport': 'football', 'league': 'nfl', 'team_id': '3'},
        'chi': {'sport': 'football', 'league': 'nfl', 'team_id': '3'},
        'bengals': {'sport': 'football', 'league': 'nfl', 'team_id': '4'},
        'cincinnati': {'sport': 'football', 'league': 'nfl', 'team_id': '4'},
        'cin': {'sport': 'football', 'league': 'nfl', 'team_id': '4'},
        'bills': {'sport': 'football', 'league': 'nfl', 'team_id': '2'},
        'buffalo': {'sport': 'football', 'league': 'nfl', 'team_id': '2'},
        'buf': {'sport': 'football', 'league': 'nfl', 'team_id': '2'},
        'broncos': {'sport': 'football', 'league': 'nfl', 'team_id': '7'},
        'denver': {'sport': 'football', 'league': 'nfl', 'team_id': '7'},
        'den': {'sport': 'football', 'league': 'nfl', 'team_id': '7'},
        'browns': {'sport': 'football', 'league': 'nfl', 'team_id': '5'},
        'cleveland': {'sport': 'football', 'league': 'nfl', 'team_id': '5'},
        'cle': {'sport': 'football', 'league': 'nfl', 'team_id': '5'},
        'buccaneers': {'sport': 'football', 'league': 'nfl', 'team_id': '27'},
        'bucs': {'sport': 'football', 'league': 'nfl', 'team_id': '27'},
        'tampa bay': {'sport': 'football', 'league': 'nfl', 'team_id': '27'},
        'tb': {'sport': 'football', 'league': 'nfl', 'team_id': '27'},
        'cardinals': {'sport': 'football', 'league': 'nfl', 'team_id': '22'},
        'arizona': {'sport': 'football', 'league': 'nfl', 'team_id': '22'},
        'ari': {'sport': 'football', 'league': 'nfl', 'team_id': '22'},
        'chargers': {'sport': 'football', 'league': 'nfl', 'team_id': '24'},
        'lac': {'sport': 'football', 'league': 'nfl', 'team_id': '24'},
        'chiefs': {'sport': 'football', 'league': 'nfl', 'team_id': '12'},
        'kansas city': {'sport': 'football', 'league': 'nfl', 'team_id': '12'},
        'kc': {'sport': 'football', 'league': 'nfl', 'team_id': '12'},
        'colts': {'sport': 'football', 'league': 'nfl', 'team_id': '11'},
        'indianapolis': {'sport': 'football', 'league': 'nfl', 'team_id': '11'},
        'ind': {'sport': 'football', 'league': 'nfl', 'team_id': '11'},
        'commanders': {'sport': 'football', 'league': 'nfl', 'team_id': '28'},
        'washington': {'sport': 'football', 'league': 'nfl', 'team_id': '28'},
        'wsh': {'sport': 'football', 'league': 'nfl', 'team_id': '28'},
        'cowboys': {'sport': 'football', 'league': 'nfl', 'team_id': '6'},
        'dallas': {'sport': 'football', 'league': 'nfl', 'team_id': '6'},
        'dal': {'sport': 'football', 'league': 'nfl', 'team_id': '6'},
        'dolphins': {'sport': 'football', 'league': 'nfl', 'team_id': '15'},
        'miami': {'sport': 'football', 'league': 'nfl', 'team_id': '15'},
        'mia': {'sport': 'football', 'league': 'nfl', 'team_id': '15'},
        'eagles': {'sport': 'football', 'league': 'nfl', 'team_id': '21'},
        'philadelphia': {'sport': 'football', 'league': 'nfl', 'team_id': '21'},
        'phi': {'sport': 'football', 'league': 'nfl', 'team_id': '21'},
        'falcons': {'sport': 'football', 'league': 'nfl', 'team_id': '1'},
        'atlanta': {'sport': 'football', 'league': 'nfl', 'team_id': '1'},
        'atl': {'sport': 'football', 'league': 'nfl', 'team_id': '1'},
        'giants': {'sport': 'football', 'league': 'nfl', 'team_id': '19'},
        'nyg': {'sport': 'football', 'league': 'nfl', 'team_id': '19'},
        'jaguars': {'sport': 'football', 'league': 'nfl', 'team_id': '30'},
        'jax': {'sport': 'football', 'league': 'nfl', 'team_id': '30'},
        'jets': {'sport': 'football', 'league': 'nfl', 'team_id': '20'},
        'nyj': {'sport': 'football', 'league': 'nfl', 'team_id': '20'},
        'lions': {'sport': 'football', 'league': 'nfl', 'team_id': '8'},
        'detroit': {'sport': 'football', 'league': 'nfl', 'team_id': '8'},
        'det': {'sport': 'football', 'league': 'nfl', 'team_id': '8'},
        'packers': {'sport': 'football', 'league': 'nfl', 'team_id': '9'},
        'green bay': {'sport': 'football', 'league': 'nfl', 'team_id': '9'},
        'gb': {'sport': 'football', 'league': 'nfl', 'team_id': '9'},
        'panthers': {'sport': 'football', 'league': 'nfl', 'team_id': '29'},
        'carolina': {'sport': 'football', 'league': 'nfl', 'team_id': '29'},
        'car': {'sport': 'football', 'league': 'nfl', 'team_id': '29'},
        'patriots': {'sport': 'football', 'league': 'nfl', 'team_id': '17'},
        'new england': {'sport': 'football', 'league': 'nfl', 'team_id': '17'},
        'ne': {'sport': 'football', 'league': 'nfl', 'team_id': '17'},
        'raiders': {'sport': 'football', 'league': 'nfl', 'team_id': '13'},
        'las vegas': {'sport': 'football', 'league': 'nfl', 'team_id': '13'},
        'lv': {'sport': 'football', 'league': 'nfl', 'team_id': '13'},
        'rams': {'sport': 'football', 'league': 'nfl', 'team_id': '14'},
        'lar': {'sport': 'football', 'league': 'nfl', 'team_id': '14'},
        'ravens': {'sport': 'football', 'league': 'nfl', 'team_id': '33'},
        'baltimore': {'sport': 'football', 'league': 'nfl', 'team_id': '33'},
        'bal': {'sport': 'football', 'league': 'nfl', 'team_id': '33'},
        'saints': {'sport': 'football', 'league': 'nfl', 'team_id': '18'},
        'new orleans': {'sport': 'football', 'league': 'nfl', 'team_id': '18'},
        'no': {'sport': 'football', 'league': 'nfl', 'team_id': '18'},
        'steelers': {'sport': 'football', 'league': 'nfl', 'team_id': '23'},
        'pittsburgh': {'sport': 'football', 'league': 'nfl', 'team_id': '23'},
        'pit': {'sport': 'football', 'league': 'nfl', 'team_id': '23'},
        'texans': {'sport': 'football', 'league': 'nfl', 'team_id': '34'},
        'houston': {'sport': 'football', 'league': 'nfl', 'team_id': '34'},
        'hou': {'sport': 'football', 'league': 'nfl', 'team_id': '34'},
        'titans': {'sport': 'football', 'league': 'nfl', 'team_id': '10'},
        'tennessee': {'sport': 'football', 'league': 'nfl', 'team_id': '10'},
        'ten': {'sport': 'football', 'league': 'nfl', 'team_id': '10'},
        'vikings': {'sport': 'football', 'league': 'nfl', 'team_id': '16'},
        'minnesota': {'sport': 'football', 'league': 'nfl', 'team_id': '16'},
        'min': {'sport': 'football', 'league': 'nfl', 'team_id': '16'},
        
        # MLB Teams
        'mariners': {'sport': 'baseball', 'league': 'mlb', 'team_id': '12'},
        'seattle': {'sport': 'baseball', 'league': 'mlb', 'team_id': '12'},
        'sea': {'sport': 'baseball', 'league': 'mlb', 'team_id': '12'},
        'angels': {'sport': 'baseball', 'league': 'mlb', 'team_id': '3'},
        'laa': {'sport': 'baseball', 'league': 'mlb', 'team_id': '3'},
        'astros': {'sport': 'baseball', 'league': 'mlb', 'team_id': '18'},
        'houston': {'sport': 'baseball', 'league': 'mlb', 'team_id': '18'},
        'hou': {'sport': 'baseball', 'league': 'mlb', 'team_id': '18'},
        'athletics': {'sport': 'baseball', 'league': 'mlb', 'team_id': '11'},
        'a\'s': {'sport': 'baseball', 'league': 'mlb', 'team_id': '11'},
        'oakland': {'sport': 'baseball', 'league': 'mlb', 'team_id': '11'},
        'oak': {'sport': 'baseball', 'league': 'mlb', 'team_id': '11'},
        'blue jays': {'sport': 'baseball', 'league': 'mlb', 'team_id': '14'},
        'toronto': {'sport': 'baseball', 'league': 'mlb', 'team_id': '14'},
        'tor': {'sport': 'baseball', 'league': 'mlb', 'team_id': '14'},
        'braves': {'sport': 'baseball', 'league': 'mlb', 'team_id': '15'},
        'atlanta': {'sport': 'baseball', 'league': 'mlb', 'team_id': '15'},
        'atl': {'sport': 'baseball', 'league': 'mlb', 'team_id': '15'},
        'brewers': {'sport': 'baseball', 'league': 'mlb', 'team_id': '8'},
        'milwaukee': {'sport': 'baseball', 'league': 'mlb', 'team_id': '8'},
        'mil': {'sport': 'baseball', 'league': 'mlb', 'team_id': '8'},
        'cardinals': {'sport': 'baseball', 'league': 'mlb', 'team_id': '24'},
        'st louis': {'sport': 'baseball', 'league': 'mlb', 'team_id': '24'},
        'stl': {'sport': 'baseball', 'league': 'mlb', 'team_id': '24'},
        'cubs': {'sport': 'baseball', 'league': 'mlb', 'team_id': '16'},
        'chicago': {'sport': 'baseball', 'league': 'mlb', 'team_id': '16'},
        'chc': {'sport': 'baseball', 'league': 'mlb', 'team_id': '16'},
        'diamondbacks': {'sport': 'baseball', 'league': 'mlb', 'team_id': '29'},
        'arizona': {'sport': 'baseball', 'league': 'mlb', 'team_id': '29'},
        'ari': {'sport': 'baseball', 'league': 'mlb', 'team_id': '29'},
        'dodgers': {'sport': 'baseball', 'league': 'mlb', 'team_id': '19'},
        'lad': {'sport': 'baseball', 'league': 'mlb', 'team_id': '19'},
        'giants': {'sport': 'baseball', 'league': 'mlb', 'team_id': '26'},
        'san francisco': {'sport': 'baseball', 'league': 'mlb', 'team_id': '26'},
        'sf': {'sport': 'baseball', 'league': 'mlb', 'team_id': '26'},
        'guardians': {'sport': 'baseball', 'league': 'mlb', 'team_id': '5'},
        'cleveland': {'sport': 'baseball', 'league': 'mlb', 'team_id': '5'},
        'cle': {'sport': 'baseball', 'league': 'mlb', 'team_id': '5'},
        'marlins': {'sport': 'baseball', 'league': 'mlb', 'team_id': '28'},
        'miami': {'sport': 'baseball', 'league': 'mlb', 'team_id': '28'},
        'mia': {'sport': 'baseball', 'league': 'mlb', 'team_id': '28'},
        'mets': {'sport': 'baseball', 'league': 'mlb', 'team_id': '21'},
        'nym': {'sport': 'baseball', 'league': 'mlb', 'team_id': '21'},
        'nationals': {'sport': 'baseball', 'league': 'mlb', 'team_id': '20'},
        'washington': {'sport': 'baseball', 'league': 'mlb', 'team_id': '20'},
        'was': {'sport': 'baseball', 'league': 'mlb', 'team_id': '20'},
        'orioles': {'sport': 'baseball', 'league': 'mlb', 'team_id': '1'},
        'baltimore': {'sport': 'baseball', 'league': 'mlb', 'team_id': '1'},
        'bal': {'sport': 'baseball', 'league': 'mlb', 'team_id': '1'},
        'padres': {'sport': 'baseball', 'league': 'mlb', 'team_id': '25'},
        'san diego': {'sport': 'baseball', 'league': 'mlb', 'team_id': '25'},
        'sd': {'sport': 'baseball', 'league': 'mlb', 'team_id': '25'},
        'phillies': {'sport': 'baseball', 'league': 'mlb', 'team_id': '22'},
        'philadelphia': {'sport': 'baseball', 'league': 'mlb', 'team_id': '22'},
        'phi': {'sport': 'baseball', 'league': 'mlb', 'team_id': '22'},
        'pirates': {'sport': 'baseball', 'league': 'mlb', 'team_id': '23'},
        'pittsburgh': {'sport': 'baseball', 'league': 'mlb', 'team_id': '23'},
        'pit': {'sport': 'baseball', 'league': 'mlb', 'team_id': '23'},
        'rangers': {'sport': 'baseball', 'league': 'mlb', 'team_id': '13'},
        'texas': {'sport': 'baseball', 'league': 'mlb', 'team_id': '13'},
        'tex': {'sport': 'baseball', 'league': 'mlb', 'team_id': '13'},
        'rays': {'sport': 'baseball', 'league': 'mlb', 'team_id': '30'},
        'tampa bay': {'sport': 'baseball', 'league': 'mlb', 'team_id': '30'},
        'tb': {'sport': 'baseball', 'league': 'mlb', 'team_id': '30'},
        'red sox': {'sport': 'baseball', 'league': 'mlb', 'team_id': '2'},
        'boston': {'sport': 'baseball', 'league': 'mlb', 'team_id': '2'},
        'bos': {'sport': 'baseball', 'league': 'mlb', 'team_id': '2'},
        'reds': {'sport': 'baseball', 'league': 'mlb', 'team_id': '17'},
        'cincinnati': {'sport': 'baseball', 'league': 'mlb', 'team_id': '17'},
        'cin': {'sport': 'baseball', 'league': 'mlb', 'team_id': '17'},
        'rockies': {'sport': 'baseball', 'league': 'mlb', 'team_id': '27'},
        'colorado': {'sport': 'baseball', 'league': 'mlb', 'team_id': '27'},
        'col': {'sport': 'baseball', 'league': 'mlb', 'team_id': '27'},
        'royals': {'sport': 'baseball', 'league': 'mlb', 'team_id': '7'},
        'kansas city': {'sport': 'baseball', 'league': 'mlb', 'team_id': '7'},
        'kc': {'sport': 'baseball', 'league': 'mlb', 'team_id': '7'},
        'tigers': {'sport': 'baseball', 'league': 'mlb', 'team_id': '6'},
        'detroit': {'sport': 'baseball', 'league': 'mlb', 'team_id': '6'},
        'det': {'sport': 'baseball', 'league': 'mlb', 'team_id': '6'},
        'twins': {'sport': 'baseball', 'league': 'mlb', 'team_id': '9'},
        'minnesota': {'sport': 'baseball', 'league': 'mlb', 'team_id': '9'},
        'min': {'sport': 'baseball', 'league': 'mlb', 'team_id': '9'},
        'white sox': {'sport': 'baseball', 'league': 'mlb', 'team_id': '4'},
        'chw': {'sport': 'baseball', 'league': 'mlb', 'team_id': '4'},
        'yankees': {'sport': 'baseball', 'league': 'mlb', 'team_id': '10'},
        'new york': {'sport': 'baseball', 'league': 'mlb', 'team_id': '10'},
        'nyy': {'sport': 'baseball', 'league': 'mlb', 'team_id': '10'},
        
        # NBA Teams (limited data available from API)
        'lakers': {'sport': 'basketball', 'league': 'nba', 'team_id': '13'},
        'warriors': {'sport': 'basketball', 'league': 'nba', 'team_id': '9'},
        'celtics': {'sport': 'basketball', 'league': 'nba', 'team_id': '2'},
        'heat': {'sport': 'basketball', 'league': 'nba', 'team_id': '14'},
        '76ers': {'sport': 'basketball', 'league': 'nba', 'team_id': '20'},
        'knicks': {'sport': 'basketball', 'league': 'nba', 'team_id': '18'},
        'pelicans': {'sport': 'basketball', 'league': 'nba', 'team_id': '3'},
        'trail blazers': {'sport': 'basketball', 'league': 'nba', 'team_id': '22'},
        'blazers': {'sport': 'basketball', 'league': 'nba', 'team_id': '22'},
        
        # WNBA Teams
        'storm': {'sport': 'basketball', 'league': 'wnba', 'team_id': '14'},
        'seattle storm': {'sport': 'basketball', 'league': 'wnba', 'team_id': '14'},
        'liberty': {'sport': 'basketball', 'league': 'wnba', 'team_id': '9'},
        'new york liberty': {'sport': 'basketball', 'league': 'wnba', 'team_id': '9'},
        'sparks': {'sport': 'basketball', 'league': 'wnba', 'team_id': '6'},
        'los angeles sparks': {'sport': 'basketball', 'league': 'wnba', 'team_id': '6'},
        'sky': {'sport': 'basketball', 'league': 'wnba', 'team_id': '19'},
        'chicago sky': {'sport': 'basketball', 'league': 'wnba', 'team_id': '19'},
        'dream': {'sport': 'basketball', 'league': 'wnba', 'team_id': '20'},
        'atlanta dream': {'sport': 'basketball', 'league': 'wnba', 'team_id': '20'},
        'sun': {'sport': 'basketball', 'league': 'wnba', 'team_id': '18'},
        'connecticut sun': {'sport': 'basketball', 'league': 'wnba', 'team_id': '18'},
        'wings': {'sport': 'basketball', 'league': 'wnba', 'team_id': '3'},
        'dallas wings': {'sport': 'basketball', 'league': 'wnba', 'team_id': '3'},
        'valkyries': {'sport': 'basketball', 'league': 'wnba', 'team_id': '129689'},
        'golden state valkyries': {'sport': 'basketball', 'league': 'wnba', 'team_id': '129689'},
        'fever': {'sport': 'basketball', 'league': 'wnba', 'team_id': '5'},
        'indiana fever': {'sport': 'basketball', 'league': 'wnba', 'team_id': '5'},
        'aces': {'sport': 'basketball', 'league': 'wnba', 'team_id': '17'},
        'las vegas aces': {'sport': 'basketball', 'league': 'wnba', 'team_id': '17'},
        'lynx': {'sport': 'basketball', 'league': 'wnba', 'team_id': '8'},
        'minnesota lynx': {'sport': 'basketball', 'league': 'wnba', 'team_id': '8'},
        'mercury': {'sport': 'basketball', 'league': 'wnba', 'team_id': '11'},
        'phoenix mercury': {'sport': 'basketball', 'league': 'wnba', 'team_id': '11'},
        'mystics': {'sport': 'basketball', 'league': 'wnba', 'team_id': '16'},
        'washington mystics': {'sport': 'basketball', 'league': 'wnba', 'team_id': '16'},
        
        # NHL Teams (limited data available from API)
        'kraken': {'sport': 'hockey', 'league': 'nhl', 'team_id': '124292'},
        'seattle kraken': {'sport': 'hockey', 'league': 'nhl', 'team_id': '124292'},
        'blues': {'sport': 'hockey', 'league': 'nhl', 'team_id': '19'},
        'stars': {'sport': 'hockey', 'league': 'nhl', 'team_id': '9'},
        
        # MLS Teams
        'sounders': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9726'},
        'seattle sounders': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9726'},
        
        # NWSL Teams
        'reign': {'sport': 'soccer', 'league': 'usa.nwsl', 'team_id': '15363'},
        'seattle reign': {'sport': 'soccer', 'league': 'usa.nwsl', 'team_id': '15363'},
        'racing': {'sport': 'soccer', 'league': 'usa.nwsl', 'team_id': '20905'},
        'racing louisville': {'sport': 'soccer', 'league': 'usa.nwsl', 'team_id': '20905'},
        'louisville': {'sport': 'soccer', 'league': 'usa.nwsl', 'team_id': '20905'},
        'atlanta united': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '18418'},
        'atl': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '18418'},
        'austin fc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '20906'},
        'atx': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '20906'},
        'cf montreal': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9720'},
        'montreal': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9720'},
        'mtl': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9720'},
        'charlotte fc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '21300'},
        'clt': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '21300'},
        'chicago fire': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '182'},
        'fire': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '182'},
        'chi': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '182'},
        'rapids': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '184'},
        'colorado': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '184'},
        'col': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '184'},
        'crew': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '183'},
        'columbus': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '183'},
        'clb': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '183'},
        'dc united': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '193'},
        'dc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '193'},
        'fc cincinnati': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '18267'},
        'cincinnati': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '18267'},
        'cin': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '18267'},
        'fc dallas': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '185'},
        'dallas': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '185'},
        'dal': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '185'},
        'dynamo': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '6077'},
        'houston': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '6077'},
        'hou': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '6077'},
        'inter miami': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '20232'},
        'miami': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '20232'},
        'mia': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '20232'},
        'la galaxy': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '187'},
        'galaxy': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '187'},
        'la': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '187'},
        'lafc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '18966'},
        'minnesota united': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '17362'},
        'minnesota': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '17362'},
        'min': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '17362'},
        'nashville sc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '18986'},
        'nashville': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '18986'},
        'nsh': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '18986'},
        'revolution': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '189'},
        'new england': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '189'},
        'ne': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '189'},
        'nyc fc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '17606'},
        'nyc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '17606'},
        'red bulls': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '190'},
        'ny': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '190'},
        'orlando city': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '12011'},
        'orlando': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '12011'},
        'orl': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '12011'},
        'union': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '10739'},
        'philadelphia': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '10739'},
        'phi': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '10739'},
        'timbers': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9723'},
        'portland': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9723'},
        'por': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9723'},
        'real salt lake': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '4771'},
        'salt lake': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '4771'},
        'rsl': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '4771'},
        'san diego fc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '22529'},
        'san diego': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '22529'},
        'sd': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '22529'},
        'earthquakes': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '191'},
        'san jose': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '191'},
        'sj': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '191'},
        'sporting kc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '186'},
        'sporting kansas city': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '186'},
        'skc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '186'},
        'st louis city': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '21812'},
        'st louis': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '21812'},
        'stl': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '21812'},
        'toronto fc': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '7318'},
        'toronto': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '7318'},
        'tor': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '7318'},
        'whitecaps': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9727'},
        'vancouver': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9727'},
        'van': {'sport': 'soccer', 'league': 'usa.1', 'team_id': '9727'},
        
        # Premier League Teams
        'lfc': {'sport': 'soccer', 'league': 'eng.1', 'team_id': '364'},
        'liverpool': {'sport': 'soccer', 'league': 'eng.1', 'team_id': '364'},
        'manchester united': {'sport': 'soccer', 'league': 'eng.1', 'team_id': '360'},
        'man united': {'sport': 'soccer', 'league': 'eng.1', 'team_id': '360'},
        'arsenal': {'sport': 'soccer', 'league': 'eng.1', 'team_id': '359'},
        'chelsea': {'sport': 'soccer', 'league': 'eng.1', 'team_id': '363'},
        'manchester city': {'sport': 'soccer', 'league': 'eng.1', 'team_id': '382'},
        'man city': {'sport': 'soccer', 'league': 'eng.1', 'team_id': '382'},
    }
    
    def __init__(self, bot):
        super().__init__(bot)
        self.url_timeout = 10  # seconds
        
        # Per-user cooldown tracking
        self.user_cooldowns = {}  # user_id -> last_execution_time
        
        # Load default teams from config
        self.default_teams = self.load_default_teams()
        # Note: allowed_channels is now loaded by BaseCommand from config
        # Keep sports_channels for backward compatibility (used in execute() for channel-specific team defaults)
        self.sports_channels = self.load_sports_channels()
        self.channel_overrides = self.load_channel_overrides()
        
    def load_default_teams(self) -> List[str]:
        """Load default teams from config"""
        teams_str = self.get_config_value('Sports_Command', 'teams', fallback='seahawks,mariners,sounders,kraken', value_type='str')
        return [team.strip().lower() for team in teams_str.split(',') if team.strip()]
    
    def load_sports_channels(self) -> List[str]:
        """Load sports channels from config"""
        channels_str = self.get_config_value('Sports_Command', 'channels', fallback='', value_type='str')
        return [channel.strip() for channel in channels_str.split(',') if channel.strip()]
    
    def load_channel_overrides(self) -> Dict[str, str]:
        """Load channel overrides from config"""
        overrides_str = self.get_config_value('Sports_Command', 'channel_override', fallback='', value_type='str')
        overrides = {}
        if overrides_str:
            for override in overrides_str.split(','):
                if '=' in override:
                    channel, team = override.strip().split('=', 1)
                    overrides[channel.strip()] = team.strip().lower()
        return overrides
    
    def is_womens_league(self, sport: str, league: str) -> bool:
        """Check if the league is a women's league"""
        womens_leagues = {
            ('basketball', 'wnba'),
            ('soccer', 'usa.nwsl')
        }
        return (sport, league) in womens_leagues
    
    def get_team_abbreviation(self, team_id: str, team_abbreviation: str, sport: str, league: str) -> str:
        """Get team abbreviation, using -W suffix only for women's leagues"""
        if self.is_womens_league(sport, league):
            return self.WOMENS_TEAM_ABBREVIATIONS.get(team_id, team_abbreviation)
        else:
            return team_abbreviation
    
    def extract_score(self, competitor: Dict) -> str:
        """Extract score value from competitor data, handling both dict and string formats
        
        ESPN API returns scores in different formats:
        - Schedule endpoint: {'value': 13.0, 'displayValue': '13'}
        - Scoreboard endpoint: may be string or dict format
        
        Returns the score as a string for consistent formatting.
        """
        score = competitor.get('score', '0')
        
        # Handle dictionary format (from schedule endpoint)
        if isinstance(score, dict):
            # Prefer displayValue if available, otherwise use value
            if 'displayValue' in score:
                return str(score['displayValue'])
            elif 'value' in score:
                # Convert float to int if it's a whole number, otherwise keep as is
                value = score['value']
                if isinstance(value, float) and value.is_integer():
                    return str(int(value))
                return str(value)
            else:
                return '0'
        
        # Handle string format (from scoreboard endpoint or already processed)
        if isinstance(score, str):
            return score
        
        # Handle numeric format
        if isinstance(score, (int, float)):
            if isinstance(score, float) and score.is_integer():
                return str(int(score))
            return str(score)
        
        # Fallback
        return '0'
    
    def extract_shootout_score(self, competitor: Dict) -> Optional[int]:
        """Extract penalty shootout score from competitor data"""
        score = competitor.get('score', {})
        if isinstance(score, dict) and 'shootoutScore' in score:
            shootout = score['shootoutScore']
            if isinstance(shootout, (int, float)):
                return int(shootout) if isinstance(shootout, float) and shootout.is_integer() else int(shootout)
        return None
    
    def format_clean_date_time(self, dt) -> str:
        """Format date and time without leading zeros"""
        month = dt.month
        day = dt.day
        minute = dt.minute
        ampm = dt.strftime("%p")
        
        # Convert to 12-hour format
        hour_12 = dt.hour
        if hour_12 == 0:
            hour_12 = 12
        elif hour_12 > 12:
            hour_12 = hour_12 - 12
        
        # Remove leading zeros
        time_str = f"{month}/{day} {hour_12}:{minute:02d} {ampm}"
        return time_str
    
    def format_clean_date(self, dt) -> str:
        """Format date without leading zeros"""
        month = dt.month
        day = dt.day
        return f"{month}/{day}"
    
    def matches_keyword(self, message: MeshMessage) -> bool:
        """Check if this command matches the message content - sports must be first word"""
        if not self.keywords:
            return False
        
        # Strip exclamation mark if present (for command-style messages)
        content = message.content.strip()
        if content.startswith('!'):
            content = content[1:].strip()
        
        # Split into words and check if first word matches any keyword
        words = content.split()
        if not words:
            return False
        
        first_word = words[0].lower()
        
        for keyword in self.keywords:
            if first_word == keyword.lower():
                return True
        
        return False
    
    def can_execute(self, message: MeshMessage) -> bool:
        """Check if this command can execute with the given message"""
        # Check if sports command is enabled
        sports_enabled = self.get_config_value('Sports_Command', 'sports_enabled', fallback=True, value_type='bool')
        if not sports_enabled:
            return False
        
        # Channel access is now handled by BaseCommand.is_channel_allowed()
        # Call parent can_execute() which includes channel checking
        if not super().can_execute(message):
            return False
        
        # Check per-user cooldown (don't set it here, just check)
        if self.cooldown_seconds > 0:
            import time
            current_time = time.time()
            user_id = message.sender_id or "unknown"
            
            if user_id in self.user_cooldowns:
                time_since_last = current_time - self.user_cooldowns[user_id]
                if time_since_last < self.cooldown_seconds:
                    remaining = self.cooldown_seconds - time_since_last
                    self.logger.info(f"Sports command cooldown active for user {user_id}, {remaining:.1f}s remaining")
                    return False
        
        return True
    
    def get_help_text(self) -> str:
        return self.translate('commands.sports.help')
    
    async def execute(self, message: MeshMessage) -> bool:
        """Execute the sports command"""
        try:
            # Set cooldown for this user
            if self.cooldown_seconds > 0:
                import time
                current_time = time.time()
                user_id = message.sender_id or "unknown"
                self.user_cooldowns[user_id] = current_time
            
            # Parse the command
            content = message.content.strip()
            if content.startswith('!'):
                content = content[1:].strip()
            
            # Extract team name if provided
            parts = content.split()
            if len(parts) > 1:
                team_name = ' '.join(parts[1:]).lower()
                response = await self.get_team_scores(team_name)
            else:
                # Check if this channel has an override team
                if not message.is_dm and message.channel in self.channel_overrides:
                    override_team = self.channel_overrides[message.channel]
                    response = await self.get_team_scores(override_team)
                else:
                    response = await self.get_default_teams_scores()
            
            # Send response
            return await self.send_response(message, response)
            
        except Exception as e:
            self.logger.error(f"Error in sports command: {e}")
            return await self.send_response(message, self.translate('commands.sports.error_fetching'))
    
    async def get_default_teams_scores(self) -> str:
        """Get scores for default teams, sorted by game time"""
        if not self.default_teams:
            return self.translate('commands.sports.no_default_teams')
        
        game_data = []
        for team in self.default_teams:
            try:
                team_info = self.TEAM_MAPPINGS.get(team)
                if team_info:
                    game_info = await self.fetch_team_game_data(team_info)
                    if game_info:
                        game_data.append(game_info)
            except Exception as e:
                self.logger.warning(f"Error fetching score for {team}: {e}")
        
        if not game_data:
            return self.translate('commands.sports.no_games_default')
        
        # Sort by game time (earliest first)
        game_data.sort(key=lambda x: x['timestamp'])
        
        # Format responses with sport emojis
        responses = []
        for game in game_data:
            sport_emoji = self.SPORT_EMOJIS.get(game['sport'], '🏆')
            responses.append(f"{sport_emoji} {game['formatted']}")
        
        # Join responses with newlines and ensure under 130 characters
        result = "\n".join(responses)
        if len(result) > 130:
            # If still too long, truncate the last response
            while len(result) > 130 and len(responses) > 1:
                responses.pop()
                result = "\n".join(responses)
            if len(result) > 130:
                result = result[:127] + "..."
        
        return result
    
    def get_league_info(self, league_name: str) -> Optional[Dict[str, str]]:
        """Get league information for league queries"""
        league_mappings = {
            # NFL
            'nfl': {'sport': 'football', 'league': 'nfl'},
            'football': {'sport': 'football', 'league': 'nfl'},
            
            # MLB
            'mlb': {'sport': 'baseball', 'league': 'mlb'},
            'baseball': {'sport': 'baseball', 'league': 'mlb'},
            
            # NBA
            'nba': {'sport': 'basketball', 'league': 'nba'},
            'basketball': {'sport': 'basketball', 'league': 'nba'},
            
            # WNBA
            'wnba': {'sport': 'basketball', 'league': 'wnba'},
            'womens basketball': {'sport': 'basketball', 'league': 'wnba'},
            'womens': {'sport': 'basketball', 'league': 'wnba'},
            
            # NHL
            'nhl': {'sport': 'hockey', 'league': 'nhl'},
            'hockey': {'sport': 'hockey', 'league': 'nhl'},
            
            # MLS
            'mls': {'sport': 'soccer', 'league': 'usa.1'},
            'soccer': {'sport': 'soccer', 'league': 'usa.1'},
            
            # NWSL
            'nwsl': {'sport': 'soccer', 'league': 'usa.nwsl'},
            'womens soccer': {'sport': 'soccer', 'league': 'usa.nwsl'},
            'womens': {'sport': 'soccer', 'league': 'usa.nwsl'},
            
            # Premier League
            'epl': {'sport': 'soccer', 'league': 'eng.1'},
            'premier league': {'sport': 'soccer', 'league': 'eng.1'},
            'premier': {'sport': 'soccer', 'league': 'eng.1'},
        }
        
        return league_mappings.get(league_name.lower())
    
    def get_city_teams(self, city_name: str) -> List[Dict[str, str]]:
        """Get all teams for a given city"""
        city_name_lower = city_name.lower()
        
        # Define city mappings to team names
        city_mappings = {
            'seattle': ['seahawks', 'mariners', 'sounders', 'kraken', 'reign', 'storm'],
            'chicago': ['bears', 'cubs', 'white sox', 'fire', 'sky'],
            'new york': ['giants', 'jets', 'yankees', 'mets', 'knicks', 'nyc fc', 'red bulls', 'liberty'],
            'ny': ['giants', 'jets', 'yankees', 'mets', 'knicks', 'nyc fc', 'red bulls', 'liberty'],
            'los angeles': ['rams', 'dodgers', 'lakers', 'la galaxy', 'lafc', 'sparks'],
            'la': ['rams', 'dodgers', 'lakers', 'la galaxy', 'lafc', 'sparks'],
            'miami': ['dolphins', 'marlins', 'heat', 'inter miami'],
            'boston': ['patriots', 'red sox', 'celtics', 'revolution'],
            'philadelphia': ['eagles', 'phillies', '76ers', 'union'],
            'philadelphia': ['eagles', 'phillies', '76ers', 'union'],
            'atlanta': ['falcons', 'braves', 'hawks', 'atlanta united', 'dream'],
            'houston': ['texans', 'astros', 'dynamo'],
            'dallas': ['cowboys', 'rangers', 'stars', 'fc dallas', 'wings'],
            'denver': ['broncos', 'rockies', 'rapids'],
            'detroit': ['lions', 'tigers', 'pistons'],
            'minnesota': ['vikings', 'twins', 'timberwolves', 'minnesota united', 'lynx'],
            'minneapolis': ['vikings', 'twins', 'timberwolves', 'minnesota united', 'lynx'],
            'cleveland': ['browns', 'guardians', 'cavaliers'],
            'cincinnati': ['bengals', 'reds', 'fc cincinnati'],
            'pittsburgh': ['steelers', 'pirates', 'penguins'],
            'baltimore': ['ravens', 'orioles'],
            'tampa': ['buccaneers', 'rays', 'lightning'],
            'tampa bay': ['buccaneers', 'rays', 'lightning'],
            'kansas city': ['chiefs', 'royals', 'sporting kc'],
            'kc': ['chiefs', 'royals', 'sporting kc'],
            'washington': ['commanders', 'nationals', 'wizards', 'dc united', 'mystics'],
            'dc': ['commanders', 'nationals', 'wizards', 'dc united', 'mystics'],
            'phoenix': ['cardinals', 'diamondbacks', 'suns', 'mercury'],
            'indiana': ['colts', 'pacers', 'fever'],
            'indianapolis': ['colts', 'pacers', 'fever'],
            'las vegas': ['raiders', 'aces', 'golden knights'],
            'connecticut': ['sun'],
            'arizona': ['cardinals', 'diamondbacks', 'coyotes'],
            'golden state': ['warriors', 'valkyries'],
            'san francisco': ['49ers', 'giants', 'warriors', 'earthquakes', 'valkyries'],
            'sf': ['49ers', 'giants', 'warriors', 'earthquakes', 'valkyries'],
            'san diego': ['chargers', 'padres', 'san diego fc'],
            'sd': ['chargers', 'padres', 'san diego fc'],
            'ind': ['colts', 'pacers'],
            'nashville': ['titans', 'predators', 'nashville sc'],
            'tennessee': ['titans', 'predators', 'nashville sc'],
            'ten': ['titans', 'predators', 'nashville sc'],
            'lv': ['raiders', 'golden knights'],
            'louisville': ['racing'],
            'carolina': ['panthers', 'hornets'],
            'charlotte': ['panthers', 'hornets', 'charlotte fc'],
            'new orleans': ['saints', 'pelicans'],
            'no': ['saints', 'pelicans'],
            'green bay': ['packers'],
            'gb': ['packers'],
            'buffalo': ['bills', 'sabres'],
            'buf': ['bills', 'sabres'],
            'milwaukee': ['bucks', 'brewers'],
            'mil': ['bucks', 'brewers'],
            'portland': ['trail blazers', 'timbers'],
            'por': ['trail blazers', 'timbers'],
            'pdx': ['trail blazers', 'timbers'],
            'salt lake': ['jazz', 'real salt lake'],
            'utah': ['jazz', 'real salt lake'],
            'orlando': ['magic', 'orlando city'],
            'orl': ['magic', 'orlando city'],
            'toronto': ['raptors', 'blue jays', 'toronto fc', 'maple leafs'],
            'tor': ['raptors', 'blue jays', 'toronto fc', 'maple leafs'],
            'vancouver': ['canucks', 'whitecaps'],
            'van': ['canucks', 'whitecaps'],
            'montreal': ['canadiens', 'cf montreal'],
            'mtl': ['canadiens', 'cf montreal'],
            'calgary': ['flames'],
            'edmonton': ['oilers'],
            'winnipeg': ['jets'],
            'ottawa': ['senators'],
            'columbus': ['blue jackets', 'crew'],
            'clb': ['blue jackets', 'crew'],
            'st louis': ['blues', 'st louis city'],
            'stl': ['blues', 'st louis city'],
            'colorado': ['avalanche', 'rockies', 'rapids'],
            'col': ['avalanche', 'rockies', 'rapids'],
            'san jose': ['sharks', 'earthquakes'],
            'sj': ['sharks', 'earthquakes'],
            'anaheim': ['ducks', 'angels'],
            'austin': ['austin fc'],
            'atx': ['austin fc'],
        }
        
        # Get team names for this city
        team_names = city_mappings.get(city_name_lower, [])
        if not team_names:
            return []
        
        # Get team info for each team name
        city_teams = []
        for team_name in team_names:
            team_info = self.TEAM_MAPPINGS.get(team_name)
            if team_info:
                city_teams.append(team_info)
        
        return city_teams
    
    async def get_city_scores(self, city_teams: List[Dict[str, str]], city_name: str) -> str:
        """Get scores for all teams in a city"""
        if not city_teams:
            return self.translate('commands.sports.no_teams_city', city=city_name)
        
        game_data = []
        for team_info in city_teams:
            try:
                game_info = await self.fetch_team_game_data(team_info)
                if game_info:
                    game_data.append(game_info)
            except Exception as e:
                self.logger.warning(f"Error fetching score for {team_info}: {e}")
        
        if not game_data:
            return self.translate('commands.sports.no_games_city', city=city_name)
        
        # Sort by game time (earliest first)
        game_data.sort(key=lambda x: x['timestamp'])
        
        # Format responses with sport emojis
        responses = []
        for game in game_data:
            sport_emoji = self.SPORT_EMOJIS.get(game['sport'], '🏆')
            responses.append(f"{sport_emoji} {game['formatted']}")
        
        # Join responses with newlines and ensure under 130 characters
        result = "\n".join(responses)
        if len(result) > 130:
            # If still too long, truncate the last response
            while len(result) > 130 and len(responses) > 1:
                responses.pop()
                result = "\n".join(responses)
            if len(result) > 130:
                result = result[:127] + "..."
        
        return result
    
    async def get_league_scores(self, league_info: Dict[str, str]) -> str:
        """Get upcoming games for a league"""
        try:
            # Construct API URL
            url = f"{self.ESPN_BASE_URL}/{league_info['sport']}/{league_info['league']}/scoreboard"
            
            # Make API request
            response = requests.get(url, timeout=self.url_timeout)
            response.raise_for_status()
            
            data = response.json()
            events = data.get('events', [])
            
            if not events:
                return self.translate('commands.sports.no_games_league', sport=league_info['sport'])
            
            # Parse all games and sort by time
            game_data = []
            for event in events:
                game_info = self.parse_league_game_event(event, league_info['sport'], league_info['league'])
                if game_info:
                    game_data.append(game_info)
            
            if not game_data:
                return self.translate('commands.sports.no_games_league', sport=league_info['sport'])
            
            # Sort by game time (earliest first)
            game_data.sort(key=lambda x: x['timestamp'])
            
            # Format responses with sport emojis
            responses = []
            for game in game_data[:5]:  # Limit to 5 games to keep under 130 chars
                sport_emoji = self.SPORT_EMOJIS.get(game['sport'], '🏆')
                responses.append(f"{sport_emoji} {game['formatted']}")
            
            # Join responses with newlines and ensure under 130 characters
            result = "\n".join(responses)
            if len(result) > 130:
                # If still too long, truncate the last response
                while len(result) > 130 and len(responses) > 1:
                    responses.pop()
                    result = "\n".join(responses)
                if len(result) > 130:
                    result = result[:127] + "..."
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error fetching league scores: {e}")
            return self.translate('commands.sports.error_fetching_league', sport=league_info['sport'])
    
    def parse_league_game_event(self, event: Dict, sport: str, league: str) -> Optional[Dict]:
        """Parse a league game event and return structured data with timestamp for sorting"""
        try:
            competitions = event.get('competitions', [])
            if not competitions:
                return None
            
            competition = competitions[0]
            competitors = competition.get('competitors', [])
            
            if len(competitors) != 2:
                return None
            
            # Extract team info
            team1 = competitors[0]
            team2 = competitors[1]
            
            # Determine home/away teams for all sports
            home_team = team1 if team1.get('homeAway') == 'home' else team2
            away_team = team2 if team1.get('homeAway') == 'home' else team1
            home_team_id = home_team.get('team', {}).get('id', '')
            away_team_id = away_team.get('team', {}).get('id', '')
            home_abbreviation = home_team.get('team', {}).get('abbreviation', 'UNK')
            away_abbreviation = away_team.get('team', {}).get('abbreviation', 'UNK')
            home_name = self.get_team_abbreviation(home_team_id, home_abbreviation, sport, league)
            away_name = self.get_team_abbreviation(away_team_id, away_abbreviation, sport, league)
            home_score = self.extract_score(home_team)
            away_score = self.extract_score(away_team)
            
            # Keep original variables for backward compatibility
            team1_name = away_name  # away team first
            team2_name = home_name  # home team second (gets @ symbol)
            team1_score = away_score
            team2_score = home_score
            
            # Get game status
            # In schedule endpoint, status is in competition, not event
            status = competition.get('status', event.get('status', {}))
            status_type = status.get('type', {})
            status_name = status_type.get('name', 'UNKNOWN')
            
            # Get timestamp for sorting
            date_str = event.get('date', '')
            timestamp = 0  # Default for sorting
            event_timestamp = None
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    event_timestamp = dt.timestamp()
                    timestamp = event_timestamp
                except:
                    pass
            
            # Format based on game status
            if status_name in ['STATUS_IN_PROGRESS', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF']:
                # Game is live - prioritize these (use negative timestamp)
                clock = status.get('displayClock', '')
                period = status.get('period', 0)
                
                # Format period based on sport
                if sport == 'soccer':
                    # For soccer, use displayClock if available (e.g., "90'+5'"), otherwise use half
                    # For soccer, show home team first (traditional soccer format)
                    if clock and clock != '0:00' and clock != "0'":
                        period_str = clock  # Use displayClock directly (e.g., "90'+5'")
                        formatted = f"@{home_name} {home_score}-{away_score} {away_name} ({period_str})"
                    else:
                        period_str = f"{period}H"  # Fallback to half
                        formatted = f"@{home_name} {home_score}-{away_score} {away_name} ({clock} {period_str})"
                elif sport == 'baseball':
                    # Use shortDetail for ongoing baseball games to show top/bottom of inning
                    short_detail = status_type.get('shortDetail', '')
                    if short_detail and ('Top' in short_detail or 'Bottom' in short_detail):
                        period_str = short_detail  # e.g., "Top 14th", "Bottom 9th"
                    else:
                        period_str = f"{period}I"  # Fallback to inning number only
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} ({period_str})"
                elif sport == 'football':
                    period_str = f"Q{period}"  # Quarters
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} ({clock} {period_str})"
                else:
                    period_str = f"P{period}"  # Generic periods
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} ({clock} {period_str})"
                
                timestamp = -1  # Live games first
                
            elif status_name == 'STATUS_SCHEDULED':
                # Game is scheduled
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        time_str = self.format_clean_date_time(local_dt)
                        if sport == 'soccer':
                            formatted = f"@{home_name} vs. {away_name} ({time_str})"
                        else:
                            formatted = f"{away_name} @ {home_name} ({time_str})"
                    except:
                        if sport == 'soccer':
                            formatted = f"@{home_name} vs. {away_name} (TBD)"
                        else:
                            formatted = f"{away_name} @ {home_name} (TBD)"
                        timestamp = 9999999999  # Put TBD games last
                else:
                    if sport == 'soccer':
                        formatted = f"@{home_name} vs. {away_name} (TBD)"
                    else:
                        formatted = f"{away_name} @ {home_name} (TBD)"
                    timestamp = 9999999999  # Put TBD games last
                    
            elif status_name == 'STATUS_HALFTIME':
                # Game is at halftime
                if sport == 'soccer':
                    formatted = f"@{home_name} {home_score}-{away_score} {away_name} (HT)"
                else:
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} (HT)"
                timestamp = -2  # Halftime games second priority after live games
            elif status_name == 'STATUS_FULL_TIME':
                # Soccer game is finished - put these last
                # Check if game was played today or on a different day
                date_suffix = ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        today = datetime.now().date()
                        game_date = local_dt.date()
                        if game_date != today:
                            date_suffix = f", {self.format_clean_date(local_dt)}"
                    except:
                        pass
                formatted = f"@{home_name} {home_score}-{away_score} {away_name} (FT{date_suffix})"
                timestamp = 9999999998  # Final games second to last
            elif status_name == 'STATUS_FINAL_PEN':
                # Soccer game finished in penalty shootout
                # Check if game was played today or on a different day
                date_suffix = ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        today = datetime.now().date()
                        game_date = local_dt.date()
                        if game_date != today:
                            date_suffix = f", {self.format_clean_date(local_dt)}"
                    except:
                        pass
                
                # Get penalty shootout scores
                home_shootout = self.extract_shootout_score(home_team)
                away_shootout = self.extract_shootout_score(away_team)
                
                # Format with penalty shootout result
                if home_shootout is not None and away_shootout is not None:
                    formatted = f"@{home_name} {home_score}-{away_score} {away_name} (FT-PEN {home_shootout}-{away_shootout}{date_suffix})"
                else:
                    formatted = f"@{home_name} {home_score}-{away_score} {away_name} (FT-PEN{date_suffix})"
                
                timestamp = 9999999998  # Final games second to last
            elif status_name == 'STATUS_FINAL':
                # Other sports game is finished - put these last
                # Check if game was played today or on a different day
                date_suffix = ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        today = datetime.now().date()
                        game_date = local_dt.date()
                        if game_date != today:
                            date_suffix = f", {self.format_clean_date(local_dt)}"
                    except:
                        pass
                formatted = f"{away_name} {away_score}-{home_score} @{home_name} (F{date_suffix})"
                timestamp = 9999999998  # Final games second to last
                
            else:
                # Other status
                if sport == 'soccer':
                    formatted = f"@{home_name} {home_score}-{away_score} {away_name} ({status_name})"
                else:
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} ({status_name})"
                timestamp = 9999999997  # Other statuses third to last
            
            return {
                'timestamp': timestamp,
                'event_timestamp': event_timestamp,
                'formatted': formatted,
                'sport': sport,
                'status': status_name
            }
                
        except Exception as e:
            self.logger.error(f"Error parsing league game event: {e}")
            return None
    
    async def get_team_scores(self, team_name: str) -> str:
        """Get scores for a specific team or league"""
        # Check if this is a league query
        league_info = self.get_league_info(team_name)
        if league_info:
            return await self.get_league_scores(league_info)
        
        # Check if this is a city search that should return multiple teams
        city_teams = self.get_city_teams(team_name)
        if city_teams:
            return await self.get_city_scores(city_teams, team_name)
        
        # Otherwise, treat as single team query
        team_info = self.TEAM_MAPPINGS.get(team_name)
        if not team_info:
            return self.translate('commands.sports.team_not_found', team=team_name)
        
        try:
            score_info = await self.fetch_team_score(team_info)
            if score_info:
                # fetch_team_score already includes emojis, so return as-is
                return score_info
            else:
                return self.translate('commands.sports.no_games_team', team=team_name)
        except Exception as e:
            self.logger.error(f"Error fetching score for {team_name}: {e}")
            return self.translate('commands.sports.error_fetching_team', team=team_name)
    
    async def fetch_team_score(self, team_info: Dict[str, str]) -> Optional[str]:
        """Fetch score information for a team - returns current/next game plus past results"""
        games = await self.fetch_team_games(team_info)
        if not games:
            return None
        
        # Format games to fit within message limit (130 characters)
        # Use 125 as a buffer to avoid cutting off mid-game
        sport_emoji = self.SPORT_EMOJIS.get(team_info['sport'], '🏆')
        formatted_games = []
        current_length = 0
        max_length = 125  # Leave buffer to avoid cutoff
        
        for game in games:
            # Ensure game['formatted'] doesn't already have an emoji
            game_formatted = game['formatted'].strip()
            # Remove emoji if it's at the start (some games might have it)
            if game_formatted and game_formatted[0] in self.SPORT_EMOJIS.values():
                game_formatted = game_formatted[1:].strip()
            
            game_str = f"{sport_emoji} {game_formatted}"
            # Check if adding this game would exceed limit
            if formatted_games:
                # Account for newline separator
                test_length = current_length + len("\n") + len(game_str)
            else:
                test_length = len(game_str)
            
            if test_length <= max_length:
                formatted_games.append(game_str)
                current_length = test_length
            else:
                # Can't fit more games - stop before exceeding limit
                break
        
        if not formatted_games:
            # If even the first game doesn't fit, return it anyway (truncated)
            game_formatted = games[0]['formatted'].strip()
            if game_formatted and game_formatted[0] in self.SPORT_EMOJIS.values():
                game_formatted = game_formatted[1:].strip()
            return f"{sport_emoji} {game_formatted[:120]}"
        
        return "\n".join(formatted_games)
    
    async def fetch_team_games(self, team_info: Dict[str, str]) -> List[Dict]:
        """Fetch multiple games for a team: current/next game plus past results
        
        Uses the team schedule endpoint which returns both past and upcoming games
        in a single API call. Returns games sorted by relevance:
        - Live games first
        - Then upcoming games
        - Then recent past games (most recent first)
        """
        try:
            # Use team schedule endpoint - returns both past and upcoming games
            url = f"{self.ESPN_BASE_URL}/{team_info['sport']}/{team_info['league']}/teams/{team_info['team_id']}/schedule"
            
            # Make API request
            response = requests.get(url, timeout=self.url_timeout)
            response.raise_for_status()
            
            data = response.json()
            events = data.get('events', [])
            
            if not events:
                return []
            
            # Parse all games
            all_games = []
            for event in events:
                game_data = self.parse_game_event_with_timestamp(event, team_info['team_id'], team_info['sport'], team_info['league'])
                if game_data:
                    all_games.append(game_data)
            
            if not all_games:
                return []
            
            # Sort by timestamp (negative for live games, then by actual timestamp)
            # This prioritizes: live games > upcoming games > recent past games
            all_games.sort(key=lambda x: x['timestamp'])
            
            # Get current time for comparison
            now = datetime.now(timezone.utc).timestamp()
            
            # Separate into categories
            live_games = [g for g in all_games if g['timestamp'] < 0]  # Negative timestamps = live
            upcoming_games = []
            past_games = []
            
            # Categorize games with positive timestamps
            for game in all_games:
                if game['timestamp'] < 0:
                    continue  # Already in live_games
                
                game_event_ts = game.get('event_timestamp')
                effective_ts = game_event_ts if game_event_ts is not None else game['timestamp']
                
                if game['timestamp'] >= 9999999990 and game_event_ts is None:
                    # No real timestamp available, treat as past
                    past_games.append((effective_ts, game))
                elif effective_ts is None:
                    past_games.append((effective_ts, game))
                elif effective_ts > now:
                    # Future game
                    upcoming_games.append((effective_ts, game))
                else:
                    # Past game
                    past_games.append((effective_ts, game))
            
            # Sort upcoming games by soonest first, past games by most recent first
            upcoming_games.sort(key=lambda x: x[0] if x[0] is not None else float('inf'))
            past_games.sort(key=lambda x: x[0] if x[0] is not None else -float('inf'), reverse=True)
            
            # Build result: live games + next upcoming + recent past
            result = []
            
            # Add live games (if any)
            if live_games:
                result.extend(live_games)
            
            # Add next upcoming game (if no live games)
            if not live_games and upcoming_games:
                result.append(upcoming_games[0][1])
            
            # Add recent past games (most recent first, up to what fits)
            result.extend([g for _, g in past_games])
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error fetching team games: {e}")
            return []
    
    async def fetch_team_game_data(self, team_info: Dict[str, str]) -> Optional[Dict]:
        """Fetch structured game data for a team with timestamp for sorting
        
        Uses the team schedule endpoint which returns both past and upcoming games
        in a single API call, eliminating the need for multiple scoreboard requests.
        Returns only the most relevant game (for backward compatibility).
        """
        games = await self.fetch_team_games(team_info)
        return games[0] if games else None
    
    def parse_game_event_with_timestamp(self, event: Dict, team_id: str, sport: str, league: str) -> Optional[Dict]:
        """Parse a game event and return structured data with timestamp for sorting"""
        try:
            competitions = event.get('competitions', [])
            if not competitions:
                return None
            
            competition = competitions[0]
            competitors = competition.get('competitors', [])
            
            if len(competitors) != 2:
                return None
            
            # Check if our team is in this game
            our_team = None
            other_team = None
            
            for competitor in competitors:
                if competitor.get('team', {}).get('id') == team_id:
                    our_team = competitor
                else:
                    other_team = competitor
            
            if not our_team or not other_team:
                return None
            
            # Determine home/away teams for all sports
            home_team = our_team if our_team.get('homeAway') == 'home' else other_team
            away_team = other_team if our_team.get('homeAway') == 'home' else our_team
            home_team_id = home_team.get('team', {}).get('id', '')
            away_team_id = away_team.get('team', {}).get('id', '')
            home_abbreviation = home_team.get('team', {}).get('abbreviation', 'UNK')
            away_abbreviation = away_team.get('team', {}).get('abbreviation', 'UNK')
            home_name = self.get_team_abbreviation(home_team_id, home_abbreviation, sport, league)
            away_name = self.get_team_abbreviation(away_team_id, away_abbreviation, sport, league)
            home_score = self.extract_score(home_team)
            away_score = self.extract_score(away_team)
            
            # For individual team queries, we still want to show our team first
            # but in the correct home/away order for each sport
            if our_team.get('homeAway') == 'home':
                our_team_name = home_name
                other_team_name = away_name
                our_score = home_score
                other_score = away_score
            else:
                our_team_name = away_name
                other_team_name = home_name
                our_score = away_score
                other_score = home_score
            
            # Get game status
            # In schedule endpoint, status is in competition, not event
            status = competition.get('status', event.get('status', {}))
            status_type = status.get('type', {})
            status_name = status_type.get('name', 'UNKNOWN')
            
            # Get timestamp for sorting
            date_str = event.get('date', '')
            timestamp = 0  # Default for sorting
            event_timestamp = None
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    event_timestamp = dt.timestamp()
                    timestamp = event_timestamp
                except:
                    pass
            
            # Format based on game status
            if status_name in ['STATUS_IN_PROGRESS', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF']:
                # Game is live - prioritize these (use negative timestamp)
                clock = status.get('displayClock', '')
                period = status.get('period', 0)
                
                # Format period based on sport
                if sport == 'soccer':
                    # For soccer, use displayClock if available (e.g., "90'+5'"), otherwise use half
                    # For soccer, show home team first (traditional soccer format)
                    if clock and clock != '0:00' and clock != "0'":
                        period_str = clock  # Use displayClock directly (e.g., "90'+5'")
                        formatted = f"@{home_name} {home_score}-{away_score} {away_name} ({period_str})"
                    else:
                        period_str = f"{period}H"  # Fallback to half
                        formatted = f"@{home_name} {home_score}-{away_score} {away_name} ({clock} {period_str})"
                elif sport == 'baseball':
                    # Use shortDetail for ongoing baseball games to show top/bottom of inning
                    short_detail = status.get('type', {}).get('shortDetail', '')
                    if short_detail and ('Top' in short_detail or 'Bottom' in short_detail):
                        period_str = short_detail  # e.g., "Top 14th", "Bottom 9th"
                    else:
                        period_str = f"{period}I"  # Fallback to inning number only
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} ({period_str})"
                elif sport == 'football':
                    period_str = f"Q{period}"  # Quarters
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} ({clock} {period_str})"
                else:
                    period_str = f"P{period}"  # Generic periods
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} ({clock} {period_str})"
                
                timestamp = -1  # Live games first
                
            elif status_name == 'STATUS_SCHEDULED':
                # Game is scheduled
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        time_str = self.format_clean_date_time(local_dt)
                        if sport == 'soccer':
                            formatted = f"@{home_name} vs. {away_name} ({time_str})"
                        else:
                            formatted = f"{away_name} @ {home_name} ({time_str})"
                    except:
                        if sport == 'soccer':
                            formatted = f"@{home_name} vs. {away_name} (TBD)"
                        else:
                            formatted = f"{away_name} @ {home_name} (TBD)"
                        timestamp = 9999999999  # Put TBD games last
                else:
                    if sport == 'soccer':
                        formatted = f"@{home_name} vs. {away_name} (TBD)"
                    else:
                        formatted = f"{away_name} @ {home_name} (TBD)"
                    timestamp = 9999999999  # Put TBD games last
                    
            elif status_name == 'STATUS_HALFTIME':
                # Game is at halftime
                if sport == 'soccer':
                    formatted = f"@{home_name} {home_score}-{away_score} {away_name} (HT)"
                else:
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} (HT)"
                timestamp = -2  # Halftime games second priority after live games
            elif status_name == 'STATUS_FULL_TIME':
                # Soccer game is finished - put these last
                # Check if game was played today or on a different day
                date_suffix = ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        today = datetime.now().date()
                        game_date = local_dt.date()
                        if game_date != today:
                            date_suffix = f", {self.format_clean_date(local_dt)}"
                    except:
                        pass
                formatted = f"@{home_name} {home_score}-{away_score} {away_name} (FT{date_suffix})"
                timestamp = 9999999998  # Final games second to last
            elif status_name == 'STATUS_FINAL_PEN':
                # Soccer game finished in penalty shootout
                # Check if game was played today or on a different day
                date_suffix = ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        today = datetime.now().date()
                        game_date = local_dt.date()
                        if game_date != today:
                            date_suffix = f", {self.format_clean_date(local_dt)}"
                    except:
                        pass
                
                # Get penalty shootout scores
                home_shootout = self.extract_shootout_score(home_team)
                away_shootout = self.extract_shootout_score(away_team)
                
                # Format with penalty shootout result
                if home_shootout is not None and away_shootout is not None:
                    formatted = f"@{home_name} {home_score}-{away_score} {away_name} (FT-PEN {home_shootout}-{away_shootout}{date_suffix})"
                else:
                    formatted = f"@{home_name} {home_score}-{away_score} {away_name} (FT-PEN{date_suffix})"
                
                timestamp = 9999999998  # Final games second to last
            elif status_name == 'STATUS_FINAL':
                # Other sports game is finished - put these last
                # Check if game was played today or on a different day
                date_suffix = ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        today = datetime.now().date()
                        game_date = local_dt.date()
                        if game_date != today:
                            date_suffix = f", {self.format_clean_date(local_dt)}"
                    except:
                        pass
                formatted = f"{away_name} {away_score}-{home_score} @{home_name} (F{date_suffix})"
                timestamp = 9999999998  # Final games second to last
                
            else:
                # Other status
                if sport == 'soccer':
                    formatted = f"@{home_name} {home_score}-{away_score} {away_name} ({status_name})"
                else:
                    formatted = f"{away_name} {away_score}-{home_score} @{home_name} ({status_name})"
                timestamp = 9999999997  # Other statuses third to last
            
            return {
                'timestamp': timestamp,
                'event_timestamp': event_timestamp,
                'formatted': formatted,
                'sport': sport,
                'status': status_name
            }
                
        except Exception as e:
            self.logger.error(f"Error parsing game event with timestamp: {e}")
            return None

    def parse_game_event(self, event: Dict, team_id: str) -> Optional[str]:
        """Parse a game event and return formatted score info"""
        try:
            competitions = event.get('competitions', [])
            if not competitions:
                return None
            
            competition = competitions[0]
            competitors = competition.get('competitors', [])
            
            if len(competitors) != 2:
                return None
            
            # Check if our team is in this game
            our_team = None
            other_team = None
            
            for competitor in competitors:
                if competitor.get('team', {}).get('id') == team_id:
                    our_team = competitor
                else:
                    other_team = competitor
            
            if not our_team or not other_team:
                return None
            
            # Extract team info
            our_team_name = our_team.get('team', {}).get('abbreviation', 'UNK')
            other_team_name = other_team.get('team', {}).get('abbreviation', 'UNK')
            
            # Determine home/away teams
            our_home_away = our_team.get('homeAway', '')
            other_home_away = other_team.get('homeAway', '')
            
            if our_home_away == 'home':
                home_team_name = our_team_name
                away_team_name = other_team_name
            elif other_home_away == 'home':
                home_team_name = other_team_name
                away_team_name = our_team_name
            else:
                # Fallback if homeAway is not available
                home_team_name = other_team_name
                away_team_name = our_team_name
            
            # Get scores
            our_score = self.extract_score(our_team)
            other_score = self.extract_score(other_team)
            
            # Get game status
            status = event.get('status', {})
            status_type = status.get('type', {})
            status_name = status_type.get('name', 'UNKNOWN')
            
            # Format based on game status
            if status_name in ['STATUS_IN_PROGRESS', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF']:
                # Game is live
                clock = status.get('displayClock', '')
                period = status.get('period', 0)
                
                # Format period based on sport (need to determine sport from team_info)
                # This is a legacy method, so we'll use a generic approach
                if period <= 2:
                    period_str = f"{period}H"  # Likely soccer (halves)
                elif period <= 4:
                    period_str = f"Q{period}"  # Likely football (quarters)
                else:
                    period_str = f"{period}I"  # Likely baseball (innings)
                
                return f"{our_team_name} {our_score}-{other_score} @{other_team_name} ({clock} {period_str})"
            
            elif status_name == 'STATUS_SCHEDULED':
                # Game is scheduled
                date_str = event.get('date', '')
                if date_str:
                    try:
                        # Parse date and format
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        # Convert to local time (assuming Pacific for Seattle teams)
                        local_dt = dt.astimezone()
                        time_str = self.format_clean_date_time(local_dt)
                        return f"{away_team_name} @ {home_team_name} ({time_str})"
                    except:
                        return f"{away_team_name} @ {home_team_name} (TBD)"
                else:
                    return f"{away_team_name} @ {home_team_name} (TBD)"
            
            elif status_name == 'STATUS_HALFTIME':
                # Game is at halftime
                return f"{our_team_name} {our_score}-{other_score} @{other_team_name} (HT)"
            elif status_name == 'STATUS_FULL_TIME':
                # Soccer game is finished
                # Check if game was played today or on a different day
                date_str = event.get('date', '')
                date_suffix = ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        today = datetime.now().date()
                        game_date = local_dt.date()
                        if game_date != today:
                            date_suffix = f", {self.format_clean_date(local_dt)}"
                    except:
                        pass
                return f"{our_team_name} {our_score}-{other_score} @{other_team_name} (FT{date_suffix})"
            elif status_name == 'STATUS_FINAL':
                # Other sports game is finished
                # Check if game was played today or on a different day
                date_str = event.get('date', '')
                date_suffix = ""
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        local_dt = dt.astimezone()
                        today = datetime.now().date()
                        game_date = local_dt.date()
                        if game_date != today:
                            date_suffix = f", {self.format_clean_date(local_dt)}"
                    except:
                        pass
                return f"{our_team_name} {our_score}-{other_score} @{other_team_name} (F{date_suffix})"
            
            else:
                # Other status
                return f"{our_team_name} {our_score}-{other_score} {other_team_name} ({status_name})"
                
        except Exception as e:
            self.logger.error(f"Error parsing game event: {e}")
            return None
