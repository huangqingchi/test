"""Render maintained .mmd sources to standalone SVG/PNG using Mermaid CLI."""

import argparse
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "docs" / "diagrams"


def fix_svg_size(path):
    """Give standalone SVGs intrinsic dimensions instead of the browser's 300x150 fallback."""
    content = path.read_text(encoding="utf-8")
    opening = re.search(r"<svg\b[^>]*>", content).group()
    box = re.search(r'viewBox="([^"]+)"', opening).group(1).split()
    dimensions = {"width": box[2], "height": box[3]}
    fixed = opening
    for name, value in dimensions.items():
        if re.search(rf'\b{name}="[^"]*"', fixed):
            fixed = re.sub(rf'\b{name}="[^"]*"', f'{name}="{value}"', fixed, count=1)
        else:
            fixed = fixed[:-1] + f' {name}="{value}">'
    path.write_text(content.replace(opening, fixed, 1), encoding="utf-8", newline="\n")


def write_gallery(items):
    cards = []
    for item in items:
        name, title = item["id"], html.escape(item["title"])
        cards.append(f'''<section id="{name}" class="card">
<div class="card-head"><h2>{title}</h2><nav><a href="{name}.svg" target="_blank">打开 SVG</a>
<a href="{name}.png" target="_blank">打开 PNG</a><a href="{name}.png" download>下载图片</a></nav></div>
<div class="controls"><button type="button" data-step="-0.25">缩小</button><button type="button" data-fit>适应宽度</button><button type="button" data-step="0.25">放大</button><output>100%</output></div>
<div class="viewport"><img src="{name}.svg" alt="{title}" loading="lazy"></div></section>''')
    navigation = "".join(f'<a href="#{x["id"]}">{html.escape(x["title"])}</a>' for x in items)
    page = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MiniMax-H3 项目流程图</title>
<style>
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f3f6fb;color:#172b4d;font:16px/1.6 "Microsoft YaHei",sans-serif}
header,main{max-width:1440px;margin:auto;padding:28px}h1{font-size:30px;margin:0 0 6px}header p{margin:0 0 18px;color:#53657d}
a{color:#2159a5;text-decoration:none}a:hover{text-decoration:underline}nav{display:flex;gap:18px;flex-wrap:wrap}
.card{background:white;border:1px solid #d9e3f0;border-radius:12px;margin-bottom:28px;overflow:hidden;scroll-margin-top:16px}
.card-head{padding:16px 22px;display:flex;align-items:center;justify-content:space-between;gap:16px;border-bottom:1px solid #e4ebf4;flex-wrap:wrap}
h2{font-size:20px;margin:0}.controls{padding:12px 22px;display:flex;gap:10px;align-items:center;background:#fbfcfe}
button{font:inherit;border:1px solid #c6d3e4;border-radius:6px;background:white;padding:4px 14px;cursor:pointer}button:hover{background:#eaf2ff}
output{font-size:14px;color:#53657d}.viewport{overflow:auto;max-height:82vh;padding:24px;text-align:center}.viewport img{display:block;margin:auto;width:auto;max-width:100%;height:auto}
footer{padding:0 28px 30px;max-width:1440px;margin:auto;color:#53657d}@media(max-width:700px){header,main{padding:14px}.viewport{padding:10px}.card-head{padding:14px}}
</style></head><body>
<header><h1>MiniMax-H3 项目流程图</h1><p>直接查看图形、箭头和分支。可离线打开，不依赖 Markdown 插件或在线服务。超出屏幕时可滚动或缩放。</p><nav>''' + navigation + '''</nav></header>
<main>''' + "\n".join(cards) + '''</main>
<footer>运行入口：bash setup.sh（仅环境） / bash deploy.sh（完整部署）。本页展示实现流程，不表示目标 GPU 实测已通过。</footer>
<script>
document.querySelectorAll('.card').forEach(card=>{
 const img=card.querySelector('img'),view=card.querySelector('.viewport'),out=card.querySelector('output');let zoom=1;
 function apply(){img.style.maxWidth='none';img.style.width=Math.max(100,(view.clientWidth-48)*zoom)+'px';out.textContent=Math.round(zoom*100)+'%'}
 card.querySelectorAll('[data-step]').forEach(button=>button.onclick=()=>{zoom=Math.max(.25,Math.min(4,zoom+Number(button.dataset.step)));apply()});
 card.querySelector('[data-fit]').onclick=()=>{zoom=1;apply()};
});
</script></body></html>
'''
    (DIRECTORY / "index.html").write_text(page, encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mmdc", default="mmdc", help="Path to Mermaid CLI; optional development tool")
    parser.add_argument("--browser", type=Path, help="Existing Chrome/Edge executable to avoid a browser download")
    args = parser.parse_args()
    executable = shutil.which(args.mmdc)
    if executable is None:
        raise SystemExit("Mermaid CLI not found; see docs/diagrams/README.md")
    executable = str(Path(executable).resolve())
    items = json.loads((DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="h3-diagrams-") as folder:
        config = Path(folder) / "browser.json"
        config.write_text(json.dumps({"executablePath": str(args.browser.resolve())} if args.browser else {}), encoding="utf-8")
        for item in items:
            for suffix in ("svg", "png"):
                command = [executable, "-i", str(DIRECTORY / (item["id"] + ".mmd")),
                           "-o", str(DIRECTORY / (item["id"] + "." + suffix)),
                           "-c", str(DIRECTORY / "mermaid.config.json"), "-p", str(config),
                           "-b", "white", "-w", "1800", "-s", "1.5"]
                subprocess.run(command, check=True, timeout=120)
                if suffix == "svg":
                    fix_svg_size(DIRECTORY / (item["id"] + ".svg"))
    write_gallery(items)
    print(f"View diagrams: {DIRECTORY / 'index.html'}")


if __name__ == "__main__":
    main()
