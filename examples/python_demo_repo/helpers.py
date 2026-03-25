class Formatter:
    def format(self, value: str) -> str:
        return f"[{value}]"


def finalize(value: str) -> str:
    formatter = Formatter()
    return formatter.format(value)
