# 6.0A.1 검증 및 실행 기록

기준은 PR #12의 `d12d0fe758ea75957d84a98b9a491828bb848d1f`이다. `b01468f`에서 여섯 실험군·고정 반사실·측정 기준을 먼저 기록했다. `0f077518f998efdbb34494659641e4e605d51d52`에서 원조 정책, 국경 집행, 감사, 측정 계산과 실험 실행기를 고정했다. 이후 추가한 분석은 같은 원자료를 읽는다. [실험 계획](phase6a1-protocol.md) · [PR #14](https://github.com/mrgameskr-lang/civilization/pull/14)

## 원장과 단년 실험

저장소 루트에서 아래 모듈을 실행했다. 로컬 환경은 Windows, CPython 3.12.14다. 표의 원자료와 샘플 원장을 재생성할 때는 별도의 빈 출력 경로를 사용한다. 기존 결과를 확인하는 `verify`와 비교 기준인 `--verify-against`에는 아래의 공개 경로를 사용할 수 있다.

```sh
python -B -m civsim.aid61 run --arm F --seed 0 --years 4 --out samples/phase6a1/seed0-capped
python -B -m civsim.aid61 verify samples/phase6a1/seed0-capped
python -B -m experiments.aid_forks61 --out examples/phase6a1/forks-dev.json
python -B -m experiments.aid_forks61 --out ../../work/phase6a1-forks-repeat.json --verify examples/phase6a1/forks-dev.json
python -B -m experiments.replay_legacy61 --workers 8 --out examples/phase6a1/legacy-ab.json
python -B -m experiments.verify_archives31 --workers 3
```

| 실제 검사 | 결과 |
|---|---|
| 신규 F 시드 0의 4년치 원장 | 3,464,441바이트. 처음부터 재생한 연간 원장 SHA-256 `b5683aecfce60fce74cccedebb43305bcfede4675186db7bd9458778da322c6b` |
| 같은 연초 반사실 | 3쌍을 새 프로세스에서 다시 실행. 결과 파일 SHA-256 `2f488be43f5777db01b2d67cf7ad619c1db766d0d56e2dcff795ef7ff722bf93` |
| 6.0A 기존 A/B | 40시드 × 2군 × 200년을 재생해 초기 및 50·100·200년 누적 해시 240개 모두 일치 |
| 이전 버전의 저장 결과 | 기존 검증기로 국가 모형 280개 경로의 체크포인트 400개와 전체 예제 원장 9개 재생. 5.0D 원장 `c96297045b5475154e9a6e0cebd0b21a37e9ab6e883b2cd8fe6fcecdbd00c169`, 6.0A 원장 `d4ee8225688cde4dc82d967d450ca3f6f2f79769164e4762ee9583630de11507` |

[원조 포함 예제](../samples/phase6a1/seed0-capped) · [반사실 세 쌍](../examples/phase6a1/forks-dev.json) · [6.0A A/B 체크포인트 증빙](../examples/phase6a1/legacy-ab.json)

## 개발·검증 표본과 독립 반복

각 시드에서 A–F를 같은 기초 세계에서 200년 동안 실행했다. 50·100년 수치는 그 연속 경로의 중간 결산이다. 같은 고정 코드로 각 표본을 새 프로세스·새 출력 경로에서 다시 계산했다. 실행 영수증의 소요 시간과 원자료 파일 9개의 해시는 별도로 보관한다. 아래의 `../../work/`는 이 검증에서 사용한 별도 작업 디렉터리다.

```sh
python -B -m experiments.phase6a1 --sample dev --workers 5 --out examples/phase6a1/study/dev
python -B -m experiments.phase6a1 --sample holdout --workers 5 --out examples/phase6a1/study/holdout
python -B -m experiments.phase6a1 --sample dev --workers 5 --out ../../work/phase6a1-repeat-dev --verify-against examples/phase6a1/study/dev
python -B -m experiments.phase6a1 --sample holdout --workers 5 --out ../../work/phase6a1-repeat-holdout --verify-against examples/phase6a1/study/holdout
```

| 표본 | 본실험 | 새 프로세스 반복 | 실험군 × 시드 × 연도 (각 실행) | 일치한 체크포인트 / 과학 파일 |
|---|---:|---:|---|---|
| 개발 0–19 | 1,021.494초 | 1,030.219초 | 6 × 20 × 200 | 360 / 9 |
| 검증 20–39 | 1,027.909초 | 1,028.576초 | 6 × 20 × 200 | 360 / 9 |

