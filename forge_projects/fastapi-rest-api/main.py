from fastapi import FastAPI

app = FastAPI(title="FastAPI REST API", version="0.1.0")


@app.get("/", tags=["root"])
async def read_root() -> dict:
    return {"message": "Welcome to the FastAPI REST API"}


@app.get("/items/{item_id}", tags=["items"])
async def read_item(item_id: int, q: str | None = None) -> dict:
    return {"item_id": item_id, "q": q}
