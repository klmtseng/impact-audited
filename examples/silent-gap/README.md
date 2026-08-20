# Silent-gap fixture

A fake graph backend reports `caller_a.py` and `caller_b.py`.
The lexical floor also finds `caller_c.py`. That disagreement is the product.

No GitNexus, no network, no extra dependencies:

```bash
python3 examples/silent-gap/run_demo.py
```

Last line when the fixture is intact:

```text
Demo PASS: expected FAIL reproduced (missing caller_c.py)
```
