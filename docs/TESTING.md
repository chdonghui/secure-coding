# 테스트 가이드

이 가이드는 자동 테스트, 관리자 전용 테스트, 의존성 검사와 문서 검증 방법을
정리합니다. 모든 명령은 저장소 루트에서 실행합니다.

## 테스트 데이터베이스 정책

- 실제 데이터가 들어 있는 DB와 빈 DB를 Git에 올리지 않습니다.
- 애플리케이션은 최초 실행 시 로컬 `market.db`와 스키마를 자동 생성합니다.
- pytest는 각 테스트의 `tmp_path`에 별도 SQLite DB를 생성합니다.
- 빠른 실행 데모는 운영체제 임시 디렉터리에 별도 DB를 만들고 종료 시
  삭제합니다.
- 테스트·빠른 실행 DB는 일반 실행용 `market.db`를 읽거나 변경하지 않습니다.
- `.gitignore`는 `*.db`, `*.sqlite`, `*.sqlite3`와 SQLite Journal 파일을
  제외합니다.

## 1. 테스트 환경 준비

최초 한 번:

```sh
conda env create -f enviroments.yaml
```

기존 환경 갱신:

```sh
conda env update -n secure_coding -f enviroments.yaml
```

활성화한 환경의 Python을 명시적으로 선택합니다.

```sh
conda activate secure_coding
SECURE_CODING_PYTHON="${CONDA_PREFIX}/bin/python"

"${SECURE_CODING_PYTHON}" --version
"${SECURE_CODING_PYTHON}" -m pip check
```

## 2. 전체 자동 테스트

```sh
conda activate secure_coding
SECURE_CODING_PYTHON="${CONDA_PREFIX}/bin/python"

"${SECURE_CODING_PYTHON}" -m pytest -q
```

모든 테스트가 통과해야 기능·보안·문서 변경을 완료한 것으로 봅니다. 현재 `v6.1`
기준 전체 결과는 `215 passed`입니다. 릴리스별
검증 개수와 결과는 [보안 변경 이력](SECURITY_CHANGELOG.md)에서 확인합니다.

## 3. 관리자 페이지 테스트

```sh
conda activate secure_coding
SECURE_CODING_PYTHON="${CONDA_PREFIX}/bin/python"

"${SECURE_CODING_PYTHON}" -m pytest -q \
  tests/test_admin_moderation_security.py
```

검증 범위:

- 비로그인·일반 사용자 관리자 접근 차단
- 관리자 상태 변경의 CSRF와 재인증
- 상품 관리 삭제와 증거 보존
- 사용자 휴면·재활성화와 HTTP·Socket 세션 차단
- 신고 완료·반려 처리와 추가 전용 검토 기록
- 관리자 역할 부여·해제와 감사 로그
- 관리자 내 상품 관리·전체/1대1 채팅 메뉴와 서버 경로 차단, 신고 접수함,
  상품 관리 삭제 사유·현재 비밀번호 검증
- 관리자 자신·다른 관리자 보호와 작업 속도 제한

## 4. 빠른 실행 도구 테스트

```sh
conda activate secure_coding
SECURE_CODING_PYTHON="${CONDA_PREFIX}/bin/python"

"${SECURE_CODING_PYTHON}" -m pytest -q \
  tests/test_quickstart_demo.py
```

임시 DB 권한, 관리자 1명·일반 사용자 2명 생성, Argon2id 비밀번호 해시,
학습용 송금 잔액, 샘플 상품·신고, 감사 기록과 외래키 무결성을 확인합니다.
샘플 상품은 두 일반 사용자가 각각 판매하는 `사과 한 상자`와
`바나나 한 송이`입니다.

## 5. 기능별 테스트

| 범위 | 테스트 파일 |
|---|---|
| 회원·로그인·프로필 | `tests/test_account_security.py` |
| 회원 탈퇴 | `tests/test_account_deletion_security.py` |
| 상품 | `tests/test_product_security.py` |
| 신고 | `tests/test_report_security.py` |
| 송금 | `tests/test_transfer_security.py` |
| 구매·주문 | `tests/test_purchase_security.py` |
| 전체 채팅 | `tests/test_chat_security.py` |
| 1대1 채팅 | `tests/test_direct_chat_security.py` |
| 관리자 | `tests/test_admin_moderation_security.py` |
| DB 백업 | `tests/test_database_backup.py` |
| 빠른 실행 데모 | `tests/test_quickstart_demo.py` |
| 사업자 역할 | `tests/test_business_role_security.py` |

회원가입 테스트는 기존 빠른 실행 계정 중복, 신규 계정의 일반 사용자 고정과
동시성 UNIQUE 충돌 처리를 확인합니다. 회원 탈퇴 테스트는 일반 사용자의 탈퇴와
관리자·사업자 계정의 메뉴·서버 경로 차단을 확인합니다.

구매·주문 테스트는 구매자 인증, 판매자 입금, 잔액 부족, 중복 구매, 판매 완료
상품 비노출, 관리자 차단, 주문 원장 UPDATE·DELETE 차단을 확인합니다.

특정 파일만 실행하는 예시:

```sh
"${SECURE_CODING_PYTHON}" -m pytest -q \
  tests/test_product_security.py
```

## 6. 의존성 보안 검사

```sh
"${SECURE_CODING_PYTHON}" -m pip check
"${SECURE_CODING_PYTHON}" -m pip_audit \
  --require-hashes \
  -r requirements.lock
```

## 7. 문서와 Git 변경 검증

```sh
git diff --check
git diff
git status --short
```

실제 DB, 임시 DB, 비밀번호, 세션 비밀키, API 토큰과 개인정보가 변경 목록에
포함되지 않았는지 확인합니다.
