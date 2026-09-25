from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from twirl.auth.deps import ShopContext, require_shop
from twirl.web.templating import render

router = APIRouter()


@router.get("/shop", response_class=HTMLResponse)
def today(request: Request, ctx: ShopContext = Depends(require_shop)):
    return render(request, "shop/today.html", {"ctx": ctx})
