# Paper Monitor 中文说明

[English](README.md)

Paper Monitor 是一个本地优先的桌面文献监控工具。它会定期从 Crossref、RSS 和可选的 arXiv 检索论文，按照用户设置的期刊与关键词进行筛选，把结果统一写入本地 SQLite 生命周期数据库，并且只对尚未在软件中展示过的真正新内容发送系统通知。

默认检索方向主要面向全固态电池、固态电解质、电极材料和锂金属负极，但内置的 300 本跨学科期刊目录覆盖 AI、计算机、工程、医学、生命科学、物理、化学、材料、环境、数学和社会科学。用户可以自由修改关键词、期刊范围和检索方向。软件不依赖云端后台或大模型服务，也不会上传阅读记录。

## 当前架构

1. 定时刷新或手动刷新会启动一个有明确边界的短时工作进程，依次完成检索、筛选、本地写入和通知，然后自动退出。
2. Windows 任务计划、托盘操作和主界面刷新共用同一个 SQLite 文献生命周期，不再分别维护相互错配的缓存。
3. 主界面直接读取本地状态，因此打开软件时可以立即看到最近一次刷新后的数据，不会为了显示页面再次进行网络检索。
4. 首页时间线使用来源提供的发表日期；首次检测时间只在内部用于通知与保留期限判断。
5. 主列表只保留最近 30 天的文献，过期后直接从活动数据库中删除。首页只展示精简元数据，不显示摘要。

Windows 后台监控由任务计划程序按设定时间唤醒，检索结束后 Python 工作进程立即退出。关闭主窗口也会释放 Python、WebView 和本地桥接服务。用户可以选择保留一个轻量原生 C 托盘；“登录 Windows 时启动”使用独立任务，只静默启动托盘，不打开窗口，也不会立即联网检索。

## 主要功能

### 1. 桌面应用

Windows 版本使用一个原生窗口展示 Dashboard 和设置页面；重复启动会切换并聚焦已有窗口，不会创建多个相互竞争的窗口。macOS 版本作为普通 Dock 应用运行，可从应用菜单或窗口进入 Dashboard、设置页面、手动刷新和通知测试。

Windows 版关闭窗口后会结束本次界面进程并释放 WebView、Python 和本地服务占用，只保留用户选择启用的轻量原生 C 托盘。托盘本身不包含网络检索、数据库或页面渲染逻辑。开启“后台监控”后，由 Windows 任务计划程序在检索到期时启动一个短时刷新进程；完成检索、存储和通知后进程立即退出，因此两次检索之间不会常驻 Python、WebView 或本地 HTTP 服务。

常用操作包括：

- 手动检索最新文献。
- 打开 Dashboard 查看匹配结果。
- 打开设置并调整检索范围。
- 发送测试通知，确认 macOS 通知权限正常。

### 2. 文献检索

Paper Monitor 使用 Crossref、RSS 和可选的 arXiv 进行文献检索。OpenAlex 默认关闭，公开版本不要求用户配置 API Key。arXiv 属于预发表来源，默认不勾选，需要用户在期刊筛选中手动启用。

检索范围可以通过以下方式控制：

- 选择 Top N 期刊范围。
- 手动勾选或取消特定期刊。
- 手动启用 arXiv 预发表来源。
- 修改检索词和查询语句。
- 调整刷新频率。
- 设置排除词，过滤明显无关的结果。

期刊目录和影响力信息来自随版本冻结的 `journal_metrics.json`。统一显示的 `2Y Impact` 取自 OpenAlex 的 two-year mean citedness；它是开放的两年引用影响指标，不是 Clarivate Journal Impact Factor。默认配置文件是 `config.example.json`。

### 3. 本地生命周期与去重

软件会把已检索到的文章统一记录到本地 SQLite 数据库。定时刷新、托盘刷新和主界面刷新共用同一份状态；已经在软件中展示过或已经成功通知过的论文不会再次通知。活动列表只保留最近 30 天的数据，过期记录会被直接删除，不保留隐藏历史。

