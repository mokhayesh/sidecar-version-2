# tools/patch_fonts.py
import re
from pathlib import Path

p = Path("app/main_window.py")
src = p.read_text(encoding="utf-8")

# Ensure mkfont helper exists (idempotent insert at top if missing)
if "def mkfont(" not in src:
    helper = """
def mkfont(size: int, *, bold: bool = False, italic: bool = False,
          family: int = wx.FONTFAMILY_SWISS) -> wx.Font:
    info = wx.FontInfo(size).Family(family)
    if italic:
        info = info.Italic()
    if bold:
        info = info.Bold()
    return wx.Font(info)
"""
    # inject after first import wx
    src = re.sub(r"(import wx[^\n]*\n)",
                 r"\\1" + helper + "\n",
                 src, count=1)

# Pattern: wx.Font(size, family, style, weight)
FONT_CALL = re.compile(
    r"wx\.Font\s*\(\s*(\d+)\s*,\s*(wx\.[A-Z_]+)\s*,\s*(wx\.[A-Z_]+)\s*,\s*(wx\.[A-Z_]+)\s*\)"
)

def repl(m):
    size, family, style, weight = m.groups()
    bold = "BOLD" in weight
    italic = "ITALIC" in style
    fam = family  # keep whatever family they used
    return f"mkfont({size}, bold={str(bold)}, italic={str(italic)}, family={fam})"

src2 = FONT_CALL.sub(repl, src)

# Also handle 3-arg forms: wx.Font(size, family, style)
FONT_CALL3 = re.compile(
    r"wx\.Font\s*\(\s*(\d+)\s*,\s*(wx\.[A-Z_]+)\s*,\s*(wx\.[A-Z_]+)\s*\)"
)
def repl3(m):
    size, family, style = m.groups()
    italic = "ITALIC" in style
    return f"mkfont({size}, italic={str(italic)}, family={family})"

src2 = FONT_CALL3.sub(repl3, src2)

# Handle simple: wx.Font(size)
FONT_CALL1 = re.compile(r"wx\.Font\s*\(\s*(\d+)\s*\)")
src2 = FONT_CALL1.sub(lambda m: f"mkfont({m.group(1)})", src2)

p.write_text(src2, encoding="utf-8")
print("Patched fonts in", p)
