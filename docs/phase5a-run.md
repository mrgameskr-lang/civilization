# 5.0A 실행 기록

PR #7의 기준은 `37935d78954b5c11de697257a8d38a4cb7a1d3c9`이다. 실험 계획은 `8097b5a`, 네 정책의 경제 규칙은 `75af26c`에서 고정했다. 실행 환경은 Windows 11 x64, CPython 3.12.14다. 개발·독립 검증은 공통 초기 세계에서 진행했고 출력 경로를 분리했다. [사전 계획](phase5a-protocol.md) · [실험 결과와 시드별 증거](phase5a-results.md)

## 직접 실행한 명령

아래 `python`은 같은 번들 CPython 실행 파일이다. 명령은 저장소 루트 기준이다. 기존 디렉터리에는 재발행할 수 없어 반복 실행에는 새 출력 이름이 필요하다.

```sh
python -B -m unittest discover -q
python -B -m unittest tests.test_government5 -q
python -B -m unittest discover -v
python -B -m civsim government --seed 7 --years 3 --policy integrated --out examples/phase5/seed7-integrated
python -B -m civsim verify examples/phase5/seed7-integrated
python -B -m civsim analyze examples/phase5/seed7-integrated --csv ../../work/phase5-sample-regions.csv
python -B -m cProfile -o ../../work/phase5-seed7.prof -m civsim government --seed 7 --years 50 --policy integrated --out ../../work/phase5-profile-seed7
python -B -m experiments.verify_archives31 --workers 3
python -B -m experiments.phase4 --seeds 20 --workers 4 --horizons 50,200 --out ../../work/phase5a-legacy4
```

기준 브랜치에서 기존 테스트 149개가 11.828초에 통과했다. 새 단일 연도 원장에 같은 국가 내 두 지역의 현금을 서로 바꾸는 위조를 넣자 초기 검사에서 놓쳤다. 국경 거래의 판매·구매 대금을 지역별로 재기표하는 수정 뒤 해당 테스트를 포함한 6개 통합 테스트가 통과했다. 정책 동결본의 전체 테스트 174개도 통과했다. 최종 테스트별 결과는 [전체 로그](phase5a-tests.txt)에 있다.

시드 7의 통합 정책 3년 전체 원장은 923,957바이트다. 저장 파일 전체 SHA-256과 재실행 결과가 `ea91ffa3f442b2c73ff6d1daf01bc05f75d5eea374410deb1855a7e9133c5293`로 일치했다. 시작 인구 74,762명, 기말 인구 76,516명, 미충족 식량 13,634, 실제 구호 165, 공공 운송비 24, 현지 공공 노동 28인년, 토양 사업 7건이었다. 정부 기말 재고는 식량 677, 광석 844, 도구 1,243이었다. [예제 원장](../examples/phase5/seed7-integrated)

이전 `examples`의 추적 파일 54개에 대해 PR #7 대비 Git 변경 목록은 비어 있었다. 기존 1.0~3.0 실험의 400개 체크포인트를 재생했고 4.0의 80개 경로 16,000년을 다시 실행했다. 4.0 CSV 5개와 사례 JSON 전체 바이트가 보관본과 같았다. 이번에 다시 실행한 범위와 3.1의 소스 동일성 검사는 [구버전 호환성 로그](phase5a-legacy.md)에 구분했다.

최종 전체 실행에서 **178개(기존 149개와 신규 29개)가 19.759초에 모두 통과**했다. 신규 검사에는 현지·원거리 배급, 용량 경쟁, 유지비 부족에 따른 개량 소멸, 공공 노동 이중 배정 방지, 창고 중복 집계, 예산·후보 점수·징수 구성 변조, 실패 연도의 원자성, 구버전 대조와 저장 결과의 재현이 포함된다. 독립 연도 검사에서 승인 메타데이터 위조가 드러나지 않았던 경우를 확인한 뒤, 기초 재고와 지도에서 가능한 후보·승인 예산을 다시 산출하는 읽기 전용 검사를 추가했다. 전년도 원장을 함께 제공하면 지연 관측도 직전 실현값과 대조한다. 이 변경은 `23d557d`에 있으며, `75af26c`에서 고정한 정책 규칙과 기록 숫자는 같다. [승인 검산](../civsim/appropriation_audit.py)

