# 버전별 보안 조치

이 문서는 각 버전에서 적용한 보안 조치와 검증 결과를 버전별로 기록합니다.
최신 버전을 위에 두며, 모든 버전은 동일한 구조로 작성합니다.

## 문서 안내

| 문서 | 역할 |
|---|---|
| `README.md` | 현재 버전과 설치·실행 방법 |
| `SECURITY_CHANGELOG.md` | 버전별로 적용한 보안 조치와 테스트 이력 |
| `SECURITY_REVIEW.md` | 현재 코드 기준 전체 보안 체크리스트와 남은 작업 |
| `VERSIONING.md` | 버전 결정과 필수 커밋 절차 |

## 버전 빠른 보기

| Version | Date | 주요 보안 범위 | 검증 |
|---|---|---|---|
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

버전 번호를 변경하면 `README.md`, `SECURITY_REVIEW.md`, `VERSIONING.md`와 이
문서의 현재 버전·변경 이력을 함께 갱신하고, 테스트 후 버전 커밋을 생성합니다.
