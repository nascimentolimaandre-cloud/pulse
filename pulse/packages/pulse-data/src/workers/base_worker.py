"""Base Kafka consumer worker.

Provides a shared pattern for long-running workers that
consume messages from Kafka topics and process them.
Locally runs as a loop; in Lambda, batch is passed via event.

Uses manual commit after successful processing for at-least-once delivery.
"""

import asyncio
import logging
import signal
from abc import ABC, abstractmethod
from typing import Any

from aiokafka import AIOKafkaConsumer

from src.shared.kafka import create_consumer

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """Abstract base class for Kafka consumer workers.

    Subclasses implement process_message() with their specific logic.
    Handles graceful shutdown on SIGTERM/SIGINT.
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
        """Start consuming messages in a loop (local dev mode).

        Uses manual commit after each message is successfully processed.
        Handles SIGTERM and SIGINT for graceful shutdown.
        """
        self._consumer = await create_consumer(*self._topics, group_id=self._group_id)
        self._running = True
        logger.info("Worker %s started, consuming from %s", self._group_id, self._topics)

        # Register signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

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
                    # Manual commit after successful processing
                    await self._consumer.commit()
                except Exception:
                    logger.exception(
                        "Error processing message from %s partition=%d offset=%d",
                        msg.topic,
                        msg.partition,
                        msg.offset,
                    )
                    # Still commit to avoid infinite retry on poison messages.
                    # In production, failed messages should go to a DLQ.
                    await self._consumer.commit()
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the consumer gracefully."""
        if not self._running:
            return
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            self._consumer = None
            logger.info("Worker %s stopped gracefully", self._group_id)
