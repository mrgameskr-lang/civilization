# PR #4~#10 통합 상태

GitHub에서 일곱 PR이 모두 열려 있고 각 PR의 현재 기본·제안 브랜치 커밋이 아래와 같음을 확인했다. Git 객체로 매 단계 기본 커밋이 제안 커밋의 조상인지 확인했다. 각 제안 커밋을 별도 임시 폴더에 풀어 CPython 3.12.14에서 그 시점의 전체 테스트를 다시 실행했다. PR을 병합하거나 기준 브랜치의 참조를 이동하지 않았다.

| PR | 기본 브랜치 → 제안 브랜치 | 고정 헤드 | 기능과 변경 파일 수 | 재실행 테스트 | 물려받은 예제 파일 중 같은 Git blob | 마지막 PR CI |
|---|---|---|---|---:|---:|---|
| [#4](https://github.com/mrgameskr-lang/civilization/pull/4) | `main` → `phase3/productive-investment` | `64fcfeb` | 재투자·자본 마모와 200년 비교 (29) | 91/91 | 13/13 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44786974731) |
| [#5](https://github.com/mrgameskr-lang/civilization/pull/5) | `phase3/productive-investment` → `phase31/stability-investment` | `881469a` | 토양·투자 편향 반사실 (51) | 115/115 | 21/21 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44791216090) |
| [#6](https://github.com/mrgameskr-lang/civilization/pull/6) | `phase31/stability-investment` → `phase4a/regional-accounts` | `a8172b9` | 연결 지역과 국가 집계 (6) | 120/120 | 43/43 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44797700687) |
| [#7](https://github.com/mrgameskr-lang/civilization/pull/7) | `phase4a/regional-accounts` → `phase4b/regional-logistics` | `37935d7` | 지역 생산·유상 운송 (32) | 149/149 | 44/44 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44799024342) |
| [#8](https://github.com/mrgameskr-lang/civilization/pull/8) | `phase4b/regional-logistics` → `phase5a/public-finance` | `739a168` | 현물 재정·창고·공공사업 (50) | 178/178 | 54/54 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44807280330) |
| [#9](https://github.com/mrgameskr-lang/civilization/pull/9) | `phase5a/public-finance` → `phase5b/political-feedback` | `b7c2aaa` | 지역 정치 반응·도로 지표 정정 (75) | 198/198 | 74/74 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44869694312) |
| [#10](https://github.com/mrgameskr-lang/civilization/pull/10) | `phase5b/political-feedback` → `phase5c/representative-competition` | `c220dc5` | 대표 선거·집권 강령·세율 (65) | 222/222 | 119/119 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44873001280) |

#4의 기본은 `main@102dd33`이며 #5~#10은 바로 앞 PR의 헤드가 기본이었다. 매 단계 이전 `examples/`의 파일명과 blob을 전수 대조했다. 5.0B의 도로 보고 지표 정정도 새 출력 경로를 사용했다. 이 검사는 보관 파일의 동일성과 각 버전 테스트의 성공을 확인한다. 일곱 단계의 과거 장기 실험 행렬 전체를 여기서 다시 실행하지 않았다. [분리 실행 결과와 각 SHA](../examples/phase5d/pr-stack.json) · [검사 코드](../experiments/check_stack5d.py)

```sh
python -B -m experiments.check_stack5d --out examples/phase5d/pr-stack.json --workers 3
```

## 제안하는 수동 병합 순서

**#4 → #5 → #6 → #7 → #8 → #9 → #10 → 별도 검토한 5.0D** 순서다. 각 단계에서 승인된 헤드뿐 아니라 그 커밋의 이력을 보존하는 merge commit 또는 fast-forward를 권한다. 다음 단계는 직전 헤드가 실제로 `main`의 조상이 된 뒤 진행한다.

1. #4의 기본이 당시의 최신 `main`인지, 헤드가 검토한 SHA인지 확인하고 통합 후보의 CI를 통과시킨다. 기준이 이동했다면 새 차이와 호환성 검사를 먼저 확인한다.
2. 상위 PR을 병합한 뒤 다음 PR의 기본 브랜치를 `main`으로 명시적으로 바꾼다. 하위 PR 재지정이 끝날 때까지 상위 브랜치를 보존한다. 재지정한 PR의 비교 범위에 이미 병합한 기능이 다시 나타나지 않는지 확인한다.
3. 새 `main`과 다음 PR의 실제 통합 후보에서 전체 테스트·보관 예제 재생·당시 기준 파일의 blob 비교를 실행하고 그 PR을 별도로 승인한다. 이 단계를 #10까지 반복한다.
4. 저장소 정책상 squash/rebase 병합으로 커밋 ID가 달라지면 위 조상 검사가 성립하지 않을 수 있다. 다음 PR에서 **직전 검토 헤드 이후의 커밋만** 새 통합 브랜치 위에 다시 적용해 차이·CI·기존 원장을 재검토한다. 직전 커밋이 조상임을 전제한 일괄 병합을 진행하지 않는다.

실제 `main` 병합과 재지정 시점의 충돌, 이후에 생길 변경, 보호 규칙에 따른 최종 승인은 이번 작업에서 시험하지 않았다.
