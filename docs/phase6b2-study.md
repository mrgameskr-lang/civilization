# 평시 복무 비교 실험의 측정 범위

개발 시드 0~19와 독립 검증 시드 20~39에서 같은 세계의 고정 복무 C와 적응형 복무 D를 200년 실행한다. 각 경로의 초기 SHA-256이 B1의 같은 시드와 일치해야 한다. B1 `runs.csv`의 해시와 표본·기간·행 수도 대조한다. 50·100·200년의 C−B, D−C, D−B뿐 아니라 B−A, C−A, D−A를 같은 시드끼리 계산한다. B2 보고서가 참조하는 A/B는 앞서 실행해 독립 재생한 실제 값이다. [사전 계획](phase6b-protocol.md) · [B1 연구 자료](phase6b-study.md) · [B2 자료 사전](../examples/phase6b2/study/README.md)

목표 규모, 실제 명부, 급식·도구를 지급받은 인원과 민간 산출은 별도 열이다. 계량의 주소지는 원래 거주 지역이다. 다른 근무지에서 일한 인원은 그곳의 도구 사용과 도로 운임에 영향을 주며 새로운 거주민으로 더하지 않는다. 등록·해제·등록자 중 사망·전출로 갱신한 명부가 실제 기말 명부와 일치해야 한다. 한 해의 철회 노동, 공공 사업, 복무, 참여 가능한 생산·건설·토양 노동 합이 주민의 노동 예산과 맞는지도 지역별로 검산한다.

저장된 `service-policy.csv.gz`는 각 국가가 결정 전에 알 수 있었던 외교 관계·국경의존·직전 위반·국내 식량·집단 선호·정파·예상 생산비용과 선택한 목표를 잇는다. `service-moves.csv.gz`는 실제 국내 이동의 인원·거리·운임·왕복 도로 사용을 보존한다. 회계 검산은 급식이 주민의 원래 식사 안에서 소비되고, 이동 운임과 도구가 쓰인 지역 정부창고에서 차감됐는지 확인한다. [실험 결과와 한계](phase6b2-results.md)

## 실행과 자료 대조

저장소 루트에서 아래 명령을 실행했다. `SAMPLE`에는 `dev` 또는 `holdout`을 넣는다. 시드 수와 관측 연도는 각각 기본값 20과 50·100·200을 사용했다.

```text
python -B -m experiments.phase6b2 --sample SAMPLE --reference examples/phase6b1/study/SAMPLE --workers 3 --out examples/phase6b2/study/SAMPLE
python -B -m experiments.phase6b2 --sample SAMPLE --reference examples/phase6b1/study/SAMPLE --workers 5 --out ../../work/phase6b2-repeat-SAMPLE --verify-against examples/phase6b2/study/SAMPLE
```

두 표본 각각 8,000세계연도를 실행했다. 개발 877.500초, 독립 검증 866.756초가 걸렸다. 각 표본당 3개 작업자가 동작했고 초반에는 B1 반복과 CPU를 공유했다. 두 표본의 B1 참조 240행은 앞서 게시한 A·B 체크포인트와 일치했다. [개발 실행 확인서](../examples/phase6b2/study/dev/execution.json) · [독립 검증 실행 확인서](../examples/phase6b2/study/holdout/execution.json)

새 프로세스에서 표본당 5개 작업자로 다시 실행했다. 개발은 961.932초, 독립 검증은 967.398초가 걸렸다. 240개 연간 원장 체크포인트 해시가 모두 일치했다. 원본과 반복의 과학 파일 26개를 바이트 단위로 대조했다. 실행 확인서를 제외한 표의 크기는 개발 54,526,517바이트, 독립 검증 54,468,327바이트다. 두 표본은 CPU를 공유했으며 위 시간에는 결과표 작성과 압축도 포함된다. [개발 반복 확인서](../examples/phase6b2/study/replay-dev.json) · [독립 검증 반복 확인서](../examples/phase6b2/study/replay-holdout.json)
