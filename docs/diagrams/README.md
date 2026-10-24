# 直接查看流程图

打开 [index.html](index.html)，即可离线查看全部图形、缩放及下载，不需要 Markdown 扩展、Node.js 或网络。也可以直接打开下面的 PNG/SVG：

| 图形 | 图片 | 可缩放矢量图 |
| --- | --- | --- |
| 一键配置与完整部署 | [PNG](deployment.png) | [SVG](deployment.svg) |
| 模型下载与缓存恢复 | [PNG](cache.png) | [SVG](cache.svg) |
| 生成与产物验收 | [PNG](generation.png) | [SVG](generation.svg) |
| 失败、超时与取消 | [PNG](cancellation.png) | [SVG](cancellation.svg) |
| 模块调用关系 | [PNG](modules.png) | [SVG](modules.svg) |

`.mmd` 是维护用源文件；交付图形是 SVG/PNG，HTML 是本地查看入口。源码与图片一起维护，不能只更新源码却留下过期图片。

## 修改后重新生成

渲染工具仅用于文档维护，不属于模型运行依赖。参考工具版本是 `@mermaid-js/mermaid-cli@11.4.2`；使用本机已有 Chrome/Edge，或按照 Mermaid CLI 的安装要求准备浏览器。中文字体须在渲染机器可用，例如 Microsoft YaHei / Noto Sans CJK SC。

使用独立开发目录安装 CLI（此目录已被项目忽略）：

```bash
npm install --prefix .cache/docs-render --no-save --package-lock=false @mermaid-js/mermaid-cli@11.4.2
python scripts/render_diagrams.py --mmdc .cache/docs-render/node_modules/.bin/mmdc
```

如使用已有浏览器，可设置 `PUPPETEER_SKIP_DOWNLOAD=true` 跳过安装器下载浏览器，并通过 `--browser` 指定实际可执行文件。Windows 使用 `mmdc.cmd`，路径有空格时加引号。

`scripts/render_diagrams.py` 读取 `manifest.json`、`.mmd` 和 `mermaid.config.json`，生成五组 SVG/PNG 和 HTML 查看页。渲染后需实际打开图片，检查中文、分支、箭头与裁切，并检查 HTML 的链接/缩放。

生成前对照 [代码结构](../code_structure.md) 和 [项目代码流程说明](../code_flow.md)。模型、环境、模式或错误处理发生变化时同步更新相应图形。
