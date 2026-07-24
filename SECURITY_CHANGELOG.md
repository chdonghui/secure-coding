# 버전별 보안 조치

이 문서는 각 버전에서 적용한 보안 조치와 검증 결과를 버전별로 기록합니다.
최신 버전을 위에 두며, 모든 버전은 동일한 구조로 작성합니다.

## 문서 안내

| 문서 | 역할 |
|---|---|
| `README.md` | 현재 버전과 설치·실행 방법 |
| `FEATURE_CHANGELOG.md` | 버전별로 추가·변경·제거한 기능 설명 |
| `SECURITY_CHANGELOG.md` | 버전별로 적용한 보안 조치와 테스트 이력 |
| `SECURITY_REVIEW.md` | 현재 코드 기준 전체 보안 체크리스트와 남은 작업 |
| `VERSIONING.md` | 버전 결정과 필수 커밋 절차 |

## 버전 빠른 보기

| Version | Date | 주요 보안 범위 | 검증 |
|---|---|---|---|
| `3.0` | `2026-07-24` | 관리자 역할 기반 상품·사용자 제재와 감사 무결성 | 자동 테스트 167개 통과 |
| `2.1` | `2026-07-24` | 안전한 회원 탈퇴와 공개 상품 조회 권한 분리 | 자동 테스트 155개 통과 |
| `2.0` | `2026-07-24` | 1대1 채팅 권한 격리, 메시지 무결성 및 비공개 전달 | 자동 테스트 145개 통과 |
| `1.7` | `2026-07-24` | 본인 등록 상품 관리와 판매자별 조회 격리 | 자동 테스트 119개 통과 |
| `1.6` | `2026-07-24` | 본인 마이페이지 조회·소개글·비밀번호 변경과 세션 무효화 | 자동 테스트 117개 통과 |
| `1.5` | `2026-07-24` | Socket 인증·메시지 검증·채팅 남용 및 연결 보호 | 자동 테스트 108개 통과 |
| `1.4` | `2026-07-24` | 신고 시도 제한·실패 감사·개인정보 차단과 DB 백업 검증 | 자동 테스트 88개 통과 |
| `1.3` | `2026-07-24` | 신고 접수 검증, 남용 방지, 참조 무결성 및 감사 로그 | 자동 테스트 72개 통과 |
| `1.2` | `2026-07-24` | 상품 등록·수정·삭제, 소유권 및 상품 데이터 무결성 강화 | 자동 테스트 45개 통과 |
| `1.1` | `2026-07-24` | 회원가입, 로그인, 세션 및 프로필 보안 강화 | 자동 테스트 18개 통과 |
| `1.0` | `2026-07-24` | 기반 코드 점검과 최초 취약점 식별 | 정적 점검 |

표기:

- ✅: 해당 버전에서 적용 및 검증 완료
- ⚠️: 일부 방어만 존재하거나 후속 개선 필요
- ❌: 해당 버전에서 미적용
- N/A: 해당 버전에 기능이 없음

---

## Version 3.0

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `3.0` |
| Date | `2026-07-24` |
| 변경 유형 | Major Version |
| 적용 범위 | 관리자 역할, 불량 상품 관리 삭제, 사용자 휴면·해제, 제재 감사 |
| 테스트 | 기존 보안 테스트, `tests/test_admin_moderation_security.py` |
| 테스트 결과 | `167 passed` |

관리자 권한 체계와 서비스 전체 노출·인증 상태를 변경하는 핵심 관리 기능이므로
Versioning 규칙에 따라 Major Version을 증가시켰습니다.

### 조치 전후 요약

| 항목 | Version 2.1 | Version 3.0 |
|---|---|---|
| 관리자 역할 | ❌ 없음 | ✅ DB 역할과 관리자 전용 접근 제어 |
| 관리자 지정 | ❌ 없음 | ✅ 활성 사용자 대상 로컬 CLI |
| 불량 상품 삭제 | ⚠️ 소유자 물리 삭제만 제공 | ✅ 관리자 논리 삭제와 신고 증거 보존 |
| 불량 사용자 | ❌ 제재 기능 없음 | ✅ 휴면·해제와 로그인·기능 차단 |
| 기존 세션 | ❌ 관리자 제재 없음 | ✅ 휴면 즉시 HTTP 세션 버전 변경·Socket 종료 |
| 관리자 보호 | ❌ 역할 없음 | ✅ 자신·다른 관리자 휴면 차단 |
| 처리 감사 | ⚠️ 신고 접수 감사만 존재 | ✅ 제재 처리자·대상·사유·시각 추가 전용 기록 |
| 공개 노출 | ❌ 제재 상태 없음 | ✅ 제재 상품·휴면 사용자 상품을 전체 공개 기능에서 제외 |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V3.0-ADMIN-RBAC-01` | 역할 접근 제어 | 요청마다 DB의 `is_admin=1`을 확인해 관리자 화면·API 보호 | `admin_required` |
| `V3.0-ADMIN-BOOTSTRAP-01` | 명시적 역할 부여 | 기존 계정은 일반 사용자로 유지하고 로컬 CLI에서만 권한 변경 | `scripts/admin_user.py` |
| `V3.0-ADMIN-CSRF-01` | 상태 변경 보호 | 상품 삭제·휴면·해제를 POST와 CSRF Token으로 처리 | 관리자 제재 라우트·템플릿 |
| `V3.0-ADMIN-INPUT-01` | 사유 검증 | NFKC, 10~500자, 제어 문자·개인정보 차단 | `validate_moderation_reason` |
| `V3.0-PRODUCT-REMOVE-01` | 관리 삭제 | 제재 테이블 행으로 상품을 서비스 전체에서 비노출 | `admin_remove_product`, 상품 Query |
| `V3.0-PRODUCT-EVIDENCE-01` | 증거 보존 | 상품·신고 원본을 유지하고 관리 삭제 레코드를 추가 | `product_moderation` |
| `V3.0-PRODUCT-APPEND-01` | 제재 무결성 | 상품 제재 UPDATE·DELETE를 Trigger로 차단 | `prevent_product_moderation_*` |
| `V3.0-USER-DORMANT-01` | 사용자 휴면 | 일반 사용자만 휴면 처리하고 활성 사용자 Query에서 제외 | `admin_dormant_user`, `user_dormancy` |
| `V3.0-USER-SESSION-01` | 세션 차단 | 휴면 시 세션 버전을 원자적으로 증가시키고 Socket 종료 | `admin_dormant_user`, `disconnect_user_sockets` |
| `V3.0-USER-REACTIVATE-01` | 안전한 복구 | 관리자 사유와 감사 기록 후 휴면 해제, 과거 세션은 계속 무효 | `admin_reactivate_user` |
| `V3.0-ADMIN-PROTECT-01` | 관리자 보호 | 관리자 자신과 다른 관리자의 휴면을 애플리케이션·DB에서 차단 | 휴면 라우트·검증 Trigger |
| `V3.0-AUDIT-01` | 제재 감사 | 처리자·Action·대상·사유·시각을 제재와 같은 트랜잭션에 저장 | `add_admin_action_audit` |
| `V3.0-AUDIT-02` | 감사 변조 방지 | 관리자 감사 UPDATE·DELETE를 Trigger로 차단 | `prevent_admin_action_audit_*` |
| `V3.0-DB-AUTH-01` | DB 우회 방어 | 제재·감사 INSERT에서도 활성 관리자 역할을 Trigger로 확인 | `validate_*_admin` Trigger |
| `V3.0-XSS-01` | 안전한 출력 | 상품·사용자·감사 사유를 Jinja 자동 이스케이프로 출력 | `templates/admin_moderation.html` |

상품 관리 삭제는 신고된 상품의 외래키와 감사 증거를 보존하는 논리 삭제입니다.
소유자 물리 삭제와 달리 `product_moderation` 레코드를 추가하고 상품 원본은
유지합니다. 휴면 사용자는 삭제 사용자가 아니므로 관리자 재검토 후 복구할 수
있지만 휴면 전에 발급된 세션은 다시 유효해지지 않습니다.

### 데이터베이스 변경과 마이그레이션

`user` 테이블에 역할 컬럼을 추가했습니다.

| 컬럼 | 타입·제약 | 기본값·용도 |
|---|---|---|
| `is_admin` | `INTEGER NOT NULL`, `0` 또는 `1` | `0`, 관리자 역할 |

새 관리 테이블:

| 테이블 | 용도 |
|---|---|
| `product_moderation` | 관리 삭제 상품·관리자·사유·시각 |
| `user_dormancy` | 현재 휴면 사용자·관리자·사유·시각 |
| `admin_action_audit` | 상품 삭제·휴면·해제의 영구 감사 이력 |

무결성:

- 세 테이블의 관리자·대상은 사용자·상품 외래키로 연결됩니다.
- 상품 제재와 관리자 감사 로그는 UPDATE·DELETE Trigger로 추가 전용입니다.
- 제재·감사 INSERT Trigger가 활성 관리자 역할을 다시 확인합니다.
- 사용자 휴면 Trigger가 관리자 자신과 다른 관리자 제재를 차단합니다.
- 관리자 감사 생성 시각 인덱스로 최근 이력을 조회합니다.

마이그레이션 동작:

1. 기존 `user`에 `is_admin`이 없으면 제약·기본값과 함께 추가합니다.
2. 기존 사용자는 모두 `is_admin=0`을 유지합니다.
3. 관리 테이블이 없으면 현재 제약과 외래키로 생성합니다.
4. 기존 동명 비호환 테이블이 있으면 초기화를 중단합니다.
5. Trigger와 감사 조회 인덱스를 재현 가능하게 생성합니다.
6. 운영자가 CLI로 신뢰하는 활성 사용자에게만 역할을 부여합니다.

로컬 DB는 마이그레이션 전에 저장소 밖에 권한 `600`으로 백업했습니다.
마이그레이션 후 `PRAGMA integrity_check`는 `ok`, 외래키 위반은 0건이며
`market.db` 권한도 `600`입니다. DB와 백업은 Git에 포함하지 않습니다.

### 템플릿·도구·의존성·환경변수 변경

- `templates/admin_moderation.html`
  - 상품·사용자 신고 수와 최소 공개 정보
  - CSRF 보호 상품 관리 삭제·휴면·해제 Form
  - 최근 관리자 감사 이력
- `templates/base.html`: 관리자 역할 사용자에게만 제재 메뉴 표시
- `scripts/admin_user.py`
  - 활성 관리자 목록
  - 활성 일반 사용자 관리자 권한 부여
  - 마지막 활성 관리자 권한 해제 차단
- `tests/test_admin_moderation_security.py`: 관리자 기능·권한·DB 테스트 12개

새 Python 의존성과 환경변수는 없습니다.

### 검증 결과

실행 명령:

```sh
conda activate secure_coding
python -m pytest -q
git diff --check
```

결과:

```text
167 passed
```

검증한 주요 시나리오:

- 비로그인·일반 사용자 관리자 화면과 API 접근 차단
- 관리자 API CSRF Token 누락 차단
- 관리 사유 길이·제어 문자·개인정보 검증
- 신고된 상품 관리 삭제 후 공개·상세·소유자 관리 비노출
- 상품·신고 원본과 처리 감사 증거 보존
- 관리자 감사 사유의 저장형 XSS 이스케이프
- 사용자 휴면 즉시 기존 HTTP·Socket 세션 차단
- 휴면 사용자 로그인·채팅 상대·상품 노출 차단
- 휴면 해제와 새 로그인 성공, 과거 세션 무효 유지
- 관리자 자신·다른 관리자 휴면 차단
- 비관리자의 DB 우회 제재·감사 INSERT 차단
- 상품 제재·감사 로그 UPDATE·DELETE 차단
- 관리자 역할 CLI 부여·해제
- Version 2.1 사용자 스키마의 역할·제재 테이블 마이그레이션
- Version 1.1~2.1 전체 보안 회귀 없음

### Version 3.0 이후 남은 보안 항목

- 신고 건별 검토·승인·반려·처리 상태 Workflow와 담당자 배정
- 관리자 역할 부여·해제 자체의 영구 감사 이력
- 관리자 권한에 대한 세부 역할 분리와 다중 승인 정책
- 상품 관리 삭제 복구 정책과 별도 승인 절차
- 관리자 감사 로그 보존 기간과 승인된 정리 절차
- 실제 운영 TLS 인증서, HTTPS/WSS와 Secure 쿠키 배포 검증
- Content-Security-Policy 등 HTTP 보안 헤더
- Python 전체 의존성 버전 고정과 정기 취약점 검사
- IP 기준 로그인 Rate Limiting과 민감정보 로그 필터링
- 기존 Git 이력에 포함됐던 민감 DB 데이터 처리

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 2.1

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `2.1` |
| Date | `2026-07-24` |
| 변경 유형 | Minor Version |
| 적용 범위 | 회원 탈퇴·익명화, 세션 종료, 공개 상품 목록과 상품 ID 표시 |
| 테스트 | 기존 보안 테스트, 계정 탈퇴·상품 보안 테스트 |
| 테스트 결과 | `155 passed` |

### 조치 전후 요약

| 항목 | Version 2.0 | Version 2.1 |
|---|---|---|
| 회원 탈퇴 | ❌ 기능 없음 | ✅ 재인증·확인 문구·CSRF 기반 탈퇴 |
| 계정 데이터 | ❌ 탈퇴 정책 없음 | ✅ 사용자명·소개글·기존 비밀번호 제거와 탈퇴 시각 저장 |
| 기존 세션 | ❌ 탈퇴 기능 없음 | ✅ HTTP 세션과 개인 Socket 연결 즉시 종료 |
| 참조 기록 | ❌ 탈퇴 정책 없음 | ✅ 익명 사용자 행으로 상품·신고·메시지 외래키 보존 |
| 탈퇴 계정 노출 | ❌ 탈퇴 기능 없음 | ✅ 로그인·상품·채팅 상대·신고 대상에서 제외 |
| 비로그인 상품 조회 | ⚠️ 상세 URL만 공개, 목록은 로그인 대시보드 | ✅ `/products` 공개 목록과 상세 조회 |
| 상품 ID 표시 | ⚠️ URL에만 포함 | ✅ 공개·대시보드·관리·상세 화면에 명시 |
| 보호 기능 | ✅ 등록·관리·채팅 로그인 필수 | ✅ 공개 조회와 상태 변경 권한을 분리해 기존 보호 유지 |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V2.1-DELETE-CSRF-01` | 상태 변경 보호 | 회원 탈퇴를 CSRF 보호된 POST 요청으로만 처리 | `delete_account`, `templates/profile.html` |
| `V2.1-DELETE-AUTH-01` | 재인증 | 저장된 Argon2id 해시로 현재 비밀번호를 다시 확인 | `delete_account` |
| `V2.1-DELETE-CONFIRM-01` | 명시적 동의 | UTF-8 상수 시간 비교로 `회원탈퇴` 확인 문구 검증 | `delete_account` |
| `V2.1-DELETE-ANON-01` | 식별정보 제거 | 사용자명을 내부 익명 ID로 변경하고 소개글 제거 | `delete_account` |
| `V2.1-DELETE-PASSWORD-01` | 인증정보 폐기 | 기존 비밀번호를 새 무작위 Argon2id 해시로 교체 | `delete_account` |
| `V2.1-DELETE-SESSION-01` | 세션 무효화 | 세션 버전 증가와 `deleted_at` 검증으로 모든 HTTP 세션 차단 | `delete_account`, `load_and_validate_session` |
| `V2.1-DELETE-SOCKET-01` | 연결 종료 | 사용자 개인 방의 모든 Socket을 서버에서 즉시 종료 | `disconnect_user_sockets` |
| `V2.1-DELETE-TX-01` | 동시 요청 방어 | 기존 세션 버전과 활성 상태가 일치할 때만 조건부 갱신 | `delete_account` |
| `V2.1-DELETE-REF-01` | 기록 무결성 | 사용자 행을 유지해 상품·신고·감사·메시지 외래키 보존 | 익명화 정책, 계정 탈퇴 테스트 |
| `V2.1-DELETE-HIDE-01` | 공개 비노출 | 탈퇴 계정과 상품을 로그인·채팅·신고·상품 조회에서 제외 | 활성 사용자 조건 쿼리 |
| `V2.1-PRODUCT-PUBLIC-01` | 공개 조회 | 비로그인 사용자에게 읽기 전용 상품 목록·상세 제공 | `products`, `get_product_or_404` |
| `V2.1-PRODUCT-AUTH-01` | 권한 분리 | 등록·관리·채팅 등 보호 경로는 기존 로그인 검사를 유지 | `login_required`, 공개 상품 테스트 |
| `V2.1-PRODUCT-ID-01` | 대상 식별 | 공개·대시보드·관리·상세 화면에 서버 상품 UUID 표시 | 상품 템플릿 |
| `V2.1-PRODUCT-XSS-01` | 출력 인코딩 | 공개 상품 목록에도 Jinja 자동 이스케이프 적용 | `templates/products.html` |

