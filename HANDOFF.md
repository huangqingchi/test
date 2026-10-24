# 在目标机器上一键部署完整公开 MiniMax-H3

**第一项要求：部署对象是 MiniMax-H3（MiniMaxAI/MiniMax-H3），包含文生音视频、首尾帧和多模态参考三个公开本地工作流。**

进入项目目录运行：

```bash
bash deploy.sh
```

无需预置模型。脚本自动适配 Python/依赖、检查 GPU/资源、下载完整 Diffusers 模型（两套 transformer + 共享组件，约 **195.89GiB**），然后依次运行：

1. `t2va`：文字生成带声音视频。
2. `fl2va`：首帧 + 尾帧生成带声音视频。
3. `ref2va`：图像 + 视频 + 音频混合参考生成带声音视频。

测试用的图片、2 秒视频和音频由脚本自动生成，不需要对方找素材。每个流程在独立进程中运行，结束后释放模型内存，再测试下一个流程。三项都通过才算本次全流程验收成功。默认测试用简单图形和音调验证接口连通性，正式画质和素材一致性需要实际业务素材另行评估。

## 机器与权限前提

当前自动适配范围：Ubuntu x86_64、稳定 Python 3.11–3.13、单张 80GB 级 NVIDIA GPU、至少 150GiB 可用 RAM。推荐 Ubuntu 24.04；首次建议至少 **300GiB 空闲磁盘**。参考素材增加后可能需要更多内存/显存。脚本不自动改成小显存量化或多卡方案。

驱动需预装。缺少 Python/系统包时，脚本从现有 apt 源中选择兼容稳定版本及匹配 venv，要求 root 或可用的 sudo；必要时先在终端执行 `sudo -v`。无可用安装源/权限时明确报错，不更改系统 Python 链接或临时添加 PPA。

网络需能访问 Ubuntu 软件源、PyPI、PyTorch、GitHub codeload、Hugging Face 文件端点。自动化减少人工操作，不保证约 196GiB 下载或三个模型任务在几分钟内完成。

## 大磁盘与 GPU 选择

项目盘够大时无需配置；需换盘时，同一终端执行：

```bash
export H3_HF_HOME=/data/h3-model-cache
export H3_PIP_CACHE=/data/h3-pip-cache
export H3_GPU_INDEX=0
bash deploy.sh
```

项目盘仍需存放虚拟环境和临时文件。重跑时使用同一缓存路径，已下载文件会复用。

## 快速测试与完整验收是两个入口

| 命令 | 作用 |
| --- | --- |
| `bash deploy.sh` | 首次完整部署：自动环境、完整下载、三流程 GPU 验收 |
| `bash deploy.sh --prepare` | 只安装环境并下载完整模型，暂不推理 |
| `bash deploy.sh --setup` | 安装/修复依赖并做 CPU 导入/编码检查 |
| `bash deploy.sh --download` | 补齐完整模型，支持中断后继续 |
| `bash deploy.sh --check` | GPU、依赖、完整缓存、三工作流本地索引检查，不加载权重 |
| `bash deploy.sh --test` | 快速文生音视频测试；不等于全流程验收 |
| `bash deploy.sh --test-all` | 已部署环境的三流程完整 GPU 验收 |
| `bash deploy.sh --preflight` | 只读资源检查 |

`--test`、`--test-all` 都不安装、不下载，且要求完整模型缓存。下载中断可只运行 `--download`，随后 `--test-all`。从旧版 t2va-only 缓存升级，会复用原有文件并补下载约 61.73GiB 的参考生成权重，重新生成完整模型清单。

## 时限与失败结果

如需要限制每个工作流的加载和生成时间：

```bash
H3_TEST_TIMEOUT=600 bash deploy.sh
```

该设置是 **每个工作流子进程最多 600 秒**，不是整次部署 10 分钟完成；安装、下载、素材创建、就绪检查和父进程复核解码不在此时限内。默认 0 不限时。超时通常返回 124；任何流程失败或超时都会停止后续流程，完整验收结果为失败。

生成阶段常规取消会回收 Linux 生成进程组、等待当前任务退出，再记录 `cancelled`；SIGINT/SIGTERM 退出码分别是 130/143。快速测试只有本次新文件通过验证后才替换旧样片；失败后旧文件仍存在也不表示本次成功。断电或强杀进程可能来不及写最终报告。

## 对方回传什么

- 终端最后的 `RESULT` 行及对应 `logs/*-result.txt`。
- 同一前缀的 `*-acceptance.json`、`*-stages.tsv`、`.log`、`*-packages.txt`。
- 完整验收生成的 `outputs/h3-full-<运行ID>/t2va.mp4`、`fl2va.mp4`、`ref2va.mp4`；准确目录在 JSON 报告中。

完整成功必须同时满足：三个流程状态都是 `passed`，且 `all_workflows_passed=true`。快速测试报告会明确写 `scope=quick-t2va-only`，未执行流程是 `not_run`，即使成功也不会写成全流程通过。失败时不能把旧样片作为本次成功证据。

若在平台检查、写目录或取锁之前失败，可能尚无报告，回传终端错误即可。不要回传 token、代理密码或完整环境变量。

## 公开本地范围

完整公开本地模型对应 H3-Base 的三个工作流。Diffusers 格式已经包含两套生成权重；供其他框架读取的原始格式副本无需重复下载。H3-Context-IR / H3-Regenerate-2K 是官方尚未开放本地权重的托管流程，不声称已本地部署。[官方说明](https://github.com/MiniMax-AI/MiniMax-H3)

参数与自定义图片/参考媒体命令见 [README.md](README.md)。本项目尚未在目标 GPU 上执行完整生成验收；CI 验证与服务器真实推理必须区分。
