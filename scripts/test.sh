#!/bin/bash
set -e
# Run all tests
# Prerequisite: Python 3.11+, pytest installed

echo "Running tests..."
python -m pytest tests/ -v
echo "Tests completed."
