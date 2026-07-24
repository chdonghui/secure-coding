# 빠른 실행 가이드

이 문서는 macOS와 `zsh`를 기준으로 합니다. 경로를 다른 컴퓨터에서도 그대로
사용할 수 있도록 저장소 내부 파일은 모두 상대경로로 실행합니다.

## 1. 저장소와 환경 준비

처음 내려받는 경우:

```sh
git clone https://github.com/chdonghui/secure-coding
cd secure-coding
conda env create -f enviroments.yaml
```

이미 내려받은 저장소라면 해당 저장소 루트로 이동하고 환경을 갱신합니다.

```sh
cd secure-coding
conda env update -n secure_coding -f enviroments.yaml
```

`scripts`, `templates`, `tests` 디렉터리가 보이는 저장소 루트에서 아래 명령을
실행해야 합니다.

## 2. 테스트 계정이 포함된 자동 실행

가장 빠른 방법은 다음 한 줄입니다.

```sh
./scripts/quickstart_demo.sh
```

이 명령은 다음 작업을 자동으로 수행합니다.

- Conda 설치 위치에서 `secure_coding` 환경 Python 선택
- 저장소 밖 운영체제 임시 디렉터리에 별도 DB 생성
- 무작위 비밀번호를 사용하는 관리자 `quick_admin`과 일반 사용자
  `user1`, `user2` 생성
- 두 일반 사용자에게 각각 100,000원의 학습용 송금 잔액 생성
- 두 일반 사용자가 판매하는 `사과 한 상자`, `바나나 한 송이` 상품 생성
- 관리자 화면 확인용 사용자 신고와 사과 상품 신고 생성
- `http://127.0.0.1:5000`에서 로컬 서버 실행

터미널에 표시된 임시 계정과 비밀번호로 로그인합니다.

```text
일반 로그인: http://127.0.0.1:5000/login
관리자 페이지: http://127.0.0.1:5000/admin
송금 페이지: http://127.0.0.1:5000/transfers
```

서버를 `Ctrl+C`로 종료하면 임시 DB와 테스트 계정이 삭제됩니다. 저장소의
`market.db`는 읽거나 변경하지 않습니다.

### 가장 간단한 송금 테스트

1. 터미널에 출력된 `user1` 계정으로 로그인합니다.
2. 상단 `송금` 메뉴를 누릅니다.
3. 받는 사용자로 `user2`를 선택합니다.
4. 금액과 `user1`의 현재 비밀번호를 입력하고 `송금하기`를 누릅니다.
5. `user2`로 다시 로그인하면 반대 방향 송금도 할 수 있습니다.

상품 구매를 확인하려면 상품 목록에서 `사과 한 상자` 또는 `바나나 한 송이`를
열고 현재 비밀번호를 입력해 구매합니다. 구매 후 상단 `주문 내역`에서 구매자와
판매자 양쪽의 `결제 완료` 상태를 확인할 수 있습니다.

두 일반 사용자 계정에는 각각 100,000원의 학습용 잔액이 준비됩니다. 실제
현금이나 계좌 잔액은 이동하지 않으며 토스페이먼츠와도 연결되지 않습니다.

다른 포트를 사용하려면 다음과 같이 실행합니다.

```sh
./scripts/quickstart_demo.sh --port 5050
```

## 3. 일반 사용자와 관리자를 동시에 확인

서버는 하나만 실행합니다. 세션 쿠키가 섞이지 않도록 브라우저를 분리합니다.

- 일반 브라우저 창 또는 브라우저 프로필: `user1`
- 시크릿 창 또는 다른 브라우저 프로필: `quick_admin`

같은 브라우저 프로필의 여러 탭은 로그인 세션을 공유하므로 서로 다른 계정을
동시에 사용할 수 없습니다.

## 4. 데이터를 유지하는 로컬 실행

임시 계정이 아닌 직접 만든 계정과 데이터를 유지하려면 다음 블록을 실행합니다.

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

이 실행은 Git에서 제외된 로컬 `market.db`를 사용합니다. DB 파일이 없으면
애플리케이션이 최신 빈 스키마를 자동으로 생성합니다.

- 일반 사용자: `/register`에서 가입한 뒤 로그인
- 관리자: [관리자 계정 빠른 시작](ADMIN_QUICK_START.md)에 따라 역할 부여

## 5. 경로 오류 해결

다음과 같은 오류는 저장소 루트가 아닌 위치에서 상대경로 명령을 실행했을 때
발생합니다.

```text
can't open file '.../scripts/admin_user.py'
```

현재 위치를 확인하고 저장소 루트로 이동합니다.

```sh
pwd
cd secure-coding
test -f scripts/admin_user.py
```

마지막 명령이 오류 없이 끝나면 상대경로를 사용할 수 있는 위치입니다. 저장소를
다른 이름이나 위치에 복제했다면 실제 복제 디렉터리로 이동합니다.

## 6. 테스트

자동 테스트와 DB 격리 확인 방법은 [테스트 가이드](TESTING.md)를 참고합니다.
