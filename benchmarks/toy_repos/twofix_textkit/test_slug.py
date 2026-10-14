from slug import slugify
def test_basic(): assert slugify("Hello, World!") == "hello-world"
def test_runs(): assert slugify("  a -- b  ") == "a-b"