회원 탈퇴는 참조 무결성과 신고 감사 증거를 보존하는 논리 탈퇴입니다. 익명화한
사용자 행은 일반 로그인과 공개 기능에서 활성 사용자로 취급하지 않습니다. 기존
사용자명은 익명화 후 새로운 계정이 다시 사용할 수 있습니다.

### 데이터베이스 변경과 마이그레이션

`user` 테이블에 다음 컬럼을 추가했습니다.

| 컬럼 | 타입·제약 | 기본값·용도 |
|---|---|---|
| `deleted_at` | `INTEGER`, `NULL` 또는 0 이상 | `NULL`은 활성, 정수는 탈퇴 Unix 시각 |

마이그레이션 동작:

1. 기존 `user` 테이블의 컬럼을 확인합니다.
2. `deleted_at`이 없으면 타입·범위 `CHECK`와 함께 추가합니다.
3. 기존 사용자는 `NULL`을 유지해 활성 계정으로 호환됩니다.
4. 탈퇴 시 사용자 행을 삭제하지 않고 식별정보·비밀번호·세션 버전을 원자적으로
   변경합니다.
5. 상품·신고·감사·메시지 외래키는 기존 사용자 ID를 계속 참조합니다.

탈퇴 사용자의 상품은 DB에 보존되지만 활성 판매자와 JOIN하는 공개 목록·상세
쿼리에서 제외됩니다.

### 템플릿·의존성·환경변수 변경

- `templates/profile.html`
  - 탈퇴 시 기록 보존 정책 안내
  - 현재 비밀번호와 확인 문구를 요구하는 CSRF 보호 Form
- `templates/products.html`
  - 비로그인 사용자용 상품 목록
  - 상품 ID·제목·가격·판매자 표시
  - 비로그인 상태에서 등록·채팅은 로그인 필요 안내
- `templates/base.html`: 로그인 여부와 무관한 상품 목록 링크
- `templates/dashboard.html`, `templates/manage_products.html`,
  `templates/view_product.html`: 상품 ID 표시
- `tests/test_account_deletion_security.py`: 탈퇴 보안·보존·마이그레이션 테스트
- `tests/test_product_security.py`: 공개 조회·보호 경로·상품 ID·XSS 테스트

새 의존성과 환경변수는 없습니다.

### 검증 결과

실행 명령:

```sh
conda activate secure_coding
python -m pytest -q
```

결과:

```text
155 passed
```

검증한 주요 시나리오:

- 비로그인·CSRF 없는 회원 탈퇴 요청 차단
- 잘못된 현재 비밀번호·확인 문구·과도한 입력 거부
- 사용자명·소개글·기존 비밀번호 제거와 탈퇴 시각 기록
- 상품·신고·감사·1대1 메시지 외래키 기록 보존
- 현재·다른 브라우저 HTTP 세션과 개인 Socket 즉시 종료
- 탈퇴 계정 로그인·채팅 상대·상품 목록·상세 비노출
- 기존 사용자명으로 안전한 신규 회원가입
- 구버전 사용자 스키마의 `deleted_at=NULL` 마이그레이션과 DB 범위 제약
- 비로그인 상품 목록과 상세 조회
- 비로그인 상품 등록·관리·전체·1대1 채팅 접근 차단
- 공개 목록·대시보드·관리·상세의 상품 ID 표시
- 공개 상품 목록의 저장형 XSS 이스케이프
- Version 1.1~2.0 전체 보안 회귀 없음

### Version 2.1 이후 남은 보안 항목

- 탈퇴 기록의 보존 기간, 실제 삭제 요청과 법적·운영 정책
- 탈퇴 재인증 실패에 대한 별도 속도 제한과 감사 로그
- 탈퇴 계정의 보존 상품·신고·메시지 관리자 처리 화면
- 공개 상품 목록의 페이지네이션·검색과 판매자 조회 인덱스
- 1대1 메시지 사용자 차단, 읽음 확인, 삭제와 보존 정책
- 다중 서버용 공용 Socket 방·채팅 Rate Limiting 저장소
- 실제 운영 TLS 인증서, HTTPS/WSS 프록시와 Secure 쿠키 배포 검증
- 관리자 상품·신고 처리 흐름과 역할 기반 접근 제어
- Content-Security-Policy 등 HTTP 보안 헤더
- Python 전체 의존성 버전 고정과 정기 취약점 검사

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 2.0

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `2.0` |
| Date | `2026-07-24` |
| 변경 유형 | Major Version |
| 적용 범위 | 사용자 선택, 1대1 실시간 메시지, 대화 기록과 메시지 DB 스키마 |
| 테스트 | 기존 보안 테스트, `tests/test_direct_chat_security.py` |
| 테스트 결과 | `145 passed` |

### 조치 전후 요약