本地运行数据默认保存在：

```text
$HOME/Library/Application Support/PaperMonitor
%APPDATA%\PaperMonitor
```

这些运行数据不会上传到 GitHub，也不会上传到外部服务器。

### 4. Dashboard

Dashboard 由本地应用生成，用来查看已经保存的检索结果和分析结果；打开页面本身不会自动触发新的网络检索。

Dashboard 支持：

- 按来源提供的发表日期分组显示文章。
- 显示论文标题、作者、期刊、本地影响力参考和 URL，不在主页显示摘要。
- 按时间、影响因子或相关性排序。
- 对只提供年月的来源保留原始日期精度，不虚构具体日期。
- 点击论文标题跳转到官方页面查看摘要和全文信息。

当按影响因子排序时，文章会按期刊影响因子排列，不再按日期分栏。

### 5. Keyword Analysis

Keyword Analysis 用于统计指定时间范围内的研究热点。它会根据日期范围和期刊范围重新检索文献，并基于标题进行快速分析。

主要功能包括：

- 选择起止日期。
- 选择 Top N 期刊或手动勾选期刊。
- 选择快速分析或更完整的分析模式。
- 自动提取候选关键词。
- 使用屏蔽词过滤通用词或干扰词。
- 编辑自定义分类词库。
- 查看不同分类的占比和文章数量。
- 展开分析文章列表，查看用于统计的论文标题、DOI、期刊和作者。

该功能适合做阶段性热点判断，例如统计某一年或某几个月内，固态电解质、硫化物、氧化物、卤化物、界面、电极等方向的大致占比。

## 下载和安装

打开 GitHub Release 页面：

```text
https://github.com/Dahe-Labs/paper-monitor/releases
```

最新 Release 会把 macOS 和 Windows 下载文件放在同一个版本下，并保持版本号一致，例如：

```text
Paper-Monitor-macOS-x.y.z.pkg
Paper-Monitor-Windows-x.y.z-Setup.exe
Paper-Monitor-Windows-x.y.z.zip
Paper-Monitor-Windows-x.y.z.exe
```

macOS 用户下载 `.pkg` 安装包，双击后按系统提示安装。安装完成后会得到 `/Applications/Paper Monitor.app`。

首次打开时，macOS 可能会提示应用来自互联网或未公证。可以右键点击 `Paper Monitor.app`，选择 `Open`，再确认打开。也可以在系统设置的安全性页面中允许打开。

Windows 用户优先下载 `-Setup.exe` 安装包；需要免安装运行时可下载 ZIP，独立 EXE 也会保留。Windows 发布流程会同时生成 SHA256 校验文件。

## 首次使用

1. 打开 `Paper Monitor.app`。
2. 如果系统请求通知权限，选择允许。
3. 运行一次测试通知，确认通知可以正常弹出。
4. 打开设置，检查默认检索范围和关键词。
5. 点击刷新，等待软件检索并生成 Dashboard。
6. 打开 Dashboard 查看匹配到的文献。

## 设置说明

### 检索设置

这里可以调整：

- 期刊范围：选择 Top 多少的期刊，最高支持到 Top 300。
- 刷新频率：控制后台计划任务多久唤醒一次进行检索。
- 文献检索方向：选择或修改当前研究方向的检索语句。

修改设置后，点击窗口右上角的 `Apply` 生效。没有修改时，`Apply` 会保持不可点击；修改后会变亮，点击后窗口不会关闭，用户可以继续调整其他设置。

### 后台监控

