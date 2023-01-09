import os
import select
import subprocess
from typing import Awaitable, BinaryIO

from miniscreen.consoleio import read_one_keystroke


class Task:
    coro = None

    def __await__(self):
        return (yield self)


class Process:
    cmdline: tuple[str, ...]
    inner: subprocess.Popen
    input: bytes | None
    output: bytearray
    pidfd: int | None
    readfd: BinaryIO | None
    writefd: BinaryIO | None
    task: Task | None = None

    def __await__(self):
        return (yield self)


class NextKeystroke:
    def __init__(self, fd: int) -> None:
        self.fd = fd

    def __await__(self):
        return (yield self)


class EventLoop:
    def __init__(self) -> None:
        self.pidfd_to_process: dict[int, Process] = {}
        self.readfd_to_process: dict[int, Process] = {}
        self.writefd_to_process: dict[int, Process] = {}

    def __enter__(self) -> "EventLoop":
        global _event_loop
        assert _event_loop is None
        _event_loop = self
        return self

    def __exit__(self, et, ev, eb) -> None:
        global _event_loop
        if et is None:
            assert _event_loop is self
        if _event_loop is self:
            _event_loop = None

    def can_read(self, fd: int) -> None:
        if fd in self.readfd_to_process:
            assert fd not in self.pidfd_to_process
            proc = self.readfd_to_process[fd]
            assert proc.readfd is not None
            assert proc.readfd.fileno() == fd
            r = os.read(fd, 2**20)
            proc.output += r
            if not r:
                proc.readfd.close()
                del self.readfd_to_process[fd]
                proc.readfd = None
        if fd in self.pidfd_to_process:
            assert fd not in self.readfd_to_process
            proc = self.pidfd_to_process[fd]
            assert proc.pidfd == fd
            os.close(proc.pidfd)
            del self.pidfd_to_process[fd]
            proc.pidfd = None
            if proc.readfd is not None:
                del self.readfd_to_process[proc.readfd.fileno()]
                proc.readfd.close()
                proc.readfd = None
            if proc.writefd is not None:
                del self.writefd_to_process[proc.writefd.fileno()]
                proc.writefd.close()
                proc.writefd = None

            assert proc.task is not None
            task = proc.task
            proc.task = None

            returncode = proc.inner.wait()
            assert task.coro is not None
            stdout = bytes(proc.output)
            try:
                if returncode:
                    fut = task.coro.throw(subprocess.CalledProcessError(returncode, proc.cmdline, stdout, None))
                else:
                    fut = task.coro.send(stdout)
            except StopIteration:
                task.coro = None
            else:
                assert isinstance(fut, Process)
                # Mount new Process into EventLoop
                assert fut.task is None
                fut.task = task
                assert fut.pidfd is not None
                self.pidfd_to_process[fut.pidfd] = fut
                assert fut.readfd is not None
                self.readfd_to_process[fut.readfd.fileno()] = fut
                if fut.writefd is not None:
                    self.writefd_to_process[fut.writefd.fileno()] = fut

    def can_write(self, fd: int) -> None:
        proc = self.writefd_to_process[fd]
        assert proc.writefd is not None
        assert proc.writefd.fileno() == fd
        assert proc.input is not None
        try:
            w = os.write(fd, proc.input)
        except Exception:
            raise
        assert w > 0
        rest = proc.input[w:]
        proc.input = rest or None
        if not rest:
            del self.writefd_to_process[proc.writefd.fileno()]
            proc.writefd.close()
            proc.writefd = None

    def resolve(self, nk: NextKeystroke | Task | None) -> str | None:
        while True:
            to_read = [*self.pidfd_to_process.keys(), *self.readfd_to_process.keys()]
            if isinstance(nk, NextKeystroke):
                to_read.append(nk.fd)
            elif isinstance(nk, Task) and nk.coro is None:
                return None
            readfds, writefds, exceptfds = select.select(
                to_read,
                [*self.writefd_to_process.keys()],
                [],
            )
            if nk is not None and nk.fd in readfds:
                res = read_one_keystroke(0.1, fd=nk.fd)
                assert res
                return res
            if readfds:
                self.can_read(next(iter(readfds)))
            elif writefds:
                self.can_write(next(iter(writefds)))


_event_loop: EventLoop | None = None


def get_event_loop() -> EventLoop:
    assert _event_loop is not None
    return _event_loop


async def check_output(cmdline: tuple[str, ...], *, input: bytes | None = None) -> bytes:
    inner = subprocess.Popen(
        cmdline,
        stdin=None if input is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        close_fds=False,
    )
    proc = Process()
    proc.cmdline = cmdline
    proc.inner = inner
    proc.input = input
    proc.output = bytearray()
    assert inner.pid
    proc.pidfd = os.pidfd_open(inner.pid)
    assert inner.stdout is not None
    proc.readfd = inner.stdout
    if input is None:
        proc.writefd = None
    else:
        assert inner.stdin is not None
        proc.writefd = inner.stdin
    return (await proc)


async def next_keystroke(fd=0):
    return (await NextKeystroke(fd))


def run_coroutine(coro) -> None:
    with EventLoop() as loop:
        try:
            fut = coro.send(None)
        except StopIteration:
            return
        assert isinstance(fut, NextKeystroke), fut
        while True:
            try:
                result = loop.resolve(fut)
            except Exception as e:
                coro.throw(e)
            try:
                fut = coro.send(result)
            except StopIteration:
                return


def create_task(coro) -> Awaitable[None]:
    loop = get_event_loop()
    task = Task()
    try:
        fut = coro.send(None)
    except StopIteration:
        pass
    else:
        task.coro = coro
        assert isinstance(fut, Process)
        # Mount new Process into EventLoop
        assert fut.task is None
        fut.task = task
        assert fut.pidfd is not None
        loop.pidfd_to_process[fut.pidfd] = fut
        assert fut.readfd is not None
        loop.readfd_to_process[fut.readfd.fileno()] = fut
        if fut.writefd is not None:
            loop.writefd_to_process[fut.writefd.fileno()] = fut
    return task