개발 시드의 첫해 현물세 효과를 별도 경로에 다시 계산했다. 기존 파일에 쓰는 시도는 종료 코드 1로 거절됐고 두 JSON의 SHA-256은 `035f2da3c2d95fe124b93a6a412f534dab6911e4f63dafef55c89d10acf48653`로 같았다. [실험 명령·경로·반례 원장](fiscal-tax-case5.md)

## 성능

공개한 본 실험은 네 정책과 40개 시드의 200년 경로 160개, 총 32,000세계연도다. 50·100·200년의 누적 원장 해시 480개를 보존했다. 독립 반복 32,000세계연도에서 480개가 모두 일치했으며 두 표본 각각 CSV 5개와 사례 JSON이 공개 파일과 바이트 단위로 같았다. 다음 명령의 실행 시간, 원자료와 SHA-256은 [본 실험 보고서](phase5a-results.md)에 수록했다.

```sh
python -B -m experiments.phase5a --sample dev --out examples/phase5/study/dev --workers 8
python -B -m experiments.phase5a --sample holdout --out examples/phase5/study/holdout --workers 8
python -B -m experiments.phase5a --sample dev --out ../../work/phase5-replay-dev --workers 8 --verify-against examples/phase5/study/dev
python -B -m experiments.phase5a --sample holdout --out ../../work/phase5-replay-holdout --workers 8 --verify-against examples/phase5/study/holdout
```

정책 동결 시점 코드에서 시드 7 통합 50년의 상세 원장 저장을 프로파일링했다. 6,148,763회 함수 호출에 프로파일러 집계 20.952초, 연도 처리 17.616초였다. 국내 수송의 지도·도로 초기화 `logistics._open`은 300회 4.851초, 민간 생산 3.372초, 생산 독립 감사 2.419초, 정규 JSON 직렬화 52회 2.212초였다. 누적 함수 시간은 서로 포함될 수 있다. 전체 연간 원장 파일은 15,418,516바이트였다. 이 시간은 병렬 연구 작업이 실행 중인 환경의 프로파일러 관측값이다. 더 큰 지도에서는 동일한 정적 도로의 경로 검증을 단계별로 반복하는 비용과 상세 원장 직렬화 크기를 따로 측정할 필요가 있다.

## 연동과 해석 범위

GitHub에서 PR #7을 확인하고 별도 검토 브랜치에 게시했다. Context7에서 CPython 3.12 표준 라이브러리의 dataclass 복사 API를 확인했다. 변경 가능한 재고·설비는 별도로 복사하여 실패한 해가 기존 상태를 바꾸지 않도록 했다. tldraw에 지역 창고·국가 장부·공사·구호·민간 도로의 흐름을 기록했다. 이번 단계는 경제 엔진으로 한정하여 Figma UI 작업은 수행하지 않았다. [CPython dataclasses 문서](https://docs.python.org/3.12/library/dataclasses.html#dataclasses.replace) · [tldraw 시스템 도식](https://www.tldraw.com/f/0bUzL9_Y5-sq8tpY7HMM6)

수송비·세금·정부 보유량은 재화 단위다. 평가 점수의 가격은 구매력이나 세수로 집계되지 않는다. 급여·가구별 소득·지역별 소득 분포·행정 인건비는 추정하지 않았다. 비축의 대비 점수는 경험적 휴리스틱이며 추가 재난을 생성한 스트레스 시험은 수행하지 않았다. 48×32, 8개국·32개 지역, 기존 기후와 국제시장 규칙, 200년을 넘는 일반화는 미검증이다.
