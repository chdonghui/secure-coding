# 안전한 중고거래 플랫폼

Flask와 Flask-SocketIO로 만든 소규모 중고거래 학습 프로젝트입니다. 회원가입,
로그인, 마이페이지, 상품 등록·조회·수정·삭제와 내 상품 관리, 실시간 채팅 및
신고 기능을 포함합니다.

이 프로젝트는 [ugonfor/secure-coding](https://github.com/ugonfor/secure-coding)
저장소에서 가져온 기반 코드를 바탕으로 보안 취약점을 분석하고 개선하는 실습용
프로젝트입니다. 웹 애플리케이션 보안 조치의 적용 전후를 학습하고 자동 테스트로
검증하는 것을 목적으로 합니다.

교육 및 실습 목적으로만 사용하며, 현재 개발 서버와 구성 그대로 실제 서비스나
운영 환경에 배포하지 않습니다. 원본 프로젝트와 외부 패키지를 사용할 때는 각
저장소의 라이선스와 이용 조건을 별도로 확인해야 합니다.

- 현재 버전: `1.7`
- AI 작업 규칙: [AGENTS.md](AGENTS.md)
- 버전별 보안 조치: [SECURITY_CHANGELOG.md](SECURITY_CHANGELOG.md)
- 보안 현황: [SECURITY_REVIEW.md](SECURITY_REVIEW.md)
- 버전 및 커밋 규칙: [VERSIONING.md](VERSIONING.md)

## 개발 환경

- macOS
- Homebrew
- Git 및 GitHub
- Python 3.9
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

### 직접 설치가 필요한 경우

환경 파일 설치가 정상적으로 끝났다면 아래 명령은 실행할 필요가 없습니다.
패키지가 누락된 개발환경을 복구할 때만 활성화된 `secure_coding` 환경에서
사용합니다.

```sh
conda activate secure_coding
python -m pip install flask flask-socketio flask-sqlalchemy
python -m pip install argon2-cffi==25.1.0 pytest==8.4.2
python -m pip check
```

직접 설치 후에는 다른 개발자도 같은 환경을 만들 수 있도록
`enviroments.yaml`에도 해당 직접 의존성을 추가해야 합니다.

## 4. 직접 의존성

| 패키지 | 용도 | 설치·사용 출처 |
|---|---|---|
| `flask` | 웹 라우트, 템플릿, 세션 및 요청 처리 | [Flask 공식 설치 문서](https://flask.palletsprojects.com/en/stable/installation/) |
| `flask-socketio` | 실시간 채팅과 Socket.IO 서버 | [Flask-SocketIO 공식 설치 문서](https://flask-socketio.readthedocs.io/en/latest/intro.html#installation) |
| `flask-sqlalchemy` | Flask용 SQLAlchemy 연동 패키지 | 현재 환경에는 포함되지만 애플리케이션은 아직 `sqlite3`를 직접 사용 |
| `argon2-cffi==25.1.0` | 비밀번호 Argon2id 해시 및 검증 | [argon2-cffi 공식 문서](https://argon2-cffi.readthedocs.io/en/25.1.0/installation.html) |
| `pytest==8.4.2` | 회원·프로필 보안 자동 테스트 | [pytest 공식 시작 문서](https://docs.pytest.org/en/stable/getting-started.html) |

`argon2-cffi`와 `pytest`는 Version `1.1` 보안 개선 과정에서 추가했습니다.
각 패키지가 필요로 하는 하위 의존성은 pip와 Conda가 자동으로 설치하므로
애플리케이션에서 직접 사용하지 않는 하위 패키지를 개별 설치할 필요는 없습니다.

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
```

`MARKET_DEBUG=true`는 오류 정보가 노출될 수 있으므로 공개 환경에서 사용하면
안 됩니다.

`MARKET_REQUIRE_HTTPS=true`이면 평문 HTTP 요청과 평문 Socket.IO 연결을
거부합니다. HTTPS 페이지에서 실행되는 채팅 클라이언트는 같은 Origin의 WSS
연결을 사용합니다. TLS 인증서와 HTTPS 종료는 ngrok 또는 통제하는 리버스
프록시에서 제공해야 합니다.

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

채팅은 동일 Origin 연결만 허용하고 연결 시 세션 CSRF Token을 확인합니다.
메시지는 1~500자이며 브라우저의 `textContent`로 출력됩니다. 기본 전송 제한은
사용자별 10초에 5건, IP별 1분에 30건이고 동일 메시지는 5초 안에 반복할 수
없습니다.

## 6. 애플리케이션 실행

```sh
conda activate secure_coding
python app.py
```

브라우저에서 다음 주소로 접속합니다.

```text
http://127.0.0.1:5000
```

### ngrok으로 외부 HTTPS 주소 열기

애플리케이션은 `MARKET_COOKIE_SECURE=true`로 실행하고, 다른 터미널에서 다음
명령을 실행합니다.

```sh
ngrok http 5000
```

ngrok이 표시한 `https://...ngrok...` 주소로 접속합니다. 이 개발 서버와 ngrok
터널은 테스트 용도이며 운영 배포 방식으로 사용하지 않습니다.

## 7. 보안 테스트

```sh
conda activate secure_coding
python -m pytest -q
```

현재 버전에서 검증하는 보안 시나리오와 결과는
[SECURITY_CHANGELOG.md](SECURITY_CHANGELOG.md), 전체 보안 상태와 남은 작업은
[SECURITY_REVIEW.md](SECURITY_REVIEW.md)에서 확인합니다.

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
