# 6.0B2 평시 복무 검토 안내

**전체 테스트 346개 통과.** Windows·Python 3.12.14에서 B1의 336개와 B2의 추가 10개를 모두 실행했다. 소요시간은 137.272초다. 네 정책의 과학 파일 48개가 독립 반복과 바이트 단위로 같았고, A의 과거 6.0A.1 F 원장도 120/120개 시점에서 일치했다. 기준 PR #14의 추적 파일 493개는 Git 객체와 파일 모드가 같다. [최종 테스트 로그](../examples/phase6b2/full-tests.txt) · [표본별 실행 시간과 원자료](phase6b2-study.md)

원자료를 생성한 본실험과 독립 반복에서 각각 32,000세계연도를 계산했다. 그 뒤 별도의 지리·회계 검산으로 32,000세계연도를 다시 계산했다. 160개 경로 × 3개 시점의 누적 원장 해시 480개가 모두 일치했다. C/D의 최종 명령은 `python -B -m experiments.verify_public62 --stage B2 --workers 5 --out examples/phase6b2/final-audit.json`이며 1,001.044초가 걸렸다. 공식 연간 지역행은 1,024,000개이고 A~D의 압축 파일 및 결과표 크기는 합계 198,643,975바이트다. 실행 시간에는 각 경로의 검산이 포함되며 함수별 소요시간은 측정하지 않았다. [B2 감사 영수증](../examples/phase6b2/final-audit.json) · [B1 감사 영수증](../examples/phase6b1/final-audit.json)

6.0B1에 두 선택형 정책을 더한다. C는 배정 가능한 노동의 24‰를 목표로 하고 D는 연초 경제·외교·정치 관측값으로 국가 총원 목표를 정한다. 같은 시드에서 A·B·C·D의 초기 상태가 같아야 실행을 승인한다. C와 D 규칙을 별도 커밋 `a4ef279`로 고정한 다음 두 표본을 실행했다.

- [인구·노동·급식·도구·도로 수식](service62.md) · [실제 코드](../civsim/service62.py) · [연간 실행 순서](../civsim/peace62.py)
- [정책별 장기 통계와 반례](phase6b2-results.md) · [지역·국가·이동·정책·도로 원자료 사전](../examples/phase6b2/study/README.md)
- [신규 모집 보류 반사실 2쌍](../examples/phase6b2/forks) · [4년 연속 원장](../samples/phase6b2/seed0-service) · [B1의 호환성·반사실](phase6b1-review.md)

주민 등록과 근무지 출근을 구분한다. 출근한 인원은 당년 주소지의 민간 생산·공공사업 노동에서 빠지고, 왕복 도로 용량과 주소지 창고의 운임을 사용한다. 기말 인구는 주민 장부에서 한 번만 센다. 공공창고 지급 식량은 기존 주민 수요를 충당하며, 비용에는 실제 운임 및 실제 근무지의 소모 도구도 포함된다. 근무 중 필요한 식량·도구를 모두 확보한 사람 수를 가용 인원으로 기록한다. 기존 정치 모델은 생활 조건과 공공정책의 변화에 반응한다.

```powershell
python -B -m civsim.peace62_cli run --seed 0 --years 4 --arm D --out samples/phase6b2/seed0-service
python -B -m civsim.peace62_cli verify samples/phase6b2/seed0-service
python -B -m experiments.peace_forks62 --out examples/phase6b2/forks
python -B -m experiments.peace_forks62 --out ../../work/repeat-b2-forks
python -B -m unittest discover -v
```

장기 실험에서 표본별 B1 기준 원자료와 초기 상태 해시를 확인한 뒤 다음 인수로 실행했다. 두 표본은 서로 다른 저장 경로에서 병행했다.

```powershell
foreach ($sample in 'dev','holdout') {
    python -B -m experiments.phase6b2 --sample $sample --reference examples/phase6b1/study/$sample --workers 3 --out examples/phase6b2/study/$sample
    python -B -m experiments.phase6b2 --sample $sample --reference examples/phase6b1/study/$sample --workers 5 --out ../../work/phase6b2-repeat-$sample --verify-against examples/phase6b2/study/$sample
}
```

4년 연간 원장의 검증 해시는 `7fb4dea84b05f2545ddf210a68d6431d23f0dfa9bd916278201d30f9e35414f7`이다. 시드 0의 1년차와 3년차를 두 번 독립 실행했고 양쪽 단년 원장 압축 파일의 해시가 모두 일치했다. 연초 정책·주민·창고와 기존 명부를 고정한 상태에서 그해 신규 등록만 보류했다. 연말의 인구와 섭취가 실제로 같거나 달라지는 경우를 각각 보관했다.

이 모형의 지역 근무는 한 해 안에 국내 인접 도로로 왕복한다. 장기 이전 주둔, 가족 동반 이동, 급여, 장비 종류, 전투 능력은 계량 범위 밖이다. 식사가 주민 계정에 합산되므로 특정 개인이 어떤 식량을 먹었는지는 식별할 수 없다. 모형의 정책 계수와 40개 시드에 관한 실험이므로 다른 지형·계수로의 일반화는 별도 검증이 필요하다.
