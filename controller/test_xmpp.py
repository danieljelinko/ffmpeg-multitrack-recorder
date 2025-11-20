#!/usr/bin/env python3
"""
Test XMPP connection
"""
import sys
import logging
from xmpp_client import create_xmpp_bot_from_env

logging.basicConfig(level=logging.DEBUG, format='%(levelname)-8s %(message)s')

def test_logger(msg):
    print(f"[BOT] {msg}")

print("Creating XMPP bot...")
bot = create_xmpp_bot_from_env(logger=test_logger)

print(f"Bot type: {type(bot).__name__}")
print(f"Bot JID: {bot.boundjid if hasattr(bot, 'boundjid') else 'N/A'}")

print("Attempting to connect...")
connected = bot.connect()
print(f"Connect result: {connected}")

if connected:
    print("Processing...")
    bot.process(block=False, forever=False, timeout=10)
    print(f"Bridge JID discovered: {bot.bridge_jid}")
else:
    print("Connection failed")
    sys.exit(1)

print("Disconnecting...")
bot.disconnect()
print("Done")
