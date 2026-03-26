#!/usr/bin/env python3
"""
RSS Watcher background task
Polls specified RSS feeds and broadcasts new articles to the configured channel
"""

import asyncio
import feedparser
from typing import Dict, Set

class RssWatcher:
    """Watches RSS feeds and broadcasts new articles"""
    
    def __init__(self, bot):
        self.bot = bot
        self.logger = bot.logger
        self.enabled = False
        self.channel = "general"
        self.interval_minutes = 15
        self.feeds: Dict[str, str] = {}
        
        # Deduplication cache (in-memory)
        # We store up to N recently seen article IDs to avoid sending duplicates.
        # We use a set for O(1) lookups, but we must limit its size to avoid leaks or use a capped structure.
        # Let's use a simple list used as a queue for limiting size, and a set for quick lookups.
        self.seen_articles: Set[str] = set()
        self.seen_articles_queue: list = []
        self.max_cache_size = 500
        self._is_first_run = True
        
        self.load_config()

    def load_config(self):
        """Load configuration from [RSS] section"""
        if not self.bot.config.has_section('RSS'):
            self.logger.info("No [RSS] section in config, RSS Watcher disabled.")
            return

        self.enabled = self.bot.config.getboolean('RSS', 'enabled', fallback=False)
        self.channel = self.bot.config.get('RSS', 'channel', fallback='general')
        self.interval_minutes = self.bot.config.getint('RSS', 'interval_minutes', fallback=1)

        # Iterate over all items in [RSS] to find feeds starting with 'rss_'
        for key, value in self.bot.config.items('RSS'):
            if key.startswith('rss_') and value.strip():
                self.feeds[key] = value.strip()

        if self.enabled and self.feeds:
            self.logger.info(f"RSS Watcher enabled. Interval: {self.interval_minutes}m, Channel: {self.channel}, Feeds: {len(self.feeds)}")
        else:
            self.enabled = False

    def start(self):
        """Start the background poll loop"""
        if self.enabled:
            asyncio.create_task(self._poll_loop())

    def _mark_seen(self, article_id: str):
        """Mark an article as seen to avoid sending it again"""
        if article_id not in self.seen_articles:
            self.seen_articles.add(article_id)
            self.seen_articles_queue.append(article_id)
            
            # Prune cache if it gets too large
            if len(self.seen_articles_queue) > self.max_cache_size:
                oldest_id = self.seen_articles_queue.pop(0)
                if oldest_id in self.seen_articles:
                    self.seen_articles.remove(oldest_id)

    async def _poll_loop(self):
        """The main polling loop for fetching and broadcasting RSS updates"""
        self.logger.info("RSS Watcher loop started.")
        # Sleep for a short start delay to let bot fully connect
        await asyncio.sleep(5)
        
        while self.bot.connected and self.enabled:
            try:
                for feed_name, url in self.feeds.items():
                    await self._check_feed(feed_name, url)
                self._is_first_run = False
            except Exception as e:
                self.logger.error(f"Error checking RSS feeds: {e}")
            
            # Sleep until next check (interval in minutes)
            await asyncio.sleep(self.interval_minutes * 60)
            
    async def _check_feed(self, feed_name: str, url: str):
        """Fetch and process a single feed"""
        self.logger.debug(f"Checking RSS feed: {feed_name}")
        # feedparser.parse is blocking, but given usually small feeds, it runs fast enough. 
        # Alternatively we could run it in an executor. For now, running directly.
        feed = feedparser.parse(url)
        
        # Parse items (usually newest first). We can reverse it if we want oldest-new sent first,
        # but iterating normally works too.
        for entry in feed.entries:
            # We use id if available, otherwise fallback to link
            article_id = entry.get('id', entry.get('link'))
            if not article_id:
                continue
                
            if article_id not in self.seen_articles:
                if not self._is_first_run:
                    # It's a new article! Broadcast
                    title = entry.get('title', 'No Title')
                    link = entry.get('link', '')
                    
                    message = f"📰 {title}\n🔗 {link}"
                    self.logger.info(f"Broadcasting new RSS article '{title}' to channel {self.channel}")
                    
                    try:
                        await self.bot.command_manager.send_channel_message(self.channel, message)
                    except Exception as e:
                        self.logger.error(f"Failed to send RSS message to channel {self.channel}: {e}")
                else:
                    self.logger.debug(f"First run: silencing initial article '{entry.get('title', 'No Title')}'")
                
                self._mark_seen(article_id)
