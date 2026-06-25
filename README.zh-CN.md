# Paper Monitor 中文说明

Paper Monitor 是一个本地运行的文献监控工具。它会按照设定的期刊范围和检索词，定期检索新发表或新收录的论文，筛选出与研究方向相关的文章，并通过 macOS 通知和本地 Dashboard 展示结果。

当前版本主要面向全固态电池、固态电解质、电极材料、锂金属负极等电池研究方向。默认配置可以直接使用，也可以在设置里改成自己的关键词、期刊范围和检索方向。

## 主要功能

### 1. macOS 应用

安装后，Paper Monitor 会作为普通 macOS 应用运行，并显示在 Dock。打开应用后，可以从左上角应用菜单或窗口中进入 Dashboard、设置页面、手动刷新和通知测试。

关闭 Dashboard 或设置窗口不会退出应用；只要没有选择 `Quit Paper Monitor`，应用会继续在后台按设置的刷新频率监控并发送通知。

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

默认期刊范围和影响因子信息来自 `journal_metrics.json`。默认配置文件是 `config.example.json`。

### 3. 本地去重

软件会把已检索到的文章记录到本地 SQLite 数据库。已经出现过的论文不会重复通知，只有新匹配文章会进入通知队列。

本地运行数据默认保存在：

```text
$HOME/Library/Application Support/PaperMonitor
```

这些运行数据不会上传到 GitHub，也不会上传到外部服务器。

### 4. Dashboard

Dashboard 是本地生成的 HTML 页面，用来查看检索结果和分析结果。

Dashboard 支持：

- 按检测日期分组显示文章。
- 显示论文标题、期刊、DOI、链接、检测日期和发表日期。
- 按时间、影响因子或相关性排序。
- 对正式发布日期和检测日期不同的文章做额外标注。
- 点击论文标题或 DOI 跳转到官方页面。

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
https://github.com/Stephendahe/paper-monitor/releases
```

最新 Release 会把 macOS 和 Windows 下载文件放在同一个版本下，并保持版本号一致，例如：

```text
Paper-Monitor-macOS-0.1.5.pkg
Paper-Monitor-Windows-0.1.5.exe
```

macOS 用户下载 `.pkg` 安装包，双击后按系统提示安装。安装完成后会得到 `/Applications/Paper Monitor.app`。

首次打开时，macOS 可能会提示应用来自互联网或未公证。可以右键点击 `Paper Monitor.app`，选择 `Open`，再确认打开。也可以在系统设置的安全性页面中允许打开。

Windows 用户下载同版本号的 `.exe` 文件。Windows 包由仓库里的 GitHub Actions Windows 构建流程生成。

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

- 期刊范围：选择 Top 多少的期刊，最高支持到 Top 50。
- 刷新频率：控制应用运行时多久自动检索一次。
- 文献检索方向：选择或修改当前研究方向的检索语句。

修改设置后，点击窗口右上角的 `Apply` 生效。没有修改时，`Apply` 会保持不可点击；修改后会变亮，点击后窗口不会关闭，用户可以继续调整其他设置。

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
- 按影响因子排序显示。
- 使用 Top 50 期刊元数据。
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
python3 -m pytest
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
windows/                Windows 托盘版本的早期入口代码
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

### 为什么某些文章的发表日期和检测日期不同？

部分期刊或数据库会提前收录文章，正式出版日期可能晚于检测日期。Paper Monitor 默认按检测日期排序，并在日期不一致时做额外标注。

### 可以换成其他研究方向吗？

可以。用户可以在设置里修改检索词、排除词和查询语句，也可以调整期刊范围。当前默认配置偏向固态电池方向，但核心逻辑可以用于其他文献监控任务。

## 许可证

本项目使用 MIT License。可以下载、修改、二次开发和分发，但需要保留许可证说明。
