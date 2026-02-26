# Instruction: Parallelize Mockup Compositing (AI-only, no Pillow)

## Mục tiêu
Chuyển toàn bộ mockup compositing từ serial → parallel bằng ThreadPoolExecutor.
Bỏ Pillow handler fallback — tất cả 10 mockups đều dùng Gemini AI reconstruction.

## Lý do
- Hiện tại `composite_all_mockups()` (line 1833) loop serial qua ~10 mockup files
- Mỗi mockup gọi `_ai_reconstruct_with_retry()` → 15-30s/mockup → tổng ~2.5-5 phút
- Chạy parallel 10 calls cùng lúc → rút xuống ~30-45s (thời gian của 1 mockup chậm nhất)

## Files cần sửa

### 1. `src/mockup_compositor.py`

#### A. Sửa `composite_all_mockups()` (line 1771-1896)

Thay vòng for serial:
```python
for mp_idx, mp in enumerate(processed_files, 1):
    ...  # serial loop
```

Bằng ThreadPoolExecutor:
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def _composite_one(mp, mp_idx, total_mp, assets, mockup_dir, brand_name, api_key):
    """Composite 1 mockup file (runs in worker thread)."""
    out_path = mockup_dir / (mp.stem + "_composite.png")

    # Extract zones
    zones = _extract_zones(mp)
    zone_text = _zones_to_text(zones)

    # Find original
    original_path = _find_original(mp)
    if not original_path:
        return None, mp.name, "original not found"

    # Build prompt
    mockup_key = MOCKUP_KEY_MAP.get(mp.name, "")
    prompt = build_mockup_prompt(mockup_key, assets, brand_name, zone_text=zone_text)

    # Choose logo variant (dark bg → white logo)
    DARK_BG_MOCKUPS = {
        "tote_bag_processed.jpg",
        "black_shirt_logo_processed.png",
        "tshirt_processed.png",
        "employee_id_card_processed.png",
    }
    if mp.name in DARK_BG_MOCKUPS:
        logo_for_ai = (
            assets.logo_white
            if (assets.logo_white and assets.logo_white.exists()
                and assets.logo_white.stat().st_size > 100)
            else assets.logo
        )
    else:
        logo_for_ai = (
            assets.logo_transparent
            if (assets.logo_transparent and assets.logo_transparent.exists()
                and assets.logo_transparent.stat().st_size > 100)
            else assets.logo
        )

    # AI reconstruction (Gemini) — NO Pillow handler
    ai_bytes = _ai_reconstruct_with_retry(
        original_path=original_path,
        full_prompt=prompt,
        logo_path=logo_for_ai,
        api_key=api_key,
        zones=zones,
    )

    if ai_bytes:
        out_path.write_bytes(ai_bytes)
        return out_path, mp.name, "ok"
    return None, mp.name, "all attempts failed"


# Trong composite_all_mockups(), thay serial loop bằng:
max_workers = min(len(processed_files), 10)
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {
        executor.submit(
            _composite_one, mp, idx, len(processed_files),
            assets, mockup_dir, brand_name, api_key
        ): mp
        for idx, mp in enumerate(processed_files, 1)
    }
    for future in as_completed(futures):
        mp = futures[future]
        try:
            result_path, name, status = future.result()
            if result_path:
                composited.append(result_path)
                ok_count += 1
                console.print(f"  [green]✓[/green] {name} (AI) → {result_path.name}")
            else:
                fail_count += 1
                console.print(f"  [yellow]⚠ {name}: {status}[/yellow]")
        except Exception as exc:
            fail_count += 1
            console.print(f"  [yellow]✗ {mp.name}: {exc}[/yellow]")
```

#### B. Sửa `composite_single_mockup()` (line 1899-1998)

Bỏ Strategy 1 (Pillow handler). Chỉ giữ Strategy 2 (AI reconstruction).

Xoá block:
```python
# ── Strategy 1: Pillow-based compositing (deterministic, pixel-perfect) ──
handler = HANDLER_MAP.get(processed_file.name)
if handler:
    try:
        ...
    except Exception as pillow_err:
        ...
```

Giữ nguyên phần AI reconstruction từ line 1960 trở xuống.

## Lưu ý quan trọng

1. **Rate limiting**: 10 concurrent Gemini calls có thể trigger rate limit. `_ai_reconstruct_with_retry()` đã có exponential backoff cho `_RateLimitError` — nên giữ nguyên logic đó.

2. **Thread safety**: `console.print()` từ Rich Console là thread-safe. `Path.write_bytes()` ghi vào file khác nhau nên không conflict.

3. **max_workers = 10**: Gemini API cho phép concurrent requests. Nếu bị rate limit nhiều quá, có thể giảm xuống 5-6.

4. **KHÔNG sửa** `_ai_reconstruct_with_retry()`, `_ai_reconstruct_mockup()`, `build_mockup_prompt()` — giữ nguyên logic retry/fallback.

## Kết quả kỳ vọng

| Metric | Trước | Sau |
|--------|-------|-----|
| 10 mockups compositing | ~2.5-5 phút (serial) | ~30-60s (parallel) |
| API calls | 10 serial | 10 concurrent |
| Pillow handlers | 10 handlers (local) | Bỏ, dùng AI hết |
