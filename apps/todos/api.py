from typing import Literal

from ninja import Field, Router, Schema
from ninja.errors import HttpError

router = Router(tags=["Todos"])


class TodoIn(Schema):
    title: str = Field(
        ...,
        min_length=3,
        description="Task title",
        examples=["Review pull requests"],
    )
    priority: Literal["low", "normal", "high"] = Field(
        default="normal",
        description="Task priority",
        examples=["high"],
    )


class TodoOut(Schema):
    id: str = Field(..., description="Todo ID", examples=["todo_1"])
    title: str = Field(..., description="Task title", examples=["Review pull requests"])
    priority: Literal["low", "normal", "high"] = Field(
        ...,
        description="Task priority",
    )
    done: bool = Field(default=False, description="Completion status", examples=[False])


# In-memory store mirroring gota/examples/todos/todos.go
_TODOS: list[dict] = [
    {
        "id": "todo_1",
        "title": "Update README badges",
        "priority": "low",
        "done": True,
    },
    {
        "id": "todo_2",
        "title": "Review pull requests",
        "priority": "normal",
        "done": False,
    },
    {
        "id": "todo_3",
        "title": "Deploy release v1.0",
        "priority": "high",
        "done": False,
    },
]


@router.get(
    "",
    response=list[TodoOut],
    summary="List all todos",
    description="Returns all todo items in the store.",
)
def list_todos(request):
    return _TODOS


@router.get(
    "/{id}",
    response=TodoOut,
    summary="Get todo by ID",
    description="Retrieves a single todo item by its unique identifier.",
)
def get_todo(request, id: str):
    for item in _TODOS:
        if item["id"] == id:
            return item
    raise HttpError(404, "Todo not found")


@router.post(
    "",
    response={201: TodoOut},
    summary="Create a new todo",
    description="Validates the input payload and creates a new todo item.",
)
def create_todo(request, payload: TodoIn):
    new_id = f"todo_{len(_TODOS) + 1}"
    item = {
        "id": new_id,
        "title": payload.title,
        "priority": payload.priority,
        "done": False,
    }
    _TODOS.append(item)
    return 201, item
