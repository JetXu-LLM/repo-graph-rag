class Worker:
    def prepare(self, value: str) -> str:
        return value.strip().upper()

    def work(self, value: str) -> str:
        prepared = self.prepare(value)
        return f"WORKER:{prepared}"
