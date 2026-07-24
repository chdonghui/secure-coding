# 안전한 중고거래 플랫폼

Flask와 Flask-SocketIO로 만든 소규모 중고거래 학습 프로젝트입니다. 회원가입,
로그인, 마이페이지·회원 탈퇴, 공개 상품 조회, 상품 등록·수정·삭제와 내 상품
관리, 학습용 사용자 간 송금, 전체·1대1 실시간 채팅 및 신고 기능을 포함합니다.
관리자는 별도 권한으로 불량 상품을 관리 삭제하고 불량 사용자를 휴면·해제할 수
있습니다.

이 프로젝트는 [ugonfor/secure-coding](https://github.com/ugonfor/secure-coding)
저장소에서 가져온 기반 코드를 바탕으로 보안 취약점을 분석하고 개선하는 실습용
프로젝트입니다. 웹 애플리케이션 보안 조치의 적용 전후를 학습하고 자동 테스트로
검증하는 것을 목적으로 합니다.

교육 및 실습 목적으로만 사용하며, 현재 개발 서버와 구성 그대로 실제 서비스나
운영 환경에 배포하지 않습니다. 원본 프로젝트와 외부 패키지를 사용할 때는 각
저장소의 라이선스와 이용 조건을 별도로 확인해야 합니다.

- 현재 버전: `4.1`
- 빠른 실행: [docs/QUICK_START.md](docs/QUICK_START.md)
- 관리자 계정 빠른 시작:
  [docs/ADMIN_QUICK_START.md](docs/ADMIN_QUICK_START.md)
- 테스트: [docs/TESTING.md](docs/TESTING.md)
- AI 작업 규칙: [AGENTS.md](AGENTS.md)
- 버전별 기능 설명:
  [docs/FEATURE_CHANGELOG.md](docs/FEATURE_CHANGELOG.md)
- 버전별 보안 조치:
  [docs/SECURITY_CHANGELOG.md](docs/SECURITY_CHANGELOG.md)
- 보안 현황: [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md)
- 버전 및 커밋 규칙: [docs/VERSIONING.md](docs/VERSIONING.md)

## 개발 환경

- macOS
- Homebrew
- Git 및 GitHub
- Python 3.12
- Miniconda
- ChatGPT, Codex, Claude

## 1. 사전 준비

### Git 설치

Git이 없다면 Homebrew로 설치합니다.

```sh
brew install git
git --version
```

### ngrok 설치

ngrok은 로컬의 `5000` 포트를 외부 HTTPS 주소로 연결할 때 사용합니다.

macOS에서는 [ngrok 공식 macOS 설치 페이지](https://ngrok.com/download/mac-os)의
Homebrew 명령을 사용합니다.

```sh
brew install ngrok
ngrok version
```

ngrok 계정의 인증 토큰을 발급받았다면 다음과 같이 등록합니다.

```sh
ngrok config add-authtoken "<YOUR_AUTHTOKEN>"
```

사용자가 참고한 [Linux용 Snap 설치 페이지](https://ngrok.com/downloads/linux?tab=snap)는
Linux 환경용입니다. 이 프로젝트의 기본 개발환경인 macOS에서는 위 Homebrew 설치
방법을 사용합니다.

### Miniconda 설치

전체 설치 안내는 [Anaconda Miniconda 설치 문서](https://www.anaconda.com/docs/getting-started/miniconda/install)를
참고합니다.

먼저 Mac의 CPU 아키텍처를 확인합니다.

```sh
uname -m
```

- `arm64`: Apple Silicon(M1 이상)
- `x86_64`: Intel Mac

아래 과정은 Apple Silicon 기준입니다. 최신 명령줄 설치 프로그램을 홈 디렉터리에
다운로드합니다.

```sh
cd ~
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
```

#### 설치 파일 무결성 확인

설치 전에 SHA-256 해시를 계산합니다.

```sh
shasum -a 256 Miniconda3-latest-MacOSX-arm64.sh
```

출력된 값을 [Miniconda 공식 배포 목록](https://repo.anaconda.com/miniconda/)의
동일 파일 SHA-256 값과 비교합니다. 두 값이 정확히 같을 때만 설치를 계속합니다.

`latest` 파일은 새 버전이 배포될 때 변경되므로 README에 적힌 과거 해시값을
정답으로 사용하면 안 됩니다. 반드시 다운로드한 시점의 공식 해시와 비교합니다.
자세한 원리는 [Conda의 암호학적 해시 검증 안내](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html#cryptographic-hash-verification)를
참고합니다.

#### Miniconda 설치 및 셸 초기화

```sh
bash ~/Miniconda3-latest-MacOSX-arm64.sh
~/miniconda3/bin/conda init zsh
```

설치가 끝나면 터미널을 종료한 뒤 다시 실행하고 정상 설치 여부를 확인합니다.

```sh
conda --version
conda info --envs
```

설치 위치를 기본값이 아닌 다른 경로로 선택했다면 `conda init` 명령의 경로도
실제 설치 경로에 맞게 변경해야 합니다.

## 2. 저장소 내려받기

```sh
git clone https://github.com/chdonghui/secure-coding
cd secure-coding
```

## 3. Python 환경과 의존성 설치

### 권장 방법: 환경 파일로 한 번에 설치

저장소의 `enviroments.yaml`에는 Python 버전과 프로젝트의 직접 의존성이 정의되어
있습니다. 다음 명령 하나로 별도의 Conda 환경과 필요한 패키지를 함께 설치합니다.

```sh
conda env create -f enviroments.yaml
conda activate secure_coding
```

환경이 이미 만들어져 있고 `enviroments.yaml`에 패키지가 추가된 경우에는 다음
명령으로 환경을 갱신합니다.

```sh
conda activate secure_coding
conda env update -f enviroments.yaml
```

설치 결과를 확인합니다.

```sh
python --version
python -m pip check
python -m pip list
```

[Conda 환경 파일 공식 문서](https://docs.conda.io/projects/conda/en/latest/commands/env/create.html)에
따르면 `conda env create -f <파일>`을 사용해 YAML 파일에 정의된 환경을 재현할 수
있습니다. 패키지를 하나씩 설치하면 누락이나 버전 차이가 생길 수 있으므로 환경
파일 사용을 우선합니다.

### 잠금 파일로 설치하는 방법

Conda를 사용하지 않을 때는 Python 3.12 가상환경에 해시가 고정된
`requirements.lock`을 설치합니다. 이 파일은 직접·간접 의존성의 정확한 버전과
배포 파일 SHA-256을 모두 고정합니다.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m pip check
```

`requirements.in`은 사람이 관리하는 직접 의존성 목록이고,
`requirements.lock`은 설치와 CI에서 사용하는 전체 잠금 목록입니다. 임의로
패키지를 하나씩 설치하면 검증한 조합과 달라질 수 있으므로 일반 개발자는
`enviroments.yaml` 또는 `requirements.lock` 중 하나를 사용합니다.

## 4. 패키지와 의존성

### 직접 사용하는 PyPI 패키지

| 패키지·버전 | 어디에 사용했는가 | 역할과 실제 사용 방식 |
|---|---|---|
| [`Flask==3.1.3`](https://pypi.org/project/Flask/3.1.3/) | `app.py`, `templates/` | HTTP 라우트, 요청·응답, 세션, CSRF 처리, Jinja 템플릿과 오류 처리를 담당합니다. `Flask`, `request`, `session`, `render_template`, `abort` 등을 직접 import해 사용합니다. |
| [`Flask-SocketIO==5.6.1`](https://pypi.org/project/Flask-SocketIO/5.6.1/) | `app.py`의 Socket 연결과 `send_message`, `send_direct_message` 이벤트 | 로그인된 사용자의 전체·1대1 실시간 채팅, 개인 Room, 연결 종료와 테스트 클라이언트를 제공합니다. `SocketIO`, `emit`, `send`, `join_room`, `disconnect`를 직접 사용합니다. |
| [`argon2-cffi==25.1.0`](https://pypi.org/project/argon2-cffi/25.1.0/) | `app.py`의 회원가입, 로그인, 비밀번호 변경·탈퇴·관리자 재인증과 기존 DB 마이그레이션 | `PasswordHasher`로 비밀번호를 Argon2id 해시하고 `verify`로 비교합니다. 평문 비밀번호는 DB에 저장하지 않으며 필요하면 로그인 때 현재 파라미터로 재해시합니다. |
| [`pytest==9.0.3`](https://pypi.org/project/pytest/9.0.3/) | `tests/` 전체 | 정상·실패·권한 우회·XSS·CSRF·Rate Limit·DB Trigger·마이그레이션을 자동 회귀 테스트합니다. 애플리케이션 실행에는 필요 없지만 개발과 CI 검증에 필요합니다. |
| [`pip-audit==2.10.1`](https://pypi.org/project/pip-audit/2.10.1/) | `.github/workflows/security-tests.yml`, 로컬 보안 점검 | Python Packaging Advisory Database 등 알려진 취약점 정보를 기준으로 잠금 의존성을 검사합니다. 애플리케이션 런타임이 아닌 개발·CI 도구입니다. |

설치 명령은 모두 다음 입력 파일에 같은 버전으로 기록되어 있습니다.

- `enviroments.yaml`: Python 3.12 Conda 환경과 직접 PyPI 의존성
- `requirements.in`: 잠금 파일 생성의 직접 의존성 입력
- `requirements.lock`: 직접·간접 의존성, 버전과 해시를 포함한 설치 기준

직접 의존성만 임시로 확인하는 명령은 아래와 같지만, 실제 프로젝트 환경은 위
잠금 파일 설치 방법을 사용해야 합니다.

```sh
python -m pip install -r requirements.in
```

### 자동 설치되는 간접 의존성

아래 패키지는 소스에서 직접 import하기 위한 목록이 아니라, 위 직접 패키지가
내부 동작을 위해 요구하는 하위 패키지입니다. 개별 설치하지 않습니다.

| 상위 기능 | 잠금된 간접 패키지 | 맡는 역할 |
|---|---|---|
| Flask 웹 실행 | `blinker`, `click`, `itsdangerous`, `Jinja2`, `MarkupSafe`, `Werkzeug` | Signal, CLI, 서명, 템플릿, HTML 안전 문자열, WSGI·요청 처리를 지원합니다. |
| Socket.IO·WebSocket | `bidict`, `python-engineio`, `python-socketio`, `simple-websocket`, `h11`, `wsproto` | Socket.IO 프로토콜, Engine.IO 전송, WebSocket과 HTTP/1.1 처리를 지원합니다. |
| Argon2 | `argon2-cffi-bindings`, `cffi`, `pycparser`, `typing-extensions` | Argon2 네이티브 바인딩과 Python C FFI 호환 계층을 제공합니다. |
| pytest | `iniconfig`, `packaging`, `pluggy`, `Pygments` | 테스트 설정, 버전 처리, Plugin 실행과 실패 출력 강조를 지원합니다. |
| pip-audit | `boolean-py`, `CacheControl`, `certifi`, `charset-normalizer`, `cyclonedx-python-lib`, `defusedxml`, `filelock`, `idna`, `license-expression`, `markdown-it-py`, `mdurl`, `msgpack`, `packageurl-python`, `pip`, `pip-api`, `pip-requirements-parser`, `platformdirs`, `py-serializable`, `pyparsing`, `requests`, `rich`, `sortedcontainers`, `tomli`, `tomli-w`, `urllib3` | 잠금 파일 해석, Advisory 조회, HTTP 인증서 검증, 캐시, Package URL·SBOM 자료 구조와 CLI 출력을 지원합니다. |

정확한 간접 버전과 플랫폼별 해시는 `requirements.lock`이 단일 기준입니다.
예를 들어 소스에서는 SQLite를 사용하지만 Python 표준 라이브러리의 `sqlite3`를
사용하므로 별도 PyPI 패키지나 `Flask-SQLAlchemy`가 필요하지 않습니다.
`hashlib`, `hmac`, `ipaddress`, `secrets`, `threading`, `unicodedata`, `uuid`도
Python 표준 라이브러리입니다.

### 브라우저 의존성

`templates/base.html`은 실시간 채팅 클라이언트로 cdnjs의
`Socket.IO JavaScript 4.0.1`을 불러옵니다. PyPI 패키지가 아니며
`Flask-SocketIO` 서버와 브라우저 사이의 연결에 사용됩니다. 파일 변조를 막기
위해 `integrity` SHA-384와 `crossorigin="anonymous"`를 지정했습니다. CSP도
cdnjs 스크립트만 명시적으로 허용합니다.

## 5. 실행 설정

### 세션 비밀키

애플리케이션을 실행하려면 32자 이상의 무작위 `MARKET_SECRET_KEY`가 필요합니다.
다음 명령은 현재 터미널 세션에서 사용할 임시 비밀키를 생성합니다.

```sh
export MARKET_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

비밀키를 소스 코드, README, Git 커밋 또는 공개 채팅에 기록하지 마세요. 터미널을
다시 열면 새로운 키를 설정해야 하며, 키가 변경되면 기존 로그인 세션은
무효화됩니다.

### 쿠키와 디버그 설정

세션 쿠키의 Secure 설정은 기본적으로 활성화됩니다.

로컬 HTTP 주소로만 개발할 때:

```sh
export MARKET_COOKIE_SECURE=false
export MARKET_DEBUG=false
export MARKET_REQUIRE_HTTPS=false
```

ngrok HTTPS 주소로 접속할 때:

```sh
export MARKET_COOKIE_SECURE=true
export MARKET_DEBUG=false
export MARKET_REQUIRE_HTTPS=true
export MARKET_TRUSTED_PROXY_COUNT=1
export MARKET_TRUSTED_HOSTS="<ASSIGNED_NGROK_HOST>"
```

`MARKET_DEBUG=true`는 오류 정보가 노출될 수 있으므로 공개 환경에서 사용하면
안 됩니다.

`MARKET_REQUIRE_HTTPS=true`이면 평문 HTTP 요청과 평문 Socket.IO 연결을
거부합니다. HTTPS 페이지에서 실행되는 채팅 클라이언트는 같은 Origin의 WSS
연결을 사용합니다. TLS 인증서와 HTTPS 종료는 ngrok 또는 통제하는 리버스
프록시에서 제공해야 합니다.

### 신뢰 Host 설정

Host Header 공격을 막기 위해 기본값은 `localhost`, `127.0.0.1`, `[::1]`만
허용합니다. 다른 개발 도메인이나 ngrok 주소를 사용할 때 Scheme과 경로를
제외한 Host만 쉼표로 구분해 지정합니다.

```sh
export MARKET_TRUSTED_HOSTS="market.example,localhost"
```

ngrok이 `https://example.ngrok-free.app`을 할당했다면 값은
`example.ngrok-free.app`입니다. `https://`나 `/path`를 넣으면 안전을 위해
애플리케이션 시작을 중단합니다.

### 신뢰 프록시 설정

신고·채팅 IP 제한은 기본적으로 직접 연결된 클라이언트 주소만 사용하며
전달된 클라이언트 IP와 프로토콜 헤더를 신뢰하지 않습니다.

```sh
export MARKET_TRUSTED_PROXY_COUNT=0
```

통제하는 리버스 프록시가 애플리케이션 바로 앞에 하나 있는 구성이 확실할 때만
다음과 같이 설정합니다.

```sh
export MARKET_TRUSTED_PROXY_COUNT=1
```

실제 프록시 수보다 큰 값을 설정하면 공격자가 전달한 IP 헤더를 신뢰할 수
있습니다. 프록시 구성을 확인할 수 없다면 기본값 `0`을 유지하세요.

채팅은 Origin이 없는 연결과 교차 Origin 연결을 거부하고 연결 시 세션 CSRF
Token을 확인합니다.
메시지는 1~500자이며 브라우저의 `textContent`로 출력됩니다. 기본 전송 제한은
사용자별 10초에 5건, IP별 1분에 30건이고 동일 메시지는 5초 안에 반복할 수
없습니다. 연결 시도는 IP별 1분에 20회, 동시 연결은 사용자별 5개로 제한합니다.

상단의 `1대1 채팅` 메뉴에서는 다른 사용자를 선택해 비공개 메시지를 전송할 수
있습니다. 1대1 메시지는 발신자와 수신자에게만 실시간 전달되고 SQLite에
저장되며, 대화 화면은 페이지당 최근 100건을 표시합니다. 사용자는 상대를
차단·해제할 수 있고 어느 한쪽이 차단하면 직접 메시지 전송이 거부됩니다. 전체
채팅과 1대1 채팅은 동일한 사용자·IP 전송 제한을 공유합니다.

## 6. 실행과 배포

모든 명령은 GitHub에서 내려받은 저장소 루트에서 상대경로로 실행합니다.
일반 사용자와 관리자는 별도 서버가 아니라 하나의 애플리케이션과 DB를 사용하며
계정 역할로 접근 권한만 구분합니다.

### 테스트 계정이 포함된 가장 빠른 로컬 실행

다음 명령은 저장소 밖의 임시 DB에 관리자 1명·일반 사용자 `user1`, `user2`, 학습용 송금
잔액, 사과·바나나 상품과 신고를 자동으로 만들고 서버를 실행합니다.

```sh
./scripts/quickstart_demo.sh
```

터미널에 출력된 무작위 임시 비밀번호로 로그인합니다. `Ctrl+C`로 종료하면 임시
DB와 계정이 삭제되며 일반 실행용 `market.db`는 변경하지 않습니다. 자세한
흐름은 [빠른 실행 가이드](docs/QUICK_START.md)와
[관리자 계정 빠른 시작](docs/ADMIN_QUICK_START.md)을 참고합니다.

### 학습용 송금의 한계

송금 화면의 내역은 개인정보 노출을 줄이기 위해 돈의 이동 방향과 금액만
표시합니다. 이 기능은 다음 범위의 로컬 보안 실습용 원장입니다.

- 실제 현금·은행 계좌·전자지급수단과 연결되지 않으며, 토스페이먼츠 결제나
  지급대행 API를 호출하지 않습니다.
- 빠른 실행에서만 두 계정에 예시 잔액을 넣고, 일반 회원가입 계정의 초기 잔액은
  0원입니다. 운영자 충전·출금, 환불, 수수료, 정산 기능은 없습니다.
- 송금은 일반 사용자끼리만 가능하며 관리자 계정에는 송금 메뉴와 처리 권한이
  없습니다. `user1`과 `user2`는 서로 양방향으로 송금할 수 있습니다.
- 상품 주문·결제와 송금은 연결되지 않습니다. 사과·바나나 상품은 화면 확인용
  테스트 데이터일 뿐입니다.
- SQLite 단일 파일과 로컬 프로세스를 전제로 하므로 운영 수준의 동시성,
  원장 대사, 이상거래 탐지, 알림, 분쟁·복구 절차를 제공하지 않습니다.

### 데이터를 유지하는 로컬 실행

```sh
conda activate secure_coding
SECURE_CODING_PYTHON="${CONDA_PREFIX}/bin/python"

export MARKET_SECRET_KEY="$(
  "${SECURE_CODING_PYTHON}" -c \
    'import secrets; print(secrets.token_urlsafe(48))'
)"
export MARKET_COOKIE_SECURE=false
export MARKET_DEBUG=false
export MARKET_REQUIRE_HTTPS=false

"${SECURE_CODING_PYTHON}" app.py
```

접속 주소는 `http://127.0.0.1:5000`이며 SQLite 데이터는 Git에서 제외된 로컬
`market.db`에 저장됩니다. 빈 DB도 Git에 올리지 않으며 애플리케이션이 최초
실행에서 필요한 스키마를 생성합니다.

### 외부 HTTPS 실습

ngrok은 로컬 실습 서버를 일시적으로 외부에 공개할 때만 사용합니다.

```sh
export MARKET_COOKIE_SECURE=true
export MARKET_DEBUG=false
export MARKET_REQUIRE_HTTPS=true
export MARKET_TRUSTED_PROXY_COUNT=1
export MARKET_TRUSTED_HOSTS="<ASSIGNED_NGROK_HOST>"

"${SECURE_CODING_PYTHON}" app.py
```

다른 터미널에서 다음 명령을 실행합니다.

```sh
ngrok http 5000
```

`MARKET_TRUSTED_HOSTS`에는 ngrok이 할당한 주소에서 `https://`와 경로를 제외한
Host만 입력합니다.

### 실제 운영 배포

현재 저장소에는 검증된 운영용 WSGI·WebSocket 서버, 중앙 Rate Limit 저장소,
운영 DB, 중앙 로그 필터링과 TLS 종료 구성이 없습니다. 따라서 `python app.py`,
빠른 실행 도구와 ngrok은 모두 교육·로컬 실습용이며 실제 운영 배포 방법으로
사용하지 않습니다. 송금 잔액도 내부 보안 실습용 데이터일 뿐 실제 현금,
은행 계좌 또는 전자지급수단과 연결되지 않습니다.

운영 배포를 추가하려면 프로덕션 서버와 리버스 프록시, HTTPS/WSS 인증서,
지속되는 `MARKET_SECRET_KEY`, `MARKET_COOKIE_SECURE=true`,
`MARKET_REQUIRE_HTTPS=true`, 정확한 신뢰 Host·프록시 수, 운영 DB·백업·중앙
Rate Limit과 로그 보호를 별도 구현하고 배포 환경에서 검증해야 합니다.

## 7. 테스트

자동 테스트, 관리자 테스트, 의존성 감사와 DB 격리 정책은
[테스트 가이드](docs/TESTING.md)에서 별도로 관리합니다. 현재 버전의 검증
결과는 [보안 변경 이력](docs/SECURITY_CHANGELOG.md)에서 확인합니다.

## 8. 데이터베이스 백업과 복구 검증

애플리케이션을 중지한 뒤 저장소 밖의 새 파일로 백업합니다. 기존 파일은
덮어쓰지 않으며 결과 파일 권한은 `600`으로 설정됩니다.

```sh
python scripts/database_backup.py backup \
  --source market.db \
  --output /private/tmp/market.backup.db
```

백업의 SQLite 무결성과 외래키를 다시 확인합니다.

```sh
python scripts/database_backup.py verify \
  --database /private/tmp/market.backup.db
```

복구 검증은 운영 DB를 덮어쓰지 않고 새로운 파일을 생성합니다.

```sh
python scripts/database_backup.py restore \
  --backup /private/tmp/market.backup.db \
  --output /private/tmp/market.restore.db
```

복구 파일 검증이 끝나도 실행 중인 `market.db`를 자동 교체하지 않습니다.
백업에는 비밀번호 해시, 신고 사유 등 민감한 데이터가 포함될 수 있으므로 Git,
공개 저장소 또는 공개 클라우드 폴더에 업로드하지 마세요.

## 9. 자주 발생하는 문제

### `ModuleNotFoundError: No module named 'flask'`

대부분 Conda 환경이 활성화되지 않았거나 환경 파일 설치가 끝나지 않은 경우입니다.

```sh
conda activate secure_coding
conda env update -f enviroments.yaml
python -m pip check
```

그래도 설치되지 않았다면 활성 환경의 Python이 맞는지 확인합니다.

```sh
which python
python -m pip --version
```

### 로그인 후 다시 로그인 페이지로 이동

로컬 `http://127.0.0.1:5000`으로 접속한다면
`MARKET_COOKIE_SECURE=false`인지 확인하고 애플리케이션을 재실행합니다. ngrok의
HTTPS 주소에서는 `MARKET_COOKIE_SECURE=true`를 사용합니다.

### `MARKET_SECRET_KEY` 오류

비밀키가 없거나 32자보다 짧으면 애플리케이션은 안전을 위해 실행을 중단합니다.
위의 “세션 비밀키” 명령으로 새로운 키를 설정한 후 다시 실행합니다.

## 참고 문서

- [ngrok macOS 설치](https://ngrok.com/download/mac-os)
- [Miniconda 설치](https://www.anaconda.com/docs/getting-started/miniconda/install)
- [Miniconda 설치 파일 및 SHA-256](https://repo.anaconda.com/miniconda/)
- [Conda 환경 생성](https://docs.conda.io/projects/conda/en/latest/commands/env/create.html)
- [Flask 설치](https://flask.palletsprojects.com/en/stable/installation/)
- [Flask-SocketIO 설치](https://flask-socketio.readthedocs.io/en/latest/intro.html#installation)
- [argon2-cffi 설치](https://argon2-cffi.readthedocs.io/en/25.1.0/installation.html)
- [pytest 시작하기](https://docs.pytest.org/en/stable/getting-started.html)
- [pip-audit](https://pypi.org/project/pip-audit/)
