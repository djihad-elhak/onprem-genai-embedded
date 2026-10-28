#!/usr/bin/env bash
# What an assistant sees through the knowledge MCP server.
source "$(dirname "$0")/_lib.sh"
say "Knowledge graph of F´ (code, tests, requirements, design docs) served over MCP"
run python demo/mcp_tour.py --pause 1.2
