"""Pytest configuration for shared test fixtures and setup."""

from pathlib import Path

from dotenv import load_dotenv


# Ensure the project's .env file is loaded for all tests so API keys and other
# configuration values are available without needing to export them manually.
ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env", override=False)