본실험 48,000세계·년과 반복 48,000세계·년에서 720개 체크포인트와 과학 자료 18개가 일치했다. 압축된 국가·지역·국경 패널도 전체 파일 바이트를 대조했다. Git 필터 적용 전후 18개 파일의 blob도 전부 일치했다. A·E의 240개 체크포인트가 각각 기존 C·D와 같았고 기존 A·B 재생을 합쳐 6.0A **480/480**개가 일치했다. 실행 시간에는 두 표본을 동시에 실행한 시간이 겹친다. [개발 반복 영수증](../examples/phase6a1/study/replay-dev.json) · [검증 반복 영수증](../examples/phase6a1/study/replay-holdout.json)

## 공개 원자료의 재집계

```sh
python -B -m experiments.effects61 --study examples/phase6a1/study --out docs/phase6a1-effects.md
python -B -m experiments.aid_results61 --study examples/phase6a1/study --out examples/phase6a1/aid-diagnostics.json
```

국가·지역·방향 표로 17개 경제·외교 지표를 다시 계산했다. 표본별로 지역 11,520행·국가 2,880행·세계 360행을 확인했다. 다른 프로세스에서 생성한 경제 분석 보고서 24,427바이트가 같았다. SHA-256은 `39a8132427bbe71f0aa9d16ab2de36280f4bdb4c9c9bb8b10e4d826b1ef7dc10`이다.

원조 진단 JSON의 첫 독립 반복에서 수치가 모두 같은데 파일 해시가 달랐다. 한 운송 시도에서 동률이었던 승인량·예산 두 키를 집합의 순서로 출력했기 때문이다. 집계기는 사전에 정의된 제약 순서로 필드를 쓰도록 수정했다. `PYTHONHASHSEED=1`과 `42`로 각각 위 집계기를 다시 실행해 `../../work/phase6a1-diagnostics-hash1.json`, `../../work/phase6a1-diagnostics-hash42.json`에 썼다. 두 파일 모두 처음 게시한 원조 진단 36,262바이트와 완전히 같았다. SHA-256은 `d5d00495e346724b18b72decc301bc7d837ed1955779be34051e258d02eb0322`다. [경제 지표 검산](phase6a1-effects.md) · [원조 진단 원자료](../examples/phase6a1/aid-diagnostics.json)

## 자동 시험

최종 트리와 공개 자료를 모두 갖춘 상태에서 `python -B -m unittest discover -v`를 실행했다. **311/311 통과, 실패·오류·건너뜀 0, 73.202초**였다. 6.0A 원문 로그의 280개 시험 이름이 모두 포함됐고, 이번 단계의 신규 시험은 31개였다. Windows 콘솔 출력은 줄바꿈을 LF로 통일해 저장했다. [전체 시험명과 실제 출력](../examples/phase6a1/test-log.txt) · [720개 체크포인트·재고·재생 검사](../tests/test_aid61_publication.py)

