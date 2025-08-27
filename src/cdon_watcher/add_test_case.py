#!/usr/bin/env python3
"""
Helper script to add new test cases to test_data.json
"""

import argparse
import json
import os
import re
import sys
from typing import Any
from urllib.parse import urlparse


def validate_url(url: str) -> bool:
    """Validate that the URL is a CDON product URL"""
    try:
        parsed = urlparse(url)
        return parsed.netloc == "cdon.fi" and "/tuote/" in parsed.path
    except Exception:
        return False


def determine_format_from_title(title: str) -> str:
    """Determine format from title"""
    title_lower = title.lower()
    if "4k" in title_lower or "uhd" in title_lower or "ultra hd" in title_lower:
        return "4K Blu-ray"
    elif "blu-ray" in title_lower or "bluray" in title_lower:
        return "Blu-ray"
    else:
        return "DVD"


def generate_test_name(title: str, url: str) -> str:
    """Generate a test case name from title"""
    # Extract movie name and clean it up
    name = title.lower()
    # Remove format info
    name = re.sub(r"\s*\([^)]*\)\s*", " ", name)
    name = re.sub(r"\s*-\s*(blu-ray|4k|uhd|dvd).*", "", name)
    # Clean up and make safe filename
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    name = name[:30]  # Limit length

    # If name is too short or generic, use URL ID
    if len(name) < 5:
        url_match = re.search(r"/([^/]+)/?$", url.rstrip("/"))
        if url_match:
            name = url_match.group(1).replace("-", "_")[:30]

    return name


def load_test_data() -> dict[str, Any]:
    """Load existing test data"""
    test_data_path = os.path.join(os.path.dirname(__file__), "test_data.json")

    if os.path.exists(test_data_path):
        with open(test_data_path) as f:
            data: dict[str, Any] = json.load(f)
            return data
    else:
        return {"test_cases": []}


def save_test_data(data: dict[str, Any]) -> None:
    """Save test data to JSON file"""
    test_data_path = os.path.join(os.path.dirname(__file__), "test_data.json")

    with open(test_data_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_test_case(
    url: str,
    title: str,
    format_type: str | None = None,
    price_min: float = 10.0,
    price_max: float = 100.0,
    notes: str = "",
    active: bool = True,
) -> bool:
    """Add a new test case"""

    # Validate inputs
    if not validate_url(url):
        raise ValueError(f"Invalid CDON URL: {url}")

    if not title or len(title.strip()) < 5:
        raise ValueError("Title must be at least 5 characters long")

    # Auto-detect format if not provided
    if not format_type:
        format_type = determine_format_from_title(title)

    # Generate test name
    test_name = generate_test_name(title, url)

    # Load existing data
    data = load_test_data()

    # Check for duplicates
    existing_names = [case["name"] for case in data["test_cases"]]
    existing_urls = [case["url"] for case in data["test_cases"]]

    if test_name in existing_names:
        # Make name unique
        counter = 1
        original_name = test_name
        while test_name in existing_names:
            test_name = f"{original_name}_{counter}"
            counter += 1

    if url in existing_urls:
        print(f"Warning: URL {url} already exists in test data")
        return False

    # Create new test case
    new_case = {
        "name": test_name,
        "url": url,
        "expected_title": title.strip(),
        "expected_format": format_type,
        "price_range": {"min": price_min, "max": price_max},
        "active": active,
        "notes": notes,
    }

    # Add to data
    data["test_cases"].append(new_case)

    # Save
    save_test_data(data)

    print(f"✓ Added test case: {test_name}")
    print(f"  URL: {url}")
    print(f"  Title: {title}")
    print(f"  Format: {format_type}")
    print(f"  Price range: €{price_min}-{price_max}")

    return True


def list_test_cases() -> None:
    """List all test cases"""
    data = load_test_data()

    print(f"Total test cases: {len(data['test_cases'])}")
    print()

    for case in data["test_cases"]:
        status = "✓" if case.get("active", True) else "✗"
        print(f"{status} {case['name']}")
        print(f"  {case['expected_title']} ({case['expected_format']})")
        print(f"  €{case['price_range']['min']}-{case['price_range']['max']}")
        if case.get("notes"):
            print(f"  Note: {case['notes']}")
        print()


def deactivate_test_case(name: str) -> bool:
    """Deactivate a test case"""
    data = load_test_data()

    for case in data["test_cases"]:
        if case["name"] == name:
            case["active"] = False
            save_test_data(data)
            print(f"✓ Deactivated test case: {name}")
            return True

    print(f"✗ Test case not found: {name}")
    return False


def activate_test_case(name: str) -> bool:
    """Activate a test case"""
    data = load_test_data()

    for case in data["test_cases"]:
        if case["name"] == name:
            case["active"] = True
            save_test_data(data)
            print(f"✓ Activated test case: {name}")
            return True

    print(f"✗ Test case not found: {name}")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage CDON scraper test cases")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a new test case")
    add_parser.add_argument("--url", required=True, help="CDON product URL")
    add_parser.add_argument("--title", required=True, help="Expected movie title")
    add_parser.add_argument("--format", help="Format (Blu-ray, 4K Blu-ray, DVD)")
    add_parser.add_argument("--price-min", type=float, default=10.0, help="Minimum expected price")
    add_parser.add_argument("--price-max", type=float, default=100.0, help="Maximum expected price")
    add_parser.add_argument("--notes", default="", help="Optional notes")
    add_parser.add_argument("--inactive", action="store_true", help="Add as inactive test case")

    # List command
    subparsers.add_parser("list", help="List all test cases")

    # Activate/deactivate commands
    activate_parser = subparsers.add_parser("activate", help="Activate a test case")
    activate_parser.add_argument("name", help="Test case name")

    deactivate_parser = subparsers.add_parser("deactivate", help="Deactivate a test case")
    deactivate_parser.add_argument("name", help="Test case name")

    args = parser.parse_args()

    if args.command == "add":
        try:
            success = add_test_case(
                url=args.url,
                title=args.title,
                format_type=args.format,
                price_min=args.price_min,
                price_max=args.price_max,
                notes=args.notes,
                active=not args.inactive,
            )
            sys.exit(0 if success else 1)
        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

    elif args.command == "list":
        list_test_cases()

    elif args.command == "activate":
        success = activate_test_case(args.name)
        sys.exit(0 if success else 1)

    elif args.command == "deactivate":
        success = deactivate_test_case(args.name)
        sys.exit(0 if success else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
