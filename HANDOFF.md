# 在目标机器上一键下载、部署和测试 MiniMax-H3

**第一项必要条件：部署对象必须是 MiniMax-H3（`MiniMaxAI/MiniMax-H3`），在目标机器下载并本地运行。** 当前脚本实现文生音视频 `t2va`；首尾帧与多模态参考流程尚未接入，不能把当前流程验收当作 H3 全部功能验收。

把项目放到现有 Ubuntu GPU 机器上，进入项目目录，执行：

```bash
bash deploy.sh
```

无需提前准备模型。脚本依次完成：

1. 检查 Ubuntu/x86_64，自动选择兼容的 Python；没有时尝试从现有 apt 源安装稳定 Python 3.11–3.13 和匹配的 venv。
2. 检查 GPU、驱动、可用显存、内存及磁盘；不适配时先报错，避免开始下载大模型。
3. 补齐系统包、建立独立环境、安装固定版本的 CUDA PyTorch 和运行依赖。
4. 实际测试 CUDA 内核、H3 类导入、音视频编码与解码。
5. 从 `MiniMaxAI/MiniMax-H3` 下载约 134GiB 的文生音视频工作流权重和配置（H3 transformer、文本编码器、音视频 VAE 等），校验缺失/截断文件；已有完整文件复用。
6. 加载 MiniMax-H3，生成 960×544、124 帧的带声音 MP4，完整解码并核对帧数、音频等信息。
7. 输出明确的 PASS/FAIL、失败阶段、各阶段耗时、日志和依赖清单。

**主入口会下载模型并实际测试，不是仅做就绪检查。** 分阶段入口只是出错后的续跑工具，不需要按顺序手动执行一遍。

## 机器与权限前提

当前自动适配范围是 Ubuntu x86_64 + 稳定 Python 3.11–3.13 + 单张 80GB 级 NVIDIA GPU + 至少 150GiB 可用 RAM。推荐 Ubuntu 24.04；首次建议至少 220GiB 空闲磁盘。脚本不会把 24/32GB 卡自动切换成另一套量化实现。

宿主 NVIDIA 驱动须已安装。缺少系统包时，需要 root 或已可用的 sudo；必要时先在终端执行 `sudo -v`，脚本不会无人值守地等密码。如果当前 apt 源没有兼容的稳定 Python + venv，脚本会明确退出，不改系统 Python 链接、不自动添加第三方 PPA。

网络需能访问 Ubuntu 软件源、PyPI、PyTorch、GitHub codeload、Hugging Face 文件端点。脚本能减少人工操作，首次下载与模型加载的耗时仍取决于带宽和硬件，不能承诺几分钟完成。

## 缓存放大磁盘

项目所在磁盘足够时，无需配置。需要换盘时，在目标机器同一个终端中：

```bash
export H3_HF_HOME=/data/h3-model-cache
export H3_PIP_CACHE=/data/h3-pip-cache
export H3_GPU_INDEX=0
bash deploy.sh
```

项目盘还要存 `.venv` 与临时文件。后续重试继续使用相同缓存路径；模型不会因为重新运行而全量重复下载。

## 出错后只续跑必要阶段

| 当前情况 | 执行命令 |
| --- | --- |
| 首次部署、模型尚未下载 | `bash deploy.sh` |
| 只想完成安装与下载，暂不推理 | `bash deploy.sh --prepare` |
| 依赖安装失败，修好网络后重试 | `bash deploy.sh --setup` |
| 模型下载中断 | `bash deploy.sh --download`，完成后运行 `--test` |
| 环境和模型已有，只重跑真实测试 | `bash deploy.sh --test` |
| 快速检查资源/内核/缓存，不加载大模型 | `bash deploy.sh --check` |
| 只读硬件检查，不写报告 | `bash deploy.sh --preflight` |

也可重新执行完整命令，已有 Python/虚拟环境会复用，pip 检查固定依赖，下载按缺失文件继续；它不是“从零删除重装”。`--prepare`、`--setup`、`--download` 不要求 GPU，只用于准备/恢复；无需另一台机器。

`--test` 不安装、不下载；缓存不完整会退出并提示续传，而不会在推理阶段临时下载。

## 可选测试时限

如果对方要求实际模型加载和生成最多占用 10 分钟，可在完整部署命令中设置：

```bash
H3_TEST_TIMEOUT=600 bash deploy.sh
```

安装、下载仍正常执行；只有模型加载、生成和产物验证阶段限时。**这不是整个部署 10 分钟完成的承诺。** 超时记为失败，通常退出码 124，强制终止可能为 137；强制停止另有最多 15 秒宽限。默认不设时限，首次推理耗时需实测。

## 对方回传什么

- 终端最后的 `RESULT` 行，以及对应的 `logs/*-result.txt`。
- 同一前缀的 `*-stages.tsv`（各阶段秒数）、`.log`、`*-packages.txt`。
- 成功时的 `outputs/smoke-test.mp4`；失败时不要把旧 MP4 当成本次成功结果。

报告包含运行模式、PASS/FAIL、退出码、最后阶段和耗时；只有完整生成验收成功才出现 `validated_output`。单独运行 `--prepare` 或 `--check` 的 PASS 不表示模型推理成功。

平台不支持、目录不可写或无法取得并发锁时，可能来不及创建报告；此时回传终端错误即可。不要回传自己的 token、代理密码或完整环境变量。

详细环境与故障排查见 [README.md](README.md)。
