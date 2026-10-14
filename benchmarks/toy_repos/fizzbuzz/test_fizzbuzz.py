from fizzbuzz import fizzbuzz

def test_length():
    assert len(fizzbuzz(15)) == 15

def test_values():
    assert fizzbuzz(15)[:5] == ["1", "2", "Fizz", "4", "Buzz"]

def test_fizzbuzz():
    assert fizzbuzz(15)[-1] == "FizzBuzz"
