# 部署流程审查与扩展路线

检查日期：2026-10-24。检查对象为原始 `deploy.sh`、`generate.py`、依赖文件及部署计划；修复后的使用入口为 [README.md](README.md)。

## 发现的问题与处理

| 优先级 | 原流程风险 | 已实施处理 |
| --- | --- | --- |
| 高 | 允许 Python 3.10，但所选当前 Diffusers 源码要求 Python ≥3.11 | 使用 3.11–3.13 范围，推荐 Ubuntu 24.04/Python 3.12；在安装前检查 |
| 高 | `main` 与宽泛 `>=` 依赖漂移，重装结果不一致 | 固定直接依赖、Diffusers commit、模型 revision；记录完整安装清单；增加 `pip check` |
| 高 | torch 单独安装，但没有匹配的 torchvision/Qwen3-VL 视觉依赖验证 | 固定 torch/torchvision CUDA 配对，真实导入 H3/Qwen 类并执行 torchvision 原生算子 |
| 高 | 缓存仅凭 `snapshots/` 目录存在，就把磁盘要求降至 20GiB | 下载前获取固定 revision 文件清单，按缺失/截断文件大小计算空间，完成后写 manifest |
| 高 | 仅检查总 RAM/VRAM，繁忙机器或内存受限容器会通过 | 检查空闲显存、MemAvailable，以及 cgroup v1/v2 和父级限额 |
| 高 | 仅用 `cuda.is_available()` 判断 CUDA 可运行 | 测试原生 BF16、矩阵乘法、SDPA attention、同步执行，提前发现驱动/内核错误 |
| 高 | 模型索引内部组件引用远程 ID 且 revision 为空 | 固定 snapshot 下载，组件加载显式指定本地路径，并启用 `local_files_only` |
| 中 | 系统检查前可能调用 `apt-get` | 平台、Python、硬件检查通过后才进行安装 |
| 中 | `python -m venv --help` 成功不能说明 ensurepip 存在 | 检查 `venv` 与 `ensurepip`，安装匹配解释器的 venv 系统包 |
| 中 | GPU 序号、CUDA 可见设备、容器映射可能不一致 | 尊重已有单 GPU 选择，转换为 GPU UUID；明确不支持多卡/MIG 配置 |
| 中 | 只检查模型缓存磁盘，忽略环境、pip 缓存和临时空间 | 对实际文件系统合并空间预算；将 pip 临时目录移到已检查的项目盘 |
| 中 | 输出非空且有音视频流，不足以说明文件完整 | 完整解码；检查编码、分辨率、帧数、帧率、采样率、声道和时长 |
| 中 | 导出失败可破坏已有成功产物 | 临时 MP4 验证通过后再原子替换；失败保留旧文件 |
| 中 | 并发运行可能重复加载模型、耗尽资源 | 同一 checkout 加 flock 锁；跨 checkout 的 GPU 调度仍由操作者负责 |
| 中 | Windows 提交后 shell 脚本可能变为 CRLF | 增加 `.gitattributes` 强制脚本 LF |
| 中 | 网络中断时缺少分阶段恢复和定位信息 | 拆出 `--setup`、`--download`、`--test`，记录阶段、行号与日志 |

此外，本次安装验证实际遇到 Git 克隆 GitHub 连接失败，已改为固定提交的官方 codeload ZIP，随后安装成功。它仍依赖网络可达，不能替代网络配置。

## 官方项目如何扩展

不要把不同框架的权重目录、量化格式和安装命令混用。

| 方向 | 开源项目的扩展方式 | 本项目下一步及限制 |
| --- | --- | --- |
| 图生视频/首尾帧 | Diffusers 的 `fl2va` 工作流；和 `t2va` 共享 transformer | 添加图片参数、读取和尺寸验证，再单独验收；不是只改提示词 |
| 多模态参考 | Diffusers 的 `ref2va` 使用另一套 `transformer_ref`，并带参考媒体预处理 | 另建组件下载清单和内存预算，保存引用顺序及媒体采样率；不能沿用当前 t2va manifest |
| 24–32GB GPU | 官方提供 int8 与 CPU 分组卸载路线 | 建立独立量化 profile，验证 torchao/torch/transformers 组合与主机 RAM；不能把当前显存阈值调低就算支持 |
| 工作流 UI | ComfyUI 原生节点、模板和相应模型布局 | 适合可视化使用；模板、模型和 ComfyUI 版本应成套固定，不直接把本项目缓存当作 ComfyUI 模型目录 |
| API/多 GPU | vLLM-Omni 的服务与并行部署路线 | 适合服务化；需要单独验证模型布局、并行策略、请求超时及队列，不能只在现有脚本外套一个 HTTP handler |
| 完整商业工作流 | 官方区分本地 Base 与托管上下文处理/2K 流程 | 当前本地 Base 验收不代表托管全流程效果；如需要再独立集成 API、凭据、失败重试与费用控制 |

