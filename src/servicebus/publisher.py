"""Message publisher implementation for Service Bus."""

import logging
from datetime import datetime
from uuid import uuid4

from src.core.models import MessageEnvelope
from .models import (
    IMessagePublisher,
    IServiceBusClient,
    ServiceBusConfig,
    ServiceBusMessage,
    ServiceBusMessageType,
)

logger = logging.getLogger(__name__)


class MessagePublisher(IMessagePublisher):
    """Message publisher implementation using Service Bus."""

    def __init__(self, client: IServiceBusClient, config: ServiceBusConfig) -> None:
        """Initialize message publisher.

        Args:
            client: Service Bus client instance
            config: Service Bus configuration
        """
        self.client = client
        self.config = config

    async def publish_request(
        self,
        envelope: MessageEnvelope,
        payload: bytes,
        session_id: str | None = None
    ) -> bool:
        """Publish a request message."""
        logger.debug(f"Publishing request to_agent={envelope.to_agent}, correlation_id={envelope.correlation_id}")

        try:
            message = ServiceBusMessage(
                message_id=str(uuid4()),
                correlation_id=envelope.correlation_id,
                envelope=envelope,
                payload=payload,
                message_type=ServiceBusMessageType.REQUEST,
                created_at=datetime.utcnow()
            )

            # Use group-specific topic name according to proxy specification
            topic_name = f"a2a.{envelope.group}.requests"
            
            # Use correlation_id as session_id if none provided (required for ordered delivery)
            effective_session_id = session_id or envelope.correlation_id
            
            success = await self.client.send_message(
                topic_name=topic_name,
                message=message,
                session_id=effective_session_id
            )

            if success:
                logger.info(f"Request published to_agent={envelope.to_agent}, group={envelope.group}, topic={topic_name}, correlation_id={envelope.correlation_id}")
            else:
                logger.error(f"Failed to publish request to_agent={envelope.to_agent}, correlation_id={envelope.correlation_id}")

            return success

        except Exception as e:
            logger.error(f"Error publishing request to_agent={envelope.to_agent}, error={str(e)}")
            return False

    async def publish_response(
        self,
        envelope: MessageEnvelope,
        payload: bytes,
        correlation_id: str,
        session_id: str | None = None
    ) -> bool:
        """Publish a response message."""
        logger.debug(f"Publishing response correlation_id={correlation_id}")

        try:
            message = ServiceBusMessage(
                message_id=str(uuid4()),
                correlation_id=correlation_id,
                envelope=envelope,
                payload=payload,
                message_type=ServiceBusMessageType.RESPONSE,
                created_at=datetime.utcnow()
            )

            # Use group-specific topic name according to proxy specification
            topic_name = f"a2a.{envelope.group}.responses"

            # Use correlation_id as session_id if none provided (required for ordered delivery)
            effective_session_id = session_id or correlation_id

            success = await self.client.send_message(
                topic_name=topic_name,
                message=message,
                session_id=effective_session_id
            )

            if success:
                logger.info(f"Response published group={envelope.group}, topic={topic_name}, correlation_id={correlation_id}")
            else:
                logger.error(f"Failed to publish response correlation_id={correlation_id}")

            return success

        except Exception as e:
            logger.error(f"Error publishing response correlation_id={correlation_id}, error={str(e)}")
            return False

    async def publish_notification(
        self,
        envelope: MessageEnvelope,
        payload: bytes,
        session_id: str | None = None
    ) -> bool:
        """Publish a notification message."""
        logger.debug(f"Publishing notification correlation_id={envelope.correlation_id}")

        try:
            message = ServiceBusMessage(
                message_id=str(uuid4()),
                correlation_id=envelope.correlation_id,
                envelope=envelope,
                payload=payload,
                message_type=ServiceBusMessageType.NOTIFICATION,
                created_at=datetime.utcnow()
            )

            # Use correlation_id as session_id if none provided (required for ordered delivery)
            effective_session_id = session_id or envelope.correlation_id

            success = await self.client.send_message(
                topic_name=self.config.notification_topic,
                message=message,
                session_id=effective_session_id
            )

            if success:
                logger.info(f"Notification published correlation_id={envelope.correlation_id}")
            else:
                logger.error(f"Failed to publish notification correlation_id={envelope.correlation_id}")

            return success

        except Exception as e:
            logger.error(f"Error publishing notification correlation_id={envelope.correlation_id}, error={str(e)}")
            return False