# CLAUDE.md — 인도네시아 언론 온라인 스캠센터 보도 내용분석 코퍼스 구축

> 이 파일은 Claude Code가 레포 루트에서 자동으로 읽는 프로젝트 브리프다.
> 목표: SSCI 투고용 내용분석을 위한 **코딩 가능한 코퍼스**를 최대 규모로 구축하고,
> LLM 1차 프리코딩 + 사람 검수 + Krippendorff's α 신뢰도까지 이어지는 파이프라인을 만든다.

---

## 0. 연구 개요 (판단 기준)

- 분석 대상: 인도네시아 국적자(WNI)의 동남아 온라인 스캠센터 편입을 다룬 **인도네시아어 뉴스 기사**.
- 분석 단위: **개별 기사 1건**.
- 이론 골격: Entman(문제정의·원인·책임·해결) + Iyengar(에피소드/주제) + 플랫폼 책임 가시화 + 강제범죄화.
- 방법론 템플릿: Meghan Sobel (2015 FGC; 2016 Thai sex trafficking) — 아카이브 기반 목적표집 + Krippendorff's α.
- 코딩 기준: `SSCI_온라인스캠센터_내용분석_3개국어_코드북.xlsx` 의 63개 변수(A~H). **이 코드북이 유일한 코딩 기준이다.**

## 1. 입력 자산 (레포에 배치)

- `seeds/existing_120.csv` — 이미 1차 코딩된 120건. 컬럼: ID, 발행일, 매체, 제목, 대상국, 출처URL, 사건군, 접근상태 등.
  - 이 중 "본문 확인"은 27건뿐. 나머지는 스니펫/링크 수준 → **본문 전량 재수집으로 승격**한다.
- `config/codebook.xlsx` — 3개국어 코드북(README, Codebook_KR/ID/EN, CodingSheet_KR/ID/EN, Method_Notes, Variable_Summary).
- `config/codebook_flat.json` — 코드북을 LLM 프리코딩용으로 평탄화한 파일(변수ID→허용코드값·정의·코딩규칙). **Claude Code가 xlsx에서 생성한다.**

## 2. 파이프라인 & 레포 구조

```
scam-corpus/
  config/     outlets.yaml  queries.yaml  codebook.xlsx  codebook_flat.json
  seeds/      existing_120.csv
  crawler/    discover.py  fetch.py  extract.py  filter.py  dedup.py
  precode/    precode_llm.py   review_sheet.py
  data/       raw_html/  corpus.jsonl  corpus.sqlite
  coding/     coding_sheet.xlsx        # CodingSheet 템플릿과 동일 컬럼, A~자동 / B~H는 프리코딩값+검수
  reliability/ alpha.py
  analysis/   freqs.py  crosstab.py  trends.py
  logs/       crawl_log.jsonl
```

빌드 순서(점진 검증): **outlets.yaml → 기존 120 재수집으로 추출기 검증 → 발견 확장 → 필터/중복/사건군 → 프리코딩 → 코딩시트 → 신뢰도/분석.**

## 3. 수집 전략 — 표본 최대화가 최우선

### 3.1 대상 매체 (config/outlets.yaml)
1차 코퍼스 매체: **ANTARA, Detik, CNN Indonesia, Liputan6, Tirto, Kumparan, CNBC Indonesia, Suara.**
표본 확장 후보(추가로 순회): **Kompas, Tribunnews, Republika, Media Indonesia, Sindonews, Viva, Okezone, JPNN.**
- ANTARA·Detik는 **지역판 서브도메인**이 태그에 안 잡힌다. 반드시 별도 시드로 추가: `jabar/megapolitan/sulteng/jateng/jambi/ambon…antaranews.com`, `detik.com/jogja`, `news.detik.com/bbc-world`(BBC Indonesia 재게재).

### 3.2 발견(Discovery) — 세 소스 병용
- (a) `seeds/existing_120.csv` 시드(재수집·골드셋).
- (b) 태그 페이지 **완전 페이지네이션**: `antaranews.com/tag/wni-online-scam`, `/tag/wni-di-myawaddy`, `detik.com/tag/wni-korban-online-scams`. 매체별 유사 태그를 추가 탐색.
- (c) 매체별 사이트검색 + 보조 `site:` 검색을 아래 쿼리셋으로 순회.
- 기간: **2022-01 ~ 현재**(2022-08 이전 기사도 있으면 포함; 최대화). `queries.yaml`의 기간을 파라미터화.

### 3.3 쿼리셋 (config/queries.yaml)
`WNI korban online scam Kamboja`, `WNI online scam Myanmar`, `lowongan kerja Kamboja admin online`, `operator komputer gaji Kamboja`, `WNI Myawaddy`, `korban TPPO scam`, `WNI dipulangkan scam`, `judi online WNI`, `perdagangan orang online scam` + 철자 변형 `scam/scamming/scammer/penipuan daring/penipuan online`.

### 3.4 수집(Fetch)
- **매체별로 정적 HTTP(requests) vs 헤드리스(Playwright)를 라이브로 검증해 결정**한다. 인니 주요 매체는 대체로 서버 렌더링이라 정적으로 충분하나, **Kumparan 등 JS 의존 매체는 Playwright**로 처리. (실행 환경: VS Code + Node/Playwright 사용 가능.)
- 예의 규칙: robots.txt 확인, 도메인당 요청 지연·지수 백오프·재시도, 식별 가능한 User-Agent.
- 다중 페이지: ANTARA `?page=all`, Detik 페이지 파라미터 등 **본문 전체 병합**.
- 실패(404·삭제·유료벽)는 파이프라인을 죽이지 말고 `access_status`에 기록하고 계속.

