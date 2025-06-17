
import tracemalloc

def capture_memory_snapshot():
    tracemalloc.start()
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')
    return top_stats[:10]