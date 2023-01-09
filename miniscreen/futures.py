import asyncio
import subprocess
from typing import Awaitable

from miniscreen.consoleio import read_one_keystroke


async def next_keystroke(fd=0):
    loop = asyncio.get_event_loop()
    future = asyncio.Future[None]()
    loop.add_reader(fd, future.set_result, None)
    future.add_done_callback(lambda _f: loop.remove_reader(fd))
    await future
    return read_one_keystroke(0.1, fd=fd)


async def check_output(cmdline: tuple[str, ...], *, input: bytes | None = None) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *cmdline,
        stdin=None if input is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    stdout_data, stderr_data = await proc.communicate(input)
    assert stdout_data is not None
    assert stderr_data is None
    r = await proc.wait()
    if r:
        raise subprocess.CalledProcessError(r, cmdline, stdout_data, stderr_data)
    return stdout_data


def create_task(coro) -> Awaitable[None]:
    return asyncio.create_task(coro)


def run_coroutine(coro) -> None:
    asyncio.run(coro)
