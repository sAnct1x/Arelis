"""Quick validation script for OCR and SQL tools with matrix fixtures."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def validate_sql_tool():
    """Validate SQL tool can query the matrix sales.csv fixture."""
    print("Validating SQL tool...")
    
    from arelis.tools.sql_query import SqlTool
    from arelis.workspace import WorkspaceRoots
    
    # Set up paths like live_matrix does
    matrix = ROOT / "outputs" / "test_matrix"
    work = matrix / "work"
    work.mkdir(parents=True, exist_ok=True)
    
    # Create sales.csv fixture
    (work / "sales.csv").write_text(
        "region,revenue\nnorth,100\nnorth,150\nsouth,250\neast,100\nwest,150\n",
        encoding="ascii",
    )
    print(f"  Created fixture: {work / 'sales.csv'}")
    print(f"  File exists: {(work / 'sales.csv').is_file()}")
    
    # Create tool with workspace
    workspace = WorkspaceRoots.from_paths([str(matrix)])
    tool = SqlTool(workspace)
    print(f"  Workspace roots: {[str(r.path) for r in workspace.roots]}")
    
    # Test resolution
    try:
        resolved = workspace.resolve_read("work/sales.csv")
        print(f"  Resolved path: {resolved.path}")
        print(f"  Resolved exists: {resolved.path.is_file()}")
    except Exception as e:
        print(f"  Resolution failed: {e}")
        return False
    
    # Query for max revenue
    result = await tool.run(
        sql="SELECT MAX(revenue) as max_revenue FROM data",
        path="work/sales.csv",
    )
    
    print(f"  SQL ok: {result.ok}")
    print(f"  Output: {result.output[:200]}")
    
    if result.ok and "250" in result.output:
        print("✓ SQL tool validated successfully")
        return True
    else:
        print("✗ SQL tool validation failed")
        return False


async def validate_ocr_tool():
    """Validate OCR tool can read data-dir-relative paths from image_edit."""
    print("\nValidating OCR tool...")
    
    from PIL import Image, ImageDraw, ImageFont

    from arelis.tools.ocr import OcrTool, tesseract_available
    from arelis.workspace import WorkspaceRoots
    
    if not tesseract_available():
        print("  Tesseract not available, skipping OCR validation")
        return True
    
    # Set up paths
    matrix = ROOT / "outputs" / "test_matrix"
    work = matrix / "work"
    data = matrix / "data"
    images = data / "outputs" / "images"
    images.mkdir(parents=True, exist_ok=True)
    
    # Create invoice.png fixture in work/ (original location)
    def font(size: int):
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except OSError:
            return ImageFont.load_default()
    
    img = Image.new("RGB", (1000, 300), "white")
    dr = ImageDraw.Draw(img)
    dr.text((40, 40), "INVOICE 88", fill="black", font=font(64))
    dr.text((40, 150), "Amount due: $1250.00", fill="black", font=font(64))
    img.save(work / "invoice.png")
    print(f"  Created fixture: {work / 'invoice.png'}")
    
    # Create grayscale version in outputs/images/ (where image_edit saves)
    gray = img.convert("L")
    gray.save(images / "invoice-gray.png")
    print(f"  Created grayscale: {images / 'invoice-gray.png'}")
    
    # Set data dir env var
    import os
    os.environ["ARELIS_DATA_DIR"] = str(data)
    
    # Create tool
    workspace = WorkspaceRoots.from_paths([str(matrix)])
    tool = OcrTool(workspace)
    
    # Test reading data-dir-relative path (the fix we added)
    result = await tool.run(action="text", path="outputs/images/invoice-gray.png")
    
    print(f"  OCR ok: {result.ok}")
    print(f"  Output: {result.output[:200] if result.output else 'None'}")
    
    if result.ok and ("1250" in result.output or "1250" in str(result.data)):
        print("✓ OCR tool validated successfully")
        return True
    else:
        print("✗ OCR tool validation failed")
        return False


async def main():
    """Run all validations."""
    print("=" * 60)
    print("Tool Validation Script")
    print("=" * 60)
    
    results = []
    
    try:
        results.append(await validate_sql_tool())
    except Exception as e:
        print(f"✗ SQL validation error: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)
    
    try:
        results.append(await validate_ocr_tool())
    except Exception as e:
        print(f"✗ OCR validation error: {e}")
        import traceback
        traceback.print_exc()
        results.append(False)
    
    print("\n" + "=" * 60)
    if all(results):
        print("All validations passed!")
        return 0
    else:
        print("Some validations failed")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
