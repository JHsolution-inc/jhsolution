# JHsolution service archive

본 레포지토리는 화물운송 시장에서 시작한 스타트업 JH솔루션의 소스코드입니다.
해당 사업이 종료됨에 따라 본 프로젝트의 코드가 공개전환 되었습니다.

# 실행하기

## 로컬 실행

이 서비스를 실행하기 위해서는 `python3{,-pip,-venv}`, `postgresql`을 설치해야 합니다.
또한, [구글 oauth](https://developers.google.com/identity/protocols/oauth2),
[바로써트](https://www.barocert.com),
[자동차 정보 공공데이터 API](https://www.barocert.com/https://www.barocert.com/)
를 사용하고 있어 `.env` 파일에 API 키가 없으면 일부 기능이 동작하지 않을 수 있습니다.

1. `python3{,-venv}`, `postgresql`을 설치한 이후 python 패키지들을 설치해 주세요.
여기서는 `venv` 가상환경을 사용하는 것을 전제로 합니다.
	```bash
	python3 -m venv venv
	. venv/bin/activate
	pip install -r requirements.txt
	pip install -r test-requirements.txt
	```

2. 만약 서비스 API 키가 있다면 먼저 `.env` 파일에 추가해 주세요.

3. 그 이후 `postgresql`에서 계정과 DB를 생성하고 `.env` 파일에 아래와 같은 형태로 추가해 주세요.
방법은 postgresql 공식 문서 또는 아래의 [서비스 배포](#서비스-배포)를 참고해 주세요.
	```env
	DATABASE_URL=postgresql+psycopg2://{user}:{password}@{host}/{database}
	```

4. `.env` 파일의 세팅이 끝났다면 DB에 스키마를 생성해 주세요.
	```bash
	python -m alembic upgrade head
	```

5. 마지막으로 어플리케이션을 실행해 주세요.
	```bash
	python -m uvicorn --host 127.0.0.1 --port 8888 jhsolution.main:app
	```

## 로컬 테스트

테스트를 실행할 때는 브라우저 테스트를 위해 `playwright`용 브라우저 드라이버가 설치되어야만 합니다.
`python -m playwright install`을 통해서 설치해 주세요.

또한, DB 마이그레이션 테스트를 위해서는 테스트용 DB가 별도로 필요합니다.
`postgresql`에서 테스트용 DB를 하나 더 생성해주시고 `.env`파일의 `TEST_DATABASE_URL`에 추가해 주세요.

위에서의 준비가 끝났다면, `pytest`로 테스트를 수행할 수 있습니다.
`--no-cov`는 테스트 커버리지 확인을 하지 않을 때,
`--test-migration`은 DB 마이그레이션을 테스트할 때 붙여주세요.
```
pytest [--no-cov] [--test-migration]
```

## 서비스 배포

프로젝트의 `devops` 디렉토리에 CI/CD와 관련된 파일들이 있습니다.

단, https를 위해 `nginx/certs/{chain,key}.pem` 파일이 있어야만 동작함을 유의해 주세요.
그 다음, 도메인을 설정하기 위해 `nginx/default_server_name` 파일을 수정해 주세요.
마지막으로 `install.sh`를 실행하면 초기 인스턴스에 필요한 작업을 자동으로 진행합니다.

설치 스크립트가 종료되면 `jenkins`, `grafana`, `portainer`의 출력되는 암호는 관리자 초기 암호입니다.
이 관리전용 서비스들은 `https://jenkins.mydomain` 과 같은 형태로 접근할 수 있습니다.

설치가 끝났다면, 우선 `postgresql`에서 아래와 같이 데이터베이스를 생성해 주세요.

1. `postgresql` 접근
	```
	docker exec -tiu postgres postgres psql
	```

2. 계정 및 데이터베이스 생성 (암호는 수정해 주세요)
	```
	CREATE USER jhsol_backend WITH PASSWORD 'FAKE_PASSWORD';
	CREATE DATABASE jhsol_backend WITH OWNER jhsol_backend;
	CREATE DATABASE jhsol_backend_test WITH OWNER jhsol_backend;
	```

데이터베이스 생성이 끝났다면, 배포환경용 `.env` 파일을 생성하고 `jenkins`에 저장할 필요가 있습니다.
브라우저로 `jenkins`에 들어간 후 초기 플러그인 설치를 완료해 주세요.
설치 완료 후 pipeline job을 생성한 후, 프로젝트의 `Jenkinsfile`와 배포용 `.env` 파일을 사용하도록 설정하면 모든 설정이 끝납니다.

필요할 경우 로그를 확인하기 위해 `grafana`에 대시보드를 만들 수 있습니다.
서비스의 로그들은 `opentelemetry`를 통하여 수집되고 있으며, 관리자가 원하는 형태로 대시보드를 직접 작성할 수 있습니다.

# Troubleshooting

## `url_for`의 프로토콜이 `https'로 바뀌지 않음

`nginx`와 같은 웹서버가 프록시로써 앞단에 있을 때, `fastapi`가 이를 확인하기 위해서는 프록시 헤더가 설정되어야 합니다.
우선 프록시 서버에서는 아래와 같은 추가 헤더를 붙여야 합니다.
```
Host ${domain_name}
X-Forwarded-For ${remote_address}
X-Forwarded-Proto https
```

또는, `/etc/nginx/proxy_params`를 이용하여도 좋습니다.
다만, 프록시가 둘 이상일때, `X-Forwarded-Proto https`를 덮어써야 할 수도 있습니다.

그 다음, `fastapi`에서 프록시 헤더를 인식하기 위하여 실행시 아래 옵션이 추가되어야 합니다.
```
--proxy-headers --forwarded-allow-ips ${proxy_server_ips}
```

## nginx에서 502 에러와 함께 에러 로그에서 `upstream sent too big header ...`가 발견됨

헤더 사이즈가 버퍼에 비해 크기가 커서 발생하는 문제로, 아래 옵션을 추가하는 것을 시도할 수 있습니다.
```
fastcgi_buffers         16  16k;
fastcgi_buffer_size         32k;
proxy_buffer_size          128k;
proxy_buffers            4 256k;
proxy_busy_buffers_size    256k;
```

출처: https://stackoverflow.com/a/43093634/7579126

# 창립 멤버

* CEO: 명재훈
* CTO: 이종휘
