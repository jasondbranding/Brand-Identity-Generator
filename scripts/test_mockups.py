import json
import os
from pathlib import Path
from dotenv import load_dotenv

from src.director import BrandDirectionsOutput
from src.generator import DirectionAssets
from src.mockup_compositor import composite_all_mockups


class MockColor:
    def __init__(self, hex_code):
        self.hex = hex_code

class MockDirection:
    def __init__(self, d):
        self.option_number = d.get('option_number', 1)
        self.direction_name = d.get('direction_name', 'Test')
        self.colors = [MockColor(c.get('hex', '#000000')) for c in d.get('colors', [])]

def test_mockups():
    load_dotenv()
    run_dir = Path("outputs/bot_20260225_190109")
    json_path = run_dir / "directions.json"
    
    if not json_path.exists():
        print("Test data not found.")
        return
        
    data = json.loads(json_path.read_text())
    
    all_assets = {}
    for d_data in data.get("directions", []):
        d = MockDirection(d_data)
        slug = d.direction_name.lower().replace(" ", "_")
        slug = "".join(c for c in slug if c.isalnum() or c == "_")
        slug = slug[:30]
        opt_dir = run_dir / f"option_{d.option_number}_{slug}"
        
        assets = DirectionAssets(
            direction=d,
            background=opt_dir / "background.png",
            logo=opt_dir / "logo.png",
            pattern=opt_dir / "pattern.png"
        )
        assets.logo = opt_dir / "logo.png"
        assets.logo_transparent = opt_dir / "logo_transparent.png"
        assets.logo_white = opt_dir / "logo_white.png"
        assets.logo_black = opt_dir / "logo_black.png"
        assets.pattern = opt_dir / "pattern.png"
        assets.background = opt_dir / "background.png"
        assets.palette_png = opt_dir / "palette.png"
        assets.shades_png = opt_dir / "shades.png"
        
        all_assets[d.option_number] = assets
        
    print("Starting mockup composition test...")
    results = composite_all_mockups(all_assets)
    print("Done!")
    for opt, mockups in results.items():
        print(f"Option {opt} generated {len(mockups)} mockups.")

if __name__ == "__main__":
    test_mockups()
