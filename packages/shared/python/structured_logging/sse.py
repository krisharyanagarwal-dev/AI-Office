"""
Server-Sent Events (SSE) broadcasting for real-time updates.
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, List, AsyncGenerator
from fastapi import Request


class EventBroadcaster:
    """Manages SSE connections and broadcasts events to all connected clients."""
    
    def __init__(self, max_queue_size: int = 100):
        self.queues: List[asyncio.Queue] = []
        self.max_queue_size = max_queue_size
        self._lock = asyncio.Lock()
    
    async def add_connection(self) -> asyncio.Queue:
        """Add a new SSE connection and return its queue."""
        queue = asyncio.Queue(maxsize=self.max_queue_size)
        async with self._lock:
            self.queues.append(queue)
        return queue
    
    async def remove_connection(self, queue: asyncio.Queue):
        """Remove an SSE connection."""
        async with self._lock:
            if queue in self.queues:
                self.queues.remove(queue)
    
    async def broadcast(self, event_type: str, data: Dict[str, Any]):
        """Broadcast an event to all connected clients."""
        event_data = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        
        async with self._lock:
            for queue in self.queues[:]:
                try:
                    queue.put_nowait(event_data)
                except asyncio.QueueFull:
                    # Remove full queues
                    self.queues.remove(queue)
    
    async def broadcast_task_event(self, event_type: str, task_id: str, data: Dict[str, Any]):
        """Broadcast a task-related event."""
        await self.broadcast(event_type, {
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data
        })
    
    async def broadcast_agent_event(self, event_type: str, agent_name: str, data: Dict[str, Any]):
        """Broadcast an agent-related event."""
        await self.broadcast(event_type, {
            "agent_name": agent_name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data
        })
    
    async def broadcast_model_event(self, event_type: str, backend_name: str, data: Dict[str, Any]):
        """Broadcast a model router backend event."""
        await self.broadcast(event_type, {
            "backend_name": backend_name,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data
        })
    
    async def broadcast_launchd_event(self, event_type: str, label: str, data: Dict[str, Any]):
        """Broadcast a launchd job event."""
        await self.broadcast(event_type, {
            "label": label,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data
        })
    
    async def broadcast_system_event(self, event_type: str, data: Dict[str, Any]):
        """Broadcast a system-level event."""
        await self.broadcast(event_type, {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            **data
        })


async def sse_event_generator(request: Request, queue: asyncio.Queue, 
                              heartbeat_interval: float = 30.0) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for a connection.
    
    Args:
        request: FastAPI request object
        queue: Event queue for this connection
        heartbeat_interval: Seconds between heartbeat events
    """
    try:
        # Send initial connection event
        yield f"event: connected\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat() + 'Z'})}\n\n"
        
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                yield event
            except asyncio.TimeoutError:
                # Send heartbeat
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.utcnow().isoformat() + 'Z'})}\n\n"
    finally:
        pass  # Queue cleanup handled by caller


# Global event broadcaster instance
event_broadcaster = EventBroadcaster()