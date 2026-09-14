<!-- 翻译版 — 请与英文版 README.md 保持同步 / Translation — keep in sync with README.md -->

**语言 / Language:** [English](README.md) | [日本語](README-ja.md) | [한국어](README-ko.md) | **简体中文** | [繁體中文](README-zh-hant.md)

# DocuBrowse v1.5.2

<a name="top"></a>

<a href="https://www.producthunt.com/products/docubrowser?embed=true&amp;utm_source=badge-featured&amp;utm_medium=badge&amp;utm_campaign=badge-docubrowser" target="_blank" rel="noopener noreferrer"><img alt="DocuBrowser - Finally search your files by meaning. 100% local, 100% yours | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/featured.svg?post_id=1250608&amp;theme=light&amp;t=1789413804133"></a>

为 Linux（RPM、DEB、tarball）、Windows（zip）和 macOS（dmg）打包。
接口保持稳定；在可能的情况下避免破坏性变更。

**DocuBrowse 把一堆杂乱的文档变成你真正能搜索的东西。**
把它指向你的文件 —— PDF、电子书、Word 文档、笔记，任何东西 —— 它会建立一个
不仅理解关键词、还理解含义的智能索引。搜索“那份关于续租的合同”，即使这些确切
的字眼从未出现也能找到它。点击任意结果，在打开文件之前就能得到即时的 AI 摘要。
支持 PII 识别,并可处理多个文档目录。

DocuBrowse 使用本地 AI 模型完全在你自己的机器上运行 —— 无需联网,无需账户,
无需 API 密钥,也没有按次查询侵蚀令牌预算的费用。**你的数据。你的 AI。**

底层技术:SQLite FTS5 关键词搜索,加上 AI 驱动的语义相似度与摘要生成
(Ollama + nomic-embed-text + dolphin3)。支持多种文档与源代码类型。

> **Docker(实验性 —— 暂不推荐):** 一个容器化部署正在 `docker-experiment`
> 分支上试验。由于 Docker/操作系统的限制以及 DocuBrowse 的安全模型,目前**尚未**
> 实现一个完全可用的方案 —— 特别是,从基于浏览器的容器中在桌面应用里打开文档
> 无法工作(服务器无头,浏览器处于沙箱中)。它在该分支上提供给想要试验的人,
> 但**不推荐使用**。参见该分支上的 `docker/README.md`。

---

## 导航

