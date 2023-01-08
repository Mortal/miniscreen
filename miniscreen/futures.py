import asyncio
from miniscreen.consoleio import read_one_keystroke


async def next_keystroke(fd=0):
    loop = asyncio.get_event_loop()
    future = asyncio.Future[None]()
    loop.add_reader(fd, future.set_result, None)
    future.add_done_callback(lambda _f: loop.remove_reader(fd))
    await future
    return read_one_keystroke(0.1, fd=fd)
