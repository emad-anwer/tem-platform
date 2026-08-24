from fastapi import FastAPI


async def lifespan(app: FastAPI):
    # Perform any startup tasks here
    yield
    # Perform any shutdown tasks here


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def root():
        return {"message": "Hello from TEM Platform"}

    return app


app = create_app()
