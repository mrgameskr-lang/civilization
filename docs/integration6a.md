# 열린 PR의 독립 통합 검증

2026-11-21 GitHub에서 #4~#11의 대상·소스 브랜치와 커밋, 열린 상태, 병합 여부, 변경 파일 수, 최근 CI 결과를 조회했다. 8건 모두 열려 있고 병합 전이었다. #4의 기준은 main의 `102dd33`이며 이후 각 기준 커밋은 바로 앞 PR의 소스 커밋과 같다.

| PR | 대상 → 소스 브랜치 | 검증 커밋 | 변경 파일 | 독립적으로 통과한 테스트 | 물려받아 보존한 예제 파일 | 기존 CI |
|---|---|---|---:|---:|---:|---|
| [#4](https://github.com/mrgameskr-lang/civilization/pull/4) | `main` → `phase3/productive-investment` | `64fcfeb` | 29 | 91 | 13 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44786974731) |
| [#5](https://github.com/mrgameskr-lang/civilization/pull/5) | `phase3/productive-investment` → `phase31/stability-investment` | `881469a` | 51 | 115 | 21 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44791216090) |
| [#6](https://github.com/mrgameskr-lang/civilization/pull/6) | `phase31/stability-investment` → `phase4a/regional-accounts` | `a8172b9` | 6 | 120 | 43 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44797700687) |
| [#7](https://github.com/mrgameskr-lang/civilization/pull/7) | `phase4a/regional-accounts` → `phase4b/regional-logistics` | `37935d7` | 32 | 149 | 44 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44799024342) |
| [#8](https://github.com/mrgameskr-lang/civilization/pull/8) | `phase4b/regional-logistics` → `phase5a/public-finance` | `739a168` | 50 | 178 | 54 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44807280330) |
| [#9](https://github.com/mrgameskr-lang/civilization/pull/9) | `phase5a/public-finance` → `phase5b/political-feedback` | `b7c2aaa` | 75 | 198 | 74 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44869694312) |
| [#10](https://github.com/mrgameskr-lang/civilization/pull/10) | `phase5b/political-feedback` → `phase5c/representative-competition` | `c220dc5` | 65 | 222 | 119 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44873001280) |
| [#11](https://github.com/mrgameskr-lang/civilization/pull/11) | `phase5c/representative-competition` → `phase5d/collective-action` | `a4721bd` | 70 | 242 | 150 | [성공](https://github.com/mrgameskr-lang/civilization/actions/runs/44875879753) |

각 커밋의 파일을 별도 작업 폴더에 풀고 해당 커밋의 전체 테스트를 실행했다. 각 단계의 이전 예제 Git blob에서 변경·삭제가 0개였다. `git merge-tree --write-tree BASE HEAD`로 얻은 통합 트리는 각 테스트 대상의 트리와 일치했다. 실행 시각과 이후 원격 브랜치 변경으로 결과가 달라질 수 있다. [전체 커밋·트리·소요 시간](../examples/phase6a/pr-stack.json) · [독립 실행기](../experiments/check_stack6a.py)

## 사용자 승인 이후 적용할 순서

1. 원격 브랜치와 PR의 최신 상태를 새로 읽고 위 커밋 및 기준 관계를 대조한다. 달라진 항목은 새 후보로 검증한다.
2. 임시 통합 브랜치에서 #4 → #5 → #6 → #7 → #8 → #9 → #10 → #11 → 6.0A 순서로 한 단계씩 통합을 예행한다. GitHub의 이전 PR 소스 브랜치를 다음 PR 기준으로 쓰므로 선행 브랜치가 자동 삭제되지 않는지도 확인한다.
3. 단계마다 실제 통합 후보에서 전체 테스트, 상속 원장의 Git blob 대조, 예제 재생을 수행한다. 최종 후보에서는 과거 실행 해시와 A/B 대조 및 6.0A 재생 해시를 검증한다. 운영체제별 CI와 계산 결과를 원격에 올린 후보의 SHA에 연결한다.
4. 충돌이나 해시 차이가 생기면 최초로 어긋난 단계에서 원인을 기록하고 수정 후보를 다시 검증한다. 병합 전략이 새 커밋을 만들거나 이전 PR이 닫혀 기준 관계가 바뀌면 최신 후보로 1~3을 반복한다.
5. 실제 병합과 기준 변경은 검증 결과와 함께 사용자 승인 대상으로 둔다. 이번 작업은 새 기능 브랜치에서 PR #11의 소스 브랜치를 대상으로 제출한다.

```sh
python -B -m experiments.check_stack6a --out examples/phase6a/pr-stack.json --workers 3
```

명령은 새 출력 경로에만 쓸 수 있다. 이미 공개된 결과를 재검증할 때는 `--out`에 새 경로를 준다.
