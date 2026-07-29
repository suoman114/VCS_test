# 배포/실행 가이드

로컬 개발 환경이든 실제 배포 대상 서버든 공통 절차는 `backend/README.md`, `frontend/README.md`를 따른다. 이 문서는 그중 **CentOS 7처럼 오래된 운영체제**에서 겪을 수 있는 환경 문제와 해결책을 정리한다 — 실제로 사내 VCS 시험 서버가 CentOS 7 계열인 경우가 많아, 한 번 겪은 문제를 반복하지 않기 위한 기록이다.

## 표준 절차 (최신 OS 기준)

### 백엔드
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 필요 시 VCS_SSH_* 값 채움
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### 프론트엔드
```bash
cd frontend
cp .env.example .env        # VITE_API_BASE_URL 기본값(http://localhost:8000)이면 그대로 둬도 됨
npm install
npm run dev                 # http://localhost:5173
```

## CentOS 7 (glibc 2.17) 환경일 경우

CentOS 7은 2024년 기준으로도 여전히 널리 쓰이지만, glibc 2.17 / GCC 4.8.2라는 아주 오래된 베이스라인 때문에 아래 문제들을 순서대로 만나게 된다. 실제로 이 프로젝트를 CentOS 7 서버에 배포하며 확인된 문제와 해결 순서다.

### 1. 시스템 기본 Python(3.6)으로는 안 됨
`sqlalchemy>=2.0`은 Python 3.7+가 필요하다. `pyenv`로 Python 3.11을 새로 설치해야 하는데, 이때 두 가지 컴파일 문제가 연달아 발생한다.

**a) SSL 모듈 컴파일 실패** — CentOS 7 기본 OpenSSL(1.0.2)이 너무 낮음. EPEL의 `openssl11`(1.1.1) 패키지를 별도 설치해 그 경로를 알려줘야 한다.
```bash
yum install -y epel-release
yum install -y openssl11 openssl11-devel

CPPFLAGS="-I/usr/include/openssl11" \
LDFLAGS="-L/usr/lib64/openssl11 -Wl,-rpath,/usr/lib64/openssl11" \
pyenv install 3.11.9
```

**b) `greenlet`(SQLAlchemy 의존 패키지) 빌드 실패** — 시스템 기본 g++(4.8.2)가 C++11을 기본으로 지원하지 않음. `devtoolset-9`로 새 GCC를 설치해야 한다.
```bash
yum install -y centos-release-scl
yum install -y devtoolset-9-gcc devtoolset-9-gcc-c++
source /opt/rh/devtoolset-9/enable   # 이 터미널 세션에서만 유효, 새 셸이면 다시 실행

cd backend
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Node.js 18/20이 설치가 안 됨
NodeSource의 최신 Node(18/20) 패키지는 `glibc >= 2.28`을 요구한다(CentOS 7은 2.17). NodeSource는 더 이상 Node 16용 yum 저장소도 제공하지 않으므로, **공식 tar 바이너리를 직접 받아서 설치**한다(yum/rpm 의존성 체크를 완전히 우회).
```bash
cd /usr/local
curl -O https://nodejs.org/dist/v16.20.2/node-v16.20.2-linux-x64.tar.xz
tar xf node-v16.20.2-linux-x64.tar.xz

ln -sf /usr/local/node-v16.20.2-linux-x64/bin/node /usr/local/bin/node
ln -sf /usr/local/node-v16.20.2-linux-x64/bin/npm  /usr/local/bin/npm
ln -sf /usr/local/node-v16.20.2-linux-x64/bin/npx  /usr/local/bin/npx
```
Node 16은 glibc 2.17에서 동작하는 마지막 LTS 라인이다.

### 3. Vite 5 / rollup 4가 Node 16과 안 맞음
저장소의 `frontend/package.json`은 이미 아래 두 가지를 반영해 커밋되어 있다(추가 조치 불필요, 참고용 기록):
- `vite`를 5.x → `^4.5.5`로 고정 (Vite 5는 Node 18+ 요구)
- `rollup`을 devDependency에 `3.29.4`로 직접 고정 (rollup 4.x의 플랫폼별 네이티브 바이너리가 `glibc >= 2.29`를 요구해서 CentOS 7에서 `ERR_DLOPEN_FAILED`가 남). `overrides` 필드만으로는 오래된 npm(8.x)에서 제대로 적용되지 않아, 최상위 `devDependencies`에 직접 명시하는 방식으로 고정했다.

이 상태에서 `npm install && npm run dev`가 정상 동작함을 확인했다.

## 외부 접속

`npm run dev`/`uvicorn`은 기본적으로 `localhost`에만 바인딩된다. 원격 서버에서 브라우저로 접속하려면:

- **SSH 포트포워딩(권장)**: `ssh -L 5173:localhost:5173 -L 8000:localhost:8000 <user>@<서버IP>` 후 로컬 브라우저에서 `http://localhost:5173`
- 또는 `npm run dev -- --host`로 외부 노출 + 방화벽에서 5173/8000 포트 개방

## 현재 확인된 상태

- 백엔드: `alembic upgrade head`로 4개 테이블 생성 확인, `GET /api/health` 200 확인, 유닛+통합 테스트 52/52 통과
- 프론트엔드: 대시보드 로드 확인, `API 서버` 헬스체크 정상 표시
- `VCS SSH 연결` / `SIPp 실행 가능` 배지는 아직 "확인중" 고정 — 백엔드에 실제 헬스체크 로직이 없어서다(TBD, 아래 참고)

## 실 VCS 서버 연동 (2026-07-29 확인 완료)

`.env`에 아래를 채우면 실제 장비로 시험을 실행할 수 있다(호스트/계정 값 자체는 이 문서에 적지 않는다 — `.env`에만 채운다).

```bash
VCS_SSH_HOST=<VCS IP>
VCS_SSH_PORT=22
VCS_SSH_USERNAME=<계정>
VCS_SSH_PASSWORD=<비밀번호>

SIPP_EXEC_MODE=ssh
SIPP_SSH_HOST=<SIPp 전용 서버 IP>
SIPP_SSH_USERNAME=<계정>
SIPP_SSH_PASSWORD=<비밀번호>
```

나머지(vctp 재기동 명령, pcap 샘플 디렉토리, vcsm/vcmm/vcmc 로그 경로)는 `backend/app/core/config.py`에 확인된 기본값으로 이미 들어가 있다 — 배포 환경이 다르면 `.env`에서 override(`.env.example`에 주석으로 키 이름 목록 있음). VoLTE Test Case 등록 시 pcap 샘플은 `GET /api/vcs/volte-sample-files`가 VCS의 `/home/vcs/vctp/sample`을 SSH로 조회해 select box로 보여준다(VCS 연결이 안 되면 502 → 폼이 텍스트 입력으로 자동 폴백).

## 아직 남은 것 (CLAUDE.md §13 TBD)

- 실패/타임아웃 케이스 로그 샘플 — 현재는 성공 케이스만 있어 Pass 판정만 구현됨
- 대시보드 헬스체크 배지(`VCS SSH 연결`, `SIPp 실행 가능`)를 실제로 채우는 백엔드 로직
- vctp 설정 파일의 `SAMPLEFILE1` 라인 문법(공백 등) — sed 치환 로직이 vctp.log의 파싱된 출력에서 역추정한 것이라, 실 서버 최초 실행 시 검증 필요
- vctp/vctp 재기동 명령 실행 권한(sudo 필요 여부 등) 검증
