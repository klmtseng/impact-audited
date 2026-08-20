#!/usr/bin/env python3
"""Pretend graph backend that silently omits caller_c.py.

The audited symbol is accepted for --graph template compatibility and ignored.
This is the 30-second FAIL fixture: no GitNexus, no network, no extra deps.
"""
import sys

_ = sys.argv[1:]
print("caller_a.py")
print("caller_b.py")
