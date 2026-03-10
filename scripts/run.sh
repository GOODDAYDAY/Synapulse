#!/bin/bash
set -e
# Start the Synapulse bot
# Prerequisite: Python 3.11+, .env configured

echo "Starting Synapulse..."
python -m apps.bot.main