| | | |
|---|---|---|
| [功能](#features) | [搜索技巧与窍门](#search-tips-and-tricks) | [屏幕截图](#screenshots) |
| [快速开始](#quick-start) | [语言](#languages) | |
| [CLI 参考](#cli-reference) | [配置](#configuration) | [架构](#architecture) |
| [API 端点](#api-endpoints) | [搜索算法](#search-algorithm) | [安全](#security) |
| [文件结构](#file-structure) | [故障排除](#troubleshooting) | [已知限制](#known-limitations) |
| [近期变更](#recent-changes) | | |
| [路线图](#roadmap) | [AI 辅助开发](#ai-assisted-development) | [许可证](#license) |

---

<a name="features"></a>

## 功能

[↑ 顶部](#top)

### 🔍 双搜索模式
- **关键词搜索** —— 通过 SQLite FTS5 进行快速全文搜索(标题、作者、主题、标签、摘录)
- **语义搜索** —— 通过 Ollama 嵌入(nomic-embed-text:latest)实现的 AI 相似度。语义搜索识别*哪些文档*与你的查询相关;随后**深度链接**(见下文)精确定位文档*内部*匹配的位置。
- **混合模式**(默认,“两者”)—— 合并关键词与语义:每份文档取两个分数中较高的一个(两者都命中时略有加成),且必须清除关键词命中或语义下限才会出现。参见[搜索技巧与窍门](#search-tips-and-tricks)。

### 🎯 深度链接 —— 文档内段落搜索
- 从任意关键词或语义结果中,点击**深度链接**即可在该文档*内部*查找匹配段落 —— 按需进行,无需重新索引,无需更改架构。
- 每个段落显示一小段样本和一个位置标签(**页**、**行**或**节**);点击其一即可打开该段落并高亮匹配文本。
- 模式跟随搜索:**语义**搜索按含义查找段落;**关键词**(或混合)搜索按词条查找。
- 散文格式:**PDF、TXT、HTML、Markdown、DOCX、RTF、ODT**、电子书(EPUB、MOBI、AZW3)、DjVu,以及 SGML/XML 家族(XHTML、XML、DocBook、RSS/Atom、OPML)和其他文本/标记格式(reST、AsciiDoc、LaTeX、配置文件、JSON/YAML、电子邮件、源代码)。非散文(电子表格、演示文稿、图表)则回退到用其阅读器打开。
- 深度链接可能返回“未找到”;若如此,很可能是该文档类型尚未被编入处理流程。它已识别出分配给文档的关键词,但目前仍无法真正读取该文档并创建深度链接。我正在尽可能地扩展这一能力,并聚焦于能带来价值的地方(对一份是蒙娜丽莎图片的 PDF 做深度搜索,大概永远不会以这种方式被搜索到)。

### 📖 AI 摘要
- 点击任意文档标题,即可获得一段 Kindle 风格的“书封”式摘要,按需通过 Ollama
  (`dolphin3:latest`)生成,并在首次生成后缓存到数据库中。
  在极简硬件上(仅 CPU、无 GPU),某份文档的首个摘要可能需要一些时间 ——
  由于结果已缓存,后续请求都是即时的。
  语义搜索的嵌入由第二个本地模型(`nomic-embed-text:latest`)生成。

### 📚 文档索引
- **格式**:PDF、DOCX、PPTX、XLSX、ODT、ODS、ODP、OTT/OTS/OTP(ODF 模板)、VSDX/VSDM、VSD/VSS/VST(旧版 Visio)、VDX(Visio 2003 XML)、draw.io/diagrams.net(.drawio/.dio)、PlantUML(.puml/.plantuml)、Mermaid(.mmd)、SGML/XML 家族(.xml/.xhtml/.sgml/.sgm)、DocBook(.docbook/.dbk)、SVG、订阅源(.rss/.atom/.opml)、reStructuredText(.rst)、AsciiDoc(.adoc/.asciidoc)、LaTeX(.tex/.latex)、电子邮件(.eml)、RTF(.rtf)、CSV / TSV、EPUB、MOBI、AZW3、AZW、DjVu(.djvu/.djv)、HTML、TXT、Markdown,以及类配置纯文本(.ini/.conf/.cfg/.log/.lst)
- **PDF 智能处理**:pdfplumber(优先)加上 pypdf 回退以处理臃肿对象文件;对复杂版式进行 `layout=False` 重试;检测扫描(纯图像)PDF 并路由到 `ocr_list_pdfs.txt`
- **Word 文档**:python-docx 提取段落、表格和核心属性(标题、作者、主题)
- **演示文稿**:python-pptx 提取幻灯片文本、备注和核心属性
- **电子表格**:openpyxl 提取单元格值和工作表名称
- **OpenDocument**:ODF 文本文档(.odt)、电子表格(.ods)和演示文稿(.odp),以及它们的模板变体(.ott/.ots/.otp)—— 通过 Python 标准库(`zipfile` + `xml.etree.ElementTree`)提取段落、标题、列表、表格、单元格值和幻灯片文本。模板按 mimetype 前缀路由到匹配的提取器。元数据(标题、作者、主题、描述、关键词)从 `meta.xml` 读取。无需额外依赖。
- **Visio 与图表**:
  - 现代 Visio(`.vsdx`/`.vsdm`)—— 用标准库解析的 OOXML zip;提取形状文本、页面名称和核心属性(标题/作者/主题/关键词),无需第三方依赖。
  - 旧版 Visio(`.vsd`/`.vss`/`.vst`)—— 二进制复合文档;需要来自 **libvisio-tools** 的可选 `vsd2xml` 工具(`sudo dnf install libvisio-tools` / `sudo apt install libvisio-tools`)。没有它时,旧版文件仅按元数据索引(文件名作为标题,无正文),并将路径追加到 `visio_legacy_missing.txt`,以便安装后重新扫描时可以识别它们。
  - draw.io / diagrams.net(`.drawio`/`.dio`)—— 支持纯 `mxfile` XML 和压缩(`deflate + base64 + URL 编码`)图表;提取每个 `mxCell` 标签和 `object` 标签,以及页面名称。仅使用标准库。
  - 基于文本的图表 —— PlantUML(`.puml`/`.plantuml`)和 Mermaid(`.mmd`)源码作为纯文本索引,并标记为 `diagram`。
- **标记家族**(全部使用标准库,无额外依赖):
  - XML/SGML(`.xml`/`.xhtml`/`.sgml`/`.sgm`)、DocBook(`.docbook`/`.dbk`)、SVG(同时标记为 `diagram`)和订阅源(`.rss`/`.atom`/`.opml`)会被去标签 —— 移除 DOCTYPE、注释、CDATA 包装、`<script>` 和 `<style>` 块,并删除其余标签;实体被反转义。在去标签之前,会从熟知的元素(`<title>`、`<dc:title>`、`<author>`、`<dc:creator>`)嗅探标题/作者/主题,因此 DocBook、Atom、RSS 和 SVG 都能呈现有用的元数据。
  - reStructuredText(`.rst`)、AsciiDoc(`.adoc`/`.asciidoc`)和 LaTeX(`.tex`/`.latex`)按原样索引(所有标记都成为可搜索文本),并采用逐格式的标题启发式:reST 下划线式标题、AsciiDoc 的 0 级 `= 标题`、LaTeX 的 `\title{}` / `\section{}`。LaTeX 的 `\author{}` 会被捕获,行内 `%` 注释会被剥除。
  - 每个标记文件都被标记为 `markup` 以便浏览/筛选。`.vdx`(Visio 2003 XML)也会获得 `diagram` 标签。
- **电子邮件、RTF、表格与类配置文本**:
  - 电子邮件(`.eml`)—— 用标准库 `email` 包解析。Subject 成为标题,From 成为作者,To/Cc/Date 和纯文本正文(或去标签的 HTML 正文)成为可搜索内容。附件文件名会被追加,以便按名称搜索仍能命中。
  - RTF(`.rtf`)—— 通过 **striprtf**(纯 Python,MIT)解码。没有它时,文件仅按元数据索引,路径追加到 `rtf_missing_striprtf.txt`;安装 `striprtf` 并重新扫描即可提取正文。
  - CSV / TSV —— 前约 500 行被索引,行以竖线分隔渲染;表头行落入 `description` 字段,因此列名会计入关键词搜索。仅使用标准库;自动检测分隔符。
  - 类配置纯文本 —— `.ini`、`.conf`、`.cfg`、`.log`、`.lst` 走标准文本路径,采用相同的 200 KB 读取上限。
- **电子书**:EPUB 使用 ebooklib;MOBI/AZW3 文本提取使用 mobi 包 + Calibre `ebook-convert` 回退;DRM 加密的 AZW 文件仅按元数据索引(标题/作者可见,正文不可搜索)
- **DjVu**:`.djvu`/`.djv` 文本层通过 **DjVuLibre**(`djvutxt`/`djvused`,外部非 pip 工具)提取。没有它时,DjVu 文件仅按元数据索引,路径追加到 `djvu_missing_djvulibre.txt`;安装 DjVuLibre 并重新扫描以获取正文。无文本层的纯图像 DjVu 仅按元数据索引(不执行 OCR,与扫描 PDF 相同)
- **平台**:所有提取库都是纯 Python 或对 x86_64 和 ARM64 都提供 wheel。不支持 32 位系统。
- **元数据**:从文档元数据字段提取标题、作者、主题;从目录结构和内容关键词自动生成标签
- **PII 保护**:摄取后扫描器检测 SSN、信用卡、银行路由/账号、出生日期、MRN、驾照、护照模式;移除匹配的文档并永久将其列入黑名单

### 🎨 用户界面
- 深色/浅色主题切换
- 分页结果(每页 50 份文档),带上一页/下一页控件
- 字母索引栏(A–Z、0–9)用于快速导航,状态在页面加载间保留;Home 按钮用于重置
- 用于按主题筛选的标签云
- 每个结果上的相关度分数徽章(0–100%)
- 每张结果卡片上的**打开按钮** —— 通过 `xdg-open` 在默认应用中启动文件
- 点击文档标题获取 AI 摘要;📋 复制路径到剪贴板;🗑 从磁盘和索引中删除文件(需确认)
- 已移动/已删除的文档:点击文件已不存在的文档,若其文件系统已挂载,会显示一个可关闭的模态框(关闭时从索引中移除它);若无法验证文件系统(例如未挂载的驱动器),则显示一个提示条(不更改索引)

### ⚙️ 设置(`/settings`)
- 常规面板:文档目录(带实时目录浏览器)、任意数量的额外扫描目录(在同一面板下添加/移除 —— 自动纳入 `scan`/`rescan`,无需额外命令)、工作目录和端口
- 忽略目录面板:浏览以将目录添加到 `ignore_dirs.txt`,在清除其下已索引文档前有确认提示,移除条目前也有确认

### ⚡ 性能
- 搜索延迟:通常 <150ms
- 使用 `ProcessPoolExecutor` 的并行 PDF 提取(按物理核心数确定工作进程数)
- 内存安全:内核强制的 RLIMIT_AS(每工作进程 6 GB)+ 在空闲 RAM 阈值上暂停/恢复

---

<a name="search-tips-and-tricks"></a>

## 搜索技巧与窍门

[↑ 顶部](#top)

DocuBrowse 有三种搜索模式(在右上角切换):**关键词**、**语义**和**两者**(默认的混合)。**按下回车时才执行搜索** —— 清空搜索框会再次显示所有文档。当你点击**深度链接**时,文档内部适用相同的规则;深度链接跟随你的搜索所用的模式。

### 三种模式

- **关键词** —— 通过 SQLite FTS5 的字面文本。每个词都做前缀匹配,词之间是“或”的关系,因此 `budget report` 会找到包含 *budget…* **或** *report…* 的文档(不一定两者都有)。按命中位置排名 —— **标题**和**作者**中的匹配优先于正文或标签中的匹配。当你知道文档中确实存在的某个词、名称或代码时最佳。
- **语义** —— 通过 AI 嵌入的含义。即使文档不包含你的确切字眼,也能找到*关于*你查询的文档。按概念接近度排名。当你不知道确切措辞、想找“关于 X 的文档”时最佳。
- **两者**(默认)—— 同时运行两者,并为每份文档保留两个分数中较强的一个(某文档在两者上都得分时略有提升)。文档必须赢得一个关键词命中或有意义的语义分数才会出现,因此微弱的语义噪声不会淹没扎实的关键词匹配。

### 不同词语搭配下会发生什么

| 你输入 | 关键词模式 | 语义模式 |
|---|---|---|
| `budget report` | 含 *budget…* **或** *report…* 的文档(前缀,任一词) | 关于预算/财务报告的文档,按含义 |
| `"budget report"` | 仅含确切短语 **budget report** 的文档 | 同一确切短语集,然后按含义排名 |
| `freedom and liberty` | *freedom…* 或 *and…* 或 *liberty…*(关键词保留每个词) | 嵌入 **freedom liberty** —— 冠词和连词被丢弃,以免稀释匹配 |
| `man in the middle` | *man… in… the… middle…*(前缀,任意) | 嵌入 **man in middle** —— 冠词 *the* 被丢弃,但介词 *in* 被保留(介词承载含义) |
| `"man in the middle"` | 仅含该确切短语的文档(不区分大小写) | 首先要求确切短语,然后按含义为该集合排名 |
| 人名,如 `fred` | 以 *fred* 开头的词条 —— Frederick、Fredonia… | 模糊:可能浮现相似词(如 *Fedora*),因为短词条嵌入得较松散 —— 对人名请用**关键词** |

### 引号 = 确切短语

用 `"..."`(或 `'...'`)包住词语,以要求那个**确切的连续短语**(匹配不区分大小写)。`"machine learning"` 只匹配这两个词按该顺序一起出现的文档,而不匹配仅分别提及 *machine* 和 *learning* 的文档。这在每种模式下都有效 —— 在语义/两者中,它先作为存在过滤器,然后按含义为包含该短语的集合排名。你可以混用形式:`golang "import fmt"` 表示*短语 "import fmt"* 或松散的词 *golang*。

具体来说,引号决定了小词是否计入。**`"man in the middle"`** 搜索整个短语,每个词都包括在内。**`man in the middle`**(无引号)在语义模式下会在匹配前丢弃冠词 *the* —— 它按 *man*、*in*、*middle* 搜索 —— 因为只有冠词(*a/an/the*)和连词(*and/or/but/nor/for/so/yet*)被视为填充词。当确切措辞重要时,请给短语加引号。

### 经验法则

- 知道确切的词、名称或错误代码 → **关键词**。
- 寻找*关于*某主题的文档 → **语义**或**两者**。
- 想要确切短语 → **给它加引号**(任意模式)。
- 搜索**人名** → **关键词**胜过语义(人名嵌入得较模糊)。
- 语义可以为一个从未字面命名的概念浮现出文档 —— 例如,一份 MIT 许可的文件会因为许可证文本的表述而在搜索 *freedom* 时出现。这是语义按预期工作,而非 bug。

---

<a name="screenshots"></a>

## 屏幕截图

[↑ 顶部](#top)

点击任意缩略图查看完整尺寸。

| 深色模式 | 浅色模式 |
|---|---|
| [![Dark mode](screenshots/screenshot-dark-mode.png)](screenshots/screenshot-dark-mode.png) | [![Light mode](screenshots/screenshot-light-mode.png)](screenshots/screenshot-light-mode.png) |

| 设置 | AI 摘要 |
|---|---|
| [![Settings page](screenshots/screenshot-settings-page.png)](screenshots/screenshot-settings-page.png) | [![Synopsis modal](screenshots/screenshot-synopsis-modal.png)](screenshots/screenshot-synopsis-modal.png) |

### 深度链接 —— 文档内段落搜索

从任意关键词或语义结果,**深度链接**会在该文档*内部*查找匹配段落,跳转到其中之一,并高亮匹配文本。

三个阶段 —— 结果上的**深度链接**按钮、列出匹配段落的模态框,以及被选中并高亮的段落:

| 语义搜索结果 | 匹配段落 | 高亮段落 |
|---|---|---|
| [![Semantic search results with Deep Links](screenshots/deep-links-semantic-results.png)](screenshots/deep-links-semantic-results.png) | [![Semantic Deep Links passage list](screenshots/deep-links-semantic-list.png)](screenshots/deep-links-semantic-list.png) | [![Semantic Deep Links passage](screenshots/deep-links-semantic-passage.png)](screenshots/deep-links-semantic-passage.png) |

| 关键词搜索结果 | 匹配段落 | 高亮段落 |
|---|---|---|
| [![Keyword search results with Deep Links](screenshots/deep-links-keyword-results.png)](screenshots/deep-links-keyword-results.png) | [![Keyword Deep Links passage list](screenshots/deep-links-keyword-list.png)](screenshots/deep-links-keyword-list.png) | [![Keyword Deep Links passage](screenshots/deep-links-keyword-passage.png)](screenshots/deep-links-keyword-passage.png) |

> 深度链接以黄色渲染文档提取文本中的匹配片段,并按其位置(页/行/节)标注。模式跟随搜索:语义搜索打开语义段落,关键词打开关键词段落。

> 设置是位于 `/settings` 的独立页面(通过齿轮图标在新标签页中打开)。常规面板涵盖文档目录(带实时目录浏览器,以及任意数量的额外扫描目录)、工作目录和端口;忽略目录面板管理扫描排除项,每项都带目录浏览器、添加/清除控件,以及移除前的确认。

---

<a name="quick-start"></a>

## 快速开始

[↑ 顶部](#top)

### 系统要求

**最低:** 8 GB 内存,x86_64 或 ARM64 CPU,2 GB 可用磁盘(外加你的文档和索引所需空间)。无 GPU 也能工作 —— 摘要生成会较慢但可用。不支持 32 位系统(Ollama 不提供 32 位构建)。

**推荐:** 12 GB 内存,4 GB 以上显存(NVIDIA 或 Apple Silicon)。GPU 加速能显著加快摘要生成和嵌入。

### 前置条件
- Python 3.9+
- `pdfplumber`、`pypdf` —— PDF 提取
- `python-docx` —— Word 文档
- `python-pptx` —— PowerPoint 演示文稿
- `openpyxl` —— Excel 电子表格
- `ebooklib`、`beautifulsoup4`、`mobi` —— 电子书
- `striprtf` —— RTF 文本提取(纯 Python;没有它时 .rtf 仅按元数据索引)
- `psutil` —— 跨平台进程与硬件检测
- **Calibre** —— 电子书元数据与转换(MOBI/AZW3/AZW 索引所需):
  `sudo dnf install calibre` 或 `sudo apt install calibre`
- **libvisio-tools** —— *可选*;仅在从旧版二进制 Visio(`.vsd`/`.vss`/`.vst`)提取正文时需要。
  没有它时,这些文件仍按元数据索引。
  `sudo dnf install libvisio-tools` 或 `sudo apt install libvisio-tools`
- **DjVuLibre** —— *可选*;仅在从 DjVu(`.djvu`/`.djv`)提取文本时需要。
  没有它时,这些文件仍按元数据索引。
  `sudo dnf install djvulibre` / `sudo apt install djvulibre-bin` / `brew install djvulibre` / `choco install djvu-libre`
- Ollama —— 若缺失,由 `docubrowser start` 自动安装
- 现代浏览器(Chrome、Firefox、Safari、Edge)

完整的分步指南参见 [INSTALL.md](INSTALL.md)。

### 安装(推荐)

DocuBrowse 以 RPM、DEB、tarball、Windows zip 和 macOS dmg 包形式发布。
从 [Releases](https://github.com/linuxrebel/DocuBrowser/releases) 页面下载合适的包。

```bash
# Fedora / RHEL
sudo dnf install ./docubrowser-foss-<VERSION>-<RELEASE>.noarch.rpm

# Debian / Ubuntu / Mint
sudo apt install ./docubrowser-foss_<VERSION>-<RELEASE>_all.deb

# 任意 Linux(tarball)
tar xzf docubrowser-foss-<VERSION>-<RELEASE>.tar.gz
cd docubrowser-foss-<VERSION>-<RELEASE>
sudo ./install.sh
```

**Windows:** 解压 zip,然后双击 `Install.bat`。需要预先安装 Python 3.9+ 和 Ollama。
安装到 `%USERPROFILE%\DocuBrowse`,并带一个开始菜单快捷方式 —— 无需管理员权限。
你可能需要注销并重新登录,快捷方式才会出现。

**macOS:** 打开 dmg,然后双击 `Install.command`(首次请右键 → 打开 —— 这些脚本未签名)。需要 Python 3.9+。
安装到 `~/Applications/DocuBrowse/`,带 Python 虚拟环境、位于 `/usr/local/bin/docubrowser` 和 `/usr/local/bin/docuback` 的 CLI
包装脚本(会提示 sudo;若拒绝则回退到 `~/bin/`),以及一个启动服务器并在终端中打开 Web UI 的 `DocuBrowse.app` 启动器。

所有 Linux 方法都安装到 `/opt/docubrowser/`,带 Python 虚拟环境、位于 `/usr/bin/docubrowser` 和 `/usr/bin/docuback` 的
CLI 包装脚本、Office 下的桌面菜单项,以及来自 `requirements.txt` 的所有 Python 依赖。

安装后,CLI 就是 `docubrowser` 命令 —— 从下面每个示例中去掉 `./` 和 `.py`。
例如 `docubrowser start` 和 `docubrowser rescan`。本 README 其余部分显示的
`./docubrowser.py <cmd>` 形式是开发/克隆仓库路径(直接从检出目录运行)。

卸载:`sudo dnf remove docubrowser-foss`(RPM)、
`sudo apt remove docubrowser-foss`(DEB)、`sudo ./uninstall.sh`(tarball)、
双击 `Uninstall.bat`(Windows),或双击 `Uninstall.command`
(macOS —— 在 dmg 上或 `~/Applications/DocuBrowse/` 中)。

### 首次运行(开发/克隆仓库)

```bash
cd /path/to/DocuBrowse

# 扫描并索引你的文档
./docubrowser.py rescan

# 启动服务器
./docubrowser.py start

# 打开 UI
./docubrowser.py open
```

> 在已安装的系统上,请改用 `docubrowser` 命令,例如
> `docubrowser rescan` / `docubrowser start` / `docubrowser open`。

`docubrowser.py start` 会自动验证 Ollama 已安装、正在运行,并具备两个所需
模型 —— `nomic-embed-text:latest`(嵌入)和 `dolphin3:latest`(摘要生成)——
按需安装/启动/拉取。

---

<a name="cli-reference"></a>

## CLI 参考

[↑ 顶部](#top)

```
用法: docubrowser.py <command> [options]
```

### 命令

| 命令 | 描述 |
|---------|-------------|
| `start` | 启动搜索服务器(先运行 Ollama 检查) |
| `stop` | 停止服务器 |
| `restart` | 先停止再启动 |
| `status` | 显示服务器状态、文档数、嵌入数、标签数 |
| `scan [TYPE ...]` | 扫描、索引并嵌入文档(与 `rescan` 相同;用 `--no-embed` 跳过嵌入) |
| `rescan [TYPE ...]` | `scan` 的别名(为向后兼容而保留) |
| `scan-file --file PATH` | 提取并索引单个文件,然后嵌入它 |
| `embed` | 为未嵌入的文档生成/刷新嵌入 |
| `open` | 在默认浏览器中打开 DocuBrowse UI |
| `purge` | 扫描索引以查找 PII 并移除匹配的文档 |
| `ignore add\|remove\|list DIR` | 管理从扫描中排除的目录(添加时自动清除) |
| `report` | 遍历文档目录并显示文件类型分布(不更改数据库) |
| `scan-missing [--db PATH] [--dry-run]` | 可选清理:将每个已索引路径分类为存在/缺失/未挂载,删除 `missing` 行(级联),不动 `unmounted` 行 |
| `stopall` | 停止所有正在运行的扫描、嵌入以及服务器 |
| `duplist` | 列出重复文档(精确 SHA256 + 可选近似重复) |
| `dupclean` | 交互式 TUI,用于审查并移除重复文档 |

### 全局选项

```
--db PATH      SQLite 数据库路径(覆盖配置)
--port PORT    服务器端口(覆盖配置)
--config FILE  配置文件路径
```

### 命令示例

```bash
# 服务器管理
./docubrowser.py start
./docubrowser.py start --port 9000
./docubrowser.py status
./docubrowser.py stop
./docubrowser.py stopall

# 扫描(scan 和 rescan 完全相同)
./docubrowser.py scan                          # 扫描、索引并嵌入所有类型
./docubrowser.py scan pdf                      # 仅 PDF
./docubrowser.py scan pdf txt                  # PDF 和纯文本
./docubrowser.py scan --limit 100              # 仅前 100 个未索引文件
./docubrowser.py scan --workers 4              # 4 个提取工作进程
./docubrowser.py scan --no-embed               # 扫描但不执行嵌入步骤
./docubrowser.py scan --doc-dir /data/docs

# 单文件索引(对重试被列入黑名单的文件很有用)
./docubrowser.py scan-file --file /path/to/document.pdf
./docubrowser.py scan-file --file /path/with spaces/doc.pdf   # 无需引号
./docubrowser.py scan-file --file /path/to/doc.pdf --no-embed

# 报告与维护
./docubrowser.py report                         # 文件类型分布,不更改数据库
./docubrowser.py embed                          # 嵌入任何未嵌入的文档
./docubrowser.py purge --dry-run               # 预览 PII 匹配(安全)
./docubrowser.py purge                         # 移除 PII 文档(会提示)

# 从扫描中排除目录
./docubrowser.py ignore add ~/Documents/myWorkDocs   # 排除 + 清除其下已索引文档
./docubrowser.py ignore list                                  # 显示已忽略目录
./docubrowser.py ignore remove ~/Documents/myWorkDocs # 重新允许(重新扫描以重新索引)

# 重复检测与清理
./docubrowser.py duplist                       # 查找精确 SHA256 重复
./docubrowser.py duplist --near-dups           # 也查找近似重复(余弦 ≥97%)
./docubrowser.py duplist --near-dups --threshold 0.95
./docubrowser.py dupclean                      # 交互式 保留 A/保留 B/两者都保留 TUI
./docubrowser.py dupclean --near-dups          # 在清理中包含近似重复

# 清理已移动/已删除的文档(可选,不自动运行)
./docubrowser.py scan-missing --dry-run        # 仅报告数量,不更改数据库
./docubrowser.py scan-missing                  # 删除真正缺失文件的行

# 移除旧版本索引的点文件(独立的一次性工具)
python3 purge_dotfiles.py                       # 试运行:分页显示完整列表,不做更改
python3 purge_dotfiles.py --apply               # 删除它们(级联安全)
python3 purge_dotfiles.py --db /path/du.db --roots /docs /extra --apply
```

> `purge_dotfiles.py` 是一个过渡性迁移工具,直接运行(不是 `docubrowser`
> 子命令)。扫描器今后已经会跳过点文件(D-6);此工具清除旧版本遗留在数据库中的行。
> 它使用与扫描器相同的、感知根目录的隐藏路径检查(有意扫描的点目录根是豁免的)
> 以及级联安全的删除路径,因此 FTS 行、标签和嵌入都能被正确清理。默认为试运行;
> `--apply` 执行删除;`--db` / `--roots` 覆盖默认值。

### scan / rescan 类型过滤器

```
类型: pdf  txt  md  html  (默认: 所有支持的类型)

示例:
  scan pdf               仅 PDF
  scan pdf txt           PDF 和纯文本
  scan                   所有支持的类型(未过滤时会提示)
```

### scan-file 细节

`scan-file` 专为重试个别问题文件而设计:
- 若文件在 `scan_blacklist.txt` 中列出,则将其移除(显式重试)
- 拒绝 `pii_blacklist.txt` 中的文件(永久 PII 阻止)
- 检测扫描(纯图像)PDF → 添加到 `ocr_list_pdfs.txt`
- 带空格的路径无需引号即可工作:`--file` 接受多个 token 并将其重新拼接

---

<a name="configuration"></a>

## 配置

[↑ 顶部](#top)

DocuBrowse 读取它找到的第一个配置文件:

1. `/etc/docubrowse.config`(系统级)
2. `./docubrowse.config`(在 `docubrowser.py` 旁边)

若两者都不存在,则应用内置默认值 —— 但 `doc_dir` 除外,它没有默认值。
在配置文档目录之前(通过 Web UI 中的设置齿轮图标,或在 `docubrowse.config`
中设置 `doc_dir`),Web UI 会显示一个横幅提示你去配置一个,而需要文档目录的
CLI 命令(`rescan`、`report`、`scan`)会以错误退出,并说明如何设置它。

### 配置文件格式

```ini
# docubrowse.config
doc_dir      = ~/Documents
db_path      = /home/user/DocuBrowse/du-docs.db
port         = 8643
work_dir     = /home/user/DocuBrowse
lang         = en
```

### 默认值

| 键 | 默认 |
|-----|---------|
| `doc_dir` | _(无 —— 必须通过设置或 docubrowse.config 配置)_ |
| `db_path` | `<脚本目录>/du-docs.db` |
| `port` | `8643` |
| `work_dir` | `<脚本目录>` |
| `lang` | `en` —— 参见[语言](#languages) |

### 环境变量

环境变量覆盖对应的配置文件键(对容器有用)。提供 CLI 标志时仍以其为准。

| 变量 | 默认 / 覆盖 | 描述 |
|----------|---------------------|-------------|
| `DOCUBROWSE_DOC_DIR` | 配置 `doc_dir` | 要索引的主文档目录 |
| `DOCUBROWSE_DB` / `DOCUBROWSE_DB_PATH` | 配置 `db_path` | `du-docs.db` 的路径 |
| `DOCUBROWSE_PORT` | `8643` | HTTP 服务器端口 |
| `DOCUBROWSE_WORK_DIR` | 配置 `work_dir` | 运行时数据的工作目录 |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama HTTP API 的基础 URL(嵌入 + 摘要)。接受裸 `host:port`(scheme 默认为 `http://`)。也接受为 `DOCUBROWSE_OLLAMA_HOST`。 |
| `DOCUBROWSE_TRUSTED_CIDRS` | _(空)_ | 除回环外允许访问服务器的、以逗号分隔的 CIDR/IP(例如单个 Docker 代理的 `172.17.0.2/32`,或确切的 Compose 子网)。空 = 仅回环。宽于 `/24`(IPv4)或 `/120`(IPv6)的范围会被拒绝 —— 信任一台主机,而非整个网络;首选 `/32`。**这不是身份验证** —— 只列出反向代理/BFF 之后的私有网络。 |
| `DOCUBROWSE_ALLOWED_HOSTS` | _(空)_ | 除回环外接受的、以逗号分隔的 Host 头名称(例如 `docubrowse`)。当 `Host` 中出现容器服务名时需要。 |

当省略 argv 时,`doc_search.py` 也接受 `DOCUBROWSE_DB` / `DOCUBROWSE_PORT`,
因此容器入口点仅凭环境变量即可启动服务器。
`OLLAMA_HOST` 由 `doc_search.py`、`embed_docs.py` 和 `ensure_ollama.py` 读取 ——
当 Ollama 运行在另一台主机或容器上时设置它(例如 Docker Compose 中的
`http://ollama:11434`)。

仍然没有用户登录。受信任的对等方可以调用完整的 API;把身份验证放在你的反向代理或 BFF 中,永远不要公开 DocuBrowse 的端口。

---

<a name="languages"></a>

## 语言

[↑ 顶部](#top)

一个 DocuBrowse 安装一次只服务**一种**语言 —— 界面、FTS 分词器、嵌入模型和
摘要模型全都为那一种语言选择。这是每次安装的设置,而非每份文档的设置:
DocuBrowse 假定所配置的文档目录压倒性地是一种语言,不支持混合语言语料库或
逐文档的语言检测。

**当前支持:** 英语(`en`,默认)、日语(`ja`)、韩语(`ko`)、简体中文(`zh`)和
繁体中文(`zh-hant`)。日语、韩语和两种中文变体都使用 `bge-m3` 多语言嵌入模型
(英语使用 `nomic-embed-text`);韩语的摘要模型是 `exaone3.5`,两种中文变体都使用
`ornith-1.5:9b`(繁体由一个强制输出 繁體/正體字 的提示词驱动)。对于关键词(FTS5)
搜索,CJK 文本(日语、韩语和中文)使用标准 `unicode61` 分词器加上应用侧字符二元组
分割(参见 `cjk.py`),而非 FTS5 内置的 `trigram` 分词器 —— 日语词间没有空格,
韩语是膠着语,而中文根本没有词边界,因此索引时和查询时的文本都在 FTS5 看到之前
被预先切分为重叠的 2 字符二元组。同一个分割器同时覆盖简体和繁体字符(两者都在
CJK 统一表意文字范围内),因此无需单独处理。这不是形态素分割器(无
MeCab/jieba/konlpy 依赖);它是一个零依赖的替代方案,以语言学上的正确性换取可靠地
索引每个 2 字符以上的 CJK 子串。单个 CJK 字符在关键词模式下不会精确匹配(有意设计
—— 单字符匹配噪声太大),但仍会通过两者/语义搜索浮现。

**韩语字母索引栏:** 韩语是真正的字母文字(不同于假名和汉字没有首字母排序的日语),
因此文档列表索引栏对韩语启用,并显示 14 个基本首辅音(初声):ㄱ ㄴ ㄷ ㄹ ㅁ ㅂ ㅅ
ㅇ ㅈ ㅊ ㅋ ㅌ ㅍ ㅎ。每个按钮筛选标题以由该辅音引导的音节开头的文档(紧音折叠回其
基础辅音,例如 ㄲ→ㄱ)。英语使用 A–Z/0–9 栏;该栏对日语和中文(简体和繁体都)隐藏
—— 中文不是字母文字、没有首字母排序,与日语被隐藏的原因相同。

**选择语言:**

- **安装时** —— 全新安装时 `install.sh` 会询问语言。用 `DOCUBROWSE_LANG=en`、
  `=ja`、`=ko`、`=zh` 或 `=zh-hant` 进行非交互式回答。**升级绝不重新询问** ——
  `docubrowse.config` 中已有的 `lang` 值始终被保留。(平台安装程序 ——
  Windows/macOS/RPM/DEB —— 将新安装默认为 `lang = en`;之后通过设置更改。)
- **启动时** —— `docubrowser ko start`(或 `docubrowser start ja`)以该语言启动
  服务器;代码可出现在任一位置。选择会被写入 `docubrowse.config`,因此在你选择
  另一种语言之前,它会为之后普通的 `docubrowser start` 运行持续保留。
- **安装后** —— 打开 Web UI,点击设置(齿轮)图标,并使用常规面板中的语言下拉菜单
  (调用 `POST /api/language`)。切换到使用不同嵌入器或 FTS 分词器的语言(例如
  英语 ↔ 日语/韩语)会显示一个警告:在你重新运行 `docubrowser rescan`(或
  `embed_docs.py`)以为新语言重建之前,现有文档会保留其旧的嵌入和 FTS 索引 ——
  在那之前,先前已索引文档的搜索质量会下降。(日语 ↔ 韩语共享 `bge-m3` 嵌入器和
  相同的分词器,因此这两者之间无需重建。)

**尚不支持:** 混合语言或逐文档的语言语料库、英语/日语/韩语/中文以外的语言
(`lang_models.py` 中的 `LANG_MODELS` 表加上一个 `locales/<code>.json` 文件就是全部
机制,因此新增一种是数据变更,而非代码变更)、面向日语/中文文档列表的假名/读音(或
拼音)索引栏(两者都没有首字母排序;韩语使用上文所述的初声栏),以及日语“My Number”
PII 检测(目前仅实现了美国 PII 模式)。

---

<a name="architecture"></a>

## 架构

[↑ 顶部](#top)

```
┌─────────────────────────────────────┐
│  docubrowser.py  (CLI entry point)  │
│  ensure_ollama.py (prereq check)    │
└──────────┬──────────────────────────┘
           │ subprocess / direct call
           ↓
┌──────────────────────┐  ┌─────────────────────────────────┐
│  scan_docs.py        │  │  doc_search.py  (HTTP :8643)    │
│  ProcessPoolExecutor │  │  GET /  /api/search             │
│  pdf_extractor.py    │  │  GET /api/stats  /api/tags      │
│  embed_docs.py       │  │  GET /api/open  /api/config     │
│                      │  │  GET /api/delete /api/synopsis  │
│                      │  │  GET /api/deep-links            │
└──────────┬───────────┘  └──────────────┬──────────────────┘
           │                             │
           └──────────┬──────────────────┘
                      ↓
        ┌──────────────────────────────────────────────────┐
        │  du-docs.db  (SQLite FTS5)                       │
        │  Ollama (nomic-embed-text + dolphin3)            │
        └──────────────────────────────────────────────────┘
```

### 关键脚本

| 脚本 | 角色 |
|--------|------|
| `docubrowser.py` | CLI 启动器 —— 所有命令 |
| `ensure_ollama.py` | 检查/安装 Ollama 二进制、服务和所需模型 |
| `doc_search.py` | HTTP 服务器;搜索 API 和 UI |
| `docubrowse_db.py` | SQLite 架构和迁移 |
| `platform_paths.py` | 跨平台路径解析和进程管理 |
| `scan_docs.py` | 文档发现、提取和数据库写入 |
| `pdf_extractor.py` | 使用 pdfplumber/pypdf 的 PDF 专用提取 |
| `docx_extractor.py` | Word 文档提取(python-docx) |
| `odf_extractor.py` | OpenDocument(.odt、.ods、.odp)提取(标准库) |
| `visio_extractor.py` | Visio + draw.io 提取(.vsdx/.vsdm/.vsd/.vss/.vst/.drawio/.dio) |
| `markup_extractor.py` | SGML/XML 家族 + reST/AsciiDoc/LaTeX(标准库) |
| `eml_extractor.py` | 电子邮件(.eml),通过标准库 `email` |
| `csv_extractor.py` | CSV / TSV,通过标准库 `csv` |
| `rtf_extractor.py` | RTF,通过 `striprtf`(缺失时优雅降级) |
| `djvu_extractor.py` | DjVu(.djvu/.djv),通过 DjVuLibre `djvutxt`/`djvused`(缺失时优雅降级) |
| `ebook_extractor.py` | EPUB/MOBI/AZW3/AZW 提取(ebooklib + Calibre) |
| `hardware_utils.py` | CPU/GPU/RAM 检测,工作进程数公式 |
| `embed_docs.py` | 向 Ollama 发送文本;存储 768 维向量 |
| `purge_pii.py` | 扫描索引以查找 PII;移除匹配项并列入黑名单 |
| `purge_dotfiles.py` | 一次性迁移工具:从数据库中移除已索引的点文件(默认试运行) |
| `dup_detect.py` | 精确(SHA256)和近似重复(余弦相似度)检测 |

### 黑名单文件

| 文件 | 用途 | 永久? |
|------|---------|-----------|
| `scan_blacklist.txt` | 提取失败的文件 | 否 —— 移除该行以重试 |
| `pii_blacklist.txt` | 因含 PII 而被移除的文件 | 是 —— 绝不重新摄取 |
| `ocr_list_pdfs.txt` | 需要 OCR 的纯图像 PDF | 不适用 —— 仅供参考 |
| `visio_legacy_missing.txt` | 在缺少 `vsd2xml` 时看到的旧版 `.vsd`/`.vss`/`.vst` | 不适用 —— 仅供参考;安装 libvisio-tools + 重新扫描 |
| `rtf_missing_striprtf.txt` | 在缺少 `striprtf` 时看到的 `.rtf` | 不适用 —— 仅供参考;`pip install striprtf` + 重新扫描 |
| `ignore_dirs.txt` | 从扫描中排除的目录(通过 `ignore` 命令管理) | 否 —— `ignore remove` + `rescan` |

---

<a name="api-endpoints"></a>

## API 端点

[↑ 顶部](#top)

基础 URL:`http://localhost:8643`

| 方法 | 路径 | 描述 |
|--------|------|-------------|
| `GET` | `/` | 提供 `index.html`(注入每进程的 CSRF 令牌) |
| `GET` | `/settings` | 提供 `settings.html` |
| `GET` | `/api/stats` | 文档总数、已嵌入数、唯一标签数 |
| `GET` | `/api/tags` | 带计数的标签列表(≥3 次出现) |
| `GET` | `/api/search` | 带分页的搜索 |
| `GET` | `/api/letters` | 字母栏的首字母索引 |
| `GET` | `/api/synopsis` | 为文档生成/返回 AI 摘要 |
| `GET` | `/api/deep-links` | 单份已索引文档内的匹配段落(`path`、`q`、`mode=keyword\|semantic`) |
| `GET` | `/api/config` | 当前服务器配置 |
| `GET` | `/api/ignore-dirs` | 列出排除的目录 |
| `GET` | `/api/scan-dirs` | 列出额外的扫描目录 |
| 🔒 `GET` | `/api/browse` | 设置用的目录浏览器(令牌门控) |
| 🔒 `POST` | `/api/open` | 用 xdg-open/gio 打开文件(对照数据库验证) |
| 🔒 `POST` | `/api/delete` | 从磁盘删除文件并从索引中移除(路径必须已索引) |
| 🔒 `POST` | `/api/config` | 保存服务器配置 |
| 🔒 `POST` | `/api/ignore-dirs` | 添加/移除排除的目录 |
| 🔒 `POST` | `/api/scan-dirs` | 添加/移除额外的扫描目录 |

🔒 = 更改状态或暴露文件系统;需要每进程的 `X-CSRF-Token` 头和一个回环
`Origin`/`Referer`。该令牌被注入到所提供的 HTML 中,因此只有第一方 UI 能调用这些。
参见[安全](#security)。除非 `Host` 头为 `localhost`/`127.0.0.1`/`[::1]`,否则所有请求
也会被拒绝(DNS 重绑定保护)。

### /api/open —— 缺失和未挂载的文件

若已索引的路径在磁盘上不再存在,`/api/open` 返回下列之一:

```json
{"ok": false, "error": "missing", "message": "..."}
{"ok": false, "error": "unmounted", "message": "..."}
```

`missing` 表示该文件的文件系统已挂载而文件确实已消失 —— UI 显示一个可关闭的模态框,
并在关闭时从索引(及磁盘相邻的数据库行)中删除该文档。`unmounted` 表示当前无法验证该
路径的文件系统(很可能是未挂载的驱动器)—— UI 显示一个提示条,且不更改数据库。等效的
批量清理参见 `scan-missing`。

### 搜索参数

```
GET /api/search?q=QUERY&offset=0&mode=both
```

| 参数 | 值 | 默认 |
|-------|--------|---------|
| `q` | 搜索字符串 | `""`(返回所有文档) |
| `mode` | `both` \| `keyword` \| `semantic` | `both` |
| `offset` | 整数 | `0` |

### 搜索响应

```json
{
  "documents": [
    {
      "id": 1,
      "name": "doc.pdf",
      "title": "Document Title",
      "author": "Jane Smith",
      "subject": "Cloud Security",
      "description": "First 500 chars of content...",
      "path": "~/Documents/doc.pdf",
      "tags": ["pdf", "security", "cloud"],
      "modified_at": "2026-06-07T14:30:00",
      "score": 0.95,
      "fts_score": 0.8,
      "sem_score": 0.98
    }
  ],
  "query": "cloud security",
  "count": 50,
  "total": 312,
  "offset": 0,
  "has_more": true,
  "mode": "both"
}
```

### 快速 API 测试

```bash
# 读取端点是普通的 GET:
curl "http://localhost:8643/api/stats"
curl "http://localhost:8643/api/search?q=kubernetes&mode=both"
curl "http://localhost:8643/api/search?q=&offset=50"
```

变更端点(`/api/delete`、`/api/open`,以及 `POST` 配置/目录路由)和 `/api/browse`
需要每进程的 CSRF 令牌和一个回环来源,因此它们不易用裸 `curl` 演练 —— 请从 UI 驱动它们,
或传入 `-X POST -H "X-CSRF-Token: <token>" -H "Origin: http://localhost:8643"`,
其中 `<token>` 从 `/` 中的 `<meta name="csrf-token">` 标签读取。

---

<a name="search-algorithm"></a>

## 搜索算法

[↑ 顶部](#top)

非空查询会以两种方式打分并合并;随后仅为所请求的页面获取元数据(不再为每个请求
加载整个语料库)。

```
final_score = 0.3 × keyword_score + 0.7 × semantic_score   (mode=both)
```

### 关键词打分(FTS5 BM25)

- 由 SQLite **FTS5** 索引通过 `MATCH` + `bm25()` 支撑 —— 不是 Python 子串扫描。
- 查询 token 被加引号并做前缀匹配(`"tok"*`)、以“或”组合,因此任意输入(操作符、
  引号、`C++`、`&`)都无法破坏查询。
- 逐列 BM25 权重呼应旧的字段优先级
  (name 6、title 8、author 7、subject 5、description 3、content_snippet 3、
  tags 4);结果归一化到 0–1。
- 孤立的 `doc_fts` rowid(无内容的 FTS 没有外键级联)会对照存活文档集被剪除,
  因此它们无法虚增总数。

### 语义打分

- 查询嵌入与每份文档嵌入之间的余弦相似度。
- 针对一个**进程内、L2 归一化的嵌入矩阵**计算(一次向量化的 NumPy 矩阵-向量乘积),
  在嵌入表变化时缓存并失效 —— 而非为每个请求重新加载每个 BLOB。
- 范围 0.0–1.0;最小阈值(仅语义模式):**0.30**。
- 嵌入:768 维 float32 向量(nomic-embed-text:latest)。

---

<a name="security"></a>

## 安全

[↑ 顶部](#top)

DocuBrowse 绑定到 localhost,面向单用户本地使用,但它经过加固,使你恰好访问的
恶意网页无法触及它:

- **Host 头白名单** —— 除非 `Host` 为 `localhost`/`127.0.0.1`/`[::1]`(可带服务端口),
  否则每个请求都会被拒绝。击败针对回环绑定服务器的 DNS 重绑定。
- **变更操作上的 CSRF 令牌** —— `/api/delete` 和 `/api/open` 仅限 POST;它们加上
  POST 配置/目录路由以及暴露文件系统的 `/api/browse`,都需要每进程的
  `X-CSRF-Token`(注入到所提供的 HTML 中,因此只有第一方 UI 拥有它)和一个回环
  `Origin`/`Referer`。
- **无存储数据注入** —— 文档字段针对 HTML 转义,卡片操作使用 `data-*` 属性 + 委托
  监听器(不从文档数据构建内联 `onclick`),封堵了一个存储型 XSS 向量。
- **PII 清除**在删除前做结构性验证:SSN 对照 SSA 分配规则,信用卡按长度 + 发卡机构
  前缀 + Luhn,银行路由号按 ABA 校验和 + 美联储前缀 —— 因此它既能捕获更多真实 PII,
  又能避免因偶然的数字组而删除文档。

服务器默认仅限 localhost —— 它只绑定 `127.0.0.1`(因此端口不暴露在任何外部接口上),
并且在可选的 `DOCUBROWSE_TRUSTED_CIDRS` 模式下,在套接字层拒绝回环 + 受信任列表之外的
所有连接。无需身份验证,因为只有本地用户能触及服务器,且访问控制不依赖主机防火墙。

可选:设置 `DOCUBROWSE_TRUSTED_CIDRS`(通常还有 `DOCUBROWSE_ALLOWED_HOSTS`)以允许
私有网络的反向代理或 BFF(例如 Docker Compose)触及 API。这**不是**公开暴露,也**不是**
身份验证 —— 请保持 CIDR 列表私有,并在 DocuBrowse 前面放置登录。

受信任的对等方是完全受信任的:`DOCUBROWSE_TRUSTED_CIDRS` 中的非回环对等方跳过 CSRF
检查,以便服务端代理可以调用变更端点而无需抓取 HTML 令牌(回环浏览器仍需要它)。由于
这授予对整个 API 的未认证访问,解析器拒绝任何宽于 `/24`(IPv4)或 `/120`(IPv6)的范围
—— 信任单台主机(`/32`)或小型子网,绝不信任 `/8` 或 `/16` 的企业网络,因为其中一台被
攻陷的主机就能触及 DocuBrowse。

---

<a name="file-structure"></a>

## 文件结构

[↑ 顶部](#top)

```
DocuBrowse/
├── docubrowser.py          # CLI 入口点(所有命令)
├── ensure_ollama.py        # Ollama 前置条件检查器/安装器
├── doc_search.py           # HTTP 搜索服务器(端口 8643)
├── docubrowse_db.py        # SQLite 架构和迁移
├── scan_docs.py            # 扫描器:发现、提取、数据库写入
├── pdf_extractor.py        # PDF 提取(pdfplumber + pypdf 回退)
├── docx_extractor.py       # Word 文档提取(python-docx)
├── odf_extractor.py        # OpenDocument(.odt/.ods/.odp)提取(标准库)
├── visio_extractor.py      # Visio(.vsdx/.vsdm/.vsd)+ draw.io(.drawio/.dio)
├── markup_extractor.py     # SGML/XML 家族 + reST/AsciiDoc/LaTeX(标准库)
├── eml_extractor.py        # 电子邮件(.eml)—— 标准库 `email`
├── csv_extractor.py        # CSV / TSV —— 标准库 `csv`
├── rtf_extractor.py        # RTF,通过 striprtf(优雅降级)
├── ebook_extractor.py      # EPUB/MOBI/AZW3/AZW 提取(ebooklib + Calibre)
├── hardware_utils.py       # CPU/GPU/RAM 检测,工作进程公式
├── embed_docs.py           # 嵌入生成流水线
├── purge_pii.py            # PII 扫描与清除工具
├── purge_dotfiles.py       # 一次性:从数据库移除已索引的点文件
├── dup_detect.py           # 精确(SHA256)和近似重复检测
├── platform_paths.py       # 跨平台路径和进程管理
├── index.html              # 前端 UI(单文件,深色/浅色主题)
├── du-docs.db              # SQLite 数据库(gitignored)
├── du-docs.db.example      # 新安装用的空架构
├── scan_blacklist.txt      # 提取失败跳过列表(gitignored)
├── pii_blacklist.txt       # 已移除 PII 的文件 —— 永久(gitignored)
├── ocr_list_pdfs.txt       # 需要 OCR 的纯图像 PDF(gitignored)
├── visio_legacy_missing.txt # 无 vsd2xml 时看到的旧版 .vsd 文件(gitignored)
├── rtf_missing_striprtf.txt # 无 striprtf 时看到的 .rtf 文件(gitignored)
├── ignore_dirs.txt         # 从扫描中排除的目录(gitignored)
├── scan_dirs.txt           # 额外的扫描目录(gitignored)
├── docubrowse.config       # 本地配置(可选,gitignored)
├── INSTALL.md              # 分步安装指南
├── README.md               # 本文件
├── LICENSE                 # GPL-3.0
├── packaging/              # RPM spec、DEB control、构建脚本、安装器
│   ├── build_packages.sh   # 构建 RPM、DEB 和 tarball(Linux)
│   ├── build_windows_zip.sh # 构建 Windows zip
│   ├── docubrowser-foss.spec  # RPM spec
│   ├── docubrowser.desktop # 桌面菜单项(Linux)
│   ├── install.sh          # tarball 安装器(Linux)
│   ├── uninstall.sh        # tarball 卸载器(Linux)
│   ├── windows/            # Windows 安装/卸载脚本
│   │   ├── Install.bat     # 双击安装
│   │   ├── Uninstall.bat   # 双击卸载
│   │   ├── install.ps1     # PowerShell 安装器
│   │   └── uninstall.ps1   # PowerShell 卸载器
│   └── macos/              # macOS 安装/卸载脚本
│       ├── build_macos_dmg.sh   # 构建 macOS dmg
│       ├── Install.command      # 双击安装
│       └── Uninstall.command    # 双击卸载
├── systemd/
│   └── docubrowser.service # systemd 单元文件
├── status_docs/            # 项目规划与决策日志
│   ├── project_status.md   # 当前版本、会话历史
│   └── DECISIONS.md        # 推迟的决策和已知问题
└── test_pdfs_live/         # 100 份用于测试的样本 PDF
```

---

<a name="troubleshooting"></a>

## 故障排除

[↑ 顶部](#top)

### Inotify 监视上限

大型文档集合可能触发:
```
OSError: [Errno 28] inotify watch limit reached
```
这是 Linux 内核限制,而非磁盘空间问题。忽略这些警告是安全的 —— 但如果你不想看到它们,
可在扫描期间抬高该限制:

1. 编辑 `/etc/sysctl.conf` 并找到该行:
   ```
   fs.inotify.max_user_instances=128
   ```
2. 将其抬高到 `256` 或 `512`:
   ```
   fs.inotify.max_user_instances=256
   ```
3. 无需重启即可应用更改:
   ```bash
   sudo sysctl -p
   ```

摄取完成后,你可以把值设回 `128`(再次编辑文件并重新运行 `sudo sysctl -p`)——
或者干脆保持抬高。

### 扫描期间 PDF 挂起

某些 PDF 会导致 pdfminer 挂起。这些会被自动检测并列入黑名单。如果某个特定文件
造成问题,检查:

```bash
# 它有多少个 PDF 对象?(>8000 属异常)
pdfinfo /path/to/file.pdf | grep -i objects

# 在文件被列入黑名单后重试它
./docubrowser.py scan-file --file /path/to/file.pdf
```

对象超过 8,000 个的 PDF(通常由反复的 ExifTool 元数据更新引起)会自动改用 pypdf
而非 pdfminer 处理。

### 纯图像(扫描)PDF

没有可提取文本的 PDF 会被检测到并添加到 `ocr_list_pdfs.txt`。它们以占位符
(`[scanned PDF — OCR required]`)索引,因此会出现在浏览中,但在运行 OCR 之前不会
匹配关键词或语义搜索。

### 扫描进度看似卡住

检查日志:
```bash
tail -f /var/log/docubrowser.log
# 或
tail -f ~/.local/share/docubrowser/docubrowser.log
```

### Ollama 未启动

```bash
ollama serve                       # 手动启动
ollama list                        # 验证两个模型都存在
ollama pull nomic-embed-text:latest              # 嵌入,若缺失
ollama pull dolphin3:latest                      # 摘要生成,若缺失
```

---

<a name="known-limitations"></a>

## 已知限制

[↑ 顶部](#top)

| 限制 | 状态 |
|------------|--------|
| DRM 加密的 AZW 不完全可搜索 | 元数据已索引;正文需要 DeDRM_tools |
| 扫描 PDF 不可搜索 | 列在 ocr_list_pdfs.txt 中;OCR 推迟 |
| 纯图像 DjVu 不可搜索 | 无文本层的 DjVu 仅按元数据索引;OCR 推迟(与扫描 PDF 相同) |
| 多个顶层文档目录 | 完全支持 —— 在常规面板中配置任意数量的额外扫描目录(`scan_dirs.txt`);`scan`/`rescan` 会自动把它们全部扫描进单一共享数据库 |
| 已移动/重命名的文件 | 不作为移动被检测 —— 旧路径被移除(交互式或通过 `scan-missing`),新路径在下次重新扫描时作为新条目被识别;真正的重复由 `duplist`/`dupclean` 捕获 |
| 隐藏文件/点文件不索引 | 有意设计 —— 任何带点前缀路径分量的文件(`.env`、`.bashrc`,以及像 `.git/`/`.venv/` 这样的隐藏目录内容)都在扫描时被跳过。由**旧**版本索引的点文件**不会**被重新扫描自动移除(文件仍在磁盘上);运行独立的 `purge_dotfiles.py` 工具(或重建索引)来清除它们 |
| 无身份验证 | 仅限本地使用;针对跨源/CSRF/DNS 重绑定加固(参见[安全](#security)),但不适合网络暴露 |
| 语义*排名*是文档级的 | 整篇文档的嵌入对*哪些*文档匹配进行排名;随后**深度链接**按需精确定位任意结果*内部*的位置。全语料库块级排名仍是未来工作 |
| 无混合语言语料库 | 一个安装服务一种语言(英语、日语、韩语、简体中文或繁体中文,在安装时或通过设置选择);不支持逐文档语言检测或混合语言语料库。参见[语言](#languages) |
| PII 检测仅限美国模式 | `purge_pii.py` 检测美国格式(SSN、电话等);日语“My Number”和其他非美国 PII 模式尚未实现 |
| ETA 显示偏高 | 使用简单平均;滑动窗口推迟 |

---

<a name="recent-changes"></a>

## 近期变更

[↑ 顶部](#top)

## v1.5.2 (2026-09-13) —— 中文支持(简体 + 繁体)

DocuBrowse 现在可完全以**中文**运行 —— **简体**(`zh`)和**繁体**(`zh-hant`)
两者。参见[语言](#languages)。

- **简体(`zh`)和繁体(`zh-hant`)。** 两者都使用 `bge-m3` 多语言嵌入器和
  `ornith-1.5:9b` 摘要模型;二者共享同一个模型,仅提示词不同(繁体强制输出
  繁體/正體字,已经实测验证)。完整的 UI 翻译(`locales/zh.json`、
  `locales/zh-hant.json`)以及 README 翻译(`README-zh.md`、`README-zh-hant.md`)。
- **CJK 关键词搜索覆盖中文。** 现有的字符二元组分割已经涵盖 CJK 统一表意文字范围,
  因此简体和繁体都无需修改 `cjk.py` 即可索引与匹配;2 字符以上的词可靠匹配,单个字符
  通过两者/语义搜索浮现。
- **中文无索引栏。** 中文不是字母文字、没有首字母排序,因此文档列表索引栏被隐藏
  (与日语相同)。
- **打包。** 所有 README 翻译(en/ja/ko/zh/zh-hant)现在都随每种包类型
  (RPM、DEB、tarball、Windows、macOS)一起发布。

## v1.5.1 (2026-09-11) —— 韩语/日语搜索 bug 修复

修复 v1.5.0 之后发现的 CJK 搜索与语言配置问题的 bug 修复版。

- **修复切换语言后语义搜索的 HTTP 500。** 语义打分现在只比较由当前嵌入器构建的
  向量,因此在不同语言下构建的索引会降级为关键词搜索,而不是崩溃。
- **深度链接现在能找到 CJK 段落。** 关键词深度链接将查询切分为搜索索引所用的相同
  字符二元组,因此任何被搜索浮现的文档都会产出匹配段落(此前即便 100% 匹配也显示
  “无匹配段落”)。
- **每一步都遵循所配置的语言。** `docubrowser scan`、嵌入和数据库初始化现在都解析
  与服务器相同的语言,因此所配置的 `ko`/`ja` 不再默默地按英语索引。语言设置后不再
  需要 `docubrowser ko scan`。

## v1.5.0 (2026-09-11) —— 韩语支持 + 完整 UI 本地化

DocuBrowse 现在可完全以**韩语**运行,且界面本地化已完成(搜索页和设置页)。参见
[语言](#languages)。

- **韩语(`ko`)。** 完整语言栈:`bge-m3` 嵌入、`exaone3.5` 摘要、韩文字符二元组
  关键词搜索,以及完整的韩语 UI 翻译(`locales/ko.json`)。
- **韩语字母索引栏。** 由于韩文是真正的字母文字,文档列表索引栏对韩语启用,并按 14 个
  基本首辅音(初声)ㄱ–ㅎ 浏览;紧音折叠回其基础辅音(ㄲ→ㄱ)。英语保留 A–Z/0–9 栏;
  该栏对日语保持隐藏。
- **设置页完全国际化。** 设置页上的每个标签、描述、按钮、占位符、状态行、确认对话框、
  提示条和警告现在都已本地化(英语/日语/韩语)。
- **从 CLI 以所选语言启动。** `docubrowser ko start`(或 `docubrowser start ja`)以
  该语言启动服务器,并将选择持久化到 `docubrowse.config`;代码可出现在任一位置。
- **本地化消息。** 摘要模态框错误、文档/标签计数器、标签类别(code/diagram/markup)、
  滚动到顶部按钮,以及网络/错误消息现在都已翻译。
- **修复。** 全新实例的“添加目录出错”(空的 `work_dir` 行不再覆盖默认值);CLI 现在读取
  设置 UI 写入的相同配置,因此 `scan` 面向所配置的目录;HTML 以 `no-cache` 提供,因此
  UI/本地化更改总是重新加载最新内容。

## v1.4.0 (2026-09-09) —— 多语言支持(日语优先)

DocuBrowse 现在可完全以第二种语言运行。参见[语言](#languages)。

- **每次安装一种语言。** 一个安装服务一种语言 —— 界面字符串、嵌入模型、摘要模型和
  FTS 分词器全都一起选择。目前支持英语(`en`,默认)和**日语**(`ja`);新增一种语言
  是数据变更(`lang_models.py` 一行 + `locales/<code>.json`),而非新代码。
- **本地化 UI。** 所有界面字符串都从每语言的 locale 文件(`locales/en.json`、
  `locales/ja.json`)提供并在客户端解析;当前 locale 随 `GET /api/config` 一起发送。
- **语言合适的 AI。** 日语使用 `bge-m3` 多语言嵌入器和一个日语摘要模型;模型在首次运行
  (以及切换语言时)从 Ollama 按需拉取,不捆绑任何东西。
- **CJK 关键词搜索**在 `unicode61` 分词器之上使用应用侧字符二元组分割(而非 `trigram`),
  因此 2 字符以上的日语词(例如 2 字符汉字复合词)能可靠匹配;单字符查询通过两者/语义
  浮现。零依赖,并在中文/韩语落地时一致适用。
- **选择语言。** 全新安装时询问一次(升级绝不重新询问 —— 已有的 `lang` 被保留),或之后
  从设置齿轮切换(`POST /api/language`),它会警告需要重新扫描以为新语言重建嵌入/索引。
- **推理模型摘要修复。** 混合推理型摘要模型(例如日语的 nemotron)不再返回空白摘要;
  大型冷模型的摘要超时也已抬高。

## v1.3.0 (2026-08-25) —— 深度链接覆盖 + 语义调优

- **深度链接覆盖更多格式** —— HTML、Markdown、EPUB/MOBI/AZW3、DjVu、SGML/XML 家族、
  电子邮件、JSON/YAML、源代码和其他文本/标记格式现在都支持文档内段落搜索;非散文
  (电子表格、演示文稿、图表)回退到用其阅读器打开。
- **语义搜索调优** —— 冠词和连词在嵌入前从查询中剥除,以免填充词稀释匹配;深度链接
  获得了语义相关度下限并丢弃无内容段落(注释标记、裸数字),其语义嵌入也有界限,因此
  大型文档不再超时。
- **按回车搜索** —— 搜索在你按回车时执行,而非随打随搜;清空搜索框会再次显示所有文档。
- **跳过点文件(D-6)** —— 带点前缀路径分量的文件(`.env`、`.git/`、`.venv/`)不再被索引。
  新的一次性 `purge_dotfiles.py` 工具会移除旧版本遗留在数据库中的点文件(默认试运行)。
- **文档** —— 新增搜索技巧与窍门章节;澄清了加引号与不加引号的短语搜索以及不区分大小写。

## v1.2.0 (2026-08-24) —— 深度链接

- **深度链接 —— 文档内段落搜索。** 从任意关键词或语义结果,查找该文档*内部*的匹配
  段落,每个都带位置标签(页/行/节),并跳转到其一并高亮匹配文本。按需计算 ——
  无需重新索引,无需更改架构,无需新依赖。散文格式:PDF、TXT、HTML、Markdown、DOCX、
  RTF、ODT、电子书(EPUB/MOBI/AZW3)、DjVu,以及 SGML/XML 家族、电子邮件、JSON/YAML、
  源代码和其他文本/标记格式;非散文回退到用阅读器打开。新端点 `GET /api/deep-links`。
- **头部 logo 链接到 GitHub 上的项目。**
- **修复:** 当 `--db` / `--port` 放在子命令之前时(`docubrowser --db PATH start`)现在
  会被遵循 —— 此前它们被默默丢弃并使用了默认数据库。
- 包含首次在 v1.0.3.1 中发布的 **Intel Arc GPU 检测**(通过 `xpu-smi`,带 `nvidia-smi`
  回退)和 **tar 遍历还原加固**。

## v1.0.3 (2026-08-21) —— 容器与环境配置

- **可配置的 Ollama 主机** —— `OLLAMA_HOST`(或 `DOCUBROWSE_OLLAMA_HOST`)将嵌入器、
  搜索服务器和前置条件检查器指向远程或 sidecar Ollama。接受裸 `host:port`;scheme 默认为
  `http://`。默认仍为 `http://localhost:11434`。
- **通过环境的路径/端口/数据库** —— `DOCUBROWSE_DOC_DIR`、`DOCUBROWSE_DB` /
  `DOCUBROWSE_DB_PATH`、`DOCUBROWSE_PORT` 和 `DOCUBROWSE_WORK_DIR` 覆盖配置文件(环境覆盖
  文件;CLI 仍以其为准),因此容器可以在没有 `docubrowse.config` 的情况下运行。
  `GET /api/config` 也会反映这些,且 `doc_search.py` 可以仅凭 `DOCUBROWSE_DB` /
  `DOCUBROWSE_PORT` 启动。
- **可选的私有网络访问** —— `DOCUBROWSE_TRUSTED_CIDRS` 和 `DOCUBROWSE_ALLOWED_HOSTS` 让
  私有反向代理/BFF 越过仅回环的门访问 API。受信任范围上限为 `/24`(IPv4)/ `/120`
  (IPv6)—— 首选 `/32` 主机 —— 因此误设的 `/8` 无法授予整个网络未认证的 API 访问。默认仍为
  仅回环。
- **文档** —— README、INSTALL 和管理员指南记录了完整的环境变量集和受信任对等方安全模型;
  新增了可重复的端到端功能测试(`test_features.py`)和测试笔记。

## v1.0.2 (2026-08-19) —— DjVu 和 ODF 模板

- **DjVu 支持**(`.djvu`/`.djv`)—— 通过 **DjVuLibre**(`djvutxt`/`djvused`,可选外部工具)
  提取文本层。没有它时,DjVu 文件仅按元数据索引,路径记录到 `djvu_missing_djvulibre.txt`;
  安装 DjVuLibre 并重新扫描以获取正文。无文本层的纯图像 DjVu 仅按元数据索引(OCR 推迟,与
  扫描 PDF 相同)。
- **ODF 模板支持**(`.ott`/`.ots`/`.otp`)—— OpenDocument 模板变体现在通过现有的 ODF
  提取器索引,按 mimetype 前缀路由到匹配的文本/电子表格/演示文稿处理器。无新依赖。
- **打包** —— `djvu_extractor.py` 已添加到所有打包清单(RPM、DEB、tarball、Windows、macOS)。

## v1.0.0 (2026-07-23) —— 功能完备里程碑

DocuBrowse 达到 v1.0.0:功能完备、经生产测试,并为全部三个桌面平台打包。此版本标志着从
MVP(v0.1.0)历经格式扩展、安全加固和代码质量,共 7 周开发的顶点。

- **40+ 支持的文件格式**,跨 15 个提取器模块 —— PDF、DOCX、PPTX、XLSX、ODF、Visio、
  draw.io、SGML/XML 家族、电子邮件、RTF、CSV/TSV、EPUB、MOBI、AZW、HTML、Markdown、LaTeX、
  reST、AsciiDoc 和类配置纯文本。
- **Pylint 10.00/10**,覆盖全部 28 个 Python 源文件。
- **Python 3.9 至 3.14 测试通过** —— 包括针对 Python 3.14 更严格关键字参数处理的修复。
- **为 Linux 打包**(RPM、DEB、tarball)、**Windows**(zip)和 **macOS**(dmg)。
- **安全加固** —— CSRF 保护、Host 头白名单、无未认证 GET 变更、带 SSN/CC/路由号验证的
  PII 检测。
- **AI 驱动** —— 语义搜索、混合关键词+语义模式,以及按需 AI 摘要生成,全部通过 Ollama
  本地运行。

---

## v0.9.3 (2026-07-17)

### 格式扩展 —— 图表、标记、电子邮件、RTF、CSV、类配置文本

覆盖面大幅提升。跨五个新提取器模块新增 40+ 个新文件扩展名,尽可能全部为纯 Python / 标准库。

- **Visio 与图表** —— 新的 `visio_extractor.py` 处理现代 Visio(`.vsdx`/`.vsdm`)、旧版
  二进制 Visio(`.vsd`/`.vss`/`.vst` —— 正文需要可选的 `libvisio-tools`;否则降级为仅元
  数据),以及 draw.io / diagrams.net(`.drawio`/`.dio`)—— 纯与压缩(deflate + base64 +
  URL 编码)mxfile 变体皆可。捕获形状文本、页面名称和核心属性。PlantUML
  (`.puml`/`.plantuml`)和 Mermaid(`.mmd`)源码作为文本索引并标记 `diagram`。
- **SGML/XML 标记家族** —— 新的 `markup_extractor.py` 处理 `.xml`/`.xhtml`/`.sgml`/`.sgm`、
  DocBook(`.docbook`/`.dbk`)、SVG(同时标记 `diagram`)、Visio 2003 XML(`.vdx`,标记
  `diagram`)、订阅源(`.rss`/`.atom`/`.opml`)、reStructuredText(`.rst`)、AsciiDoc
  (`.adoc`/`.asciidoc`)和 LaTeX(`.tex`/`.latex`)。与架构无关的去标签,并从常见的
  local-name(`<title>`、`<dc:title>`、`<author>`、`<dc:creator>`)嗅探标题/作者。仅标准库。
- **电子邮件、RTF、表格** —— 新的 `eml_extractor.py`、`csv_extractor.py` 和
  `rtf_extractor.py`。电子邮件(`.eml`)通过标准库 `email` 包(Subject → 标题,From → 作者,
  To/Cc/Date → subject 字段,纯文本或去标签的 HTML 正文)。CSV/TSV 通过标准库 `csv`,带分隔符
  自动嗅探和 BOM 安全读取;表头行 → description。RTF 通过可选的 `striprtf`(已添加到
  `requirements.txt`);缺失时降级为仅元数据,并带一个 `rtf_missing_striprtf.txt` 附属文件 ——
  与 `visio_legacy_missing.txt` 模式一致。
- **类配置纯文本** —— `.ini`、`.conf`、`.cfg`、`.log`、`.lst` 走现有文本路径。
- **标记** —— 每个图表文件获得 `diagram` 标签;每个标记文件获得 `markup` 标签。自动关键词标签
  生成已扩展以覆盖所有新格式。
- **CLI** —— 30+ 个新 `_TYPE_MAP` 条目,因此 `scan vsdx drawio eml rtf` 等都能自然工作。
- **新的附属文件**(gitignored,信息性):`visio_legacy_missing.txt`、`rtf_missing_striprtf.txt`。

### 代码质量 —— pylint 10/10 + Python 3.14 兼容

- **全部 28 个 Python 源文件得分 pylint 10.00/10** —— 两轮清理,处理未使用的导入、缺失的
  docstring、过宽的异常捕获、行长度和命名约定。无行为变更。
- **Python 3.14 兼容修复** —— Python 3.14 强制要求以 `_` 前缀的参数不能以不同的关键字名传递。
  `scan_docs.py` 和 `embed_docs.py` 调用了 `wait_for_memory(is_tty=...)`,但该函数定义为
  `_is_tty`。已修复 —— 扫描在 Python 3.14+ 上不再崩溃。

## v0.9.2 (2026-07-13)

### Bug 修复

- **损坏的符号链接和权限错误不再使扫描崩溃** —— 目录遍历期间的 `is_file()` 和 `stat()` 调用
  现在捕获 `OSError` 而非将其传播。受影响的代码路径:扫描前文件计数、`report` 命令、
  `scan_docs.py` 中的主文件收集,以及两个数据整理去重脚本。不可访问的条目(损坏的符号链接、
  复制到 ext4 的 NTFS junction/reparse point、sshfs/网络挂载上的权限拒绝路径)会被跳过并在
  摘要输出中计数。

---

## v0.9.2 (2026-07-09)

### OpenDocument 格式支持

- **ODF 扫描** —— `.odt`(文本)、`.ods`(电子表格)和 `.odp`(演示文稿)文件现在被索引。
  提取仅使用 Python 标准库(`zipfile` + `xml.etree.ElementTree`)—— 无需额外依赖。元数据
  (标题、作者、主题、描述、关键词)从 `meta.xml` 读取;正文文本从 `content.xml` 提取,并对
  段落、标题、列表、表格和幻灯片框进行完整的命名空间处理。
- **版本升级** —— 所有打包文件更新到 0.9.2。

### Bug 修复

- **相关度分数上限为 100%** —— 混合搜索合并公式 `max(fts, sem) + 0.1 × min(fts, sem)` 在关键词
  和语义分数都很高时可能超过 1.0,产生高于 100% 的相关度百分比。现在钳制到 1.0。

---

## v0.9.0 (2026-07-05)

### 原生打包与 Windows 支持

DocuBrowse 现在为 Linux 和 Windows 提供原生安装器打包。

- **RPM、DEB、tarball 和 Windows zip 包** —— `build_packages.sh` 生成 Linux 包;
  `build_windows_zip.sh` 生成 Windows zip。Linux 安装到 `/opt/docubrowser/`,带 Python 虚拟
  环境、位于 `/usr/bin/docubrowser` 和 `/usr/bin/docuback` 的 CLI 包装脚本,以及 Office 下的
  桌面菜单项。Windows 安装到 `%USERPROFILE%\DocuBrowse`,带开始菜单快捷方式(无需管理员)。
- **Windows 安装器** —— `Install.bat` / `install.ps1` 检测 Python、创建虚拟环境、安装依赖并
  创建开始菜单快捷方式。`Uninstall.bat` 逆转一切。
- **跨平台路径抽象** —— 新的 `platform_paths.py` 集中了所有运行时路径选择(PID 文件、日志
  文件、备份目录)和进程管理(kill、find-by-script、kill-port)。Linux 路径不变;Windows
  路径使用 `%USERPROFILE%\DocuBrowse\`。
- **Windows 兼容** —— 将所有仅 Unix 的构造(`resource`、`SIGALRM`、`os.killpg`、`/proc` 访问)
  置于平台检查之后。进程管理使用 `psutil`,在 Linux 上带 `/proc` 回退。
- **备份/还原** —— `backup_restore.py` 支持 Windows 权限检查(`IsUserAnAdmin`),并优雅处理缺失
  的 `pwd` 模块。
- **桌面菜单项** —— `.desktop` 文件使用 `xdg-terminal-exec` 以在所有桌面环境中可靠地启动终端;
  归类于 Office 下。
- **Systemd 服务文件** —— 为 Linux 上的系统级部署提供。
- **dist/ 修剪** —— 构建脚本每种格式仅保留最新 2 个版本。
- **macOS dmg 安装器** —— `packaging/macos/build_macos_dmg.sh` 生成一个带可双击的
  `Install.command` / `Uninstall.command` 脚本的 dmg。安装到 `~/Applications/DocuBrowse/`
  (应用本身无需 sudo),带 Python 虚拟环境、CLI 包装脚本,以及一个图标由 `icons/icon-512.png`
  通过 sips/iconutil 生成的 `DocuBrowse.app` 启动器。

### v0.8.4 (2026-07-02)

### 代码库清理与简化

移除从未属于 FOSS 版本的未使用代码路径和实验性功能,留下一个更整洁、更聚焦的代码库。

- **更精简的服务器** —— `doc_search.py` 减少约 300 行;移除了开发期间积累的未使用的网络配置、
  协议协商和处理器代码。
- **更精简的 CLI** —— `docubrowser.py` 减少约 240 行;移除了不适用于 localhost 应用的
  `setup-tls` 命令及相关辅助函数。
- **移除陈旧文件** —— 删除了 `branding.json.example` 和其他从未在生产中使用的仅开发文件。
- **文档更新** —— README、INSTALL 和架构笔记经过清理,以准确反映当前功能集。

---

## v0.8.3.1 (2026-06-28)

### 通过基于标签的可见性控件显示、隐藏和取消隐藏文档

- **从视图中隐藏文档** —— 每张卡片现在都有一个 🙈 隐藏图标,它将文档标记为“hidden”并将其从
  列表中淡出。隐藏的文档仍留在数据库中,可随时恢复。
- **“Show 🙈”切换按钮** —— 添加在所有视图(全部文档、字母筛选、搜索结果)的页数旁。点击它会
  在正常卡片旁揭示所有隐藏卡片;按钮标签切换为“Hide 🙈”以将其切回关闭。
- **取消隐藏(👀)图标** —— 当隐藏卡片可见时,它们显示 👀 图标而非 🙈。点击它会在服务端移除
  “hidden”标签、将图标换回 🙈,并从卡片上移除“hidden”标签芯片。
- **新 API 端点:`POST /api/remove-tag`** —— 从文档移除单个标签。参数:`path`(URL 编码的
  文件路径)、`tag`(标签名)。返回更新后的标签列表。受 CSRF 保护。
- **卡片操作图标重新设计** —— 所有图标(📋 🔖 🙈 ❌)现在都使用实心、彩色的 emoji,以完全不透明
  显示。深色模式下不再有淡化/暗淡的图标。
[↑ 顶部](#top)

## v0.8.3 (2026-06-27)

### UI 大改、搜索修复、扫描改进

- **深色与浅色模式配色重新设计** —— 新的 CSS 变量主题,带 `data-theme` 属性切换。深色模式使用
  深海军蓝/紫色调,配青色、橙色和紫罗兰色点缀。浅色模式使用干净的白色,配为可读性加深的点缀
  变体。标签颜色通过 `nth-child` 选择器循环五种不同色相。分数徽章、模式按钮和操作按钮都使用新
  配色。
- **垃圾桶图标现在打开一个 4 选项模态框**,而非立即删除:
  (1) 仅从索引移除(文件留在磁盘上,下次运行重新扫描),
  (2) 移除并列入黑名单(文件保留,未来扫描跳过它),
  (3) 移除并从磁盘删除文件(带双重确认),
  (4) 取消。
  服务器 API 已更新:`POST /api/delete?path=...&mode=db_only|blacklist|delete_file`
  (为向后兼容默认为 `db_only`)。
- **“both”模式下的搜索打分修复** —— 关键词匹配此前被埋在数千个低相似度语义结果之下。现在应用一个
  语义下限(`SEM_FLOOR=0.30`)并使用 `max(fts, sem)` 打分,而非把纯关键词命中封顶在 0.3 的加权平均。
- **`scan` 命令现在默认嵌入**(与 `rescan` 相同)—— 新安装开箱即获得可用的语义搜索。新增
  `--no-embed` 和 `--embed-workers` 标志用于退出。
- **安全加固** —— 为 `/api/synopsis` 添加 CSRF 保护;抑制了异常向客户端泄漏。

---

## v0.8.2 (2026-06-27)

### UI:打开按钮、CLI 改进

- **打开操作按钮**替换了每张结果卡片上旧的可点击文件路径链接 —— 通过 `xdg-open` 在默认应用中启动
  文件。
- **按钮样式**更新 —— 按钮使用点缀色边框和文本,配填充式悬停状态,取代此前暗淡/灰化的外观。

---

## v0.8.1 (2026-06-14)

### Bug 修复:陈旧的示例数据库架构

- **`du-docs.db.example` 重新生成**,采用当前架构 —— 全新安装在首个页面加载时不再遇到 HTTP 500
  (“no such column: d.subject”)。旧示例是针对更旧的架构(在 author/subject/synopsis 列之前以及
  在完整 FTS5 索引之前)构建的,导致惰性迁移与首个搜索请求竞争。新示例从一开始就有正确的架构。

---

## v0.8.0 (2026-06-13)

### 设置页、字母索引栏、多根扫描
- **设置移到一个独立页面**(`/settings`,通过齿轮图标在新标签页中打开)—— 取代旧模态框。全宽布局、
  一个保存配置并返回搜索标签页的头部“Done”按钮,以及重新设计的忽略目录面板(描述文本、“添加要
  排除的目录”行、带内联 ✕ 移除按钮的“当前排除的目录”列表、添加时的清除前确认和移除时的重新扫描
  提醒)。
- **字母索引栏(0-9、A-Z)现在是真正的全局过滤器** —— 点击一个字母查询 `/api/search?letter=X` 以获取
  *所有*匹配文档(不仅是已加载页),按现有的页面大小偏好分页;Next/Back 和页面大小更改在筛选时都
  工作,再次点击活动字母会返回全部文档。一个“Home”按钮(在“0-9”左侧)可从任何地方返回全部文档,且
  索引栏现在在每个视图(全部文档、字母筛选、搜索、分页)间持续存在。
- **确认多个文档目录完全自动**:`resolve_doc_dirs()` 将所配置的 docPath 与 `scan_dirs.txt` 统一为一个
  有序列表;`scan`/`rescan` 遍历每个目录进入单一共享数据库,并在最后运行一次嵌入 —— 无需手动逐目录
  重新扫描。
- 从头部统计栏移除了“N embedded”计数(现为“N docs · N tags”)。
- `index.html` 中的 `friendlyError()` 辅助函数在服务器于页面已加载时宕机的情况下,给出清晰的“Cannot
  reach the DocuBrowse service”消息(而非通用网络错误)—— 应用于搜索、筛选、分页、摘要、打开和删除。
- 摘要模态框的“Generating synopsis...”消息现在在 6s/25s 更新,配以安抚性文本,使缓慢的冷启动 Ollama
  请求(最多约 90s)看起来不像卡住。

### 无默认 doc_dir、配置横幅、uninstall.sh
- `doc_dir`/`docPath` 不再默认为 `~/Documents` —— 未配置的文档目录现在是 CLI(`docubrowser.py`)、
  API(`doc_search.py` `/api/config`)和 `install.sh` 生成的配置中的有效状态。
- 需要文档目录的 CLI 命令(`rescan`、`report`、`scan`)现在以清晰的错误退出,指向设置齿轮、
  `docubrowse.config` 或 `--doc-dir`(若未配置)。
- 每当 `/api/config` 报告空的 `docPath` 时,`index.html` 显示一个横幅 ——“No document directory
  configured yet. Click the Settings (gear) icon...”。
- 添加了 `uninstall.sh`,镜像 `install.sh` 的用户/系统模式检测:停止/禁用/移除 systemd 单元、移除 CLI
  包装脚本和安装目录、清理 pid/log 文件,并(系统模式,单独确认)可移除专用的 `docubrowse` 用户/组。

### 安装器
- **安装器:** 重写的 `install.sh`/`uninstall.sh`,带清晰的用户与系统拆分 —— 用户模式安装到
  `~/.docubrowse`(自有 venv、位于 `~/.local/bin/docubrowser` 的包装脚本、无 root、无 systemd);系统
  模式安装到 `/opt/docubrowse`,作为专用 `docubrowse` 用户,带一个(不自动启用的)`docubrowser.service`
  systemd 单元和 `/usr/local/bin/docubrowser` 包装脚本。
- **预检查:** 安装器预先验证所有前置条件(python3 ≥ 3.9 + venv/ensurepip、rsync、curl、tar、calibre、
  ollama,以及系统模式下的 getent/useradd/groupadd/systemctl),并在做任何更改前一次性报告所有缺失项。
- **CLI:** 启动器现在安装为 `docubrowser` 命令(无 `.py`)。
- **requirements.txt** 已添加并通过 `pip install -r requirements.txt` 安装 —— 现在包含此前缺失的依赖
  (numpy、python-pptx、openpyxl),以及 pdfplumber、pypdf、python-docx、ebooklib、beautifulsoup4、mobi。
- **全新安装从空开始:** `du-docs.db.example` 现在以空发布,因此新安装从未索引任何文档开始。
- **多个文档目录:** 设置现在显示单一的“文档目录”列表(旧的分离 docPath +“额外目录”面板已合并)。
  `rescan`/`scan` 索引**每个**列出的目录;显式的 `--doc-dir` 仍只面向一个。`doc_dir` 现在是可选的。

### 安全与可靠性加固
对一次完整的代码质量 + 安全审计的整改(细节见 `status_docs/DECISIONS.md`)。要点:
- **安全:** Host 头白名单(反 DNS 重绑定);`/api/delete` 和 `/api/open` 移到 POST,并与 POST 配置/目录
  路由和 `/api/browse` 一起,由每进程的 CSRF 令牌 + 回环来源门控;封堵了存储型 XSS 向量(data 属性 +
  委托监听器);PII 清除现在用 SSA 规则 + Luhn/IIN 验证。
- **搜索:** 关键词路径现在使用 FTS5 `bm25()` 索引,语义打分使用缓存的 NumPy 嵌入矩阵,而非为每个请求
  加载整个语料库(关键词约 4ms,两者约 55ms);修复了服务端语义搜索(此前默默返回空)。
- **可靠性:** `INSERT … ON CONFLICT` upsert(重新索引不再抹掉标签/嵌入/摘要);worker 死亡的“嫌疑隔离”
  仅将真正的肇事者列入黑名单;架构初始化每进程运行一次;扫描/嵌入按约 2s 时间预算提交,因此服务器不被
  阻塞;`dupclean` 在其主路径上不再损坏磁盘/数据库;基于 `/proc` 的精确 worker 终止;单一共享的文档删除
  辅助函数;各种中/低级修复。
- **UI:** 分页 Back/Next 在所有页面大小下正确;更新的搜索现在会取代进行中的页面加载(无陈旧结果)。

### 处理已移动/缺失/已删除的文档
- `/api/open` 现在为不再存在的文件返回 `{"ok": false, "error": "missing"|"unmounted", "message": ...}`,
  而非通用错误。
- UI 为 `missing` 文件显示一个可关闭的模态框(并在关闭时从索引移除它们),或为 `unmounted` 文件显示提示
  条(文件系统无法验证,不更改索引)。
- 新的可选 `scan-missing [--dry-run]` CLI 命令在整个索引范围内批量清理 `missing` 行,而不触及 `unmounted`
  行。

### v0.7.2.1 —— Bug 修复
- 修复了“打开文件”(`/api/open`)静默无反应 —— 服务器的环境缺少 `DBUS_SESSION_BUS_ADDRESS`/`DISPLAY`/
  `XAUTHORITY`/`XDG_RUNTIME_DIR`,因此 `xdg-open` 成功退出而未启动默认应用。`handle_open` 现在重建桌面
  会话环境,并优先使用 `gio open` 以可靠启动。

---

<a name="roadmap"></a>

## 路线图

[↑ 顶部](#top)

### 阶段 2b —— 格式扩展 ✅ 完成
- ✅ DOCX 提取器(python-docx)
- ✅ EPUB/MOBI/AZW3/AZW 提取(ebooklib + Calibre)
- 无扩展名文件分类(magic bytes)
- 扩展到 10K+ 文档

### 阶段 2 —— 日常维护 ✅ 完成
- ✅ `duplist` / `dupclean` —— 精确 + 近似重复检测和交互式清理
- ✅ 通过设置 UI 的配置读/写(port、docPath、workDir)
- 进度条的滑动窗口 ETA
- 搜索 UI 中的文件类型过滤器

### 阶段 3 —— 打磨
- 配置持久化
- 高级筛选(日期范围、类型、作者)
- 结果导出(CSV/JSON)
- 扫描 PDF 的 OCR 集成

### 阶段 3+ —— 进阶
- API 密钥身份验证
- 文档相似度聚类
- Docker 部署

---

<a name="ai-assisted-development"></a>

## AI 辅助开发

[↑ 顶部](#top)

DocuBrowse 以 Claude 作为活跃的编码伙伴进行开发。要以完整上下文恢复一个会话,在开始时加载这些文件:

| 文件 | 内容 |
|------|---------|
| `.claude/CLAUDE.md` | 项目规则、关键文件、来之不易的经验 |
| `status_docs/project_status.md` | 版本、会话历史、进行中的工作 |
| `status_docs/DECISIONS.md` | 推迟的决策、已知问题、理由 |

```bash
# 打印全部三个以便复制/粘贴到任何 AI 助手
cat .claude/CLAUDE.md status_docs/project_status.md status_docs/DECISIONS.md
```

---

<a name="license"></a>

## 许可证

[↑ 顶部](#top)

GNU 通用公共许可证 v3.0 或更高版本(GPL-3.0-or-later)。

Copyright (C) 2026 James Sparenberg

参见 [LICENSE](LICENSE) 或 https://www.gnu.org/licenses/gpl-3.0.html。

---

**DocuBrowse v1.5.2** —— 快速、本地、AI 驱动的文档搜索。
