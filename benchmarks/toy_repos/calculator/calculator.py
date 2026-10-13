"""Bug: Calculator returns wrong result for division by zero."""


def calculator(a: float, b: float, operation: str) -> float:
    """Perform calculation."""
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        return a / b
    else:
        raise ValueError(f"Unknown operation: {operation}")