전체 시험에 앞서 기준 커밋의 `tests/` 아래 62개 모듈을 Git에서 열거해 `python -B -m unittest -v`로 실행했다. 279개가 148.700초에 통과했다. 저장된 6.0A 시험 로그와 시험명을 대조하고 별도 폴더의 `python -B -m unittest -v benchmarks.test_benchmark`도 실행했다. 이 1개는 0.553초에 통과했다. GitHub 검사는 Ubuntu의 Python 3.11과 Windows의 Python 3.12로 전체 시험 및 보관 원장 검사를 실행한다. [PR의 커밋별 검사 결과](https://github.com/mrgameskr-lang/civilization/pull/14/checks)

장거리·여러 도로·여러 수혜국·운임 올림·포화 창고의 고정 사례에 더해, `python -B -m unittest tests.test_aid_limits61 -v`에서 거리·공여 재고·국가 예산·입고 여유 조합 2,160개의 가능한 적재량을 직접 열거했다. 1개 시험의 2,160개 하위 사례 모두 통과했다(0.359초). 시드 0의 4년차에는 연말 상태와 실제 소비 결과를 입력에서 제외하고 32개 지역의 식사를 재계산했다. 그해 **모든 방향**의 송장 5장을 넣었을 때 총섭취는 69,953, 모두 뺐을 때 70,090이었고 전체 자료로 재계산한 32개 지역의 식사 원장과 같았다. [송장 경계값 시험](../tests/test_aid_limits61.py) · [연초 정책과 생산 직후 재고만 이용한 식사 시험](../tests/test_meal_inputs61.py)

독립 감사의 재검토에서, 실물 상태가 우연히 일치하는 첫해 F 뒤에 둘째 해 E 원장을 붙이면 기존 포맷으로 위임하는 검사 한 곳이 이를 허용하는 사례를 재현했다. 실행기의 연속 경로는 처음부터 군 변경을 거부했다. 이전 레코드를 따로 전달받는 감사 API도 서로 다른 포맷과 진단용 전년 원장을 거부하게 고쳤다. 동결 후 실행기 파일에서 바뀐 코드는 이 **제출된 과거 원장의 유효성 검사** 네 줄이다. 국가의 정책·물량·비용·식사 수식과 원자료 수집 코드는 동결판과 같다. [양방향 군 교체 및 단년 진단 종료 시험](../tests/test_aid_continuity61.py)

감사 보완 후 새 프로세스에서 `python -B -m experiments.phase6a1 --sample dev --seeds 1 --workers 1 --out ../../work/phase6a1-postreview-seed0`도 실행했다. 265.575초에 시드 0 여섯 경로 1,200세계·년을 재생했다. 원자료에서 같은 시드를 추출해 체크포인트 18행, 국가 144행, 지역 576행, 비교 18행, 국가·년 9,600행, 지역·년 38,400행, 국경 방향·년 7,068행, 원조 운송 시도 443행의 모든 열이 일치했다. 표본 평균은 시드 한 개와 스무 개의 분모가 달라 이 단일 시드 검사에서 제외했다.

## 속도 측정

```sh
python -B -m cProfile -o ../../work/phase6a1-capped.prof -m civsim.aid61 run --arm F --seed 0 --years 30 --out ../../work/phase6a1-profile
```

F의 30년 전체 원장 작성에서 19,349,857회 호출, 프로파일러 측정 시간 16.491초였다. 누적 시간은 상태 복사 `deepcopy` 8.010초, 재정 감사 4.393초, 원장 JSON 표준화 1.156초, 공여국 예산·송장 검산 0.022초였다. 일부 호출이 다른 호출 안에 있으므로 시간을 합산할 수 없다. 프로파일러를 켠 한 시드의 전체 원장 작성 시간과 병렬 표본 실험 시간은 작업량과 측정 조건이 다르다.

## 검증 범위

```sh
git ls-tree -r --name-only d12d0fe
git ls-tree -r --name-only d12d0fe -- examples
git diff --exit-code --no-renames --diff-filter=MDTR d12d0fe HEAD
git diff --check d12d0fe HEAD
```

기준 커밋의 추적 파일 434개(기존 예제·실험 216개)를 대조했다. 기존 경로의 내용·유형 변경이나 삭제 건수는 0이다. GitHub PR #14의 기준은 PR #12의 `phase6a/diplomacy`다. 기존 PR은 열린 상태로 두었다.

- 48×32 지도·8개국·32개 지역, 고정된 40개 시드, 200년까지를 시험했다. 각국 창고 및 민간 재고(식량·광석·도구), 실제 송장의 거리·용량·취급 손실, 국경 현금 지급과 인구를 원장과 대조한다. 국가별 누적 계산은 초기 지역 재고에서 독립적으로 다시 합산한다.
- 실험군 A와 E는 기존 연간 원장을 그대로 재생한다. B·C·D·F는 새 감사 경로를 거쳐 해마다 정책과 물리 효과를 함께 기록한다. 더 오래된 모든 실험의 모든 궤적을 재실행한 범위는 위 표의 검증기로 한정한다. 기존 저장소 파일의 Git 내용 해시 보존은 별도로 확인한다.
- 개별 식량의 최종 구매자나 섭취자는 추적하지 않는다. 입고, 국내 배급, 실제 송장을 제거한 해당 연도의 섭취 차, 처음부터 정책을 달리한 장기 섭취 차를 구분했다. 이미 같은 공공창고에 있던 원조의 향후 가치와 저장 후 폐기량을 산지별로 식별하지 않는다.
- 검증 표본까지 계수를 사전에 고정했다. 실제 국가에서의 인과 효과, 200년 이후의 경로, 원조+수출·원조+이주·수출+이주 세 조합은 이 실험에서 추정하지 않았다. 제한에 걸린 물량·이동 시도는 다른 국경으로 대체될 수 있어 순수출 손실이나 고유 주민 수와 다를 수 있다.
- 저장 호환성을 지키기 위해 새 버전의 연간 단계 연결과 재정 감사 일부를 별도 모듈에 두었다. 향후 공통 물류 단계가 바뀌면 버전별 감사와 각 기준군의 보관 원장을 함께 확인해야 한다. 현행 제안은 공여국당 한 해 최대 한 수혜국을 선택한다. 여러 수혜국이 하나의 예산을 쓰는 경계 조건은 구성한 회귀 사례에서 검증했다.
- GitHub에서 이슈와 기준 PR을 확인하고 검토용 PR을 열었다. Context7에서 CPython 표준 라이브러리 `hashlib.file_digest`의 파일 모드와 해시 객체 사용을 확인했다. 사용한 경제 엔진과 실험 실행기는 Python 표준 라이브러리만 필요하다. tldraw에는 의사결정·송장·국경·소비 검산 흐름을 추가했다. UI 작업이 없어 Figma는 사용하지 않았다. [설계도](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)
