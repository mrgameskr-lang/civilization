# 6.0C1 부분 구현 검토 안내

PR #16의 `5d686a5` 위에 기존 평시 모형의 회계 검증과 선택형 민간 외교분쟁 관측을 추가했다. [범위와 실험 조건](phase6c1-scope.md) · [평시 식사·노동·창고 분석](phase6c1-accounts.md) · [양자 협의·반사실 결과](phase6c1-diplomacy-results.md)

Windows · Python 3.12.14에서 전체 테스트 **373개**가 91.588초에 통과했다. 기존 테스트 346개와 새 테스트 27개를 포함한다. [실행 로그](../examples/phase6c1/full-tests.txt)

## 검토할 결과

독립 검증 20개 세계의 200년 합계에서 기존 고정 정원은 복무 5,464,740인년, 공공 식량 지급 303,191인년, 식량과 도구 모두 충족 302,840인년이었다. 기존 자율 정원은 각각 886,142, 270,264, 270,210인년이었다. 지역·연도마다 **복무 = 공공 미배식 + 배식 후 도구 미충족 + 두 요건 충족**을 확인했다. 단순 시드평균 충족률은 5.442%와 29.854%이고 인년을 합친 비율은 5.542%와 30.493%다. 이 분해는 결산 단계에서 직접 성립한다. 반면 도로·공공사업·원조 각각의 독립 인과효과나 식사를 받은 개인의 신원은 집계 원장으로 식별할 수 없다. [원래 지급과 실제 식사의 분자·분모](../examples/phase6c1/accounts/cohort-accounts.csv)

아래 값은 기존 자율 정책을 40개 시드에서 실제 재실행한 결과다. 각 행은 20개 세계의 합이고, 지지와 불만은 당해까지 대표 집단 구성원·연도로 가중한 0~1,000 점수다. 정권 교체에서 최초 정부 설치는 제외했다. 부족률의 분모는 누적 주민 필요 식량이다. 두 민간 외교 모드는 같은 경제 연말 원장을 읽는다.

| 표본 | 연도 | 기말 인구 | 누적 부족률 | 정권 교체 | 평균 지지 | 평균 불만 | 기말 총현금 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 개발 | 50 | 2,270,066 | 5.97455% | 651 | 470.07 | 71.85 | 6,656,043 |
| 개발 | 100 | 2,381,517 | 8.69663% | 1,085 | 456.40 | 95.04 | 6,656,043 |
| 개발 | 200 | 2,399,048 | 10.19753% | 1,924 | 448.41 | 106.16 | 6,656,043 |
| 검증 | 50 | 2,330,270 | 5.43254% | 633 | 472.06 | 66.58 | 6,757,950 |
| 검증 | 100 | 2,461,332 | 8.42157% | 1,058 | 457.48 | 92.68 | 6,757,950 |
| 검증 | 200 | 2,455,434 | 10.11221% | 1,895 | 448.83 | 105.18 | 6,757,950 |

[국가별 960개 결산](../examples/phase6c1/baseline/country-totals.csv) · [시드별 기존 경제 해시 120개](../examples/phase6c1/baseline/checkpoints.csv)

## 지역 데이터 구조와 적용 범위

`baseline/regional-closes.csv`는 40개 세계 × 3개 결산연도 × 32개 지역의 3,840행이다. 각 행은 해당 단년의 주민 주소지와 두 소유권 계정을 나타낸다. 연간량과 기말값을 구분한다.

| 필드 | 단위·시점 |
|---|---|
| `seed,year,region,owner` | 세계, 결산연도, 지역 ID, 소속 국가 ID |
| `population_open,population_close,births,deaths,immigrants,emigrants` | 주소지 주민. 출생·사망·유입·유출은 해당 연도 |
| `food_need,food_eaten,food_unmet` | 해당 연도 지역의 주민 필요·실제 섭취·부족. 공공 지급 식사는 일반 수요 안에서 한 번 계상 |
| `private_food/ore/tools,public_food/ore/tools,cash` | 기말 민간 재고, 공공창고 재고, 지역 현금 |
| `support_points,discontent_points,members` | 해당 연도 대표 집단의 구성원 가중 합과 그 분모 |

민간 상태를 읽는 소비자는 `(seed,year,region)`을 키로 사용한다. 다음 해의 외교 모듈에는 이전 결산만 제공한다. 전시 동원·국경 배치·준비 기간 및 6.0C2 전투용 지역 상태 인터페이스는 제공 범위 밖이다. [지역 원자료](../examples/phase6c1/baseline/regional-closes.csv) · [경제 원장과 별도 외교 원장을 반환하는 실행 API](../civsim/civic_observer63.py)

## 실행과 독립 검산

아래는 저장소 루트에서 사용한 Python 모듈 및 인수다. 원본 결과 경로는 이미 발행됐으므로 새 실행은 새 경로를 사용한다. 집계는 Python 표준 라이브러리로 작성했다.

```powershell
python -B -m experiments.civic_baseline63 --workers 6 --out examples/phase6c1/baseline
python -B -m experiments.civic_accounts63 --out examples/phase6c1/accounts --report docs/phase6c1-accounts.md
python -B -m experiments.civic_accounts63 --verify examples/phase6c1/accounts --report docs/phase6c1-accounts.md
python -B -m experiments.civic_disputes63 --sample dev --out examples/phase6c1/diplomacy/dev
python -B -m experiments.civic_disputes63 --sample holdout --out examples/phase6c1/diplomacy/holdout
python -B -m experiments.analyze_civic63 --study examples/phase6c1/diplomacy --out examples/phase6c1/diplomacy/outcomes.json
python -B -m experiments.verify_live_civic63 --workers 4 --out examples/phase6c1/live-check.json
python -B -m unittest discover -v
```

민간 분쟁 본실험과 독립 반복의 표본별 명령은 [실험 보고서](phase6c1-diplomacy-results.md)에 있다. 기존 자율 경로 8,000세계연도의 인구·노동·재화·정부창고·현금·도로·원조 예산을 원래 지도와 대조했고, 120개 누적 경제 해시가 기존 발표값과 일치했다. 외교 등록부의 독립 반복은 두 표본 합계 240개 시점·14개 과학 파일 전체 바이트를 대조했다. 별도로 시드 0·20에서 두 모드를 각각 직접 실행해 800개의 단년 원장과 22,400개의 국가쌍·연도를 대조했다. [경제 재실행 영수증](../examples/phase6c1/baseline/receipt.json) · [실시간과 저장 원장 비교](../examples/phase6c1/live-check.json) · [전체 테스트 로그](../examples/phase6c1/full-tests.txt)

PR #16까지의 과거 버전은 이번 작업의 입력이다. 과거 모든 버전·모든 정책의 장기 경로를 새로 실행한 것은 아니다. 검증 표본은 기존에 공개된 20개 세계이고 다른 지도 규모, 다른 임곗값, 개인 식생활 또는 실제 국가에 대한 외부 검증은 수행하지 않았다.