| 항목 | Version 1.7 | Version 2.0 |
|---|---|---|
| 채팅 유형 | 전체 사용자 브로드캐스트 | 전체 채팅 유지와 별도 1대1 채팅 추가 |
| 대화 상대 선택 | ❌ 없음 | ✅ 본인을 제외한 사용자명 목록 |
| 메시지 전달 범위 | 전체 연결 사용자 | ✅ 서버가 배정한 발신자·수신자 개인 방 |
| 발신자 결정 | ✅ 전체 채팅에서 서버 생성 | ✅ 1대1 채팅도 세션과 DB에서 서버 생성 |
| 기록 저장 | ❌ 전체 채팅은 미저장 | ✅ 1대1 메시지를 SQLite에 저장 |
| 기록 열람 권한 | ❌ 기록 없음 | ✅ 현재 사용자와 상대방의 대화만 최대 100건 조회 |
| 메시지 검증 | ✅ 전체 채팅 1~500자 검증 | ✅ 1대1 채팅에도 동일 검증과 필드 허용 목록 적용 |
| 남용 방지 | ✅ 전체 채팅 사용자·IP 제한 | ✅ 전체·1대1 채팅이 같은 제한을 공유 |
| DB 무결성 | ❌ 메시지 테이블 없음 | ✅ 외래키·자기 전송 금지·길이·시각 제약과 조회 인덱스 |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V2.0-DM-AUTH-01` | HTTP 인증 | 사용자 목록과 대화 화면을 로그인 사용자에게만 제공 | `direct_chat_users`, `direct_chat`, `login_required` |
| `V2.0-DM-PRIVACY-01` | 정보 최소화 | 사용자 목록에 본인을 제외한 ID와 사용자명만 표시 | `direct_chat_users`, 목록 테스트 |
| `V2.0-DM-TARGET-01` | 상대 검증 | UUID 형식·존재 여부를 확인하고 자기 자신과의 대화를 거부 | `get_chat_recipient_or_404` |
| `V2.0-DM-ROOM-01` | 서버 방 배정 | Socket 인증 성공 시 서버가 사용자 ID 기반 개인 방에 연결 | `handle_socket_connect`, `direct_chat_room` |
| `V2.0-DM-INPUT-01` | 이벤트 허용 목록 | `recipient_id`, `message`만 허용해 발신자·방 위조 필드를 거부 | `validate_direct_chat_message` |
| `V2.0-DM-SENDER-01` | 발신자 무결성 | 발신자 ID·사용자명을 인증 세션과 DB에서 생성 | `handle_send_direct_message_event` |
| `V2.0-DM-DELIVERY-01` | 비공개 전달 | 발신자와 수신자의 개인 Socket 방에만 메시지 전달 | `handle_send_direct_message_event` |
| `V2.0-DM-HISTORY-01` | 기록 권한 | 양쪽 당사자가 현재 사용자와 상대인 행만 최근 100건 조회 | `direct_chat` |
| `V2.0-DM-XSS-01` | 출력 인코딩 | 기존 기록은 Jinja 이스케이프, 실시간 메시지는 DOM `textContent` 사용 | `templates/direct_chat.html` |
| `V2.0-DM-RATE-01` | 전송 제한 | 전체·1대1 채팅에 동일한 사용자·IP 제한 적용 | `consume_chat_rate_limit` |
| `V2.0-DM-SPAM-01` | 반복 제한 | 같은 상대에게 동일 메시지를 5초 안에 반복 전송하지 못하게 제한 | `chat_message_is_duplicate` |
| `V2.0-DM-DATA-01` | 참조 무결성 | 발신자·수신자 외래키와 자기 전송 금지 제약 적용 | `create_direct_message_table` |
| `V2.0-DM-DATA-02` | 내용 무결성 | 1~500자, NUL 차단, 정수 생성 시각 제약 적용 | `create_direct_message_table` |
| `V2.0-DM-DATA-03` | 조회 인덱스 | 양방향 대화 기록 조회용 복합 인덱스 두 개 적용 | `ensure_direct_message_schema` |
| `V2.0-DM-ERROR-01` | 안전한 실패 | DB 저장 실패 시 롤백하고 내부정보 없는 Socket 오류 반환 | `handle_send_direct_message_event` |

개인 Socket 방 이름은 서버 내부에서만 생성합니다. 클라이언트가 전송 이벤트에
`sender_id`, `username` 또는 `room`을 추가하면 전체 요청을 거부합니다. 전송 전과
기록 조회 시 모두 실제 사용자와 대화 당사자 관계를 다시 확인합니다.

### 데이터베이스 변경과 마이그레이션

새 핵심 업무 테이블인 `direct_message`를 추가했습니다.

| 필드 | 타입·제약 | 용도 |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | 서버 생성 메시지 UUID |
| `sender_id` | `TEXT NOT NULL`, `user(id)` 외래키 | 발신자 |
| `recipient_id` | `TEXT NOT NULL`, `user(id)` 외래키 | 수신자 |
| `message` | `TEXT NOT NULL`, 1~500자·NUL 차단 | 일반 텍스트 메시지 |
| `created_at` | 0 이상 `INTEGER` | 서버 생성 Unix 시각 |

테이블에는 `sender_id <> recipient_id` 제약을 적용했습니다. 양방향 기록 조회를
위해 다음 인덱스를 함께 생성합니다.

- `direct_message_sender_recipient_created`
- `direct_message_recipient_sender_created`

마이그레이션 동작:

1. 기존 사용자 보안 컬럼과 상품 스키마를 먼저 확인합니다.
2. `direct_message` 테이블이 없으면 현재 제약을 포함해 새로 생성합니다.
3. 기존에 같은 이름의 비호환 테이블이 있으면 임의 변환하지 않고 초기화를
   중단합니다.
4. 현재 스키마가 확인된 경우에만 양방향 조회 인덱스를 생성합니다.

Version 1.7까지 메시지 테이블이 없었으므로 이동할 기존 1대1 메시지 데이터는
없습니다. 기존 전체 채팅 메시지는 계속 저장하지 않습니다.

### 템플릿·의존성·환경변수 변경

- `templates/base.html`: 로그인 메뉴에 1대1 채팅 링크와 기록 영역 스타일 추가
- `templates/direct_chat_users.html`
  - 본인을 제외한 대화 상대 사용자명 목록
  - 다른 계정 필드 미노출과 빈 목록 안내
- `templates/direct_chat.html`
  - 최근 대화 기록과 실시간 입력 화면
  - CSRF Token을 사용한 Socket 연결
  - 현재 대화 메시지만 DOM에 추가하는 참여자 ID 검사
  - 발신자명과 메시지를 `textContent`로 출력
- `tests/test_direct_chat_security.py`: 1대1 채팅 기능·보안·DB 테스트 26개

새 의존성과 환경변수는 없습니다.

### 검증 결과

실행 명령:

```sh
conda activate secure_coding
python -m pytest -q
```

결과:

```text
145 passed
```

검증한 주요 시나리오:

- 비로그인 사용자 목록·대화 화면 접근 차단
- 사용자 목록에서 본인과 비공개 계정 필드 미노출
- 잘못된·미존재·자기 자신 상대의 일반 404 처리
- 대화 당사자가 아닌 메시지의 기록 미노출
- 최근 기록 100건 제한과 시간순 표시
- 발신자·수신자만 실시간 메시지 수신
- 발신자 ID·사용자명 서버 생성과 메시지 영구 저장
- 추가 필드를 이용한 발신자·방 위조 차단
- 미존재 수신자와 자기 전송 차단
- 기존·실시간 메시지의 저장형·DOM XSS 방어
- 전체 채팅에서 1대1 채팅으로 전환하는 속도 제한 우회 차단
- 동일 상대·동일 메시지 반복 차단
- 이벤트 처리 시 만료 세션 재검사와 연결 종료
- 메시지 외래키·자기 전송·길이·NUL·시각 DB 제약
- 비호환 기존 메시지 테이블 발견 시 안전한 초기화 중단
- Version 1.1~1.7 전체 보안 회귀 없음

### Version 2.0 이후 남은 보안 항목

- 1대1 메시지 보존 기간, 사용자 삭제 요청 및 운영자 보존 정책
- 사용자 차단, 읽음 확인, 안 읽은 메시지 개수와 기록 페이지네이션
- 관리자 권한 체계가 추가될 경우 대화 열람 정책과 감사 로그
- 다중 서버용 공용 Socket 방·채팅 Rate Limiting 저장소
- 실제 운영 TLS 인증서, HTTPS/WSS 프록시와 Secure 쿠키 배포 검증
- 비밀번호 변경·재인증 실패 속도 제한과 분실 복구
- 관리자 상품·신고 처리 흐름과 역할 기반 접근 제어
- Content-Security-Policy 등 HTTP 보안 헤더
- Python 전체 의존성 버전 고정과 정기 취약점 검사
- 기존 Git 이력에 포함됐던 민감 DB 데이터 처리

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 1.7

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `1.7` |
| Date | `2026-07-24` |
| 변경 유형 | Minor Version |
| 적용 범위 | 로그인 사용자의 등록 상품 관리 목록과 기존 관리 작업 연결 |
| 테스트 | 기존 보안 테스트, `tests/test_product_security.py` |
| 테스트 결과 | `119 passed` |

### 조치 전후 요약

| 항목 | Version 1.6 | Version 1.7 |
|---|---|---|
| 등록 상품 관리 | ⚠️ 개별 상세 화면에서만 본인 상품 수정·삭제 가능 | ✅ 본인 상품을 한 화면에서 조회·수정·삭제 |
| 목록 접근 | ❌ 전용 관리 목록 없음 | ✅ 로그인 사용자만 접근 가능 |
| 목록 조회 권한 | ❌ 전용 관리 목록 없음 | ✅ DB 조회부터 현재 사용자의 판매자 ID로 제한 |
| 상태 변경 보호 | ✅ 개별 상품 CSRF·소유권 검증 | ✅ 관리 화면에서도 기존 보호를 그대로 사용 |
| XSS 출력 방어 | ✅ 전체 상품 목록·상세·수정 화면 이스케이프 | ✅ 관리 목록까지 Jinja 자동 이스케이프 검증 |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V1.7-PRODUCT-01` | 본인 상품 관리 | 로그인한 사용자가 등록한 상품을 관리 목록으로 제공 | `manage_products`, `templates/manage_products.html` |
| `V1.7-AUTH-01` | 인증 필수 | 비로그인 사용자의 관리 목록 접근을 로그인 화면으로 전환 | `login_required`, 상품 테스트 |
| `V1.7-OWNER-01` | 조회 범위 제한 | 클라이언트 입력이 아닌 세션에서 검증된 사용자 ID를 `seller_id` 조건으로 사용 | `manage_products` |
| `V1.7-OWNER-02` | 변경 권한 유지 | 수정·삭제 시 기존 라우트와 SQL의 판매자 소유권 검증을 재사용 | `require_product_owner`, `edit_product_post`, `delete_product` |
| `V1.7-CSRF-01` | 삭제 요청 보호 | 관리 목록의 삭제 Form에 세션 CSRF Token 적용 | `templates/manage_products.html`, `delete_product` |
| `V1.7-XSS-01` | 출력 인코딩 | 제목·설명을 일반 텍스트로 출력하고 Jinja 자동 이스케이프 검증 | 관리 템플릿, 상품 테스트 |

이번 기능은 일반 사용자가 자신이 등록한 상품을 관리하는 화면입니다. 모든
사용자의 상품을 제재하는 관리자용 상품 관리와 역할 기반 권한 체계는 포함하지
않습니다.

### 데이터베이스 변경

없습니다. 기존 `product.seller_id` 외래키와 인덱스 없는 판매자 조건 조회를
사용하므로 기존 데이터와 스키마를 그대로 유지합니다.

### 템플릿·의존성·환경변수 변경

- `templates/base.html`: 로그인 사용자 메뉴에 내 상품 관리 링크 추가
- `templates/manage_products.html`
  - 본인 상품 목록과 빈 목록 안내
  - 새 상품 등록, 상세 조회, 수정 링크
  - CSRF 보호 삭제 Form
- `tests/test_product_security.py`
  - 비로그인 관리 화면 접근 차단
  - 다른 판매자 상품의 목록 미노출
  - 관리 작업 링크와 CSRF Token
  - 제목·설명의 저장형 XSS 출력 이스케이프
  - 삭제 후 관리 목록 복귀

새 의존성과 환경변수는 없습니다.

### 검증 결과

실행 명령:

```sh
conda activate secure_coding
python -m pytest -q
```

결과:

```text
119 passed
```

검증한 주요 시나리오:

- 비로그인 등록 상품 관리 화면 접근 차단
- 현재 로그인 사용자의 상품만 서버 쿼리에서 조회
- 다른 사용자의 제목·ID·관리 링크 미노출
- 관리 목록의 상세·수정·삭제 연결
- 삭제 Form의 CSRF Token 적용과 기존 검증 회귀
- 상품 제목·설명의 저장형 XSS 이스케이프
- 삭제 후 등록 상품 관리 목록으로 이동
- Version 1.1~1.6 전체 보안 회귀 없음

