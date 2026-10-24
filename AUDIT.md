# MiniMax-H3 部署审查与修正记录

## 2026-10-25：修正完整公开模型范围

之前实现把 t2va 冒烟测试范围当成了部署范围，遗漏了 `transformer_ref` 和两个工作流入口。本次按 既定步骤 先制定计划，再修改代码和测试。

| 项目 | 修正后行为 |
| --- | --- |
| 模型 | 固定 `MiniMaxAI/MiniMax-H3`，不替换为其他生成模型 |
| 完整下载 | 两套 transformer 和所有共享组件，固定 revision；元数据共 77 个文件，约 195.89GiB |
| 缓存升级 | 复用原 t2va 文件，补齐参考权重；新 schema/profile 的完整清单，旧部分清单不能通过 |
| 文生音视频 | `generate.py --workflow t2va` |
| 首尾帧 | `--workflow fl2va`，支持首帧、尾帧或两者 |
| 多模态参考 | `--workflow ref2va --reference 类型 路径`，支持有序图像/视频/音频混合输入 |
| 默认一键部署 | 环境适配 → 完整下载 → 三工作流索引检查 → 三流程实际 GPU 生成验收 |
| 测试分级 | `--test` 快速 t2va；`--test-all` 完整三流程；快速成功不等于全部成功 |
| 资源控制 | 按工作流分别启动进程，只加载该任务权重，避免两套 transformer 同时常驻 RAM |
| 验收报告 | 记录每个工作流 passed/failed/timeout/not_run；只有三项成功才设置 all_workflows_passed |
| 素材 | 自动生成诊断图片、2秒视频、音频；不是画质样片或正式基准 |

完整范围是公开本地的 H3-Base 三工作流。托管 H3-Context-IR / H3-Regenerate-2K 未公开的本地权重不能通过下载补齐；未集成其 API，不能声称它们已本地部署。[MiniMax 官方范围说明](https://github.com/MiniMax-AI/MiniMax-H3)

## 保留的环境与可靠性修复

- 自动选择稳定 Python 3.11–3.13，缺少时从现有 apt 源安装匹配的解释器/venv；不修改系统 Python 链接，不添加 PPA。
- 固定 torch/torchvision cu128 配对、直接依赖、Diffusers commit 与模型 revision；执行 pip check，记录实际依赖。
- 检查空闲显存、MemAvailable、cgroup v1/v2 及父级内存限额；CUDA 原生 BF16/矩阵乘法/attention 实测。
- 按缺失文件大小检查模型盘，分别检查环境/缓存/临时空间；不以 snapshots 目录存在判定下载完成。
- 本地固定 snapshot 和 local_files_only；加载时显式覆盖组件源，防止索引中的远程引用漂移。
- 模型加载前验证媒体组合、数量、文件、解码、参考时长；保留参考顺序与原始采样率。
- MP4 完整解码，检查 H.264/AAC、尺寸、帧数、帧率、声道和时长；临时文件验证通过后才替换目标。
- 同目录 flock、阶段日志、耗时、结果报告、LF 行尾、可选逐流程超时。

## 测试方法与边界

- 标准库回归：参数组合、引用顺序/数量、缓存升级、缺失权重、失败传播、部分通过、超时及快速测试不能冒充完整测试。
- Ubuntu Bash 编排：默认冷启动按顺序安装、完整下载、全流程验收；恢复模式、错误报告、不意外下载。使用替身命令测试编排，未执行真实大模型推理。
- 真实 CPU 集成：固定库版本导入、H.264/AAC 实际编码与解码、首/尾/首尾帧读取、图像/视频/音频混合参考解码和采样率、损坏/超长/过短媒体拒绝。
- 三工作流路由：固定官方 JSON 索引和临时的占位权重文件名，验证 t2va/fl2va 指向 transformer、ref2va 指向 transformer_ref；没有加载占位文件作为权重。
- GitHub Actions 同时运行脚本回归与真实 CPU 集成；以本次提交的运行结果为准。[CI 运行列表](https://github.com/huangqingchi/test/actions)

此前的依赖/CPU 检查记录：[2026-10-24](https://github.com/huangqingchi/test/actions/runs/40109323527)、[一键编排版本](https://github.com/huangqingchi/test/actions/runs/40118960726)。这些历史结果不能替代本次完整工作流修改的 CI，也不能替代 GPU 实测。

**仍待服务器实测：**完整权重实际下载、Linux CUDA wheel 运行、BF16 加载/CPU 卸载、三个工作流真实生成、资源峰值、耗时、画质和素材一致性。工作区仅完成可运行的本地/CI 检查，没有目标 GPU 验收记录。

## 仍存在的限制

- 直接依赖固定，间接依赖尚未形成全量 hash lock；已记录解析结果供后续复现。
- 文件清单检查存在性和大小，不能发现同大小内容损坏。
- 80GB/150GiB 是保守起点，不保证所有参考素材、分辨率和时长不 OOM；参考图像/视频编码尤其增加资源需求。
- 跨目录并发任务仍可能争抢 GPU；预检通过之后其他任务也可能占用资源。
- 默认完整验收测试三个代表性请求，不穷举所有首帧/尾帧组合与全部参考数量；画质需用真实业务素材验收。
- 当前不提供常驻 API、Docker 镜像、量化或多卡配置。此类扩展应独立固定版本、配置与测试。

## 上游依据

- [Diffusers 三工作流、两套权重及参考媒体接口](https://huggingface.co/docs/diffusers/main/en/api/pipelines/minimax_h3)
- [固定提交的组件加载实现](https://github.com/huggingface/diffusers/blob/aaf57d03a3edfbd9de457d2872417a92f149a91d/src/diffusers/modular_pipelines/modular_pipeline.py)
- [固定模型版本的文件元数据](https://huggingface.co/api/models/MiniMaxAI/MiniMax-H3/revision/42ed227ee7df40d41602854ae760620d6eb651fe?blobs=true)
- [PyTorch 配对版本表](https://pytorch.org/get-started/previous-versions/)
- [NVIDIA CUDA 兼容说明](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html)

可视化扩展可参考 [ComfyUI](https://docs.comfy.org/tutorials/video/minimax/minimax-h3)，服务化/多 GPU 可参考 [vLLM-Omni](https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3)。框架、权重布局和依赖不能直接混用；这些不是当前项目已交付的能力。