依据：[Diffusers H3](https://huggingface.co/docs/diffusers/main/en/api/pipelines/minimax_h3)、[ComfyUI 官方 H3 教程](https://docs.comfy.org/tutorials/video/minimax/minimax-h3)、[vLLM-Omni 官方 recipe](https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3)、[MiniMax 官方 README](https://github.com/MiniMax-AI/MiniMax-H3)。本节是对这些集成边界的归纳，不表示上述扩展已在本项目实现。

## “一键部署”的实际边界

当前裸机路线的入口是 `bash deploy.sh`。它自动完成前置条件检查、隔离环境、依赖安装、最小运行验证、按需下载和产物验收。GPU 驱动、受支持 Python、网络权限和硬件资源必须先具备。

如果之后做 Docker，建议把依赖固定在镜像内、模型缓存挂载到镜像外、产物挂载到持久目录；启动时检查 GPU 和容器资源，再加载已固定的模型。驱动属于宿主机，`--gpus` 透传和 NVIDIA Container Toolkit 需单独配置。应在镜像构建中运行 CPU 检查，在部署机器上运行 GPU 验收。

vLLM-Omni recipe 特别提示其 H3 镜像 tag 与当前模块化实现存在时间差，需要同时挂载源码。因此不能仅凭一个镜像名字就认定包含所需功能；实际采用时应固定镜像 digest 与源码 commit，并按该项目的硬件方案测试。[官方 recipe 的安装说明](https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3)

## 已验证和仍未验证

本地 Windows/Python 3.12 验证：

- 14 项标准库回归测试通过，覆盖帧数边界、无效参数、缺失/截断缓存、cgroup 限额、同盘空间预算、导出失败保留旧产物。
- Bash 语法与 ShellCheck v0.11.0 检查通过；Windows 执行部署预检会在安装前明确拒绝。
- 独立 CPU 虚拟环境安装固定依赖通过，`pip check` 无冲突；CPU torch/torchvision 为 `2.11.0+cpu` / `0.26.0+cpu`，与服务器 CUDA 构建不同。
- H3/Qwen3-VL 模块导入、torchvision 原生算子、真实 1 秒 H.264/AAC 编码及完整解码通过。
- 对固定模型索引和模拟本地组件文件布局做了离线解析，t2va 仅引用八个目标组件；未加载权重。
- 已核对官方 cu128 索引中 Python 3.11/3.12/3.13 的 Linux x86_64 torch/torchvision wheel 存在；并未在本地安装这些 Linux CUDA wheel。

GitHub Actions 的 Ubuntu 24.04/Python 3.12 检查也已全部通过：Bash/ShellCheck/14 项回归，以及固定依赖安装、`pip check`、H3 导入与实际 CPU 编解码。[运行记录：40109323527，代码提交 c22d83a](https://github.com/huangqingchi/test/actions/runs/40109323527)。CI 使用 CPU wheel，不是 CUDA 推理测试。

尚需目标服务器完成：Ubuntu 系统包安装、Linux CUDA 依赖解析和内核检查、完整模型下载、BF16 加载/CPU 卸载、真实视频生成、峰值内存/显存、耗时和画质验收。

仍存在的边界：直接依赖已固定但间接依赖尚未形成完整 hash lock；缓存校验不覆盖同大小的内容损坏；资源预检与实际加载之间可能有其他任务抢占；高分辨率/长视频仍可能 OOM；本地 shell 锁不覆盖不同目录的任务。首次服务器验收后，应保存实际依赖清单、日志、资源峰值和样片，再决定是否发布 Docker 或扩展到小显存、多卡、API。

## 源码审查定位

- [固定 Diffusers 提交的 Python 版本与依赖要求](https://github.com/huggingface/diffusers/blob/aaf57d03a3edfbd9de457d2872417a92f149a91d/setup.py)
- [固定 Diffusers 提交的组件加载实现](https://github.com/huggingface/diffusers/blob/aaf57d03a3edfbd9de457d2872417a92f149a91d/src/diffusers/modular_pipelines/modular_pipeline.py)
- [固定模型版本的文件元数据](https://huggingface.co/api/models/MiniMaxAI/MiniMax-H3/revision/42ed227ee7df40d41602854ae760620d6eb651fe?blobs=true)
- [PyTorch 官方版本配对](https://pytorch.org/get-started/previous-versions/)
- [NVIDIA CUDA 兼容说明](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html)
