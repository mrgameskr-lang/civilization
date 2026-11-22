# 자율 문명 시뮬레이션

8개 가상 국가가 48×32 타일 세계에서 50년을 살아가는 Python 엔진이다. 시드는 영토·자원·인구·생산성·기술의 초기 차이와 기후 주기를 결정한다. 이후 식량 재고가 다음 해의 노동 배분을 바꾸고, 무역으로 확보한 식량이 출생·사망·이동에 영향을 준다. 식량 부족과 이주 사건은 실제 수량이 계산된 연도에 기록한다.

기본 실행은 1.0 규칙을 사용한다. 2.0은 농지 수용 한도를 초과하는 인력의 재배치와 재화별 결제 순서를 선택할 수 있다. 20개 시드·240개 조합의 실측 결과, 반례, 검증 명령은 [2차 실험 보고서](docs/phase2.md)에 있다.

3.0은 도구의 목표 재고를 두고, 농업 설비·광공업 설비·경작지 개간에 광석·도구·노동을 투자한다. 유지비를 낸 기존 설비가 생산에 참여하며, 새 설비는 다음 해부터 가동된다. [투자 정책과 수식](docs/investment-rules.md) · [50년·200년 비교 보고서](docs/phase3.md)

3.1에서는 설비의 체감수익, 규모별 효과·유지비, 연간 사업 수를 각각 선택할 수 있다. 개발 세계 20개와 별도 검증 세계 20개에서 투자 규칙을 비교했다. 개발 세계에서는 인구와 식량을 500년까지 추적했다. [장기 안정성과 투자 비교](docs/phase31.md) · [투자 수식](docs/investment31-rules.md)

4.0은 국가마다 기본 4개의 연결된 지역을 만들고 지역별 생산·재고·소비·인구를 계산한다. 국내 화물은 공유 용량이 있는 도로를 지나며, 운송한 수량과 타일 거리에 따라 식량을 지출한다. [지역 생성·국가 회계](docs/regions4.md) · [연간 계산과 실행 방법](docs/phase4.md) · [50년·200년 실험과 반례](docs/phase4-results.md)

5.0A에서는 지역별 창고에 현물을 징수하는 정부가 구호·도로·토양·예비 비축·지출 유보 중 하나를 선택한다. 공사·구호는 민간과 도로를 공유하고 공공 노동은 민간 생산에서 차감한다. [재정 장부와 실행 방법](docs/phase5a.md) · [정책 수식](docs/fiscal-policy5.md) · [실험과 반례](docs/phase5a-results.md)

5.0B는 5.0A 통합 재정에서 실제 집행된 구호·산업 부담·공공사업과 식량 사정을 지역 집단별로 관측한다. `python -m civsim politics --feedback on`은 그 기억을 다음 해 정책 순위에 반영하며, `off`는 같은 정치 지표를 관찰하면서 5.0A 경제 경로를 재생한다. [지역 정치 상태와 실행 방법](docs/phase5b.md) · [수식](docs/political-rules.md) · [검증 결과와 반례](docs/phase5b-results.md)

## 실행

Python 3.11 이상에서 저장소 루트를 작업 디렉터리로 사용한다. 런타임과 테스트는 모두 표준 라이브러리를 사용한다.

```sh
python -m civsim run --seed 42 --years 50 --out runs/seed-42
python -m civsim verify runs/seed-42
python -m civsim analyze runs/seed-42 --csv runs/country-years.csv
python -m unittest discover -v
python -m benchmarks.benchmark
```

지역 버전은 `python -m civsim regional --seed 7 --years 50 --out runs/regional-7`로 선택한다. `python -m civsim verify runs/regional-7`은 초기 지도·도로와 연간 원장을 재생한다. `python -m civsim analyze runs/regional-7 --csv runs/region-panel.csv`는 지역·연도별 CSV를 쓴다.

2.0 예제를 새 디렉터리에 만들려면 `python -m civsim run --seed 13 --years 50 --labor reallocate --trade-order food,ore,tools --out runs/phase2-seed13`를 실행한다. `verify`는 매니페스트에 저장된 버전·규칙을 읽어 해당 실행을 재생한다.

3.0의 설비 투자군은 `--investment capital`, 도구 재고 제어만 적용하는 대조군은 `--investment inventory`로 선택한다. 다음 명령은 3차 보고서와 같은 노동·결제 규칙을 사용한다.

```sh
python -m civsim run --seed 7 --years 50 --labor reallocate --investment capital --out runs/capital-7
python -m civsim verify runs/capital-7
python -m experiments.phase3 --seeds 20 --horizons 50,200 --out runs/investment-study
```

3.1의 체감·규모 보정과 복수 사업을 함께 적용하는 예는 다음과 같다.

