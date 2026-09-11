<!-- 번역판 — 영어판 README.md 와 동기화하여 갱신하세요 / Translation — keep in sync with README.md -->

**언어 / Language:** [English](README.md) | [日本語](README-ja.md) | **한국어**

# DocuBrowse v1.5.0

<a name="top"></a>

Linux(RPM·DEB·tarball), Windows(zip), macOS(dmg)용으로 패키징되어 있습니다.
인터페이스는 안정적이며, 가능한 한 파괴적 변경을 피합니다.

**DocuBrowse 는 어질러진 대량의 문서를 실제로 검색할 수 있는 것으로 바꿉니다.**
손에 있는 파일(PDF, 전자책, Word 문서, 메모 등 무엇이든)을 가리키면, 키워드뿐 아니라
"의미"까지 이해하는 스마트한 인덱스를 구축합니다. "그 임대 갱신에 관한 계약서"라고 물으면
그 정확한 어구가 한 번도 나오지 않더라도 찾아냅니다. 임의의 검색 결과를 클릭하면 파일을 열기도 전에
즉시 AI 요약을 볼 수 있습니다. PII 를 인식하며 여러 문서 디렉터리와 함께 동작합니다.

DocuBrowse 는 로컬 AI 모델을 사용하여 전적으로 사용자 자신의 컴퓨터에서 실행됩니다 — 인터넷
연결이 필요 없고, 계정도 없으며, API 키도 없고, 토큰 예산을 갉아먹는 쿼리당 비용도 없습니다.
**당신의 데이터. 당신의 AI.**

내부 구조: SQLite FTS5 키워드 검색과 AI 기반 의미 유사도 및 요약 생성(Ollama +
nomic-embed-text + dolphin3). 여러 문서 및 소스 코드 형식을 지원합니다.

> **Docker(실험적 — 아직 권장하지 않음):** 컨테이너화된 배포를 `docker-experiment`
> 브랜치에서 시험하고 있습니다. Docker/OS 의 제약과 DocuBrowse 의 보안 모델 때문에 완전히
> 동작하는 형태는 **아직** 실현되지 않았습니다 — 특히 브라우저 기반 컨테이너에서는 데스크톱
> 앱으로 문서를 여는 것이 동작하지 않습니다(서버는 헤드리스이고 브라우저는 샌드박스에
> 있습니다). 실험하고 싶은 분을 위해 해당 브랜치에서 이용할 수 있지만 **사용은 권장하지
> 않습니다.** 브랜치의 `docker/README.md` 를 참조하세요.

---

## 내비게이션