### Version 1.7 이후 남은 보안 항목

- 관리자 상품 목록·검색·상태 관리와 역할 기반 접근 제어
- 상품 수 증가에 대비한 페이지네이션과 판매자 조회 인덱스
- 비밀번호 변경·재인증 실패에 대한 별도 속도 제한과 감사 정책
- 비밀번호 재설정·분실 복구와 일회용 Token
- 실제 운영 TLS 인증서, HTTPS/WSS 프록시와 Secure 쿠키 배포 검증
- 다중 서버용 공용 채팅 Rate Limiting 저장소
- Content-Security-Policy 등 HTTP 보안 헤더
- Python 전체 의존성 버전 고정과 정기 취약점 검사
- 신고 관리자 처리 흐름과 감사 로그 보존 정책
- 기존 Git 이력에 포함됐던 민감 DB 데이터 처리

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 1.6

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `1.6` |
| Date | `2026-07-24` |
| 변경 유형 | Minor Version |
| 적용 범위 | 본인 사용자 조회, 소개글 수정, 비밀번호 변경, 세션 무효화 |
| 테스트 | 기존 보안 테스트, `tests/test_account_security.py` |
| 테스트 결과 | `117 passed` |

### 조치 전후 요약

| 항목 | Version 1.5 | Version 1.6 |
|---|---|---|
| 마이페이지 조회 | ⚠️ 프로필 수정 화면에서 사용자명만 표시 | ✅ 로그인한 본인의 사용자명·소개글 조회 |
| 조회 권한 | ⚠️ 로그인 보호만 존재 | ✅ 본인 세션의 DB 사용자만 표시하고 다른 사용자 미노출 검증 |
| 소개글 변경 | ✅ 현재 비밀번호 재인증·CSRF 적용 | ✅ 기존 보안 유지 |
| 비밀번호 변경 | ❌ 기능 없음 | ✅ 별도 CSRF POST와 현재 비밀번호 재인증 |
| 새 비밀번호 검증 | ❌ 기능 없음 | ✅ 12~128자·문자·숫자·공백 정책과 확인값 검증 |
| 비밀번호 재사용 | ❌ 기능 없음 | ✅ 현재 비밀번호와 동일한 새 비밀번호 거부 |
| 비밀번호 저장 | ❌ 변경 기능 없음 | ✅ 새로운 Salt를 사용한 Argon2id 해시 저장 |
| 세션 무효화 | ❌ 비밀번호 변경 기능 없음 | ✅ 변경 후 기존 HTTP·Socket 세션 전체 무효화 |
| 로그인 | ✅ Argon2id 검증 | ✅ 이전 비밀번호 거부, 새 비밀번호 로그인 |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V1.6-MYPAGE-01` | 본인 조회 | 세션에서 확인한 DB 사용자의 사용자명·소개글만 표시 | `profile`, `templates/profile.html` |
| `V1.6-MYPAGE-02` | 정보 최소화 | 비밀번호 해시·잠금·세션 버전을 화면에 출력하지 않음 | `templates/profile.html`, 계정 테스트 |
| `V1.6-BIO-01` | 소개글 변경 | 기존 CSRF·길이·XSS 출력·현재 비밀번호 재인증 유지 | `profile_post` |
| `V1.6-PASSWORD-01` | 전용 변경 요청 | 비밀번호 변경을 별도 CSRF 보호 POST 경로로 처리 | `update_password` |
| `V1.6-PASSWORD-02` | 현재 비밀번호 확인 | 저장된 Argon2id 해시로 현재 비밀번호 재인증 | `verify_password`, `update_password` |
| `V1.6-PASSWORD-03` | 새 비밀번호 정책 | 12~128자, 문자·숫자 필수, 공백·제어문자 거부 | `validate_password` |
| `V1.6-PASSWORD-04` | 확인·재사용 방지 | 확인값 상수 시간 비교와 현재 비밀번호 재사용 차단 | `update_password` |
| `V1.6-PASSWORD-05` | 안전한 저장 | 새 무작위 Salt를 포함한 Argon2id 해시만 저장 | `password_hasher.hash` |
| `V1.6-SESSION-01` | 전체 세션 무효화 | 변경 성공 시 사용자 `session_version`을 원자적으로 증가 | `update_password` |
| `V1.6-SESSION-02` | HTTP 세션 검사 | 요청마다 쿠키와 DB의 세션 버전 일치 여부 확인 | `load_and_validate_session` |
| `V1.6-SESSION-03` | Socket 세션 검사 | Socket 연결·메시지마다 DB 세션 버전 재확인 | `get_authenticated_socket_user` |
| `V1.6-TX-01` | 동시 변경 방어 | 기존 세션 버전이 일치할 때만 비밀번호를 변경 | `update_password`의 조건부 UPDATE |

마이페이지는 로그인 사용자가 자신의 정보만 확인하는 기능입니다. 관리자용
사용자 목록, 다른 사용자 상세 조회, 검색 및 상태 관리는 이번 버전에 포함하지
않습니다.

### 데이터베이스 변경

`user` 테이블에 기존 기능과 호환되는 세션 무효화 컬럼을 추가했습니다.

| 컬럼 | 타입 | 기본값 | 용도 |
|---|---|---|---|
| `session_version` | `INTEGER NOT NULL` | `0` | 비밀번호 변경 후 기존 세션 일괄 무효화 |

마이그레이션 동작:

1. 기존 `user` 테이블의 컬럼을 확인합니다.
2. `session_version`이 없을 때 기본값 `0`으로 추가합니다.
3. 기존 세션은 사용자 버전이 `0`인 동안 호환됩니다.
4. 비밀번호 변경 성공 시 DB 버전을 증가시키고 현재 세션을 제거합니다.
5. 이전 버전이 담긴 HTTP·Socket 세션은 다음 요청 또는 이벤트에서 거부됩니다.

로컬 DB는 저장소 밖에 권한 `600`으로 백업하고 별도 파일 복구 검증 후
마이그레이션했습니다. 마이그레이션 후 기존 사용자의 초기 버전은 모두 `0`,
외래키 위반은 0건이고 `PRAGMA integrity_check` 결과는 `ok`였습니다.

### 템플릿·의존성·환경변수 변경

- `templates/base.html`: 프로필 링크 명칭을 마이페이지로 변경
- `templates/profile.html`
  - 본인 사용자명·소개글 조회
  - 기존 소개글 변경 Form 유지
  - 현재·새·확인 비밀번호 입력을 가진 별도 변경 Form
- `tests/test_account_security.py`
  - 비로그인 조회, 다른 사용자·해시 미노출
  - 비밀번호 변경 성공·실패·CSRF·정책·확인·재사용 검증
  - 이전 비밀번호 거부와 HTTP·Socket 세션 무효화
  - 구버전 DB의 `session_version=0` 마이그레이션

새 의존성과 환경변수는 없습니다.

### 검증 결과

실행 명령:

```sh
python -m pytest -q
```

결과:

```text
117 passed
```

검증한 주요 시나리오:

- 비로그인 마이페이지 접근 차단
- 로그인한 본인의 사용자명·소개글 조회
- 다른 사용자명과 비밀번호 해시 미노출
- 소개글 현재 비밀번호 재인증과 XSS 출력 이스케이프 회귀
- 비밀번호 변경 CSRF Token 누락 거부
- 잘못된 현재 비밀번호와 약한 새 비밀번호 거부
- 새 비밀번호 확인 불일치와 현재 비밀번호 재사용 거부
- Argon2id 새 해시와 Salt 생성
- 변경 직후 현재 세션 로그아웃
- 다른 브라우저 HTTP 세션과 기존 Socket 세션 무효화
- 이전 비밀번호 로그인 거부와 새 비밀번호 로그인 성공
- 조건부 UPDATE를 통한 동시 비밀번호 변경 방어
- 기존 DB에 `session_version` 기본값 마이그레이션
- Version 1.1~1.5 전체 보안 회귀 없음

### Version 1.6 이후 남은 보안 항목

- 비밀번호 변경·재인증 실패에 대한 별도 속도 제한과 감사 정책
- 비밀번호 재설정·분실 복구와 일회용 Token
- 관리자 사용자 목록·검색·상태 관리와 역할 기반 접근 제어
- 실제 운영 TLS 인증서, HTTPS/WSS 프록시와 Secure 쿠키 배포 검증
- 다중 서버용 공용 채팅 Rate Limiting 저장소
- Content-Security-Policy 등 HTTP 보안 헤더
- Python 전체 의존성 버전 고정과 정기 취약점 검사
- 신고 관리자 처리 흐름과 감사 로그 보존 정책
- 기존 Git 이력에 포함됐던 민감 DB 데이터 처리

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 1.5

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `1.5` |
| Date | `2026-07-24` |
| 변경 유형 | Minor Version |
| 적용 범위 | Socket 인증, 메시지 검증, 채팅 Rate Limiting, 연결 보호 |
| 테스트 | 기존 보안 테스트, `tests/test_chat_security.py` |
| 테스트 결과 | `108 passed` |

### 조치 전후 요약

| 항목 | Version 1.4 | Version 1.5 |
|---|---|---|
| Socket 연결 인증 | ❌ 로그인·CSRF 확인 없음 | ✅ 로그인 세션·만료·실사용자·CSRF 확인 |
| 이벤트 인증 | ❌ 메시지 이벤트에서 미확인 | ✅ 메시지마다 세션 만료와 사용자 존재 재확인 |
| 발신자 정보 | ❌ 클라이언트 사용자명 신뢰 | ✅ DB 사용자명과 서버 ID·시각 사용 |
| 메시지 검증 | ❌ 객체·필드·타입·길이 검증 없음 | ✅ 단일 필드, 문자열, NFKC, 1~500자 검증 |
| 제어문자 | ❌ 제한 없음 | ✅ Unicode `C` 범주 문자 거부 |
| XSS 출력 | ⚠️ 클라이언트 `textContent`만 적용 | ✅ 서버 필드 제한과 `textContent` 병행 |
| 사용자 제한 | ❌ 없음 | ✅ 사용자별 10초에 5건 |
| IP 제한 | ❌ 없음 | ✅ HMAC IP별 1분에 30건 |
| 반복 스팸 | ❌ 없음 | ✅ 동일 메시지 5초 이내 반복 거부 |
| Origin | ⚠️ 라이브러리 기본 정책 | ✅ 전달 Host를 배제한 동일 Origin 명시 검증 |
| 전송 크기 | ❌ 별도 제한 없음 | ✅ Socket.IO Payload 16 KiB 제한 |
| HTTPS/WSS | ❌ 저장소 강제 설정 없음 | ⚠️ 평문 거부 설정 추가, 실제 TLS는 외부 구성 필요 |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V1.5-CHAT-AUTH-01` | 연결 인증 | Socket 연결에서 로그인 세션, 만료 시각, 실제 사용자 확인 | `handle_socket_connect`, `get_authenticated_socket_user` |
| `V1.5-CHAT-CSRF-01` | Socket CSRF | 연결 인증 데이터의 세션 CSRF Token을 상수 시간 비교 | `socket_csrf_is_valid`, `templates/dashboard.html` |
| `V1.5-CHAT-AUTH-02` | 이벤트 재인증 | 메시지마다 세션 만료와 DB 사용자 존재 재확인 | `handle_send_message_event` |
| `V1.5-CHAT-ID-01` | 사칭 방지 | 클라이언트 사용자명을 거부하고 DB 사용자명 사용 | `validate_chat_message`, `handle_send_message_event` |
| `V1.5-CHAT-INPUT-01` | 형식 검증 | 객체와 `message` 단일 필드·문자열 타입만 허용 | `validate_chat_message` |
| `V1.5-CHAT-INPUT-02` | 내용 검증 | NFKC 정규화, 공백 제거, 1~500자와 제어문자 차단 | `validate_chat_message` |
| `V1.5-CHAT-XSS-01` | 출력 인코딩 | 검증된 일반 텍스트를 DOM `textContent`로만 출력 | `templates/dashboard.html` |
| `V1.5-CHAT-RATE-01` | 사용자 제한 | 사용자별 모든 메시지 시도를 10초에 5건으로 제한 | `consume_chat_rate_limit` |
| `V1.5-CHAT-RATE-02` | IP 제한 | 원문이 아닌 HMAC IP별 시도를 1분에 30건으로 제한 | `get_client_ip_hash`, `consume_chat_rate_limit` |
| `V1.5-CHAT-SPAM-01` | 반복 방지 | 동일 사용자의 동일 메시지 5초 이내 반복 차단 | `chat_message_is_duplicate` |
| `V1.5-CHAT-META-01` | 서버 메타데이터 | 메시지 UUID, DB 사용자명, Unix 시각을 서버에서 생성 | `handle_send_message_event` |
| `V1.5-SOCKET-ORIGIN-01` | Origin 검증 | 현재 Scheme·Host와 정확히 일치하는 Origin만 허용 | `socket_origin_is_allowed` |
| `V1.5-SOCKET-SIZE-01` | 전송 크기 | Engine.IO 최대 Payload를 16 KiB로 제한 | `CHAT_MAX_PAYLOAD_BYTES`, `SocketIO` |
| `V1.5-HTTPS-01` | 평문 연결 거부 | WSGI 경계에서 HTTP와 Socket.IO 평문 handshake를 400으로 거부 | `MARKET_REQUIRE_HTTPS`, `RequireHttpsMiddleware` |
| `V1.5-PROXY-01` | 프록시 Scheme 신뢰 | 명시한 신뢰 프록시 수만큼만 전달 프로토콜 사용 | `MARKET_TRUSTED_PROXY_COUNT`, `ProxyFix` |

