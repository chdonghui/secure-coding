# 소프트웨어 개발 주기 현황

이 문서는 현재 `v5.1` 구현을 기준으로 요구사항 도출부터 유지보수까지의
개발 주기와 확인 결과를 정리합니다. 프로젝트는 실제 금융·상거래 서비스가
아닌 웹 보안 교육·실습용 애플리케이션입니다.

## 1. 요구사항 도출

### 사용자 기능

- 회원가입, 로그인, 프로필 및 회원 탈퇴
- 공개 상품 목록·상세 조회와 로그인 사용자의 상품 등록·수정·삭제
- 상품 구매, 결제 완료 주문 생성, 구매자·판매자 주문 내역 조회
- 일반 사용자 간 학습용 송금과 양방향 잔액 이동
- 전체 채팅과 사용자 간 1대1 채팅
- 사용자·상품 신고

### 관리자 기능

- 관리자 전용 통합 페이지
- 신고 검토와 완료·반려 처리
- 불량 상품 관리 삭제
- 사용자 휴면·재활성화
- 관리자 작업 감사 기록
- 관리자 계정은 송금·구매·주문 내역 기능에서 제외

### 보안·운영 요구사항

- 서버 측 입력 검증, 파라미터 바인딩, 출력 자동 이스케이프
- 비밀번호 Argon2id 해시 저장
- CSRF, 세션 만료, 민감 작업 재인증
- 송금·구매의 잔액 부족, 중복 요청, 권한 우회 방어
- SQLite 테스트 DB 격리와 임시 빠른 실행 계정
- 실제 결제·은행 계좌·배송·환불 시스템은 범위에서 제외

## 2. 시스템 설계

### 구성

- Flask 웹 애플리케이션과 Flask-SocketIO 실시간 통신
- SQLite 단일 로컬 DB
- Jinja 템플릿 기반 서버 렌더링
- Argon2id 비밀번호 해시와 세션 기반 인증
- pytest 기반 기능·보안 회귀 테스트

### 주요 데이터 흐름

```text
상품 상세
  → 구매 요청(CSRF·현재 비밀번호)
  → BEGIN IMMEDIATE
  → money_transfer(구매자 차감·판매자 입금)
  → purchase_order(status=paid)
  → 상품 판매 완료·주문 내역 표시
```

### 핵심 데이터 구조

| 영역 | 테이블 또는 구성 | 목적 |
|---|---|---|
| 사용자 | `user`, `user_dormancy` | 계정·관리자 역할·휴면 상태 |
| 상품 | `product`, `product_moderation` | 상품과 관리 삭제 상태 |
| 지갑 | `wallet_account`, `wallet_adjustment` | 사용자별 학습용 잔액 |
| 송금 | `money_transfer` | 추가 전용 사용자 간 잔액 이동 |
| 주문 | `purchase_order` | 상품·구매자·판매자·결제 완료 원장 |
| 감사·제한 | `*_audit`, `security_rate_limit` | 관리자 작업과 남용 방지 |

구매는 송금 원장과 주문 원장을 한 트랜잭션에서 생성합니다. `purchase_order`의
상품 ID는 UNIQUE이며 주문 완료 레코드는 DB Trigger로 수정·삭제할 수 없습니다.

## 3. 시스템 구현

### 구현된 화면과 경로

- 상품 목록: `/products`
- 상품 상세·구매: `/product/<product_id>`
- 주문 내역: `/orders`
- 사용자 송금: `/transfers`
- 상품 관리: `/products/manage`
- 프로필·계정 관리: `/profile`
- 1대1 채팅: `/chat`
- 신고: `/report`
- 관리자 페이지: `/admin`

### 구매·주문 구현

- 일반 사용자만 구매 가능
- 상품 상세에서 현재 학습용 잔액과 가격 확인
- 현재 비밀번호와 CSRF 재검증
- 구매자 잔액 부족 시 거래와 주문 모두 롤백
- 구매 완료 상품은 공개 목록에서 제외
- 판매자는 판매 완료 상품을 수정할 수 없음
- 구매자와 판매자 모두 `/orders`에서 `결제 완료` 내역 확인
- 관리자 계정은 구매·주문 내역에 접근할 수 없음

