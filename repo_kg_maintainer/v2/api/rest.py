from __future__ import annotations

from v2.api.service import GraphServiceV2, IndexRepositoryRequestV2, QueryContextRequestV2


def create_fastapi_app(service: GraphServiceV2):
    try:
        from fastapi import FastAPI, Header, HTTPException
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("FastAPI is required to run the REST server") from exc

    app = FastAPI(title="Code Mesh Graph API v2", version="2.0")

    def _key(value: str | None) -> str:
        if not value:
            raise HTTPException(status_code=401, detail="missing api key")
        return value

    @app.post("/v2/index/repository")
    def post_index_repository(payload: IndexRepositoryRequestV2, x_api_key: str | None = Header(default=None)):
        try:
            return service.post_index_repository(payload, _key(x_api_key))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v2/index/commit")
    def post_index_commit(payload: IndexRepositoryRequestV2, x_api_key: str | None = Header(default=None)):
        try:
            return service.post_index_commit(payload, _key(x_api_key))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v2/graph/{tenant}/{repo}/{sha}")
    def get_graph(tenant: str, repo: str, sha: str, x_api_key: str | None = Header(default=None)):
        try:
            return service.get_graph(tenant, repo, sha, _key(x_api_key))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v2/query/context")
    def post_query_context(payload: QueryContextRequestV2, x_api_key: str | None = Header(default=None)):
        try:
            return service.post_query_context(payload, _key(x_api_key))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v2/jobs/{job_id}")
    def get_job(job_id: str, tenant_id: str, x_api_key: str | None = Header(default=None)):
        try:
            return service.get_job(tenant_id, job_id, _key(x_api_key))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