메시지의 HTML 태그 문자열을 서버에서 불완전하게 제거하지 않습니다. 메시지는
HTML 기능이 아닌 일반 텍스트이며 클라이언트가 `textContent`로 출력해 마크업으로
해석되지 않도록 합니다. 클라이언트가 보낸 사용자명, 메시지 ID와 시각은
사용하지 않습니다.

사용자·IP 제한은 인증 후 도착한 유효·무효 메시지 시도를 모두 계산합니다.
Rate Limiting 시간은 시스템 시각 변경의 영향을 줄이기 위해 단조 시계를
사용합니다. IP 원문은 저장하지 않고 애플리케이션 비밀키 기반 HMAC으로
변환합니다.

### 데이터베이스 변경

데이터베이스 스키마 변경은 없습니다. 메시지 본문과 Rate Limiting 상태를 DB에
저장하지 않습니다.

현재 Rate Limiting 상태는 단일 애플리케이션 프로세스 메모리에만 존재합니다.
재시작하면 초기화되며, 여러 서버를 운영할 때는 Redis 같은 공용 저장소로
이전해야 합니다.

### 템플릿·의존성·환경변수 변경

- `templates/dashboard.html`
  - Socket 연결 CSRF Token 전달
  - 클라이언트 사용자명 필드 제거
  - 메시지 `maxlength=500` 보조 제한
  - 연결·검증·속도 제한 오류를 `textContent`로 표시
- `tests/test_chat_security.py`: 채팅 보안 전용 테스트 20개

새 Python 의존성은 없습니다.

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `MARKET_REQUIRE_HTTPS` | `false` | 활성화하면 평문 HTTP와 Socket.IO handshake 거부 |
| `MARKET_TRUSTED_PROXY_COUNT` | `0` | 신뢰할 프록시의 전달 IP·Scheme 홉 수 |

HTTPS 페이지에서 같은 Origin에 연결하는 Socket.IO 클라이언트는 WSS를
사용합니다. `MARKET_REQUIRE_HTTPS=true`, `MARKET_COOKIE_SECURE=true`와 실제
TLS 인증서·프록시 구성을 함께 사용해야 합니다. 저장소 테스트만으로 실제 운영
인증서와 프록시 배포 상태까지 검증하지는 않았습니다.

### 검증 결과

실행 명령:

```sh
python -m pytest -q
```

결과:

```text
108 passed
```

검증한 주요 시나리오:

- 비로그인 또는 잘못된 Socket CSRF Token 연결 거부
- 정상 로그인 사용자의 연결과 메시지 전송
- 메시지 객체·단일 필드·문자열 타입 검증
- 빈 값·공백·500자 초과·NUL·방향 제어 문자 거부
- 클라이언트 사용자명 위조 필드 거부
- 서버 UUID·DB 사용자명·전송 시각 생성
- XSS 태그 문자열의 일반 텍스트 전송과 `textContent` 출력
- 사용자·IP별 메시지 속도 제한
- 동일 메시지 반복 차단
- 메시지 이벤트에서 만료 세션과 삭제 사용자 재검증
- 악성 Origin과 전달 Host 위조 거부
- 16 KiB Socket.IO Payload 제한
- 선택적 HTTPS 강제와 신뢰하지 않은 전달 Scheme 무시
- Version 1.1~1.4 전체 보안 회귀 없음

### Version 1.5 이후 남은 보안 항목

- 실제 운영 TLS 인증서, HTTPS/WSS 프록시와 Secure 쿠키 배포 검증
- 다중 애플리케이션 서버용 공용 채팅 Rate Limiting 저장소
- Socket 연결 폭주와 동시 연결 수 제한
- 채팅 차단 이벤트의 민감정보 없는 운영 감사·모니터링 정책
- Content-Security-Policy 등 HTTP 보안 헤더
- CDN Socket.IO 스크립트 SRI 또는 자체 호스팅
- Python 전체 의존성 버전 고정과 정기 취약점 검사
- IP 단위 로그인 Rate Limiting
- 신고 관리자 처리 흐름과 감사 로그 보존 정책
- 기존 Git 이력에 포함됐던 민감 DB 데이터 처리

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 1.4

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `1.4` |
| Date | `2026-07-24` |
| 변경 유형 | Minor Version |
| 적용 범위 | 신고 시도 제한, 실패 감사, 개인정보 최소화, DB 백업·복구 검증 |
| 테스트 | 기존 보안 테스트, `tests/test_report_security.py`, `tests/test_database_backup.py` |
| 테스트 결과 | `88 passed` |

### 조치 전후 요약

