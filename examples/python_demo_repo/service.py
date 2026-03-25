from helpers import finalize
from workers import Worker


class TaskService:
    def execute(self, raw_value: str) -> str:
        worker = Worker()
        result = worker.work(raw_value)
        return finalize(result)
