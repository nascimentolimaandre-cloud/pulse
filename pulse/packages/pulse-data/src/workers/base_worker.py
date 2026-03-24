"""Base Kafka consumer worker.

Provides a shared pattern for long-running workers that
consume messages from Kafka topics and process them.
Locally runs as a loop; in Lambda, batch is passed via event.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from aiokafka import AIOKafkaConsumer

from src.shared.kafka import create_consumer

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """Abstract base class for Kafka consumer workers.

    Subclasses implement process_message() with their specific logic.
    """

    def __init__(self, topics: list[str], group_id: str) -> None:
        self._topics = topics
        self._group_id = group_id
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False

    @abstractmethod
    async def process_message(self, topic: str, key: str | None, value: dict[str, Any]) -> None:
        """Process a single Kafka message. Implemented by subclasses."""
        ...

    async def process_batch(self, messages: list[dict[str, Any]]) -> None:
        """Process a batch of messages (used by Lambda handler).

        Args:
            messages: List of deserialized Kafka messages with topic, key, value.
        """
        for msg in messages:
            await self.process_message(
                topic=msg["topic"],
                key=msg.get("key"),
                value=msg["value"],
            )

    async def start(self) -> None:
        """Start consuming messages in a loop (local dev mode)."""
        self._consumer = await create_consumer(*self._topics, group_id=self._group_id)
        self._running = True
        logger.info("Worker %s started, consuming from %s", self._group_id, self._topics)

        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                try:
                    await self.process_message(
                        topic=msg.topic,
                        key=msg.key.decode("utf-8") if msg.key else None,
                        value=msg.value,
                    )
                except Exception:
                    logger.exception("Error processing message from %s", msg.topic)
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the consumer gracefully."""
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("Worker %s stopped", self._group_id)
