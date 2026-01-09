"""
Terminal routes module - REMOVED.

This module previously handled WebSocket-based terminal streaming via SSM Session Manager.
It has been removed in favor of AWS Console Session Manager deep links.

The frontend now uses openAwsConsoleTerminal(region, instanceId) which opens AWS Console directly.
No backend endpoints are needed - AWS Console handles everything.

This file is kept as a stub to maintain compatibility with api_server.py imports.
"""

from fastapi import APIRouter

# Empty router - no endpoints needed since we use AWS Console deep links
router = APIRouter(prefix="/api", tags=["terminal"])

