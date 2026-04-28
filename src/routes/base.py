from fastapi import FastAPI, APIRouter, Depends
import os
from helpers.confg import get_settings , Settings

base_router = APIRouter(
    prefix="/api/v1",  #This prefix will be added to all routes in this router
    tags=["api_v1"], #This tag is used for grouping routes in the documentation
)


@base_router.get("/")
async def welcome(app_settings: Settings = Depends(get_settings)):
    #app_name = os.getenv('APP_NAME')
    app_name = app_settings.APP_NAME
    #app_version = os.getenv('APP_VERSION')
    app_version = app_settings.APP_VERSION
    return {
        "message": f"Welcome to {app_name} version {app_version}!!"
        }
