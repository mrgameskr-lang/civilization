# 6.0B1 공공 보급망 검토 안내

PR #14의 `5480ebb`에서 분기했다. 외교팀의 연초 승인과 공여국 예산을 그대로 받아, 승인 물자가 국경창고에 없어 집행할 수 없는 경우를 국내 실물 수송으로 처리한다. 다음 링크에서 코드, 선행 진단, 실제 장기 및 단년 원장을 확인할 수 있다.

- [이송 순서·경로·원가 코드](../civsim/depot_supply62.py) · [원조 예산 분개](../civsim/supply_border62.py) · [독립 결산](../civsim/supply_audit62.py)
- [사전 비교 계획](phase6b-protocol.md) · [개발·검증 결과 및 반례](phase6b1-results.md) · [연간 파일 사전](../examples/phase6b1/study/README.md)
- [단년 개입 3쌍의 전체 송장과 요약](../examples/phase6b1/forks) · [4년 연속 원장](../samples/phase6b1/seed0-warehouse)

연간 일반 실행 명령과 검증 명령은 아래와 같다. 새 실행은 비어 있는 경로를 지정한다. 예시의 run 및 forks 명령은 보관본이 만들어질 때 실행한 명령이다.

```powershell
python -B -m civsim.depot62_cli run --seed 0 --years 4 --arm B --out samples/phase6b1/seed0-warehouse
python -B -m civsim.depot62_cli verify samples/phase6b1/seed0-warehouse
python -B -m experiments.depot_forks62 --out examples/phase6b1/forks
python -B -m experiments.depot_forks62 --out ../../work/repeat-b1-forks
python -B -m experiments.verify_archives31 --workers 3
python -B -m civsim.aid61 verify samples/phase6a1/seed0-capped
python -B -m unittest discover -v
```

원장 검증기의 4년 연간 SHA-256은 `5e4355591de7b43ad60f3969c9f9acf7abf926d540e180afa0d811f5e3843963`이다. 단년 비교는 공공 이송 허용·보류 순의 정규 JSON 두 행을 담았고, 새 프로세스에서 재생성한 세 압축 파일 해시도 모두 동일했다. 각 쌍에서 연초 상태의 불변성, 양쪽 외교 승인, 일반 경로와의 일치, 실제 계정 결산을 검사했다.

과거 280개 시드·정책 경로의 저장 시점 400개와 기존 대표 실행 원장 9개를 재검산했다. 별도로 6.0A.1 시드 0의 예산 상한 원장 해시 `b5683aecfce60fce74cccedebb43305bcfede4675186db7bd9458778da322c6b`를 재현했다. 새 A군의 과거 F군 대조 범위는 40개 시드 × 3개 시점이다. 과거 모든 중간 버전과 선택지의 200년 전 경로 재실행은 이번 검증에 포함되지 않았다.

모형은 정수 재고·운임·연간 도로 사용량을 계산한다. 한 해 안의 통행 순서에는 기존 제도의 우선순위가 있다. 주민 식량은 지역에서 합산되므로 특정 식사가 어느 송장의 원조였는지 식별할 수 없다. 각 단년 차이는 같은 연초의 정책 개입 효과이며 장기 시드 차이에는 후속 연도의 반응이 포함된다. [시스템 흐름도](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)
