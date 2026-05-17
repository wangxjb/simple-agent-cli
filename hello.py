def hello_world(name: str = "World") -> str:
    """返回问候语"""
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(hello_world())
    print(hello_world("张三"))
