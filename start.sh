#!/bin/bash
export DEFAULT_CACHE_VERIFY_SECONDS=30
python3 serve_dashboard.py --host 127.0.0.1 --port 8765 --workers 64