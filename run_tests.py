#!/usr/bin/env python
"""
Test runner with clean output.

Usage:
    python run_tests.py              # Run all tests with minimal output
    python run_tests.py -v           # Run with verbose output showing test names
"""

import sys
import unittest
import logging

# Completely disable INFO and DEBUG logging before any imports
logging.disable(logging.INFO)


def main():
    """Run tests with clean output."""
    # Check for verbose flag
    verbose = '-v' in sys.argv or '--verbose' in sys.argv
    
    # Discover and run tests
    loader = unittest.TestLoader()
    suite = loader.discover('tests', pattern='test_*.py')
    
    # Run with minimal or verbose output
    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
    result = runner.run(suite)
    
    # Exit with proper code
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
