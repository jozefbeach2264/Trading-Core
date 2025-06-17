from queue import Queue

class MessageQueue:
    def __init__(self):
        self.queue = Queue()

    def push(self, msg):
        self.queue.put(msg)

    def pull(self):
        return self.queue.get()