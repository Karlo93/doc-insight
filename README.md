# doc-insight
[![CI](https://github.com/Karlo93/doc-insight/actions/workflows/ci.yml/badge.svg)](https://github.com/Karlo93/doc-insight/actions/workflows/ci.yml)

Document insight platform, built as a Python 3.12 uv workspace.

Start local dependencies without building application images:

```sh
cp .env.example .env
make infra-up
bash scripts/smoke_infra.sh
make telemetry-up
bash scripts/smoke_infra.sh telemetry
```

See [local stack](docs/local-stack.md) for ports, profiles, encryption and Grafana.
Choose a free database port in `.env` if 5432 is occupied.
Stop with `make telemetry-down` and `make infra-down`; data volumes are retained.
