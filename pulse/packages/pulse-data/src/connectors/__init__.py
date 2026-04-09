"""Source connectors — fetch data directly from GitHub, Jira, Jenkins APIs.

Replaces the DevLake intermediate layer with direct API access.
Each connector implements BaseConnector and returns dicts compatible
with the existing normalizer (same field names as DevLake domain tables).
"""

from src.connectors.base import BaseConnector
from src.connectors.aggregator import ConnectorAggregator

__all__ = ["BaseConnector", "ConnectorAggregator"]