```sh
python -m civsim run --seed 7 --years 200 --labor reallocate --investment capital --policy31 combined-multi --out runs/combined-7
python -m civsim verify runs/combined-7
```

`run`과 CSV 내보내기는 새 경로에 쓴다. 다른 실험을 저장할 때는 새 디렉터리·파일 이름을 지정한다. `--width`, `--height`, `--nations`로 규모를 바꿀 수 있다. 이미 저장된 예제를 살펴볼 때는 `python -m civsim analyze examples/seed-42`를 실행한다.

## 결과 읽기

| 파일 | 확인할 수 있는 내용 |
| --- | --- |
| [manifest.json](examples/seed-42/manifest.json) | 시드, 크기, 국가 수, 연수, 모델·저장 형식 버전 |
| [world.json](examples/seed-42/world.json) | 초기 타일별 소유국·토질·광맥과 0년차 국가 상태 |
| [years.jsonl](examples/seed-42/years.jsonl) | 1행이 1년. 국가별 기초·기말, 부문별 투입·생산, 호가·체결, 소비, 인구, 이동 및 사건 |
| [국가별 CSV](examples/country-years.csv) | 국가·연도별 400행. 인구, 부문별 생산, 수입·수출, 식량 부족, 호가와 잔여 자원 |
| [요약](examples/summary.json) | 세계 인구, 출생·사망, 누적 이주, 식량 거래·섭취·부패 |
| [검증 보고](docs/validation.md) | 한 국가·연도의 계산 재구성, 재현 해시, 테스트 범위 및 규모별 성능 |

`verify`는 초기 지도를 시드에서 다시 생성하고, 저장된 매년의 원장을 검사한 뒤 모든 입력과 결과를 연도별로 재계산해 대조한다. 일치하면 원본 JSONL의 SHA-256을 출력한다. 편집·전달받은 자료는 `verify` 후 분석하면 된다. `analyze`는 연도 순서와 행 수를 확인하면서 집계한다.

## 규칙과 코드

| 모듈 | 규칙·역할 |
| --- | --- |
| [model.py](civsim/model.py) | 연결된 영토, 타일 자원, 국가별 초기 능력, 기후 주기. [세계 생성 수식](docs/world.md) |
| [economy.py](civsim/economy.py) | 노동·도구·토양 제약, 유한 광맥, 광석 → 도구 변환, 호가와 거래, 섭취·부패. [경제 수식](docs/economy.md) |
| [demography.py](civsim/demography.py) | 섭취량별 출생·사망, 과밀과 잉여 식량에 따른 동시 이주 배정. [인구 수식](docs/demography.md) |
| [engine.py](civsim/engine.py) · [audit.py](civsim/audit.py) | 연속된 한 해의 단계 조정, 독립 원장 검사, 사건 도출, 검사 성공 후 상태 반영 |
| [storage.py](civsim/storage.py) · [analysis.py](civsim/analysis.py) | 실행별 저장·재생, 순차 조회, 세계 요약과 CSV 추출 |

국가 하나가 생산과 거래의 단위다. 기술·생산성은 국가마다 다른 고정 계수다. 영토의 토질·광석 품위, 해마다 달라지는 기후·토양과 남은 매장량이 공급량을 결정한다. 국내 가계, 운송 거리, 신용, 연령구조를 생략했다. 계수와 기후 주기는 가정값이며 역사 자료로 보정하는 작업은 후속 범위다.

정치·외교는 연말 상태를 읽어 다음 해의 정책·거래 가능 조건을 정하는 모듈로 연결할 수 있다. 설계도에는 후속 모듈의 의존관계도 담았다. [설계 문서](docs/design.md) · [tldraw 보드](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)

## 후속 개발

1. 초기 현금과 비축 목표를 바꿔 식량 부족이 수확량과 구매력 중 어느 쪽에 민감한지 측정한다. [GitHub 이슈 #1](https://github.com/mrgameskr-lang/civilization/issues/1)
2. 장기·다시드 데이터에서 국가 스냅샷 복사와 직렬화 비용을 줄이되 원장 재현성을 유지한다. [GitHub 이슈 #2](https://github.com/mrgameskr-lang/civilization/issues/2)
3. 거리·인접국을 무역 및 이주 조건에 도입하고 이후 외교 정책을 연결한다. UI는 엔진과 분리된 후속 작업으로 둔다.

## 개발 도구

GitHub에서 기능별 커밋·후속 이슈를 관리한다. Context7에서 CPython 공식 문서의 JSON 정렬·구분자·인코딩 옵션을 확인해 연간 기록 형식에 적용했다. Figma는 계정 연결을 확인했고 이번 범위의 설계도는 tldraw에서 작성했다. [Python JSON 공식 문서](https://docs.python.org/3.12/library/json.html)