| | | |
|---|---|---|
| [기능](#features) | [검색 팁과 요령](#search-tips-and-tricks) | [스크린샷](#screenshots) |
| [빠른 시작](#quick-start) | [언어](#languages) | |
| [CLI 참조](#cli-reference) | [설정](#configuration) | [아키텍처](#architecture) |
| [API 엔드포인트](#api-endpoints) | [검색 알고리즘](#search-algorithm) | [보안](#security) |
| [파일 구조](#file-structure) | [문제 해결](#troubleshooting) | [알려진 제한](#known-limitations) |
| [변경 이력](#recent-changes) | | |
| [로드맵](#roadmap) | [AI 지원 개발](#ai-assisted-development) | [라이선스](#license) |

---

<a name="features"></a>

## 기능

[↑ 맨 위](#top)

### 🔍 두 가지 검색 모드
- **키워드 검색** — SQLite FTS5 를 통한 빠른 전문 검색(제목, 저자, 주제, 태그, 스니펫)
- **의미 검색** — Ollama 임베딩(nomic-embed-text:latest)을 통한 AI 기반 유사도. 의미 검색은 쿼리와 관련된 *어느 문서*가 적합한지를 식별하고, **딥 링크**(아래)가 그다음 문서 *내부의 어디*에서 매치가 일어나는지를 짚어냅니다.
- **하이브리드 모드**(기본값, "모두") — 키워드와 의미를 병합합니다. 각 문서는 두 점수 중 더 강한 쪽을 취하며(양쪽 모두 맞으면 소폭 가산), 결과에 나타나려면 키워드 매치 또는 의미 하한을 넘어야 합니다. [검색 팁과 요령](#search-tips-and-tricks)을 참조하세요.

### 🎯 딥 링크 — 문서 내 구절 검색
- 임의의 키워드 또는 의미 검색 결과에서 **딥 링크**를 클릭하면 그 문서 *내부*의 매치 구절을 찾습니다 — 온디맨드이며, 재인덱싱도 스키마 변경도 없습니다.
- 각 구절은 짧은 샘플과 위치 라벨(**페이지**, **줄**, 또는 **섹션**)을 표시하며, 클릭하면 매치된 텍스트가 강조된 상태로 구절이 열립니다.
- 모드는 검색을 따릅니다: **의미** 검색은 의미로 구절을 찾고, **키워드**(또는 하이브리드) 검색은 용어로 찾습니다.
- 산문 형식: **PDF, TXT, HTML, Markdown, DOCX, RTF, ODT**, 전자책(EPUB, MOBI, AZW3), DjVu, 그리고 SGML/XML 계열(XHTML, XML, DocBook, RSS/Atom, OPML) 및 기타 텍스트/마크업 형식(reST, AsciiDoc, LaTeX, 설정 파일, JSON/YAML, 이메일, 소스 코드). 비산문(스프레드시트, 프레젠테이션, 다이어그램)은 해당 뷰어로 여는 방식으로 대체됩니다.
- 딥 링크는 "찾을 수 없음"을 반환할 수 있는데, 그런 경우는 대개 해당 문서 형식이 아직 처리 로직에 포함되지 않았기 때문입니다. 문서에 이미 할당된 키워드는 잡았지만, 아직 문서 자체를 읽어 딥 링크를 만들지는 못하는 상태입니다. 가치가 있는 곳을 중심으로 가능한 한 확장 중입니다(모나리자 그림인 PDF 에 대한 딥 검색은 아마 영원히 이 방식으로는 검색되지 않을 것입니다).

### 📖 AI 요약
- 임의의 문서 제목을 클릭하면 Kindle 풍의 책 표지 요약이 온디맨드로 생성됩니다.
  Ollama(`dolphin3:latest`)로 생성되며 최초 생성 후 데이터베이스에 캐시됩니다.
  최소 사양 하드웨어(CPU 전용, GPU 없음)에서는 특정 문서의 첫 요약에 시간이 걸릴 수 있으나,
  결과가 캐시되므로 이후 요청은 즉시 반환됩니다.
  의미 검색 임베딩은 두 번째 로컬 모델(`nomic-embed-text:latest`)이 생성합니다.

### 📚 문서 인덱싱
- **형식**: PDF, DOCX, PPTX, XLSX, ODT, ODS, ODP, OTT/OTS/OTP(ODF 템플릿), VSDX/VSDM, VSD/VSS/VST(레거시 Visio), VDX(Visio 2003 XML), draw.io/diagrams.net(.drawio/.dio), PlantUML(.puml/.plantuml), Mermaid(.mmd), SGML/XML 계열(.xml/.xhtml/.sgml/.sgm), DocBook(.docbook/.dbk), SVG, 피드(.rss/.atom/.opml), reStructuredText(.rst), AsciiDoc(.adoc/.asciidoc), LaTeX(.tex/.latex), 이메일(.eml), RTF(.rtf), CSV / TSV, EPUB, MOBI, AZW3, AZW, DjVu(.djvu/.djv), HTML, TXT, Markdown, 그리고 설정 계열 일반 텍스트(.ini/.conf/.cfg/.log/.lst)
- **PDF 지능**: pdfplumber(우선)와 비대해진 오브젝트 파일용 pypdf 폴백; 복잡한 레이아웃을 위한 `layout=False` 재시도; 스캔된(이미지 전용) PDF 는 감지하여 `ocr_list_pdfs.txt` 로 라우팅
- **Word 문서**: python-docx 가 단락, 표, 핵심 속성(제목, 저자, 주제)을 추출
- **프레젠테이션**: python-pptx 가 슬라이드 텍스트, 노트, 핵심 속성을 추출
- **스프레드시트**: openpyxl 이 셀 값과 시트 이름을 추출
- **OpenDocument**: ODF 텍스트 문서(.odt), 스프레드시트(.ods), 프레젠테이션(.odp) 및 그 템플릿 변형(.ott/.ots/.otp) — 단락, 제목, 목록, 표, 셀 값, 슬라이드 텍스트를 Python 표준 라이브러리(`zipfile` + `xml.etree.ElementTree`)로 추출. 템플릿은 mimetype 접두어로 해당 추출기에 라우팅. 메타데이터(제목, 저자, 주제, 설명, 키워드)는 `meta.xml` 에서 읽습니다. 추가 의존성 불필요.
- **Visio 및 다이어그램**:
  - 최신 Visio(`.vsdx`/`.vsdm`) — 표준 라이브러리로 OOXML zip 을 파싱; 도형 텍스트, 페이지 이름, 핵심 속성(제목/저자/주제/키워드)을 제3자 의존성 없이 추출.
  - 레거시 Visio(`.vsd`/`.vss`/`.vst`) — 바이너리 복합 문서; **libvisio-tools** 의 선택적 `vsd2xml` 도구가 필요합니다(`sudo dnf install libvisio-tools` / `sudo apt install libvisio-tools`). 없으면 레거시 파일은 메타데이터만 인덱싱되며(파일명이 제목, 본문 없음), 설치 후 재스캔 시 잡히도록 경로가 `visio_legacy_missing.txt` 에 추가됩니다.
  - draw.io / diagrams.net(`.drawio`/`.dio`) — 일반 `mxfile` XML 과 압축(`deflate + base64 + URL 인코딩`) 다이어그램을 모두 지원; 모든 `mxCell` 라벨과 `object` 라벨, 그리고 페이지 이름을 추출. 표준 라이브러리만 사용.
  - 텍스트 기반 다이어그램 — PlantUML(`.puml`/`.plantuml`)과 Mermaid(`.mmd`) 소스는 일반 텍스트로 인덱싱되며 `diagram` 태그가 붙습니다.
- **마크업 계열**(모두 표준 라이브러리, 추가 의존성 없음):
  - XML/SGML(`.xml`/`.xhtml`/`.sgml`/`.sgm`), DocBook(`.docbook`/`.dbk`), SVG(역시 `diagram` 태그), 피드(`.rss`/`.atom`/`.opml`)는 태그가 제거됩니다 — DOCTYPE, 주석, CDATA 래퍼, `<script>` 및 `<style>` 블록을 제거하고 나머지 태그를 떼어내며, 엔티티는 언이스케이프합니다. 제목/저자/주제는 잘 알려진 요소(`<title>`, `<dc:title>`, `<author>`, `<dc:creator>`)에서 제거 전에 탐지하므로 DocBook, Atom, RSS, SVG 모두 유용한 메타데이터를 드러냅니다.
  - reStructuredText(`.rst`), AsciiDoc(`.adoc`/`.asciidoc`), LaTeX(`.tex`/`.latex`)는 그대로 인덱싱되며(모든 마크업이 검색 가능한 텍스트가 됨) 형식별 제목 휴리스틱을 씁니다: reST 밑줄 스타일 제목, AsciiDoc 레벨 0 `= Title`, LaTeX `\title{}` / `\section{}`. LaTeX `\author{}` 는 캡처되고 줄 `%` 주석은 제거됩니다.
  - 모든 마크업 파일에는 탐색/필터 편의를 위해 `markup` 태그가 붙습니다. `.vdx`(Visio 2003 XML)에는 `diagram` 태그도 붙습니다.
- **이메일, RTF, 표 형식, 설정 계열 텍스트**:
  - 이메일(`.eml`) — 표준 라이브러리 `email` 패키지로 파싱. Subject 가 제목, From 이 저자, To/Cc/Date 와 일반 텍스트 본문(또는 태그 제거한 HTML 본문)이 검색 가능한 내용이 됩니다. 첨부 파일명이 추가되어 이름 검색도 잡힙니다.
  - RTF(`.rtf`) — **striprtf**(순수 Python, MIT)로 디코딩. 없으면 파일은 메타데이터만 인덱싱되고 경로가 `rtf_missing_striprtf.txt` 에 추가됩니다. `striprtf` 설치 후 재스캔하면 본문이 잡힙니다.
  - CSV / TSV — 처음 약 500 행이 파이프 구분 행 렌더링으로 인덱싱됩니다. 헤더 행은 `description` 필드로 들어가 열 이름이 키워드 검색에 반영됩니다. 표준 라이브러리만 사용하며 구분자는 자동 감지됩니다.
  - 설정 계열 일반 텍스트 — `.ini`, `.conf`, `.cfg`, `.log`, `.lst` 는 동일한 200 KB 읽기 상한으로 표준 텍스트 경로를 통합니다.
- **전자책**: EPUB 는 ebooklib; MOBI/AZW3 텍스트 추출은 mobi 패키지 + Calibre `ebook-convert` 폴백; DRM 으로 암호화된 AZW 파일은 메타데이터만 인덱싱(제목/저자는 보이나 본문은 검색 불가)
- **DjVu**: `.djvu`/`.djv` 텍스트 레이어를 **DjVuLibre**(`djvutxt`/`djvused`, 외부 비 pip 도구)로 추출. 없으면 DjVu 파일은 메타데이터만 인덱싱되고 경로가 `djvu_missing_djvulibre.txt` 에 추가됩니다. DjVuLibre 설치 후 재스캔하면 본문 텍스트가 잡힙니다. 텍스트 레이어가 없는 이미지 전용 DjVu 는 메타데이터만 인덱싱됩니다(스캔 PDF 와 동일하게 OCR 미수행)
- **플랫폼**: 모든 추출 라이브러리는 순수 Python 이거나 x86_64 및 ARM64 양쪽의 wheel 이 있습니다. 32비트 시스템은 지원하지 않습니다.
- **메타데이터**: 제목, 저자, 주제를 문서 메타데이터 필드에서 추출; 디렉터리 구조와 내용 키워드에서 태그를 자동 생성
- **PII 보호**: 인제스트 후 스캐너가 SSN, 신용카드, 은행 라우팅/계좌번호, 생년월일, MRN, 운전면허, 여권 패턴을 감지하여 매치 문서를 제거하고 영구 블랙리스트에 등록

### 🎨 사용자 인터페이스
- 다크/라이트 테마 토글
- 페이지네이션된 결과(50 문서/페이지)와 뒤로/다음 컨트롤
- 빠른 이동을 위한 알파벳 인덱스 바(A–Z, 0–9), 페이지 로드 간 상태 유지; 초기화용 홈 버튼
- 주제별 필터링을 위한 태그 클라우드
- 모든 결과에 관련도 점수 배지(0–100%)
- 각 결과 카드의 **열기 버튼** — `xdg-open` 으로 기본 앱에서 파일 실행
- 문서 제목 클릭 시 AI 요약; 📋 는 경로를 클립보드에 복사; 🗑 은 디스크와 인덱스에서 파일 삭제(확인 포함)
- 이동/삭제된 문서: 파일이 더 이상 존재하지 않는 문서를 클릭하면, 해당 파일시스템이 마운트되어 있으면 닫을 수 있는 모달을 표시(닫을 때 인덱스에서 제거)하고, 파일시스템을 확인할 수 없으면(예: 마운트 해제된 드라이브) 토스트를 표시(인덱스 변경 없음)

### ⚙️ 설정(`/settings`)
- 일반 패널: 문서 디렉터리(라이브 디렉터리 브라우저 포함), 임의 개수의 추가 스캔 디렉터리(같은 패널에서 추가/제거 — `scan`/`rescan` 에 자동 포함되며 별도 명령 불필요), 작업 디렉터리, 포트
- 무시 디렉터리 패널: 브라우즈로 디렉터리를 `ignore_dirs.txt` 에 추가하며, 그 아래 이미 인덱싱된 문서를 정리하기 전 확인 프롬프트, 항목 제거 전 확인을 제공

### ⚡ 성능
- 검색 지연: 일반적으로 <150ms
- `ProcessPoolExecutor` 를 통한 병렬 PDF 추출(물리 코어 인식 워커 수)
- 메모리 안전: 커널 강제 RLIMIT_AS(6 GB/워커) + 여유 RAM 임계값에서의 일시정지/재개

---

<a name="search-tips-and-tricks"></a>

## 검색 팁과 요령

[↑ 맨 위](#top)

DocuBrowse 에는 세 가지 검색 모드가 있습니다(우측 상단 토글): **키워드**, **의미**, **모두**(기본 하이브리드). **검색은 Enter 를 누르면 실행됩니다** — 입력란을 비우면 모든 문서가 다시 표시됩니다. **딥 링크**를 클릭했을 때 문서 내부에서도 같은 규칙이 적용되며, 딥 링크는 검색에 사용한 모드를 따릅니다.

### 세 가지 모드

- **키워드** — SQLite FTS5 를 통한 문자 그대로의 텍스트. 각 단어는 접두어 매치되고 OR 로 결합되므로 `budget report` 는 *budget…* **또는** *report…* 를 포함하는 문서를 찾습니다(반드시 둘 다는 아님). 매치 위치로 순위가 매겨집니다 — **제목**과 **저자**의 매치가 본문이나 태그의 매치보다 우선합니다. 실제로 문서에 있는 단어, 이름, 코드를 알 때 가장 좋습니다.
- **의미** — AI 임베딩을 통한 의미. 정확한 단어를 포함하지 않더라도 쿼리에 *관한* 문서를 찾습니다. 개념적 근접도로 순위가 매겨집니다. 정확한 표현을 모른 채 "X 에 관한 문서"를 찾을 때 가장 좋습니다.
- **모두**(기본) — 양쪽을 실행하고 문서별로 두 점수 중 더 강한 쪽을 유지합니다(양쪽 모두 점수가 나면 소폭 가산). 문서가 나타나려면 키워드 매치나 의미 있는 의미 점수를 얻어야 하므로, 약한 의미 잡음이 견고한 키워드 매치를 묻어버리지 않습니다.

### 서로 다른 단어 조합에서 일어나는 일

| 입력 | 키워드 모드 | 의미 모드 |
|---|---|---|
| `budget report` | *budget…* **또는** *report…* 를 가진 문서(접두어, 어느 한쪽) | 예산/재무 보고에 관한 문서, 의미로 |
| `"budget report"` | 정확한 구절 **budget report** 를 포함하는 문서만 | 동일 정확 구절 집합을 의미로 순위화 |
| `freedom and liberty` | *freedom…* 또는 *and…* 또는 *liberty…*(키워드는 모든 단어 유지) | **freedom liberty** 를 임베딩 — 관사와 접속사는 매치를 희석하지 않도록 제거 |
| `man in the middle` | *man… in… the… middle…*(접두어, 임의) | **man in middle** 을 임베딩 — 관사 *the* 는 제거되지만 전치사 *in* 은 유지(전치사는 의미를 담음) |
| `"man in the middle"` | 그 정확한 구절을 가진 문서만(대소문자 무시) | 먼저 정확한 구절을 요구한 뒤 그 집합을 의미로 순위화 |
| 사람 이름, 예: `fred` | *fred* 로 시작하는 토큰 — Frederick, Fredonia… | 퍼지: 짧은 토큰은 느슨하게 임베딩되므로 유사 형태(예: *Fedora*)가 나올 수 있음 — 이름에는 **키워드**를 사용 |

### 따옴표 = 정확한 구절

단어를 `"..."`(또는 `'...'`)로 감싸면 그 **정확한 연속 구절**을 요구합니다(매치는 대소문자 무시). `"machine learning"` 은 그 두 단어가 그 순서로 함께 나타나는 문서만 매치하며, 단지 *machine* 과 *learning* 을 따로 언급하는 문서는 매치하지 않습니다. 이는 모든 모드에서 동작합니다 — 의미/모두 모드에서는 먼저 존재 필터로 작동한 뒤 구절을 포함하는 집합을 의미로 순위화합니다. 형식을 섞을 수 있습니다: `golang "import fmt"` 는 *구절 "import fmt"* 또는 느슨한 단어 *golang* 을 뜻합니다.

구체적으로, 따옴표는 작은 단어들이 계산에 들어가는지를 결정합니다. **`"man in the middle"`** 은 모든 단어를 포함한 그 구절 전체를 검색합니다. **`man in the middle`**(따옴표 없음)은 의미 모드에서 매치 전에 관사 *the* 를 제거하고 *man*, *in*, *middle* 로 검색합니다 — 관사(*a/an/the*)와 접속사(*and/or/but/nor/for/so/yet*)만 불필요어로 취급하기 때문입니다. 정확한 표현이 중요할 때는 구절을 따옴표로 감싸세요.

### 사용 지침

- 정확한 단어, 이름, 오류 코드를 안다 → **키워드**.
- 어떤 주제에 *관한* 문서를 찾는다 → **의미** 또는 **모두**.
- 정확한 구절을 원한다 → **따옴표로 감싼다**(모든 모드).
- **이름**을 검색한다 → **키워드**가 의미보다 낫다(이름은 퍼지하게 임베딩됨).
- 의미 검색은 문자 그대로 명시하지 않은 개념에 대해서도 문서를 드러낼 수 있습니다 — 예: MIT 라이선스 파일이 *freedom* 에 나타나는데, 라이선스 텍스트가 그렇게 읽히기 때문입니다. 이는 버그가 아니라 의미 검색이 의도대로 작동하는 것입니다.

---

<a name="screenshots"></a>

## 스크린샷

[↑ 맨 위](#top)

썸네일을 클릭하면 전체 크기로 볼 수 있습니다.

| 다크 모드 | 라이트 모드 |
|---|---|
| [![Dark mode](screenshots/screenshot-dark-mode.png)](screenshots/screenshot-dark-mode.png) | [![Light mode](screenshots/screenshot-light-mode.png)](screenshots/screenshot-light-mode.png) |

| 설정 | AI 요약 |
|---|---|
| [![Settings page](screenshots/screenshot-settings-page.png)](screenshots/screenshot-settings-page.png) | [![Synopsis modal](screenshots/screenshot-synopsis-modal.png)](screenshots/screenshot-synopsis-modal.png) |

### 딥 링크 — 문서 내 구절 검색

임의의 키워드 또는 의미 검색 결과에서 **딥 링크**는 그 문서 *내부*의 매치 구절을 찾아 하나로 점프하고 매치된 텍스트를 강조합니다.

세 단계 — 결과의 **딥 링크** 버튼, 매치 구절을 나열하는 모달, 선택한 구절이 강조된 모습:

| 의미 검색 결과 | 매치 구절 | 강조된 구절 |
|---|---|---|
| [![Semantic search results with Deep Links](screenshots/deep-links-semantic-results.png)](screenshots/deep-links-semantic-results.png) | [![Semantic Deep Links passage list](screenshots/deep-links-semantic-list.png)](screenshots/deep-links-semantic-list.png) | [![Semantic Deep Links passage](screenshots/deep-links-semantic-passage.png)](screenshots/deep-links-semantic-passage.png) |

| 키워드 검색 결과 | 매치 구절 | 강조된 구절 |
|---|---|---|
| [![Keyword search results with Deep Links](screenshots/deep-links-keyword-results.png)](screenshots/deep-links-keyword-results.png) | [![Keyword Deep Links passage list](screenshots/deep-links-keyword-list.png)](screenshots/deep-links-keyword-list.png) | [![Keyword Deep Links passage](screenshots/deep-links-keyword-passage.png)](screenshots/deep-links-keyword-passage.png) |

> 딥 링크는 문서의 추출된 텍스트를 렌더링하고 매치된 스니펫을 노란색으로, 위치(페이지 / 줄 / 섹션)로 라벨링합니다. 모드는 검색을 따릅니다: 의미 검색은 의미 구절을, 키워드는 키워드 구절을 엽니다.

> 설정은 `/settings` 의 독립 페이지입니다(톱니바퀴 아이콘으로 새 탭에서 열림). 일반 패널은 문서 디렉터리(라이브 디렉터리 브라우저와 임의 개수의 추가 스캔 디렉터리 포함), 작업 디렉터리, 포트를 다루며, 무시 디렉터리 패널은 스캔 제외를 관리합니다(각각 디렉터리 브라우저, 추가/삭제 컨트롤, 제거 전 확인 포함).

---

<a name="quick-start"></a>

## 빠른 시작

[↑ 맨 위](#top)

### 시스템 요구 사항

**최소:** 8 GB RAM, x86_64 또는 ARM64 CPU, 2 GB 여유 디스크(문서와 인덱스를 위한 공간은 별도). GPU 없이 동작합니다 — 요약 생성은 느리지만 작동합니다. 32비트 시스템은 지원하지 않습니다(Ollama 는 32비트 빌드를 제공하지 않습니다).

**권장:** 12 GB RAM, 4 GB 이상 vRAM(NVIDIA 또는 Apple Silicon). GPU 가속은 요약 생성과 임베딩을 크게 빠르게 합니다.

### 전제 조건
- Python 3.9+
- `pdfplumber`, `pypdf` — PDF 추출
- `python-docx` — Word 문서
- `python-pptx` — PowerPoint 프레젠테이션
- `openpyxl` — Excel 스프레드시트
- `ebooklib`, `beautifulsoup4`, `mobi` — 전자책
- `striprtf` — RTF 텍스트 추출(순수 Python; 없으면 .rtf 는 메타데이터만 인덱싱)
- `psutil` — 크로스 플랫폼 프로세스 및 하드웨어 감지
- **Calibre** — 전자책 메타데이터 및 변환(MOBI/AZW3/AZW 인덱싱에 필요):
  `sudo dnf install calibre` 또는 `sudo apt install calibre`
- **libvisio-tools** — *선택*; 레거시 바이너리 Visio(`.vsd`/`.vss`/`.vst`)에서 본문 텍스트를 추출할 때만 필요.
  없어도 해당 파일은 메타데이터만 인덱싱됩니다.
  `sudo dnf install libvisio-tools` 또는 `sudo apt install libvisio-tools`
- **DjVuLibre** — *선택*; DjVu(`.djvu`/`.djv`)에서 텍스트를 추출할 때만 필요.
  없어도 해당 파일은 메타데이터만 인덱싱됩니다.
  `sudo dnf install djvulibre` / `sudo apt install djvulibre-bin` / `brew install djvulibre` / `choco install djvu-libre`
- Ollama — 없으면 `docubrowser start` 가 자동 설치
- 최신 브라우저(Chrome, Firefox, Safari, Edge)

전체 단계별 가이드는 [INSTALL.md](INSTALL.md)를 참조하세요.

### 설치(권장)

DocuBrowse 는 RPM, DEB, tarball, Windows zip, macOS dmg 패키지로 배포됩니다.
[Releases](https://github.com/linuxrebel/DocuBrowser/releases) 페이지에서 적절한 패키지를 다운로드하세요.

```bash
# Fedora / RHEL
sudo dnf install ./docubrowser-foss-<VERSION>-<RELEASE>.noarch.rpm

# Debian / Ubuntu / Mint
sudo apt install ./docubrowser-foss_<VERSION>-<RELEASE>_all.deb

# 임의의 Linux(tarball)
tar xzf docubrowser-foss-<VERSION>-<RELEASE>.tar.gz
cd docubrowser-foss-<VERSION>-<RELEASE>
sudo ./install.sh
```

**Windows:** zip 을 풀고 `Install.bat` 을 더블 클릭합니다. Python 3.9+ 와 Ollama 가
사전 설치되어 있어야 합니다. 시작 메뉴 바로 가기와 함께 `%USERPROFILE%\DocuBrowse` 에
설치됩니다 — 관리자 권한 불필요. 바로 가기가 나타나려면 로그아웃 후 다시 로그인해야 할 수
있습니다.

**macOS:** dmg 를 열고 `Install.command` 를 더블 클릭합니다(처음에는 우클릭 →
열기 — 스크립트는 서명되지 않았습니다). Python 3.9+ 가 필요합니다.
Python 가상환경과 함께 `~/Applications/DocuBrowse/` 에 설치되며, CLI 래퍼가
`/usr/local/bin/docubrowser` 및 `/usr/local/bin/docuback` 에(sudo 프롬프트; 거부 시
`~/bin/` 으로 폴백), 서버를 시작하고 터미널에서 웹 UI 를 여는 `DocuBrowse.app`
런처가 생성됩니다.

모든 Linux 방식은 Python 가상환경과 함께 `/opt/docubrowser/` 에 설치되며, CLI 래퍼가
`/usr/bin/docubrowser` 및 `/usr/bin/docuback` 에, 데스크톱 메뉴 항목이 Office 아래에,
그리고 `requirements.txt` 의 모든 Python 의존성이 설치됩니다.

설치되면 CLI 는 `docubrowser` 명령입니다 — 아래 모든 예시에서 `./` 와 `.py` 를
빼세요. 예: `docubrowser start` 및 `docubrowser rescan`. 이 README 나머지 전반에서
보이는 `./docubrowser.py <cmd>` 형식은 개발 / 클론한 리포지토리 경로입니다(체크아웃에서
직접 실행).

제거하려면: `sudo dnf remove docubrowser-foss`(RPM),
`sudo apt remove docubrowser-foss`(DEB), `sudo ./uninstall.sh`(tarball),
`Uninstall.bat` 더블 클릭(Windows), 또는 `Uninstall.command` 더블 클릭
(macOS — dmg 또는 `~/Applications/DocuBrowse/` 에서).

### 초기 실행(개발 / 클론한 리포지토리)

```bash
cd /path/to/DocuBrowse

# 문서를 스캔하고 인덱싱
./docubrowser.py rescan

# 서버 시작
./docubrowser.py start

# UI 열기
./docubrowser.py open
```

> 설치된 시스템에서는 대신 `docubrowser` 명령을 사용하세요. 예:
> `docubrowser rescan` / `docubrowser start` / `docubrowser open`.

`docubrowser.py start` 는 Ollama 가 설치·실행 중이며 필요한 두 모델 —
`nomic-embed-text:latest`(임베딩)와 `dolphin3:latest`(요약 생성) — 이 있는지 자동
확인하고, 필요에 따라 설치/시작/풀합니다.

---

<a name="cli-reference"></a>

## CLI 참조

[↑ 맨 위](#top)

```
Usage: docubrowser.py <command> [options]
```

### 명령

| 명령 | 설명 |
|---------|-------------|
| `start` | 검색 서버 시작(먼저 Ollama 확인 실행) |
| `stop` | 서버 중지 |
| `restart` | 중지 후 시작 |
| `status` | 서버 상태, 문서 수, 임베딩 수, 태그 수 표시 |
| `scan [TYPE ...]` | 문서 스캔·인덱싱·임베딩(`rescan` 과 동일; `--no-embed` 로 임베딩 생략) |
| `rescan [TYPE ...]` | `scan` 의 별칭(하위 호환용 유지) |
| `scan-file --file PATH` | 단일 파일을 추출·인덱싱한 뒤 임베딩 |
| `embed` | 미임베딩 문서의 임베딩 생성/갱신 |
| `open` | 기본 브라우저에서 DocuBrowse UI 열기 |
| `purge` | 인덱스에서 PII 를 스캔하여 매치 문서 제거 |
| `ignore add\|remove\|list DIR` | 스캔에서 제외할 디렉터리 관리(추가 시 자동 정리) |
| `report` | 문서 디렉터리를 순회하며 파일 형식 분포 표시(DB 변경 없음) |
| `scan-missing [--db PATH] [--dry-run]` | 옵트인 정리: 인덱싱된 모든 경로를 존재/누락/마운트 해제로 분류하고, `missing` 행 삭제(연쇄), `unmounted` 행은 그대로 둠 |
| `stopall` | 실행 중인 모든 스캔, 임베딩, 서버 중지 |
| `duplist` | 중복 문서 목록(정확 SHA256 + 선택적 근사 중복) |
| `dupclean` | 중복 문서를 검토·제거하는 대화형 TUI |

### 전역 옵션

```
--db PATH      SQLite 데이터베이스 경로(설정 무시)
--port PORT    서버 포트(설정 무시)
--config FILE  설정 파일 경로
```

### 명령 예시

```bash
# 서버 관리
./docubrowser.py start
./docubrowser.py start --port 9000
./docubrowser.py status
./docubrowser.py stop
./docubrowser.py stopall

# 스캔(scan 과 rescan 은 동일)
./docubrowser.py scan                          # 모든 형식 스캔·인덱싱·임베딩
./docubrowser.py scan pdf                      # PDF 만
./docubrowser.py scan pdf txt                  # PDF 와 일반 텍스트
./docubrowser.py scan --limit 100              # 미인덱싱 파일 처음 100 개만
./docubrowser.py scan --workers 4              # 추출 워커 4 개
./docubrowser.py scan --no-embed               # 임베딩 단계 없이 스캔
./docubrowser.py scan --doc-dir /data/docs

# 단일 파일 인덱싱(블랙리스트된 파일 재시도에 유용)
./docubrowser.py scan-file --file /path/to/document.pdf
./docubrowser.py scan-file --file /path/with spaces/doc.pdf   # 따옴표 불필요
./docubrowser.py scan-file --file /path/to/doc.pdf --no-embed

# 보고 및 유지 관리
./docubrowser.py report                         # 파일 형식 분포, DB 변경 없음
./docubrowser.py embed                          # 미임베딩 문서 임베딩
./docubrowser.py purge --dry-run               # PII 매치 미리보기(안전)
./docubrowser.py purge                         # PII 문서 제거(확인)

# 스캔에서 디렉터리 제외
./docubrowser.py ignore add ~/Documents/myWorkDocs   # 제외 + 그 아래 인덱싱 문서 정리
./docubrowser.py ignore list                                  # 무시 디렉터리 표시
./docubrowser.py ignore remove ~/Documents/myWorkDocs # 재허용(재스캔하면 재인덱싱)

# 중복 감지 및 정리
./docubrowser.py duplist                       # 정확 SHA256 중복 찾기
./docubrowser.py duplist --near-dups           # 근사 중복도 찾기(코사인 ≥97%)
./docubrowser.py duplist --near-dups --threshold 0.95
./docubrowser.py dupclean                      # 대화형 Keep A/Keep B/Keep Both TUI
./docubrowser.py dupclean --near-dups          # 정리에 근사 중복 포함

# 이동/삭제된 문서 정리(옵트인, 자동 실행 아님)
./docubrowser.py scan-missing --dry-run        # 개수만 보고, DB 변경 없음
./docubrowser.py scan-missing                  # 실제로 누락된 파일의 행 삭제

# 구버전이 인덱싱한 도트파일 제거(독립 일회성 도구)
python3 purge_dotfiles.py                       # 드라이런: 전체 목록 표시, 변경 없음
python3 purge_dotfiles.py --apply               # 삭제(연쇄 안전)
python3 purge_dotfiles.py --db /path/du.db --roots /docs /extra --apply
```

> `purge_dotfiles.py` 는 과도기 마이그레이션 도구로 직접 실행합니다(`docubrowser`
> 하위 명령 아님). 스캐너는 앞으로 도트파일을 이미 건너뜁니다(D-6); 이 도구는 구버전이
> 남긴 행을 정리합니다. 스캐너와 동일한 roots 인식 숨김 경로 검사(의도적으로 스캔된
> 도트 디렉터리 root 는 예외)와 연쇄 안전 삭제 경로를 사용하므로 FTS 행, 태그, 임베딩이
> 올바르게 정리됩니다. 기본은 드라이런; `--apply` 로 삭제; `--db` / `--roots` 로 기본값
> 재정의.

### scan / rescan 형식 필터

```
Types: pdf  txt  md  html  (default: all supported)

Examples:
  scan pdf               PDFs only
  scan pdf txt           PDFs and plain text
  scan                   all supported types (prompts if unfiltered)
```

### scan-file 세부 사항

`scan-file` 은 개별 문제 파일 재시도를 위해 설계되었습니다:
- 목록에 있으면 `scan_blacklist.txt` 에서 파일 제거(명시적 재시도)
- `pii_blacklist.txt` 의 파일은 거부(영구 PII 차단)
- 스캔된(이미지 전용) PDF 감지 → `ocr_list_pdfs.txt` 에 추가
- 공백이 포함된 경로는 따옴표 없이 동작: `--file` 은 여러 토큰을 받아 다시 결합

---

<a name="configuration"></a>

## 설정

[↑ 맨 위](#top)

DocuBrowse 는 처음 발견한 설정 파일을 읽습니다:

1. `/etc/docubrowse.config`(시스템 전역)
2. `./docubrowse.config`(`docubrowser.py` 옆)

둘 다 없으면 내장 기본값이 적용됩니다 — 단, 기본값이 없는 `doc_dir` 은 예외입니다.
문서 디렉터리가 설정되기 전까지(웹 UI 의 설정 톱니바퀴 아이콘 또는 `docubrowse.config` 의
`doc_dir` 설정을 통해), 웹 UI 는 설정을 유도하는 배너를 표시하며, 문서 디렉터리가 필요한
CLI 명령(`rescan`, `report`, `scan`)은 설정 방법을 설명하는 오류로 종료됩니다.

### 설정 파일 형식

```ini
# docubrowse.config
doc_dir      = ~/Documents
db_path      = /home/user/DocuBrowse/du-docs.db
port         = 8643
work_dir     = /home/user/DocuBrowse
lang         = en
```

### 기본값

| 키 | 기본값 |
|-----|---------|
| `doc_dir` | _(없음 — 설정 또는 docubrowse.config 로 지정 필요)_ |
| `db_path` | `<script dir>/du-docs.db` |
| `port` | `8643` |
| `work_dir` | `<script dir>` |
| `lang` | `en` — [언어](#languages) 참조 |

### 환경 변수

환경 변수는 일치하는 설정 파일 키를 무시합니다(컨테이너에 유용). 제공되면 CLI 플래그가
여전히 우선합니다.

| 변수 | 기본값 / 무시 대상 | 설명 |
|----------|---------------------|-------------|
| `DOCUBROWSE_DOC_DIR` | config `doc_dir` | 인덱싱할 기본 문서 디렉터리 |
| `DOCUBROWSE_DB` / `DOCUBROWSE_DB_PATH` | config `db_path` | `du-docs.db` 경로 |
| `DOCUBROWSE_PORT` | `8643` | HTTP 서버 포트 |
| `DOCUBROWSE_WORK_DIR` | config `work_dir` | 런타임 데이터용 작업 디렉터리 |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama HTTP API(임베딩 + 요약)의 기본 URL. 맨 `host:port` 도 허용(스킴 기본값 `http://`). `DOCUBROWSE_OLLAMA_HOST` 로도 허용. |
| `DOCUBROWSE_TRUSTED_CIDRS` | _(비어 있음)_ | 루프백에 더해 서버에 접근을 허용하는 쉼표 구분 CIDR/IP(예: 단일 Docker 프록시에 `172.17.0.2/32`, 또는 정확한 Compose 서브넷). 비어 있으면 루프백 전용. `/24`(IPv4) 또는 `/120`(IPv6)보다 넓은 범위는 거부 — 네트워크 전체가 아니라 호스트를 신뢰; `/32` 를 선호. **인증이 아님** — 리버스 프록시/BFF 뒤의 사설 네트워크만 나열. |
| `DOCUBROWSE_ALLOWED_HOSTS` | _(비어 있음)_ | 루프백에 더해 허용되는 쉼표 구분 Host 헤더 이름(예: `docubrowse`). 컨테이너 서비스 이름이 `Host` 에 나타날 때 필요. |

`doc_search.py` 는 argv 가 생략되면 `DOCUBROWSE_DB` / `DOCUBROWSE_PORT` 도 받으므로,
컨테이너 진입점이 환경만으로 서버를 시작할 수 있습니다. `OLLAMA_HOST` 는
`doc_search.py`, `embed_docs.py`, `ensure_ollama.py` 가 읽습니다 — Ollama 가 다른
호스트나 컨테이너에서 실행될 때 설정하세요(예: Docker Compose 의 `http://ollama:11434`).

여전히 사용자 로그인은 없습니다. 신뢰된 피어는 전체 API 를 호출할 수 있습니다; 리버스
프록시나 BFF 에 인증을 두고 DocuBrowse 의 포트를 절대 공개하지 마세요.

---

<a name="languages"></a>

## 언어

[↑ 맨 위](#top)

DocuBrowse 설치는 한 번에 **하나의** 언어를 제공합니다 — 인터페이스, FTS 토크나이저,
임베딩 모델, 요약 모델이 모두 그 하나의 언어에 맞게 선택됩니다. 이는 문서 단위가 아니라
설치 단위 설정입니다: DocuBrowse 는 구성된 문서 디렉터리가 압도적으로 하나의 언어라고
가정하며, 혼합 언어 코퍼스나 문서 단위 언어 감지를 지원하지 않습니다.

**현재 지원:** 영어(`en`, 기본), 일본어(`ja`), 한국어(`ko`).
일본어와 한국어는 `bge-m3` 다국어 임베딩 모델을 사용합니다(영어는 `nomic-embed-text`).
한국어 요약 모델은 `exaone3.5` 입니다. 키워드(FTS5) 검색에서 CJK 텍스트(일본어와 한국어)는
FTS5 내장 `trigram` 토크나이저 대신 표준 `unicode61` 토크나이저와 앱 측 문자 바이그램
분절(`cjk.py` 참조)로 인덱싱됩니다 — 일본어 텍스트는 단어 사이에 공백이 없고, 한국어는
어절 사이에 공백이 있지만 교착어라 명사에 조사가 붙으므로(예: `학교에서` = `학교` + `에서`),
색인 시점과 질의 시점 텍스트 모두 FTS5 가 보기 전에 겹치는 2 문자 바이그램으로 미리
분할됩니다. 이는 형태소 분석기가 아니며(MeCab/jieba/konlpy 의존성 없음), 언어적 정확성을
내주는 대신 2 문자 이상의 모든 CJK 부분 문자열을 확실히 인덱싱하는 무의존 대체물입니다.
단일 CJK 문자는 키워드 모드에서 정확 매치되지 않지만(설계상 — 1 문자 매치는 너무 잡음이
많음) 모두/의미 검색으로는 여전히 드러납니다.

**한국어 자모 인덱스 바:** 한글은 진정한 알파벳이므로(가나·한자에 첫 글자 순서가 없는
일본어와 다릅니다) 한국어에서는 문서 목록 인덱스 바가 활성화되어 14 개의 기본 초성
ㄱ ㄴ ㄷ ㄹ ㅁ ㅂ ㅅ ㅇ ㅈ ㅊ ㅋ ㅌ ㅍ ㅎ 을 표시합니다. 각 버튼은 그 자음으로 시작하는
음절로 제목이 시작하는 문서를 필터링합니다(된소리는 기본 자음으로 통합됩니다, 예: ㄲ→ㄱ).
영어는 A–Z/0–9 바를 사용하고, 일본어에서는 바가 숨겨진 채로 유지됩니다.

**언어 선택:**

- **설치 시점** — `install.sh` 가 새 설치에서 언어를 묻습니다. 비대화식으로는
  `DOCUBROWSE_LANG=en`, `=ja`, `=ko` 로 답합니다. **업그레이드는 절대 다시 묻지
  않습니다** — `docubrowse.config` 의 기존 `lang` 값은 항상 보존됩니다. (플랫폼 설치
  프로그램 — Windows/macOS/RPM/DEB — 은 새 설치를 `lang = en` 으로 기본 설정합니다;
  이후 설정에서 변경하세요.)
- **시작 시점** — `docubrowser ko start`(또는 `docubrowser start ja`)로 해당 언어로
  서버를 시작합니다. 코드는 어느 위치에 두어도 됩니다. 선택은 `docubrowse.config` 에
  기록되어, 다른 언어를 고를 때까지 이후의 일반 `docubrowser start` 에서도 유지됩니다.
- **설치 후** — 웹 UI 를 열고 설정(톱니바퀴) 아이콘을 클릭한 뒤, 일반 패널의 언어
  드롭다운을 사용합니다(`POST /api/language` 호출). 다른 임베더나 FTS 토크나이저를 쓰는
  언어로 전환하면(예: 영어 ↔ 일본어/한국어) 경고가 표시됩니다: 기존 문서는
  `docubrowser rescan`(또는 `embed_docs.py`)을 다시 실행하여 새 언어에 맞게 재구축할
  때까지 기존 임베딩과 FTS 인덱스를 유지하며, 그때까지는 이미 인덱싱된 문서의 검색
  품질이 저하됩니다. (일본어 ↔ 한국어는 `bge-m3` 임베더와 같은 토크나이저를 공유하므로
  두 언어 간에는 재구축이 필요 없습니다.)

**아직 미지원:** 혼합 언어 또는 문서 단위 언어 코퍼스, 영어/일본어/한국어 이외의
언어(`lang_models.py` 의 `LANG_MODELS` 테이블에 한 행과 `locales/<code>.json` 파일이
전체 메커니즘이므로, 언어 추가는 코드 변경이 아니라 데이터 변경입니다), 일본어/중국어
문서 목록을 위한 가나/읽기 기반(또는 병음) 인덱스 바(일본어에는 첫 글자 순서가 없고,
한국어는 위에서 설명한 초성 바를 사용합니다), 그리고 일본어 "마이넘버" PII 감지(현재는
미국 PII 패턴만 구현됨).

---

<a name="architecture"></a>

## 아키텍처

[↑ 맨 위](#top)

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

### 주요 스크립트

| 스크립트 | 역할 |
|--------|------|
| `docubrowser.py` | CLI 런처 — 모든 명령 |
| `ensure_ollama.py` | Ollama 바이너리, 서비스, 필요한 모델 확인/설치 |
| `doc_search.py` | HTTP 서버; 검색 API 및 UI |
| `docubrowse_db.py` | SQLite 스키마 및 마이그레이션 |
| `platform_paths.py` | 크로스 플랫폼 경로 해석 및 프로세스 관리 |
| `scan_docs.py` | 문서 발견, 추출, DB 쓰기 |
| `pdf_extractor.py` | pdfplumber/pypdf 를 통한 PDF 전용 추출 |
| `docx_extractor.py` | Word 문서 추출(python-docx) |
| `odf_extractor.py` | OpenDocument(.odt, .ods, .odp) 추출(표준 라이브러리) |
| `visio_extractor.py` | Visio + draw.io 추출(.vsdx/.vsdm/.vsd/.vss/.vst/.drawio/.dio) |
| `markup_extractor.py` | SGML/XML 계열 + reST/AsciiDoc/LaTeX(표준 라이브러리) |
| `eml_extractor.py` | 이메일(.eml) — 표준 라이브러리 `email` |
| `csv_extractor.py` | CSV / TSV — 표준 라이브러리 `csv` |
| `rtf_extractor.py` | RTF — `striprtf`(없으면 우아한 성능 저하) |
| `djvu_extractor.py` | DjVu(.djvu/.djv) — DjVuLibre `djvutxt`/`djvused`(없으면 우아한 성능 저하) |
| `ebook_extractor.py` | EPUB/MOBI/AZW3/AZW 추출(ebooklib + Calibre) |
| `hardware_utils.py` | CPU/GPU/RAM 감지, 워커 수 공식 |
| `embed_docs.py` | Ollama 에 텍스트 전송; 768 차원 벡터 저장 |
| `purge_pii.py` | 인덱스의 PII 스캔; 매치 제거 및 블랙리스트 |
| `purge_dotfiles.py` | 일회성 마이그레이션 도구: 이미 인덱싱된 도트파일을 DB 에서 제거(기본 드라이런) |
| `dup_detect.py` | 정확(SHA256) 및 근사 중복(코사인 유사도) 감지 |

### 블랙리스트 파일

| 파일 | 목적 | 영구? |
|------|---------|-----------|
| `scan_blacklist.txt` | 추출 실패 파일 | 아니오 — 줄 삭제로 재시도 |
| `pii_blacklist.txt` | PII 로 제거된 파일 | 예 — 절대 재인제스트 안 함 |
| `ocr_list_pdfs.txt` | OCR 이 필요한 이미지 전용 PDF | 해당 없음 — 정보용 |
| `visio_legacy_missing.txt` | `vsd2xml` 이 없을 때 본 레거시 `.vsd`/`.vss`/`.vst` | 해당 없음 — 정보용; libvisio-tools 설치 + 재스캔 |
| `rtf_missing_striprtf.txt` | `striprtf` 가 없을 때 본 `.rtf` | 해당 없음 — 정보용; `pip install striprtf` + 재스캔 |
| `ignore_dirs.txt` | 스캔에서 제외된 디렉터리(`ignore` 명령으로 관리) | 아니오 — `ignore remove` + `rescan` |

---

<a name="api-endpoints"></a>

## API 엔드포인트

[↑ 맨 위](#top)

기본 URL: `http://localhost:8643`

| 메서드 | 경로 | 설명 |
|--------|------|-------------|
| `GET` | `/` | `index.html` 제공(프로세스별 CSRF 토큰 주입) |
| `GET` | `/settings` | `settings.html` 제공 |
| `GET` | `/api/stats` | 전체 문서 수, 임베딩 수, 고유 태그 수 |
| `GET` | `/api/tags` | 개수가 있는 태그 목록(≥3 회 등장) |
| `GET` | `/api/search` | 페이지네이션 검색 |
| `GET` | `/api/letters` | 알파벳 바용 첫 글자 인덱스 |
| `GET` | `/api/synopsis` | 문서의 AI 요약 생성/반환 |
| `GET` | `/api/deep-links` | 하나의 인덱싱된 문서 내부의 매치 구절(`path`, `q`, `mode=keyword\|semantic`) |
| `GET` | `/api/config` | 현재 서버 설정 |
| `GET` | `/api/ignore-dirs` | 제외된 디렉터리 목록 |
| `GET` | `/api/scan-dirs` | 추가 스캔 디렉터리 목록 |
| 🔒 `GET` | `/api/browse` | 설정용 디렉터리 브라우저(토큰 게이트) |
| 🔒 `POST` | `/api/open` | xdg-open/gio 로 파일 열기(DB 대조 검증) |
| 🔒 `POST` | `/api/delete` | 디스크에서 파일 삭제 및 인덱스에서 제거(경로가 인덱싱되어 있어야 함) |
| 🔒 `POST` | `/api/config` | 서버 설정 저장 |
| 🔒 `POST` | `/api/ignore-dirs` | 제외 디렉터리 추가/제거 |
| 🔒 `POST` | `/api/scan-dirs` | 추가 스캔 디렉터리 추가/제거 |

🔒 = 상태 변경 또는 파일시스템 노출; 프로세스별 `X-CSRF-Token` 헤더와 루프백
`Origin`/`Referer` 가 필요합니다. 토큰은 제공되는 HTML 에 주입되므로 first-party UI 만
이를 호출할 수 있습니다. [보안](#security)을 참조하세요. 또한 `Host` 헤더가
`localhost`/`127.0.0.1`/`[::1]` 이 아니면 모든 요청이 거부됩니다(DNS 리바인딩 방어).

### /api/open — 누락 및 마운트 해제된 파일

인덱싱된 경로가 디스크에 더 이상 존재하지 않으면, `/api/open` 은 다음 중 하나를 반환합니다:

```json
{"ok": false, "error": "missing", "message": "..."}
{"ok": false, "error": "unmounted", "message": "..."}
```

`missing` 은 파일의 파일시스템이 마운트되어 있고 파일이 실제로 사라졌음을 뜻합니다 — UI 는
닫을 수 있는 모달을 표시하고 닫을 때 인덱스(및 디스크 인접 DB 행)에서 문서를 삭제합니다.
`unmounted` 는 경로의 파일시스템을 현재 확인할 수 없음을 뜻합니다(마운트 해제된 드라이브일
가능성) — UI 는 토스트를 표시하고 DB 를 변경하지 않습니다. 동등한 배치 정리는
`scan-missing` 을 참조하세요.

### 검색 파라미터

```
GET /api/search?q=QUERY&offset=0&mode=both
```

| 파라미터 | 값 | 기본값 |
|-------|--------|---------|
| `q` | 검색 문자열 | `""`(모든 문서 반환) |
| `mode` | `both` \| `keyword` \| `semantic` | `both` |
| `offset` | 정수 | `0` |

### 검색 응답

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

### 빠른 API 테스트

```bash
# 읽기 엔드포인트는 단순 GET:
curl "http://localhost:8643/api/stats"
curl "http://localhost:8643/api/search?q=kubernetes&mode=both"
curl "http://localhost:8643/api/search?q=&offset=50"
```

변경 엔드포인트(`/api/delete`, `/api/open`, `POST` 설정/디렉터리 라우트)와
`/api/browse` 는 프로세스별 CSRF 토큰과 루프백 오리진을 요구하므로, 맨 `curl` 로는 쉽게
호출되지 않습니다 — UI 에서 구동하거나, `<token>` 을 `/` 의 `<meta name="csrf-token">`
태그에서 읽어 `-X POST -H "X-CSRF-Token: <token>" -H "Origin: http://localhost:8643"`
를 전달하세요.

---

<a name="search-algorithm"></a>

## 검색 알고리즘

[↑ 맨 위](#top)

비어 있지 않은 쿼리는 두 방식으로 점수화되어 병합됩니다; 이후 메타데이터는 요청된
페이지에 대해서만 조회됩니다(더 이상 요청마다 전체 코퍼스를 로드하지 않음).

```
final_score = 0.3 × keyword_score + 0.7 × semantic_score   (mode=both)
```

### 키워드 점수화(FTS5 BM25)

- Python 부분 문자열 스캔이 아니라 `MATCH` + `bm25()` 를 통한 SQLite **FTS5** 인덱스로
  뒷받침됩니다.
- 쿼리 토큰은 따옴표로 묶여 접두어 매치되고(`"tok"*`) OR 로 결합되므로, 임의 입력(연산자,
  따옴표, `C++`, `&`)이 쿼리를 깨뜨릴 수 없습니다.
- 열별 BM25 가중치는 기존 필드 우선순위를 반영합니다
  (name 6, title 8, author 7, subject 5, description 3, content_snippet 3,
  tags 4); 결과는 0–1 로 정규화됩니다.
- 고아 `doc_fts` rowid(내용 없는 FTS 는 FK 연쇄가 없음)는 라이브 문서 집합과 대조해
  제거되므로 합계를 부풀릴 수 없습니다.

### 의미 점수화

- 쿼리 임베딩과 각 문서 임베딩 사이의 코사인 유사도.
- 요청마다 모든 BLOB 을 다시 로드하는 대신, **프로세스 내 L2 정규화 임베딩 행렬**(하나의
  벡터화된 NumPy 행렬-벡터 곱)에 대해 계산되며, 임베딩 테이블이 바뀌면 캐시가
  무효화됩니다.
- 범위 0.0–1.0; 최소 임계값(의미 전용 모드): **0.30**.
- 임베딩: 768 차원 float32 벡터(nomic-embed-text:latest).

---

<a name="security"></a>

## 보안

[↑ 맨 위](#top)

DocuBrowse 는 localhost 에 바인딩되며 단일 사용자 로컬 사용을 위한 것이지만, 방문하게 된
악의적 웹 페이지가 접근할 수 없도록 강화되어 있습니다:

- **Host 헤더 허용 목록** — `Host` 가 `localhost`/`127.0.0.1`/`[::1]`(선택적으로 서비스
  포트 포함)이 아니면 모든 요청이 거부됩니다. localhost 바인딩 서버에 대한 DNS 리바인딩을
  무력화합니다.
- **변경에 대한 CSRF 토큰** — `/api/delete` 와 `/api/open` 은 POST 전용이며, POST
  설정/디렉터리 라우트 및 파일시스템 노출 `/api/browse` 와 함께 프로세스별
  `X-CSRF-Token`(제공되는 HTML 에 주입되므로 first-party UI 만 보유)과 루프백
  `Origin`/`Referer` 를 요구합니다.
- **저장 데이터 주입 없음** — 문서 필드는 HTML 용으로 이스케이프되고 카드 동작은 `data-*`
  속성 + 위임 리스너를 사용하므로(문서 데이터로 만든 인라인 `onclick` 없음), 저장형 XSS
  벡터를 차단합니다.
- **PII 정리**는 삭제 전에 구조적으로 검증합니다: SSN 은 SSA 할당 규칙, 신용카드는 길이 +
  발급사 접두어 + Luhn, 은행 라우팅 번호는 ABA 체크섬 + 연방준비 접두어로 — 그래서 실제
  PII 를 더 많이 잡으면서 우연한 숫자 묶음으로 문서를 삭제하지 않습니다.

서버는 기본적으로 localhost 전용입니다 — `127.0.0.1` 에만 바인딩하며(그래서 포트가 외부
인터페이스에 노출되지 않음), 옵트인 `DOCUBROWSE_TRUSTED_CIDRS` 모드에서는 루프백 + 신뢰
목록 밖의 모든 연결을 소켓 수준에서 거부합니다. 로컬 사용자만 서버에 도달할 수 있으므로
인증이 필요 없으며, 접근 제어는 호스트 방화벽에 의존하지 않습니다.

선택: `DOCUBROWSE_TRUSTED_CIDRS`(그리고 보통 `DOCUBROWSE_ALLOWED_HOSTS`)를 설정하여
사설 네트워크 리버스 프록시나 BFF(예: Docker Compose)가 API 에 도달하도록 허용할 수
있습니다. 이는 공개 노출이 **아니며** 인증도 **아닙니다** — CIDR 목록을 비공개로 유지하고
DocuBrowse 앞에 로그인을 두세요.

신뢰된 피어는 완전히 신뢰됩니다: `DOCUBROWSE_TRUSTED_CIDRS` 의 비루프백 피어는 CSRF 검사를
건너뛰므로, 서버 측 프록시가 HTML 토큰을 긁지 않고도 변경 엔드포인트를 호출할 수
있습니다(루프백 브라우저는 여전히 요구). 이는 전체 API 에 미인증 접근을 부여하므로, 파서는
`/24`(IPv4) 또는 `/120`(IPv6)보다 넓은 범위를 거부합니다 — 단일 호스트(`/32`)나 작은
서브넷을 신뢰하고, 손상된 한 호스트가 DocuBrowse 에 도달할 수 있는 `/8` 이나 `/16` 기업
네트워크는 절대 신뢰하지 마세요.

---

<a name="file-structure"></a>

## 파일 구조

[↑ 맨 위](#top)

```
DocuBrowse/
├── docubrowser.py          # CLI entry point (all commands)
├── ensure_ollama.py        # Ollama prerequisite checker/installer
├── doc_search.py           # HTTP search server (port 8643)
├── docubrowse_db.py        # SQLite schema and migrations
├── scan_docs.py            # Scanner: discovery, extraction, DB writes
├── pdf_extractor.py        # PDF extraction (pdfplumber + pypdf fallback)
├── docx_extractor.py       # Word document extraction (python-docx)
├── odf_extractor.py        # OpenDocument (.odt/.ods/.odp) extraction (stdlib)
├── visio_extractor.py      # Visio (.vsdx/.vsdm/.vsd) + draw.io (.drawio/.dio)
├── markup_extractor.py     # SGML/XML family + reST/AsciiDoc/LaTeX (stdlib)
├── eml_extractor.py        # Email (.eml) — stdlib `email`
├── csv_extractor.py        # CSV / TSV — stdlib `csv`
├── rtf_extractor.py        # RTF via striprtf (graceful degradation)
├── ebook_extractor.py      # EPUB/MOBI/AZW3/AZW extraction (ebooklib + Calibre)
├── hardware_utils.py       # CPU/GPU/RAM detection, worker formula
├── embed_docs.py           # Embedding generation pipeline
├── purge_pii.py            # PII scanner and purge tool
├── purge_dotfiles.py       # One-off: remove indexed dotfiles from the DB
├── dup_detect.py           # Exact (SHA256) and near-duplicate detection
├── platform_paths.py       # Cross-platform paths and process management
├── index.html              # Frontend UI (single-file, dark/light theme)
├── du-docs.db              # SQLite database (gitignored)
├── du-docs.db.example      # Empty schema for new installs
├── scan_blacklist.txt      # Failed-extraction skiplist (gitignored)
├── pii_blacklist.txt       # PII-removed files — permanent (gitignored)
├── ocr_list_pdfs.txt       # Image-only PDFs needing OCR (gitignored)
├── visio_legacy_missing.txt # Legacy .vsd files seen without vsd2xml (gitignored)
├── rtf_missing_striprtf.txt # .rtf files seen without striprtf (gitignored)
├── ignore_dirs.txt         # Directories excluded from scanning (gitignored)
├── scan_dirs.txt           # Additional scan directories (gitignored)
├── docubrowse.config       # Local config (optional, gitignored)
├── INSTALL.md              # Step-by-step install guide
├── README.md               # This file
├── LICENSE                 # GPL-3.0
├── packaging/              # RPM spec, DEB control, build scripts, installers
│   ├── build_packages.sh   # Builds RPM, DEB, and tarball (Linux)
│   ├── build_windows_zip.sh # Builds Windows zip
│   ├── docubrowser-foss.spec  # RPM spec
│   ├── docubrowser.desktop # Desktop menu entry (Linux)
│   ├── install.sh          # Tarball installer (Linux)
│   ├── uninstall.sh        # Tarball uninstaller (Linux)
│   ├── windows/            # Windows installer/uninstaller scripts
│   │   ├── Install.bat     # Double-click to install
│   │   ├── Uninstall.bat   # Double-click to uninstall
│   │   ├── install.ps1     # PowerShell installer
│   │   └── uninstall.ps1   # PowerShell uninstaller
│   └── macos/              # macOS installer/uninstaller scripts
│       ├── build_macos_dmg.sh   # Builds the macOS dmg
│       ├── Install.command      # Double-click to install
│       └── Uninstall.command    # Double-click to uninstall
├── systemd/
│   └── docubrowser.service # systemd unit file
├── status_docs/            # Project planning and decision logs
│   ├── project_status.md   # Current version, session history
│   └── DECISIONS.md        # Deferred decisions and known issues
└── test_pdfs_live/         # 100 sample PDFs for testing
```

---

<a name="troubleshooting"></a>

## 문제 해결

[↑ 맨 위](#top)

### Inotify 감시 한도

대규모 문서 모음은 다음을 유발할 수 있습니다:
```
OSError: [Errno 28] inotify watch limit reached
```
이는 디스크 공간 문제가 아니라 Linux 커널 한도입니다. 이 경고는 무시해도 안전하지만,
보고 싶지 않다면 스캔하는 동안 한도를 높이세요:

1. `/etc/sysctl.conf` 를 편집하여 다음 줄을 찾습니다:
   ```
   fs.inotify.max_user_instances=128
   ```
2. `256` 또는 `512` 로 높입니다:
   ```
   fs.inotify.max_user_instances=256
   ```
3. 재부팅 없이 변경 적용:
   ```bash
   sudo sysctl -p
   ```

인제스트가 끝나면 값을 `128` 로 되돌리거나(파일을 다시 편집하고 `sudo sysctl -p` 재실행)
그대로 높인 채 두어도 됩니다.

### 스캔 중 PDF 멈춤

일부 PDF 는 pdfminer 를 멈추게 합니다. 이들은 자동 감지되어 블랙리스트됩니다. 특정 파일이
문제를 일으키면 확인하세요:

```bash
# PDF 오브젝트가 몇 개인가? (>8000 은 비정상)
pdfinfo /path/to/file.pdf | grep -i objects

# 블랙리스트된 후 파일 재시도
./docubrowser.py scan-file --file /path/to/file.pdf
```

PDF 오브젝트가 8,000 개를 초과하는 파일(보통 반복적인 ExifTool 메타데이터 갱신이 원인)은
자동으로 pdfminer 대신 pypdf 를 통해 처리됩니다.

### 이미지 전용(스캔된) PDF

추출 가능한 텍스트가 없는 PDF 는 감지되어 `ocr_list_pdfs.txt` 에 추가됩니다. 플레이스홀더
(`[scanned PDF — OCR required]`)로 인덱싱되어 탐색에는 나타나지만, OCR 이 실행될 때까지
키워드나 의미 검색에는 매치되지 않습니다.

### 스캔 진행이 멈춘 것처럼 보임

로그를 확인하세요:
```bash
tail -f /var/log/docubrowser.log
# 또는
tail -f ~/.local/share/docubrowser/docubrowser.log
```

### Ollama 가 시작되지 않음

```bash
ollama serve                       # 수동 시작
ollama list                        # 두 모델이 모두 있는지 확인
ollama pull nomic-embed-text:latest              # 임베딩, 없으면
ollama pull dolphin3:latest                      # 요약 생성, 없으면
```

---

<a name="known-limitations"></a>

## 알려진 제한

[↑ 맨 위](#top)

| 제한 | 상태 |
|------------|--------|
| DRM 암호화 AZW 완전 검색 불가 | 메타데이터 인덱싱; 본문 텍스트에는 DeDRM_tools 필요 |
| 스캔된 PDF 검색 불가 | ocr_list_pdfs.txt 에 나열; OCR 보류 |
| 이미지 전용 DjVu 검색 불가 | 텍스트 레이어 없는 DjVu 는 메타데이터만 인덱싱; OCR 보류(스캔 PDF 와 동일) |
| 여러 최상위 문서 디렉터리 | 완전 지원 — 일반 패널에서 임의 개수의 추가 스캔 디렉터리 구성(`scan_dirs.txt`); `scan`/`rescan` 이 모두를 단일 공유 데이터베이스로 자동 스캔 |
| 이동/이름 변경 파일 | 이동으로 감지되지 않음 — 이전 경로는 제거되고(대화식 또는 `scan-missing` 으로) 새 경로는 다음 재스캔에서 새 항목으로 잡힘; 진짜 중복은 `duplist`/`dupclean` 이 잡음 |
| 숨김 파일/도트파일 미인덱싱 | 설계상 — 점 접두 경로 구성요소를 가진 모든 파일(`.env`, `.bashrc`, `.git/`/`.venv/` 같은 숨김 디렉터리 내용)은 스캔 시 건너뜀. **구버전**이 인덱싱한 도트파일은 재스캔으로 자동 제거되지 **않음**(파일이 디스크에 여전히 존재); 독립 `purge_dotfiles.py` 도구를 실행하거나 인덱스를 재구축하여 정리 |
| 인증 없음 | 로컬 사용 전용; 교차 오리진/CSRF/DNS 리바인딩에 강화([보안](#security) 참조)되어 있으나 네트워크 노출용은 아님 |
| 의미 *순위*는 문서 수준 | 전체 문서 임베딩이 *어느* 문서가 매치하는지 순위화; **딥 링크**가 그다음 임의 결과 *내부의 어디*를 온디맨드로 짚음. 코퍼스 전역 청크 수준 순위화는 향후 과제 |
| 혼합 언어 코퍼스 없음 | 한 설치는 하나의 언어를 제공(영어·일본어·한국어, 설치 시점 또는 설정에서 선택); 문서 단위 언어 감지나 혼합 언어 코퍼스는 미지원. [언어](#languages) 참조 |
| PII 감지는 미국 패턴 전용 | `purge_pii.py` 는 미국 형식(SSN, 전화 등)을 감지; 일본 "마이넘버" 및 기타 비미국 PII 패턴은 아직 미구현 |
| ETA 표시가 높게 드리프트 | 단순 평균 사용; 슬라이딩 윈도 보류 |

---

<a name="recent-changes"></a>

## 변경 이력

[↑ 맨 위](#top)

## v1.5.0 (2026-09-11) — 한국어 지원 + UI 전체 현지화

DocuBrowse 를 이제 완전히 **한국어**로 실행할 수 있으며, 인터페이스 현지화가
완성되었습니다(검색 페이지와 설정 페이지). [언어](#languages)를 참조하세요.

- **한국어(`ko`).** 전체 언어 스택: `bge-m3` 임베딩, `exaone3.5` 요약, 한글 문자
  바이그램 키워드 검색, 완전한 한국어 UI 번역(`locales/ko.json`).
- **한국어 자모 인덱스 바.** 한글은 진정한 알파벳이므로 문서 목록 인덱스 바가
  한국어에서 활성화되어 14 개의 기본 초성 ㄱ–ㅎ 으로 탐색합니다; 된소리는 기본
  자음으로 통합됩니다(ㄲ→ㄱ). 영어는 A–Z/0–9 바를 유지하고, 일본어에서는 바가
  숨겨진 채로 유지됩니다.
- **설정 페이지 전체 현지화.** 설정 페이지의 모든 레이블, 설명, 버튼, 자리표시자,
  상태 표시줄, 확인 대화상자, 토스트, 경고가 이제 현지화됩니다(영어/일본어/한국어).
- **CLI 에서 언어를 지정해 시작.** `docubrowser ko start`(또는 `docubrowser start ja`)로
  해당 언어로 서버를 시작하고, 선택을 `docubrowse.config` 에 저장합니다; 코드는 어느
  위치에 두어도 됩니다.
- **현지화된 메시지.** 요약 모달 오류, 문서/태그 카운터, 태그 분류(code/diagram/markup),
  맨 위로 버튼, 네트워크/오류 메시지가 이제 번역됩니다.
- **수정 사항.** 새 인스턴스의 "디렉터리 추가 오류"(빈 `work_dir` 줄이 더 이상 기본값을
  덮어쓰지 않음); CLI 가 이제 설정 UI 가 쓰는 것과 동일한 구성을 읽어 `scan` 이 구성된
  디렉터리를 대상으로 합니다; HTML 을 `no-cache` 로 제공하여 UI/현지화 변경이 항상 새로
  로드됩니다.

## v1.4.0 (2026-09-09) — 다국어 지원(일본어가 최초)

DocuBrowse 를 이제 완전히 제2 언어로 실행할 수 있습니다. [언어](#languages)를 참조하세요.

- **설치 단위 언어.** 한 설치는 하나의 언어를 제공합니다 — 인터페이스 문자열, 임베딩 모델,
  요약 모델, FTS 토크나이저가 모두 함께 선택됩니다. 오늘 영어(`en`, 기본)와 **일본어**
  (`ja`)를 지원하며, 언어 추가는 데이터 변경(`lang_models.py` 행 + `locales/<code>.json`)
  이지 새 코드가 아닙니다.
- **로컬라이즈 UI.** 모든 인터페이스 문자열은 언어별 로케일 파일(`locales/en.json`,
  `locales/ja.json`)에서 제공되어 클라이언트 측에서 해석됩니다; 활성 로케일은
  `GET /api/config` 로 함께 전달됩니다.
- **언어에 맞는 AI.** 일본어는 `bge-m3` 다국어 임베더와 일본어 요약 모델을 사용합니다;
  모델은 최초 실행 시(및 언어 전환 시) Ollama 에서 온디맨드로 풀되며, 아무것도 동봉되지
  않습니다.
- **CJK 키워드 검색**은 `unicode61` 토크나이저 위의 앱 측 문자 바이그램 분절(`trigram`
  아님)을 사용하므로, 2 문자 이상 일본어 용어(예: 2 문자 한자 복합어)가 확실히
  매치됩니다; 단일 문자 쿼리는 모두/의미로 드러납니다. 무의존이며, 중국어/한국어가
  도입될 때도 균일하게 적용됩니다.
- **언어 선택.** 새 설치에서 한 번 묻고(업그레이드는 절대 다시 묻지 않음 — 기존 `lang`
  보존), 이후 설정 톱니바퀴에서 전환(`POST /api/language`)하며, 새 언어에 맞게
  임베딩/인덱스를 재구축하려면 재스캔이 필요함을 경고합니다.
- **추론 모델 요약 수정.** 하이브리드 추론 요약 모델(예: 일본어 nemotron)이 더 이상 빈
  요약을 반환하지 않습니다; 대형 콜드 모델을 위한 요약 타임아웃도 상향되었습니다.

## v1.3.0 (2026-08-25) — 딥 링크 커버리지 + 의미 조정

- **훨씬 더 많은 형식의 딥 링크** — HTML, Markdown, EPUB/MOBI/AZW3, DjVu, SGML/XML
  계열, 이메일, JSON/YAML, 소스 코드, 기타 텍스트/마크업 형식이 이제 문서 내 구절 검색을
  지원합니다; 비산문(스프레드시트, 프레젠테이션, 다이어그램)은 해당 뷰어로 여는 방식으로
  대체됩니다.
- **의미 검색 조정** — 불필요어가 매치를 희석하지 않도록 임베딩 전에 관사와 접속사를 쿼리
  에서 제거합니다; 딥 링크는 의미 관련도 하한을 얻고 내용 없는 구절(주석 마커, 맨 숫자)을
  버리며, 대형 문서가 더 이상 타임아웃되지 않도록 의미 임베딩이 제한됩니다.
- **Enter 로 검색** — 입력 즉시가 아니라 Enter 를 누르면 검색이 실행됩니다; 입력란을
  비우면 모든 문서가 다시 표시됩니다.
- **도트파일 건너뜀(D-6)** — 점 접두 경로 구성요소를 가진 파일(`.env`, `.git/`, `.venv/`)
  은 더 이상 인덱싱되지 않습니다. 새 일회성 `purge_dotfiles.py` 도구가 구버전이 DB 에 남긴
  도트파일을 제거합니다(기본 드라이런).
- **문서** — 새 검색 팁과 요령 섹션; 따옴표 유무 구절 검색과 대소문자 무시를 명확화.

## v1.2.0 (2026-08-24) — 딥 링크

- **딥 링크 — 문서 내 구절 검색.** 임의의 키워드 또는 의미 결과에서 그 문서 *내부*의 매치
  구절을 찾고, 각각 위치 라벨(페이지 / 줄 / 섹션)과 함께 매치된 텍스트가 강조된 하나로
  점프합니다. 온디맨드 계산 — 재인덱싱도, 스키마 변경도, 새 의존성도 없습니다. 산문 형식:
  PDF, TXT, HTML, Markdown, DOCX, RTF, ODT, 전자책(EPUB/MOBI/AZW3), DjVu, 그리고
  SGML/XML 계열, 이메일, JSON/YAML, 소스 코드, 기타 텍스트/마크업 형식; 비산문은 뷰어로
  여는 방식으로 대체됩니다. 새 엔드포인트 `GET /api/deep-links`.
- **헤더 로고가 GitHub 의 프로젝트로 연결됩니다.**
- **수정:** `--db` / `--port` 가 이제 하위 명령 앞에 놓여도 존중됩니다
  (`docubrowser --db PATH start`) — 이전에는 조용히 무시되어 기본 데이터베이스가
  사용되었습니다.
- v1.0.3.1 에서 처음 배포된 **Intel Arc GPU 감지**(`xpu-smi`, `nvidia-smi` 폴백)와
  **tar 순회 복원 강화**를 포함합니다.

## v1.0.3 (2026-08-21) — 컨테이너 & 환경 설정

- **구성 가능한 Ollama 호스트** — `OLLAMA_HOST`(또는 `DOCUBROWSE_OLLAMA_HOST`)가
  임베더, 검색 서버, 전제 조건 검사기를 원격 또는 사이드카 Ollama 로 향하게 합니다. 맨
  `host:port` 도 허용되며 스킴은 `http://` 로 기본 설정됩니다. 기본값은
  `http://localhost:11434` 로 유지됩니다.
- **환경을 통한 경로/포트/DB** — `DOCUBROWSE_DOC_DIR`, `DOCUBROWSE_DB` /
  `DOCUBROWSE_DB_PATH`, `DOCUBROWSE_PORT`, `DOCUBROWSE_WORK_DIR` 이 설정 파일을
  덮어씁니다(환경이 파일을 무시; CLI 가 여전히 우선). 그래서 컨테이너가
  `docubrowse.config` 없이 실행될 수 있습니다. `GET /api/config` 도 이를 반영하며,
  `doc_search.py` 는 `DOCUBROWSE_DB` / `DOCUBROWSE_PORT` 만으로 시작할 수 있습니다.
- **옵트인 사설 네트워크 접근** — `DOCUBROWSE_TRUSTED_CIDRS` 와
  `DOCUBROWSE_ALLOWED_HOSTS` 가 사설 리버스 프록시 / BFF 가 루프백 전용 게이트를 지나 API
  에 도달하게 합니다. 신뢰 범위는 `/24`(IPv4) / `/120`(IPv6)로 제한되며 — `/32` 호스트가
  선호됩니다 — 그래서 우연한 `/8` 이 네트워크 전체에 미인증 API 접근을 부여할 수 없습니다.
  기본값은 루프백 전용으로 유지됩니다.
- **문서** — README, INSTALL, 관리자 가이드가 전체 환경 변수 집합과 신뢰 피어 보안 모델을
  문서화; 반복 가능한 종단 간 기능 테스트(`test_features.py`)와 테스트 노트가
  추가되었습니다.

## v1.0.2 (2026-08-19) — DjVu 와 ODF 템플릿

- **DjVu 지원**(`.djvu`/`.djv`) — **DjVuLibre**(`djvutxt`/`djvused`, 선택적 외부 도구)를
  통한 텍스트 레이어 추출. 없으면 DjVu 파일은 메타데이터만 인덱싱되고 경로가
  `djvu_missing_djvulibre.txt` 에 기록됩니다; DjVuLibre 설치 후 재스캔하면 본문 텍스트가
  잡힙니다. 텍스트 레이어 없는 이미지 전용 DjVu 는 메타데이터만 인덱싱됩니다(OCR 보류,
  스캔 PDF 와 동일).
- **ODF 템플릿 지원**(`.ott`/`.ots`/`.otp`) — OpenDocument 템플릿 변형이 이제 기존 ODF
  추출기를 통해 인덱싱되며, mimetype 접두어로 해당 텍스트/스프레드시트/프레젠테이션
  핸들러에 라우팅됩니다. 새 의존성 없음.
- **패키징** — `djvu_extractor.py` 가 모든 패키징 매니페스트(RPM, DEB, tarball, Windows,
  macOS)에 추가되었습니다.

## v1.0.0 (2026-07-23) — 기능 완성 마일스톤

DocuBrowse 가 v1.0.0 에 도달합니다: 기능 완성, 프로덕션 테스트 완료, 세 데스크톱 플랫폼
모두에 패키징. 이 릴리스는 MVP(v0.1.0)에서 형식 확장, 보안 강화, 코드 품질에 이르는 7 주
개발의 정점을 표시합니다.

- **15 개 추출기 모듈에 걸친 40 개 이상 지원 파일 형식** — PDF, DOCX, PPTX, XLSX, ODF,
  Visio, draw.io, SGML/XML 계열, 이메일, RTF, CSV/TSV, EPUB, MOBI, AZW, HTML, Markdown,
  LaTeX, reST, AsciiDoc, 설정 계열 일반 텍스트.
- 모든 28 개 Python 소스 파일에서 **Pylint 10.00/10**.
- **Python 3.9 ~ 3.14 테스트** — Python 3.14 의 더 엄격한 키워드 인자 처리 수정 포함.
- **Linux**(RPM, DEB, tarball), **Windows**(zip), **macOS**(dmg) 패키징.
- **보안 강화** — CSRF 보호, Host 헤더 허용 목록, 미인증 GET 변경 없음, SSN/CC/라우팅 번호
  검증이 있는 PII 감지.
- **AI 기반** — 의미 검색, 하이브리드 키워드+의미 모드, 온디맨드 AI 요약 생성, 모두
  Ollama 를 통해 로컬에서 실행.

---

## v0.9.3 (2026-07-17)

### 형식 확장 — 다이어그램, 마크업, 이메일, RTF, CSV, 설정 계열 텍스트

대규모 커버리지 향상. 다섯 개의 새 추출기 모듈에 걸쳐 40 개 이상의 새 파일 확장자를
추가하며, 가능한 한 순수 Python / 표준 라이브러리입니다.

- **Visio & 다이어그램** — 새 `visio_extractor.py` 가 최신 Visio(`.vsdx`/`.vsdm`), 레거시
  바이너리 Visio(`.vsd`/`.vss`/`.vst` — 본문 텍스트에 선택적 `libvisio-tools` 필요;
  없으면 메타데이터만으로 저하), draw.io / diagrams.net(`.drawio`/`.dio` — 일반 및 압축
  (deflate + base64 + URL 인코딩) mxfile 변형 모두)을 처리합니다. 도형 텍스트, 페이지
  이름, 핵심 속성 캡처. PlantUML(`.puml`/`.plantuml`)과 Mermaid(`.mmd`) 소스는 텍스트로
  인덱싱되고 `diagram` 태그가 붙습니다.
- **SGML/XML 마크업 계열** — 새 `markup_extractor.py` 가 `.xml`/`.xhtml`/`.sgml`/`.sgm`,
  DocBook(`.docbook`/`.dbk`), SVG(역시 `diagram` 태그), Visio 2003 XML(`.vdx`, `diagram`
  태그), 피드(`.rss`/`.atom`/`.opml`), reStructuredText(`.rst`),
  AsciiDoc(`.adoc`/`.asciidoc`), LaTeX(`.tex`/`.latex`)를 처리합니다. 공통
  로컬 네임(`<title>`, `<dc:title>`, `<author>`, `<dc:creator>`)에서 제목/저자를 탐지하는
  스키마 무관 태그 제거. 표준 라이브러리만 사용.
- **이메일, RTF, 표 형식** — 새 `eml_extractor.py`, `csv_extractor.py`,
  `rtf_extractor.py`. 이메일(`.eml`)은 표준 라이브러리 `email` 패키지를 통해(Subject →
  제목, From → 저자, To/Cc/Date → 주제 필드, 일반 또는 태그 제거 HTML 본문). CSV/TSV 는
  표준 라이브러리 `csv` 를 통해 구분자 자동 탐지 및 BOM 안전 읽기; 헤더 행 → 설명. RTF 는
  선택적 `striprtf`(`requirements.txt` 에 추가)를 통해; 없으면 `rtf_missing_striprtf.txt`
  사이드카와 함께 메타데이터만으로 저하 — `visio_legacy_missing.txt` 패턴을 반영.
- **설정 계열 일반 텍스트** — `.ini`, `.conf`, `.cfg`, `.log`, `.lst` 가 기존 텍스트
  경로를 통합니다.
- **태그 지정** — 모든 다이어그램 파일에 `diagram` 태그; 모든 마크업 파일에 `markup`
  태그. 자동 키워드 태그 생성이 모든 새 형식을 다루도록 확장됨.
- **CLI** — 30 개 이상의 새 `_TYPE_MAP` 항목으로 `scan vsdx drawio eml rtf` 등이 모두
  자연스럽게 동작.
- **새 사이드카 파일**(gitignore, 정보용): `visio_legacy_missing.txt`,
  `rtf_missing_striprtf.txt`.

### 코드 품질 — pylint 10/10 + Python 3.14 호환성

- **모든 28 개 Python 소스 파일이 pylint 10.00/10** — 미사용 임포트, 누락 docstring, 광범위
  예외 캐치, 줄 길이, 명명 규칙을 다루는 두 번의 정리 패스. 동작 변경 없음.
- **Python 3.14 호환성 수정** — Python 3.14 는 `_` 접두 파라미터를 다른 키워드 이름으로
  전달할 수 없도록 강제합니다. `scan_docs.py` 와 `embed_docs.py` 가
  `wait_for_memory(is_tty=...)` 를 호출했지만 함수는 `_is_tty` 를 정의합니다. 수정됨 —
  스캔이 Python 3.14+ 에서 더 이상 크래시하지 않습니다.

## v0.9.2 (2026-07-13)

### 버그 수정

- **끊어진 심링크와 권한 오류가 더 이상 스캔을 크래시시키지 않음** — 디렉터리 순회 중
  `is_file()` 및 `stat()` 호출이 이제 `OSError` 를 전파하지 않고 캐치합니다. 영향받은 코드
  경로: 사전 스캔 파일 수, `report` 명령, `scan_docs.py` 의 주 파일 수집, 두 데이터 그루밍
  중복 제거 스크립트. 접근 불가 항목(끊어진 심링크, ext4 로 복사된 NTFS 정션/reparse
  포인트, sshfs/네트워크 마운트의 권한 거부 경로)은 건너뛰고 요약 출력에서 집계됩니다.

---

## v0.9.2 (2026-07-09)

### OpenDocument 형식 지원

- **ODF 스캔** — `.odt`(텍스트), `.ods`(스프레드시트), `.odp`(프레젠테이션) 파일이 이제
  인덱싱됩니다. 추출은 Python 표준 라이브러리(`zipfile` + `xml.etree.ElementTree`)만
  사용 — 추가 의존성 불필요. 메타데이터(제목, 저자, 주제, 설명, 키워드)는 `meta.xml` 에서
  읽고; 본문 텍스트는 단락, 제목, 목록, 표, 슬라이드 프레임에 대한 완전한 네임스페이스
  처리로 `content.xml` 에서 추출됩니다.
- **버전 상향** — 모든 패키징 파일이 0.9.2 로 갱신됨.

### 버그 수정

- **관련도 점수 100% 상한** — 하이브리드 검색 병합 공식
  `max(fts, sem) + 0.1 × min(fts, sem)` 은 키워드와 의미 점수가 모두 높을 때 1.0 을
  초과하여 100% 를 넘는 관련도 백분율을 만들 수 있었습니다. 이제 1.0 으로 클램프됩니다.

---

## v0.9.0 (2026-07-05)

### 네이티브 패키징 및 Windows 지원

DocuBrowse 가 이제 네이티브 설치 프로그램과 함께 Linux 및 Windows 용으로 패키징됩니다.

- **RPM, DEB, tarball, Windows zip 패키지** — `build_packages.sh` 가 Linux 패키지를,
  `build_windows_zip.sh` 가 Windows zip 을 생성합니다. Linux 는 Python 가상환경과 함께
  `/opt/docubrowser/` 에, CLI 래퍼가 `/usr/bin/docubrowser` 및 `/usr/bin/docuback` 에,
  데스크톱 메뉴 항목이 Office 아래에 설치됩니다. Windows 는 시작 메뉴 바로 가기와 함께
  `%USERPROFILE%\DocuBrowse` 에 설치됩니다(관리자 불필요).
- **Windows 설치 프로그램** — `Install.bat` / `install.ps1` 이 Python 을 감지하고,
  가상환경을 만들며, 의존성을 설치하고, 시작 메뉴 바로 가기를 만듭니다. `Uninstall.bat` 이
  모든 것을 되돌립니다.
- **크로스 플랫폼 경로 추상화** — 새 `platform_paths.py` 가 모든 런타임 경로 선택(PID 파일,
  로그 파일, 백업 디렉터리)과 프로세스 관리(kill, find-by-script, kill-port)를
  중앙화합니다. Linux 경로는 변경 없음; Windows 경로는 `%USERPROFILE%\DocuBrowse\` 사용.
- **Windows 호환성** — 모든 Unix 전용 구성(`resource`, `SIGALRM`, `os.killpg`, `/proc`
  접근)을 플랫폼 검사 뒤로 가드했습니다. 프로세스 관리는 Linux 의 `/proc` 폴백과 함께
  `psutil` 을 사용합니다.
- **백업/복원** — `backup_restore.py` 가 Windows 권한 검사(`IsUserAnAdmin`)를 지원하고
  누락된 `pwd` 모듈을 우아하게 처리합니다.
- **데스크톱 메뉴 항목** — `.desktop` 파일이 모든 데스크톱 환경에서 신뢰할 수 있는 터미널
  실행을 위해 `xdg-terminal-exec` 를 사용; Office 아래로 분류됨.
- **Systemd 서비스 파일** — Linux 의 시스템 수준 배포용으로 포함됨.
- **dist/ 정리** — 빌드 스크립트가 형식별 최신 2 개 릴리스만 유지.
- **macOS dmg 설치 프로그램** — `packaging/macos/build_macos_dmg.sh` 가 더블 클릭 가능한
  `Install.command` / `Uninstall.command` 스크립트와 함께 dmg 를 생성합니다. Python
  가상환경, CLI 래퍼, 그리고 아이콘이 sips/iconutil 로 `icons/icon-512.png` 에서 생성되는
  `DocuBrowse.app` 런처와 함께 `~/Applications/DocuBrowse/`(앱 자체에는 sudo 불필요)에
  설치됩니다.

### v0.8.4 (2026-07-02)

### 코드베이스 정리 및 단순화

FOSS 릴리스의 일부였던 적이 없는 미사용 코드 경로와 실험적 기능을 제거하여, 더 깔끔하고
집중된 코드베이스를 남깁니다.

- **더 가벼운 서버** — `doc_search.py` 가 약 300 줄 감소; 개발 중 누적된 미사용 네트워크
  설정, 프로토콜 협상, 핸들러 코드를 제거.
- **더 가벼운 CLI** — `docubrowser.py` 가 약 240 줄 감소; localhost 애플리케이션에 적용되지
  않는 `setup-tls` 명령과 관련 헬퍼를 제거.
- **오래된 파일 제거** — 프로덕션에서 사용된 적 없는 `branding.json.example` 및 기타 개발
  전용 파일 삭제.
- **문서 갱신** — README, INSTALL, 아키텍처 노트를 현재 기능 집합을 정확히 반영하도록 정리.

---

## v0.8.3.1 (2026-06-28)

### 태그 기반 가시성 컨트롤로 문서 표시, 숨기기, 숨김 해제

- **문서를 화면에서 숨기기** — 각 카드에 이제 문서를 "hidden" 으로 태그하고 목록에서
  흐리게 하는 🙈 숨기기 아이콘이 있습니다. 숨긴 문서는 데이터베이스에 남아 언제든 복원할 수
  있습니다.
- **"Show 🙈" 토글 버튼** — 모든 뷰(모든 문서, 문자 필터, 검색 결과)에서 페이지 수 옆에
  추가됨. 클릭하면 숨긴 모든 카드를 일반 카드와 함께 드러내며; 버튼 라벨이 "Hide 🙈" 로
  바뀌어 다시 끕니다.
- **숨김 해제(👀) 아이콘** — 숨긴 카드가 보일 때 🙈 대신 👀 아이콘을 표시합니다. 클릭하면
  서버 측에서 "hidden" 태그를 제거하고, 아이콘을 🙈 로 되돌리며, 카드에서 "hidden" 태그
  칩을 제거합니다.
- **새 API 엔드포인트: `POST /api/remove-tag`** — 문서에서 단일 태그를 제거합니다.
  파라미터: `path`(URL 인코딩 파일 경로), `tag`(태그 이름). 갱신된 태그 목록을 반환합니다.
  CSRF 보호.
- **카드 동작 아이콘 재스타일** — 모든 아이콘(📋 🔖 🙈 ❌)이 이제 완전 불투명의 단색 컬러
  이모지를 사용합니다. 다크 모드에서 더 이상 흐리거나 어두운 아이콘이 없습니다.
[↑ 맨 위](#top)

## v0.8.3 (2026-06-27)

### UI 개편, 검색 수정, 스캔 개선

- **다크 & 라이트 모드 팔레트 재설계** — `data-theme` 속성 전환이 있는 새 CSS 변수 테마.
  다크 모드는 시안, 오렌지, 바이올렛 강조와 함께 깊은 네이비/퍼플 톤을 사용합니다. 라이트
  모드는 가독성을 위해 어둡게 한 강조 변형과 함께 깨끗한 흰색을 사용합니다. 태그 색상은
  `nth-child` 셀렉터로 다섯 개의 뚜렷한 색조를 순환합니다. 점수 배지, 모드 버튼, 동작 버튼이
  모두 새 팔레트를 사용합니다.
- **휴지통 아이콘이 이제 즉시 삭제하는 대신 4 옵션 모달을 엽니다**:
  (1) 인덱스에서만 제거(파일은 디스크에 남아 다음 실행에서 재스캔),
  (2) 제거 & 블랙리스트(파일은 남고 향후 스캔에서 건너뜀),
  (3) 제거 & 디스크에서 파일 삭제(이중 확인 포함),
  (4) 취소.
  서버 API 갱신: `POST /api/delete?path=...&mode=db_only|blacklist|delete_file`
  (하위 호환을 위해 기본값 `db_only`).
- **"both" 모드 검색 점수화 수정** — 키워드 매치가 이전에는 수천 개의 낮은 유사도 의미
  결과 아래에 묻혔습니다. 이제 의미 하한(`SEM_FLOOR=0.30`)을 적용하고 키워드 전용 히트를
  0.3 으로 제한하던 가중 평균 대신 `max(fts, sem)` 점수화를 사용합니다.
- **`scan` 명령이 이제 기본으로 임베딩**(`rescan` 과 동일) — 새 설치가 처음부터 동작하는
  의미 검색을 얻습니다. 옵트아웃을 위한 `--no-embed` 와 `--embed-workers` 플래그 추가.
- **보안 강화** — `/api/synopsis` 에 CSRF 보호 추가; 클라이언트로의 예외 누출 억제.

---

## v0.8.2 (2026-06-27)

### UI: 열기 버튼, CLI 개선

- **열기 동작 버튼**이 각 결과 카드의 기존 클릭 가능한 파일 경로 링크를 대체합니다 —
  `xdg-open` 으로 기본 앱에서 파일을 실행합니다.
- **버튼 스타일** 갱신 — 버튼이 이전의 어둡고 회색 외형을 대체하여 채워진 호버 상태와 함께
  강조 색 테두리와 텍스트를 사용합니다.

---

## v0.8.1 (2026-06-14)

### 버그 수정: 오래된 예제 데이터베이스 스키마

- **`du-docs.db.example` 재생성** — 현재 스키마로; 새 설치가 첫 페이지 로드에서 더 이상
  HTTP 500("no such column: d.subject")을 만나지 않습니다. 기존 예제는 더 오래된
  스키마(author/subject/synopsis 열 이전, 완전 FTS5 인덱스 이전)로 빌드되어 지연
  마이그레이션이 첫 검색 요청과 경합했습니다. 새 예제는 처음부터 올바른 스키마를 가집니다.

---

## v0.8.0 (2026-06-13)

### 설정 페이지, 알파 인덱스 바, 멀티 루트 스캔
- **설정이 독립 페이지로 이동**(`/settings`, 톱니바퀴 아이콘으로 새 탭에서 열림) — 기존
  모달을 대체. 전체 너비 레이아웃, 설정을 저장하고 검색 탭으로 돌아가는 헤더 "Done" 버튼,
  재설계된 무시 디렉터리 패널(설명 텍스트, "Add a directory to exclude" 행, "Currently
  excluded directories" 목록과 인라인 ✕ 제거 버튼, 추가 시 정리 전 확인 및 제거 시 재스캔
  알림).
- **알파 인덱스 바(0-9, A-Z)가 이제 진정한 전역 필터** — 문자를 클릭하면 (로드된 페이지뿐
  아니라) *모든* 매치 문서에 대해 `/api/search?letter=X` 를 쿼리하며, 기존 페이지 크기
  기본 설정으로 페이지네이션됩니다; 필터된 동안 Next/Back 과 페이지 크기 변경이 동작하고,
  활성 문자를 다시 클릭하면 모든 문서로 돌아갑니다. "Home" 버튼("0-9" 왼쪽)은 어디서든 모든
  문서로 돌아가며, 인덱스 바는 이제 모든 뷰(모든 문서, 문자 필터, 검색, 페이지네이션)에서
  유지됩니다.
- **여러 문서 디렉터리가 완전 자동으로 확인됨**: `resolve_doc_dirs()` 가 구성된 docPath 와
  `scan_dirs.txt` 를 하나의 순서 있는 목록으로 통합; `scan`/`rescan` 이 모든 디렉터리를 단일
  공유 데이터베이스로 순회하고 끝에 임베딩을 한 번 실행 — 수동 디렉터리별 재스캔 불필요.
- 헤더 통계 바에서 "N embedded" 수를 제거(이제 "N docs · N tags").
- `index.html` 의 `friendlyError()` 헬퍼가 페이지가 로드된 동안 서버가 다운되면 (일반
  네트워크 오류 대신) 명확한 "Cannot reach the DocuBrowse service" 메시지를 제공 — 검색,
  필터, 페이지네이션, 요약, 열기, 삭제에 적용.
- 요약 모달의 "Generating synopsis..." 메시지가 이제 6s/25s 에 안심시키는 텍스트로
  갱신되어, 느린 콜드 스타트 Ollama 요청(최대 약 90s)이 멈춘 것처럼 보이지 않습니다.

### 기본 doc_dir 없음, 설정 배너, uninstall.sh
- `doc_dir`/`docPath` 가 더 이상 `~/Documents` 로 기본 설정되지 않음 — 구성되지 않은 문서
  디렉터리가 이제 CLI(`docubrowser.py`), API(`doc_search.py` `/api/config`),
  `install.sh` 의 생성된 설정 전반에서 유효한 상태입니다.
- 문서 디렉터리가 필요한 CLI 명령(`rescan`, `report`, `scan`)이 이제 구성된 것이 없으면
  설정 톱니바퀴, `docubrowse.config`, `--doc-dir` 을 가리키는 명확한 오류로 종료됩니다.
- `index.html` 이 `/api/config` 가 빈 `docPath` 를 보고할 때마다 배너 — "No document
  directory configured yet. Click the Settings (gear) icon..." — 를 표시합니다.
- `install.sh` 의 사용자/시스템 모드 감지를 반영하는 `uninstall.sh` 추가: systemd 유닛
  중지/비활성화/제거, CLI 래퍼 및 설치 디렉터리 제거, pid/log 파일 정리, 그리고 (시스템
  모드, 별도 확인) 전용 `docubrowse` 사용자/그룹 제거 가능.

### 설치 프로그램
- **설치 프로그램:** 깔끔한 사용자 대 시스템 분리로 재작성된 `install.sh`/`uninstall.sh` —
  사용자 모드는 `~/.docubrowse`(자체 venv, `~/.local/bin/docubrowser` 래퍼, root 없음,
  systemd 없음)에 설치; 시스템 모드는 (자동 활성화되지 않는) `docubrowser.service`
  systemd 유닛과 `/usr/local/bin/docubrowser` 래퍼와 함께 전용 `docubrowse` 사용자로
  `/opt/docubrowse` 에 설치.
- **사전 점검:** 설치 프로그램이 모든 전제 조건을 사전에 검증(python3 ≥ 3.9 +
  venv/ensurepip, rsync, curl, tar, calibre, ollama, 시스템 모드에서는
  getent/useradd/groupadd/systemctl)하고, 변경을 가하기 전에 누락된 모든 것을 한 번에
  보고합니다.
- **CLI:** 런처가 이제 `docubrowser` 명령(`.py` 없음)으로 설치됩니다.
- **requirements.txt** 추가 및 `pip install -r requirements.txt` 로 설치 — 이제
  pdfplumber, pypdf, python-docx, ebooklib, beautifulsoup4, mobi 와 함께 이전에 누락된
  의존성(numpy, python-pptx, openpyxl)을 포함합니다.
- **새 설치는 비어서 시작:** `du-docs.db.example` 이 이제 비어서 배포되므로, 새 설치는
  인덱싱된 문서 없이 시작합니다.
- **여러 문서 디렉터리:** 설정이 이제 단일 "Document directories" 목록을 표시(기존 별도
  docPath + "additional directories" 패널이 병합됨). `rescan`/`scan` 이 나열된 **모든**
  디렉터리를 인덱싱; 명시적 `--doc-dir` 은 여전히 하나만 대상으로 합니다. `doc_dir` 은 이제
  선택 사항입니다.

### 보안 & 안정성 강화
전체 코드 품질 + 보안 감사의 개선(세부 사항은 `status_docs/DECISIONS.md`). 하이라이트:
- **보안:** Host 헤더 허용 목록(DNS 리바인딩 방지); `/api/delete` 와 `/api/open` 이
  POST 로 이동하여, POST 설정/디렉터리 라우트 및 `/api/browse` 와 함께 프로세스별 CSRF
  토큰 + 루프백 오리진으로 게이트됨; 저장형 XSS 벡터 차단(data-attribute + 위임 리스너);
  PII 정리가 이제 SSA 규칙 + Luhn/IIN 으로 검증.
- **검색:** 키워드 경로가 이제 FTS5 `bm25()` 인덱스를 사용하고 의미 점수화가 요청마다 전체
  코퍼스를 로드하는 대신 캐시된 NumPy 임베딩 행렬을 사용(키워드 약 4ms, 모두 약 55ms);
  서버 측 의미 검색 수정(조용히 아무것도 반환하지 않았음).
- **안정성:** `INSERT … ON CONFLICT` 업서트(재인덱싱이 더 이상 태그/임베딩/요약을 지우지
  않음); 워커 사망 "suspect isolation" 이 진짜 원인만 블랙리스트; 스키마 초기화가 프로세스당
  한 번 실행; 스캔/임베딩이 약 2s 시간 예산에 커밋하여 서버가 차단되지 않음; `dupclean` 이
  주 경로에서 더 이상 디스크/DB 를 손상시키지 않음; 정밀한 `/proc` 기반 워커 종료; 단일
  공유 문서 삭제 헬퍼; 다양한 중/저 수정.
- **UI:** 페이지네이션 Back/Next 가 모든 페이지 크기에서 올바름; 더 새로운 검색이 이제
  진행 중인 페이지 로드를 대체(오래된 결과 없음).

### 이동/누락/삭제된 문서 처리
- `/api/open` 이 이제 더 이상 존재하지 않는 파일에 대해 일반 오류 대신
  `{"ok": false, "error": "missing"|"unmounted", "message": ...}` 를 반환합니다.
- UI 가 `missing` 파일에 대해 닫을 수 있는 모달을 표시(닫을 때 인덱스에서 제거)하거나,
  `unmounted` 파일에 대해 토스트를 표시(파일시스템을 확인할 수 없음, 인덱스 변경 없음).
- 새 옵트인 `scan-missing [--dry-run]` CLI 명령이 `unmounted` 행을 건드리지 않고 전체
  인덱스에서 `missing` 행을 배치 정리합니다.

### v0.7.2.1 — 버그 수정
- "파일 열기"(`/api/open`)가 조용히 아무것도 하지 않던 문제 수정 — 서버 환경에
  `DBUS_SESSION_BUS_ADDRESS`/`DISPLAY`/`XAUTHORITY`/`XDG_RUNTIME_DIR` 이 없어
  `xdg-open` 이 기본 앱을 실행하지 않고 성공으로 종료했습니다. `handle_open` 이 이제
  데스크톱 세션 환경을 재구성하고 신뢰할 수 있는 실행을 위해 `gio open` 을 선호합니다.

---

<a name="roadmap"></a>

## 로드맵

[↑ 맨 위](#top)

### Phase 2b — 형식 확장 ✅ 완료
- ✅ DOCX 추출기(python-docx)
- ✅ EPUB/MOBI/AZW3/AZW 추출(ebooklib + Calibre)
- 확장자 없는 파일 분류(매직 바이트)
- 10K+ 문서로 확장

### Phase 2 — 정리 ✅ 완료
- ✅ `duplist` / `dupclean` — 정확 + 근사 중복 감지 및 대화형 정리
- ✅ 설정 UI 를 통한 설정 읽기/쓰기(port, docPath, workDir)
- 진행률 바를 위한 슬라이딩 윈도 ETA
- 검색 UI 의 파일 형식 필터

### Phase 3 — 마무리
- 설정 지속성
- 고급 필터링(날짜 범위, 형식, 저자)
- 결과 내보내기(CSV/JSON)
- 스캔 PDF 를 위한 OCR 통합

### Phase 3+ — 고급
- API 키 인증
- 문서 유사도 클러스터링
- Docker 배포

---

<a name="ai-assisted-development"></a>

## AI 지원 개발

[↑ 맨 위](#top)

DocuBrowse 는 Claude 를 능동적 코딩 파트너로 삼아 개발됩니다. 전체 맥락으로 세션을
재개하려면 시작 시 다음 파일을 로드하세요:

| 파일 | 내용 |
|------|---------|
| `.claude/CLAUDE.md` | 프로젝트 규칙, 주요 파일, 힘겹게 얻은 교훈 |
| `status_docs/project_status.md` | 버전, 세션 이력, 진행 중인 작업 |
| `status_docs/DECISIONS.md` | 보류된 결정, 알려진 문제, 근거 |

```bash
# 임의의 AI 어시스턴트에 복사/붙여넣기용으로 세 파일 모두 출력
cat .claude/CLAUDE.md status_docs/project_status.md status_docs/DECISIONS.md
```

---

<a name="license"></a>

## 라이선스

[↑ 맨 위](#top)

GNU General Public License v3.0 이상(GPL-3.0-or-later).

Copyright (C) 2026 James Sparenberg

[LICENSE](LICENSE) 또는 https://www.gnu.org/licenses/gpl-3.0.html 를 참조하세요.

---

**DocuBrowse v1.5.0** — 빠르고, 로컬이며, AI 기반인 문서 검색.