### 빠른 실행 데이터

`./scripts/quickstart_demo.sh`로 다음 계정을 임시 생성합니다.

- `quick_admin`: 관리자
- `user1`, `user2`: 일반 사용자
- 두 일반 사용자에게 각각 100,000원 학습용 잔액
- `사과 한 상자`, `바나나 한 송이` 테스트 상품

## 4. 테스팅

### 자동 검증

권장 `secure_coding` 환경에서 다음 검증을 수행합니다.

```sh
conda activate secure_coding
SECURE_CODING_PYTHON="${CONDA_PREFIX}/bin/python"
MARKET_SECRET_KEY='test-only-secret-key-at-least-32-chars' \
  "${SECURE_CODING_PYTHON}" -m pytest -q
"${SECURE_CODING_PYTHON}" -m pip check
git diff --check
```

현재 결과:

- 전체 테스트 `208 passed`
- `pip check`: broken requirements 없음
- 구매 테스트: 정상 구매, 잔액 부족, 잘못된 비밀번호, 중복 구매,
  관리자 차단, 판매 완료 비노출, 주문 원장 변조 차단
- 송금 테스트: 양방향 이동, CSRF·재인증, 관리자 참여 차단,
  잔액·멱등성·Rate Limit·DB Trigger

상세 테스트 명령은 [TESTING.md](TESTING.md), 보안 검증 이력은
[SECURITY_CHANGELOG.md](SECURITY_CHANGELOG.md)에서 확인합니다.

## 5. 유지보수

### 현재 유지보수 정책

- 버전별 기능은 [FEATURE_CHANGELOG.md](FEATURE_CHANGELOG.md)에 기록
- 보안 조치와 회귀 결과는 [SECURITY_CHANGELOG.md](SECURITY_CHANGELOG.md)에 기록
- 현재 보안 상태는 [SECURITY_REVIEW.md](SECURITY_REVIEW.md)에서 관리
- 스키마 변경은 `init_db()`의 생성·마이그레이션과 테스트 DB로 검증
- 실제 DB·테스트 DB·임시 DB는 Git에 포함하지 않음
- 기능 변경 후 전체 pytest, `pip check`, `git diff --check` 수행

### 세션·계정 간 인수인계 규칙

다른 세션이나 계정에서 작업을 이어갈 때는 다음 순서를 지킵니다.

1. `git status --short`와 `git diff`로 기존 변경을 확인합니다.
2. 이 문서의 현재 구현·한계와 `README.md`, 기능·보안·버전 문서를 읽습니다.
3. 실제 코드와 테스트를 확인한 뒤 작업 범위를 정합니다.
4. 작업 중 변경된 기능·권한·DB·UI의 관련 문서를 즉시 갱신합니다.
5. 정상·실패·보안 회귀 테스트와 `git diff --check`를 실행합니다.
6. 완료 항목, 미완료 항목, 테스트 결과, 다음 작업을 이 문서의 유지보수 항목에
   기록합니다.

작업을 커밋하지 않은 상태로 끝내는 경우에도 변경 파일과 검증 결과를 남겨야
하며, 다음 세션은 이전 작업을 임의로 되돌리거나 덮어쓰지 않습니다.

### 알려진 한계와 다음 작업

현재 구현은 학습용 내부 원장만 사용합니다. 외부 결제, 카드 승인, 웹훅, 배송,
취소·환불, 재고, 수수료, 정산, 분쟁 처리는 구현하지 않았습니다.

다음 UX 개선 작업은 아직 남아 있습니다.

1. 상품 UX: 카테고리·이미지·고급 필터와 주문 취소·환불 화면
2. 역할 모델: 현재 `is_admin` 중심이므로 별도 `business` 계정 타입과 사업자
   등록·승인 흐름 설계
3. 관리자 UX: 통합 관리자 페이지를 상품·사용자·신고·감사 탭 또는 별도 화면으로
   분리하고 검색·필터·작업 확인 단계를 추가 (현재 섹션 바로가기는 제공)

실제 운영 전에는 운영 DB·중앙 Rate Limit·로그 보호·TLS 종료·백업 복구·외부
원장 대사와 법률·KYC/AML 검토가 별도로 필요합니다.
