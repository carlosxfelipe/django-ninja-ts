"""A small API exercising most generator features (mirrors gota/examples/todos)."""

from typing import Literal

import ninja_ts
from ninja import Field, File, Form, NinjaAPI, Query, Router, Schema
from ninja.files import UploadedFile

Priority = Literal["low", "normal", "high"]


class TodoIn(Schema):
    title: str = Field(
        ..., min_length=3, description="Task title", examples=["Review pull requests"]
    )
    priority: Priority = Field(default="normal", description="Task priority")
    notes: str | None = None


class TodoOut(Schema):
    id: str = Field(..., description="Todo ID", examples=["todo_1"])
    title: str
    priority: Priority
    done: bool = False
    notes: str | None = None


class TodoFilters(Schema):
    limit: int = 10
    q: str | None = None


class Message(Schema):
    message: str


router = Router(tags=["Todos"])


@router.get("", response=list[TodoOut], summary="List all todos")
def list_todos(request, filters: Query[TodoFilters]):
    return []


@router.get("/{id}", response=TodoOut, summary="Get todo by ID")
def get_todo(request, id: str):
    return {"id": id, "title": "x", "priority": "low"}


@router.post("", response={201: TodoOut}, summary="Create a new todo")
def create_todo(request, payload: TodoIn):
    return 201, {"id": "todo_1", **payload.dict()}


@router.delete("/{id}", response={204: None}, summary="Delete todo", deprecated=True)
def delete_todo(request, id: int):
    return 204, None


@router.post("/{id}/attachments", response=Message)
def upload(request, id: str, file: File[UploadedFile], caption: Form[str]):
    return {"message": "ok"}


@router.get("/search/required", response=list[TodoOut])
def search(request, term: str):
    return []


api = NinjaAPI(title="Sample API", version="2.0.0", urls_namespace="sample")
api.add_router("/todos", router)


@api.get("/health")
def health(request):
    return {"status": "ok"}


ninja_ts.install(api)
