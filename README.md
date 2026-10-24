# MiniMax-H3 单卡部署与验收

本项目把官方 Diffusers 的 `t2va` 工作流封装成一条部署命令，生成带音频的 MP4。当前实现面向 **Ubuntu x86_64 + 单张 80GB 级 NVIDIA GPU + BF16/CPU 卸载**。

**验证状态：Windows 本地及 Ubuntu 24.04 CI 的依赖安装、CPU 导入/编解码、回归检查已通过；尚未在目标 GPU 服务器完成模型推理验收。** [Ubuntu CI 结果](https://github.com/huangqingchi/test/actions/runs/40109323527)。具体问题与扩展方案见 [AUDIT.md](AUDIT.md)。

**现有目标机器上的交付入口是 `bash deploy.sh`：自动适配环境、下载模型、部署并实际测试。** 不要求事先准备模型或另一台机器。分阶段命令用于失败后的续跑，详见 [交付步骤 HANDOFF.md](HANDOFF.md)。

## 环境要求

| 项目 | 本项目要求与说明 |
| --- | --- |
| 系统 | 推荐 Ubuntu 24.04 x86_64；Windows 仅用于开发检查 |
| Python | 稳定版 3.11–3.13；自动复用已有虚拟环境或兼容解释器，缺少时从现有 apt 源选择 Python + venv；源中无稳定版本则明确退出 |
| GPU | 一张完整的 80GB 级显卡；检查总显存、空闲显存均至少 75,000MiB，并实际测试原生 BF16 与 CUDA attention |
| 驱动 | 预装宿主机 NVIDIA 驱动；CUDA 12.x 兼容下限 525.60.13，CUDA 12.8 建议 570.26+，新架构还需相应驱动；以实际内核运行为准 |
| 内存 | **可用**主机/容器内存至少 150GiB；建议配置 192GiB 或更多。不能用 swap 替代；容器限额会参与检查 |
| 磁盘 | 建议首次准备至少 220GiB 空闲空间，覆盖模型、虚拟环境、pip 缓存、临时文件和产物；允许分盘存放 |
| 网络 | 安装时访问 Ubuntu 软件源、PyPI、PyTorch wheel 源、GitHub codeload；下载模型时访问 Hugging Face 及其文件传输端点 |

显存/内存阈值是当前部署方案的保守门槛，不是模型的最低硬件需求，也不能保证任意分辨率不发生 OOM。驱动依据：[NVIDIA CUDA 12.8 release notes](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html)。

## 一键部署

在服务器上获取项目，进入目录，然后执行：

```bash
git clone https://github.com/huangqingchi/test.git minimax-h3-demo
cd minimax-h3-demo
bash deploy.sh
```

执行顺序：平台检查 → 自动选择/安装兼容 Python → 资源检查 → 系统包与虚拟环境 → 固定依赖 → CUDA/编码小测试 → 下载指定模型组件 → 生成 → 完整解码验收。

缺少系统包时脚本使用 `apt-get`，非 root 用户需已具备非交互 sudo 权限，或事先在终端执行 `sudo -v`；不具备时脚本立即报错。脚本不会安装 NVIDIA 驱动或替换系统 Python。默认产物为 `outputs/smoke-test.mp4`，运行日志、阶段耗时、结果报告和完整的已安装依赖清单写入 `logs/`。Python 包候选以实际配置的软件源为准；推荐的 [Ubuntu 24.04 提供 Python 3.12 venv 包](https://packages.ubuntu.com/noble/python3.12-venv)。

若项目目录磁盘较小，可使用绝对路径指定缓存：

```bash
export H3_HF_HOME=/data/h3-model-cache
export H3_PIP_CACHE=/data/h3-pip-cache
export H3_GPU_INDEX=0
bash deploy.sh
```

项目目录仍须有足够空间存放 `.venv` 和 `.cache/tmp`；将整个项目放在大容量磁盘最直接。后续命令须保持同一组缓存环境变量，建议保存在自己的启动脚本中。

## 分阶段执行与恢复

| 命令 | 行为 |
| --- | --- |
| `bash deploy.sh --prepare` | 自动适配环境、检查 CPU 导入/编解码并下载模型；无 GPU/推理 RAM 要求，用于测试前准备 |
| `bash deploy.sh --preflight` | 只读平台/资源检查，不安装、不下载；无法证明依赖或模型可运行 |
| `bash deploy.sh --setup` | 自动选择/安装 Python，安装系统包和依赖，测试 CPU 导入/编解码；不需要 GPU、不下载模型 |
| `bash deploy.sh --download` | 使用已有环境，下载并校验固定版本组件；无 GPU 要求，中断后可重跑 |
| `bash deploy.sh --check` | 离线 GPU/资源/依赖/编解码/缓存检查；不加载模型权重，不安装、不下载 |
| `bash deploy.sh --test` | 使用已有环境和已校验模型，离线生成与验收；不会自动补下载 |

依赖安装失败，修复网络后重跑 `--setup`。模型下载中断，重跑 `--download`；已完成文件按大小检查，缺失/截断文件继续处理。安装阶段需要额外磁盘余量，已有完整环境和模型时使用 `--test`，避免重新走安装检查。

下载依据固定 revision 的文件清单计算空间，保留至少 20GiB 余量。当前文生音视频组件约 **134.16GiB**；未选择的原始权重、`transformer_ref` 等不会下载。清单校验覆盖存在性与文件大小，**不是逐文件 SHA256 复核**。

## 版本与参数

PyTorch/torchvision 固定为 `2.11.0+cu128` / `0.26.0+cu128`，必须成对安装。CUDA 后缀用于阻止依赖解析转而选择 PyPI 的其他 CUDA 构建；版本配对见 [PyTorch 官方版本表](https://pytorch.org/get-started/previous-versions/)。

- Diffusers 固定提交：`aaf57d03a3edfbd9de457d2872417a92f149a91d`，从官方源码 ZIP 安装。
- 模型固定 revision：`42ed227ee7df40d41602854ae760620d6eb651fe`，位于 [h3_config.py](h3_config.py)。
- 直接依赖固定在 [requirements.txt](requirements.txt)，间接依赖由解析器选取并记录到日志；当前还不是含全部间接依赖/哈希的完整锁文件。
- 更换模型或框架版本后，重新运行导入、编码和 GPU 验收，不要直接把版本改成 `main`。

| 环境变量 | 用途 |
| --- | --- |
| `H3_PYTHON` | 选择 Python，例如 `python3.12`；已有虚拟环境的 Python 次版本必须一致 |
| `H3_GPU_INDEX` | GPU 序号或完整 UUID；优先于已有 `CUDA_VISIBLE_DEVICES`。最终转换为 UUID，避免选错卡 |
| `H3_HF_HOME` | 模型缓存根目录；未设置则使用 `HF_HOME` 或项目下 `.cache/huggingface` |
| `H3_PIP_CACHE` | pip 下载缓存；默认项目下 `.cache/pip` |
| `H3_OUTPUT` | MP4 输出路径，建议绝对路径 |
| `H3_PROMPT` | 一键测试的文本提示词 |
| `H3_TEST_TIMEOUT` | 模型加载、生成与输出验证阶段的时限，秒；默认 0 不限时，例如 600。超时算失败，不是成功验收 |
| `HF_TOKEN` | 模型访问需要认证时设置；不要写入仓库或命令行参数 |

直接调整生成参数，先确保缓存环境变量一致并选择一张 GPU：

```bash
export HF_HOME=/data/h3-model-cache
export CUDA_VISIBLE_DEVICES=0
.venv/bin/python generate.py \
  --prompt 'A red fox walks through snow, with wind and footsteps audible.' \
  --output outputs/custom.mp4 --width 960 --height 544 \
  --frames 124 --steps 9 --seed 42
```

直接运行 Python 会绕过 shell 的资源预检和并发锁，请自行确保 GPU 空闲。分辨率须为 32 的倍数；本封装接受 124、141……345 帧。默认测试约 5.17 秒，9 个采样网格点对应 8 次模型求值，主要验证流程，不能代表正式画质。有关模型参数与不同显存配置见 [Diffusers H3 文档](https://huggingface.co/docs/diffusers/main/en/api/pipelines/minimax_h3)。

## 验收与常见失败

成功要求：进程退出码 0；MP4 完整可解码；H.264 视频尺寸、24fps、帧数符合请求；AAC 音频为 32kHz 双声道，时长与视频相差不超过 0.15 秒。生成先写临时文件，验证通过才替换目标文件；失败时保留之前的成功产物。结构验证不判断内容质量、对白准确性或主观音画同步。

| 现象 | 排查方法 |
| --- | --- |
| Python 版本不支持 / 无 wheel | 使用 Ubuntu 24.04 默认 3.12，或通过 `H3_PYTHON` 指定受支持版本；不要直接修改系统 `python3` 链接 |
| `ensurepip`、创建 venv 失败 | 确认所选解释器对应的 `pythonX.Y-venv` 可由当前软件源安装；自定义 Python 需自行准备 ensurepip |
| `CUDA unavailable` / kernel image 错误 | 检查宿主驱动、容器 GPU 透传、torch CUDA 构建和 GPU 架构；驱动版本字符串通过不等于内核可运行 |
| `torchvision::nms` 不存在 | 通常是 torch/torchvision 构建不匹配；使用本项目虚拟环境和成对的 cu128 版本重装 |
| 内存/显存不足、进程被 killed | 先停止其他任务，检查 `free -h`、`nvidia-smi`、容器限额及内核 OOM 日志；24/32GB 卡需要另一套量化方案 |
| 401/403 | 在 Hugging Face 检查账号访问权限/模型条款，按需设置 `HF_TOKEN`；GitHub 登录不能替代 Hugging Face 授权 |
| 连接超时、TLS/代理错误 | 检查对应软件源、codeload、HF/Xet 下载端点以及代理/CA；不要关闭证书验证 |
| 磁盘空间不足 | 同时检查模型盘、项目盘、pip 缓存盘；不完整文件也会占空间。不要只看模型盘的总容量 |
| 找不到 manifest / 缓存不完整 | 保持相同缓存路径，执行 `--download`；不要手动创建 snapshots 目录绕过检查 |
| `.venv` 损坏或 Python 次版本变化 | 把旧 `.venv` 移到备份位置，再执行 `--setup`；模型缓存可保留 |
| 编码器缺失或 MP4 验证失败 | 查看 `runtime` / `generation` 阶段日志；PyAV 编码器已在下载大模型前做实际测试 |
| 报另一个任务正在运行 | 同一项目目录有部署锁；不同目录的任务仍可能争抢同一 GPU，需统一调度 |

Docker 需要宿主 NVIDIA 驱动和 NVIDIA Container Toolkit，以及足够的容器内存限额、可写模型/产物挂载。本项目尚未提供或验收 Docker 镜像；不要把裸机脚本成功等同于容器可用。

## 开发检查

```bash
python -m unittest discover -s tests -v
bash -n deploy.sh
shellcheck -x deploy.sh scripts/environment.sh
# 使用已安装运行依赖的环境；不加载模型权重
python verify_runtime.py --cpu
```

[CI 配置](.github/workflows/checks.yml)在 Ubuntu 上运行无 GPU 回归和 CPU 导入/编码测试。CI 通过不代表 80GB GPU 推理验收通过。项目只实现命令行文生音视频；图生视频、参考视频、API 服务的扩展边界见 [AUDIT.md](AUDIT.md)。
