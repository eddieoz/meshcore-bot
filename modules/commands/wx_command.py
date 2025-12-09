#!/usr/bin/env python3
"""
Weather command for the MeshCore Bot
Provides weather information using zip codes and NOAA APIs
"""

import re
import json
import requests
import xml.dom.minidom
from datetime import datetime, timedelta
from geopy.geocoders import Nominatim
from ..utils import rate_limited_nominatim_geocode_sync, rate_limited_nominatim_reverse_sync, get_nominatim_geocoder, geocode_zipcode_sync, geocode_city_sync
import maidenhead as mh
from .base_command import BaseCommand
from ..models import MeshMessage


class WxCommand(BaseCommand):
    """Handles weather commands with zipcode support"""
    
    # Plugin metadata
    name = "wx"
    keywords = ['!wx', '!weather', '!wxa', '!wxalert']
    description = "Get weather information for a zip code (usage: !wx 12345)"
    category = "weather"
    cooldown_seconds = 5  # 5 second cooldown per user to prevent API abuse
    
    # Error constants
    NO_DATA_NOGPS = "No GPS data available"
    ERROR_FETCHING_DATA = "Error fetching weather data"
    NO_ALERTS = "No weather alerts"
    
    def __init__(self, bot):
        super().__init__(bot)
        self.url_timeout = 10  # seconds
        self.forecast_duration = 3  # days
        self.num_wx_alerts = 2  # number of alerts to show
        self.use_metric = False  # Use imperial units by default
        self.zulu_time = False  # Use local time by default
        
        # Per-user cooldown tracking
        self.user_cooldowns = {}  # user_id -> last_execution_time
        
        # Get default state from config for city disambiguation
        self.default_state = self.bot.config.get('Weather', 'default_state', fallback='WA')
        
        # Initialize geocoder (will use rate-limited helpers for actual calls)
        # Keep geolocator for backwards compatibility, but prefer rate-limited helpers
        self.geolocator = get_nominatim_geocoder()
        
        # Get database manager for geocoding cache
        self.db_manager = bot.db_manager
    
    def get_help_text(self) -> str:
        return self.translate('commands.wx.description')
    
    def matches_keyword(self, message: MeshMessage) -> bool:
        """Check if message starts with a weather keyword"""
        content = message.content.strip()
        # if content.startswith('!'):
        #     content = content[1:].strip()
        content_lower = content.lower()
        for keyword in self.keywords:
            if content_lower.startswith(keyword + ' '):
                return True
        return False
    
    def can_execute(self, message: MeshMessage) -> bool:
        """Override cooldown check to be per-user instead of per-command-instance"""
        # Check if command requires DM and message is not DM
        if self.requires_dm and not message.is_dm:
            return False
        
        # Check per-user cooldown
        if self.cooldown_seconds > 0:
            import time
            current_time = time.time()
            user_id = message.sender_id
            
            if user_id in self.user_cooldowns:
                last_execution = self.user_cooldowns[user_id]
                if (current_time - last_execution) < self.cooldown_seconds:
                    return False
        
        return True
    
    def get_remaining_cooldown(self, user_id: str) -> int:
        """Get remaining cooldown time for a specific user"""
        if self.cooldown_seconds <= 0:
            return 0
        
        import time
        current_time = time.time()
        if user_id in self.user_cooldowns:
            last_execution = self.user_cooldowns[user_id]
            elapsed = current_time - last_execution
            remaining = self.cooldown_seconds - elapsed
            return max(0, int(remaining))
        
        return 0
    
    def _record_execution(self, user_id: str):
        """Record the execution time for a specific user"""
        import time
        self.user_cooldowns[user_id] = time.time()
    
    async def execute(self, message: MeshMessage) -> bool:
        """Execute the weather command"""
        content = message.content.strip()
        
        # Parse the command to extract location and forecast type
        # Support formats: "wx 12345", "wx seattle", "wx paris, tx", "weather everett", "wxa bellingham"
        # New formats: "wx 12345 tomorrow", "wx 12345 7", "wx 12345 7day"
        parts = content.split()
        if len(parts) < 2:
            await self.send_response(message, self.translate('commands.wx.usage'))
            return True
        
        # Check for forecast type options: "tomorrow", or a number 2-7
        forecast_type = "default"
        num_days = 7  # Default for multi-day forecast
        location_parts = parts[1:]
        
        # Check last part for forecast type
        if len(location_parts) > 0:
            last_part = location_parts[-1].lower()
            if last_part == "tomorrow":
                forecast_type = "tomorrow"
                location_parts = location_parts[:-1]
            elif last_part == "hourly":
                forecast_type = "hourly"
                location_parts = location_parts[:-1]
            elif last_part.isdigit():
                # Check if it's a number between 2-7
                days = int(last_part)
                if 2 <= days <= 7:
                    forecast_type = "multiday"
                    num_days = days
                    location_parts = location_parts[:-1]
            elif last_part in ["7day", "7-day"]:
                forecast_type = "multiday"
                num_days = 7
                location_parts = location_parts[:-1]
        
        # Join remaining parts to handle "city, state" format
        location = ' '.join(location_parts).strip()
        
        if not location:
            await self.send_response(message, self.translate('commands.wx.usage'))
            return True
        
        # Check if it's a zipcode (5 digits) or city name
        if re.match(r'^\d{5}$', location):
            # It's a zipcode
            location_type = "zipcode"
        else:
            # It's a city name (possibly with state)
            location_type = "city"
        
        try:
            # Record execution for this user
            self._record_execution(message.sender_id)
            
            # Get weather data for the location
            weather_data = await self.get_weather_for_location(location, location_type, forecast_type, num_days)
            
            # Check if we need to send multiple messages
            if isinstance(weather_data, tuple) and weather_data[0] == "multi_message":
                # Send weather data first
                await self.send_response(message, weather_data[1])
                
                # Wait for bot TX rate limiter to allow next message
                import asyncio
                rate_limit = self.bot.config.getfloat('Bot', 'bot_tx_rate_limit_seconds', fallback=1.0)
                # Use a conservative sleep time to avoid rate limiting
                sleep_time = max(rate_limit + 1.0, 2.0)  # At least 2 seconds, or rate_limit + 1 second
                await asyncio.sleep(sleep_time)
                
                # Send the special weather statement
                alert_text = weather_data[2]
                alert_count = weather_data[3]
                await self.send_response(message, f"{alert_count} alerts: {alert_text}")
            elif forecast_type == "multiday":
                # Use message splitting for multi-day forecasts
                await self._send_multiday_forecast(message, weather_data)
            else:
                # Send single message as usual
                await self.send_response(message, weather_data)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error in weather command: {e}")
            await self.send_response(message, self.translate('commands.wx.error', error=str(e)))
            return True
    
    async def get_weather_for_location(self, location: str, location_type: str, forecast_type: str = "default", num_days: int = 7) -> str:
        """Get weather data for a location (zipcode or city)
        
        Args:
            location: The location (zipcode or city name)
            location_type: "zipcode" or "city"
            forecast_type: "default", "tomorrow", "multiday", or "hourly"
            num_days: Number of days for multiday forecast (2-7)
        """
        try:
            # Convert location to lat/lon
            if location_type == "zipcode":
                lat, lon = self.zipcode_to_lat_lon(location)
                if lat is None or lon is None:
                    return self.translate('commands.wx.no_location_zipcode', location=location)
                address_info = None
            else:  # city
                result = self.city_to_lat_lon(location)
                if len(result) == 3:
                    lat, lon, address_info = result
                else:
                    lat, lon = result
                    address_info = None
                
                if lat is None or lon is None:
                    return self.translate('commands.wx.no_location_city', location=location, state=self.default_state)
                
                # Check if the found city is in a different state than default
                actual_city = location
                actual_state = self.default_state
                if address_info:
                    # Try to get the best city name from various address fields
                    actual_city = (address_info.get('city') or 
                                 address_info.get('town') or 
                                 address_info.get('village') or 
                                 address_info.get('hamlet') or 
                                 address_info.get('municipality') or 
                                 location)
                    actual_state = address_info.get('state', self.default_state)
                    # Convert full state name to abbreviation if needed
                    if len(actual_state) > 2:
                        state_abbrev_map = {
                            'Washington': 'WA', 'California': 'CA', 'New York': 'NY', 'Texas': 'TX',
                            'Florida': 'FL', 'Illinois': 'IL', 'Pennsylvania': 'PA', 'Ohio': 'OH',
                            'Georgia': 'GA', 'North Carolina': 'NC', 'Michigan': 'MI', 'New Jersey': 'NJ',
                            'Virginia': 'VA', 'Tennessee': 'TN', 'Indiana': 'IN', 'Arizona': 'AZ',
                            'Massachusetts': 'MA', 'Missouri': 'MO', 'Maryland': 'MD', 'Wisconsin': 'WI',
                            'Colorado': 'CO', 'Minnesota': 'MN', 'South Carolina': 'SC', 'Alabama': 'AL',
                            'Louisiana': 'LA', 'Kentucky': 'KY', 'Oregon': 'OR', 'Oklahoma': 'OK',
                            'Connecticut': 'CT', 'Utah': 'UT', 'Iowa': 'IA', 'Nevada': 'NV',
                            'Arkansas': 'AR', 'Mississippi': 'MS', 'Kansas': 'KS', 'New Mexico': 'NM',
                            'Nebraska': 'NE', 'West Virginia': 'WV', 'Idaho': 'ID', 'Hawaii': 'HI',
                            'New Hampshire': 'NH', 'Maine': 'ME', 'Montana': 'MT', 'Rhode Island': 'RI',
                            'Delaware': 'DE', 'South Dakota': 'SD', 'North Dakota': 'ND', 'Alaska': 'AK',
                            'Vermont': 'VT', 'Wyoming': 'WY'
                        }
                        actual_state = state_abbrev_map.get(actual_state, actual_state)
                    
                    # Also check if the default state needs to be converted for comparison
                    default_state_full = self.default_state
                    if len(self.default_state) == 2:
                        # Convert abbreviation to full name for comparison
                        abbrev_to_full_map = {v: k for k, v in state_abbrev_map.items()}
                        default_state_full = abbrev_to_full_map.get(self.default_state, self.default_state)
            
            # Add location info if city is in a different state than default
            location_prefix = ""
            if location_type == "city" and address_info:
                # Compare states (handle both full names and abbreviations)
                states_different = (actual_state != self.default_state and 
                                  actual_state != default_state_full)
                if states_different:
                    location_prefix = f"{actual_city}, {actual_state}: "
            
            # Get weather forecast based on type
            if forecast_type == "tomorrow":
                forecast_periods, points_data = self.get_noaa_weather(lat, lon, return_periods=True)
                if forecast_periods == self.ERROR_FETCHING_DATA:
                    return self.translate('commands.wx.error_fetching')
                weather = self.format_tomorrow_forecast(forecast_periods)
            elif forecast_type == "multiday":
                forecast_periods, points_data = self.get_noaa_weather(lat, lon, return_periods=True)
                if forecast_periods == self.ERROR_FETCHING_DATA:
                    return self.translate('commands.wx.error_fetching')
                weather = self.format_multiday_forecast(forecast_periods, num_days)
            elif forecast_type == "hourly":
                hourly_periods, points_data = self.get_noaa_hourly_weather(lat, lon)
                if hourly_periods == self.ERROR_FETCHING_DATA:
                    return self.translate('commands.wx.error_fetching')
                weather = self.format_hourly_forecast(hourly_periods)
            else:  # default
                weather, points_data = self.get_noaa_weather(lat, lon)
                if weather == self.ERROR_FETCHING_DATA:
                    return self.translate('commands.wx.error_fetching')
                
                # Note: Current conditions are now integrated directly into the current period
                # via _add_period_details() using observation station data
            
            # Get weather alerts (only for default forecast type to avoid cluttering)
            if forecast_type == "default":
                alerts_result = self.get_weather_alerts_noaa(lat, lon)
                if alerts_result == self.ERROR_FETCHING_DATA:
                    alerts_info = None
                elif alerts_result == self.NO_ALERTS:
                    alerts_info = None
                else:
                    full_alert_text, abbreviated_alert_text, alert_count = alerts_result
                    if alert_count > 0:
                        # Always send weather first, then alerts in separate message
                        self.logger.info(f"Found {alert_count} alerts - using two-message mode")
                        return ("multi_message", f"{location_prefix}{weather}", full_alert_text, alert_count)
            
            return f"{location_prefix}{weather}"
            
        except Exception as e:
            self.logger.error(f"Error getting weather for {location_type} {location}: {e}")
            return self.translate('commands.wx.error', error=str(e))
    
    async def get_weather_for_zipcode(self, zipcode: str) -> str:
        """Get weather data for a specific zipcode (legacy method)"""
        return await self.get_weather_for_location(zipcode, "zipcode")
    
    def zipcode_to_lat_lon(self, zipcode: str) -> tuple:
        """Convert zipcode to latitude and longitude"""
        try:
            lat, lon = geocode_zipcode_sync(self.bot, zipcode, timeout=10)
            return lat, lon
        except Exception as e:
            self.logger.error(f"Error geocoding zipcode {zipcode}: {e}")
            return None, None
    
    def city_to_lat_lon(self, city: str) -> tuple:
        """Convert city name to latitude and longitude using default state"""
        try:
            # Use shared geocode_city_sync function with address info
            default_country = self.bot.config.get('Weather', 'default_country', fallback='US')
            lat, lon, address_info = geocode_city_sync(
                self.bot, city, default_state=self.default_state,
                default_country=default_country,
                include_address_info=True, timeout=10
            )
            
            if lat and lon:
                return lat, lon, address_info or {}
            else:
                return None, None, None
        except Exception as e:
            self.logger.error(f"Error geocoding city {city}: {e}")
            return None, None, None
    
    def get_noaa_weather(self, lat: float, lon: float, return_periods: bool = False) -> tuple:
        """Get weather forecast from NOAA and return both weather string and points data
        
        Args:
            lat: Latitude
            lon: Longitude
            return_periods: If True, return forecast periods array instead of formatted string
        
        Returns:
            Tuple of (weather_string_or_periods, points_data)
        """
        try:
            # Round coordinates to 4 decimal places to avoid API redirects
            lat_rounded = round(lat, 4)
            lon_rounded = round(lon, 4)
            
            # Get weather data from NOAA
            weather_api = f"https://api.weather.gov/points/{lat_rounded},{lon_rounded}"
            
            # Get the forecast URL
            weather_data = requests.get(weather_api, timeout=self.url_timeout)
            if not weather_data.ok:
                self.logger.warning("Error fetching weather data from NOAA")
                return self.ERROR_FETCHING_DATA, None
            
            weather_json = weather_data.json()
            forecast_url = weather_json['properties']['forecast']
            
            # Get the forecast
            forecast_data = requests.get(forecast_url, timeout=self.url_timeout)
            if not forecast_data.ok:
                self.logger.warning("Error fetching weather forecast from NOAA")
                return self.ERROR_FETCHING_DATA, None
            
            forecast_json = forecast_data.json()
            forecast = forecast_json['properties']['periods']
            
            # If return_periods is True, return the periods array directly
            if return_periods:
                if not forecast:
                    return self.ERROR_FETCHING_DATA, None
                return forecast, weather_json
            
            # Format the forecast - focus on current conditions and key info
            if not forecast:
                return "No forecast data available", weather_json
            
            current = forecast[0]
            day_name = self.abbreviate_noaa(current['name'])
            temp = current.get('temperature', 'N/A')
            temp_unit = current.get('temperatureUnit', 'F')
            short_forecast = current.get('shortForecast', 'Unknown')
            wind_speed = current.get('windSpeed', '')
            wind_direction = current.get('windDirection', '')
            detailed_forecast = current.get('detailedForecast', '')
            
            # Extract additional useful info from detailed forecast
            humidity = self.extract_humidity(detailed_forecast)
            precip_chance = self.extract_precip_chance(detailed_forecast)
            
            # Create compact but complete weather string with emoji
            weather_emoji = self.get_weather_emoji(short_forecast)
            weather = f"{day_name}: {weather_emoji}{short_forecast} {temp}°{temp_unit}"
            
            # Add wind info if available
            if wind_speed and wind_direction:
                wind_match = re.search(r'(\d+)', wind_speed)
                if wind_match:
                    wind_num = wind_match.group(1)
                    wind_dir = self.abbreviate_wind_direction(wind_direction)
                    if wind_dir:
                        weather += f" {wind_dir}{wind_num}"
            
            # PRIORITIZE: Add all available details to current period first
            # Get observation station data for more accurate current conditions
            observation_data = self.get_observation_data(weather_json)
            
            # Use most of the 130 char limit (120 chars) to ensure current period gets full details
            # Additional periods will only be added if there's remaining space
            # Pass observation_data to use real-time station data instead of parsing from text
            weather = self._add_period_details(weather, detailed_forecast, 0, max_length=120, observation_data=observation_data)
            
            # Also add precipitation chance if available (not in helper function)
            if precip_chance and self._count_display_width(weather) < 120:
                weather += f" 🌦️{precip_chance}%"
            
            # Also add UV index if available (not in helper function)
            uv_index = self.extract_uv_index(detailed_forecast)
            if uv_index and self._count_display_width(weather) < 120:
                weather += f" UV{uv_index}"
            
            # Add next period (Today, Tonight) and Tomorrow if available
            # First, find Today, Tonight, and Tomorrow periods
            today_period = None
            tonight_period = None
            tomorrow_period = None
            current_period_name = current.get('name', '').lower()
            is_current_tonight = 'tonight' in current_period_name
            is_current_night = any(word in current_period_name for word in ['tonight', 'overnight', 'night'])
            
            # Check if current period is a night period (Overnight, Tonight, etc.)
            # If so, we should prioritize showing the upcoming daytime period (Today)
            for i, period in enumerate(forecast):
                period_name = period.get('name', '').lower()
                # Look for "Today" period (daytime forecast)
                if 'today' in period_name and today_period is None and i > 0:
                    # Make sure it's not a night period
                    if 'night' not in period_name and 'tonight' not in period_name:
                        today_period = (i, period)
                elif 'tonight' in period_name and tonight_period is None:
                    tonight_period = (i, period)
                elif 'tomorrow' in period_name and tomorrow_period is None:
                    tomorrow_period = (i, period)
            
            # If current is a night period and we haven't found Today yet, look for next daytime period
            if is_current_night and not today_period:
                # Look for the next period that's not a night period
                for i, period in enumerate(forecast):
                    if i > 0:  # Skip current period
                        period_name = period.get('name', '').lower()
                        # Look for daytime periods (Today, or day names without "night")
                        if 'today' in period_name and 'night' not in period_name:
                            today_period = (i, period)
                            break
                        # Also check for day names that aren't night periods
                        day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                        if any(day in period_name for day in day_names) and 'night' not in period_name:
                            today_period = (i, period)
                            break
            
            # If current is Tonight and we haven't found Tomorrow yet, look for next day's periods
            if is_current_tonight and not tomorrow_period:
                # Look for periods after Tonight (next day)
                for i, period in enumerate(forecast):
                    if i > 0:  # Skip current period
                        period_name = period.get('name', '').lower()
                        # Look for tomorrow, next day, or day names
                        if any(word in period_name for word in ['tomorrow', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']):
                            tomorrow_period = (i, period)
                            break
            
            # If current is a night period, prioritize adding Today (the upcoming daytime)
            if is_current_night and today_period:
                period = today_period[1]
                period_name = self.abbreviate_noaa(period.get('name', 'Today'))
                period_temp = period.get('temperature', '')
                period_short = period.get('shortForecast', '')
                period_detailed = period.get('detailedForecast', '')
                period_wind_speed = period.get('windSpeed', '')
                period_wind_direction = period.get('windDirection', '')
                
                if period_temp and period_short:
                    # Try to get high/low
                    period_high_low = self.extract_high_low(period_detailed)
                    
                    period_emoji = self.get_weather_emoji(period_short)
                    if period_high_low:
                        period_str = f" | {period_name}: {period_emoji}{period_short} {period_high_low}"
                    else:
                        period_str = f" | {period_name}: {period_emoji}{period_short} {period_temp}°"
                    
                    # Add wind info if space allows (using display width)
                    if period_wind_speed and period_wind_direction:
                        test_str = weather + period_str
                        if self._count_display_width(test_str) < 120:
                            wind_match = re.search(r'(\d+)', period_wind_speed)
                            if wind_match:
                                wind_num = wind_match.group(1)
                                wind_dir = self.abbreviate_wind_direction(period_wind_direction)
                                if wind_dir:
                                    wind_info = f" {wind_dir}{wind_num}"
                                    if self._count_display_width(test_str + wind_info) <= 130:
                                        period_str += wind_info
                    
                    # Add additional details (humidity, dew point, visibility, etc.)
                    # But only if current period isn't too long - prioritize current period details
                    current_weather_len = self._count_display_width(weather)
                    # Only add details to additional periods if current period is under 110 chars
                    # This ensures we prioritize current period details first
                    if current_weather_len < 110:
                        period_str = self._add_period_details(period_str, period_detailed, current_weather_len, max_length=130)
                    
                    # Only add if we have space (using display width)
                    # Be more conservative - only add if current period is reasonable length
                    if current_weather_len < 110 and self._count_display_width(weather + period_str) <= 130:
                        weather += period_str
            
            # Add Tonight if it's the immediate next period (and current is not already Tonight)
            # If we already added Today, we can still add Tonight if it's the next period after Today
            if tonight_period and not is_current_tonight:
                # Only add if it's the immediate next period, or if current is night and we haven't added Today yet
                should_add_tonight = False
                if is_current_night and today_period:
                    # If current is night and we added Today, check if Tonight comes after Today
                    if tonight_period[0] > today_period[0]:
                        should_add_tonight = True
                elif tonight_period[0] == 1:
                    # If current is not night, Tonight should be the immediate next period
                    should_add_tonight = True
                
                if should_add_tonight:
                    period = tonight_period[1]
                    period_name = self.abbreviate_noaa(period.get('name', 'Tonight'))
                    period_temp = period.get('temperature', '')
                    period_short = period.get('shortForecast', '')
                    period_detailed = period.get('detailedForecast', '')
                    period_wind_speed = period.get('windSpeed', '')
                    period_wind_direction = period.get('windDirection', '')
                    
                    if period_temp and period_short:
                        # Try to get high/low
                        period_high_low = self.extract_high_low(period_detailed)
                        
                        period_emoji = self.get_weather_emoji(period_short)
                        if period_high_low:
                            period_str = f" | {period_name}: {period_emoji}{period_short} {period_high_low}"
                        else:
                            period_str = f" | {period_name}: {period_emoji}{period_short} {period_temp}°"
                        
                        # Add wind info if space allows (using display width)
                        if period_wind_speed and period_wind_direction:
                            test_str = weather + period_str
                            if self._count_display_width(test_str) < 120:
                                wind_match = re.search(r'(\d+)', period_wind_speed)
                                if wind_match:
                                    wind_num = wind_match.group(1)
                                    wind_dir = self.abbreviate_wind_direction(period_wind_direction)
                                    if wind_dir:
                                        wind_info = f" {wind_dir}{wind_num}"
                                        if self._count_display_width(test_str + wind_info) <= 130:
                                            period_str += wind_info
                        
                    # Add additional details (humidity, dew point, visibility, etc.)
                    # But only if current period isn't too long - prioritize current period details
                    current_weather_len = self._count_display_width(weather)
                    # Only add details to additional periods if current period is under 110 chars
                    # This ensures we prioritize current period details first
                    if current_weather_len < 110:
                        period_str = self._add_period_details(period_str, period_detailed, current_weather_len, max_length=130)
                    
                    # Only add if we have space (using display width)
                    # Be more conservative - only add if current period is reasonable length
                    if current_weather_len < 110 and self._count_display_width(weather + period_str) <= 130:
                        weather += period_str
            
            # Always try to add Tomorrow if available (especially if current is Tonight)
            # Prioritize adding Tomorrow when current is Tonight to use more of the 130 char limit
            if tomorrow_period:
                period = tomorrow_period[1]
                period_name = self.abbreviate_noaa(period.get('name', 'Tomorrow'))
                period_temp = period.get('temperature', '')
                period_short = period.get('shortForecast', '')
                period_detailed = period.get('detailedForecast', '')
                period_wind_speed = period.get('windSpeed', '')
                period_wind_direction = period.get('windDirection', '')
                
                if period_temp and period_short:
                    # Try to get high/low for tomorrow
                    period_high_low = self.extract_high_low(period_detailed)
                    
                    # Abbreviate forecast text if it's too long (especially when current is a night period)
                    abbreviated_forecast = period_short
                    if (is_current_tonight or is_current_night) and len(period_short) > 20:
                        # Try to shorten forecast text to fit more info
                        # Remove transitional words and keep meaningful conditions
                        words = period_short.split()
                        # Transitional words to skip
                        transitions = {'then', 'and', 'or', 'becoming', 'followed', 'by', 'with'}
                        
                        # If there's a "then" pattern, take first condition and last significant condition
                        if 'then' in words:
                            then_index = words.index('then')
                            # Take first condition (before "then")
                            first_part = words[:then_index]
                            # Take last significant condition (after "then", skip small words)
                            if then_index + 1 < len(words):
                                last_part = [w for w in words[then_index + 1:] if w.lower() not in transitions]
                                # Combine: first condition + last significant condition (max 2 words)
                                if last_part:
                                    abbreviated_forecast = ' '.join(first_part)
                                    if len(last_part) <= 2:
                                        abbreviated_forecast += ' ' + ' '.join(last_part)
                                    else:
                                        # Take last 2 words of the last part
                                        abbreviated_forecast += ' ' + ' '.join(last_part[-2:])
                                else:
                                    abbreviated_forecast = ' '.join(first_part)
                            else:
                                abbreviated_forecast = ' '.join(first_part)
                        else:
                            # Filter out transitional words and take first meaningful words
                            meaningful_words = [w for w in words if w.lower() not in transitions]
                            if len(meaningful_words) > 3:
                                abbreviated_forecast = ' '.join(meaningful_words[:3])
                            else:
                                abbreviated_forecast = ' '.join(meaningful_words)
                    
                    period_emoji = self.get_weather_emoji(period_short)
                    if period_high_low:
                        period_str = f" | {period_name}: {period_emoji}{abbreviated_forecast} {period_high_low}"
                    else:
                        period_str = f" | {period_name}: {period_emoji}{abbreviated_forecast} {period_temp}°"
                    
                    # Add wind info if space allows (using display width)
                    # Be more aggressive about adding wind when current is a night period
                    wind_threshold = 115 if (is_current_tonight or is_current_night) else 120
                    if period_wind_speed and period_wind_direction:
                        test_str = weather + period_str
                        if self._count_display_width(test_str) < wind_threshold:
                            wind_match = re.search(r'(\d+)', period_wind_speed)
                            if wind_match:
                                wind_num = wind_match.group(1)
                                wind_dir = self.abbreviate_wind_direction(period_wind_direction)
                                if wind_dir:
                                    wind_info = f" {wind_dir}{wind_num}"
                                    if self._count_display_width(test_str + wind_info) <= 130:
                                        period_str += wind_info
                    
                    # Add additional details (humidity, dew point, visibility, etc.)
                    # But only if current period isn't too long - prioritize current period details
                    current_weather_len = self._count_display_width(weather)
                    # Only add details to additional periods if current period is under 110 chars
                    # This ensures we prioritize current period details first
                    if current_weather_len < 110:
                        max_chars = 128 if (is_current_tonight or is_current_night) else 130
                        period_str = self._add_period_details(period_str, period_detailed, current_weather_len, max_chars)
                    
                    # Only add if we have space (using display width, prioritize current period)
                    # Be more conservative - only add if current period is reasonable length
                    max_chars = 128 if (is_current_tonight or is_current_night) else 130
                    if current_weather_len < 110 and self._count_display_width(weather + period_str) <= max_chars:
                        weather += period_str
            
            return weather, weather_json
            
        except Exception as e:
            self.logger.error(f"Error fetching NOAA weather: {e}")
            return self.ERROR_FETCHING_DATA, None
    
    def get_noaa_hourly_weather(self, lat: float, lon: float) -> tuple:
        """Get hourly weather forecast from NOAA
        
        Args:
            lat: Latitude
            lon: Longitude
        
        Returns:
            Tuple of (hourly_periods_list, points_data)
        """
        try:
            # Round coordinates to 4 decimal places to avoid API redirects
            lat_rounded = round(lat, 4)
            lon_rounded = round(lon, 4)
            
            # Get weather data from NOAA
            weather_api = f"https://api.weather.gov/points/{lat_rounded},{lon_rounded}"
            
            # Get the forecast URL
            weather_data = requests.get(weather_api, timeout=self.url_timeout)
            if not weather_data.ok:
                self.logger.warning("Error fetching weather data from NOAA")
                return self.ERROR_FETCHING_DATA, None
            
            weather_json = weather_data.json()
            hourly_forecast_url = weather_json['properties'].get('forecastHourly')
            
            if not hourly_forecast_url:
                self.logger.warning("Hourly forecast not available for this location")
                return self.ERROR_FETCHING_DATA, None
            
            # Get the hourly forecast
            hourly_data = requests.get(hourly_forecast_url, timeout=self.url_timeout)
            if not hourly_data.ok:
                self.logger.warning("Error fetching hourly forecast from NOAA")
                return self.ERROR_FETCHING_DATA, None
            
            hourly_json = hourly_data.json()
            hourly_periods = hourly_json['properties']['periods']
            
            if not hourly_periods:
                self.logger.warning("No hourly periods returned from NOAA")
                return self.ERROR_FETCHING_DATA, None
            
            return hourly_periods, weather_json
            
        except Exception as e:
            self.logger.error(f"Error fetching NOAA hourly weather: {e}")
            return self.ERROR_FETCHING_DATA, None
    
    def format_hourly_forecast(self, hourly_periods: list) -> str:
        """Format hourly forecast to fit as many hours as possible in 130 chars
        
        Args:
            hourly_periods: List of hourly forecast periods from NOAA
        
        Returns:
            Formatted string with one hour per line
        """
        try:
            if not hourly_periods:
                return self.translate('commands.wx.hourly_not_available')
            
            lines = []
            current_length = 0
            max_length = 130
            
            # Filter to only future hours
            now = datetime.now()
            future_periods = []
            for period in hourly_periods:
                start_time_str = period.get('startTime', '')
                if start_time_str:
                    try:
                        # Parse ISO format with timezone
                        if 'Z' in start_time_str:
                            start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        else:
                            start_time = datetime.fromisoformat(start_time_str)
                        
                        # Convert to local timezone if needed
                        if start_time.tzinfo:
                            # Make naive for comparison
                            start_time = start_time.replace(tzinfo=None)
                        
                        if start_time > now:
                            future_periods.append(period)
                    except (ValueError, TypeError):
                        # If parsing fails, include it anyway
                        future_periods.append(period)
                else:
                    # If no startTime, include it
                    future_periods.append(period)
            
            if not future_periods:
                return "No future hourly periods available"
            
            # Format each hour
            for period in future_periods:
                start_time_str = period.get('startTime', '')
                temp = period.get('temperature', '')
                temp_unit = period.get('temperatureUnit', 'F')
                short_forecast = period.get('shortForecast', '')
                wind_speed = period.get('windSpeed', '')
                wind_direction = period.get('windDirection', '')
                precip_prob = period.get('probabilityOfPrecipitation', {}).get('value')
                
                # Format time (e.g., "2PM", "10AM")
                time_str = ""
                if start_time_str:
                    try:
                        # Parse ISO format - handle timezone
                        if 'Z' in start_time_str:
                            dt = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        elif '+' in start_time_str or start_time_str.count('-') > 2:
                            # Has timezone info
                            dt = datetime.fromisoformat(start_time_str)
                        else:
                            # No timezone, parse as naive
                            dt = datetime.fromisoformat(start_time_str)
                        
                        # Extract hour (assume it's already in local time or close enough)
                        hour = dt.hour
                        
                        # Format as 12-hour time
                        if hour == 0:
                            time_str = "12AM"
                        elif hour < 12:
                            time_str = f"{hour}AM"
                        elif hour == 12:
                            time_str = "12PM"
                        else:
                            time_str = f"{hour-12}PM"
                    except (ValueError, TypeError):
                        time_str = ""
                
                # Build hour line: "10AM: 🌦️ 26% Chance Light Rain 49° SS5"
                emoji = self.get_weather_emoji(short_forecast)
                
                # Abbreviate forecast if too long
                forecast_short = short_forecast
                if len(forecast_short) > 18:
                    # Take first 2-3 words
                    words = forecast_short.split()
                    if len(words) > 3:
                        forecast_short = ' '.join(words[:3])
                    else:
                        forecast_short = forecast_short[:18]
                
                # Build the line - format: "10AM: 🌦️ 26% Chance Light Rain 49° SS5"
                line_parts = []
                if time_str:
                    line_parts.append(f"{time_str}:")
                
                # Add emoji
                line_parts.append(emoji)
                
                # Add precip probability if > 0% (before forecast text)
                if precip_prob is not None and precip_prob > 0:
                    line_parts.append(f"{precip_prob}%")
                
                # Add forecast text
                line_parts.append(forecast_short)
                
                # Add temperature
                if temp:
                    line_parts.append(f"{temp}°")
                
                # Add wind if available (use compact format)
                if wind_speed and wind_direction:
                    wind_match = re.search(r'(\d+)', wind_speed)
                    if wind_match:
                        wind_num = wind_match.group(1)
                        # Get direction abbreviation (first 1-2 chars)
                        wind_dir_abbrev = wind_direction[:2] if len(wind_direction) >= 2 else wind_direction
                        # Remove any spaces and make uppercase
                        wind_dir_abbrev = wind_dir_abbrev.replace(' ', '').upper()
                        line_parts.append(f"{wind_dir_abbrev}{wind_num}")
                
                line = " ".join(line_parts)
                
                # Check if adding this line would exceed limit
                test_lines = lines + [line]
                test_message = "\n".join(test_lines)
                test_length = self._count_display_width(test_message)
                
                if test_length <= max_length:
                    lines.append(line)
                else:
                    # This line would exceed limit, stop here
                    break
            
            if not lines:
                return "Hourly forecast not available"
            
            return "\n".join(lines)
            
        except Exception as e:
            self.logger.error(f"Error formatting hourly forecast: {e}")
            return f"Error formatting hourly forecast: {str(e)}"
    
    def format_tomorrow_forecast(self, forecast: list) -> str:
        """Format a detailed forecast for tomorrow"""
        try:
            # Find tomorrow's periods
            # NOAA may use "Tomorrow", "Tomorrow Night" or day names like "Tuesday", "Tuesday Night"
            tomorrow_periods = []
            tomorrow_day_name = (datetime.now() + timedelta(days=1)).strftime('%A')
            
            # First, try to find periods with "tomorrow" in the name
            for period in forecast:
                period_name = period.get('name', '').lower()
                if 'tomorrow' in period_name:
                    tomorrow_periods.append(period)
            
            # If not found, look for tomorrow's day name (e.g., "Tuesday", "Tuesday Night")
            if not tomorrow_periods:
                for period in forecast:
                    period_name = period.get('name', '')
                    period_name_lower = period_name.lower()
                    # Check if it contains tomorrow's day name
                    if tomorrow_day_name.lower() in period_name_lower:
                        # Make sure it's not today
                        today_day_name = datetime.now().strftime('%A')
                        if today_day_name.lower() not in period_name_lower:
                            tomorrow_periods.append(period)
            
            # If still not found, find periods after "Tonight" (skip current day periods)
            # This handles cases where NOAA uses generic day names
            if not tomorrow_periods:
                found_tonight = False
                current_day_periods = 0
                for period in forecast:
                    period_name = period.get('name', '').lower()
                    # Count current day periods (Today, This Afternoon, Tonight, This Evening)
                    if any(word in period_name for word in ['today', 'this afternoon', 'this evening', 'tonight']):
                        current_day_periods += 1
                        found_tonight = True
                        continue
                    if found_tonight:
                        # This should be tomorrow's period
                        tomorrow_periods.append(period)
                        # Stop after collecting tomorrow's day and night periods (usually 2)
                        if len(tomorrow_periods) >= 2:
                            break
            
            if not tomorrow_periods:
                return self.translate('commands.wx.tomorrow_not_available')
            
            # Build detailed forecast for tomorrow
            parts = []
            for period in tomorrow_periods:
                period_name = self.abbreviate_noaa(period.get('name', 'Tomorrow'))
                temp = period.get('temperature', '')
                temp_unit = period.get('temperatureUnit', 'F')
                short_forecast = period.get('shortForecast', '')
                detailed_forecast = period.get('detailedForecast', '')
                wind_speed = period.get('windSpeed', '')
                wind_direction = period.get('windDirection', '')
                
                if not temp or not short_forecast:
                    continue
                
                # Create period string
                emoji = self.get_weather_emoji(short_forecast)
                period_str = f"{period_name}: {emoji}{short_forecast} {temp}°{temp_unit}"
                
                # Add wind info
                if wind_speed and wind_direction:
                    wind_match = re.search(r'(\d+)', wind_speed)
                    if wind_match:
                        wind_num = wind_match.group(1)
                        wind_dir = self.abbreviate_wind_direction(wind_direction)
                        if wind_dir:
                            period_str += f" {wind_dir}{wind_num}"
                
                # Try to extract high/low
                high_low = self.extract_high_low(detailed_forecast)
                if high_low and '°' not in period_str.split()[-1]:  # Avoid duplicate temp
                    period_str = period_str.replace(f" {temp}°{temp_unit}", f" {high_low}")
                
                parts.append(period_str)
            
            if not parts:
                return self.translate('commands.wx.tomorrow_not_available')
            
            return " | ".join(parts)
            
        except Exception as e:
            self.logger.error(f"Error formatting tomorrow forecast: {e}")
            return self.translate('commands.wx.tomorrow_error')
    
    def format_multiday_forecast(self, forecast: list, num_days: int = 7) -> str:
        """Format a less detailed multi-day forecast summary"""
        try:
            # Group periods by day
            days = {}
            for period in forecast:
                period_name = period.get('name', '')
                period_name_lower = period_name.lower()
                
                # Skip if it's a time period (Tonight, This Afternoon, etc.) unless it's the only period for that day
                # We want to focus on daily summaries
                if any(word in period_name_lower for word in ['tonight', 'afternoon', 'morning', 'evening']):
                    # Only include if it's a named day (Monday, Tuesday, etc.)
                    day_name = None
                    for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                        if day in period_name_lower:
                            day_name = day.capitalize()
                            break
                    
                    if not day_name:
                        continue
                else:
                    # Extract day name
                    day_name = None
                    for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                        if day in period_name_lower:
                            day_name = day.capitalize()
                            break
                    
                    if not day_name:
                        # Try to extract from "Tomorrow", "Today", etc.
                        if 'tomorrow' in period_name_lower:
                            tomorrow = datetime.now() + timedelta(days=1)
                            day_name = tomorrow.strftime('%A')
                        elif 'today' in period_name_lower:
                            day_name = datetime.now().strftime('%A')
                        else:
                            continue
                
                # Get temperature (prefer high/low if available)
                temp = period.get('temperature', '')
                temp_unit = period.get('temperatureUnit', 'F')
                detailed_forecast = period.get('detailedForecast', '')
                high_low = self.extract_high_low(detailed_forecast)
                
                if high_low:
                    temp_str = high_low
                elif temp:
                    temp_str = f"{temp}°"
                else:
                    continue
                
                # Get short forecast
                short_forecast = period.get('shortForecast', '')
                if not short_forecast:
                    continue
                
                # Store the best period for each day (prefer day periods over night)
                if day_name not in days:
                    days[day_name] = {
                        'temp': temp_str,
                        'forecast': short_forecast,
                        'is_day': 'night' not in period_name_lower and 'tonight' not in period_name_lower
                    }
                else:
                    # Prefer day periods, but update if we have better temp info
                    if 'night' not in period_name_lower and 'tonight' not in period_name_lower:
                        days[day_name] = {
                            'temp': temp_str,
                            'forecast': short_forecast,
                            'is_day': True
                        }
                    elif not days[day_name]['is_day']:
                        # Update night period if we don't have a day period
                        days[day_name]['temp'] = temp_str
                        days[day_name]['forecast'] = short_forecast
            
            if not days:
                return self.translate('commands.wx.multiday_not_available', num_days=num_days)
            
            # Format as compact summary
            parts = []
            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            
            # Get today's day name to start ordering
            today = datetime.now().strftime('%A')
            
            # Reorder days starting from today
            if today in day_order:
                start_idx = day_order.index(today)
                ordered_days = day_order[start_idx:] + day_order[:start_idx]
            else:
                ordered_days = day_order
            
            # Limit to requested number of days
            # Map day names to 1-2 letter abbreviations
            day_abbrev_map = {
                'Monday': 'M',
                'Tuesday': 'T',
                'Wednesday': 'W',
                'Thursday': 'Th',
                'Friday': 'F',
                'Saturday': 'Sa',
                'Sunday': 'Su'
            }
            
            # Collect days up to num_days, starting from tomorrow (skip today)
            days_collected = 0
            for day in ordered_days[1:]:  # Skip today, start from tomorrow
                if days_collected >= num_days:
                    break
                if day in days:
                    day_data = days[day]
                    day_abbrev = day_abbrev_map.get(day, day[:2])  # Use 2-letter abbrev
                    emoji = self.get_weather_emoji(day_data['forecast'])
                    # Abbreviate forecast text
                    forecast_short = self.abbreviate_noaa(day_data['forecast'])
                    # Further shorten if needed to fit on one line (but be less aggressive)
                    if len(forecast_short) > 25:
                        forecast_short = forecast_short[:22] + "..."
                    
                    parts.append(f"{day_abbrev}: {emoji}{forecast_short} {day_data['temp']}")
                    days_collected += 1
            
            if not parts:
                return self.translate('commands.wx.multiday_not_available', num_days=num_days)
            
            # Join with newlines instead of pipes
            result = "\n".join(parts)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error formatting {num_days}-day forecast: {e}")
            return self.translate('commands.wx.multiday_error', num_days=num_days)
    
    def _add_period_details(self, period_str: str, detailed_forecast: str, current_weather_length: int, max_length: int = 130, observation_data: dict = None) -> str:
        """Add additional details (humidity, dew point, visibility, etc.) to a period string
        
        Args:
            period_str: The base period string (e.g., " | Today: ☀️Sunny 75°")
            detailed_forecast: The detailed forecast text to extract info from
            current_weather_length: Current length of the weather string (to check total length)
            max_length: Maximum total length allowed (default 130)
            observation_data: Optional dict with observation station data (humidity, dew_point, visibility, wind_gusts, pressure)
        
        Returns:
            Updated period string with additional details if space allows
        """
        result = period_str
        current_length = current_weather_length + self._count_display_width(result)
        
        # Extract additional details - prefer observation data if available (more accurate)
        if observation_data:
            humidity = observation_data.get('humidity')
            dew_point = observation_data.get('dew_point')
            visibility = observation_data.get('visibility')
            wind_gusts = observation_data.get('wind_gusts')
            pressure = observation_data.get('pressure')
        else:
            humidity = None
            dew_point = None
            visibility = None
            wind_gusts = None
            pressure = None
        
        # Fall back to parsing from detailed forecast if observation data not available
        if not humidity:
            humidity = self.extract_humidity(detailed_forecast)
        if not dew_point:
            dew_point = self.extract_dew_point(detailed_forecast)
        if not visibility:
            visibility = self.extract_visibility(detailed_forecast)
        if not wind_gusts:
            wind_gusts = self.extract_wind_gusts(detailed_forecast)
        if not pressure:
            pressure = self.extract_pressure(detailed_forecast)
        
        # Always try to get precip_prob from detailed forecast (not in observation data)
        precip_prob = self.extract_precip_probability(detailed_forecast)
        
        # Add humidity if available and space allows
        # Try to add all available details, only skip if they would exceed max_length
        if humidity:
            humidity_str = f" {humidity}%RH"
            if self._count_display_width(result + humidity_str) + current_weather_length <= max_length:
                result += humidity_str
                current_length = current_weather_length + self._count_display_width(result)
        
        # Add dew point if available and space allows
        if dew_point:
            dew_str = f" 💧{dew_point}°"
            if self._count_display_width(result + dew_str) + current_weather_length <= max_length:
                result += dew_str
                current_length = current_weather_length + self._count_display_width(result)
        
        # Add visibility if available and space allows
        if visibility:
            vis_str = f" 👁️{visibility}mi"
            if self._count_display_width(result + vis_str) + current_weather_length <= max_length:
                result += vis_str
                current_length = current_weather_length + self._count_display_width(result)
        
        # Add precipitation probability if available and space allows
        if precip_prob:
            precip_str = f" 🌦️{precip_prob}%"
            if self._count_display_width(result + precip_str) + current_weather_length <= max_length:
                result += precip_str
                current_length = current_weather_length + self._count_display_width(result)
        
        # Add wind gusts if available and space allows
        if wind_gusts:
            gust_str = f" 💨{wind_gusts}"
            if self._count_display_width(result + gust_str) + current_weather_length <= max_length:
                result += gust_str
                current_length = current_weather_length + self._count_display_width(result)
        
        # Add pressure if available and space allows
        if pressure:
            pressure_str = f" 📊{pressure}hPa"
            if self._count_display_width(result + pressure_str) + current_weather_length <= max_length:
                result += pressure_str
        
        return result
    
    def _count_display_width(self, text: str) -> int:
        """Count display width of text, accounting for emojis which may take 2 display units"""
        # Count regular characters
        width = len(text)
        # Emojis typically take 2 display units in terminals/clients
        # Count emoji characters (basic emoji pattern)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002702-\U000027B0"  # dingbats
            "\U000024C2-\U0001F251"  # enclosed characters
            "]+",
            flags=re.UNICODE
        )
        emoji_matches = emoji_pattern.findall(text)
        # Each emoji sequence adds 1 extra width unit (since len() already counts it as 1)
        # So we add 1 for each emoji sequence to account for display width
        width += len(emoji_matches)
        return width
    
    async def _send_multiday_forecast(self, message: MeshMessage, forecast_text: str):
        """Send multi-day forecast response, splitting into multiple messages if needed"""
        import asyncio
        
        lines = forecast_text.split('\n')
        
        # Remove empty lines
        lines = [line.strip() for line in lines if line.strip()]
        
        if not lines:
            return
        
        # If single line and under 130 chars, send as-is
        if self._count_display_width(forecast_text) <= 130:
            await self.send_response(message, forecast_text)
            return
        
        # Multi-line message - try to fit as many days as possible in one message
        # Only split when necessary (message would exceed 130 chars)
        current_message = ""
        message_count = 0
        
        for i, line in enumerate(lines):
            if not line:
                continue
            
            # Check if adding this line would exceed 130 characters (using display width)
            if current_message:
                test_message = current_message + "\n" + line
            else:
                test_message = line
            
            # Only split if message would exceed 130 chars (using display width)
            if self._count_display_width(test_message) > 130:
                # Send current message and start new one
                if current_message:
                    await self.send_response(message, current_message)
                    message_count += 1
                    # Wait between messages (same as other commands)
                    if i < len(lines):
                        await asyncio.sleep(2.0)
                    
                    current_message = line
                else:
                    # Single line is too long, send it anyway (will be truncated by bot)
                    await self.send_response(message, line)
                    message_count += 1
                    if i < len(lines) - 1:
                        await asyncio.sleep(2.0)
                    current_message = ""
            else:
                # Add line to current message (fits within 130 chars)
                if current_message:
                    current_message += "\n" + line
                else:
                    current_message = line
        
        # Send the last message if there's content
        if current_message:
            await self.send_response(message, current_message)
    
    def get_weather_alerts_noaa(self, lat: float, lon: float) -> tuple:
        """Get weather alerts from NOAA"""
        try:
            # Round coordinates to 4 decimal places to avoid API redirects
            lat_rounded = round(lat, 4)
            lon_rounded = round(lon, 4)
            
            alert_url = f"https://api.weather.gov/alerts/active.atom?point={lat_rounded},{lon_rounded}"
            
            alert_data = requests.get(alert_url, timeout=self.url_timeout)
            if not alert_data.ok:
                self.logger.warning("Error fetching weather alerts from NOAA")
                return self.ERROR_FETCHING_DATA
            
            full_alert_titles = []  # Store original full titles
            abbreviated_alert_titles = []  # Store abbreviated titles for single message mode
            alertxml = xml.dom.minidom.parseString(alert_data.text)
            
            for i in alertxml.getElementsByTagName("entry"):
                title = i.getElementsByTagName("title")[0].childNodes[0].nodeValue
                full_alert_titles.append(title)
                
                # Abbreviate alert title for brevity (for single message mode)
                short_title = self.abbreviate_alert_title(title)
                abbreviated_alert_titles.append(short_title)
            
            if not full_alert_titles:
                return self.NO_ALERTS
            
            alert_num = len(full_alert_titles)
            
            # For multi-message, we need the full first alert title
            full_first_alert_text = full_alert_titles[0]
            
            # For single message, we need the abbreviated first alert title, further abbreviated by abbreviate_noaa
            abbreviated_first_alert_text = self.abbreviate_noaa(abbreviated_alert_titles[0])
            
            # Return both full and abbreviated versions, along with count
            return full_first_alert_text, abbreviated_first_alert_text, alert_num
            
        except Exception as e:
            self.logger.error(f"Error fetching NOAA weather alerts: {e}")
            return self.ERROR_FETCHING_DATA
    
    
    def abbreviate_alert_title(self, title: str) -> str:
        """Abbreviate alert title for brevity"""
        # Common alert type abbreviations
        replacements = {
            "warning": "Warn",
            "watch": "Watch", 
            "advisory": "Adv",
            "statement": "Stmt",
            "severe thunderstorm": "SvrT-Storm",
            "tornado": "Tornado",
            "flash flood": "FlashFlood",
            "flood": "Flood",
            "winter storm": "WinterStorm",
            "blizzard": "Blizzard",
            "ice storm": "IceStorm",
            "freeze": "Freeze",
            "frost": "Frost",
            "heat": "Heat",
            "excessive heat": "ExHeat",
            "extreme heat": "ExtHeat",
            "wind": "Wind",
            "high wind": "HighWind",
            "wind advisory": "WindAdv",
            "fire weather": "FireWx",
            "red flag": "RedFlag",
            "dense fog": "DenseFog",
            "issued": "iss",
            "until": "til",
            "effective": "eff",
            "expires": "exp",
            "dense smoke": "DenseSmoke",
            "air quality": "AirQuality",
            "coastal flood": "CoastalFlood",
            "lakeshore flood": "LakeshoreFlood",
            "rip current": "RipCurrent",
            "high surf": "HighSurf",
            "hurricane": "Hurricane",
            "tropical storm": "TropStorm",
            "tropical depression": "TropDep",
            "storm surge": "StormSurge",
            "tsunami": "Tsunami",
            "earthquake": "Earthquake",
            "volcano": "Volcano",
            "avalanche": "Avalanche",
            "landslide": "Landslide",
            "debris flow": "DebrisFlow",
            "dust storm": "DustStorm",
            "sandstorm": "Sandstorm",
            "blowing dust": "BlwDust",
            "blowing sand": "BlwSand"
        }
        
        result = title
        for key, value in replacements.items():
            # Case insensitive replace
            result = result.replace(key, value).replace(key.capitalize(), value).replace(key.upper(), value)
        
        # Limit to reasonable length
        if len(result) > 30:
            result = result[:27] + "..."
        
        return result

    def abbreviate_wind_direction(self, direction: str) -> str:
        """Abbreviate wind direction to emoji + 2-3 characters"""
        if not direction:
            return ""
        
        direction = direction.upper()
        replacements = {
            "NORTHWEST": "↖️NW",
            "NORTHEAST": "↗️NE",
            "SOUTHWEST": "↙️SW", 
            "SOUTHEAST": "↘️SE",
            "NORTH": "⬆️N",
            "EAST": "➡️E",
            "SOUTH": "⬇️S",
            "WEST": "⬅️W"
        }
        
        for full, abbrev in replacements.items():
            if full in direction:
                return abbrev
        
        # If no match, return first 2 characters with generic wind emoji
        return f"💨{direction[:2]}" if len(direction) >= 2 else f"💨{direction}"

    def extract_humidity(self, text: str) -> str:
        """Extract humidity percentage from forecast text"""
        if not text:
            return ""
        
        # Look for patterns like "humidity 45%" or "45% humidity"
        humidity_patterns = [
            r'humidity\s+(\d+)%',
            r'(\d+)%\s+humidity',
            r'relative humidity\s+(\d+)%',
            r'(\d+)%\s+relative humidity'
        ]
        
        for pattern in humidity_patterns:
            match = re.search(pattern, text.lower())
            if match:
                return match.group(1)
        
        return ""

    def extract_precip_chance(self, text: str) -> str:
        """Extract precipitation chance from forecast text"""
        if not text:
            return ""
        
        # Look for patterns like "20% chance" or "chance of rain 30%"
        precip_patterns = [
            r'(\d+)%\s+chance',
            r'chance\s+of\s+\w+\s+(\d+)%',
            r'(\d+)%\s+probability',
            r'probability\s+of\s+\w+\s+(\d+)%'
        ]
        
        for pattern in precip_patterns:
            match = re.search(pattern, text.lower())
            if match:
                return match.group(1)
        
        return ""

    def extract_high_low(self, text: str) -> str:
        """Extract high/low temperatures from forecast text"""
        if not text:
            return ""
        
        # Look for more specific patterns to avoid false matches
        high_low_patterns = [
            r'high\s+near\s+(\d+).*?low\s+around\s+(\d+)',
            r'high\s+(\d+).*?low\s+(\d+)',
            r'(\d+)\s+to\s+(\d+)\s+degrees',  # More specific
            r'temperature\s+(\d+)\s+to\s+(\d+)',
            r'high\s+near\s+(\d+).*?temperatures\s+falling\s+to\s+around\s+(\d+)',  # "High near 82, with temperatures falling to around 80"
            r'low\s+around\s+(\d+)',  # Just low temp
            r'high\s+near\s+(\d+)'   # Just high temp
        ]
        
        for pattern in high_low_patterns:
            match = re.search(pattern, text.lower())
            if match:
                if len(match.groups()) == 2:
                    high, low = match.groups()
                    # Validate that these are reasonable temperatures (20-120°F)
                    try:
                        high_val = int(high)
                        low_val = int(low)
                        if 20 <= high_val <= 120 and 20 <= low_val <= 120 and high_val > low_val:
                            return f"{high}°/{low}°"
                    except ValueError:
                        continue
                elif len(match.groups()) == 1:
                    # Single temperature - could be high or low
                    temp = match.group(1)
                    try:
                        temp_val = int(temp)
                        if 20 <= temp_val <= 120:
                            return f"{temp}°"
                    except ValueError:
                        continue
        
        return ""

    def extract_uv_index(self, text: str) -> str:
        """Extract UV index from forecast text"""
        if not text:
            return ""
        
        # Look for UV index patterns
        uv_patterns = [
            r'uv\s+index\s+(\d+)',
            r'uv\s+(\d+)',
            r'ultraviolet\s+index\s+(\d+)'
        ]
        
        for pattern in uv_patterns:
            match = re.search(pattern, text.lower())
            if match:
                uv_val = match.group(1)
                # Validate UV index (0-11+ is reasonable)
                try:
                    if 0 <= int(uv_val) <= 15:
                        return uv_val
                except ValueError:
                    continue
        
        return ""

    def extract_dew_point(self, text: str) -> str:
        """Extract dew point temperature from forecast text"""
        if not text:
            return ""
        
        # Look for dew point patterns
        dew_point_patterns = [
            r'dew point\s+(\d+)',
            r'dewpoint\s+(\d+)',
            r'dew\s+point\s+(\d+)°'
        ]
        
        for pattern in dew_point_patterns:
            match = re.search(pattern, text.lower())
            if match:
                dp_val = match.group(1)
                # Validate dew point (reasonable range -20 to 80°F)
                try:
                    if -20 <= int(dp_val) <= 80:
                        return dp_val
                except ValueError:
                    continue
        
        return ""

    def extract_visibility(self, text: str) -> str:
        """Extract visibility from forecast text"""
        if not text:
            return ""
        
        # Look for visibility patterns
        visibility_patterns = [
            r'visibility\s+(\d+)\s+miles',
            r'visibility\s+(\d+)\s+mi',
            r'(\d+)\s+mile\s+visibility',
            r'(\d+)\s+mi\s+visibility'
        ]
        
        for pattern in visibility_patterns:
            match = re.search(pattern, text.lower())
            if match:
                vis_val = match.group(1)
                # Validate visibility (reasonable range 0-20 miles)
                try:
                    if 0 <= int(vis_val) <= 20:
                        return vis_val
                except ValueError:
                    continue
        
        return ""

    def extract_precip_probability(self, text: str) -> str:
        """Extract precipitation probability from forecast text"""
        if not text:
            return ""
        
        # Look for precipitation probability patterns
        precip_prob_patterns = [
            r'(\d+)%\s+chance\s+of\s+(?:rain|precipitation|showers)',
            r'chance\s+of\s+(?:rain|precipitation|showers)\s+(\d+)%',
            r'(\d+)%\s+probability\s+of\s+(?:rain|precipitation|showers)',
            r'probability\s+of\s+(?:rain|precipitation|showers)\s+(\d+)%',
            r'(\d+)%\s+chance',
            r'chance\s+(\d+)%'
        ]
        
        for pattern in precip_prob_patterns:
            match = re.search(pattern, text.lower())
            if match:
                prob_val = match.group(1)
                # Validate probability (0-100%)
                try:
                    if 0 <= int(prob_val) <= 100:
                        return prob_val
                except ValueError:
                    continue
        
        return ""

    def extract_wind_gusts(self, text: str) -> str:
        """Extract wind gusts from forecast text"""
        if not text:
            return ""
        
        # Look for wind gust patterns
        gust_patterns = [
            r'gusts\s+to\s+(\d+)\s+mph',
            r'gusts\s+up\s+to\s+(\d+)\s+mph',
            r'wind\s+gusts\s+to\s+(\d+)\s+mph',
            r'wind\s+gusts\s+up\s+to\s+(\d+)\s+mph',
            r'gusts\s+(\d+)\s+mph',
            r'wind\s+gusts\s+(\d+)\s+mph'
        ]
        
        for pattern in gust_patterns:
            match = re.search(pattern, text.lower())
            if match:
                gust_val = match.group(1)
                # Validate wind gust (reasonable range 10-100 mph)
                try:
                    if 10 <= int(gust_val) <= 100:
                        return gust_val
                except ValueError:
                    continue
        
        return ""
    
    def extract_pressure(self, text: str) -> str:
        """Extract barometric pressure from forecast text"""
        if not text:
            return ""
        
        # Look for pressure patterns (hPa, mb, inches of mercury)
        pressure_patterns = [
            r'pressure\s+(\d+)\s*hpa',
            r'pressure\s+(\d+)\s*mb',
            r'barometric\s+pressure\s+(\d+)\s*hpa',
            r'barometric\s+pressure\s+(\d+)\s*mb',
            r'(\d+)\s*hpa',
            r'(\d+)\s*mb\s+pressure'
        ]
        
        for pattern in pressure_patterns:
            match = re.search(pattern, text.lower())
            if match:
                pressure_val = match.group(1)
                # Validate pressure (reasonable range 600-1100 hPa/mb)
                # Normal sea level is ~1013 hPa, but high elevation locations can be lower
                try:
                    pressure_int = int(pressure_val)
                    if 600 <= pressure_int <= 1100:
                        return pressure_val
                except ValueError:
                    continue
        
        return ""

    def get_observation_data(self, points_data: dict) -> dict:
        """Get observation station data from NOAA and return as a dict
        
        Returns:
            Dict with keys: humidity, dew_point, visibility, wind_gusts, pressure
            Values are strings ready for display, or None if not available
        """
        try:
            if not points_data:
                return {}
            
            weather_json = points_data
            station_url = weather_json['properties'].get('observationStations')
            if not station_url:
                return {}
            
            # Get the nearest station
            stations_data = requests.get(station_url, timeout=self.url_timeout)
            if not stations_data.ok:
                return {}
            
            stations_json = stations_data.json()
            if not stations_json.get('features'):
                return {}
            
            # Get current observations from the nearest station
            station_id = stations_json['features'][0]['properties']['stationIdentifier']
            obs_url = f"https://api.weather.gov/stations/{station_id}/observations/latest"
            
            obs_data = requests.get(obs_url, timeout=self.url_timeout)
            if not obs_data.ok:
                return {}
            
            obs_json = obs_data.json()
            if not obs_json.get('properties'):
                return {}
            
            props = obs_json['properties']
            obs_data_dict = {}
            
            # Extract useful current conditions
            # Check for None explicitly to handle cases where value exists but is None
            humidity_val = props.get('relativeHumidity', {}).get('value')
            if humidity_val is not None:
                humidity = int(humidity_val)
                obs_data_dict['humidity'] = str(humidity)
            
            dewpoint_val = props.get('dewpoint', {}).get('value')
            if dewpoint_val is not None:
                dewpoint = int(dewpoint_val * 9/5 + 32)  # Convert C to F
                obs_data_dict['dew_point'] = str(dewpoint)
            
            visibility_val = props.get('visibility', {}).get('value')
            if visibility_val is not None:
                visibility = int(visibility_val * 0.000621371)  # Convert m to miles
                if visibility > 0:
                    obs_data_dict['visibility'] = str(visibility)
            
            wind_gust_val = props.get('windGust', {}).get('value')
            if wind_gust_val is not None:
                wind_gust = int(wind_gust_val * 2.237)  # Convert m/s to mph
                if wind_gust > 10:
                    obs_data_dict['wind_gusts'] = str(wind_gust)
            
            pressure_val = props.get('barometricPressure', {}).get('value')
            if pressure_val is not None:
                pressure = int(pressure_val / 100)  # Convert Pa to hPa
                obs_data_dict['pressure'] = str(pressure)
            
            return obs_data_dict
            
        except Exception as e:
            self.logger.debug(f"Error getting observation data: {e}")
            return {}
    
    def get_current_conditions(self, points_data: dict) -> str:
        """Get additional current conditions data from NOAA using existing points data (legacy method)"""
        obs_data = self.get_observation_data(points_data)
        if not obs_data:
            return ""
        
        conditions = []
        
        # Build conditions list in priority order
        if 'humidity' in obs_data:
            conditions.append(f"{obs_data['humidity']}%RH")
        
        if 'dew_point' in obs_data:
            conditions.append(f"💧{obs_data['dew_point']}°")
        
        if 'visibility' in obs_data:
            conditions.append(f"👁️{obs_data['visibility']}mi")
        
        if 'wind_gusts' in obs_data:
            conditions.append(f"💨{obs_data['wind_gusts']}")
        
        if 'pressure' in obs_data:
            conditions.append(f"📊{obs_data['pressure']}hPa")
        
        return " ".join(conditions[:3])  # Limit to 3 conditions to avoid overflow

    def get_weather_emoji(self, condition: str) -> str:
        """Get emoji for weather condition"""
        if not condition:
            return ""
        
        condition_lower = condition.lower()
        
        # Weather condition emojis
        if any(word in condition_lower for word in ['sunny', 'clear']):
            return "☀️"
        elif any(word in condition_lower for word in ['cloudy', 'overcast']):
            return "☁️"
        elif any(word in condition_lower for word in ['partly cloudy', 'mostly cloudy']):
            return "⛅"
        elif any(word in condition_lower for word in ['rain', 'showers']):
            return "🌦️"
        elif any(word in condition_lower for word in ['thunderstorm', 'thunderstorms']):
            return "⛈️"
        elif any(word in condition_lower for word in ['snow', 'snow showers']):
            return "❄️"
        elif any(word in condition_lower for word in ['fog', 'mist', 'haze']):
            return "🌫️"
        elif any(word in condition_lower for word in ['smoke']):
            return "💨"
        elif any(word in condition_lower for word in ['windy', 'breezy']):
            return "💨"
        else:
            return "🌤️"  # Default weather emoji

    def abbreviate_noaa(self, text: str) -> str:
        """Replace long strings with shorter ones for display"""
        replacements = {
            "monday": "Mon",
            "tuesday": "Tue", 
            "wednesday": "Wed",
            "thursday": "Thu",
            "friday": "Fri",
            "saturday": "Sat",
            "sunday": "Sun",
            "northwest": "NW",
            "northeast": "NE", 
            "southwest": "SW",
            "southeast": "SE",
            "north": "N",
            "south": "S",
            "east": "E",
            "west": "W",
            "precipitation": "precip",
            "showers": "shwrs",
            "thunderstorms": "t-storms",
            "thunderstorm": "t-storm",
            "quarters": "qtrs",
            "quarter": "qtr",
            "january": "Jan",
            "february": "Feb",
            "march": "Mar",
            "april": "Apr",
            "may": "May",
            "june": "Jun",
            "july": "Jul",
            "august": "Aug",
            "september": "Sep",
            "october": "Oct",
            "november": "Nov",
            "december": "Dec",
            "degrees": "°",
            "percent": "%",
            "department": "Dept.",
            "amounts less than a tenth of an inch possible.": "< 0.1in",
            "temperatures": "temps.",
            "temperature": "temp.",
        }
        
        line = text
        for key, value in replacements.items():
            # Case insensitive replace
            line = line.replace(key, value).replace(key.capitalize(), value).replace(key.upper(), value)
        
        return line
