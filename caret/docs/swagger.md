# Swagger / API 문서 접근

- 게이트웨이 서버는 `any-llm-gateway serve` 로 실행한다. 기본 포트는 `config.yml`의 `port` (기본 8000).
- `server.py` 설정:
  - `swagger_ui_parameters={"persistAuthorization": True}`로 Authorize 입력을 유지한다.
  - `CORSMiddleware`는 `*` 오리진/헤더/메서드를 허용한다.
- 루트(`/`) 접속 시 `/docs`로 리디렉트한다.

## `server.py` 진입점

- `create_app(config: GatewayConfig)`는 `init_db()`로 데이터베이스를 초기화하고 `set_config()`을 통해 전역 구성에 접근할 수 있게 한다.
- `initialize_pricing_from_config()`으로 `ModelPricing`을 `config.yml`에서 바로 채운 다음 FastAPI 애플리케이션을 생성한다.
- `CORSMiddleware`, `/docs` 리디렉트, `chat`, `auth`, `users`, `budgets`, `pricing`, `profile`, `keys`, `health` 등 모든 라우터를 포함한다.
- `any-llm-gateway serve` 커맨드는 내부적으로 이 `create_app()`을 호출하므로 `server.py`를 직접 편집하면 실행 흐름을 변경할 수 있다.

## 실행 예시

```bash
cd caret-new-router
any-llm-gateway serve \
  --config ./config.yml \
  --host 0.0.0.0 \
  --port 8000
```

## 인증 설정

- 모든 보호 엔드포인트는 `X-AnyLLM-Key: Bearer <token>` 헤더가 필요하다.
- Swagger UI에서 우측 상단 **Authorize** 클릭 → `Bearer <master/API/JWT 토큰>` 입력 → 요청 시 자동으로 헤더가 붙는다.

## 리디렉션/프런트엔드 연동

- `GatewayConfig.auth_base_url`(기본 `http://localhost:4001`)을 사용해 `/v1/auth/authorize` 리디렉트 링크를 구성한다.
- `config.yml` 또는 환경변수 `GATEWAY_AUTH_BASE_URL`로 프런트엔드 Origin에 맞춰 설정한다.

```yaml
# config.yml 예시 (발췌)
gateway:
  host: 0.0.0.0
  port: 8000
  auth_base_url: https://app.caret.team   # authorize 리디렉트 베이스
  master_key: ${GATEWAY_MASTER_KEY}
  database_url: postgresql://...
```

## 문서 페이지

- OpenAPI/Swagger: `http://<host>:<port>/docs`
- Redoc: `http://<host>:<port>/redoc`
