"""Kafka producer and consumer helpers using aiokafka.

Provides thin wrappers for producing and consuming messages
from Kafka topics used by the PULSE pipeline.

IMPORTANT: Consumers use manual commit (enable_auto_commit=False)
to guarantee at-least-once delivery. Workers must commit after processing.
"""

import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from src.config import settings

logger = logging.getLogger(__name__)

# Topic constants
TOPIC_PR_NORMALIZED = "domain.pr.normalized"
TOPIC_ISSUE_NORMALIZED = "domain.issue.normalized"
TOPIC_DEPLOYMENT_NORMALIZED = "domain.deployment.normalized"
TOPIC_SPRINT_NORMALIZED = "domain.sprint.normalized"
TOPIC_METRICS_CALCULATED = "domain.metrics.calculated"


def _json_serializer(v: Any) -> bytes:
    """Serialize a value to JSON bytes, handling datetime objects."""
    return json.dumps(v, default=str).encode("utf-8")


def _json_deserializer(v: bytes) -> Any:
    """Deserialize JSON bytes to a Python object."""
    return json.loads(v.decode("utf-8"))


async def create_producer() -> AIOKafkaProducer:
    """Create and start a Kafka producer."""
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_broker_list,
        value_serializer=_json_serializer,
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        acks="all",
        retry_backoff_ms=100,
        max_batch_size=16384,
    )
    await producer.start()
    logger.info("Kafka producer started, brokers=%s", settings.kafka_brokers)
    return producer


async def create_consumer(
    *topics: str,
    group_id: str,
) -> AIOKafkaConsumer:
    """Create and start a Kafka consumer for the given topics.

    Uses manual commit for at-least-once delivery guarantee.
    Callers MUST call consumer.commit() after successfully processing messages.
    """
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.kafka_broker_list,
        group_id=group_id,
        value_deserializer=_json_deserializer,
        auto_offset_reset="earliest",
        enable_auto_commit=False,  # Manual commit after processing
        max_poll_records=100,
        session_timeout_ms=30000,
        heartbeat_interval_ms=10000,
    )
    await consumer.start()
    logger.info("Kafka consumer started, group=%s, topics=%s", group_id, topics)
    return consumer


async def publish_event(
    producer: AIOKafkaProducer,
    topic: str,
    key: str,
    value: dict[str, Any],
) -> None:
    """Publish a single event to a Kafka topic."""
    await producer.send_and_wait(topic, value=value, key=key)
    logger.debug("Published event to %s key=%s", topic, key)


async def publish_batch(
    producer: AIOKafkaProducer,
    topic: str,
    events: list[tuple[str, dict[str, Any]]],
) -> int:
    """Publish a batch of events to a Kafka topic.

    Args:
        producer: The Kafka producer instance.
        topic: Target topic name.
        events: List of (key, value) tuples to publish.

    Returns:
        Number of events successfully published.
    """
    count = 0
    for key, value in events:
        await producer.send_and_wait(topic, value=value, key=key)
        count += 1
    if count > 0:
        logger.info("Published %d events to %s", count, topic)
    return count
