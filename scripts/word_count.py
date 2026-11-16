#!/usr/bin/env python3
"""Count words in a file."""

import sys


def count_words(filepath: str) -> int:
    with open(filepath, 'r') as f:
        text = f.read()
    return len(text.split())


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python word_count.py <filepath>")
        sys.exit(1)

    filepath = sys.argv[1]
    try:
        count = count_words(filepath)
        print(f"Word count: {count}")
    except FileNotFoundError:
        print(f"Error: File '{filepath}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)