| 항목 | Version 1.3 | Version 1.4 |
|---|---|---|
| IP 신고 제한 | ❌ 사용자 성공 건수만 제한 | ✅ HMAC IP별 1시간 20회 시도 제한 |
| 사용자 시도 제한 | ⚠️ 성공 신고만 1시간 5건 제한 | ✅ 성공 제한에 더해 사용자별 1시간 10회 시도 제한 |
| 프록시 IP 신뢰 | ❌ 명시적 정책 없음 | ✅ 기본 전달 헤더 미신뢰, 신뢰 프록시 수 명시 설정 |
| 실패 감사 | ❌ 성공·마이그레이션만 기록 | ✅ 검증·개인정보·중복·사용자/IP 제한 실패 기록 |
| IP 로그 | ❌ 없음 | ✅ 원문 대신 비밀키 기반 HMAC-SHA256만 기록 |
| 개인정보 입력 | ⚠️ 안내·탐지 없음 | ✅ 이메일·전화번호·주민등록번호 패턴 저장 차단 |
| DB 백업 | ⚠️ 수동 파일 복사 | ✅ SQLite Backup API, 무결성·외래키·권한 검증 |
| 복구 검증 | ❌ 절차 없음 | ✅ 실행 DB를 덮어쓰지 않는 새 파일 복구 검증 |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V1.4-RATE-01` | IP 시도 제한 | IP별 1시간 최대 20회 신고 POST 시도 허용 | `consume_report_rate_limit`, `report_post` |
| `V1.4-RATE-02` | 사용자 시도 제한 | 사용자별 1시간 최대 10회 시도와 기존 성공 5건 제한 병행 | `consume_report_rate_limit`, `report_post` |
| `V1.4-RATE-03` | 차단 로그 제한 | 제한 도달 이벤트는 범위별 윈도마다 한 번만 기록해 로그 증폭 방지 | `report_rate_limit.blocked_logged` |
| `V1.4-IP-01` | IP 최소 수집 | 정규화된 IP를 비밀키 기반 HMAC-SHA256으로 변환하고 원문 미저장 | `get_client_ip_hash` |
| `V1.4-IP-02` | 프록시 신뢰 경계 | 기본값은 전달 IP 헤더를 무시하고 명시한 프록시 홉만 `ProxyFix`로 신뢰 | `MARKET_TRUSTED_PROXY_COUNT`, `ProxyFix` |
| `V1.4-AUDIT-01` | 실패 감사 로그 | 검증·개인정보·중복·사용자/IP 제한 실패를 사유 코드로 기록 | `report_post`, `create_report_audit_table` |
| `V1.4-AUDIT-02` | 민감정보 제외 | 감사 로그에 신고 사유·IP 원문·세션·CSRF Token을 저장하지 않음 | `add_report_audit_log` |
| `V1.4-PRIVACY-01` | 개인정보 탐지 | NFKC 정규화 후 이메일·휴대전화·주민등록번호 패턴 저장 거부 | `report_reason_contains_sensitive_data`, `validate_report_reason` |
| `V1.4-BACKUP-01` | 안전한 백업 | 저장소 밖 새 파일에 SQLite Backup API로 복사하고 권한 `600` 설정 | `scripts/database_backup.py` |
| `V1.4-BACKUP-02` | 백업 검증 | 백업 전후 `quick_check`와 `foreign_key_check` 수행 | `verify_database`, `copy_verified_database` |
| `V1.4-BACKUP-03` | 덮어쓰기 방지 | 원자적 새 파일 생성으로 기존 백업과 실행 DB 덮어쓰기 거부 | `resolved_output_path`, `copy_verified_database` |
| `V1.4-RESTORE-01` | 복구 검증 | 백업을 별도 새 파일로 복구하고 무결성·권한을 재검증 | `restore_database_to_new_file` |

IP HMAC은 동일 IP의 반복 시도를 비교하기 위한 가명 식별자입니다. 원문 복원에는
사용하지 않으며 `MARKET_SECRET_KEY`가 변경되면 기존 IP 제한 범위도 사실상
초기화됩니다. 전달 IP 헤더는 `MARKET_TRUSTED_PROXY_COUNT`가 `0`보다 클 때만
설정한 수만큼 신뢰합니다.

개인정보 패턴 차단은 명백한 이메일·국내 휴대전화·주민등록번호 형식을 줄이는
보조 방어입니다. 모든 개인정보 표현을 완전히 식별할 수 없으므로 신고 화면의
입력 금지 안내와 함께 적용합니다.

### 데이터베이스 변경

`report_audit_log`에 `source_ip_hash`를 추가하고 다음 실패 이벤트를 허용했습니다.

- `report_rejected_validation`
- `report_rejected_sensitive_data`
- `report_rejected_duplicate`
- `report_rejected_user_rate`
- `report_rejected_ip_rate`

Version 1.3 감사 로그는 이벤트와 대상 정보를 보존한 채 새 스키마로 이동하며,
과거 로그에는 원본 IP 정보가 없으므로 `source_ip_hash=NULL`을 유지합니다.

보조 테이블 `report_rate_limit`을 추가했습니다.

| 컬럼 | 용도 |
|---|---|
| `scope_type` | `user` 또는 `ip` 제한 구분 |
| `scope_key` | 사용자 UUID 또는 IP HMAC |
| `window_started_at` | 현재 제한 윈도 시작 시각 |
| `attempt_count` | 윈도 내 신고 시도 횟수 |
| `blocked_logged` | 동일 차단 이벤트 중복 기록 방지 |

로컬 DB 마이그레이션 전 저장소 밖에 백업을 생성하고, 별도 파일 복구 검증까지
완료했습니다. 마이그레이션 후 외래키 위반은 0건이고
`PRAGMA integrity_check` 결과는 `ok`였습니다.

### 템플릿·도구 변경

- `templates/report.html`: 이메일·전화번호·주민등록번호 입력 금지 안내
- `scripts/database_backup.py`: 백업, 무결성 검증, 새 파일 복구 검증 명령
- `.gitignore`: `*.backup.db`, `*.restore.db` 제외

백업 도구 사용법은 `README.md`의 “데이터베이스 백업과 복구 검증”에서
확인할 수 있습니다.

### 의존성 및 환경변수 변경

새 Python 의존성은 없습니다.

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `MARKET_TRUSTED_PROXY_COUNT` | `0` | 신뢰할 리버스 프록시 홉 수. 확인된 구성에서만 증가 |

### 검증 결과

실행 명령:

```sh
python -m pytest -q
```

결과:

```text
88 passed
```

검증한 주요 시나리오:

- IP·사용자별 신고 시도 제한과 제한 윈도당 단일 차단 로그
- 전달 IP 헤더 기본 미신뢰와 IP HMAC IPv6 정규화
- 안전하지 않은 신뢰 프록시 수 환경변수 거부
- 검증·개인정보·중복·횟수 제한 실패 감사 로그
- 감사 로그에서 신고 사유·IP 원문 제외
- 이메일·일반 및 전각 전화번호·주민등록번호 패턴 거부
- Version 1.3 감사 로그 스키마 마이그레이션과 기존 이벤트 보존
- 저장소 내부 백업, 기존 파일 덮어쓰기 및 손상 DB 거부
- 백업·복구 파일 권한 `600`
- 백업·복구 SQLite 무결성과 외래키 위반 검사
- 전체 Version 1.1~1.3 보안 테스트 회귀 없음

### Version 1.4 이후 남은 보안 항목

- 신고 감사 로그 보존 기간과 승인된 정리 절차
- 외부 스케줄러를 이용한 정기 백업 자동화
- 다계정·다중 IP 신고 패턴 모니터링과 알림 시스템
- 관리자 신고 목록, 검토 상태, 처리자·처리 시각 및 권한 체계
- 관리자 화면 추가 시 신고 사유 출력 인코딩
- 다중 애플리케이션 서버 환경의 공용 Rate Limiting 저장소
- Socket 연결 인증, 메시지 검증 및 Rate Limiting
- HTTPS/WSS 강제와 보안 헤더
- Python 전체 의존성 버전 고정과 정기 취약점 검사
- 기존 Git 이력에 포함됐던 민감 DB 데이터 처리

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 1.3

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `1.3` |
| Date | `2026-07-24` |
| 변경 유형 | Minor Version |
| 적용 범위 | 사용자·상품 신고 접수, 신고 DB 스키마, 신고 감사 로그 |
| 테스트 | `tests/test_account_security.py`, `tests/test_product_security.py`, `tests/test_report_security.py` |
| 테스트 결과 | `72 passed` |

### 조치 전후 요약

| 항목 | Version 1.2 | Version 1.3 |
|---|---|---|
| 신고 CSRF | ❌ 토큰 없음 | ✅ 신고 POST에 세션 CSRF Token 적용 |
| 대상 검증 | ❌ 유형·형식·존재 여부 검증 없음 | ✅ 사용자·상품 유형, UUID 및 실제 대상 확인 |
| 자기 신고 | ❌ 제한 없음 | ✅ 자기 계정과 자신이 등록한 상품 신고 차단 |
| 사유 검증 | ❌ 필수 값 외 서버 검증 없음 | ✅ NFKC 정규화, 10~1,000자 및 제어 문자 검증 |
| 참조 무결성 | ❌ 외래키 없음 | ✅ 신고자·사용자 대상·상품 대상 외래키 적용 |
| 중복 신고 | ❌ 제한 없음 | ✅ 동일 신고자와 동일 대상의 중복 신고 차단 |
| 신고 횟수 | ❌ 제한 없음 | ✅ 사용자별 1시간 최대 5건 제한 |
| 감사 로그 | ❌ 없음 | ✅ 사유·비밀정보를 제외한 추가 전용 접수 로그 |
| 기존 데이터 | ❌ 마이그레이션 없음 | ✅ 대상 유형 판별·재검증 후 안전한 스키마로 변환 |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V1.3-CSRF-01` | 신고 Form 보호 | 신고 POST에 세션 CSRF Token 검증 | `report_post`, `templates/report.html` |
| `V1.3-REPORT-01` | 대상 유형 검증 | 사용자 또는 상품 유형만 허용 | `validate_report_input` |
| `V1.3-REPORT-02` | 대상 ID 검증 | 36자 UUID 형식 정규화와 실제 대상 존재 확인 | `validate_report_input` |
| `V1.3-REPORT-03` | 자기 신고 차단 | 자기 계정과 자신이 판매하는 상품을 애플리케이션과 DB에서 차단 | `validate_report_input`, `ensure_report_schema_objects` |
| `V1.3-REPORT-04` | 신고 사유 검증 | NFKC 정규화, 공백 제거, 10~1,000자 및 위험한 제어 문자 거부 | `validate_report_reason` |
| `V1.3-XSS-01` | XSS 비반사 | 신고 사유를 일반 텍스트로 저장하고 사용자 응답에 입력값을 반사하지 않음 | `report_post`, `tests/test_report_security.py` |
| `V1.3-AUTH-01` | 인증 사용자 접수 | 실제 로그인 사용자 ID만 신고자로 저장 | `load_and_validate_session`, `report` |
| `V1.3-DATA-01` | 신고 참조 무결성 | 신고자·사용자 대상·상품 대상 외래키와 대상 타입 `CHECK` 적용 | `create_report_table` |
| `V1.3-DATA-02` | 필수 데이터 제약 | 사유 길이·NUL, 생성 시각 타입 및 대상 컬럼 일관성 `CHECK` 적용 | `create_report_table` |
| `V1.3-ABUSE-01` | 중복 신고 제한 | 부분 고유 인덱스와 INSERT Trigger로 사용자·상품 중복 신고 차단 | `ensure_report_schema_objects` |
| `V1.3-ABUSE-02` | 사용자별 횟수 제한 | 애플리케이션과 DB Trigger에서 1시간 최대 5건 적용 | `report_post`, `ensure_report_schema_objects` |
| `V1.3-AUDIT-01` | 접수 감사 로그 | 접수·마이그레이션 이벤트, 신고자, 대상, 시각만 별도 저장 | `create_report_audit_table`, `add_report_audit_log` |
| `V1.3-AUDIT-02` | 로그 변조 방지 | 감사 로그 UPDATE·DELETE를 Trigger로 차단하고 추가 전용으로 관리 | `ensure_report_schema_objects` |
| `V1.3-TX-01` | 원자적 저장 | 신고와 감사 로그를 하나의 트랜잭션으로 저장하고 실패 시 전체 롤백 | `report_post` |
| `V1.3-MIGRATION-01` | 기존 신고 변환 | 기존 대상 유형·참조·사유·중복을 검증한 뒤 새 스키마로 이동 | `report_schema_is_current`, `migrate_report_schema` |
| `V1.3-EVIDENCE-01` | 신고 증거 보존 | 신고가 연결된 상품은 외래키로 삭제를 제한하고 일반 오류 처리 | `create_report_table`, `delete_product` |

현재 신고 사유를 조회하는 관리자 화면은 없습니다. 따라서 신고 사유를 HTML로
출력하지 않으며, 테스트에서 제출한 `<script>` 문자열이 신고·대시보드 응답에
반사되지 않는 것을 확인했습니다. 향후 관리자 화면을 추가할 때는 Jinja 자동
이스케이프와 권한 검증을 별도로 적용해야 합니다.

### 데이터베이스 변경

`report` 테이블을 다형 대상의 참조 무결성을 보장하도록 변경했습니다.

| 필드 | Version 1.2 | Version 1.3 |
|---|---|---|
| `target_id` | 검증 없는 `TEXT` | 제거 후 유형별 대상 컬럼으로 분리 |
| `target_type` | 없음 | `user` 또는 `product`만 허용 |
| `target_user_id` | 없음 | 사용자 신고 시 `user(id)` 외래키 |
| `target_product_id` | 없음 | 상품 신고 시 `product(id)` 외래키 |
| `reason` | `TEXT NOT NULL` | 10~1,000자와 NUL 차단 `CHECK` |
| `created_at` | 없음 | 서버 Unix 시각과 정수 타입 `CHECK` |

추가한 DB 보안 객체:

- `report_audit_log`: 사유·세션·CSRF Token을 기록하지 않는 접수 감사 로그
- 대상별 부분 고유 인덱스: 동일 신고자·대상 중복 방지
- 신고자·생성 시각 인덱스: 시간당 신고 횟수 조회
- DB Trigger: 시간당 5건, 중복 신고, 자기 상품 신고 우회 차단
- 감사 로그 Trigger: UPDATE와 DELETE 차단

마이그레이션 동작:

1. 기존 신고자와 대상 UUID를 검증합니다.
2. 대상이 사용자 또는 상품 중 정확히 하나에 존재하는지 확인합니다.
3. 자기 계정·자기 상품, 잘못된 사유 및 중복 신고가 있으면 중단합니다.
4. 검증된 대상은 유형별 외래키 컬럼으로 이동합니다.
5. 기존 생성 시각이 없으므로 마이그레이션 시각을 `created_at`에 기록합니다.
6. 마이그레이션된 항목은 `report_migrated` 감사 이벤트로 기록합니다.
7. 모든 과정이 성공할 때만 하나의 트랜잭션으로 커밋합니다.

로컬 개발 DB는 저장소 밖에 권한 `600`으로 백업한 뒤 마이그레이션했습니다.
마이그레이션 후 외래키 위반은 0건이며 `PRAGMA integrity_check` 결과는
`ok`였습니다. 실제 DB와 백업은 Git에 포함하지 않습니다.

### 템플릿 변경

- `templates/report.html`: CSRF Token, 대상 유형 선택, UUID 길이 및 사유 길이

브라우저 입력 속성은 사용 편의를 위한 보조 수단이며, 보안 판단은 서버 검증과
DB 제약으로 다시 수행합니다.

### 의존성 및 환경변수 변경

새 의존성과 환경변수는 없습니다.

### 검증 결과

실행 명령:

```sh
python -m pytest -q
```

결과:

```text
72 passed
```

검증한 주요 시나리오:

