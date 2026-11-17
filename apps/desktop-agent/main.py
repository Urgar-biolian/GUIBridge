"""Local control plane: managed launch, approvals, event stream. Implementation stages S2/S4."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="GUIBridge Desktop Agent")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "stage": "skeleton"}

    return app


app = create_app()