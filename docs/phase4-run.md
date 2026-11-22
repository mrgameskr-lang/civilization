# 4.0 실행 기록과 호환성 검증

기준 [PR #5](https://github.com/mrgameskr-lang/civilization/pull/5)의 커밋은 `881469a70083db50fd38525cc2335cdf5748f2f1`이다. [4.0A PR #6](https://github.com/mrgameskr-lang/civilization/pull/6)의 커밋은 `a8172b9c92662872d5fb4d8acd1c015ad8c13e30`이다. 아래는 Windows 11의 CPython 3.12.14에서 실제 실행한 명령이다. 예제 경로는 이 저장소 루트를 기준으로 한다. 다시 실행할 때에는 새 출력 경로를 사용한다.

## 지역 회계 검증

```console
python -m unittest discover -q
Ran 115 tests in 10.300s
OK
python -B -m experiments.regions4 --seeds 40 --out examples/phase4a/initial-worlds.csv
40 regional worlds reconciled with original national endowments
python -B -m unittest tests.test_regions4 -v
Ran 5 tests in 0.088s
OK
```

첫 115개는 PR #5 커밋에서 실행했다. 4.0A 커밋만 담은 별도 체크아웃에서 `python -B -m unittest discover -q`로 120개 테스트가 12.155초에 통과했다. 시드마다 원래 1,536개 타일의 소유권, 지역 연결, 중심지 간 도로의 실제 인접 타일과 국가별 자원 합계를 검사했다. [40개 시드의 초기 장부와 해시](../examples/phase4a/initial-worlds.csv)

## 물류·생산·인구 통합

```console
python -B -m unittest discover -v
Ran 149 tests in 12.802s
OK
python -B -m experiments.phase4 --seeds 20 --horizons 50,200 --workers 8 --out examples/phase4/study
80 paths; 16000 annual transitions; 116.500 s
python -B -m experiments.phase4 --seeds 20 --horizons 50,200 --workers 6 --out ../../work/phase4-frozen-repeat
80 paths; 16000 annual transitions; 91.554 s
python -B -m experiments.road_closure4 --seed 7
mode=unlimited food_shipped=962 domestic_cost_food=124 food_output=66551 unmet=0 regions_short=0
mode=limited food_shipped=962 domestic_cost_food=124 food_output=66551 unmet=0 regions_short=0
mode=closed food_shipped=0 domestic_cost_food=0 food_output=66551 unmet=962 regions_short=2
```

기존 115개와 신규 34개가 통과했다. 검증 범위는 국가·지역 기초/기말 합계, 매장량, 유상 토양 관리와 생산·소비 투입, 설비 장부, 지급된 효과 범위, 도로의 실제 타일·거리·용량·비용, 국경 양자 결제, 인구·이주 보존, 실패한 해의 미게시, 파일 덮어쓰기 거부, 위조된 저장 기록 거부를 포함한다. 두 국가의 기초와 기말 현금을 같은 양으로 맞바꿔 순변화만으로는 드러나지 않는 위조와, 국경 도로에 존재하지 않는 타일을 넣은 위조가 거부되는지도 시험했다. [테스트별 전체 결과](phase4-tests.txt)

독립 전체 반복에서 `runs.csv`, `paired.csv`, `regions.csv`, `roads.csv`, `means.csv`, `cases.json`의 **6개 파일 전체 바이트**가 일치했다. 160개 체크포인트의 연간 원장 해시와 512,000개 지역·연도 전이가 이 비교에 포함된다. `execution.json`은 실행별 소요 시간과 병렬 작업 수를 담는다. 8개·6개 프로세스 실행 시간은 동시 CPU 작업량이 달랐으므로 병렬 효율 비교에 사용하지 않았다.

| 아티팩트 | 전체 반복에서 일치한 SHA-256 |
|---|---|
| 시드별 runs.csv | `b9ee03de830bafde63b336f27a3b23050eadb765b00ddd52caea8024916cfebd` |
| 지역별 regions.csv | `91364c8f6b4104e8f75b5106b2bb2fde5c6105033de06af9a502a4c97ef15554` |
| 도로별 roads.csv | `6c5d8ffa1e1f036cd86cae5b9f4d051c246cb0ae4e2547b941d2b9c845a13de9` |

### CLI와 성능

```console
python -B -m civsim regional --seed 7 --years 2 --out examples/phase4/seed7-two-years
python -B -m civsim verify examples/phase4/seed7-two-years
cb5600c4af37f4a580eec64cf0cace1c0697b695b52cf526fc7d2c5665a005b4
python -B -m civsim analyze examples/phase4/seed7-two-years --csv ../../work/phase4-region-panel.csv
python -B -m cProfile -o ../../work/phase4-seed7.prof -m civsim regional --seed 7 --years 50 --out ../../work/phase4-seed7-y50
python -B -m civsim verify ../../work/phase4-seed7-y50
33607b5b65922f13a76edfb4c3c33b16a665617213f3087ec1af6d6833830c85
```

2년 예시에는 64개 지역·연도 상태가 저장됐다. 50년 상세 재실행 해시는 20시드 실험의 시드 7 제한군 50년 체크포인트와 일치했다. 50년 CLI 쓰기의 cProfile 측정은 전체 3.448초였다. 50회 연간 전이에 누적 2.798초, 그 안의 생산 0.782초, 생산 독립 검사 0.575초, 국내 운송과 운송 검사 합계 0.517초가 걸렸다. 연간 데이터를 정규 JSON으로 직렬화한 누적 시간은 0.326초였다. 중첩 호출의 누적 시간은 합산하지 않는다. 이 측정에서는 생산 계획·검사, 도로 검증·배차, 원장 직렬화에 시간이 쓰였다. 더 큰 세계의 연간 처리량은 별도의 측정이 필요하다.

### 과거 모델 재생

```console
python -B -m experiments.verify_archives31 --workers 4
python -B -m experiments.investment31 --seed-start 0 --seeds 20 --workers 6 --horizons 50,100,150,200 --out ../../work/phase4b-check-dev
python -B -m experiments.investment31 --seed-start 20 --seeds 20 --workers 6 --horizons 50,100,150,200 --match-design examples/phase31/investment/dev --out ../../work/phase4b-check-holdout
```

4.0B 작업 디렉터리에서 1.0~3.0 과거 경로 280개와 3개 상세 실행을 재생했다. 예전 실험표의 400개 체크포인트 모두 초기 지도 및 연간 원장 SHA-256이 일치했다(29.143초). 3.1의 개발·검증 표본도 각각 160경로씩 총 64,000개 세계·연도 전이를 다시 계산했다(75.642초, 80.396초). 1,280개 행의 초기 지도·연간 원장 해시 2,560개와 각 표본 CSV 5개의 모든 값이 기존 결과와 같았다.

## 도구와 미검증 범위

GitHub에서 기준 PR을 조회하고 지역 회계와 연간 엔진을 별도 검토 브랜치로 게시했다. Context7에서 CPython 3.12 표준 라이브러리의 `deque`를 확인했다. tldraw에는 시스템 흐름과 시드 18의 실제 포화 도로 사례를 작성했다. 지도 UI를 제외한 이 단계에서는 Figma를 사용하지 않았다. [CPython 문서](https://docs.python.org/3.12/library/collections.html#collections.deque) · [tldraw 보드](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)

연간 물류 실험은 개발 시드 0~19의 8개국·32개 지역에서 수행했다. 초기 회계 검증은 시드 0~39다. 200년 이후, 별도의 검증 시드에서의 장기 물류, 운송 시간 지연·운송 중 재고, 도로 증설의 투자 수익, 보정 계수 민감도와 실측 경제자료 적합성은 이번 실행으로 검증하지 않았다. [모델의 적용 범위](phase4.md)
