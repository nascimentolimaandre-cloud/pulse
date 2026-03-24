"""Kafka producer and consumer helpers using aiokafka.

Provides thin wrappers for producing and consuming messages
from Kafka topics used by the PULSE pipeline.
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


async def create_producer() -> AIOKafkaProducer:
    """Create and start a Kafka producer."""
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_broker_list,
        value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
    )
    await producer.start()
    return producer


async def create_consumer(
    *topics: str,
    group_id: str,
) -> AIOKafkaConsumer:
    """Create and start a Kafka consumer for the given topics."""
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.kafka_broker_list,
        group_id=group_id,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    await consumer.start()
    return consumer


async def publish_event(producer: AIOKafkaProducer, topic: str, key: str, value: dict[str, Any]) -> None:
    """Publish a single event to a Kafka topic."""
    await producer.send_and_wait(topic, value=value, key=key)
    logger.debug("Published event to %s with key %s", topic, key)