- 비로그인 신고와 CSRF Token 누락 차단
- 정상 사용자·상품 신고와 감사 로그의 원자적 저장
- 대상 유형·UUID·존재 여부 검증
- 자기 계정과 자기 상품 신고 차단
- 빈 값·짧은 값·초과 길이·NUL·방향 제어 문자 사유 거부
- 신고 사유의 XSS 문자열 비반사와 감사 로그 미기록
- 동일 대상 중복 신고 차단
- 사용자별 1시간 5건 제한과 DB Trigger 우회 차단
- 신고·감사 로그 DB 제약과 감사 로그 UPDATE·DELETE 차단
- 신고된 상품 삭제 제한과 신고 증거 보존
- 유효한 구버전 신고 마이그레이션과 감사 이벤트 생성
- 잘못된 구버전 신고의 마이그레이션 중단 및 원본 보존
- Version 1.1·1.2 보안 테스트 회귀 없음

### Version 1.3 이후 남은 보안 항목

- 관리자 신고 목록, 검토 상태, 처리자·처리 시각 및 권한 체계
- 관리자 처리 감사 로그와 감사 로그 보존·열람 정책
- 사용자뿐 아니라 IP 기준 신고 Rate Limiting
- 관리자 화면 추가 시 신고 사유의 출력 인코딩 회귀 테스트
- Socket 연결 인증, 메시지 검증 및 Rate Limiting
- IP 단위 로그인 Rate Limiting
- HTTPS/WSS 강제와 보안 헤더
- Python 전체 의존성 버전 고정과 정기 취약점 검사
- 기존 Git 이력에 포함됐던 민감 DB 데이터 처리

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 1.2

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `1.2` |
| Date | `2026-07-24` |
| 변경 유형 | Minor Version |
| 적용 범위 | 상품 등록, 상세 조회, 수정, 삭제, 상품 DB 스키마 |
| 테스트 | `tests/test_account_security.py`, `tests/test_product_security.py` |
| 테스트 결과 | `45 passed` |

### 조치 전후 요약

