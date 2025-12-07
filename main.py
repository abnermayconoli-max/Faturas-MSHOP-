from fastapi import FastAPI

app = FastAPI(
    title="Sistema de Faturas Transportadoras",
    version="0.1.0",
)

@app.get("/")
def read_root():
    return {"mensagem": "API de Faturas no ar a partir do Render!"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
