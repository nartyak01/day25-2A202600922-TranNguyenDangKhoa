"""Populate Redis with sample cache entries and print CLI evidence."""
from __future__ import annotations

import subprocess
import sys

from reliability_lab.cache import SharedRedisCache


def main() -> None:
    cache = SharedRedisCache(
        redis_url="redis://localhost:6379/0",
        ttl_seconds=300,
        similarity_threshold=0.92,
        prefix="rl:cache:",
    )
    if not cache.ping():
        print("Redis not available — start with: docker compose up -d", file=sys.stderr)
        sys.exit(1)

    cache.flush()
    cache.set("What is the refund policy?", "[primary] reliable answer for: What is the refund policy?")
    cache.set("How do I reset my API key?", "[primary] reliable answer for: How do I reset my API key?")

    print("=== SharedRedisCache evidence ===")
    c1 = SharedRedisCache("redis://localhost:6379/0", 300, 0.92, "rl:cache:")
    c2 = SharedRedisCache("redis://localhost:6379/0", 300, 0.92, "rl:cache:")
    val, score = c2.get("What is the refund policy?")
    print(f"Instance c2 read from c1 write: value={val!r}, score={score}")

    print("\n=== redis-cli KEYS rl:cache:* ===")
    try:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "redis", "redis-cli", "KEYS", "rl:cache:*"],
            capture_output=True,
            text=True,
            check=False,
        )
        print(result.stdout.strip() or "(no keys)")
        if result.stderr:
            print(result.stderr.strip(), file=sys.stderr)
    except FileNotFoundError:
        import redis as redis_lib

        r = redis_lib.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
        keys = list(r.scan_iter("rl:cache:*"))
        print("\n".join(keys) if keys else "(no keys)")
        r.close()

    cache.close()
    c1.close()
    c2.close()


if __name__ == "__main__":
    main()