| 항목 | Version 1.1 | Version 1.2 |
|---|---|---|
| 제목·설명 검증 | ❌ 브라우저 `required` 속성만 사용 | ✅ 서버 길이·필수 값·제어 문자 검증 |
| 가격 검증 | ❌ 문자열을 검증 없이 저장 | ✅ ASCII 정수 변환과 0~10억 원 범위 검증 |
| 상품 CSRF | ❌ 토큰 없음 | ✅ 등록·수정·삭제 POST에 적용 |
| XSS 방어 | ⚠️ Jinja 자동 이스케이프만 존재하고 회귀 테스트 없음 | ✅ 일반 텍스트 출력 이스케이프와 저장형 XSS 테스트 |
| 등록 인증 | ⚠️ 로그인 확인은 있으나 실제 사용자 확인 근거 부족 | ✅ 요청마다 실제 사용자를 확인하고 서버 사용자 ID 사용 |
| 수정·삭제 권한 | ❌ 기능 없음 | ✅ 판매자만 수정·삭제 가능하며 SQL에도 소유자 조건 적용 |
| 가격 DB 타입 | ❌ `TEXT` | ✅ `INTEGER`와 타입·범위 `CHECK` |
| 판매자 참조 | ❌ 외래키 없음 | ✅ `user(id)` 외래키와 `ON DELETE RESTRICT` |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V1.2-PRODUCT-01` | 제목 검증 | NFKC 정규화, 앞뒤 공백 제거, 1~100자 및 제어 문자 거부 | `app.py`의 `validate_product_input` |
| `V1.2-PRODUCT-02` | 설명 검증 | 앞뒤 공백 제거, 1~2,000자 및 NUL 문자 거부 | `app.py`의 `validate_product_input` |
| `V1.2-PRODUCT-03` | 가격 검증 | ASCII 숫자만 허용하고 0~1,000,000,000원 정수 범위 적용 | `app.py`의 `validate_product_input` |
| `V1.2-CSRF-01` | 상품 Form 보호 | 등록·수정·삭제 POST에 세션 CSRF Token 검증 | `new_product_post`, `edit_product_post`, `delete_product` |
| `V1.2-XSS-01` | 출력 인코딩 | 상품 입력을 일반 텍스트로 취급하고 Jinja 자동 이스케이프로 출력 | `templates/dashboard.html`, `templates/view_product.html` |
| `V1.2-AUTH-01` | 등록 인증 | 로그인된 실제 사용자의 ID만 `seller_id`로 사용 | `new_product`, `new_product_post` |
| `V1.2-OWNER-01` | 수정 소유권 | 라우트와 UPDATE 조건에서 판매자 ID를 확인 | `require_product_owner`, `edit_product_post` |
| `V1.2-OWNER-02` | 삭제 소유권 | POST 전용 삭제 라우트와 DELETE 조건에서 판매자 ID를 확인 | `delete_product` |
| `V1.2-ID-01` | 상품 ID 검증 | URL의 상품 ID를 UUID로 검증하고 미존재 대상은 일반 404 응답 | `get_product_or_404` |
| `V1.2-DATA-01` | DB 제약 | 필수 값, 길이, NUL, 가격 타입·범위 `CHECK` 적용 | `create_product_table` |
| `V1.2-DATA-02` | 참조 무결성 | 판매자 외래키와 모든 앱 DB 연결의 `foreign_keys=ON` 적용 | `create_product_table`, `get_db` |
| `V1.2-DATA-03` | 안전한 실패 | 등록·수정 무결성 오류 시 롤백하고 내부정보 없는 400 응답 | `new_product_post`, `edit_product_post` |
| `V1.2-DATA-04` | 기존 데이터 마이그레이션 | 기존 값을 새 검증기로 확인한 뒤 안전한 상품 스키마로 교체 | `product_schema_is_current`, `migrate_product_schema` |

상품 제목과 설명은 HTML 입력 기능이 아니라 일반 텍스트 기능입니다. 따라서
불완전한 문자열 기반 `<script>` 제거 대신 출력 문맥에서 HTML 이스케이프합니다.
HTML을 허용하는 기능이 추가될 때에만 별도의 허용 목록 Sanitizer가 필요합니다.

### 데이터베이스 변경

`product` 테이블을 기존 데이터를 보존하면서 다음 구조로 강화했습니다.

| 필드 | Version 1.1 | Version 1.2 |
|---|---|---|
| `title` | `TEXT NOT NULL` | `TEXT NOT NULL`, 공백 제외 1~100자 및 NUL 차단 `CHECK` |
| `description` | `TEXT NOT NULL` | `TEXT NOT NULL`, 공백 제외 1~2,000자 및 NUL 차단 `CHECK` |
| `price` | `TEXT NOT NULL` | `INTEGER NOT NULL`, 정수 타입 및 0~10억 원 `CHECK` |
| `seller_id` | `TEXT NOT NULL` | `TEXT NOT NULL`, `user(id)` 외래키, 삭제 제한 |

마이그레이션 동작:

1. 현재 상품 스키마의 타입, 외래키 및 필수 `CHECK` 제약을 확인합니다.
2. 구버전 상품을 서버 검증 함수로 다시 검증하고 판매자 존재 여부를 확인합니다.
3. 검증할 수 없는 기존 행이 있으면 마이그레이션을 중단하고 원인을 알립니다.
4. 기존 테이블을 임시 이름으로 변경하고 강화된 테이블을 생성합니다.
5. 검증된 상품만 정수 가격으로 옮긴 뒤 구버전 테이블을 제거합니다.
6. 전체 초기화 트랜잭션이 성공할 때만 커밋합니다.

로컬 개발 DB는 저장소 밖에 권한 `600`으로 백업한 뒤 마이그레이션했습니다.
마이그레이션 후 `PRAGMA foreign_key_check`에 위반이 없었고
`PRAGMA integrity_check` 결과는 `ok`였습니다. `market.db`와 백업은 Git에
포함하지 않습니다.

### 템플릿 변경

- `templates/new_product.html`: CSRF, 제목·설명 길이, 정수 가격 범위
- `templates/edit_product.html`: 소유자용 상품 수정 Form과 동일한 입력 제한
- `templates/view_product.html`: 소유자에게만 수정 링크와 CSRF 삭제 Form 표시

브라우저 속성은 사용 편의를 위한 보조 수단이며, 실제 보안 판단은 서버 검증과
DB 제약으로 수행합니다.

### 의존성 및 환경변수 변경

새 의존성과 환경변수는 없습니다.

### 검증 결과

실행 명령:

```sh
python -m pytest -q
```

결과:

```text
45 passed
```

검증한 주요 시나리오:

- 비로그인 사용자의 상품 등록 차단
- 등록·수정·삭제의 CSRF Token 누락 차단
- 정상 상품의 정규화와 정수 가격 저장
- 빈 값, 공백, 초과 길이, 제어 문자 및 NUL 문자 거부
- 음수·소수·지수·전각 숫자·상한 초과 가격 거부
- `<script>`와 이벤트 핸들러 문자열의 저장형 XSS 출력 이스케이프
- 소유자의 수정·삭제 성공
- 비소유자의 직접 URL 수정·삭제 요청을 403으로 차단
- DB `CHECK`와 판매자 외래키 우회 저장 차단
- 구버전 `TEXT` 가격 상품 데이터의 마이그레이션
- 비정상·미존재 상품 ID의 내부정보 없는 404 응답
- Version 1.1 회원 보안 테스트 회귀 없음

### Version 1.2 이후 남은 보안 항목

- 신고 Form CSRF와 서버측 입력·참조 검증
- Socket 연결 인증, 메시지 검증 및 Rate Limiting
- IP 단위 로그인 Rate Limiting
- HTTPS/WSS 강제와 보안 헤더
- 신고 테이블 외래키, 감사 로그와 신고 남용 방지
- Python 전체 의존성 버전 고정과 정기 취약점 검사
- 기존 Git 이력에 포함됐던 민감 DB 데이터 처리

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 1.1

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `1.1` |
| Date | `2026-07-24` |
| 변경 유형 | Minor Version |
| 적용 범위 | 회원가입, 로그인, 로그아웃, 세션, 프로필 |
| 테스트 | `tests/test_account_security.py` |
| 테스트 결과 | `18 passed` |

### 조치 전후 요약

| 항목 | Version 1.0 | Version 1.1 |
|---|---|---|
| 서버측 입력 검증 | ⚠️ Jinja 자동 이스케이프 외 별도 검증 없음 | ✅ 사용자명·비밀번호·소개글 길이와 형식 검증 |
| CSRF 보호 | ❌ 토큰 없음 | ✅ 회원가입·로그인·프로필·로그아웃 적용 |
| 비밀번호 보안 | ❌ 평문 저장과 평문 SQL 비교 | ✅ Argon2id 해시, 무작위 Salt 및 기존 데이터 마이그레이션 |
| 세션 쿠키 | ⚠️ HttpOnly 기본값 의존, Secure 없음 | ✅ HttpOnly·Secure·SameSite 명시 |
| 세션 만료 | ❌ 만료 정책 없음 | ✅ 30분 유휴 만료와 8시간 절대 만료 |
| 민감 작업 재인증 | ❌ 없음 | ✅ 프로필 수정 시 현재 비밀번호 확인 |
| 실패 로그인 방어 | ❌ 횟수 제한과 잠금 없음 | ✅ 5회 실패 시 15분 계정 잠금 |
| 오류 정보 보호 | ❌ 디버그 모드와 공통 오류 처리 부재 | ✅ 디버그 기본 비활성화와 일반 오류 응답 |

### 상세 적용 내역

| ID | 보안 조치 | 적용 내용 | 코드 근거 |
|---|---|---|---|
| `V1.1-ACCOUNT-01` | 사용자명 검증 | NFKC 정규화, 3~30자 제한, 문자·숫자·밑줄·마침표·하이픈 허용 | `app.py:147-156`, `app.py:291-296` |
| `V1.1-ACCOUNT-02` | 비밀번호 정책 | 12~128자, 문자·숫자 필수, 공백과 제어 문자 거부 | `app.py:159-168`, `app.py:291-296` |
| `V1.1-PROFILE-01` | 소개글 검증 | 최대 500자와 NUL 문자 차단 | `app.py:171-176`, `app.py:414-419` |
| `V1.1-XSS-01` | HTML 출력 인코딩 | Jinja 자동 이스케이프를 유지하고 XSS 회귀 테스트 추가 | `templates/profile.html`, `tests/test_account_security.py` |
| `V1.1-XSS-02` | JavaScript 인코딩 | 사용자명을 JavaScript에 삽입할 때 `tojson` 사용 | `templates/dashboard.html:39` |
| `V1.1-CSRF-01` | CSRF Token | 세션 토큰 생성과 `hmac.compare_digest` 상수 시간 비교 | `app.py:179-203` |
| `V1.1-CSRF-02` | Form 보호 | 회원가입·로그인·프로필 Form에 CSRF Token 추가 | `templates/register.html`, `templates/login.html`, `templates/profile.html` |
| `V1.1-CSRF-03` | 안전한 로그아웃 | 로그아웃을 GET에서 CSRF 보호된 POST로 변경 | `app.py:384-390`, `templates/base.html:106-109` |
| `V1.1-PASSWORD-01` | Argon2id | `PasswordHasher`로 비밀번호 해시와 검증 수행 | `app.py:62-65`, `app.py:206-210`, `app.py:300-310` |
| `V1.1-PASSWORD-02` | 고유 Salt | argon2-cffi가 생성하는 사용자별 무작위 Salt 사용 | `app.py:300` |
| `V1.1-PASSWORD-03` | 평문 제거 | 로그인 SQL의 평문 비밀번호 비교 제거 | `app.py:338-373` |
| `V1.1-PASSWORD-04` | 기존 데이터 마이그레이션 | Argon2 형식이 아닌 기존 비밀번호를 초기화 시 자동 변환 | `app.py:97-104`, `app.py:142-144` |
| `V1.1-SESSION-01` | 비밀키 관리 | 하드코딩된 키를 제거하고 32자 이상 환경변수를 필수화 | `app.py:29-35`, `app.py:50-59` |
| `V1.1-SESSION-02` | 쿠키 보안 | HttpOnly, Secure, SameSite=Lax를 명시적으로 설정 | `app.py:50-59` |
| `V1.1-SESSION-03` | 세션 만료 | 30분 유휴 만료와 8시간 절대 만료 적용 | `app.py:22-25`, `app.py:229-261` |
| `V1.1-SESSION-04` | 세션 초기화 | 로그인 성공 시 이전 세션을 제거하고 인증 시각 기록 | `app.py:375-380` |
| `V1.1-SESSION-05` | 사용자 유효성 | 요청마다 세션의 사용자 ID가 실제 사용자와 일치하는지 확인 | `app.py:250-258` |
| `V1.1-PROFILE-02` | 프로필 재인증 | 소개글을 변경하기 전에 현재 비밀번호 확인 | `app.py:412-431`, `templates/profile.html` |
| `V1.1-LOGIN-01` | 로그인 실패 기록 | 사용자별 실패 횟수와 잠금 만료 시각 저장 | `app.py:84-94`, `app.py:213-226` |
| `V1.1-LOGIN-02` | 계정 잠금 | 5회 실패 시 15분 잠금 | `app.py:22-23`, `app.py:349-358` |
| `V1.1-LOGIN-03` | 계정 열거 방어 | 로그인 실패·잠금 메시지를 일반화하고 존재하지 않는 계정에도 Argon2 검증 비용 적용 | `app.py:63-65`, `app.py:344-358` |
| `V1.1-REGISTER-01` | 중복 계정 열거 방어 | 성공·중복 회원가입 응답과 해시 비용을 동일하게 처리 | `app.py:298-319` |
| `V1.1-ERROR-01` | 디버그 비활성화 | `MARKET_DEBUG` 기본값을 false로 설정 | `app.py:38-59`, `app.py:545-547` |
| `V1.1-ERROR-02` | 공통 오류 화면 | 400, 403, 404, 429, 500 응답에서 내부정보를 숨김 | `app.py:498-542`, `templates/error.html` |
| `V1.1-DOS-01` | 요청 크기 | HTTP 요청 본문을 최대 1 MiB로 제한 | `app.py:54` |
| `V1.1-DATA-01` | 로컬 DB 제외 | `market.db`와 SQLite journal 파일을 Git 추적 대상에서 제외 | `.gitignore` |

### 데이터베이스 변경

`user` 테이블에 기존 기능과 호환되는 로그인 보안 컬럼을 추가했습니다.

| 컬럼 | 타입 | 기본값 | 용도 |
|---|---|---|---|
| `failed_login_attempts` | `INTEGER NOT NULL` | `0` | 연속 로그인 실패 횟수 |
| `locked_until` | `INTEGER` | `NULL` | 계정 잠금 종료 Unix 시각 |

마이그레이션 동작:

1. 기존 `user` 테이블의 컬럼을 확인합니다.
2. 누락된 로그인 보안 컬럼만 추가합니다.
3. Argon2 형식이 아닌 기존 비밀번호를 Argon2id로 변환합니다.
4. 마이그레이션과 스키마 초기화를 하나의 DB 커밋으로 완료합니다.

로컬 개발 DB의 기존 사용자 2명은 모두 Argon2 형식으로 변환했습니다.
`market.db`는 Git 추적 대상에서 제거했으며 애플리케이션 시작 시 필요한 테이블과
마이그레이션을 재현합니다. 단, Version 1.0 이전 Git 이력에 들어간 DB 데이터는
이 커밋만으로 삭제되지 않으며 별도의 이력 정리와 자격 증명 교체가 필요합니다.

### 템플릿 변경

- `templates/register.html`: CSRF, 사용자명·비밀번호 길이, 자동완성 속성
- `templates/login.html`: CSRF, 입력 길이, 자동완성 속성
- `templates/profile.html`: CSRF, 소개글 길이, 현재 비밀번호 재인증 입력
- `templates/base.html`: POST 로그아웃 Form과 CSRF Token
- `templates/dashboard.html`: 사용자명 JavaScript `tojson` 인코딩
- `templates/error.html`: 내부정보를 포함하지 않는 공통 오류 화면

### 의존성 변경

| 패키지 | Version | 용도 |
|---|---|---|
| `argon2-cffi` | `25.1.0` | Argon2id 비밀번호 해시와 검증 |
| `pytest` | `8.4.2` | 보안 자동 테스트 |

두 패키지는 `enviroments.yaml`에 추가했습니다.

### 환경변수

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `MARKET_SECRET_KEY` | 없음 | 32자 이상 필수. 누락 또는 길이 부족 시 실행 중단 |
| `MARKET_COOKIE_SECURE` | `true` | HTTPS 세션 쿠키. 로컬 HTTP 개발에서만 `false` |
| `MARKET_DEBUG` | `false` | 공개 환경에서는 항상 `false` |

### 검증 결과

실행 명령:

```sh
python -m pytest -q
```

결과:

```text
18 passed
```

검증한 주요 시나리오:

- 유효·무효 사용자명과 비밀번호
- Argon2id 저장, 검증 및 사용자별 Salt
- 중복 회원가입의 기존 계정 보호
- CSRF Token 누락 요청 차단
- 프로필 비밀번호 재인증
- 소개글 저장형 XSS 출력 인코딩
- 소개글 최대 길이
- HttpOnly, Secure, SameSite 쿠키
- 유휴 세션과 절대 세션 만료
- 5회 로그인 실패와 15분 계정 잠금
- 기존 DB 스키마와 평문 비밀번호 마이그레이션
- 비밀키 필수 설정과 디버그 기본 비활성화
- 오류 페이지의 Stack Trace와 DB 정보 비노출

### Version 1.1 이후 남은 보안 항목

- IP 단위 로그인 Rate Limiting
- 상품·신고 Form CSRF 보호
- 상품·신고 서버측 입력 검증
- Socket 연결 인증, 메시지 검증 및 Rate Limiting
- 데이터베이스 외래키와 참조 무결성
- HTTPS 강제와 보안 헤더
- 감사 로그와 신고 남용 방지
- Python 전체 의존성 버전 고정과 정기 취약점 검사

전체 현재 상태는 `SECURITY_REVIEW.md`에서 관리합니다.

---

## Version 1.0

### 버전 정보

| 항목 | 내용 |
|---|---|
| Version | `1.0` |
| Date | `2026-07-24` |
| 변경 유형 | 최초 기준 버전 |
| 기반 코드 | [ugonfor/secure-coding](https://github.com/ugonfor/secure-coding) |
| 검증 | 정적 코드와 SQLite 스키마 점검 |

### 최초 보안 상태

| 항목 | 상태 | 확인 결과 |
|---|---|---|
| 서버측 입력 검증 | ⚠️ | 사용자명·비밀번호·소개글의 길이·형식·허용 문자 검증이 없고 Jinja 자동 이스케이프만 일부 적용 |
| CSRF 보호 | ❌ | 회원가입·로그인·프로필 수정 Form에 CSRF Token 없음 |
| 비밀번호 보안 | ❌ | 비밀번호를 평문으로 저장하고 SQL에서 평문 직접 비교 |
| 세션 쿠키 | ⚠️ | HttpOnly는 Flask 기본값에 의존하고 Secure 설정 없음 |
| 세션 만료 및 재인증 | ❌ | 만료, 유휴 시간 제한 및 민감 작업 재인증 없음 |
| 실패 로그인 방어 | ❌ | 실패 횟수, 지연, 계정 잠금 및 IP 제한 없음 |
| 오류 메시지 | ❌ | 로그인 실패 문구만 일반화되어 있고 전역 예외 처리 없이 `debug=True` 실행 |

### 최초 확인된 주요 위험

- 하드코딩된 `SECRET_KEY = 'secret!'`
- 평문 비밀번호 저장과 비교
- 모든 회원 Form의 CSRF Token 부재
- 서버측 입력 검증 부재
- Secure 세션 쿠키와 세션 만료 부재
- 로그인 실패 제한과 계정 잠금 부재
- 디버그 모드에 의한 내부정보 노출 가능성
- 기존 DB의 평문 사용자 비밀번호

### Version 1.0 테스트

자동 테스트는 없었으며 정적 코드, 템플릿, SQLite 테이블과 실제 저장 형식만
점검했습니다.

---

## 다음 버전 작성 형식

새 버전을 추가할 때 이 문서의 맨 위에 다음 구조로 기록합니다.

```md
## Version X.Y

### 버전 정보

- Version, Date, 변경 유형, 적용 범위, 테스트

### 조치 전후 요약

- 직전 버전과 현재 버전 비교

### 상세 적용 내역

- 고유 ID, 조치, 적용 내용, 코드 근거

### 데이터베이스 변경

- 스키마, 데이터 마이그레이션, 호환성과 롤백

### 템플릿·의존성·환경변수 변경

- 변경된 파일과 운영 설정

### 검증 결과

- 실행 명령, 테스트 개수와 주요 시나리오

### 남은 보안 항목

- 다음 버전에서 처리할 위험과 제한사항
```

버전 번호를 변경하면 `AGENTS.md`, `README.md`, `FEATURE_CHANGELOG.md`,
`SECURITY_REVIEW.md`, `VERSIONING.md`와 이 문서의 현재 버전·변경 이력을 함께
갱신하고, 테스트 후 버전 커밋을 생성합니다. 기능 추가·변경·제거 내용은
`FEATURE_CHANGELOG.md`에도 같은 버전으로 기록합니다.
