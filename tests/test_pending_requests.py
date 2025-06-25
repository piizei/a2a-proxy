import asyncio

import pytest

from src.core.pending_requests import PendingRequestManager


@pytest.mark.asyncio
async def test_create_request_waits_for_response():
    manager = PendingRequestManager(cleanup_interval=1)
    await manager.start()
    await manager.create_request("req1", timeout_seconds=5)

    wait_task = asyncio.create_task(manager.wait_for_response("req1"))
    await asyncio.sleep(0)  # allow wait to start
    manager.handle_response("req1", {"ok": True})

    result = await wait_task
    assert result == {"ok": True}
    assert manager.get_pending_count() == 0

    await manager.stop()


@pytest.mark.asyncio
async def test_wait_for_response_times_out():
    manager = PendingRequestManager(cleanup_interval=1)
    await manager.start()
    await manager.create_request("req2", timeout_seconds=0)

    with pytest.raises(asyncio.TimeoutError):
        await manager.wait_for_response("req2")

    assert manager.get_pending_count() == 0
    await manager.stop()


@pytest.mark.asyncio
async def test_handle_response_completes_future():
    manager = PendingRequestManager()
    await manager.start()
    await manager.create_request("req3", timeout_seconds=5)

    completed = manager.handle_response("req3", "data")
    assert completed

    result = await manager.wait_for_response("req3")
    assert result == "data"

    await manager.stop()


@pytest.mark.asyncio
async def test_cleanup_expired_requests():
    manager = PendingRequestManager()
    await manager.start()
    await manager.create_request("req4", timeout_seconds=0)

    # store future reference for assertion after cleanup
    request_future = manager._pending_requests["req4"].future

    await asyncio.sleep(0.01)
    await manager._cleanup_expired_requests()

    assert manager.get_pending_count() == 0
    assert request_future is not None and request_future.done()
    with pytest.raises(asyncio.TimeoutError):
        request_future.result()

    await manager.stop()
