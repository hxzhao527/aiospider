#!/usr/bin/python3
#-*- coding:utf-8 -*-

'''
Asyncio.Queue's task_done only reduce the number of unfinished tasks.
This spider need a queue which used to contain running-task. So it need one method to remove finished tasks.
So asyncio.Queue is not suitable. Burt inheritance failed me. So I just copy asyncio.Queue and do some changes.
'''
import collections
import asyncio
import uuid
from asyncio import events, locks, QueueFull

_Task = collections.namedtuple("Task", ["UUID", "task", "args"])


def makeTask(task, args):
    return _Task(uuid.uuid4(), task, args)


class TaskQueue:

    def __init__(self, maxsize=0, *, loop=None):
        if loop is None:
            self._loop = events.get_event_loop()
        else:
            self._loop = loop
        self._maxsize = maxsize

        # Futures.
        self._putters = collections.deque()

        self._running_tasks = 0
        self._finished = locks.Event(loop=self._loop)
        self._finished.set()
        self._init(maxsize)

    def _init(self, maxsize):
        self._queue = collections.OrderedDict()

    def _put(self, task: _Task):
        async def _call(UUID=task.UUID):
            await task.task(task.args)
            self.task_done(str(UUID))
        
        self._queue.update(
            {str(task.UUID): asyncio.ensure_future(_call())})

    def _wakeup_next(self, waiters):
        # Wake up the next waiter (if any) that isn't cancelled.
        while waiters:
            waiter = waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                break

    def __repr__(self):
        return '<{} at {:#x} {}>'.format(
            type(self).__name__, id(self), self._format())

    def __str__(self):
        return '<{} {}>'.format(type(self).__name__, self._format())

    def _format(self):
        result = 'maxsize={!r}'.format(self._maxsize)
        if getattr(self, '_queue', None):
            result += ' _queue={!r}'.format(dict(self._queue))
        if self._getters:
            result += ' _getters[{}]'.format(len(self._getters))
        if self._putters:
            result += ' _putters[{}]'.format(len(self._putters))
        if self._unfinished_tasks:
            result += ' tasks={}'.format(self._unfinished_tasks)
        return result

    def qsize(self):
        """Number of items in the queue."""
        return len(self._queue)

    @property
    def maxsize(self):
        """Number of items allowed in the queue."""
        return self._maxsize

    def empty(self):
        """Return True if the queue is empty, False otherwise."""
        return not self._queue

    def full(self):
        """Return True if there are maxsize items in the queue.

        Note: if the Queue was initialized with maxsize=0 (the default),
        then full() is never True.
        """
        if self._maxsize <= 0:
            return False
        else:
            return self.qsize() >= self._maxsize

    async def put(self, task: _Task):
        """Put an item into the queue.

        Put an item into the queue. If the queue is full, wait until a free
        slot is available before adding item.

        This method is a coroutine.
        """
        while self.full():
            putter = self._loop.create_future()
            self._putters.append(putter)
            try:
                await putter
            except:
                putter.cancel()  # Just in case putter is not done yet.
                if not self.full() and not putter.cancelled():
                    # We were woken up by get_nowait(), but can't take
                    # the call.  Wake up the next in line.
                    self._wakeup_next(self._putters)
                raise
        return self.put_nowait(task)

    def put_nowait(self, task: _Task):
        """Put an item into the queue without blocking.

        If no free slot is immediately available, raise QueueFull.
        """
        if self.full():
            raise QueueFull
        self._put(task)
        self._finished.clear()

    def task_done(self, tag):
        if self.qsize() <= 0:
            raise ValueError('task_done(**) called too many times')
        if not tag in self._queue:
            print(tag)
            raise KeyError("This task isn't in this queue")
        self._queue.pop(tag)
        self._wakeup_next(self._putters)
        if self.qsize() == 0:
            self._finished.set()

    async def join(self):
        """Block until all items in the queue have been gotten and processed.

        The count of unfinished tasks goes up whenever an item is added to the
        queue. The count goes down whenever a consumer calls task_done() to
        indicate that the item was retrieved and all work on it is complete.
        When the count of unfinished tasks drops to zero, join() unblocks.
        """
        if self.qsize() > 0:
            await self._finished.wait()
