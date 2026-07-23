# 프로젝트 상태 — 인도네시아 언론 온라인스캠센터 보도 코퍼스

> CLAUDE.md가 연구 설계·파이프라인 규칙(정적 브리프)이라면, 이 문서는 "지금 코퍼스가 어디까지 왔는지"를
> 세션 간 이어서 확인하기 위한 상태 스냅샷이다. 작업할 때마다 갱신한다.

마지막 갱신: 2026-07-23 · 최종 커밋 `39d8904`

---

## 1. 현재 코퍼스 상태

| 항목 | 값 |
|---|---|
| `data/corpus.jsonl` 총 레코드 | **518건** |
| — 발견 확장 유래(WebSearch site: 검색 3회차 + 태그페이지) | 398건 |
| — `seeds/existing_120.csv` 유래 | 120건 (**병합 완료**) |
| article_id 유일성 | **518/518 유일, 중복 0건** (검증 완료) |
| article_id 형식 | `PREFIX-NNNN` (예: `ANT-0001`, `DET-0042`) — outlet_key 3글자 접두 + 0패딩 4자리 |
| access_status 분포 | 본문추출_자동 502 / 검수필요 16 / 접근 제한 0 (S002 재시도 성공 반영) |
| relevance_flag=='포함' & access_status=='본문추출_자동' (실제 코딩 후보) | 418건 |
| GitHub 레포 | `github.com/iamrealdragon/scam-corpus` (private) |
| 대시보드 | `dashboard.py` (Streamlit Community Cloud 배포, "Deploy a public app from GitHub"로 연결) |

seed 120건은 fetch 전 corpus.jsonl과 URL 대조 결과 **겹침 0건**이었고(발견 확장 라운드가 seed URL을
후보에서 제외하기만 했지 실제로 fetch한 적은 없었음), 전량 신규 fetch → **병합 완료, 518건**.

---

## 2. 완료된 작업 → 해결한 결함

| 결함 | 발견 경위 | 조치 |
|---|---|---|
| CLAUDE.md의 "Kumparan은 Playwright 필요" 가정 | outlets.yaml 라이브 검증 | 실측 결과 8개 매체 전부 정적 HTTP로 충분 확인, 가정 폐기 |
| 대시보드 `ValueError`/`KeyError` (pandas `value_counts().reset_index()` 컬럼명 어긋남) | Playwright 헤드리스 6페이지 검증 | `.rename_axis(name).reset_index(name=...)` 패턴으로 수정 |
| `discover.py` robots.txt 오판 (403 → 전체 차단으로 오판, 71건 스킵) | 발견 확장 1회차 실행 중 | 실제 크롤링 UA로 robots.txt 직접 fetch 후 parse하도록 수정 |
| `article_id` 130개 그룹 중복(같은 ID, 다른 URL) | 코퍼스 감사 중 발견 | 전체 재발번(`PREFIX-NNNN`, pub_date 오름차순), `legacy_article_id`로 구ID 보존 |
| `fetch.py` ID 발번이 seed CSV 최댓값 기준이라 회차마다 충돌 재발 | 위 중복 진단의 원인 추적 | `corpus.jsonl` 기존 ID 전체에서 다음 번호 발번 + 발번 직후 유일성 assert로 변경 |
| **`media_type`/`byline`/`content_hash`/`http_status` 필드 미채움** (마이그레이션 스크립트로 기존 398건에만 임시로 채워졌고, `fetch.py` 자체는 계속 안 채우고 있었음) | 스키마 감사 중 발견 | `extract.py`에 `classify_access_status()`(본문추출_자동/검수필요 통일 기준)와 byline 추출(ld+json author → meta → CSS 순) 추가, `fetch.py`가 이를 통해 4개 필드를 매 fetch마다 채우도록 수정 |
| **`event_cluster_candidate` → `event_cluster` 필드명 불일치** (corpus.jsonl은 이미 개명됐는데 `dedup.py`/`fetch.py`/`dashboard.py`는 옛 이름 참조 — 다음 fetch 때 재발할 상황) | 위와 동일 감사 | `dedup.py`/`fetch.py`/`dashboard.py` 세 곳 전부 `event_cluster`로 통일 |
| S002(Suara) fetch 실패(15초 타임아웃) | seed 병합 실행 결과 | 30초 타임아웃으로 재시도 → 성공, 레코드 in-place 갱신 |

