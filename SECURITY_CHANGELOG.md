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
| `1.1` | `2026-07-24` | 회원가입, 로그인, 세션 및 프로필 보안 강화 | 자동 테스트 18개 통과 |
| `1.0` | `2026-07-24` | 기반 코드 점검과 최초 취약점 식별 | 정적 점검 |

표기:

- ✅: 해당 버전에서 적용 및 검증 완료
- ⚠️: 일부 방어만 존재하거나 후속 개선 필요
- ❌: 해당 버전에서 미적용
- N/A: 해당 버전에 기능이 없음

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
