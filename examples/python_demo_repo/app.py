from service import TaskService


class DemoApp:
    def run(self) -> str:
        service = TaskService()
        return service.execute("  demo  ")