---

## 3. 진행 중 / 미해결 과제

- [ ] **byline 필드 오탐 정정** (우선순위: 낮음 — tier2 확장 착수 전 처리 권장)
  - A유형(날짜/시각/WIB 패턴, 예: `"AntaraTerbit 20 Nov 2025 19:06 WIB"`): **TIR 6건** — TIR 전용 패턴
  - C유형(매체명이 사람이름 자리를 통째로 차지, 예: `"ANTARA News Agency"`, `"Antara"`): **ANT/DET/CNN 12건**
  - B유형(byline이 Facebook URL): **CNN 50건** — CNN 전체 59건 중 다수. 다음 tier2 확장 전에 `extract.py`의 CNN 셀렉터(byline 추출 로직) 점검 필요
- [ ] corpus.jsonl 필드가 CLAUDE.md 4번 정식 스키마와 완전히 1:1은 아님(`event_cluster`/`search_query`는 통일했으나 `search_query` 값 자체가 `"seed_merge"`/`"tag_page"`/`"websearch_site_query"` 같은 소스명이라 CLAUDE.md가 의도한 "검색어 문자열"과는 결이 다름 — 정리 필요)
- [ ] 사건군 후보(`event_cluster`, AUTO-XXX 다수) → 최종 `KH-XXX-YYYY` 코드로 사람이 확정
- [ ] relevance_flag=='review' 건 최종 배제 확인
- [ ] LLM 프리코딩(`precode/precode_llm.py`)은 아직 미착수 — 위 검토 마친 후 진행

### 완료된 것 (이전엔 여기 있었음)
- ~~기존 120건 fetch·병합~~ → **완료**. 최종 성공률 **120/120 (100%)**, S002는 30초 timeout 재시도로 해결.
  corpus_type 플래그 정상 부여 확인(기사 115 / 재게재_해외매체 3 / 팩트체크 1 / 영상물 1).
  seed_access_status 교차표 확인 완료 — 원래 "링크 확인(본문 미검증)" 14건 전부 fetch 성공, 생존 확인.

---

## 4. 다음 단계 순서

```
✅ outlets.yaml 검증 → ✅ extract.py 검증 → ✅ 발견 확장(3회차) → ✅ 스키마 정리·ID 재발번
  → ✅ 120건 병합 → ▶ tier2 확장(Kompas·Tribunnews·Republika·Media Indonesia·
    Sindonews·Viva·Okezone·JPNN) → 필터/사건군 최종 확정 → 프리코딩 → 코딩시트 → 신뢰도/분석
```

tier2 8개 매체는 아직 fetch_method 미검증 상태(`config/outlets.yaml`에 `unverified`로만 존재) —
착수 전 tier1 때와 동일한 라이브 검증(정적 HTTP 가능 여부·CSS 셀렉터) 필요.

---

## 백업 / 커밋 기록

| 백업 파일 | 시점 | 건수 |
|---|---|---|
| `data/corpus.backup.jsonl` | 2026-07-23 09:50 | 398 |
| `data/corpus.backup2.jsonl` | 2026-07-23 10:11 | 398 |
| `data/corpus.backup3.jsonl` | 2026-07-23 19:07 | 398 (seed 병합 직전) |
| `data/corpus.backup4.jsonl` | 2026-07-23 20:28 | 518 (S002 재시도 직전) |

최종 push 커밋: **`39d8904`** (`iamrealdragon/scam-corpus`, main)
