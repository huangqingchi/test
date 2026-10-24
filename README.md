# MiniMax-H3 单卡部署与验收

通用开发规范见 [all_project_readme.md](all_project_readme.md)。本项目的 [代码结构](docs/code_structure.md)、[代码流程图](docs/code_flow.md) 和 [当前审查结果](docs/project_review.md) 位于 `docs/`。

**[直接查看流程图](docs/diagrams/index.html)** · [打开部署流程 PNG 图片](docs/diagrams/deployment.png)。图片无需 Markdown 插件；HTML 在本地浏览器打开可缩放。

只配置项目环境，直接运行根目录脚本：

```bash
bash setup.sh
```

`setup.sh` 是 `deploy.sh --setup` 的独立入口：在受支持的 Ubuntu x86_64 上自动选择/安装 Python、创建 `.venv`、安装固定依赖并验证导入和编解码；不要求 GPU，不下载模型。它继承相同的权限、软件源、磁盘和网络前提。完整下载、部署及三个工作流验收仍运行 `bash deploy.sh`。

**首要要求：部署的模型是 MiniMax-H3，模型仓库固定为 `MiniMaxAI/MiniMax-H3`。** 脚本必须从该仓库下载权重、在目标机器本地加载并测试；环境不满足时明确报错，不自动替换模型。

当前部署覆盖 MiniMax-H3 公开本地模型的三个工作流：**文生音视频 `t2va`、首帧/尾帧/首尾帧 `fl2va`、图像/视频/音频参考 `ref2va`**。下载两套生成权重和全部共享组件，使用 Diffusers 加载器，面向 **Ubuntu x86_64 + 单张 80GB 级 NVIDIA GPU + BF16/CPU 卸载**。

