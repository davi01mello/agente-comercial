"""Ponto de entrada. Rodar com:  uvicorn app.main:app --reload

As tabelas do banco são criadas e atualizadas pelas migrações: rode `alembic upgrade head` antes.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app import llm
from app.schemas import ChatIn, ChatOut

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="Cérebro Comercial CITi")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"titulo": "Cérebro Comercial CITi"})


@app.post("/chat", response_model=ChatOut)
def chat(dados: ChatIn):
    """Consultor: recebe a pergunta + o histórico e devolve a resposta citando a base."""
    historico = [h.model_dump() for h in dados.historico]
    try:
        resposta = llm.consultar(dados.mensagem, historico)
    except llm.ErroLLM as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return ChatOut(resposta=resposta)

# TODO(T3): POST /insights e GET /insights
# TODO(T4): POST /chat/registrar  (curador)
# TODO(T6): GET /playbook e aprovar/rejeitar
# TODO(T7): consultor sobre o playbook real (hoje o POST /chat usa a base de exemplo)