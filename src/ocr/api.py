"""
API HTTP para rodar o OCR (OCRia-nano-1 via LiteParse) em arquivos enviados.

Rodar:
    uv run ocr
    (ou: uv run uvicorn ocr.api:app --reload)

Exemplo:
    curl -X POST http://localhost:8000/ocr \
         -F "arquivos=@documento.pdf" \
         -F "arquivos=@foto.jpg" \
         -F "formato=markdown"
"""

import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

Formato = Literal["markdown", "text", "json"]

EXTENSOES = {
    ".pdf",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".odp", ".ods", ".rtf",
}


@lru_cache
def obter_parser(formato: Formato):
    from liteparse import LiteParse

    return LiteParse(ocr_backend="ocria-nano", output_format=formato)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from liteparse import models

    models.pull("ocria-nano")  # baixa os modelos só na primeira vez
    yield


app = FastAPI(title="OCR", lifespan=lifespan)

PAGINA = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
def pagina():
    return FileResponse(PAGINA)


class ResultadoArquivo(BaseModel):
    arquivo: str
    status: Literal["ok", "erro"]
    segundos: float
    texto: str | None = None
    erro: str | None = None


class OcrResponse(BaseModel):
    total: int
    ok: int
    erros: int
    segundos: float
    resultados: list[ResultadoArquivo]


# Endpoint síncrono (def): o FastAPI roda em threadpool, sem travar o event loop.
@app.post("/ocr", response_model=OcrResponse)
def ocr_arquivos(
    arquivos: Annotated[list[UploadFile], File(description="Um ou mais arquivos")],
    formato: Annotated[Formato, Form()] = "markdown",
):
    parser = obter_parser(formato)
    resultados: list[ResultadoArquivo] = []
    t_total = time.perf_counter()

    # Os arquivos enviados ficam numa pasta temporária, apagada ao final.
    with tempfile.TemporaryDirectory(prefix="ocr_") as tmp:
        for i, up in enumerate(arquivos):
            nome = up.filename or f"arquivo_{i + 1}"
            ext = Path(nome).suffix.lower()
            t0 = time.perf_counter()

            if ext not in EXTENSOES:
                resultados.append(
                    ResultadoArquivo(arquivo=nome, status="erro", segundos=0, erro=f"Tipo de arquivo não suportado: {ext or '(sem extensão)'}")
                )
                continue

            # Nome interno seguro (o nome original pode conter caminhos).
            destino = Path(tmp) / f"{i}{ext}"
            with destino.open("wb") as f:
                shutil.copyfileobj(up.file, f)

            try:
                texto = parser.parse(str(destino)).text
                resultados.append(
                    ResultadoArquivo(arquivo=nome, status="ok", segundos=round(time.perf_counter() - t0, 2), texto=texto)
                )
            except Exception as e:
                resultados.append(
                    ResultadoArquivo(arquivo=nome, status="erro", segundos=round(time.perf_counter() - t0, 2), erro=str(e))
                )

    ok = sum(r.status == "ok" for r in resultados)
    return OcrResponse(
        total=len(resultados),
        ok=ok,
        erros=len(resultados) - ok,
        segundos=round(time.perf_counter() - t_total, 2),
        resultados=resultados,
    )


def main():
    import uvicorn

    uvicorn.run("ocr.api:app", host="127.0.0.1", port=8000)