### 3.5 추출(Extract)
- 1순위: 매체별 CSS 셀렉터(제목·발행 datetime·본문·바이라인). **셀렉터는 라이브 페이지로 검증해 outlets.yaml에 저장.**
- 폴백: `trafilatura` → `newspaper3k`.
- 언어감지로 인니어만 통과(`lang`).

### 3.6 필터(Relevance)
- 포함기준: 본문에 **WNI(또는 orang Indonesia)** + [모집/이동/노동/폭력/송환/피해자-가해자 분류] 중 최소 1개.
- 애매하면 `relevance_flag = "review"`로 분리(삭제 금지) → 사람이 확인.

### 3.7 중복·사건군(Dedup / Cluster)
- URL 중복 제거.
- 근사중복: 제목 유사도 + (인원수·날짜·장소) 조합으로 **사건군 후보** 자동 부여. 기존 명명 규칙 유지: `KH-249-2026`(국가-사건-연도).
- **매체 간 중복·후속보도는 삭제하지 않는다.** 매체별 프레이밍 비교가 연구 핵심 → 사건군 태그로 묶기만 한다.

## 4. 데이터 스키마 (data/corpus.jsonl · corpus.sqlite)

```
article_id, outlet, media_type, pub_date, year, url, title, body_text, byline,
word_count, search_query, retrieved_at, http_status, access_status, content_hash,
event_cluster, lang, relevance_flag, raw_html_path
```
- `access_status ∈ {본문 확인, 검색결과 확인, 링크 확인, 접근 제한}`.
- A01~A12(메타데이터)는 이 스키마에서 자동 산출된다.
- 원본 HTML은 `data/raw_html/`에 보관(재추출·검증·프로비넌스용).

## 5. LLM 1차 프리코딩 (precode/precode_llm.py)

- **대상: `access_status == "본문 확인"` 인 기사만.** 스니펫만 있는 기사는 프리코딩 금지.
- 입력: `body_text` + `config/codebook_flat.json`(변수별 허용 코드값·정의·코딩규칙).
- 출력(변수별): 코드값(코드북 숫자코드) + `H03 근거메모` + `H01 원문 인용구(15단어 이내, 코드북 규칙)` + `H04 코더확신도(1높음/2중간/3낮음)`.
- 규칙:
  - 코드북에 없는 값 생성 금지, **기사에 실제로 나타난 표현만** 근거로. 배경지식으로 피해자성/가담자성 추정 금지.
  - 같은 기사에서 피해자성·가담자성이 동시에 나타나면 경계적 주체(C01=8)로.
  - 인용구는 짧게(저작권). 긴 본문 복제 금지.
  - LLM 확신도가 낮거나 프레임이 다중이면 `H04=3`으로 표시해 검수 우선순위를 높인다.
- 출력은 `coding/coding_sheet.xlsx`의 B~H 칸에 **프리코딩값**으로 채우고, 검수 컬럼(`reviewed_by`, `final_code`, `changed?`)을 추가한다.

## 6. 신뢰도 (reliability/alpha.py) — SSCI 방어 핵심

- **1차 앵커: 사람 코더 2인**이 전체의 **20~25% 층화무작위 표본**을 독립 코딩 → Krippendorff's α.
- 핵심·고추론 변수 우선: `B02 지배적 프레임`, `C01 주체명명`, `C02 피해자성`, `C05 TPPO 언급`, `D04 플랫폼 역할`, `F02 원인책임`, `F06 책임방향`.
- 명목변수는 nominal 수준으로 계산. Python `krippendorff` 패키지 사용.
- α < .667 변수 → 코드북 규칙 구체화 후 재코딩(피드백 루프).
- **추가 보고**: LLM 프리코딩값 vs 사람 최종코딩값의 일치도를 별도 산출(라벨 절감 효과의 투명한 근거). 단, 이 값은 사람-사람 α를 대체하지 않는다.

## 7. 분석 (analysis/)

- 빈도(변수별 분포), 교차표·카이제곱(매체×프레임, 연도×책임귀인 등), 연도 추이, **플랫폼 책임 가시화 갭**(D04/F05: 모집 경로로는 자주 등장하나 책임 주체로는 드문가) 분석.

## 8. 프로비넌스 · 윤리 · 저작권

- 모든 요청을 `logs/crawl_log.jsonl`에 기록(url, status, retrieved_at, query).
- robots.txt 준수, 레이트리밋 준수.
- 코퍼스 원문은 **분석 목적 저장**. 논문/산출물의 인용은 15단어 이내·출처 명시(코드북 H01 규칙).

## 9. 단계별 완료 정의 (Definition of Done)

1. **추출기 검증**: 기존 120건 중 접근 가능한 URL의 본문 추출 성공률 ≥ 90%, 27→가능한 최대치로 "본문 확인" 승격.
2. **발견 확장**: 태그·검색·서브도메인·확장 매체를 순회해 신규 기사 수집, 중복 제거 후 코퍼스 N 보고.
3. **프리코딩**: 본문 확인 기사 전량에 B~H 프리코딩 + 근거·확신도 채움.
4. **코딩시트**: CodingSheet 컬럼과 1:1 매핑된 `coding/coding_sheet.xlsx` 산출(A 자동 / B~H 프리코딩 / 검수 컬럼 포함).
5. **신뢰도**: 20~25% 표본 사람 2인 α + LLM-사람 일치도 리포트.

## 10. 주의 (하지 말 것)

- 스니펫만 있는 기사를 프리코딩하거나 "본문 확인"으로 승격하지 말 것.
- 매체 간 중복 기사를 삭제하지 말 것(사건군으로 묶기만).
- 코드북에 없는 코드값을 만들지 말 것.
- 코퍼스 원문을 산출물에 장문 복제하지 말 것.
