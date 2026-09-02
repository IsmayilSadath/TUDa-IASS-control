# Tests

Run the regression suite from the repository root:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

The tests load selected production classes with mocks and do not initialize Raspberry Pi GPIO pins.
