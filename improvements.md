# Project Improvements

This document outlines a plan to improve the structure and maintainability of the cdon-watcher project.

## 1. Single Source of Truth for Dependencies

**Issue:** The project currently has two files for managing dependencies: `pyproject.toml` and `requirements.txt`. This is redundant and can lead to inconsistencies.

**Solution:** The `pyproject.toml` file should be the single source of truth for all project dependencies. The `requirements.txt` file should be generated from `pyproject.toml` when needed (e.g., in the Docker build process).

**Action:**

1.  Remove the `requirements.txt` file from the project.
2.  Update the Dockerfile to generate the `requirements.txt` file from `pyproject.toml` before installing the dependencies. This can be done by adding the following command to the Dockerfile:

    ```bash
    RUN pip install poetry && poetry export -f requirements.txt --output requirements.txt --without-hashes
    ```

## 2. Refactor Legacy Tests

**Issue:** The `tests` directory contains `legacy_test_hybrid.py` and `legacy_test_single_url.py`. These tests are not integrated into the new `unit` and `integration` test structure.

**Solution:** The legacy tests should be refactored and moved into the appropriate `unit` or `integration` subdirectories. This will make the test suite more consistent and easier to maintain.

**Action:**

1.  Analyze the legacy tests to determine whether they are unit tests or integration tests.
2.  Refactor the tests to follow the same structure and conventions as the other tests in the project.
3.  Move the refactored tests to the appropriate `unit` or `integration` subdirectory.
4.  Remove the legacy test files.

## 3. Add `__init__.py` to `src`

**Issue:** The `src` directory does not contain an `__init__.py` file.

**Solution:** While not strictly necessary, adding an `__init__.py` file to the `src` directory can help with package discovery in some cases.

**Action:**

1.  Add an empty `__init__.py` file to the `src` directory.
