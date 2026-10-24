# MiniMax-H3 代码执行流程

模块对应关系见 [代码结构](code_structure.md)，具体运行命令见 [项目 README](../README.md)。本文件描述实际代码，不将模拟检查等同于完整 GPU 验收。

## 1. 默认一键部署

```mermaid
flowchart TD
    Start[执行 bash deploy.sh] --> Platform[检查 Ubuntu 和 x86_64]
    Platform --> Lock[取得本目录锁并创建日志]
    Lock --> Python[选择或安装兼容 Python]
    Python --> Pre[验证提示词和输出路径及硬件磁盘]
    Pre --> Packages[系统包和虚拟环境]
    Packages --> Deps[安装固定依赖]
    Deps --> Runtime[依赖检查 CUDA 内核及编解码]
    Runtime --> Download[下载两套权重和共享组件]
    Download --> Manifest[验证完整清单和本地文件]
    Manifest --> Index[验证三个工作流本地索引]
    Index --> Full[启动完整验收父进程]
    Full --> Success{三个工作流都通过}
    Success -->|是| Report[记录全流程成功和样片路径]
    Success -->|否| Failure[非零退出并记录失败阶段]
```

前置阶段任一步失败也会停止后续执行。日志启动前的错误可能仅写终端；日志启动后的常规退出写 result/stages。输出与提示词校验在安装依赖、下载模型之前，但缺少 Python 时解释器安装发生在此校验之前。

## 2. 各模式的真实执行范围

| 模式 | Python/系统/依赖安装 | GPU与推理RAM检查 | 完整下载 | 本地索引检查 | 推理 |
| --- | --- | --- | --- | --- | --- |
| 默认 all | 是，复用兼容环境 | 是 | 是，复用缓存 | 是 | 三流程 |
| `--setup` | 是 | 否 | 否 | 否 | 否 |
| `--prepare` | 是 | 否 | 是 | 是 | 否 |
| `--download` | 否 | 否 | 是 | 是 | 否 |
| `--check` | 否 | 是 | 否 | 是 | 否 |
| `--test` | 否 | 是 | 否 | 是 | 仅 t2va |
| `--test-all` | 否 | 是 | 否 | 是 | 三流程 |
| `--preflight` | 否 | 是 | 否 | 否 | 否，无日志文件 |

除 `--preflight` 外，正常执行均经过运行时检查；无 GPU 模式仅测试 CPU 导入/编解码。测试模式启用离线模型访问，缺少模型文件会停止并提示 `--download`。

## 3. 缓存下载与损坏恢复

```mermaid
flowchart TD
    Hub[查询固定 revision 文件元数据] --> Select[选择完整 Diffusers 组件]
    Select --> Check[检查组件和权重清单]
    Check --> Missing[比较本地文件存在性和大小]
    Missing --> Space[缺失字节加工作余量 检查磁盘]
    Space --> Fetch[逐文件下载或续传]
    Fetch --> Verify[再次核对全部文件大小]
    Verify --> Save[原子写入完整 manifest]
    Save --> Local[推理前读取本地 manifest]
    Local --> Valid{格式 schema profile 文件均有效}
    Valid -->|是| Ready[返回固定本地 snapshot]
    Valid -->|否| Stop[停止并提示重新执行 download]
```

原有完整文件不会因为 manifest 重建而重下载。文件存在性/大小检查不包含内容 hash 全检；同大小内容损坏是已知限制。异常 manifest JSON、非对象顶层或错误 file map 现在给出统一可操作的恢复提示。

## 4. 验收、生成与新产物发布

```mermaid
flowchart TD
    Accept[acceptance.py] --> Scope{测试范围}
    Scope -->|完整| Fixture[创建独立运行目录和三种输入素材]
    Fixture --> Queue[依次 t2va fl2va ref2va]
    Scope -->|快速| Temp[创建新的临时运行目录]
    Temp --> Quick[只选 t2va]
    Queue --> Spawn[独立进程组启动 generate.py]
    Quick --> Spawn
    Spawn --> Inputs[校验缓存 输入参数和媒体]
    Inputs --> Load[加载当前工作流权重并 CPU 卸载]
    Load --> Generate[模型生成音视频]
    Generate --> ChildVerify[子进程编码并完整验证]
    ChildVerify --> ParentVerify[父进程要求新文件存在并再次解码]
    ParentVerify --> Mode{快速还是完整}
    Mode -->|快速| Publish[原子替换快速测试目标]
    Mode -->|完整| Keep[保留本次独立目录的样片]
    Publish --> Done[记录工作流 passed]
    Keep --> Done
    Done --> More{还有工作流}
    More -->|是| Spawn
    More -->|否| Final[按实际范围写最终报告]
```

生成子进程退出 0 只是必要条件；还必须有本次新文件且验证通过。快速测试失败不会覆盖旧成功样片；完整验收使用新的运行目录。`all_workflows_passed` 只在三个工作流均成功时为 true。

## 5. 失败、超时与常规取消

```mermaid
sequenceDiagram
    participant Shell as deploy.sh
    participant Parent as acceptance.py
    participant Runner as process_runner.py
    participant Child as 生成进程组
    Shell->>Parent: 启动并保存验收进程 PID
    Parent->>Runner: 执行一个工作流并设置时限
    Runner->>Child: 新会话启动生成
    alt 正常完成
        Child-->>Runner: 返回退出码
        Runner->>Child: 回收同组遗留辅助进程
        Runner-->>Parent: 退出码
        Parent->>Parent: 验证新产物 更新报告
    else 超时
        Runner->>Child: 终止进程组并等待回收
        Runner-->>Parent: TimeoutExpired
        Parent->>Parent: 当前 timeout 后续 not_run
        Parent-->>Shell: 124
    else 操作者向 shell 发送 INT 或 TERM
        Shell->>Parent: 转发取消信号并等待
        Parent->>Runner: 抛出可处理的取消异常
        Runner->>Child: 终止进程组并等待回收
        Parent->>Parent: 当前 cancelled 后续 not_run
        Parent-->>Shell: 130 或 143
    end
    Shell->>Shell: 保存最终 result 和阶段结果
```

本图针对生成验收阶段；安装/下载还由各自工具处理终止，不宣称已有通用的全过程任务管理器。SIGKILL、断电和资源内核强杀无法保证最终报告落盘；不能把残留 running 报告当作成功。

## 6. 修改后的验证顺序

按通用规范先建本地计划，再实现；逻辑检查和回归后，使用替身命令模拟昂贵操作，使用真实小进程验证超时/取消，使用真实 CPU 媒体验证格式和接口。最后更新本文件和代码结构，删除计划后交付。

流程图与模拟测试不能替代目标机器的完整权重加载、三流程生成、资源峰值和画质验收。具体本次执行事实见 [project_review.md](project_review.md)。
