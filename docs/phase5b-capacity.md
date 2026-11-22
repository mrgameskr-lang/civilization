# 5.0A 도로 용량 교정

PR #8의 `final_effective_capacity`는 기준 연도에 실제로 운송할 수 있었던 용량을 담았다. 해당 연도의 공사와 유지 실패까지 반영한 기말 값을 구하려면 다음 해 사용 가능한 용량을 읽어야 한다. 5.0B에서 두 값을 명시한 교정 표를 별도 경로에 발행했다. 원래 표의 ‘200년차 실제 도로 용량’은 당해 사용 가능량을 뜻한다. 200년 시점에는 조사한 모든 경로에서 두 값이 같았다.

| 열 | 단위와 시점 |
|---|---|
| `year_base_capacity` | 기준 연도 지도상 기본 도로 용량 합계 |
| `opening_road_units`, `closing_road_units` | 기준 연도 초·말에 실제 남은 개량 단위 |
| `year_effective_capacity` | 기준 연도 운송에 적용된 용량. 기본 용량 + 48 × 기초 개량 단위 |
| `next_year_effective_capacity` | 기준 연도 마감 직후 다음 해 사용 가능한 용량. 기본 용량 + 48 × 기말 개량 단위 |
| `final_effective_capacity` | 교정판의 기말 값. `next_year_effective_capacity`와 같음 |
| `base_capacity`, `effective_capacity`, `next_capacity` | 1년부터 기준 연도까지 매년의 기본·당해 실효·차년도 용량을 각각 더한 용량-연도 |

## 확인한 사례와 규모

통합 정책의 시드 28은 50년 차 도로 24–25의 개량 1기를 유지하지 못했다. 당해 세계 도로 용량은 10,376, 기말 다음 해 용량은 10,328이었다. 시드 30은 도로 16–17에 개량 1기를 신설했다. 당해 10,070, 기말 10,118이었다. 두 사례 모두 51년 차 해당 도로가 실제로 전년도 기말 단위와 용량으로 시작하는지 검사했다.

| 세계당 평균 용량, 50년 | 개발 표본 당해 | 개발 표본 차년 | 검증 표본 당해 | 검증 표본 차년 |
|---|---:|---:|---:|---:|
| 정부 없음 | 10,272.65 | 10,272.65 | 10,246.70 | 10,246.70 |
| 구호 | 10,272.65 | 10,272.65 | 10,246.70 | 10,246.70 |
| 기반시설 | 11,340.65 | 11,323.85 | 11,425.10 | 11,408.30 |
| 통합 | 10,332.65 | 10,327.85 | 10,388.30 | 10,373.90 |

40개 시드와 4개 정책의 50·100·200년 시점을 비교했다. 개발 표본에서는 240개 세계 행 중 18개, 독립 검증 표본에서는 240개 중 17개에서 기말 값을 읽으면 기존 열과 수치가 달라진다. 그중 34개는 50년 시점, 1개는 100년 시점이다. 국가별로는 개발 25개 행과 검증 21개 행이 바뀐다. 지역별 지표와 사례 파일은 두 표본 각각 보관본과 바이트가 일치했다. 원래 표의 모든 누적 경제 원장 SHA-256 480개, 인구·재화·배급·운임·실제 도로 사용량도 일치했다. [개발 표](../examples/phase5b/capacity/dev) · [검증 표](../examples/phase5b/capacity/holdout) · [35개 해당 행과 대조 기록](../examples/phase5b/capacity/verification.json)

## 물리적 도로 검산

연초 빈 개량 장부와 원래 지도에서 시작해 매년 도로별로 유지·신설 영수증을 집계했다. 유지한 기존 단위 + 신설 단위가 기말 단위이며 다음 해 기초로 이월된다. 민간 수송·공사·구호의 송장마다 실제 타일 경로, 출발지·도착지, 거리와 통과 구간을 원래 지도와 대조하고 각 구간 사용량을 화물 수량만큼 더했다. 이 금액과 미사용량의 합이 해당 연도 용량과 일치해야 한다. 나라별로 도로를 합산해 연도별 국가 회계 수치도 대조했다. 별도 검산 명령은 과거 열 전체와 누적 용량의 연도 간 합계, 누적 신설·소실 단위와 기말 잔량의 관계를 확인한다. [물리 검산 코드](../experiments/capacity5.py) · [보관본 대조 코드](../experiments/verify_capacity5.py) · [회귀 테스트](../tests/test_capacity5.py)

## 실제 실행

저장소 루트에서 번들 CPython 3.12.14로 실행했다. 두 표본을 동시에 실행한 경과 시간은 개발 213.433초, 검증 213.036초였다. 각 표본은 20개 시드와 네 정책으로 16,000세계연도를 진행했다. 추가한 테스트 3개와 기존 재정 집계 테스트 3개가 15.408초에 모두 통과했다. 원래 5.0A 데이터 디렉터리의 Git 차이는 비어 있었다. 재생성 시에는 새 출력 경로를 지정할 수 있다.

```sh
python -B -m unittest tests.test_capacity5 tests.test_phase5_study -v
python -B -m experiments.phase5a --sample dev --workers 8 --out examples/phase5b/capacity/dev
python -B -m experiments.phase5a --sample holdout --workers 8 --out examples/phase5b/capacity/holdout
python -B -m experiments.verify_capacity5 --reference examples/phase5/study --corrected examples/phase5b/capacity --out examples/phase5b/capacity/verification.json
git diff 739a168 --stat -- examples/phase5/study
```
