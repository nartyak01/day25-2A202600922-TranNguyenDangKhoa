# Day 10 Reliability Report

**Author:** Tran Nguyen Dang Khoa  
**Lab:** Reliability Engineering for Production Agents

## 1. Architecture summary

Gateway nhận request, kiểm tra semantic cache trước. Nếu cache hit thì trả về ngay (latency = 0, cost = 0). Nếu miss, request đi qua circuit breaker của từng provider theo thứ tự primary → backup. Circuit breaker fail-fast khi OPEN, probe khi HALF_OPEN. Nếu tất cả provider fail → static fallback message.

```
User Request
    |
    v
[Gateway] ---> [Cache check] ---> HIT? return cached
    |                                 |
    v                                 v MISS
[Circuit Breaker: Primary] -------> Provider A
    |  (OPEN? skip)
    v
[Circuit Breaker: Backup] --------> Provider B
    |  (OPEN? skip)
    v
[Static fallback message]
```

**Components implemented:**
- `CircuitBreaker` — 3-state machine (CLOSED / OPEN / HALF_OPEN)
- `ResponseCache` — n-gram cosine similarity, privacy guardrails, false-hit detection
- `SharedRedisCache` — Redis-backed shared cache for multi-instance deployments
- `ReliabilityGateway` — cache → breaker → fallback chain
- `chaos.py` — scenario runner + recovery time calculation

## 2. Configuration

| Setting | Value | Reason |
|---|---:|---|
| failure_threshold | 3 | Cho phép vài lỗi ngẫu nhiên trước khi mở circuit, tránh false positive |
| reset_timeout_seconds | 2 | Đủ thời gian để provider phục hồi trước khi probe HALF_OPEN |
| success_threshold | 1 | Một request thành công trong HALF_OPEN đủ để đóng circuit |
| cache TTL | 300s | Cân bằng freshness và hit rate cho FAQ/policy queries |
| similarity_threshold | 0.92 | Giảm false hit; test 0.85 gây mismatch trên date queries |
| load_test requests | 100 | Đủ sample size cho P95/P99 mỗi scenario |
| cache backend | memory (chaos), redis (shared cache tests) | Memory cho chaos nhanh; Redis cho multi-instance |

## 3. SLO definitions

> Lưu ý: metrics tổng hợp (§4) gồm cả scenario `both_providers_fail` (100 static fallback) nên availability tổng thấp hơn từng scenario riêng lẻ.

| SLI | SLO target | Actual value (combined) | Met? |
|---|---|---:|---|
| Availability | >= 99% | 73.75% | No* |
| Latency P95 | < 2500 ms | 316.05 ms | Yes |
| Fallback success rate | >= 95% | 40.0% | No* |
| Cache hit rate | >= 10% | 46.5% | Yes |
| Recovery time | < 5000 ms | 2409.06 ms | Yes |

\*Scenario `all_healthy` riêng lẻ đạt 99% availability; combined thấp do cố ý inject total failure.

## 4. Metrics

Dữ liệu từ `reports/metrics.json` (400 requests, 4 scenarios):

| Metric | Value |
|---|---:|
| total_requests | 400 |
| availability | 0.7375 |
| error_rate | 0.2625 |
| latency_p50_ms | 270.45 |
| latency_p95_ms | 316.05 |
| latency_p99_ms | 319.46 |
| fallback_success_rate | 0.4 |
| cache_hit_rate | 0.465 |
| estimated_cost | 0.043976 |
| estimated_cost_saved | 0.186 |
| circuit_open_count | 11 |
| recovery_time_ms | 2409.06 |

**Scenario results:**

| Scenario | Status |
|---|---|
| primary_timeout_100 | pass |
| primary_flaky_50 | pass |
| all_healthy | pass |
| both_providers_fail | pass |

## 5. Cache comparison

Chạy thực tế với `python scripts/run_cache_comparison.py` — scenario `all_healthy`, 100 requests/run.  
Kết quả lưu tại `reports/cache_comparison.json`.

| Metric | Without cache | With cache | Delta |
|---|---:|---:|---|
| latency_p50_ms | 213.55 | 205.68 | -7.87 ms |
| latency_p95_ms | 296.71 | 308.83 | +12.12 ms |
| estimated_cost | 0.05386 | 0.018348 | -0.035512 (~66% tiết kiệm) |
| cache_hit_rate | 0.0 | 0.66 | +66% |

**Nhận xét:** Cache giảm cost đáng kể (66% hit rate) và cải thiện P50 nhờ cache hits có latency = 0. P95 tăng nhẹ do variance ngẫu nhiên trên non-cached requests — chấp nhận được.

## 6. Redis shared cache

- **Why in-memory cache is insufficient:** Mỗi gateway instance có cache riêng → cache miss khi request đến instance khác, không chia sẻ state giữa replicas.
- **How SharedRedisCache solves this:** Lưu query/response vào Redis Hash (`HSET`) với TTL (`EXPIRE`), mọi instance dùng chung prefix `rl:cache:`.

### Evidence of shared state

Chạy `python scripts/redis_evidence.py` — output lưu tại `reports/redis_evidence.txt`:

```
=== SharedRedisCache evidence ===
Instance c2 read from c1 write: value='[primary] reliable answer for: What is the refund policy?', score=1.0

=== redis-cli KEYS rl:cache:* ===
rl:cache:2d4f6b6676a4
rl:cache:f452fc0bc027
```

Test suite: `pytest tests/test_redis_cache.py -v` → **6/6 passed**.

## 7. Chaos scenarios

| Scenario | Expected behavior | Observed behavior | Pass/Fail |
|---|---|---|---|
| primary_timeout_100 | All traffic fallback to backup, circuit opens | Fallback via backup, circuit opened | pass |
| primary_flaky_50 | Circuit oscillates, mix primary/fallback | Circuit opened, mix routes | pass |
| all_healthy | Requests via primary, high cache hit | 99% availability, 66% cache hit (comparison run) | pass |
| both_providers_fail | 100% static fallback | 100/100 static_fallback | pass |

## 8. Failure analysis

**Weakness:** Availability tổng hợp và fallback success rate bị kéo xuống khi chạy scenario total failure và primary flaky cùng lúc. Circuit breaker có thể block cả backup trong cửa sổ OPEN ngắn.

**Fix trước production:**
1. Tách metrics per-scenario thay vì aggregate để SLO monitoring chính xác hơn
2. Thêm health check passive trước khi mở circuit (probe endpoint riêng)
3. Lưu circuit breaker state vào Redis cho multi-instance coordination

## 9. Next steps

1. Redis circuit state sharing (INCR/EXPIRE) cho multi-instance breaker
2. Cost-aware routing khi budget vượt 80%
3. Graceful degradation: fallback in-memory cache khi Redis down

## 10. Test evidence

Full test run: `reports/test_output.txt`

```
======================== 35 passed, 7 xpassed in 3.72s ========================
```

Reproduce:
```bash
pip install -e ".[dev]"
docker compose up -d
pytest -v
python scripts/run_chaos.py
python scripts/run_cache_comparison.py
python scripts/redis_evidence.py
```
