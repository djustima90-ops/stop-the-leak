"""Supabase client singleton for Stop the Leak."""

import os
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

_client: Optional[Client] = None


def get_supabase() -> Client:
    """Return a memoized Supabase client.

    Reads SUPABASE_URL and SUPABASE_KEY from the environment. Raises
    RuntimeError if either is missing so callers see a clear failure
    rather than a cryptic SDK error.
    """
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set in the environment."
        )

    _client = create_client(url, key)
    return _client
