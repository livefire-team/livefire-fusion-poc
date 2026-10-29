import logging
import os

# Telemetry first: the distro must patch FastAPI before FastAPI is imported.
if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor(logger_name="orders")

from fastapi import FastAPI, Form, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402
from opentelemetry import metrics, trace  # noqa: E402

import db  # noqa: E402
from catalog import PRODUCTS  # noqa: E402
from secret_provider import SecretProvider, SecretUnavailable, build_fetch, fresh_check  # noqa: E402

log = logging.getLogger("orders")
log.setLevel(logging.INFO)
tracer = trace.get_tracer("orders")
meter = metrics.get_meter("orders")
orders_completed = meter.create_counter("orders_completed")
orders_failed = meter.create_counter("orders_failed")

app = FastAPI(title="LiveFire order service")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
secrets = SecretProvider(build_fetch(), float(os.environ.get("SECRET_REFRESH_SECONDS", "30")))
_last_good = {}   # last password the health check read, so it can still ping SQL during a fault


@app.middleware("http")
async def drill_context(request: Request, call_next):
    request.state.drill_id = request.headers.get("x-drill-id")
    if request.state.drill_id:
        trace.get_current_span().set_attribute("drill_id", request.state.drill_id)
    return await call_next(request)


def _place(sku: str, drill_id: str | None) -> str:
    product = PRODUCTS.get(sku)
    if product is None:
        raise ValueError(f"unknown sku {sku}")
    with tracer.start_as_current_span("place_order") as span:
        if drill_id:
            span.set_attribute("drill_id", drill_id)
        span.set_attribute("sku", sku)
        try:
            password = secrets.get()
            order_id = db.place_order(password, sku, product["price"], drill_id)
        except Exception as exc:
            orders_failed.add(1, {"reason": type(exc).__name__})
            log.exception("order failed", extra={"drill_id": drill_id or "", "sku": sku})
            raise
        orders_completed.add(1)
        log.info("order placed", extra={"drill_id": drill_id or "", "order_id": order_id})
        return order_id


def _confirmation(order_id: str) -> str:
    return "LF-" + order_id.replace("-", "")[:8].upper()


# ---- pages the referee walks through ----

@app.get("/")
def shop(request: Request):
    return templates.TemplateResponse(request, "shop.html", {"products": PRODUCTS.values()})


@app.get("/cart")
def cart(request: Request, sku: str):
    return templates.TemplateResponse(request, "cart.html", {"product": PRODUCTS[sku]})


@app.get("/checkout")
def checkout(request: Request, sku: str):
    return templates.TemplateResponse(request, "checkout.html", {"product": PRODUCTS[sku]})


@app.post("/checkout")
def place_order_page(request: Request, sku: str = Form(...)):
    try:
        order_id = _place(sku, request.state.drill_id)
    except Exception as exc:
        return templates.TemplateResponse(
            request, "result.html",
            {"error": f"We couldn't place your order ({type(exc).__name__}). Please try again."},
            status_code=503,
        )
    return templates.TemplateResponse(request, "result.html", {"confirmation": _confirmation(order_id)})


# ---- JSON API for the load generator ----

@app.post("/api/orders")
async def create_order(request: Request):
    body = await request.json()
    try:
        order_id = _place(body["sku"], request.state.drill_id)
    except Exception as exc:
        return JSONResponse({"error": type(exc).__name__}, status_code=503)
    return JSONResponse({"order_id": order_id, "confirmation": _confirmation(order_id)}, status_code=201)


@app.get("/api/orders/{order_id}")
def read_order(order_id: str):
    try:
        order = db.get_order(secrets.get(), order_id)
    except SecretUnavailable as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    return order or JSONResponse({"error": "not found"}, status_code=404)


# ---- health ----

@app.get("/health")
def health():
    return {"status": "up"}


@app.get("/health/dependencies")
def health_dependencies():
    keyvault, value = fresh_check()
    if value:
        _last_good["password"] = value
    sql = "unknown"
    password = value or _last_good.get("password")
    if password:
        try:
            db.ping(password)
            sql = "ok"
        except Exception:
            sql = "error"
    body = {"keyvault": keyvault, "sql": sql}
    return JSONResponse(body, status_code=200 if keyvault == "ok" and sql == "ok" else 503)