Windows 设置页中的“后台监控”不会把完整应用加入开机启动。启用后只会注册当前用户的 Windows 计划任务，到期时运行一次无窗口刷新并自动退出；关闭该选项会立即移除计划任务，已有配置、数据库和 Dashboard 历史不会被删除。升级安装还会清理旧版本使用的 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\PaperMonitor` 常驻启动项，卸载时则同时移除计划任务和旧启动项。

“登录 Windows 时启动”是另一个独立选项。启用后会注册单独的当前用户登录任务，只在登录后静默启动轻量原生托盘，不打开主窗口，也不会立即执行网络检索；Python 启动器完成托盘交接后随即退出。免安装版同样可以使用这两个计划任务，但任务会记录程序当前的绝对路径；移动解压目录后，需要从新位置打开一次软件以更新任务路径。

### 检索词管理

默认检索词全部为英文。用户可以根据自己的研究方向自由修改。

适合添加的词包括：

- 材料体系，例如 `sulfide electrolyte`、`oxide electrolyte`、`halide electrolyte`。
- 器件方向，例如 `all-solid-state battery`、`lithium metal anode`。
- 机制方向，例如 `interfacial impedance`、`dendrite`。

排除词用于过滤无关结果，例如激光、照明、硬盘等和固态电池无关的语义。

### 期刊筛选

期刊页面支持：

- 按 Top N 自动选择期刊。
- 手动勾选或取消具体期刊。
- 在底部单独启用 arXiv 预发表来源。
- 按名称、别名搜索，或按学科类别筛选。
- 按 `2Y Impact`、目录排名或名称排序显示。
- 使用 300 本跨学科期刊元数据，每本均显示统一的影响力标签。
- arXiv 会显示在候选列表中，但不会被 Top N 自动勾选。

如果用户只想监控少数期刊，可以先选择一个 Top N 范围，再手动取消不需要的期刊。

## 从源码构建

需要：

- macOS
- Xcode Command Line Tools
- Swift Package Manager
- Python 3

运行 Python 测试：

```bash
python -m unittest discover -s tests
```

构建完整 Windows 发布包：

`requirements-windows.txt` 是人工维护的顶层依赖范围；CI、发布以及可复现的本地 Windows 打包统一从 `requirements-windows.lock.txt` 安装。

```powershell
python -m pip install -r requirements-windows.lock.txt
.\scripts\package_windows_release.ps1 -Version 0.1.13
```

运行 macOS 应用测试：

```bash
cd macos/PaperMonitorApp
swift test
```

构建 macOS 应用：

```bash
scripts/build_macos_app.sh
```

构建结果会出现在：

```text
dist/Paper Monitor.app
```

## 项目结构

```text
paper_monitor/          Python 检索、筛选、存储、Dashboard 和关键词分析逻辑
macos/PaperMonitorApp/  macOS 原生应用工程
tests/                  Python 测试
scripts/                构建和安装脚本
windows/                Windows 入口、安装程序和图标资源
journal_metrics.json    期刊影响因子和元数据
config.example.json     默认公开配置模板
```

## 隐私和数据

Paper Monitor 只在本地保存运行数据。默认情况下，它不会上传你的检索历史、匹配论文或配置文件。

公开仓库中不会包含：

- 个人 `config.json`
- SQLite 数据库
- 日志文件
- Crossref 缓存
- 本机构建目录

## 常见问题

### 为什么首次打开会被 macOS 拦截？

当前 Release 是本地签名版本，还没有 Apple notarization。首次打开时需要手动确认，这是 macOS 的安全机制。

### 为什么没有收到通知？

请检查：

- macOS 通知权限是否允许 Paper Monitor。
- 是否开启了专注模式。
- 是否确实检索到了新的匹配文章。
- 已经出现过的文章不会重复通知。

### 为什么某些文章的日期只有年月，或与期刊网页不同？

不同数据来源提供的日期字段和精度可能不同。Paper Monitor 优先采用来源提供的发表日期，并保留原始精度；来源只提供年月时，不会虚构具体日期。首次检测时间只在内部用于通知和保留期限判断，不作为主页上的发表日期。

### 可以换成其他研究方向吗？

可以。用户可以在设置里修改检索词、排除词和查询语句，也可以从 300 本跨学科目录中按类别筛选期刊。默认检索词偏向固态电池方向，但核心逻辑可以用于其他文献监控任务。
