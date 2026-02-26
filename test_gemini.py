import os
from pathlib import Path
from google import genai
from google.genai import types

api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

image_path = Path("/Users/sondao/brand-identity-generator/references/logos/industry_education_edtech/1226f9ea4216723f985b9bfba51ad169.jpg")
img_bytes = image_path.read_bytes()

prompt = """\
You are a professional brand identity analyst. Analyze this logo/mark image.

Return ONLY a valid JSON object with EXACTLY these fields — no explanation, no markdown fences:

{
  "form": "<one of: wordmark, lettermark, monogram, symbol, combination, emblem, abstract>",
  "style": ["<2-4 from: geometric, organic, monoline, filled, 3d, minimal, detailed, flat, gradient, textured, sharp, rounded, hand-drawn, pixel, retro, modern, classic, brutalist, elegant, playful>"],
  "technique": ["<1-3 from: negative space, grid construction, golden ratio, symmetry, asymmetry, optical illusion, line weight, counter forms, modularity, overlap, fragmentation, rotation>"],
  "industry": ["<1-3 from: tech, saas, fintech, crypto, web3, healthcare, ecommerce, education, real-estate, food, beverage, fashion, automotive, media, consulting, startup, enterprise, creative, nonprofit, gaming>"],
  "mood": ["<2-4 from: confident, calm, bold, playful, serious, premium, accessible, warm, cold, edgy, trustworthy, innovative, elegant, minimal, powerful, friendly, mysterious, dynamic, stable, futuristic>"],
  "colors": ["<1-3 from: monochrome, duo-tone, multi-color, gradient, dark, light, vibrant, muted, warm, cool, neutral, neon, pastel, earth-tone, metallic, high-contrast>"],
  "quality": <int 1-10: 6=ok, 7=professional, 8=very good, 9=excellent, 10=iconic>
}

Be specific — don't tag everything as "modern minimal". Look for real distinguishing features.
Quality: consider originality, craft, scalability, and memorability.
"""

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        types.Part.from_text(text=prompt),
        types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
    ],
    config=types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=512,
    ),
)
print("RAW OUTPUT:")
print("---")
print(response.text)
print("---")
