# 관리자 계정 빠른 시작

현재 프로젝트에는 기본 관리자 아이디나 비밀번호가 없습니다. 일반 사용자와
관리자는 별도 서버가 아니라 하나의 애플리케이션을 사용하며 계정 역할만
다릅니다.

모든 명령은 GitHub에서 내려받은 저장소 루트에서 상대경로로 실행합니다.

## 1. 가장 빠른 관리자 페이지 확인

다음 한 줄로 임시 관리자·일반 사용자와 샘플 신고를 만들고 서버를 실행합니다.

```sh
./scripts/quickstart_demo.sh
```

터미널에 출력된 `quick_admin`의 무작위 임시 비밀번호로 로그인합니다.

```text
로그인: http://127.0.0.1:5000/login
관리자 페이지: http://127.0.0.1:5000/admin
```

관리자 화면에는 바로 처리할 수 있는 사용자 신고와 상품 신고가 준비됩니다.
`quick_user`는 일반 사용자 접근을 확인할 때 사용합니다. `Ctrl+C`로 종료하면
저장소 밖의 임시 DB와 두 계정이 삭제되며 기존 `market.db`는 변경되지 않습니다.

## 2. 데이터를 유지할 관리자 계정 만들기

먼저 [빠른 실행 가이드](QUICK_START.md)의 “데이터를 유지하는 로컬 실행”으로
서버를 실행하고 `http://127.0.0.1:5000/register`에서 관리자용 일반 계정을
가입합니다.

서버는 첫 번째 터미널에서 계속 실행합니다. 두 번째 터미널을 열어 저장소
루트로 이동한 뒤 다음 블록을 실행하고 가입한 사용자명을 입력합니다.

```sh
conda activate secure_coding
SECURE_CODING_PYTHON="${CONDA_PREFIX}/bin/python"

printf '관리자로 지정할 사용자명: '
IFS= read -r MARKET_ADMIN_USERNAME

"${SECURE_CODING_PYTHON}" scripts/admin_user.py \
  --database market.db \
  grant \
  --username "${MARKET_ADMIN_USERNAME}" \
  --operator "$(id -un)" \
  --reason "로컬 관리자 페이지 사용을 위해 관리자 권한을 부여합니다."

unset MARKET_ADMIN_USERNAME
```

역할 변경 시 기존 로그인 세션이 무효화됩니다. 브라우저에서 다시 로그인한 뒤
관리자 페이지에 접속합니다.

## 3. 관리자 권한 확인

```sh
conda activate secure_coding
SECURE_CODING_PYTHON="${CONDA_PREFIX}/bin/python"

"${SECURE_CODING_PYTHON}" scripts/admin_user.py \
  --database market.db \
  list
```

출력에 관리자 사용자명과 UUID가 표시되는지 확인합니다.

## 4. 관리자 페이지 기능

- 신고 사유와 처리 상태 확인
- 신고 완료 또는 반려 처리
- 불량 상품 관리 삭제
- 일반 사용자 휴면·재활성화
- 최근 관리자 처리 감사 이력 조회

일반 사용자와 관리자를 동시에 확인할 때는 일반 브라우저 프로필과 시크릿 창
또는 서로 다른 브라우저 프로필을 사용합니다.

## 5. 관리자 권한 해제

```sh
conda activate secure_coding
SECURE_CODING_PYTHON="${CONDA_PREFIX}/bin/python"

printf '관리자 권한을 해제할 사용자명: '
IFS= read -r MARKET_ADMIN_USERNAME

"${SECURE_CODING_PYTHON}" scripts/admin_user.py \
  --database market.db \
  revoke \
  --username "${MARKET_ADMIN_USERNAME}" \
  --operator "$(id -un)" \
  --reason "로컬 관리자 업무 종료에 따라 관리자 권한을 해제합니다."

unset MARKET_ADMIN_USERNAME
```

마지막 활성 관리자의 권한은 해제할 수 없습니다. 관리자 계정을 탈퇴하려면 먼저
관리자 권한을 해제해야 합니다.

## 6. 경로·권한 오류

`scripts/admin_user.py`를 찾을 수 없다는 오류는 저장소 루트가 아닌 위치에서
명령을 실행했다는 뜻입니다.

```sh
pwd
cd secure-coding
test -f scripts/admin_user.py
```

관리자 페이지에서 `403`이 표시되면 관리자 목록을 확인하고 역할 부여 전
브라우저 세션을 로그아웃한 뒤 다시 로그인합니다.

## 7. 테스트

관리자 전용 자동 테스트는 [테스트 가이드](TESTING.md#3-관리자-페이지-테스트)를
참고합니다.
