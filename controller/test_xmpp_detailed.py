#!/usr/bin/env python3
"""
Detailed XMPP connection test
"""
import sys
import logging
import time
from xmpp_client import create_xmpp_bot_from_env
from xmpp_config import load_xmpp_settings

logging.basicConfig(level=logging.DEBUG, format='%(levelname)-8s %(message)s')

def test_logger(msg):
    print(f"[BOT] {msg}")

print("Loading XMPP settings...")
settings = load_xmpp_settings()
print(f"Mode: {settings.mode}")
print(f"Host: {settings.host}")
print(f"Port: {settings.port}")
print(f"JID: {settings.jid}")
print(f"Secret: {'*' * len(settings.password)}")
print(f"Bridge MUC: {settings.bridge_muc}")

print("\nCreating XMPP bot...")
bot = create_xmpp_bot_from_env(logger=test_logger)

print(f"Bot type: {type(bot).__name__}")

print("\nAttempting to connect...")
try:
    result = bot.connect()
    print(f"Connect returned: {result}")

    if result:
        print("Connection established! Processing...")
        bot.process(forever=False, timeout=10)
        time.sleep(2)
        print(f"Bridge JID: {bot.bridge_jid}")
        bot.disconnect()
    else:
        print("Connection failed - connect() returned False/None")
        sys.exit(1)
except Exception as e:
    print(f"Connection error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("Done")