默认命令会依次测试三个工作流；单独的 `--test` 是快速文生音视频测试，不能代表全流程验收。官方尚未公开本地权重的 H3-Context-IR / H3-Regenerate-2K 托管模块不属于本地模型部署；也不把这些 API 服务写成已部署。[官方公开范围说明](https://github.com/MiniMax-AI/MiniMax-H3)

**验证边界：本地/CI 检查覆盖依赖、脚本编排、缓存升级、全部工作流索引及真实媒体读取/编解码；没有在目标 GPU 上加载完整权重执行生成。** [最新 CI 结果](https://github.com/huangqingchi/test/actions)。服务器须用 `--test-all` 完成实际验收；具体检查记录见 [AUDIT.md](AUDIT.md)。

**现有目标机器上的交付入口是 `bash deploy.sh`：自动适配环境、下载模型、部署并实际测试。** 不要求事先准备模型或另一台机器。分阶段命令用于失败后的续跑，详见 [交付步骤 HANDOFF.md](HANDOFF.md)。

## 环境要求

| 项目 | 本项目要求与说明 |
| --- | --- |
| 部署模型 | MiniMax-H3；固定 ID `MiniMaxAI/MiniMax-H3`，覆盖 `t2va`、`fl2va`、`ref2va` |
| 系统 | 推荐 Ubuntu 24.04 x86_64；Windows 仅用于开发检查 |
| Python | 稳定版 3.11–3.13；自动复用已有虚拟环境或兼容解释器，缺少时从现有 apt 源选择 Python + venv；源中无稳定版本则明确退出 |
| GPU | 一张完整的 80GB 级显卡；检查总显存、空闲显存均至少 75,000MiB，并实际测试原生 BF16 与 CUDA attention |
| 驱动 | 预装宿主机 NVIDIA 驱动；CUDA 12.x 兼容下限 525.60.13，CUDA 12.8 建议 570.26+，新架构还需相应驱动；以实际内核运行为准 |
| 内存 | **可用**主机/容器内存至少 150GiB；建议配置 192GiB 或更多。不能用 swap 替代；容器限额会参与检查 |
| 磁盘 | 建议首次准备至少 300GiB 空闲空间；完整 Diffusers 模型约 195.89GiB，加虚拟环境、缓存、临时文件和三个流程的产物；允许分盘存放 |
| 网络 | 安装时访问 Ubuntu 软件源、PyPI、PyTorch wheel 源、GitHub codeload；下载模型时访问 Hugging Face 及其文件传输端点 |

显存/内存阈值是当前部署方案的保守门槛，不是模型的最低硬件需求，也不能保证任意分辨率不发生 OOM。驱动依据：[NVIDIA CUDA 12.8 release notes](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html)。

## 一键部署

在服务器上获取项目，进入目录，然后执行：

```bash
git clone https://github.com/huangqingchi/test.git minimax-h3-demo
cd minimax-h3-demo
bash deploy.sh
```

执行顺序：平台检查 → 自动选择/安装兼容 Python → 资源检查 → 系统包与虚拟环境 → 固定依赖 → CUDA/编码小测试 → 下载完整 H3 Diffusers 权重 → 检查三个本地工作流 → 依次生成三个音视频 → 完整解码验收。

缺少系统包时脚本使用 `apt-get`，非 root 用户需已具备非交互 sudo 权限，或事先在终端执行 `sudo -v`；不具备时脚本立即报错。脚本不会安装 NVIDIA 驱动或替换系统 Python。完整验收产物位于 `outputs/h3-full-<本次运行ID>/`，含三个 MP4 和自动生成的输入素材；准确路径记录在 `logs/*-acceptance.json`。运行日志、阶段耗时、结果报告和依赖清单也写入 `logs/`。Python 包候选以实际配置的软件源为准；推荐的 [Ubuntu 24.04 提供 Python 3.12 venv 包](https://packages.ubuntu.com/noble/python3.12-venv)。

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
| `bash deploy.sh --prepare` | 自动适配环境、检查 CPU 导入/编解码并下载完整模型；无 GPU/推理 RAM 要求 |
| `bash deploy.sh --preflight` | 只读平台/资源检查，不安装、不下载；无法证明依赖或模型可运行 |
| `bash deploy.sh --setup` | 自动选择/安装 Python，安装系统包和依赖，测试 CPU 导入/编解码；不需要 GPU、不下载模型 |
| `bash deploy.sh --download` | 使用已有环境，补齐并校验两套权重和共享组件；无 GPU 要求，中断后可重跑 |
| `bash deploy.sh --check` | 离线 GPU/资源/依赖/完整缓存/三个工作流索引检查；不加载权重、不安装、不下载 |
| `bash deploy.sh --test` | 快速测试：只做 t2va 生成；仍要求完整模型清单，不代表全部工作流通过 |
| `bash deploy.sh --test-all` | 完整测试：依次运行 t2va、首尾帧 fl2va、图像+视频+音频混合 ref2va；自动生成输入素材，不安装、不下载 |

依赖安装失败，修复网络后重跑 `--setup`。模型下载中断，重跑 `--download`；已完成文件按大小检查，缺失/截断文件继续处理。已有完整环境和模型时使用 `--test-all`，避免重新走安装检查；测试时间紧时可以明确选择 `--test`，但报告不会写成全部流程已通过。

下载依据固定 revision 的文件清单计算空间，保留至少 20GiB 余量。下载 **MiniMax-H3 完整 Diffusers 组件集合，约 195.89GiB**：`transformer`、`transformer_ref`、`text_encoder`、`tokenizer`、`processor`、`vae`、`audio_vae`、`scheduler`、`audio_scheduler` 及模型索引。文生/首尾帧使用第一套 transformer，参考生成使用第二套，其余组件共享。[官方工作流与组件说明](https://huggingface.co/docs/diffusers/main/en/api/pipelines/minimax_h3)

不重复下载供其他框架读取的原始格式副本，两套生成权重在当前格式中均已包含。每次推理只把当前任务的组件加载到 RAM；完整验收按进程顺序执行，避免两套权重同时驻留。大量参考素材仍可能增加显存/内存峰值。清单校验覆盖存在性与文件大小，**不是逐文件 SHA256 复核**。

从旧版 t2va-only 部署升级：运行 `bash deploy.sh --download`。原有 snapshot 文件复用，主要补下载约 61.73GiB 的 `transformer_ref`。完整部署使用新的 `h3-full-diffusers` 清单，旧清单即使被复制/改名，也不能通过完整检查。

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
| `H3_OUTPUT` | 快速测试 MP4 路径；完整验收在它的父目录创建独立的 `h3-full-*` 目录 |
| `H3_PROMPT` | 一键测试的文本提示词 |
| `H3_TEST_TIMEOUT` | 每个工作流子进程的加载/生成/输出验证时限，秒；默认 0 不限时。三个流程各自计时，超时退出 124 并停止后续流程 |
| `HF_TOKEN` | 模型访问需要认证时设置；不要写入仓库或命令行参数 |

直接调整生成参数，先确保缓存环境变量一致并选择一张 GPU：

```bash
export HF_HOME=/data/h3-model-cache
export CUDA_VISIBLE_DEVICES=0
.venv/bin/python generate.py \
  --workflow t2va \
  --prompt 'A red fox walks through snow, with wind and footsteps audible.' \
  --output outputs/custom.mp4 --width 960 --height 544 \
  --frames 124 --steps 9 --seed 42
```

首尾帧（可只传 `--image` 或只传 `--last-image`）：

```bash
.venv/bin/python generate.py --workflow fl2va \
  --prompt 'The red ball rolls from left to right.' \
  --image /data/first.png --last-image /data/last.png --output outputs/keyframes.mp4
```

混合参考（重复 `--reference 类型 路径`；引用顺序保持不变）：

```bash
.venv/bin/python generate.py --workflow ref2va \
  --prompt 'Follow the reference appearance, motion and sound.' \
  --reference image /data/subject.png \
  --reference video /data/motion.mp4 \
  --reference audio /data/sound.wav --output outputs/references.mp4
```

输入必须是非空本地文件，不能传 URL。参考上限是 9 张图、3 段视频、3 段音频，合计 12 个；音频需搭配至少一个图像或视频参考。音视频每段 2–15 秒，同类总时长不超过 15 秒（允许编码 padding 的小幅容差）。加载模型前校验并解码媒体，保留视频帧率与音频采样率。参考分辨率/时长越大，资源需求越高。

直接运行 Python 会绕过 shell 的资源预检和并发锁，请自行确保 GPU 空闲。分辨率须为 32 的倍数；本封装接受 124、141……345 帧。默认测试约 5.17 秒，9 个采样网格点对应 8 次模型求值，主要验证流程，不能代表正式画质。有关模型参数与不同显存配置见 [Diffusers H3 文档](https://huggingface.co/docs/diffusers/main/en/api/pipelines/minimax_h3)。

## 验收与常见失败

成功要求：进程退出码 0；MP4 完整可解码；H.264 视频尺寸、24fps、帧数符合请求；AAC 音频为 32kHz 双声道，时长与视频相差不超过 0.15 秒。生成先写临时文件，验证通过才替换目标文件；失败时保留之前的成功产物。结构验证不判断内容质量、对白准确性或主观音画同步。

完整验收还要求 `*-acceptance.json` 中三个工作流均为 `passed`，且 `all_workflows_passed=true`。快速测试的 `scope=quick-t2va-only`、其余流程为 `not_run`。任何失败/超时会停止后续执行并保留逐流程状态；不能用上一次的样片作为这次成功证据。自动生成的简单测试素材只用于验证接口和流程，不代表生产画质测试。

快速测试在新的 `.h3-quick-*` 临时目录中生成，父进程确认本次新文件完整有效后才替换 `H3_OUTPUT`。空提示词、输出扩展名和输出路径冲突在昂贵步骤前检查。损坏的本地 manifest 会提示重跑 `--download`，可复用已有模型文件。

生成验收阶段收到 SIGINT/SIGTERM 时，shell 转发给验收父进程并等待；Linux 生成进程组及同组辅助进程会被回收。当前任务记录为 `cancelled`，后续为 `not_run`，退出码为 130/143。超时返回 124。SIGKILL、断电以及安装/下载工具的所有子任务不在此取消保证内。

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

[CI 配置](.github/workflows/checks.yml)在 Ubuntu 上运行无 GPU 回归、三个工作流的离线索引路由、真实首尾帧/混合参考解码及 CPU 编解码测试。CI 通过不代表 80GB GPU 推理验收通过。项目提供三个工作流的命令行入口；常驻 API、Docker、小显存量化仍不在当前实现内。
